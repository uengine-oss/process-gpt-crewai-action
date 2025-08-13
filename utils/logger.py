# ============================================================================
# 간단한 로깅 시스템 - 에러와 일반 로그만 (가독성 향상)
# ============================================================================

import traceback
from datetime import datetime
from typing import Optional, Dict, Any

def _ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "Z"

def log(message: str, *, context: Optional[Dict[str, Any]] = None) -> None:
    """일반 로그 (UTC 타임스탬프, 선택 컨텍스트)"""
    prefix = f"📝 [{_ts()}]"
    if context:
        print(f"{prefix} {message} | {context}", flush=True)
    else:
        print(f"{prefix} {message}", flush=True)

def handle_error(operation: str, error: Exception, raise_error: bool = True, extra: Optional[Dict[str, Any]] = None) -> None:
    """에러 처리 (UTC 타임스탬프, 선택 컨텍스트)

    - raise_error=True: 예외를 다시 던짐
    - raise_error=False: 로깅만 수행
    """
    prefix = f"❌ [{_ts()}] [{operation}]"
    print(f"{prefix} 오류: {error}", flush=True)
    if extra:
        print(f"🔎 컨텍스트: {extra}", flush=True)
    print(f"📄 스택: {traceback.format_exc()}", flush=True)
    if raise_error:
        raise Exception(f"{operation} 실패: {error}")