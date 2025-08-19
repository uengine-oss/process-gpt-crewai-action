# -*- coding: utf-8 -*-
"""
dynamic_planning_global_listener_only.py

요구사항 충족:
- persist 미사용 (중도 종료 시에도 이벤트 기반으로만 기록/복원)
- 단일 플래닝 태스크(planning=True)만 사용
- 툴은 본연 로직만 수행(이벤트 저장/업데이트 없음)
- 글로벌 이벤트 리스너에서만 Task/Tool 이벤트를 수신하여 저장
- 재실행(run2) 시 이전 이벤트를 프롬프트에 주입하여 스킵 유도

실행 전 준비:
  export OPENAI_API_KEY=...
  export STATE_ID=my-run-001          # 반드시 고정 ID 사용(이어하기 위해)
  # (선택) export CREWAI_MODEL=openai/gpt-4.1

실행:
  python dynamic_planning_global_listener_only.py

run1: 중간에 프로그램을 직접 종료(CTRL+C 등)해도 됩니다.
run2: 동일한 STATE_ID로 다시 실행하면 이전 이벤트 로그를 읽고 이어 수행합니다.
"""

import os
import json
import datetime
from typing import Any, Dict, List, Optional

from crewai import Agent, Crew, Task, Process
from crewai.tools import tool

# -----------------------------
# 설정 / 저장소 경로
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.path.join(BASE_DIR, "crewai_storage")
os.makedirs(STORAGE_DIR, exist_ok=True)

EVENT_LOG = os.path.join(STORAGE_DIR, "events.jsonl")

def now_iso() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"

# -----------------------------
# 글로벌 이벤트 리스너 등록
#  - Task/Tool 이벤트를 수신할 때만 기록
#  - state_id는 환경변수 STATE_ID를 참조 (툴은 모름)
# -----------------------------
def try_register_global_listener() -> bool:
    try:
        from crewai.utilities.events.base_event_listener import BaseEventListener
        from crewai.utilities.events import (
            crewai_event_bus,
            TaskStartedEvent, TaskCompletedEvent,
            ToolUsageStartedEvent, ToolUsageFinishedEvent
        )

        class GlobalListener(BaseEventListener):
            def __init__(self):
                super().__init__()

            def setup_listeners(self, bus):
                @bus.on(TaskStartedEvent)
                def _on_task_start(source, event: TaskStartedEvent):
                    sid = os.environ.get("STATE_ID", "unknown")
                    task = getattr(event, "task", None)
                    task_id = str(getattr(task, "id", "unknown")) if task else "unknown"
                    task_name = (
                        getattr(task, "name", None)
                        or getattr(task, "description", None)
                        or getattr(event, "task_name", None)
                        or "unknown"
                    )
                    _append_event(sid, "task_start", {
                        "task_id": task_id,
                        "name": task_name,
                    })

                @bus.on(TaskCompletedEvent)
                def _on_task_done(source, event: TaskCompletedEvent):
                    sid = os.environ.get("STATE_ID", "unknown")
                    task = getattr(event, "task", None)
                    task_id = str(getattr(task, "id", "unknown")) if task else "unknown"
                    task_name = (
                        getattr(task, "name", None)
                        or getattr(task, "description", None)
                        or getattr(event, "task_name", None)
                        or "unknown"
                    )
                    output_exists = bool(getattr(event, "output", None))
                    _append_event(sid, "task_end", {
                        "task_id": task_id,
                        "name": task_name,
                        "output_exists": output_exists,
                    })


                @bus.on(ToolUsageStartedEvent)
                def _on_tool_start(source, event: ToolUsageStartedEvent):
                    sid = os.environ.get("STATE_ID", "unknown")
                    _append_event(sid, "tool_start", {
                        "tool": getattr(event, "tool_name", "unknown"),
                    })

                @bus.on(ToolUsageFinishedEvent)
                def _on_tool_end(source, event: ToolUsageFinishedEvent):
                    sid = os.environ.get("STATE_ID", "unknown")
                    _append_event(sid, "tool_end", {
                        "tool": getattr(event, "tool_name", "unknown"),
                    })


        _ = GlobalListener()  # 인스턴스화만 해도 등록됨
        return True
    except Exception:
        # 이벤트 버스가 없는/달라진 환경이어도 실행 자체는 가능
        print("[WARN] CrewAI 이벤트 버스 등록 실패: 버전/환경에 따라 미지원일 수 있습니다.")
        return False

