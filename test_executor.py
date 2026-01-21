"""
CrewAIActionTestExecutor - 로컬 테스트용 CrewAI 실행기
"""
import argparse
import asyncio
import logging
import tempfile
import os
from dotenv import load_dotenv
from pathlib import Path
from typing_extensions import override
from unittest.mock import Mock
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from processgpt_agent_sdk.utils import upload_file_to_bucket
from processgpt_agent_sdk.database import initialize_db

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CrewAIActionTestExecutor(AgentExecutor):
    """CrewAI 테스트 실행기 - 로컬 테스트용"""

    async def _upload_file(
        self,
        file_name: str = "test.txt",
        proc_inst_id: str = "proc_inst_id_123",
    ) -> dict:
        """
        파일을 버킷에 업로드하는 테스트 메서드
        
        Args:
            file_name: 파일 이름 (기본값: "test.txt")
            proc_inst_id: 프로세스 인스턴스 ID (기본값: "proc_inst_id_123")
        
        Returns:
            업로드 결과 딕셔너리
        """
        try:
            logger.info("🎯 upload_file 테스트 시작")
            
            # 임시 디렉토리에 test.txt 파일 생성
            with tempfile.TemporaryDirectory() as temp_dir:
                test_file_path = Path(temp_dir) / "test.txt"
                
                # test.txt 파일에 "test" 내용 작성
                with open(test_file_path, "w", encoding="utf-8") as f:
                    f.write("test")
                
                logger.info(f"✅ 테스트 파일 생성 완료: {test_file_path}")
                
                # 파일 내용 확인
                with open(test_file_path, "r", encoding="utf-8") as f:
                    file_content = f.read()
                assert file_content == "test"
                logger.info(f"📄 파일 내용 확인: {file_content}")
                
                # 파일을 바이너리 모드로 열어서 업로드
                with open(test_file_path, "rb") as f:
                    result = await upload_file_to_bucket(
                        file=f,
                        file_name=file_name,
                        proc_inst_id=proc_inst_id
                    )
                
                # 결과 검증 및 출력
                logger.info("\n📤 업로드 결과:")
                logger.info(f"  - success: {result.get('success')}")
                logger.info(f"  - storage_path: {result.get('storage_path')}")
                logger.info(f"  - public_url: {result.get('public_url')}")
                
                if result.get("success"):
                    assert "storage_path" in result
                    # 파일명에 UUID가 추가되므로 uploads/로 시작하고 원본 파일명을 포함하는지 확인
                    assert result["storage_path"].startswith("uploads/")
                    assert file_name in result["storage_path"] or Path(file_name).stem in result["storage_path"]
                    logger.info("✅ 업로드 성공!")
                    logger.info(f"📁 저장된 경로: {result['storage_path']}")
                    if result.get("public_url"):
                        logger.info(f"📎 공개 URL: {result.get('public_url')}")
                else:
                    error_msg = result.get("error", "알 수 없는 오류")
                    logger.error(f"❌ 업로드 실패: {error_msg}")
                    raise Exception(f"업로드 실패: {error_msg}")
                
                logger.info("🎉 테스트 완료")
                return result

        except Exception as e:
            logger.error(f"❌ 테스트 중 오류 발생: {e}", exc_info=True)
            raise


    @override
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """메인 실행 로직"""
        logger.info("🎯 CrewAI Action 테스트 실행 시작")
        await self._upload_file()
        return

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """작업 취소 (테스트용 단순 구현)"""
        logger.info("🛑 작업 취소 요청됨 (테스트)")
        return


def create_mock_context(
    user_input: str = "테스트 요청",
    row: dict | None = None,
    extras: dict | None = None,
) -> RequestContext:
    """테스트용 Mock RequestContext 생성"""
    context_data = {
        "row": row or {
            "id": "test_task_id",
            "proc_inst_id": "test_proc_inst_id",
            "root_proc_inst_id": "test_root_proc_inst_id",
            "tenant_id": "test_tenant_id",
        },
        "extras": extras or {
            "form_id": "test_form_id",
            "agents": [],
            "users": [],
            "form_fields": {},
            "form_html": "",
            "activity_name": "테스트 액티비티",
            "summarized_feedback": "",
            "tenant_mcp": None,
            "sources": [],
            "notify_user_emails": [],
        },
    }
    
    # spec을 제거하고 필요한 메서드를 직접 설정
    mock_context = Mock()
    mock_context.get_user_input.return_value = user_input
    mock_context.get_context_data.return_value = context_data
    
    return mock_context


def create_mock_event_queue() -> EventQueue:
    """테스트용 Mock EventQueue 생성"""
    mock_queue = Mock(spec=EventQueue)
    mock_queue.enqueue_event = Mock()
    return mock_queue


async def main():
    """메인 실행 함수"""
    try:
        logger.info("🚀 CrewAI Action 테스트 시작 중...")
        # DB 초기화
        initialize_db()
        logger.info("✅ DB 초기화 완료")
        # 실행기 생성
        executor = CrewAIActionTestExecutor()
        mock_context = create_mock_context()
        mock_event_queue = create_mock_event_queue()
        await executor.execute(mock_context, mock_event_queue)
        
    except Exception as e:
        logger.error(f"❌ 실행 중 오류 발생: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        load_dotenv(override=True)
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 종료 요청됨")
    except Exception as e:
        logger.error(f"💥 치명적 오류: {e}", exc_info=True)
        exit(1)
