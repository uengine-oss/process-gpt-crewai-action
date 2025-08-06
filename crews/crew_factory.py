from typing import Optional
from crewai import Crew, Process, Agent, Task
from langchain_openai import ChatOpenAI
from config.config import settings
from utils.crew_event_logger import CrewConfigManager
from tools.safe_tool_loader import SafeToolLoader
from utils.prompt_generator import DynamicPromptGenerator
from utils.logger import log

# 글로벌 이벤트 훅 등록 (한 번만 실행)
_event_manager = None

# 매니저 LLM 인스턴스 생성
manager_llm = ChatOpenAI(
    model="gpt-4.1",
    temperature=0.1,
    api_key=settings.openai_api_key
)

class AgentWithProfile(Agent):
    name: Optional[str] = None

def create_dynamic_agent(agent_info: dict, tools: list) -> AgentWithProfile:
    """에이전트 정보를 바탕으로 동적으로 Agent 객체 생성"""

    model = agent_info.get("model", "openai/gpt-4.1")  # 기본값 설정
    log(f"에이전트 생성: {agent_info.get('role', 'Unknown')} (모델: {model})")
    
    return AgentWithProfile(
        role=agent_info.get("role", "범용 AI 어시스턴트"),
        goal=agent_info.get("goal", "사용자 요청을 정확히 수행하는 것"),
        backstory=agent_info.get("backstory", "당신은 전문적이고 효율적인 AI 에이전트입니다. 주어진 작업을 정확하고 신속하게 처리하며, 사용자의 요구사항을 완벽히 이해하고 실행합니다."),
        name=agent_info.get("name", "범용 AI 어시스턴트"),
        tools=tools,
        llm=model,
        verbose=True,
        allow_delegation=True
    )

def create_user_task(task_instructions: str, agent: Agent, form_types: dict = None, current_activity_name: str = "", output_summary: str = "", feedback_summary: str = "", agent_info: list = None) -> Task:
    """사용자 요청을 바탕으로 동적 프롬프트 생성하여 단일 Task 생성"""
    
    log("동적 프롬프트 생성 시작...")
    
    # 동적 프롬프트 생성기 초기화
    prompt_generator = DynamicPromptGenerator()
    
    # 원본 agent_info를 그대로 사용 (id만 필요)
    agent_dict_list = agent_info if agent_info else []
    
    # 동적 프롬프트 생성
    description, expected_output = prompt_generator.generate_task_prompt(
        task_instructions=task_instructions,
        agent_info=agent_dict_list,
        form_types=form_types,
        output_summary=output_summary,
        feedback_summary=feedback_summary,
        current_activity_name=current_activity_name
    )
    
    return Task(
        description=description,
        expected_output=expected_output,
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
            "user_id": "default_user",
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
        agent_info=agent_info  # 원본 딕셔너리 리스트 전달
    )
    log(f"사용자 태스크 생성 완료: {task_instructions[:50]}...")
    
    # CrewAI의 계층적 프로세스와 자동 위임 기능을 활용한 크루 생성
    crew = Crew(
        agents=agents,
        tasks=[task],
        process=Process.sequential,
        planning=True, 
        manager_llm=manager_llm,
        verbose=True
    )
    
    log(f"동적 크루 생성 완료 - 매니저: {manager.role}, 총 에이전트: {len(agents)}명")
    return crew 