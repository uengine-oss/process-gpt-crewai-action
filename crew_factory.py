from typing import Optional, List, Dict
import logging
from crewai import Crew, Process, Agent, Task
from llm_factory import create_llm
from processgpt_agent_utils.utils.crew_event_logger import CrewConfigManager
from processgpt_agent_utils.tools.safe_tool_loader import SafeToolLoader
from prompt_generator import DynamicPromptGenerator

# 로깅 설정
logger = logging.getLogger(__name__)

# 글로벌 이벤트 훅 등록 (한 번만 실행)
_event_manager = None

# =============================
# 에이전트 클래스
# - 프로필 이름 필드를 가진 Agent 서브클래스 정의입니다.
# =============================
class AgentWithProfile(Agent):
    """프로필 이름 필드를 가진 Agent 서브클래스입니다."""
    name: Optional[str] = None

# =============================
# 에이전트 생성
# - 입력 정보와 로드된 도구로 동적 에이전트를 생성합니다.
# =============================
def create_dynamic_agent(agent_info: Dict, tools: List) -> AgentWithProfile:
    """에이전트 정보를 바탕으로 동적으로 Agent 객체 생성"""
    try:
        model_str = agent_info.get("model") or "gpt-4.1"
        provider = model_str.split("/", 1)[0] if "/" in model_str else None
        model_name = model_str.split("/", 1)[1] if "/" in model_str else model_str

        llm_instance = create_llm(
            provider=provider,
            model=model_name,
            temperature=0.1
        )

        agent = AgentWithProfile(
            role=agent_info.get("role", "범용 AI 어시스턴트"),
            goal=agent_info.get("goal", "사용자 요청을 정확히 수행하는 것"),
            backstory=agent_info.get("backstory", "당신은 전문적이고 효율적인 AI 에이전트입니다. 주어진 작업을 정확하고 신속하게 처리하며, 사용자의 요구사항을 완벽히 이해하고 실행합니다."),
            name=agent_info.get("username", "범용 AI 어시스턴트"),
            tools=tools,
            llm=llm_instance,
            verbose=True,
            allow_delegation=True
        )
        
        setattr(agent, "_llm_raw", llm_instance)
        return agent
        
    except Exception as e:
        logger.error(f"❌ 에이전트 생성 실패: {e}", exc_info=True)
        raise

# =============================
# 태스크 생성
# - 사용자 요청을 바탕으로 프롬프트를 만들고 플래닝 태스크를 생성합니다.
# =============================
async def create_user_task(
    task_instructions: str,
    agent: Agent,
    form_types: Dict | None = None,
    form_html: str = "",
    current_activity_name: str = "",
    feedback_summary: str = "",
    agent_info: List[Dict] | None = None,
    user_info: List[Dict] | None = None,
) -> Task:
    """사용자 요청을 바탕으로 동적 프롬프트 생성하여 단일 Task 생성"""
    try:
        logger.info("\n\n📝 동적 프롬프트 생성 시작...")
        
        # 동적 프롬프트 생성기 초기화 (에이전트의 LLM 사용)
        prompt_generator = DynamicPromptGenerator(llm=agent._llm_raw)
        
        # 원본 agent_info를 그대로 사용 (id만 필요)
        agent_dict_list = agent_info if agent_info else []
        
        # 동적 프롬프트 생성
        description, expected_output = await prompt_generator.generate_task_prompt(
            task_instructions=task_instructions,
            agent_info=agent_dict_list,
            form_types=form_types,
            form_html=form_html,
            feedback_summary=feedback_summary,
            current_activity_name=current_activity_name,
            user_info=user_info or []
        )
        
        task = Task(
            description=description,
            expected_output=expected_output,
            agent=agent
        )
        return task
        
    except Exception as e:
        logger.error(f"❌ 태스크 생성 실패: {e}", exc_info=True)
        raise

# =============================
# 크루 생성
# - 에이전트와 태스크를 구성해 실행 가능한 크루를 만듭니다.
# =============================
async def create_crew(
    agent_info: List[Dict] | None = None,
    task_instructions: str = "",
    form_types: Dict | None = None,
    form_html: str = "",
    current_activity_name: str = "",
    feedback_summary: str = "",
    user_info: List[Dict] | None = None,
    tenant_mcp: Dict | None = None,
):
    """에이전트/태스크를 구성해 크루를 생성합니다."""
    try:
        global _event_manager
        logger.info(f"🚀 동적 크루 생성 시작 - 에이전트: {len(agent_info) if agent_info else 0}개")
        
        # 글로벌 이벤트 훅 등록 (한 번만)
        if _event_manager is None:
            _event_manager = CrewConfigManager()
        
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
        
        agents = []
        logger.info(f"\n\n🔧 에이전트 생성 시작 : {agent_info}")
        for info in agent_info:
            try:
                user_id = info.get('id') or info.get('user_id')
                tenant_id = info.get('tenant_id')
                
                tools_str = info.get('tools', '')
                tool_names = [tool.strip() for tool in tools_str.split(',') if tool.strip()] if tools_str else []
                agent_name = info.get('username', 'unknown')
                logger.info(f"🔧 에이전트 '{agent_name}') 툴 목록: {tool_names}")
                loader = SafeToolLoader(tenant_id=tenant_id, user_id=user_id, agent_name=agent_name, mcp_config=tenant_mcp)
                
                try:
                    tools = loader.create_tools_from_names(tool_names)
                except Exception as e:
                    logger.warning(f"⚠️ 에이전트 '{agent_name}') 툴 로딩 실패(전파): {e}")
                    raise
                
                agent = create_dynamic_agent(info, tools)
                agents.append(agent)
                username = info.get('username') or info.get('name') or 'Unknown'
                logger.info(f"✅ 에이전트 '{agent_name}') 생성 완료, username: {username}")
                
            except Exception as e:
                username = info.get('username') or info.get('name') or 'Unknown'
                agent_name = info.get('name') or info.get('role') or "Agent"
                logger.warning(f"⚠️ 에이전트 '{agent_name}' ({info.get('role', 'Unknown')}) 생성 실패(전파) (username: {username}) - {e}")
                raise
        
        if not agents:
            # 안전 가드: 에이전트 생성 실패 시 기본 에이전트 1명 생성
            logger.warning("⚠️ 에이전트가 없어 기본 에이전트를 생성합니다.")
            default_agent = create_dynamic_agent({"role": "범용 AI 어시스턴트", "name": "Default"}, [])
            agents.append(default_agent)
        
        manager = agents[0]
        
        # 사용자 요청 기반 태스크 생성 (매니저 에이전트에 할당)
        task = await create_user_task(
            task_instructions=task_instructions,
            agent=manager,
            form_types=form_types,
            form_html=form_html,
            current_activity_name=current_activity_name,
            feedback_summary=feedback_summary,
            agent_info=agent_info,  # 원본 딕셔너리 리스트 전달
            user_info=user_info
        )
        logger.info("\n\n✅ 사용자 태스크 생성 완료")
        
        # CrewAI의 계층적 프로세스와 자동 위임 기능을 활용한 크루 생성
        crew = Crew(
            agents=agents,
            tasks=[task],
            process=Process.sequential,
            planning=True, 
            manager_llm=manager._llm_raw,
            verbose=True
        )
        
        logger.info(f"🎉 동적 크루 생성 완료 - 매니저: {manager.role}, 총 에이전트: {len(agents)}명")
        return crew
        
    except Exception as e:
        logger.error(f"❌ 크루 생성 실패: {e}", exc_info=True)
        raise 