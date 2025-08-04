import os
import uuid
import json
from datetime import datetime, timezone
from typing import Any, Optional, Dict, List

from core.database import initialize_db, get_db_client
from utils.context_manager import todo_id_var, proc_id_var
from utils.logger import handle_error, log
from crewai.utilities.events import CrewAIEventsBus
from crewai.utilities.events.task_events import TaskStartedEvent, TaskCompletedEvent
from crewai.utilities.events import ToolUsageStartedEvent, ToolUsageFinishedEvent

class CrewAIEventLogger:
    """CrewAI 이벤트 로거 - Supabase 전용"""
    
    # =============================================================================
    # Initialization
    # =============================================================================
    def __init__(self):
        initialize_db()
        self.supabase = get_db_client()
        log("CrewAIEventLogger 초기화 완료")
    
    # =============================================================================
    # Job ID Generation
    # =============================================================================
    def _generate_job_id(self, event_obj: Any, source: Any = None) -> str:
        """이벤트 객체에서 Job ID 생성"""
        if hasattr(event_obj, 'task') and hasattr(event_obj.task, 'id'):
            return str(event_obj.task.id)
        if source and hasattr(source, 'task') and hasattr(source.task, 'id'):
            return str(source.task.id)
        return 'unknown'
    
    # =============================================================================
    # Record Creation
    # =============================================================================
    def _create_event_record(self, event_type: str, data: Dict[str, Any], job_id: str,
                             crew_type: str, todo_id: Optional[str], proc_inst_id: Optional[str]) -> Dict[str, Any]:
        """이벤트 레코드 생성"""
        return {
            "id": str(uuid.uuid4()),
            "job_id": job_id,
            "todo_id": todo_id,
            "proc_inst_id": proc_inst_id,
            "event_type": event_type,
            "crew_type": crew_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    # =============================================================================
    # Parsing Helpers
    # =============================================================================
    def _parse_json_text(self, text: str) -> Any:
        """JSON 문자열을 객체로 파싱하거나 원본 반환"""
        try:
            return json.loads(text)
        except:
            return text

    def _parse_output(self, output: Any) -> Any:
        """output 또는 raw 텍스트를 파싱해 반환"""
        if not output:
            return ""
        text = getattr(output, 'raw', None) or (output if isinstance(output, str) else "")
        return self._parse_json_text(text)

    def _parse_tool_args(self, args_text: str) -> Optional[str]:
        """tool_args에서 query 키 추출"""
        try:
            args = json.loads(args_text or '{}')
            return args.get('query')
        except:
            return None

    # =============================================================================
    # Formatting Helpers
    # =============================================================================
    def _format_plans_md(self, plans: List[Dict[str, Any]]) -> str:
        """list_of_plans_per_task 형식을 Markdown 문자열로 변환"""
        lines = []
        for idx, item in enumerate(plans, 1):
            task = item.get('task', '')
            plan = item.get('plan', '')
            lines.append(f'## {idx}. {task}')
            lines.append('')
            
            # plan이 리스트인 경우와 문자열인 경우를 모두 처리
            if isinstance(plan, list):
                for line in plan:
                    lines.append(str(line))
            elif isinstance(plan, str):
                for line in plan.split('\n'):
                    lines.append(line)
            else:
                lines.append(str(plan))
            lines.append('')
        return '\n'.join(lines).strip()
    
    # =============================================================================
    # Data Extraction
    # =============================================================================
    def _extract_event_data(self, event_obj: Any, source: Any = None) -> Dict[str, Any]:
        """이벤트 타입별 데이터 추출"""
        etype = event_obj.type
        if etype == 'task_started':
            agent = event_obj.task.agent
            return {
                'role': getattr(agent, 'role', 'Unknown'),
                'goal': getattr(agent, 'goal', 'Unknown'),
                'agent_profile': getattr(agent, 'profile', None) or '/images/chat-icon.png',
                'name': getattr(agent, 'name', 'Unknown'),
            }
        if etype == 'task_completed':
            result = self._parse_output(getattr(event_obj, 'output', None))
            if isinstance(result, dict) and 'list_of_plans_per_task' in result:
                md = self._format_plans_md(result['list_of_plans_per_task'])
                return {'final_result': md}
            return {'final_result': result}
        if etype.startswith('tool_'):
            return {
                'tool_name': getattr(event_obj, 'tool_name', None),
                'query': self._parse_tool_args(getattr(event_obj, 'tool_args', ''))
            }
        return {'info': f'Event type: {etype}'}
    
    # =============================================================================
    # Event Saving
    # =============================================================================
    def _save_event(self, record: Dict[str, Any]) -> None:
        """Supabase에 이벤트 레코드 저장"""
        try:
            payload = json.loads(json.dumps(record, default=str))
            self.supabase.table('events').insert(payload).execute()
        except Exception as e:
            handle_error('Supabase저장', e)
   
    # =============================================================================
    # Event Handling
    # =============================================================================
    def on_event(self, event_obj: Any, source: Any = None) -> None:
        """이벤트 수신부터 DB 저장까지 처리"""
        etype = event_obj.type
        if etype not in ("task_started", "task_completed", "tool_usage_started", "tool_usage_finished"):
            return
        try:
            job_id = self._generate_job_id(event_obj, source)
            data = self._extract_event_data(event_obj, source)
            rec = self._create_event_record(etype, data, job_id, 'action', todo_id_var.get(), proc_id_var.get())
            self._save_event(rec)
            log(f"[{etype}] [{job_id[:8]}] 저장 완료")
        except Exception as e:
            handle_error('이벤트처리', e)

    def emit_event(self, event_type: str, data: Dict[str, Any], job_id: Optional[str] = None,
                   crew_type: Optional[str] = None, todo_id: Optional[str] = None, proc_inst_id: Optional[str] = None) -> None:
        """수동 커스텀 이벤트 발행"""
        try:
            jid = job_id or event_type
            ctype = crew_type or "action"
            rec = self._create_event_record(event_type, data, jid, ctype, todo_id, proc_inst_id)
            self._save_event(rec)
            log(f"[{event_type}] → Supabase 저장 완료")
        except Exception as e:
            handle_error("커스텀이벤트발행", e)

# =============================================================================
# Config Manager
# =============================================================================
class CrewConfigManager:
    """글로벌 CrewAI 이벤트 리스너 등록 매니저"""
    _registered = False

    def __init__(self) -> None:
        # 로거 초기화
        self.logger = CrewAIEventLogger()
        # 한번만 리스너 등록
        if not CrewConfigManager._registered:
            bus = CrewAIEventsBus()
            for evt in (TaskStartedEvent, TaskCompletedEvent, ToolUsageStartedEvent, ToolUsageFinishedEvent):
                bus.on(evt)(lambda source, event, logger=self.logger: logger.on_event(event, source))
            CrewConfigManager._registered = True
            log("CrewAI event listeners 등록 완료") 