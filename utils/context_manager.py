from contextvars import ContextVar
from typing import Optional, Any
import json
import asyncio
from utils.logger import handle_error, log
from typing import Callable
import random
from llm_factory import create_llm

todo_id_var: ContextVar[Optional[int]] = ContextVar('todo_id', default=None)
proc_id_var: ContextVar[Optional[str]] = ContextVar('proc_inst_id', default=None)
human_users_var: ContextVar[Optional[str]] = ContextVar('human_users', default=None)

# ============================================================================
# 요약 처리
# ============================================================================

async def summarize_query_async(query: str, agent_info: Any = None) -> str:
    """LLM으로 query 요약 - 핵심정보 유지, 짧으면 보강"""
    try:
        if not query or not query.strip():
            return query
            
        log("Query 요약을 위한 LLM 호출 시작")
        
        # 사용할 LLM 결정: 에이전트 정보의 첫 번째 모델을 사용 (없으면 기본값)
        provider = None
        model_name = "gpt-4.1"
        if isinstance(agent_info, list) and agent_info:
            model_str = agent_info[0].get("model") if isinstance(agent_info[0], dict) else None
            if model_str:
                if "/" in model_str:
                    provider, model_name = model_str.split("/", 1)
                else:
                    model_name = model_str
        llm = create_llm(provider=provider, model=model_name, temperature=0.1)
        
        # Query 요약 프롬프트 생성
        prompt = _create_query_summary_prompt(query)
        
        # LLM 호출
        result = await _call_llm_async(llm, prompt, "query")
        
        log(f"Query 요약 완료: {len(result)}자")
        return result
        
    except Exception as e:
        # 요약 실패 시 원본 query 반환
        handle_error("Query요약오류", e, raise_error=False)
        return query

async def summarize_async(outputs: Any, feedbacks: Any, contents: Any = None, agent_info: Any = None) -> tuple[str, str]:
    """LLM으로 컨텍스트 요약 - 병렬 처리로 별도 반환 (비동기)"""
    try:
        log("요약을 위한 LLM 병렬 호출 시작")
        
        # 데이터 준비
        outputs_str = _convert_to_string(outputs)
        feedbacks_str = _convert_to_string(feedbacks) if any(item for item in (feedbacks or []) if item and item != {}) else ""
        contents_str = _convert_to_string(contents) if contents and contents != {} else ""
        
        # 사용할 LLM 결정: 에이전트 정보의 첫 번째 모델을 사용 (없으면 기본값)
        provider = None
        model_name = "gpt-4.1"
        if isinstance(agent_info, list) and agent_info:
            model_str = agent_info[0].get("model") if isinstance(agent_info[0], dict) else None
            if model_str:
                if "/" in model_str:
                    provider, model_name = model_str.split("/", 1)
                else:
                    model_name = model_str
        llm = create_llm(provider=provider, model=model_name, temperature=0.1)
        
        # 병렬 처리
        output_summary, feedback_summary = await _summarize_parallel(outputs_str, feedbacks_str, contents_str, llm)
        
        log(f"이전결과 요약 완료: {len(output_summary)}자, 피드백 요약 완료: {len(feedback_summary)}자")
        return output_summary, feedback_summary
        
    except Exception as e:
        # 요약 실패는 작업 자체를 실패로 처리(폴링은 상위에서 계속)
        handle_error("요약오류", e, raise_error=True)

async def _summarize_parallel(outputs_str: str, feedbacks_str: str, contents_str: str = "", llm: Any = None) -> tuple[str, str]:
    """병렬로 요약 처리 - 별도 반환"""
    tasks = []
    
    # 1. 이전 결과물 요약 태스크 (데이터가 있을 때만)
    if outputs_str and outputs_str.strip():
        output_prompt = _create_output_summary_prompt(outputs_str)
        tasks.append(_call_llm_async(llm, output_prompt, "이전 결과물"))
    else:
        tasks.append(_create_empty_task(""))
    
    # 2. 피드백 요약 태스크 (피드백 또는 현재 결과물이 있을 때만)
    if (feedbacks_str and feedbacks_str.strip()) or (contents_str and contents_str.strip()):
        feedback_prompt = _create_feedback_summary_prompt(feedbacks_str, contents_str)
        tasks.append(_call_llm_async(llm, feedback_prompt, "피드백"))
    else:
        tasks.append(_create_empty_task(""))
    
    # 3. 두 태스크를 동시에 실행하고 완료될 때까지 대기
    output_summary, feedback_summary = await asyncio.gather(*tasks)
    
    # 4. 별도로 반환
    return output_summary, feedback_summary

