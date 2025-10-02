import os
import sys
import argparse
import asyncio
import logging
import random

from crewai_action_executor import CrewAIActionExecutor
from processgpt_agent_sdk.single_run import run_single_todo_readonly

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [todo=%(todo)s] %(message)s",
)
logger = logging.getLogger(__name__)


class TodoAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return msg, {"extra": {"todo": self.extra.get("todo", "-")}}


async def run_one(todo_id: str, agent_type: str = "crewai-action") -> None:
    # 작은 지터로 “동시성”을 더 현실적으로 만듭니다 (선택)
    await asyncio.sleep(random.uniform(0.0, 0.4))
    adapter = TodoAdapter(logger, {"todo": todo_id})
    adapter.info("▶️ 시작")
    executor = CrewAIActionExecutor()
    await run_single_todo_readonly(executor, agent_type, todo_id)
    adapter.info("✅ 완료")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--todo",
        dest="todo",
        help="단일 todo_id 또는 콤마(,)로 구분된 여러 todo_id",
    )
    parser.add_argument(
        "--agent-type",
        default="crewai-action",
        help="에이전트 타입 (기본: crewai-action)",
    )
    args = parser.parse_args()

    # 우선순위: CLI --todo > ENV TODO_IDS > 기본값(예시 1개)
    todo_list = []
    if args.todo:
        # 쉼표 구분 지원
        todo_list = [t.strip() for t in args.todo.split(",") if t.strip()]
    elif os.getenv("TODO_IDS"):
        todo_list = [t.strip() for t in os.getenv("TODO_IDS", "").split(",") if t.strip()]
    else:
        # 기본 1개 (기존과 동일 동작)
        todo_list = ["ad5da861-23b7-4ec8-b727-de84638b7483"]

    # 고유값만 유지
    todo_list = list(dict.fromkeys(todo_list))
    if not todo_list:
        print("todo_id가 비었습니다. --todo 또는 TODO_IDS 환경변수를 지정하세요.")
        sys.exit(1)

    # 동시에 실행
    await asyncio.gather(*(run_one(t, args.agent_type) for t in todo_list))


if __name__ == "__main__":
    asyncio.run(main())
