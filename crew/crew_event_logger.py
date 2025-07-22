import os
import uuid
import json
import traceback
from datetime import datetime, timezone
from typing import Any, Optional, Dict
import logging

from database import initialize_db, get_db_client
from context_manager import todo_id_var, proc_id_var
from crewai.utilities.events import CrewAIEventsBus
from crewai.utilities.events.task_events import TaskStartedEvent, TaskCompletedEvent
from crewai.utilities.events import ToolUsageStartedEvent, ToolUsageFinishedEvent

logger = logging.getLogger(__name__)

class CrewAIEventLogger:
    """간단한 CrewAI 이벤트 로거 - Supabase 전용"""
    def __init__(self):
        initialize_db()
        self.supabase = get_db_client()
        logger.info("🎯 CrewAIEventLogger initialized")

    # ============================================================================
    # 유틸리티 함수
    # ============================================================================
    def _handle_error(self, operation: str, error: Exception) -> None:
        """통합 에러 처리"""
        logger.error(f"❌ [{operation}] 오류 발생: {error}")
        logger.error(traceback.format_exc())

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
            self._handle_error("데이터추출", e)
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
        return {"final_result": str(final_output) if final_output is not None else ""}

    def _extract_tool_data(self, event_obj: Any) -> Dict[str, Any]:
        """Tool 사용 이벤트 데이터 추출"""
        tool_name = getattr(event_obj, 'tool_name', None)
        tool_args = getattr(event_obj, 'tool_args', None)
        print("tool args obj", tool_args)
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
            except Exception as ex:
                logger.warning(f"직렬화 실패 ({key}): {ex}")
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
            self._handle_error("Supabase저장", e)

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
            logger.info(f"📝 [{etype}] [{job_id[:8]}] → Supabase: ✅")
        except Exception as e:
            self._handle_error("이벤트처리", e)

    def emit_event(self, event_type: str, data: Dict[str, Any], job_id: Optional[str] = None,
                   crew_type: Optional[str] = None, todo_id: Optional[str] = None, proc_inst_id: Optional[str] = None) -> None:
        """수동 커스텀 이벤트 발행"""
        try:
            jid = job_id or event_type
            ctype = crew_type or "action"
            rec = self._create_event_record(event_type, data, jid, ctype, todo_id, proc_inst_id)
            self._save_to_supabase(rec)
            logger.info(f"📝 [{event_type}] → Supabase: ✅")
        except Exception as e:
            self._handle_error("커스텀이벤트발행", e)

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
            logger.info("✅ CrewAI event listeners registered") 