async def _create_empty_task(result: str) -> str:
    """빈 태스크 생성 (즉시 완료)"""
    return result

def _convert_to_string(data: Any) -> str:
    """데이터를 문자열로 변환"""
    if isinstance(data, str):
        return data
    return json.dumps(data, ensure_ascii=False)

def _create_query_summary_prompt(query: str) -> str:
    """Query 요약 프롬프트 - 핵심정보 유지, 짧으면 보강"""
    return f"""다음 사용자 요청(query)을 분석하고 적절히 처리해주세요:

{query}

**처리 원칙:**
1. **내용이 짧거나 불완전한 경우**: 
   - 원본 내용을 그대로 유지하되, 필요한 맥락이나 세부사항을 보강
   - 누락된 정보가 있다면 추론하여 추가
   - 더 명확하고 구체적으로 작성

2. **내용이 긴 경우**:
   - 핵심 요청사항과 목적을 파악하여 요약
   - **수치, 목차, 인물명, 물건명, 날짜, 시간, 파일명, URL 등 구체적 정보는 반드시 보존**
   - 지시사항과 설명은 그대로 유지
   - 각 섹션별로 내용만 요약하고 구체적인 수치 정보는 유지, 
   - 중복되거나 불필요한 부분만 정리

3. **공통 원칙**:
   - 원본 의미와 의도를 절대 변경하지 않음
   - 사용자의 실제 요구사항을 정확히 파악
   - 다음 작업자가 즉시 이해하고 실행할 수 있도록 명확하게 작성
   - 자연스럽고 완전한 문장으로 구성

**출력**: 원본 요청의 핵심을 보존하면서 적절히 처리된 완전한 요청문"""

def _create_output_summary_prompt(outputs_str: str) -> str:
    """이전 결과물 요약 프롬프트"""
    return f"""다음 작업 결과를 정리해주세요:

{outputs_str}

처리 방식:
- **짧은 내용은 요약하지 말고 그대로 유지** (정보 손실 방지)
- 긴 내용만 적절히 요약하여 핵심 정보 전달
- **수치, 목차, 인물명, 물건명, 날짜, 시간 등 객관적 정보는 반드시 포함**
- 왜곡이나 의미 변경 절대 금지, 원본 의미 그대로 보존
- 중복된 부분만 정리하고 핵심 내용은 모두 보존
- 하나의 통합된 문맥으로 작성"""

def _create_feedback_summary_prompt(feedbacks_str: str, contents_str: str = "") -> str:
    """피드백 정리 프롬프트 - 현재 결과물과 피드백을 함께 분석"""
    
    # 피드백과 현재 결과물 모두 준비
    feedback_section = f"""=== 피드백 내용 ===
{feedbacks_str}""" if feedbacks_str and feedbacks_str.strip() else ""
    
    content_section = f"""=== 현재 결과물/작업 내용 ===
{contents_str}""" if contents_str and contents_str.strip() else ""
    
    return f"""다음은 사용자의 피드백과 결과물입니다. 이를 분석하여 통합된 피드백을 작성해주세요:

{feedback_section}

{content_section}

**상황 분석 및 처리 방식:**
- **현재 결과물을 보고 어떤 점이 문제인지, 개선이 필요한지 판단**
- 피드백이 있다면 그 의도와 요구사항을 정확히 파악
- 결과물 자체가 마음에 안들어서 다시 작업을 요청하는 경우일 수 있음
- 작업 방식이나 접근법이 잘못되었다고 판단하는 경우일 수 있음
- 부분적으로는 좋지만 특정 부분의 수정이나 보완이 필요한 경우일 수 있음
- 현재 결과물에 매몰되지 말고, 실제 어떤 부분이 문제인지 파악하여 개선 방안을 제시

**피드백 통합 원칙:**
- **가장 최신 피드백을 최우선으로 반영**
- 결과물과 피드백을 종합적으로 분석하여 핵심 문제점 파악
- **시간 흐름을 파악하여 피드백들 간의 연결고리와 문맥을 이해**
- 구체적이고 실행 가능한 개선사항 제시
- **자연스럽고 통합된 하나의 완전한 피드백으로 작성**
- 최대 2500자까지 허용하여 상세히 작성

**중요한 상황별 처리:**
- 결과물 품질에 대한 불만 → **품질 개선** 요구
- 작업 방식에 대한 불만 → **접근법 변경** 요구  
- 이전에 저장을 했는데 잘못 저장되었다면 → **수정**이 필요
- 이전에 조회만 했는데 저장이 필요하다면 → **저장**이 필요
- 부분적 수정이 필요하다면 → **특정 부분 개선** 요구

출력 형식: 현재 상황을 종합적으로 분석한 완전한 피드백 문장 (다음 작업자가 즉시 이해하고 실행할 수 있도록)
"""


