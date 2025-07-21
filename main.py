# -*- coding: utf-8 -*-

# ========================================
# 기본 환경 설정 및 인코딩 설정
# ========================================
import sys
import io
import os
import builtins
import warnings
import asyncio
from contextlib import asynccontextmanager
sys.path.append(os.path.dirname(__file__))
# UTF-8 인코딩 강제 설정
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
os.environ["PYTHONIOENCODING"] = "utf-8"

# 환경변수 로드
from dotenv import load_dotenv
load_dotenv()

# 현재 디렉토리를 Python 경로에 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ========================================
# 전역 print 함수 오버라이드
# ========================================
_orig_print = builtins.print
def print(*args, **kwargs):
    """기본적으로 flush=True를 적용한 print 함수"""
    if 'flush' not in kwargs:
        kwargs['flush'] = True
    _orig_print(*args, **kwargs)
builtins.print = print

# ========================================
# 로깅 설정
# ========================================
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# ========================================
# 경고 메시지 필터링
# ========================================
warnings.filterwarnings("ignore", category=DeprecationWarning, module="qdrant_client.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="websockets.*")

# ========================================
# FastAPI 애플리케이션 설정
# ========================================
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from polling_manager import start_todolist_polling, initialize_connections

@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기 관리"""
    # 서버 시작 시 실행
    print("🚀 서버 시작 - 연결 초기화 및 폴링 시작")
    initialize_connections()
    # 통합 polling 태스크 시작
    asyncio.create_task(start_todolist_polling(interval=7))
    yield
    # 서버 종료 시 실행
    print("🔄 서버 종료")

# FastAPI 앱 인스턴스 생성
app = FastAPI(
    title="Deep Research Server",
    version="1.0",
    description="Deep Research API Server with Event Logging",
    lifespan=lifespan
)

# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # 모든 출처 허용
    allow_credentials=True,
    allow_methods=["*"],     # 모든 HTTP 메서드 허용
    allow_headers=["*"],     # 모든 HTTP 헤더 허용
)

# ========================================
# 라우터 및 엔드포인트 등록
# ========================================
# 여기에 기존 라우터나 엔드포인트 추가
# add_routes_to_app(app)

# ========================================
# 서버 실행
# ========================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=int(os.environ.get("PORT", 8000)),
        ws="none"
    ) 