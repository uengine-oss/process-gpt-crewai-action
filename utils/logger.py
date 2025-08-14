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
    """에러 로깅 + (옵션) 예외 재던지기

    - 시간/작업명/오류 메시지 출력
    - 컨텍스트가 있으면 함께 출력
    - 스택은 항상 출력
    - raise_error=True면 예외 재던짐
    """
    prefix = f"❌ [{_ts()}] [{operation}]"
    print(f"{prefix} 오류: {error}", flush=True)
    if extra:
        print(f"🔎 컨텍스트: {extra}", flush=True)
    print(f"📄 스택:\n{traceback.format_exc()}", flush=True)
    if raise_error:
        raise Exception(f"{operation} 실패: {error}")