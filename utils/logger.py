# ============================================================================
# 간단한 로깅 시스템 - 에러와 일반 로그만 (가독성 향상)
# ============================================================================

import os
import traceback
from datetime import datetime
from typing import Optional, Dict, Any

def summarize_exception_chain(error: Exception, max_len: int = 800, max_depth: int = 6) -> str:
    """예외 체인을 간단히 요약해 한 줄 문자열로 반환"""
    parts: list[str] = []
    cur: Optional[BaseException] = error
    depth = 0
    while cur and depth < max_depth:
        parts.append(f"{type(cur).__name__}: {cur}")
        cur = cur.__cause__ or cur.__context__  # type: ignore[attr-defined]
        depth += 1
    text = " -> ".join(parts)
    return text[:max_len]

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
    """단순 에러 로거 + 선택적 이벤트 발행

    - 한 줄 요약: 시간, 작업명, 예외타입, 메시지, 선택 컨텍스트
    - 상세 스택: LOG_SHOW_STACK=1 일 때만 출력
    - 에러 이벤트 발행: LOG_EMIT_EVENT=1일 때만 발행(발행 실패는 무시)
    - raise_error=True면 예외 재던짐
    """
    prefix = f"❌ [{_ts()}]"
    exc_type = type(error).__name__
    line = f"{prefix} {operation} 실패: {exc_type}: {error}"
    if extra:
        line += f" | context={extra}"
    print(line, flush=True)

    if os.getenv("LOG_SHOW_STACK", "0") == "1":
        print(f"📄 스택:\n{traceback.format_exc()}", flush=True)

    # 이벤트 발행은 사용하지 않음 (로그만 남김)

    if raise_error:
        raise Exception(f"{operation} 실패: {error}") from error