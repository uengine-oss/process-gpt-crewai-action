import os
from typing import Optional, List, Dict
import logging
from crewai import Crew, Process, Agent, Task
from llm import create_llm
from processgpt_agent_utils.utils.crew_event_logger import CrewConfigManager
from processgpt_agent_utils.tools.safe_tool_loader import SafeToolLoader
from prompt_generator import DynamicPromptGenerator

# 로깅 설정
logger = logging.getLogger(__name__)

# =============================
# 도구 우선순위 정책
# - "작업 플랜" 단계에서 먼저 고려해야 할 도구의 순서를 강제합니다.
# - 스킬: agent_info.get("skills")로 정의되며, 실제 사용은 claude-skills/computer-use MCP 도구로 수행.
# - 요구사항: (스킬이 있을 경우) 1) 스킬용 도구 2) dmn_rule 3) mem0 4) 기타 tools(memento/기타 MCP 등)
#
# 사용자 커스텀 우선순위 (agent_info.tool_priority_order):
# - 형식: 문자열 리스트. 순서 = 우선순위(앞일수록 높음).
# - 각 항목: 스킬명(에이전트에 할당된 스킬) 또는 MCP 서버명("claude-skills", "computer-use") 또는 도구명("dmn_rule", "mem0", "memento" 등).
# - 스킬명: 내부에서 claude-skills/computer-use로 매핑. (추후 도구에 _processgpt_skill_id 태깅 시 스킬 간 우선순위 지원 예정)
# - "*": 리스트에 포함 시, 나머지 미기재 도구는 이 위치에 묶임. 생략 시 미기재 도구는 맨 뒤.
# - 예: ["quiz-management-skill", "dmn_rule", "mem0", "*"] 또는 ["claude-skills", "dmn_rule", "mem0", "*"]
# - 제공하지 않거나 빈 리스트면 아래 기본 순서 사용.
# =============================
SKILL_MCP_SERVERS = {"claude-skills", "computer-use"}

# 기본 도구 우선순위 (사용자 custom_order 없을 때 사용)
DEFAULT_TOOL_PRIORITY_WITH_SKILLS = ["claude-skills", "computer-use", "dmn_rule", "mem0", "*"]
DEFAULT_TOOL_PRIORITY_NO_SKILLS = ["dmn_rule", "mem0", "*"]


class TaggedSafeToolLoader(SafeToolLoader):
    """MCP 서버 출처를 Tool 객체에 태깅하는 SafeToolLoader 래퍼.

    crewai_tools.MCPServerAdapter가 반환하는 Tool 객체는 기본적으로 '어느 MCP 서버에서 왔는지' 정보가 없어서
    우선순위 정렬을 위해 서버 키를 attribute로 주입합니다.
    """

    def _load_mcp_tool(self, tool_name: str) -> List:
        tools = super()._load_mcp_tool(tool_name)
        for t in tools or []:
            try:
                setattr(t, "_processgpt_mcp_server", tool_name)
            except Exception:
                # 일부 Tool 구현은 setattr이 막혀 있을 수 있어 무시합니다.
                pass
        return tools