def _get_query_system_prompt() -> str:
    """Query 요약용 시스템 프롬프트"""
    return """당신은 사용자 요청(query) 처리 전문가입니다.

핵심 원칙:
- **짧은 요청은 보강**: 불완전하거나 모호한 부분을 명확하게 보완
- **긴 요청은 요약**: 핵심 요구사항만 추출하여 간결하게 정리
- **구체적 정보 보존**: 수치, 이름, 날짜, 파일명, URL 등은 절대 변경하지 않음
- **원본 의도 유지**: 사용자의 실제 목적과 요구사항을 정확히 파악
- **실행 가능성**: 다음 작업자가 즉시 이해하고 실행할 수 있도록 명확하게 작성
- **자연스러운 문장**: 완전하고 자연스러운 요청문으로 구성"""

def _get_feedback_system_prompt() -> str:
    """피드백 요약용 시스템 프롬프트"""
    return """당신은 피드백 정리 전문가입니다.

핵심 원칙:
- 최신 피드백을 최우선으로 하여 시간 흐름을 파악
- 피드백 간 문맥과 연결고리를 파악하여 하나의 완전한 요청으로 통합
- 자연스럽고 통합된 피드백으로 작성
- 구체적인 요구사항과 개선사항을 누락 없이 포함
- 다음 작업자가 즉시 이해할 수 있도록 명확하게"""

def _get_output_system_prompt() -> str:
    """결과물 요약용 시스템 프롬프트"""
    return """당신은 결과물 요약 전문가입니다.

핵심 원칙:
- **짧은 내용은 요약하지 말고 그대로 유지** (오히려 정보 손실 위험)
- 긴 내용만 적절히 요약하여 핵심 정보 전달
- **왜곡이나 의미 변경 절대 금지, 원본 의미 그대로 보존**
- **수치, 목차, 인물명, 물건명, 날짜, 시간 등 객관적 정보는 반드시 포함**
- 객관적 사실만 포함, 불필요한 부연설명만 제거
- 하나의 통합된 문맥으로 작성
- 다음 작업자가 즉시 이해할 수 있도록 명확하게
- 중복된 부분만 정리하고 핵심 내용은 모두 보존"""

async def _call_llm_async(llm: Any, prompt: str, task_name: str) -> str:
    """LangChain LLM 비동기 호출 (지수 백오프 재시도)"""
    if task_name == "query":
        system_prompt = _get_query_system_prompt()
    elif task_name == "피드백":
        system_prompt = _get_feedback_system_prompt()
    else:
        system_prompt = _get_output_system_prompt()

    async def _once() -> str:
        response = await llm.ainvoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ])
        content = getattr(response, "content", None)
        return (content or str(response)).strip()

    async def _retry(fn: Callable[[], Any], *, retries: int = 3, base_delay: float = 0.8) -> str:
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                return await fn()
            except Exception as e:
                last_error = e
                # 5xx / 커넥션 계열은 재시도 가치가 높음 → 동일 정책 일괄 적용
                jitter = random.uniform(0, 0.3)
                delay = base_delay * (2 ** (attempt - 1)) + jitter
                handle_error(
                    "요약재시도",
                    e,
                    raise_error=False,
                    extra={"delay": round(delay, 2), "attempt": attempt, "retries": retries},
                )
                await asyncio.sleep(delay)
        # 모든 재시도 실패 → 예외 재던지기(작업 중단), 폴링은 상위에서 계속
        handle_error("요약실패", last_error or Exception("unknown"), raise_error=True)
        return ""

    result = await _retry(_once)
    if result:
        log(f"요약완료: {len(result)}자")
    return result