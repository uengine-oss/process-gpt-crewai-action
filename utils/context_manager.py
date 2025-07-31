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
    return f"""다음 작업 결과를 하나의 자연스러운 문맥으로 간결하게 요약해주세요:

{outputs_str}

핵심만 추출하여 중복 없이 작성하세요:
- 짧은 내용은 짧게 (200-500자)
- 복잡한 내용만 자세히 (최대 1500자)
- 객관적 사실만 포함
- 하나의 통합된 문맥으로 작성"""

def _create_feedback_summary_prompt(feedbacks_str: str) -> str:
    """피드백 정리 프롬프트 - 시간 기반 우선순위, 상세 보존"""
    return f"""다음은 피드백 데이터입니다. time 필드를 확인하여 가장 최근 피드백을 우선 반영하되, 모든 피드백을 누락 없이 포함해주세요:

{feedbacks_str}

처리 방식:
- time 필드가 가장 나중인 피드백을 최우선으로 상세히 반영
- 이전 피드백들도 모두 포함하여 통합적으로 정리
- 요약을 최소화하고 원본 내용을 최대한 보존
- 구체적인 요구사항, 개선사항, 수정사항을 모두 누락 없이 포함
- 최대 2500자까지 허용하여 상세히 작성
즉, 첫 번째 피드백에서 "정보 저장"을 요청했고, 두 번째 피드백에서 "특정 정보가 잘못 저장되어 수정이 필요"라고 했다면, 이 둘을 연결하여 "이전에 저장된 정보를 수정해야 함"과 같이 문맥을 자연스럽게 연결해주세요.
이는, 정보를 저장했는데 잘못 저장이되어서 수정이 필요한 상황이므로, 또 저장을 하면 안되니까, 자연스러운 피드백이 되도록 해야합니다.

출력 형식 예시 : 
주문 정보 저장 시 제품명은 한글로 표기하고, 이전에 저장된 주문 정보의 총 가격이 0.00으로 저장되었는데, 실제 주문 수량에 맞는 정확한 총 가격으로 수정이 필요.
"""


def _get_system_prompt() -> str:
    """시스템 프롬프트"""
    return """당신은 정확한 정보 정리 전문가입니다.

핵심 원칙:
- 피드백의 경우: 최신 피드백 우선, 상세 내용 최대한 보존
- 결과물의 경우: 적절한 요약으로 핵심 정보 전달
- 객관적 사실만 포함, 불필요한 부연설명 제거
- 다음 작업자가 즉시 이해할 수 있도록 명확하게
- 시간 순서와 우선순위를 고려하여 구성
- 구체적인 요구사항과 개선사항을 누락 없이 포함"""

async def _call_openai_api_async(prompt: str, task_name: str) -> str:
    """OpenAI API 병렬 호출"""
    try:
        # OpenAI 클라이언트를 async로 생성
        client = openai.AsyncOpenAI()
        
        response = await client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": _get_system_prompt()},
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