import os
import uuid
import json
from datetime import datetime, timezone
from typing import Any, Optional, Dict

from core.database import initialize_db, get_db_client
from utils.context_manager import todo_id_var, proc_id_var
from utils.logger import handle_error, log
from crewai.utilities.events import CrewAIEventsBus
from crewai.utilities.events.task_events import TaskStartedEvent, TaskCompletedEvent
from crewai.utilities.events import ToolUsageStartedEvent, ToolUsageFinishedEvent

class CrewAIEventLogger:
    """간단한 CrewAI 이벤트 로거 - Supabase 전용"""
    def __init__(self):
        initialize_db()
        self.supabase = get_db_client()
        log("CrewAIEventLogger 초기화 완료")

    def _generate_job_id(self, event_obj: Any, source: Any = None) -> str:
        """이벤트 객체에서 Job ID 생성"""
        if hasattr(event_obj, 'task') and hasattr(event_obj.task, 'id'):
            return str(event_obj.task.id)
        if source and hasattr(source, 'task') and hasattr(source.task, 'id'):
            return str(source.task.id)
        return 'unknown'

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

    # ============================================================================
    # 이벤트 데이터 추출
    # ============================================================================
    def _extract_event_data(self, event_obj: Any, source: Any = None) -> Dict[str, Any]:
        """이벤트 데이터 추출"""
        etype = event_obj.type
        try:
            if etype == "task_started":
                return self._extract_task_started_data(event_obj)
            elif etype == "task_completed":
                return self._extract_task_completed_data(event_obj)
            elif etype.startswith("tool_"):
                return self._extract_tool_data(event_obj)
            else:
                return {"info": f"Event type: {etype}"}
        except Exception as e:
            handle_error("데이터추출", e)
            return {"error": f"데이터 추출 실패: {e}"}

    def _extract_task_started_data(self, event_obj: Any) -> Dict[str, Any]:
        """Task 시작 이벤트 데이터 추출"""
        agent = event_obj.task.agent
        return {
            "role": getattr(agent, 'role', 'Unknown'),
            "goal": getattr(agent, 'goal', 'Unknown'),
            "agent_profile": getattr(agent, 'profile', None) or "/images/chat-icon.png",
            "name": getattr(agent, 'name', 'Unknown'),
        }

    def _extract_task_completed_data(self, event_obj: Any) -> Dict[str, Any]:
        """Task 완료 이벤트 데이터 추출"""
        final_output = getattr(event_obj, 'output', None)
        
        # Planning 결과를 사용자 친화적으로 변환
        if final_output is not None:
            formatted_result = self._format_planning_result(final_output)
            return {"final_result": formatted_result}
        
        return {"final_result": ""}

    def _format_planning_result(self, result: Any) -> str:
        """Planning 결과를 사용자 친화적인 형태로 변환"""
        try:
            # 문자열인 경우 그대로 반환
            if isinstance(result, str):
                return result
            
            # PlanPerTask 객체나 유사한 planning 객체인지 확인
            result_str = str(result)
            if "PlanPerTask" in result_str or "list_of_plans_per_task" in result_str:
                return self._format_plan_per_task(result_str)
            
            # JSON 직렬화 가능한 객체인 경우
            if hasattr(result, '__dict__'):
                try:
                    return json.dumps(result.__dict__, ensure_ascii=False, indent=2)
                except:
                    pass
            
            # 리스트인 경우
            if isinstance(result, list):
                formatted_items = []
                for i, item in enumerate(result, 1):
                    if hasattr(item, '__dict__'):
                        formatted_items.append(f"{i}. {self._format_single_plan_item(item)}")
                    else:
                        formatted_items.append(f"{i}. {str(item)}")
                return "\n".join(formatted_items)
            
            # 기타 경우 문자열로 변환
            return str(result)
            
        except Exception as e:
            handle_error("Planning결과포맷팅", e)
            return str(result)
    
    def _format_plan_per_task(self, plan_str: str) -> str:
        """PlanPerTask 형태의 문자열을 예쁜 문서 형태로 변환 (plan 값만 추출)"""
        try:
            import re
            
            # PlanPerTask(task='...', plan='...') 패턴 매칭
            pattern = r"PlanPerTask\(task='([^']+)',\s*plan='([^']+)'\)"
            matches = re.findall(pattern, plan_str, re.DOTALL)
            
            if matches:
                # plan 값들만 추출하여 예쁜 문서 형태로 구성
                document = "# 📋 작업 실행 계획\n\n"
                
                for i, (task, plan) in enumerate(matches, 1):
                    document += f"## {i}. {task}\n\n"
                    
                    # plan 내용을 단계별로 정리
                    plan_lines = plan.split('. ')
                    for j, line in enumerate(plan_lines, 1):
                        if line.strip():
                            # 숫자로 시작하는 경우 그대로, 아니면 번호 추가
                            if re.match(r'^\d+\.', line.strip()):
                                document += f"   {line.strip()}\n"
                            else:
                                document += f"   {j}. {line.strip()}\n"
                    
                    document += "\n"
                
                return document.strip()
            
            # list_of_plans_per_task= 형태 처리
            if "list_of_plans_per_task=" in plan_str:
                content = plan_str.split("list_of_plans_per_task=", 1)[1]
                return self._extract_plan_content(content)
            
            return plan_str
            
        except Exception as e:
            handle_error("PlanPerTask포맷팅", e)
            return plan_str
    
    def _format_single_plan_item(self, item: Any) -> str:
        """개별 plan 아이템을 포맷팅"""
        if hasattr(item, 'task') and hasattr(item, 'plan'):
            return f"**{item.task}**\n{item.plan}"
        elif hasattr(item, '__dict__'):
            return json.dumps(item.__dict__, ensure_ascii=False, indent=2)
        else:
            return str(item)
    
    def _extract_plan_content(self, content: str) -> str:
        """계획 내용을 추출하여 읽기 쉽게 포맷팅"""
        try:
            # 괄호 안의 내용 추출
            if content.startswith('[') and ']' in content:
                # 리스트 형태 처리
                list_content = content[1:content.rfind(']')]
                
                # PlanPerTask 객체들을 분리
                plan_items = []
                current_item = ""
                bracket_count = 0
                
                for char in list_content:
                    current_item += char
                    if char == '(':
                        bracket_count += 1
                    elif char == ')':
                        bracket_count -= 1
                        if bracket_count == 0 and 'PlanPerTask' in current_item:
                            plan_items.append(current_item.strip())
                            current_item = ""
                
                # 각 아이템을 포맷팅
                formatted_items = []
                for i, item in enumerate(plan_items, 1):
                    formatted_item = self._format_plan_per_task(item)
                    if formatted_item != item:  # 포맷팅이 성공한 경우
                        formatted_items.append(f"### 계획 {i}\n{formatted_item}")
                    else:
                        formatted_items.append(f"### 계획 {i}\n{item}")
                
                return "\n\n".join(formatted_items)
            
            return content
            
        except Exception as e:
            handle_error("계획내용추출", e)
            return content

    def _extract_tool_data(self, event_obj: Any) -> Dict[str, Any]:
        """Tool 사용 이벤트 데이터 추출"""
        tool_name = getattr(event_obj, 'tool_name', None)
        tool_args = getattr(event_obj, 'tool_args', None)
        query = None
        if tool_args:
            try:
                args = json.loads(tool_args)
                query = args.get('query')
            except Exception:
                query = None
        return {"tool_name": tool_name, "query": query}

    # ============================================================================
    # 데이터 직렬화 및 래핑
    # ============================================================================
    def _safe_serialize_data(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """이벤트 데이터 안전 직렬화"""
        safe: Dict[str, Any] = {}
        for key, val in event_data.items():
            try:
                if hasattr(val, 'raw'):
                    safe[key] = str(val.raw)
                elif hasattr(val, '__dict__') and not isinstance(val, (str, int, float, bool, type(None))):
                    safe[key] = str(val)
                else:
                    safe[key] = val
            except Exception as e:
                handle_error("직렬화실패", e)
                safe[key] = f"[직렬화 실패: {type(val).__name__}]"
        return safe

    # ============================================================================
    # 데이터베이스 저장
    # ============================================================================
    def _save_to_supabase(self, event_record: Dict[str, Any]) -> None:
        """Supabase에 이벤트 레코드 저장"""
        try:
            payload = json.loads(json.dumps(event_record, default=str))
            self.supabase.table("events").insert(payload).execute()
        except Exception as e:
            handle_error("Supabase저장", e)

    # ============================================================================
    # 메인 이벤트 처리
    # ============================================================================
    def on_event(self, event_obj: Any, source: Any = None) -> None:
        """CrewAI 이벤트 자동 처리"""
        etype = event_obj.type
        if etype not in ("task_started", "task_completed", "tool_usage_started", "tool_usage_finished"):
            return
        try:
            job_id = self._generate_job_id(event_obj, source)
            data = self._extract_event_data(event_obj, source)
            safe_data = self._safe_serialize_data(data)
            todo_id = todo_id_var.get()
            proc_inst_id = proc_id_var.get()
            rec = self._create_event_record(etype, safe_data, job_id, "action", todo_id, proc_inst_id)
            self._save_to_supabase(rec)
            log(f"[{etype}] [{job_id[:8]}] → Supabase 저장 완료")
        except Exception as e:
            handle_error("이벤트처리", e)

    def emit_event(self, event_type: str, data: Dict[str, Any], job_id: Optional[str] = None,
                   crew_type: Optional[str] = None, todo_id: Optional[str] = None, proc_inst_id: Optional[str] = None) -> None:
        """수동 커스텀 이벤트 발행"""
        try:
            jid = job_id or event_type
            ctype = crew_type or "action"
            rec = self._create_event_record(event_type, data, jid, ctype, todo_id, proc_inst_id)
            self._save_to_supabase(rec)
            log(f"[{event_type}] → Supabase 저장 완료")
        except Exception as e:
            handle_error("커스텀이벤트발행", e)

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