def _get_tool_name(tool) -> str:
    name = getattr(tool, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return tool.__class__.__name__


def _get_agent_skill_names(skills) -> List[str]:
    """agent_info['skills']에서 스킬명/ID 리스트 추출.

    지원 형식: 문자열(쉼표 구분), 리스트[문자열], 리스트[dict with name/id].
    """
    if not skills:
        return []
    result = []
    if isinstance(skills, str):
        result.extend(s.strip() for s in skills.split(",") if s.strip())
    elif isinstance(skills, list):
        for x in skills:
            if isinstance(x, str) and x.strip():
                result.append(x.strip())
            elif isinstance(x, dict):
                name = x.get("name") or x.get("id") or x.get("skill_id")
                if name and str(name).strip():
                    result.append(str(name).strip())
    return list(dict.fromkeys(result))


def _normalize_tool_priority_for_sorting(
    custom_order: List[str],
    agent_skills: List[str],
) -> tuple:
    """custom_order를 우선순위 정렬용 idx_map으로 변환.

    - 스킬명(agent_skills에 있음): claude-skills, computer-use로 확장(동일 우선순위).
      추후 도구에 _processgpt_skill_id 태깅 시 스킬명 직접 매칭 가능하도록 스킬명도 idx_map에 포함.
    - 여러 스킬이 있을 때: 첫 번째 스킬의 위치에 MCP 매핑(현재는 MCP 단위만 구분 가능).
    반환: (idx_map: Dict[str, int], wildcard_idx: int)
    """
    agent_skills_set = {s.lower() for s in agent_skills if s}
    idx_map: Dict[str, int] = {}
    wildcard_idx = 0
    for i, item in enumerate(custom_order):
        if not isinstance(item, str) or not item.strip():
            continue
        key = item.strip().lower()
        if key == "*":
            wildcard_idx = i
            idx_map["*"] = i
            continue
        if key in agent_skills_set:
            # 스킬 → MCP 매핑(첫 등장 시에만, 스킬 간 우선순위가 동일하게 적용되도록)
            for mcp in SKILL_MCP_SERVERS:
                if mcp not in idx_map:
                    idx_map[mcp] = i
            # 추후 스킬별 도구 태깅 지원용
            idx_map[key] = i
        else:
            idx_map[key] = i
    if "*" not in idx_map:
        wildcard_idx = max(idx_map.values(), default=-1) + 1
    return idx_map, wildcard_idx


def _tool_identity(tool) -> str:
    """도구의 우선순위 매칭용 식별자: MCP 서버명 또는 도구명.

    추후: getattr(tool, "_processgpt_skill_id", None)가 있으면 스킬별 매칭 지원 가능.
    """
    server = getattr(tool, "_processgpt_mcp_server", None)
    if isinstance(server, str) and server.strip():
        return server.strip().lower()
    return _get_tool_name(tool).lower()


def prioritize_tools(
    tools: List,
    has_skills: bool = False,
    custom_order: Optional[List[str]] = None,
    agent_skills: Optional[List[str]] = None,
) -> List:
    """도구 우선순위 정렬(안정 정렬).

    has_skills: agent_info.get("skills")가 있을 때 True. custom_order 없을 때만 사용.
    custom_order: 사용자 지정 우선순위 리스트(앞일수록 높음). 스킬명, MCP명, 도구명 혼합 가능.
    agent_skills: 에이전트에 할당된 스킬명 리스트. custom_order의 스킬명을 MCP로 매핑할 때 사용.
    """
    if not tools:
        return []

    if custom_order and len(custom_order) > 0:
        order_list = [s.strip() for s in custom_order if isinstance(s, str) and s.strip()]
        if not order_list:
            custom_order = None
        else:
            skills = agent_skills or []
            idx_map, wildcard_idx = _normalize_tool_priority_for_sorting(order_list, skills)

            def sort_key(it):
                idx, t = it
                identity = _tool_identity(t)
                priority = idx_map.get(identity, wildcard_idx)
                return (priority, idx)

            indexed = list(enumerate(tools))
            indexed.sort(key=sort_key)
            return [t for _, t in indexed]

    # 기본 우선순위(커스텀 없을 때)
    def bucket(t) -> int:
        server = getattr(t, "_processgpt_mcp_server", None)
        if has_skills and isinstance(server, str) and server.strip().lower() in SKILL_MCP_SERVERS:
            return 0
        n = _get_tool_name(t).lower()
        if n == "dmn_rule":
            return 1
        if n == "mem0":
            return 2
        return 3

    indexed = list(enumerate(tools))
    indexed.sort(key=lambda it: (bucket(it[1]), it[0]))
    return [t for _, t in indexed]


# MCP/HTTP 연결 오류를 위한 예외 타입 임포트 시도
try:
    import httpx
    HTTP_CONNECTION_ERRORS = (httpx.RemoteProtocolError, httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)
except ImportError:
    # httpx가 없으면 기본 예외만 사용
    HTTP_CONNECTION_ERRORS = (ConnectionError,)

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
        model_str = agent_info.get("model") or os.getenv("LLM_MODEL") or ""
        model_name = model_str.split("/", 1)[1] if "/" in model_str else (model_str or None)

        llm_instance = create_llm(
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
    sources: List[Dict] | None = None,
    tool_priority_order: Optional[List[str]] = None,
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
            user_info=user_info or [],
            sources=sources or [],
            tool_priority_order=tool_priority_order,
        )
        
        # 플래닝에서 필요한 InputData 원본만 description 뒤에 덧붙인다 (Description/Instruction은 제외)
        input_section = ""
        if task_instructions:
            marker = "[InputData]"
            if marker in task_instructions:
                input_section = task_instructions.split(marker, 1)[1].strip()
        raw_input_appendix = (
            "\n\n=== 입력 데이터 원본 (InputData) ===\n"
            "- 아래 InputData 컨텍스트를 참고해 작업을 진행하세요.\n"
            f"{input_section}\n\n"
        ) if input_section else ""
        task = Task(
            description=f"{description}{raw_input_appendix}",
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
    sources: List[Dict] | None = None,
    tenant_id: str = "",
    tool_priority_order: Optional[List[str]] = None,
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
                tenant_id = info.get('tenant_id') or tenant_id
                
                tools_str = info.get('tools', '')
                tool_names = [tool.strip() for tool in tools_str.split(',') if tool.strip()] if tools_str else []
                agent_name = info.get('username', 'unknown')
                has_skills = bool(info.get('skills'))  # 스킬 보유 시 claude-skills/computer-use 도구를 1순위로 정렬
                custom_order = info.get('tool_priority_order') or info.get('tool_priority')
                if not (isinstance(custom_order, list) and len(custom_order) > 0):
                    custom_order = None
                agent_skills = _get_agent_skill_names(info.get('skills'))
                logger.info(f"🔧 에이전트 '{agent_name}') 툴 목록: {tool_names}, 스킬 보유: {has_skills}, 커스텀 우선순위: {bool(custom_order)}")
                
                tools = []
                loader = None
                try:
                    loader = TaggedSafeToolLoader(tenant_id=tenant_id, user_id=user_id, agent_name=agent_name, mcp_config=tenant_mcp)
                    tools = loader.create_tools_from_names(tool_names)
                    tools = prioritize_tools(tools, has_skills=has_skills, custom_order=custom_order, agent_skills=agent_skills)
                    logger.info(f"✅ 에이전트 '{agent_name}') 툴 로딩 성공: {len(tools)}개")
                except HTTP_CONNECTION_ERRORS as e:
                    # HTTP/MCP 연결 오류인 경우 - 도구 없이 계속 진행
                    logger.warning(f"⚠️ 에이전트 '{agent_name}') 툴 로딩 실패 (HTTP/MCP 연결 오류) - 도구 없이 계속 진행: {type(e).__name__}: {e}")
                    tools = []  # 빈 도구 리스트로 계속 진행
                    # 로더가 생성되었지만 실패한 경우 정리 시도
                    if loader is not None:
                        try:
                            SafeToolLoader.shutdown_all_adapters()
                        except Exception as cleanup_error:
                            logger.warning(f"⚠️ MCP 어댑터 정리 중 오류(무시): {cleanup_error}")
                except Exception as e:
                    # 기타 예외인 경우도 도구 없이 계속 진행하되 로그 기록
                    logger.warning(f"⚠️ 에이전트 '{agent_name}') 툴 로딩 실패 (기타 오류) - 도구 없이 계속 진행: {type(e).__name__}: {e}")
                    tools = []  # 빈 도구 리스트로 계속 진행
                    # 로더가 생성되었지만 실패한 경우 정리 시도
                    if loader is not None:
                        try:
                            SafeToolLoader.shutdown_all_adapters()
                        except Exception as cleanup_error:
                            logger.warning(f"⚠️ MCP 어댑터 정리 중 오류(무시): {cleanup_error}")
                
                agent = create_dynamic_agent(info, tools)
                agents.append(agent)
                username = info.get('username') or info.get('name') or 'Unknown'
                logger.info(f"✅ 에이전트 '{agent_name}') 생성 완료, username: {username}")
                
            except Exception as e:
                username = info.get('username') or info.get('name') or 'Unknown'
                agent_name = info.get('name') or info.get('role') or "Agent"
                logger.error(f"❌ 에이전트 '{agent_name}' ({info.get('role', 'Unknown')}) 생성 실패 (username: {username}) - {e}", exc_info=True)
                raise
        
        if not agents:
            # 안전 가드: 에이전트 생성 실패 시 기본 에이전트 1명 생성
            logger.warning("⚠️ 에이전트가 없어 기본 에이전트를 생성합니다.")
            default_agent = create_dynamic_agent({"role": "범용 AI 어시스턴트", "name": "Default"}, [])
            agents.append(default_agent)
        
        manager = agents[0]

        # 매니저(첫 에이전트) 기준 도구 우선순위: 인자로 넘어온 값 > 첫 에이전트 설정 > 기본
        first_info = agent_info[0] if agent_info else {}
        has_skills_0 = bool(first_info.get("skills"))
        first_agent_skills = _get_agent_skill_names(first_info.get("skills"))
        effective_priority_order = tool_priority_order
        if not (isinstance(effective_priority_order, list) and len(effective_priority_order) > 0):
            effective_priority_order = first_info.get("tool_priority_order") or first_info.get("tool_priority")
        if not (isinstance(effective_priority_order, list) and len(effective_priority_order) > 0):
            if has_skills_0 and first_agent_skills:
                # 스킬이 있으면 첫 스킬명을 사용해 기본 순서 구성(프롬프트 표시용)
                effective_priority_order = [first_agent_skills[0], "dmn_rule", "mem0", "*"]
            else:
                effective_priority_order = (
                    DEFAULT_TOOL_PRIORITY_WITH_SKILLS if has_skills_0 else DEFAULT_TOOL_PRIORITY_NO_SKILLS
                )

        # 사용자 요청 기반 태스크 생성 (매니저 에이전트에 할당)
        task = await create_user_task(
            task_instructions=task_instructions,
            agent=manager,
            form_types=form_types,
            form_html=form_html,
            current_activity_name=current_activity_name,
            feedback_summary=feedback_summary,
            agent_info=agent_info,  # 원본 딕셔너리 리스트 전달
            user_info=user_info,
            sources=sources,
            tool_priority_order=effective_priority_order,
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