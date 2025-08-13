from crewai import Crew, Agent, Task
from crewai.tools import BaseTool

class HumanQuestionTool(BaseTool):
    name: str = "HumanQuestionTool"
    description: str = "Ask a question to the user and wait for their response."

    def _run(self, question: str) -> str:
        print(f"[질문] {question}")
        answer = input("> ")
        print(f"[답변] {answer}\n")
        return answer

# 에이전트 정의 (필수 정보 추가)
agent = Agent(
    role="대화형 도우미",
    goal="사용자와 대화하여 정보를 수집하고 응답 생성",
    backstory="사용자와 친근하게 대화하는 도우미입니다.",
    tools=[HumanQuestionTool()],
    verbose=True
)

# Task 정의 (올바른 형식으로 수정)
tasks = [
    Task(
        description="사용자에게 이름을 물어보세요. HumanQuestionTool을 사용하여 '안녕하세요! 이름을 알려주세요.'라고 질문하세요.",
        expected_output="사용자의 이름",
        agent=agent
    ),
    Task(
        description="사용자에게 관심 주제를 물어보세요. HumanQuestionTool을 사용하여 '어떤 주제에 관심이 있으신가요?'라고 질문하세요.",
        expected_output="사용자의 관심 주제",
        agent=agent
    ),
    Task(
        description="이전 작업에서 얻은 사용자 이름과 관심 주제를 바탕으로 친근한 인사말을 생성하세요.",
        expected_output="개인화된 인사말과 주제 소개",
        agent=agent
    )
]

# 크루 생성
crew = Crew(
    agents=[agent],
    tasks=tasks,
    process="sequential"
)

if __name__ == "__main__":
    print("Human-in-the-Loop 테스트 시작...\n")
    result = crew.kickoff()
    print(f"\n최종 결과:\n{result}")

