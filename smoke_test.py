import os
import sys
import time
import json
import urllib.request


def _get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 (trusted internal URL)
        code = resp.getcode()
        body = resp.read().decode("utf-8", errors="ignore")
        return code, body


def main() -> int:
    base_url = os.environ.get("SMOKE_BASE_URL", "http://localhost:8000")
    health_url = f"{base_url.rstrip('/')}/health"

    # 간단한 재시도 로직 (최대 10회, 1초 간격)
    for attempt in range(1, 11):
        try:
            code, body = _get(health_url, timeout=3.0)
            if code == 200:
                try:
                    data = json.loads(body)
                    if data.get("status") == "ok":
                        print(f"OK {health_url}")
                        return 0
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(1)

    print(f"FAILED {health_url}")
    return 1


if __name__ == "__main__":
    sys.exit(main())