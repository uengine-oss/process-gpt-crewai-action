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
from processgpt_agent_utils.tools.safe_tool_loader import SafeToolLoader
from processgpt_agent_utils.tools.deterministic_code_tool import DeterministicCodeTool

# 로깅 설정
logger = logging.getLogger(__name__)

class CrewAIActionExecutor(AgentExecutor):
    """CrewAI 실행기 - context에서 데이터 추출 후 CrewAI 실행"""

    def _generate_deterministic(self, tenant_id: str, task_id: str) -> bool:
        """Deterministic 코드 생성만 수행. 실패해도 예외를 전파하지 않는다.
        Returns True on success, False on failure.
        """
        try:
            logger.info(f"🔍 CrewAI 실행 결과를 기반으로 Deterministic Code 생성 시작")
            DeterministicCodeTool()._run(tenant_id=str(tenant_id), todo_id=str(task_id), action="generate")
            logger.info("✅ Deterministic Code 생성 완료")
            return True
        except Exception as e:
            logger.warning(f"⚠️ Deterministic Code 생성 실패(무시): {e}", exc_info=True)
            return False

    async def _run_deterministic(self, tenant_id: str, task_id: str, proc_inst_id: str, event_queue: EventQueue) -> bool:
        """결정론적 코드를 실행하고 이벤트를 발행한다.
        성공 시 최종 결과 이벤트까지 발행하고 True를 반환, 실패 시 False 반환.
        """
        try:
            logger.info(f"🔍 Deterministic Code Tool 실행 시작 - tenant_id: {tenant_id}, task_id: {task_id}")
            det_tool = DeterministicCodeTool(tenant_id=tenant_id, todo_id=task_id)
            job_uuid = str(uuid.uuid4())
    
            det_result = det_tool._run(tenant_id=tenant_id, todo_id=task_id)
            logger.info(f"🔍 Deterministic Code Tool 실행 결과: {det_result}")
            det_result_json = json.loads(det_result)
            
            if det_result_json.get("ok"):
                # 결정론적 코드 실행 결과 이벤트
                event_queue.enqueue_event(
                    TaskStatusUpdateEvent(
                        status={
                            "state": TaskState.working,
                            "message": new_agent_text_message(
                                json.dumps(
                                    {
                                        "role": "결정론적 코드 실행 결과",
                                        "name": "결정론적 코드 실행 결과",
                                        "goal": "결정론적 코드 실행의 결과를 보고합니다.",
                                        "agent_profile": "/images/chat-icon.png",
                                    },
                                    ensure_ascii=False,
                                ),
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
                                det_result,
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
                logger.info("🔍 Deterministic Code 실행 완료 — 최종 결과 이벤트 발송")
                end_job_uuid = str(uuid.uuid4())
                
                form_result = {}
                if det_result_json.get("form_result"):
                    form_result = det_result_json.get("form_result")

                # 최종 결과 이벤트 발송
                event_queue.enqueue_event(
                    TaskStatusUpdateEvent(
                        status={
                            "state": TaskState.working,
                            "message": new_agent_text_message(
                                json.dumps(
                                    {
                                        "role": "최종 결과 반환",
                                        "name": "최종 결과 반환",
                                        "goal": "요청된 폼 형식에 맞는 최종 결과를 반환합니다.",
                                        "agent_profile": "/images/chat-icon.png",
                                    },
                                    ensure_ascii=False,
                                ),
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
                            "job_id": end_job_uuid,
                        },
                    )
                )

                event_queue.enqueue_event(
                    TaskStatusUpdateEvent(
                        status={
                            "state": TaskState.completed,
                            "message": new_agent_text_message(
                                json.dumps(form_result, ensure_ascii=False),
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
                            "job_id": end_job_uuid,
                        },
                    )
                )

                event_queue.enqueue_event(
                    TaskArtifactUpdateEvent(
                        artifact=new_text_artifact(
                            name="deterministic_action_result",
                            description="Deterministic Action 실행 결과",
                            text=json.dumps(det_result_json, ensure_ascii=False),
                        ),
                        lastChunk=True,
                        contextId=proc_inst_id,
                        taskId=task_id,
                    )
                )
                logger.info("🎉 Deterministic 결과 반환 완료 — CrewAI 크루 생성 없이 종료")
                return True

            logger.error("❌ Deterministic Code 실행 실패")
            return False
        except Exception as e:
            logger.error(f"❌ Deterministic 실행 중 오류: {e}", exc_info=True)
            return False

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
            form_id = extras.get("form_id")
            tenant_id = row.get("tenant_id")
            
            logger.info(f"🔍 form_id: {form_id}, task_id: {task_id}, proc_inst_id: {proc_inst_id}")
            
            # Context variables 초기화
            set_context(
                task_id=str(task_id) if task_id else "",
                proc_inst_id=str(proc_inst_id) if proc_inst_id else "",
                crew_type="action",
                users_email=extras.get("notify_user_emails", [])
            )

            logger.info(f"🔧 Context variables 초기화 완료 - task_id: {task_id}, proc_inst_id: {proc_inst_id}, crew_type: action")

            # if extras.get("summarized_feedback", "") == "":
            #     # 결정론적 코드 실행: 성공 시 이벤트 발행 후 조기 종료
            #     handled = await self._run_deterministic(str(tenant_id), str(task_id), str(proc_inst_id), event_queue)
            #     if handled:
            #         return

            # CrewAI 실행
            logger.info("\n\n🤖 CrewAI Action 크루 생성 및 실행")
            crew = await create_crew(
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
            
            if pure_form_data and pure_form_data != {}:
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
                                json.dumps(pure_form_data, ensure_ascii=False),
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

            # Deterministic 코드 생성
            self._generate_deterministic(str(tenant_id), str(task_id))

        except Exception as e:
            logger.error(f"❌ CrewAI 실행 중 오류 발생: {e}", exc_info=True)
            raise
        finally:
            # MCP 어댑터 정리 - 연결 오류가 있어도 정리 시도
            try:
                logger.info("🔧 MCP 어댑터 정리 시작...")
                SafeToolLoader.shutdown_all_adapters()
                logger.info("✅ MCP 어댑터 정리 완료")
            except Exception as cleanup_error:
                # 정리 중 오류가 발생해도 로그만 남기고 계속 진행
                logger.warning(f"⚠️ MCP 어댑터 정리 중 오류 발생 (무시): {cleanup_error}", exc_info=True)

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """작업 취소 (현재는 단순 구현)"""
        logger.info("🛑 작업 취소 요청됨")
        return
