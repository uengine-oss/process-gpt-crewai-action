import re
import json
import ast
import logging
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)
_RE_CODE_BLOCK = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)

def _parse_json_guard(text: str) -> Any:
    """문자열을 JSON으로 파싱."""
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        val = ast.literal_eval(text)
        return val
    except Exception as e:
        raise ValueError(f"JSON 파싱 실패: {e}")

def _to_form_dict(form_data: Any) -> Dict[str, Any]:
    """'폼_데이터'가 dict이면 그대로, list면 {'key':'text'} 매핑. 그 외 타입은 빈 dict."""
    if isinstance(form_data, dict):
        return form_data
    if isinstance(form_data, list):
        return {
            (item.get("key") if isinstance(item, dict) else None): 
            (item.get("text") if isinstance(item, dict) else None)
            for item in form_data
            if isinstance(item, dict) and "key" in item
        }
    return {}

def convert_crew_output(result, form_id: str = None) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    CrewOutput/문자열 -> JSON 파싱 -> '폼_데이터'만 추출/정규화 -> form_id로 래핑
    + 원본 JSON에서 '폼_데이터' 키 제거한 사본도 함께 반환.
    """
    try:
        # 1) 문자열 확보
        text = getattr(result, "raw", None) or str(result)

        # 2) ```json ... ``` 코드 블록 제거
        m = _RE_CODE_BLOCK.search(text)
        if m:
            text = m.group(1)

        # 3) JSON 파싱 (견고 가드레일)
        output_val = _parse_json_guard(text)

        # dict가 아니면 원본 구조로는 의미 없으니 dict로 강제 사용 불가 → 빈 사본
        original_wo_form = dict(output_val) if isinstance(output_val, dict) else {}

        # 4) 폼_데이터 추출/정규화
        form_raw = output_val.get("폼_데이터") if isinstance(output_val, dict) else None
        pure_form_data = _to_form_dict(form_raw)

        # 5) form_id 래핑 (요청사항: form_id로 {} 해서 dict 반환)
        wrapped_form_data = {form_id: pure_form_data} if form_id else pure_form_data

        # 6) 원본에서 '폼_데이터' 제거
        if isinstance(original_wo_form, dict):
            original_wo_form.pop("폼_데이터", None)

        return pure_form_data, wrapped_form_data, original_wo_form

    except Exception as e:
        logger.error(f"❌ Crew 결과 변환 실패: {e}", exc_info=True)
        raise
