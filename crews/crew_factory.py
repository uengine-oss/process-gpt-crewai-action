from typing import Optional
from crewai import Crew, Process, Agent, Task
from langchain_openai import ChatOpenAI
from config.config import settings
from utils.crew_event_logger import CrewConfigManager
from tools.safe_tool_loader import SafeToolLoader
from utils.logger import log

# 글로벌 이벤트 훅 등록 (한 번만 실행)
_event_manager = None

# LLM 초기화
llm = ChatOpenAI(model="gpt-4.1", openai_api_key=settings.openai_api_key)

class AgentWithProfile(Agent):
    # Pydantic 모델 필드로 추가됩니다
    name: Optional[str] = None

def create_dynamic_agent(agent_info: dict, tools: list) -> AgentWithProfile:
    """에이전트 정보를 바탕으로 동적으로 Agent 객체 생성"""
    return AgentWithProfile(
        role=agent_info.get("role", "범용 AI 어시스턴트"),
        goal=agent_info.get("goal", "사용자 요청을 정확히 수행하는 것"),
        backstory=agent_info.get("backstory", "당신은 전문적이고 효율적인 AI 에이전트입니다. 주어진 작업을 정확하고 신속하게 처리하며, 사용자의 요구사항을 완벽히 이해하고 실행합니다."),
        name=agent_info.get("name", "범용 AI 어시스턴트"),
        tools=tools,
        llm=llm,
        verbose=True,
        allow_delegation=True,
        allowed_agents=["schema_analyst", "sql_executor"]
    )

def create_user_task(task_instructions: str, agent: Agent, form_types: dict = None, current_activity_name: str = "", output_summary: str = "", feedback_summary: str = "", agent_info: list = None) -> Task:
    """사용자 요청을 바탕으로 단일 Task 생성"""
    
    # 모든 정보를 기본값으로 처리 (빈 값이라도 포함)
    agent_list = "\n".join(f"- {info.role}" for info in (agent_info or []))
    
    task_description = f"""
다음 사용자 요청을 완료해주세요:

**작업 지시사항:** {task_instructions}

**현재 처리 단계:** {current_activity_name}

**이전 작업 결과:** {output_summary if output_summary else '없음'}

**피드백 및 요구사항:** {feedback_summary if feedback_summary else '없음'}

**결과 형식 요구사항:** {form_types}

**팀 에이전트 정보:** {agent_list}

**위임 지시사항:**
- 모든 작업은 사용 가능한 에이전트 목록에 있는 에이전트로만 수행하세요.
- 위임할 때는 명확한 지시사항과 기대 결과를 제공하고, 하나의 에이전트에 모두 위임하지말고, 모든 에이전트에 골고루 위임하세요
- 각 에이전트의 전문 분야와 사용 가능한 툴을 고려하여 적절한 에이전트에게 작업을 분배하세요

**최우선 플래닝 원칙:**
- 피드백이 존재하는 경우, 작업 지시는 일단 미뤄두고, 반드시 해당 피드백을 가장 우선적으로 분석하고 이를 바탕으로 전체 작업 계획을 수립하세요
- 피드백에서 지적된 문제점, 개선사항, 추가 요구사항을 모든 작업의 출발점으로 삼으세요

**작업 수행 방법:**
1. 사용 가능한 도구들을 활용하여 작업을 수행하세요
2. 이전 작업 컨텍스트가 있다면 이를 참고하여 이전에 뭘 했는지, 어떤 피드백이 있었는지 파악하고 작업에 반영하세요
3. 필요한 경우, 제공된 툴을 활용하여, 데이터베이스나 외부 시스템과 상호작용하세요
4. **팀 에이전트들에게 적절한 작업을 위임하세요** - 각 에이전트의 전문 분야에 맞는 업무를 배분하고 협업하세요
5. 최종 결과는 사용자가 요청한 Form 타입 형식에 맞춰 제공하세요

**중요 원칙:**
- 실제 도구를 사용하여 정확한 결과를 도출하세요
- 추측이나 가정하지 말고 실제 데이터를 조회하세요
- 오류가 발생하면 명확히 보고하고 대안을 제시하세요
- 모든 과정을 투명하게 공유하세요
- **팀원들과 협업하여 각자의 전문성을 활용하세요**
"""
    
    return Task(
        description=task_description,
        expected_output="""
작업 완료 결과를 다음 형식으로 제공:

1. **작업 수행 결과**: 실제 수행한 작업의 상세 내용
2. **처리된 데이터**: 실제로 처리되거나 조회된 데이터
3. **최종 결과**: 요청된 형식(폼 필드)에 맞춘 JSON 또는 구조화된 데이터

모든 결과는 실제 도구 실행 결과를 바탕으로 해야 하며, 추측이나 가정은 포함하지 마세요.
""",
        agent=agent
    )

