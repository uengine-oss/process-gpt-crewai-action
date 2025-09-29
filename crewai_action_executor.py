#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CrewAI Action Executor
- context에서 데이터를 추출하여 CrewAI 실행
- 간단하고 명확한 실행 로직
"""

import json
import logging
import uuid
from typing_extensions import override
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import TaskStatusUpdateEvent, TaskState, TaskArtifactUpdateEvent
from a2a.utils import new_agent_text_message, new_text_artifact
from crew_factory import create_crew
from utils import convert_crew_output
from processgpt_agent_utils.utils.context_manager import set_context

# 로깅 설정
logger = logging.getLogger(__name__)

class CrewAIActionExecutor(AgentExecutor):
    """CrewAI 실행기 - context에서 데이터 추출 후 CrewAI 실행"""

    @override
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """메인 실행 로직"""
        try:
            logger.info("🎯 CrewAI Action 실행 시작")
            
            # Context에서 데이터 추출
            query = context.get_user_input()
            context_data = context.get_context_data()
            logger.info(f"📝 Query: {query}\n\n" if query else "📝 Query: 없음")
            
            # SDK 컨텍스트 구조: {"row": self.row, "extras": self._extra_context}
            row = context_data.get("row", {})
            extras = context_data.get("extras", {})
            proc_inst_id = row.get("root_proc_inst_id") or row.get("proc_inst_id")
            task_id = row.get("id")
            form_id = row.get("form_id")
            
            # Context variables 초기화
            set_context(
                task_id=str(task_id) if task_id else "",
                proc_inst_id=str(proc_inst_id) if proc_inst_id else "",
                crew_type="action",
                users_email=extras.get("notify_user_emails", [])
            )

            logger.info(f"🔧 Context variables 초기화 완료 - task_id: {task_id}, proc_inst_id: {proc_inst_id}, crew_type: action")

            # CrewAI 실행
            logger.info("\n\n🤖 CrewAI Action 크루 생성 및 실행")
            crew = create_crew(
                agent_info=extras.get("agents", []),
                user_info=extras.get("users", []),
                task_instructions=query,
                form_types=extras.get("form_fields"),
                form_html=extras.get("form_html", ""),
                current_activity_name=extras.get("activity_name", ""),
                feedback_summary=extras.get("summarized_feedback", ""),
                tenant_mcp=extras.get("tenant_mcp")
            )
            
            # 크루 실행
            result = crew.kickoff()
            logger.info("✅ CrewAI 실행 완료")
            
            # 4. 결과 처리
            pure_form_data, wrapped_result, original_wo_form = convert_crew_output(result, form_id)
            job_uuid = str(uuid.uuid4())
            logger.info("\n\n📤 최종 결과 이벤트 발송")
            
            event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    status={
                        "state": TaskState.working,
                        "message": new_agent_text_message(
                            json.dumps({"role": "최종 결과 반환", 
                                        "name": "최종 결과 반환", 
                                        "goal": "요청된 폼 형식에 맞는 최종 결과를 반환합니다.", 
                                        "agent_profile": "/images/chat-icon.png"}, ensure_ascii=False),
                            proc_inst_id,
                            task_id,
                        ),
                    },
                    final=False,
                    contextId=proc_inst_id,
                    taskId=task_id,
                    metadata={
                        "crew_type": "result",
                        "event_type": "task_started",
                        "job_id": job_uuid,
                    },
                )
            )

            event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    status={
                        "state": TaskState.completed,
                        "message": new_agent_text_message(
                            json.dumps(wrapped_result, ensure_ascii=False),
                            proc_inst_id,
                            task_id,
                        ),
                    },
                    final=False,
                    contextId=proc_inst_id,
                    taskId=task_id,
                    metadata={
                        "crew_type": "result",
                        "event_type": "task_completed",
                        "job_id": job_uuid,
                    },
                )
            )

            event_queue.enqueue_event(
                TaskArtifactUpdateEvent(
                    artifact=new_text_artifact(
                        name="crewai_action_result",
                        description="CrewAI Action 실행 결과",
                        text=json.dumps(wrapped_result, ensure_ascii=False),
                    ),
                    lastChunk=True,
                    contextId=proc_inst_id,
                    taskId=task_id,
                )
            )
            
            logger.info("🎉 CrewAI 실행 완료")
            
        except Exception as e:
            logger.error(f"❌ CrewAI 실행 중 오류 발생: {e}", exc_info=True)
            raise

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """작업 취소 (현재는 단순 구현)"""
        logger.info("🛑 작업 취소 요청됨")
        return
