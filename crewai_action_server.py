import asyncio
import logging
from processgpt_agent_sdk.processgpt_agent_framework import ProcessGPTAgentServer
from crewai_action_executor import CrewAIActionExecutor
from health_server import start_health_server

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """메인 서버 실행 함수"""
    try:
        logger.info("🚀 CrewAI Action Server 시작 중...")
        # 헬스 서버 기동
        start_health_server(host="0.0.0.0", port=8000)
        
        # 실행기 생성
        executor = CrewAIActionExecutor()
        
        # 서버 생성 및 설정
        server = ProcessGPTAgentServer(
            agent_executor=executor,
            agent_type="crewai-action"
        )
        server.polling_interval = 5  # 5초 폴링 간격
        
        logger.info("✅ 서버 설정 완료, 폴링 시작...")
        
        # 서버 실행
        await server.run()
        
    except Exception as e:
        logger.error(f"❌ 서버 실행 중 오류 발생: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 서버 종료 요청됨")
    except Exception as e:
        logger.error(f"💥 치명적 오류: {e}", exc_info=True)
        exit(1)
