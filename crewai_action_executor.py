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

    def _detect_report_slide_fields(self, form_types) -> list:
        """form_types에서 리포트/슬라이드 타입 필드를 감지하여 반환"""
        report_slide_fields = []
        if not form_types:
            return report_slide_fields
        
        form_fields = None
        if isinstance(form_types, dict) and ("fields" in form_types or "html" in form_types):
            form_fields = form_types.get("fields")
        else:
            form_fields = form_types if form_types else None
        
        if form_fields and isinstance(form_fields, list):
            for field in form_fields:
                if isinstance(field, dict):
                    field_type = field.get("type", "").lower()
                    field_key = field.get("key", "")
                    if field_type in ["report", "document", "slide", "presentation"] and field_key:
                        report_slide_fields.append({
                            "key": field_key,
                            "type": field_type
                        })
        
        return report_slide_fields
    
    def _publish_report_slide_events(
        self, result, report_slide_fields: list, proc_inst_id: str, task_id: str, event_queue: EventQueue
    ):
        """리포트/슬라이드 타입 필드의 마크다운 내용을 추출하고 별도 이벤트로 발행"""
        try:
            # 결과 문자열 확보
            result_text = getattr(result, "raw", None) or str(result)
            
            # 리포트/슬라이드 타입 필드의 마크다운 내용 추출
            for field_info in report_slide_fields:
                field_key = field_info["key"]
                field_type = field_info["type"]
                
                # crew_type 결정: report 또는 slide
                if field_type in ["report", "document"]:
                    crew_type = "report"
                elif field_type in ["slide", "presentation"]:
                    crew_type = "slide"
                else:
                    crew_type = "report"  # 기본값
                
                # 결과에서 해당 필드의 마크다운 내용 찾기
                # 여러 JSON 객체가 있을 수 있으므로 패턴 매칭으로 찾기
                markdown_content = self._extract_markdown_from_result(result_text, field_key)
                
                if markdown_content:
                    job_uuid = str(uuid.uuid4())
                    logger.info(f"📤 {crew_type} 타입 이벤트 발행 시작 - 필드: {field_key}")
                    
                    # 시작 이벤트
                    event_queue.enqueue_event(
                        TaskStatusUpdateEvent(
                            status={
                                "state": TaskState.working,
                                "message": new_agent_text_message(
                                    json.dumps({
                                        "role": f"{crew_type} 생성",
                                        "name": f"{crew_type} 생성",
                                        "goal": f"{field_key} {crew_type}를 생성합니다.",
                                        "agent_profile": "/images/chat-icon.png"
                                    }, ensure_ascii=False),
                                    proc_inst_id,
                                    task_id,
                                ),
                            },
                            final=False,
                            contextId=proc_inst_id,
                            taskId=task_id,
                            metadata={
                                "crew_type": crew_type,
                                "event_type": "task_started",
                                "job_id": job_uuid,
                            },
                        )
                    )
                    
                    # 완료 이벤트 (마크다운 내용 포함)
                    event_queue.enqueue_event(
                        TaskStatusUpdateEvent(
                            status={
                                "state": TaskState.completed,
                                "message": new_agent_text_message(
                                    json.dumps({field_key: markdown_content}, ensure_ascii=False),
                                    proc_inst_id,
                                    task_id,
                                ),
                            },
                            final=False,
                            contextId=proc_inst_id,
                            taskId=task_id,
                            metadata={
                                "crew_type": crew_type,
                                "event_type": "task_completed",
                                "job_id": job_uuid,
                            },
                        )
                    )
                    
                    logger.info(f"✅ {crew_type} 타입 이벤트 발행 완료 - 필드: {field_key}")
                else:
                    logger.warning(f"⚠️ {field_key} 필드의 마크다운 내용을 찾을 수 없습니다")
        
        except Exception as e:
            logger.error(f"❌ 리포트/슬라이드 이벤트 발행 중 오류: {e}", exc_info=True)
    
    def _extract_markdown_from_result(self, result_text: str, field_key: str) -> str:
        """결과 문자열에서 특정 필드의 마크다운 내용을 추출"""
        try:
            import re
            import ast
            
            # 1. 먼저 전체 텍스트에서 JSON 객체 패턴 찾기
            # 여러 JSON 객체가 있을 수 있으므로 각각 시도
            json_pattern = r'\{[^{}]*"' + re.escape(field_key) + r'"[^{}]*\}'
            matches = re.finditer(json_pattern, result_text, re.DOTALL)
            
            for match in matches:
                json_str = match.group(0)
                try:
                    # JSON 파싱 시도
                    obj = json.loads(json_str)
                    if isinstance(obj, dict) and field_key in obj:
                        content = obj[field_key]
                        if isinstance(content, str):
                            return content
                except:
                    # JSON 파싱 실패 시 Python 리터럴 시도
                    try:
                        obj = ast.literal_eval(json_str)
                        if isinstance(obj, dict) and field_key in obj:
                            content = obj[field_key]
                            if isinstance(content, str):
                                return content
                    except:
                        continue
            
            # 2. 백틱으로 감싸진 경우 처리
            backtick_pattern = rf'\{{["\']?{re.escape(field_key)}["\']?\s*:\s*`([^`]+)`'
            match = re.search(backtick_pattern, result_text, re.DOTALL)
            if match:
                return match.group(1)
            
            # 3. 따옴표로 감싸진 경우 처리 (멀티라인 포함)
            # JSON 문자열 이스케이프 처리
            quoted_pattern = rf'\{{["\']?{re.escape(field_key)}["\']?\s*:\s*"((?:[^"\\]|\\.)*)"'
            match = re.search(quoted_pattern, result_text, re.DOTALL)
            if match:
                content = match.group(1)
                # JSON 이스케이프 해제
                try:
                    return json.loads(f'"{content}"')
                except:
                    return content.replace('\\n', '\n').replace('\\"', '"')
            
            # 4. 각 줄을 개별적으로 파싱 시도
            lines = result_text.split('\n')
            for i, line in enumerate(lines):
                line = line.strip()
                if not line or not line.startswith('{'):
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict) and field_key in obj:
                        content = obj[field_key]
                        if isinstance(content, str):
                            return content
                except:
                    # 여러 줄에 걸친 JSON 시도
                    if i + 1 < len(lines):
                        multi_line = '\n'.join(lines[i:i+10])  # 최대 10줄까지
                        try:
                            obj = json.loads(multi_line)
                            if isinstance(obj, dict) and field_key in obj:
                                content = obj[field_key]
                                if isinstance(content, str):
                                    return content
                        except:
                            continue
            
            return None
        
        except Exception as e:
            logger.error(f"❌ 마크다운 추출 중 오류: {e}", exc_info=True)
            return None

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
                tenant_mcp=extras.get("tenant_mcp"),
                sources=extras.get("sources", []),
                tenant_id=tenant_id
            )
            
            # 크루 실행
            result = crew.kickoff()
            logger.info("✅ CrewAI 실행 완료")
            
            # 4. 결과 처리
            pure_form_data, wrapped_result, original_wo_form = convert_crew_output(result, form_id)
            job_uuid = str(uuid.uuid4())
            logger.info("\n\n📤 최종 결과 이벤트 발송")
            
            # 리포트/슬라이드 타입 필드 감지 및 별도 이벤트 발행
            form_types = extras.get("form_fields")
            report_slide_fields = self._detect_report_slide_fields(form_types)
            if report_slide_fields:
                self._publish_report_slide_events(
                    result, report_slide_fields, proc_inst_id, task_id, event_queue
                )
            
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