def _append_event(state_id: str, event_type: str, payload: Dict[str, Any]):
    rec = {
        "ts": now_iso(),
        "state_id": state_id,
        "event": event_type,
        "payload": payload,
    }
    with open(EVENT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def load_event_history(state_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    if not os.path.exists(EVENT_LOG):
        return []
    out: List[Dict[str, Any]] = []
    with open(EVENT_LOG, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
                if rec.get("state_id") == state_id:
                    out.append(rec)
            except Exception:
                pass
    # 최신 limit개만 사용
    return out[-limit:]

# -----------------------------
# 툴(오직 로직만)
# -----------------------------
@tool("summarize100")
def summarize100(text: str) -> str:
    """입력 텍스트를 공백 정리 후 100자 이내로 자릅니다."""
    s = " ".join(str(text).split())
    return s if len(s) <= 100 else s[:97] + "..."

@tool("word_count")
def word_count(text: str) -> int:
    """입력 텍스트의 단어 수"""
    return len([w for w in str(text).split() if w.strip()])

# -----------------------------
# 단일 플래닝 태스크 실행
#  - 시작 시 이전 이벤트 로그를 읽어 프롬프트에 주입
#  - 완료된 내용은 스킵하도록 강하게 지시
# -----------------------------
def run_once(state_id: str, topic: str, model_name: str):
    # 이벤트 리스너 등록 (가능한 환경에서만)
    try_register_global_listener()

    # 이전 이벤트 로드 → 프롬프트에 주입
    history = load_event_history(state_id, limit=50)
    history_lines = []
    for ev in history:
        et = ev.get("event")
        pl = ev.get("payload", {})
        if et.startswith("tool_"):
            history_lines.append(f"- {et}: {pl.get('tool')}")
        elif et.startswith("task_"):
            history_lines.append(f"- {et}: {pl.get('name', pl.get('task_id','unknown'))}")
        else:
            history_lines.append(f"- {et}")

    # “여기까지 진행됨 → 스킵”을 강하게 유도
    description = f"""
당신은 단 하나의 플래닝 태스크로 전체 작업을 수행한다.
주제: {topic}

반드시 지킬 규칙:
1) 아래 '이전 이벤트 기록'을 읽고, 이미 수행된 단계/툴 호출의 재수행을 명확히 스킵하라.
2) 필요한 경우에만 툴을 사용하라. (summarize100, word_count)
3) 중간에 프로그램이 중단될 수 있으므로, 단계는 가능한 한 논리적으로 구분하고, 다음 번 재실행에서도 이어서 수행하기 쉬운 순서를 택하라.
4) 최종 결과를 만들 수 있으면 마지막에 'FINAL:' 로 시작하는 한 문단을 **한 번만** 출력하라.
5) 만약 아직 충분한 정보/이전 단계가 미완료라면, 그 단계만 수행하고 종료해도 된다. (다음 실행에서 이어감)

이전 이벤트 기록(최신순 아님, 최근 {len(history_lines)}개):
{os.linesep.join(history_lines) if history_lines else '- (없음)'}

힌트(예):
- 1차 실행(run1): 개요/핵심 요약 작성 → 필요시 summarize100/word_count 사용
- 2차 실행(run2): 이미 수행한 작업은 스킵하고, 부족한 부분(예: 예시/지표/체크리스트)을 보완
- 완료 시 'FINAL:' 로 시작하는 문단 1개만 출력
"""

    agent = Agent(
        role="동적 플래닝 에이전트",
        goal="이전 이벤트를 기반으로 중복 없이 남은 단계만 수행하여 최종 결과를 만든다.",
        backstory="툴은 오직 로직만 수행하며, 이벤트 기록은 전역 리스너가 처리한다.",
        tools=[summarize100, word_count],
        llm=model_name,
        allow_delegation=False,
        verbose=True,
    )

    task = Task(
        description=description,
        expected_output="주제에 알맞는 마크다운 문서 형태로 출력",
        agent=agent,
    )

    # 크루 실행 (단일 태스크)
    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        planning=True,
        verbose=True,
    )
    result = crew.kickoff()
    return result

# -----------------------------
# 엔트리포인트
# -----------------------------
if __name__ == "__main__":
    # 하드코딩: 고정 STATE_ID / TOPIC / MODEL
    STATE_ID = "state-5f1b6e2e-2c8c-4e1a-a2d7-a5b9307edc71"
    TOPIC = "여름철 강아지 산책시 주의사항"
    MODEL = "openai/gpt-4.1"

    # 이벤트 리스너에서 참조할 수 있게 환경변수에도 반영(리스너는 ENV만 읽음)
    os.environ["STATE_ID"] = STATE_ID

    print(f"\n=== run 시작 (STATE_ID={STATE_ID}) ===")
    out = run_once(STATE_ID, TOPIC, MODEL)

    print("\n=== 에이전트 출력 ===")
    print(out if isinstance(out, str) else str(out))

    # 최근 이벤트 몇 개 보여주기
    events = load_event_history(STATE_ID, limit=20)
    print("\n=== 최근 이벤트(해당 STATE_ID) ===")
    for e in events[-10:]:
        print(json.dumps(e, ensure_ascii=False))

    print("\n📁 이벤트 로그 파일:", EVENT_LOG)
    print("💡 팁: run1에서 중간에 종료 후, 동일 STATE_ID로 다시 실행하면 이전 이벤트를 참고하여 이어갑니다.")
