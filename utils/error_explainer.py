import json
from typing import Optional, Dict

from llm_factory import create_llm


def generate_user_error_message(*, stage: str, message: str, context: Optional[Dict] = None) -> str:
    """LLM으로 사용자 친화적 오류 설명을 생성.

    입력: 단계명, 원본 오류 메시지, 컨텍스트(그대로 전달)
    출력: 한국어 2~3문장 요약(원인 + 즉시 조치 방안)
    """
    llm = create_llm(model="gpt-4.1-mini", temperature=0.0)

    system_prompt = (
        "당신은 사용자에게 오류를 간결하고 친절하게 설명하는 도우미입니다. "
        "2~3문장으로 원인 요약과 한 가지 즉시 행동 방안을 제시하세요. "
        "내부 기술 세부사항이나 민감정보는 포함하지 마세요. 한국어로 답변하세요."
    )

    user_prompt = (
        f"단계: {stage}\n"
        f"오류: {message}\n"
        f"컨텍스트: {json.dumps(context or {}, ensure_ascii=False)}"
    )

    response = llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ])

    text = getattr(response, "content", "").strip() or str(response).strip()
    return text