def create_crew(agent_info=None, task_instructions="", form_types=None, current_activity_name="", output_summary="", feedback_summary=""):
    """동적으로 크루 생성 (첫 번째 에이전트를 매니저로 고정)"""
    global _event_manager
    log(f"동적 크루 생성 시작 - 에이전트: {len(agent_info) if agent_info else 0}개")
    
    # 글로벌 이벤트 훅 등록 (한 번만)
    if _event_manager is None:
        _event_manager = CrewConfigManager()
        log("CrewAI 글로벌 이벤트 훅 등록 완료")
    
    # 에이전트 정보 처리
    if not agent_info:
        agent_info = [{
            "role": "범용 AI 어시스턴트", 
            "goal": "사용자의 요청을 정확하고 효율적으로 처리",
            "backstory": """당신은 다양한 도구를 활용할 수 있는 전문 AI 어시스턴트입니다. 
사용자의 요청을 분석하고, 적절한 도구를 선택하여 작업을 수행하며, 
정확하고 유용한 결과를 제공하는 것이 당신의 전문 분야입니다.""",
            "tools": ""  # 기본값으로 빈 문자열 설정
        }]
    
    # 에이전트 생성
    agents = []
    for info in agent_info:
        # 개별 에이전트의 ID와 테넌트 ID 추출
        user_id = info.get('id')
        tenant_id = info.get('tenant_id')
        
        # 각 에이전트의 tools 필드를 콤마로 분리하여 리스트로 변환
        tools_str = info.get('tools', '')
        tool_names = [tool.strip() for tool in tools_str.split(',') if tool.strip()] if tools_str else []
        log(f"에이전트 {info.get('role', 'Unknown')} 툴 목록: {tool_names}")
        
        # 동적 툴 로딩 (에이전트별)
        loader = SafeToolLoader(tenant_id=tenant_id, user_id=user_id)
        tools = loader.create_tools_from_names(tool_names)
        log(f"에이전트 {info.get('role', 'Unknown')} 툴 로드 완료: ({len(tools)}개)")
        
        # 동적 에이전트 생성
        agent = create_dynamic_agent(info, tools)
        agents.append(agent)
        log(f"에이전트 생성 완료: {info.get('role', 'Unknown')}")
    
    # 첫 번째 에이전트를 매니저로 지정      # ── 변경
    manager = agents[0]
    
    # 사용자 요청 기반 태스크 생성 (매니저 에이전트에 할당)
    task = create_user_task(
        task_instructions=task_instructions,
        agent=manager,
        form_types=form_types,
        current_activity_name=current_activity_name,
        output_summary=output_summary,
        feedback_summary=feedback_summary,
        agent_info=agents  # 에이전트 정보 전달
    )
    log(f"사용자 태스크 생성 완료: {task_instructions[:50]}...")
    
    # CrewAI의 계층적 프로세스와 자동 위임 기능을 활용한 크루 생성
    crew = Crew(
        agents=agents,
        tasks=[task],
        process=Process.sequential,
        planning=True, 
        manager_llm=llm,
        verbose=True
    )
    
    log(f"동적 크루 생성 완료 - 매니저: {manager.role}, 총 에이전트: {len(agents)}명")
    return crew 