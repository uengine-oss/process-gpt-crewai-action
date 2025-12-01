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

    def _publish_task_status_event(
        self,
        event_queue: EventQueue,
        state: TaskState,
        message: str,
        proc_inst_id: str,
        task_id: str,
        metadata: dict,
    ) -> None:
        """TaskStatusUpdateEvent 발행"""
        event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                status={
                    "state": state,
                    "message": message,
                },
                final=False,
                contextId=proc_inst_id,
                taskId=task_id,
                metadata=metadata,
            )
        )

    def _publish_artifact_event(
        self,
        event_queue: EventQueue,
        artifact_name: str,
        artifact_description: str,
        artifact_text: str,
        proc_inst_id: str,
        task_id: str,
    ) -> None:
        """TaskArtifactUpdateEvent 발행"""
        event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                artifact=new_text_artifact(
                    name=artifact_name,
                    description=artifact_description,
                    text=artifact_text,
                ),
                lastChunk=True,
                contextId=proc_inst_id,
                taskId=task_id,
            )
        )

    def _publish_final_result_events(
        self,
        event_queue: EventQueue,
        form_data: dict,
        proc_inst_id: str,
        task_id: str,
        job_uuid: str,
    ) -> None:
        """최종 결과 반환을 위한 이벤트 쌍 발행 (working + completed)"""
        # working 상태 이벤트
        self._publish_task_status_event(
            event_queue=event_queue,
            state=TaskState.working,
            message=new_agent_text_message(
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
            proc_inst_id=proc_inst_id,
            task_id=task_id,
            metadata={
                "crew_type": "result",
                "event_type": "task_started",
                "job_id": job_uuid,
            },
        )

        # completed 상태 이벤트
        self._publish_task_status_event(
            event_queue=event_queue,
            state=TaskState.completed,
            message=new_agent_text_message(
                json.dumps(form_data, ensure_ascii=False),
                proc_inst_id,
                task_id,
            ),
            proc_inst_id=proc_inst_id,
            task_id=task_id,
            metadata={
                "crew_type": "result",
                "event_type": "task_completed",
                "job_id": job_uuid,
            },
        )


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
                self._publish_task_status_event(
                    event_queue=event_queue,
                    state=TaskState.working,
                    message=new_agent_text_message(
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
                    proc_inst_id=proc_inst_id,
                    task_id=task_id,
                    metadata={
                        "crew_type": "result",
                        "event_type": "task_started",
                        "job_id": job_uuid,
                    },
                )

                self._publish_task_status_event(
                    event_queue=event_queue,
                    state=TaskState.completed,
                    message=new_agent_text_message(
                        det_result,
                        proc_inst_id,
                        task_id,
                    ),
                    proc_inst_id=proc_inst_id,
                    task_id=task_id,
                    metadata={
                        "crew_type": "result",
                        "event_type": "task_completed",
                        "job_id": job_uuid,
                    },
                )
                logger.info("🔍 Deterministic Code 실행 완료 — 최종 결과 이벤트 발송")
                end_job_uuid = str(uuid.uuid4())
                
                form_result = {}
                if det_result_json.get("form_result"):
                    form_result = det_result_json.get("form_result")

                # 최종 결과 이벤트 발송
                self._publish_final_result_events(
                    event_queue=event_queue,
                    form_data=form_result,
                    proc_inst_id=proc_inst_id,
                    task_id=task_id,
                    job_uuid=end_job_uuid,
                )

                self._publish_artifact_event(
                    event_queue=event_queue,
                    artifact_name="deterministic_action_result",
                    artifact_description="Deterministic Action 실행 결과",
                    artifact_text=json.dumps(det_result_json, ensure_ascii=False),
                    proc_inst_id=proc_inst_id,
                    task_id=task_id,
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
            # 🔄 초기 단계는 항상 planning으로 설정 (CrewAI Planning 단계)
            # 이후 planning 결과(list_of_plans_per_task)가 감지되면 logger에서 action으로 전환
            set_context(
                task_id=str(task_id) if task_id else "",
                proc_inst_id=str(proc_inst_id) if proc_inst_id else "",
                crew_type="planning",
                users_email=extras.get("notify_user_emails", [])
            )

            logger.info(
                f"🔧 Context variables 초기화 완료 - task_id: {task_id}, proc_inst_id: {proc_inst_id}, crew_type: planning"
            )

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
                tenant_mcp=extras.get("tenant_mcp"),
                sources=extras.get("sources", []),
                tenant_id=tenant_id
            )
            
            # 크루 실행
            result = crew.kickoff()
            logger.info("✅ CrewAI 실행 완료")
            
            # 4. 결과 처리
            form_types = extras.get("form_fields")
            pure_form_data, wrapped_result, original_wo_form, report_fields, slide_fields = convert_crew_output(
                result, form_id, form_types
            )
            job_uuid = str(uuid.uuid4())
            logger.info("\n\n📤 최종 결과 이벤트 발송")
            
            # 리포트 필드 이벤트 발행
            for field_key, field_value in report_fields.items():
                if field_value:  # 값이 있는 경우만 발행
                    field_job_uuid = str(f"final_report_merge_{field_key}")
                    logger.info(f"📄 리포트 필드 이벤트 발행: {field_key}")
                    
                    # working 상태 이벤트
                    self._publish_task_status_event(
                        event_queue=event_queue,
                        state=TaskState.working,
                        message=new_agent_text_message(
                            json.dumps(
                                {
                                    "role": "리포트 생성",
                                    "name": "리포트 생성",
                                    "goal": f"리포트 필드 '{field_key}'를 생성합니다.",
                                    "agent_profile": "/images/chat-icon.png",
                                },
                                ensure_ascii=False,
                            ),
                            proc_inst_id,
                            task_id,
                        ),
                        proc_inst_id=proc_inst_id,
                        task_id=task_id,
                        metadata={
                            "crew_type": "report",
                            "event_type": "task_started",
                            "job_id": field_job_uuid,
                        },
                    )

                    # completed 상태 이벤트 (리포트 데이터 포함)
                    report_data = {field_key: field_value}
                    self._publish_task_status_event(
                        event_queue=event_queue,
                        state=TaskState.completed,
                        message=new_agent_text_message(
                            json.dumps(report_data, ensure_ascii=False),
                            proc_inst_id,
                            task_id,
                        ),
                        proc_inst_id=proc_inst_id,
                        task_id=task_id,
                        metadata={
                            "crew_type": "report",
                            "event_type": "task_completed",
                            "job_id": field_job_uuid,
                        },
                    )

            # 슬라이드 필드 이벤트 발행
            for field_key, field_value in slide_fields.items():
                if field_value:  # 값이 있는 경우만 발행
                    field_job_uuid = str(uuid.uuid4())
                    logger.info(f"📊 슬라이드 필드 이벤트 발행: {field_key}")
                    
                    # working 상태 이벤트
                    self._publish_task_status_event(
                        event_queue=event_queue,
                        state=TaskState.working,
                        message=new_agent_text_message(
                            json.dumps(
                                {
                                    "role": "슬라이드 생성",
                                    "name": "슬라이드 생성",
                                    "goal": f"슬라이드 필드 '{field_key}'를 생성합니다.",
                                    "agent_profile": "/images/chat-icon.png",
                                },
                                ensure_ascii=False,
                            ),
                            proc_inst_id,
                            task_id,
                        ),
                        proc_inst_id=proc_inst_id,
                        task_id=task_id,
                        metadata={
                            "crew_type": "slide",
                            "event_type": "task_started",
                            "job_id": field_job_uuid,
                        },
                    )

                    # completed 상태 이벤트 (슬라이드 데이터 포함)
                    slide_data = {field_key: field_value}
                    self._publish_task_status_event(
                        event_queue=event_queue,
                        state=TaskState.completed,
                        message=new_agent_text_message(
                            json.dumps(slide_data, ensure_ascii=False),
                            proc_inst_id,
                            task_id,
                        ),
                        proc_inst_id=proc_inst_id,
                        task_id=task_id,
                        metadata={
                            "crew_type": "slide",
                            "event_type": "task_completed",
                            "job_id": field_job_uuid,
                        },
                    )
            
            # 일반 폼 데이터 이벤트 발행
            if pure_form_data and pure_form_data != {}:
                self._publish_final_result_events(
                    event_queue=event_queue,
                    form_data=pure_form_data,
                    proc_inst_id=proc_inst_id,
                    task_id=task_id,
                    job_uuid=job_uuid,
                )

            self._publish_artifact_event(
                event_queue=event_queue,
                artifact_name="crewai_action_result",
                artifact_description="CrewAI Action 실행 결과",
                artifact_text=json.dumps(wrapped_result, ensure_ascii=False),
                proc_inst_id=proc_inst_id,
                task_id=task_id,
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
