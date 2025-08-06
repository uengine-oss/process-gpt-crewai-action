from contextvars import ContextVar
from typing import Optional, Any
import json
import asyncio
import openai
from utils.logger import handle_error, log

todo_id_var: ContextVar[Optional[int]] = ContextVar('todo_id', default=None)
proc_id_var: ContextVar[Optional[str]] = ContextVar('proc_inst_id', default=None)

# ============================================================================
# 요약 처리
# ============================================================================

async def summarize_async(outputs: Any, feedbacks: Any, drafts: Any = None) -> tuple[str, str]:
    """LLM으로 컨텍스트 요약 - 병렬 처리로 별도 반환 (비동기)"""
    try:
        log("요약을 위한 LLM 병렬 호출 시작")
        
        # 데이터 준비
        outputs_str = _convert_to_string(outputs)
        feedbacks_str = _convert_to_string(feedbacks) if any(item for item in (feedbacks or []) if item and item != {}) else ""
        
        # 병렬 처리
        output_summary, feedback_summary = await _summarize_parallel(outputs_str, feedbacks_str)
        
        log(f"이전결과 요약 완료: {len(output_summary)}자, 피드백 요약 완료: {len(feedback_summary)}자")
        return output_summary, feedback_summary
        
    except Exception as e:
        handle_error("요약처리", e)
        return "", ""

async def _summarize_parallel(outputs_str: str, feedbacks_str: str) -> tuple[str, str]:
    """병렬로 요약 처리 - 별도 반환"""
    tasks = []
    
    # 1. 이전 결과물 요약 태스크 (데이터가 있을 때만)
    if outputs_str and outputs_str.strip():
        output_prompt = _create_output_summary_prompt(outputs_str)
        tasks.append(_call_openai_api_async(output_prompt, "이전 결과물"))
    else:
        tasks.append(_create_empty_task(""))
    
    # 2. 피드백 요약 태스크 (데이터가 있을 때만)
    if feedbacks_str and feedbacks_str.strip():
        feedback_prompt = _create_feedback_summary_prompt(feedbacks_str)
        tasks.append(_call_openai_api_async(feedback_prompt, "피드백"))
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

def _create_feedback_summary_prompt(feedbacks_str: str) -> str:
    """피드백 정리 프롬프트 - 최신 피드백 최우선, 이전 피드백은 참고용"""
    return f"""다음은 시간순으로 정렬된 피드백 데이터입니다. **가장 최신 피드백이 최우선**이며, 이전 피드백들은 상황을 이해하기 위한 참고 정보입니다:

{feedbacks_str}

처리 방식:
- **가장 최신(time이 늦은) 피드백을 최우선으로 반영**
- 이전 피드백들은 상황 맥락을 이해하기 위한 참고 정보로만 활용
- **시간 흐름을 파악하여 피드백들 간의 연결고리와 문맥을 이해**
- 최신 피드백의 요구사항이 이전과 다르면 최신 것을 따라야 함
- 최신 피드백에서 요구하는 정확한 액션을 명확히 파악
- **자연스럽고 통합된 하나의 완전한 피드백으로 작성**
- 최대 2500자까지 허용하여 상세히 작성

**중요한 상황별 처리**:
- 이전에 저장을 했는데 잘못 저장되었다면 → **수정**이 필요 (다시 저장하면 안됨)
- 이전에 조회만 했는데 저장이 필요하다면 → **저장**이 필요
- 최신 피드백에서 명시한 요구사항이 절대 우선

통합 예시:
1번 피드백: "정보 저장을 요청했는데 조회만 했다"
2번 피드백: "정보 저장을 하긴 했으나 잘못 저장되어서 수정을 요청"
→ 통합 결과: "이전에 저장된 정보가 잘못되었으므로, 올바른 정보로 수정이 필요하다"

출력 형식: 최신 피드백의 요구사항을 중심으로 한 완전한 피드백 문장
"""


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

async def _call_openai_api_async(prompt: str, task_name: str) -> str:
    """OpenAI API 병렬 호출"""
    try:
        # OpenAI 클라이언트를 async로 생성
        client = openai.AsyncOpenAI()
        
        # 작업 유형에 따른 시스템 프롬프트 선택
        if task_name == "피드백":
            system_prompt = _get_feedback_system_prompt()
        else:  # "이전 결과물" 등 다른 모든 경우
            system_prompt = _get_output_system_prompt()
        
        response = await client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        
        result = response.choices[0].message.content.strip()
        log(f"{task_name} 요약 완료: {len(result)}자")
        return result
        
    except Exception as e:
        handle_error(f"{task_name} OpenAI API 호출", e)
        return "요약 생성 실패"