import os, time, uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from crewai import Crew, Agent, Task, Process
from crewai.flow.flow import Flow, start, listen
from crewai.flow.persistence import persist
from crewai.tools import tool

# ── Storage 경로 ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("CREWAI_STORAGE_DIR", os.path.join(BASE_DIR, "crewai_storage"))

# ── 상태 모델 ──
class RunState(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    # NEW: 주제 (run1에서만 설정, run2에서는 그대로 보존)
    topic: Optional[str] = None
    run_count: int = 0
    paused: bool = False             # run1 종료 시 True, run2 종료 시 False
    draft: Optional[str] = None      # run1에서 생성된 초안
    final: Optional[str] = None      # run2에서 생성된 최종본
    feedback: Optional[str] = None   # run2에서만 설정
    tool_logs: List[Dict[str, Any]] = Field(default_factory=list)

# ── 간단 도구 ──
@tool("summarize100")
def summarize100(text: str) -> str:
    """입력 텍스트를 공백을 정리한 후 100자 이내로 요약합니다."""
    s = " ".join(str(text).split())
    return s if len(s) <= 100 else s[:97] + "..."

@tool("word_count")
def word_count(text: str) -> int:
    """입력 텍스트의 단어 수를 정수로 반환합니다."""
    return len([w for w in str(text).split() if w.strip()])

# ── Flow ──
@persist()
class FeedbackResumeFlow(Flow[RunState]):
    def _agent(self) -> Agent:
        # planning=True → LLM 플래너 사용(OPENAI_API_KEY 필요)
        return Agent(
            role="초안 작성/개선 담당자",
            goal="초안을 만들고, 이후엔 피드백을 반영해 더 디테일하게 이어쓴다.",
            backstory="항상 제공된 도구를 활용하고, 지시를 엄격히 따른다.",
            tools=[summarize100, word_count],
            llm="openai/gpt-4.1",
            allow_delegation=False,
            verbose=True,
        )

    # ① run1: 주제를 state에 최초 설정(없을 때만), 초안 생성(피드백 없음)
    @start()
    def make_draft(self):
        self.state.run_count += 1

        # --- 주제 설정: run1에서만 설정, run2에서는 스킵 ---
        # kickoff(inputs={"topic": "..."}로 들어오면 state.topic에 자동 매핑됨
        if not self.state.topic:
            # 최후의 보루: topic이 정말 없다면 기본문구 사용 (실전에서는 입력 강제 권장)
            self.state.topic = "기본 주제(테스트): CrewAI 상태 복원과 이어쓰기"

        # draft가 이미 있으면(=복원 상황), 초안 재생성 스킵
        if self.state.draft:
            return self.state.draft

        agent = self._agent()
        # base_text는 topic을 기반으로 생성
        base_text = (
            f"{self.state.topic}에 대한 초안을 작성한다. "
            "run1에서는 피드백 없이 초안만 만들고 저장한다. "
            "run2에서 피드백을 받아 초안을 보존한 채 뒤에 디테일을 이어써서 최종본을 만든다."
        )
        task = Task(
            description=(
                "아래 텍스트를 바탕으로 한국어 100자 이내의 '초안'을 작성하고, "
                "해당 텍스트의 단어 수를 도구로 계산하라(summarize100, word_count 반드시 사용). "
                "출력 형식: '초안: <요약> | 단어수: <정수>'\n"
                f"텍스트: {base_text}"
            ),
            expected_output="초안: <요약> | 단어수: <정수>",
            agent=agent,
        )
        draft_out = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            planning=True,   # ✅ 실전처럼 플래너 활성화
            verbose=True,
        ).kickoff()

        self.state.draft = str(draft_out)
        self.state.paused = True      # run1 끝: 대기 상태로 종료
        return self.state.draft

    # ② run2: 같은 ID 복원 + 피드백 있을 때만 이어쓰기(확장)
    @listen(make_draft)
    def apply_feedback(self, _):
        if not self.state.draft:
            return "초안 없음(아직 run1 미수행)."

        # 주제는 run1에서 이미 설정되었으므로 run2에서는 '스킵'(절대 변경하지 않음)
        if not self.state.feedback:
            # '피드백 없음 → 계속 대기'가 맞는 동작
            return {
                "message": "피드백 없음 → 대기 유지",
                "state_id": self.state.id,
                "paused": self.state.paused,
                "topic": self.state.topic,
            }

        agent = self._agent()
        # 이어쓰기 프롬프트: 초안을 변경하지 말고 뒤에 추가
        extend_prompt = (
            "다음 '초안'을 변경하지 말고, 초안의 뒤에 새로운 문장들을 덧붙여 더 디테일한 설명과 예시를 추가하라. "
            "이어쓴 문단은 초안과 자연스럽게 연결되어야 하며, 최소 2~3문장 이상으로 확장하라. "
            "출력 형식: '최종: <초안 그대로> <이어쓴 문단>' (초안 부분은 그대로 다시 포함할 것)\n"
            f"- 주제: {self.state.topic}\n"
            f"- 초안: {self.state.draft}\n"
            f"- 피드백: {self.state.feedback}"
        )
        task = Task(
            description=extend_prompt,
            expected_output="최종: <초안 그대로> <이어쓴 문단>",
            agent=agent,
        )
        final_out = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            planning=True,   # ✅ 실전처럼 플래너 활성화
            verbose=True,
        ).kickoff()

        self.state.final = str(final_out)
        self.state.paused = False     # run2 끝: 대기 해제
        return self.state.final

    # ③ 리포트: 이어쓰기/복원/주제 보존 여부 한눈에
    @listen(apply_feedback)
    def report(self, _):
        return {
            "state_id": self.state.id,
            "run_count": self.state.run_count,
            "resumed": self.state.run_count > 1,   # True면 복원 실행
            "paused": self.state.paused,           # run1 True → run2 False
            "topic": self.state.topic,             # ★ 주제 보존 확인
            "has_draft": bool(self.state.draft),
            "has_final": bool(self.state.final),
            "draft_sample": (self.state.draft or "")[:140],
            "final_sample": (self.state.final or "")[:160],
        }

# ── 한 번 실행으로 run1 → run2 자동 ──
if __name__ == "__main__":
    # 👉 여기에서 주제를 지정하세요(실전에서는 외부 입력으로 교체 가능)
    TOPIC = "여름철 강아지 산책시 주의사항"

    print("\n=== RUN1: 피드백 없이 초안만 생성 & 저장 ===")
    f1 = FeedbackResumeFlow()
    # run1에서는 topic만 전달하여 state.topic을 '최초 설정'
    r1 = f1.kickoff(inputs={"topic": TOPIC})
    sid = f1.state.id
    topic_run1 = r1.get("topic")
    print("[RUN1] report:", r1)
    print("[RUN1] state_id:", sid)

    # 실제처럼 시간이 지난 뒤 재시작한다고 가정
    time.sleep(1)

    print("\n=== RUN2: 동일 ID 복원 + 피드백 적용(이어쓰기/확장) ===")
    f2 = FeedbackResumeFlow()
    resume_feedback = "초안을 보존하고 그 뒤에 실제 사례와 정량적 지표를 덧붙여 문단을 확장하라."
    # run2에서는 topic을 전달하지 않음 → DB의 topic을 그대로 복원/사용(스킵)
    r2 = f2.kickoff(inputs={"id": sid, "feedback": resume_feedback})
    print("[RUN2] report:", r2)

    # ── 이어쓰기/복원/주제 보존 검증 요약 ──
    print("\n=== 검증 요약 ===")
    same_id = (sid == r2.get("state_id"))
    same_topic = (topic_run1 == r2.get("topic"))
    print(f"- state_id 동일?: {same_id} (id={sid})")
    print(f"- topic 보존?: {same_topic} (run1='{topic_run1}' / run2='{r2.get('topic')}')")
    print(f"- run1 paused: {r1.get('paused')}  → run2 paused: {r2.get('paused')}")
    print(f"- resumed: {r2.get('resumed')} (True면 복원)")
    print(f"- has_draft/final: {r2.get('has_draft')}/{r2.get('has_final')}")
    print(f"- draft_sample: {r2.get('draft_sample')}")
    print(f"- final_sample: {r2.get('final_sample')}")

    # ── 보증(assert) ──
    assert same_id, "❌ state_id가 달라 복원 실패"
    assert same_topic, "❌ run2에서 topic이 바뀌었음(보존 실패)"
    assert r1.get("resumed") in (False, None) and r1.get("paused") is True and r1.get("has_draft") and not r1.get("has_final"), \
        "❌ run1 상태가 기대와 다름(피드백 없이 초안만 생성해야 함)"
    assert r2.get("resumed") is True and r2.get("paused") is False and r2.get("has_draft") and r2.get("has_final"), \
        "❌ run2 상태가 기대와 다름(복원+피드백 적용되어야 함)"
    d = (r2.get("draft_sample") or "")
    f = (r2.get("final_sample") or "")
    assert len(f) >= len(d), "❌ final이 draft보다 길지 않음(이어쓰기/확장 미흡)"
    assert (d.split(" | ")[0].replace("초안:", "").strip()[:10] in f), "❌ final에 초안 흔적이 충분히 보이지 않음"

    print("\n✅ 성공: run1(피드백 없음) → run2(동일 ID 복원 + 피드백 적용), 주제 보존 & 초안 이어쓰기까지 확인되었습니다.")
