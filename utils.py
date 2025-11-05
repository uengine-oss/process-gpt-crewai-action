import re
import json
import ast
import logging
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)
_RE_CODE_BLOCK = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)
_RE_BACKTICK_VALUE = re.compile(r'(:\s*)`([\s\S]*?)`')  # JSON value 자리에 백틱으로 감싼 리터럴

def _repair_backtick_value_literals(text: str) -> str:
    """
    JSON 객체 내에서 값이 백틱(` ... `)으로 감싸진 경우를
    정상적인 JSON 문자열 값("...")으로 변환한다(개행/따옴표 등 안전 이스케이프).
    예: "newsletter_report": `# 제목\n내용`  ->  "newsletter_report": "# 제목\\n내용"
    """
    def _repl(m: re.Match) -> str:
        prefix = m.group(1)      # ":\s*"
        raw = m.group(2)         # 백틱 내부 원문
        escaped = json.dumps(raw) # JSON-safe string (따옴표/개행 이스케이프)
        return f"{prefix}{escaped}"
    return _RE_BACKTICK_VALUE.sub(_repl, text)

def _extract_json_from_text(text: str) -> str:
    """
    텍스트에서 JSON 객체를 추출합니다.
    1. 코드펜스 내부를 우선 추출
    2. 없으면 마지막에 나오는 JSON 객체를 찾아 추출 (중괄호 카운팅 방식)
    """
    # 1) 코드펜스 내부만 추출(있으면)
    m = _RE_CODE_BLOCK.search(text)
    if m:
        return m.group(1)
    
    # 2) 코드펜스가 없으면 마지막에 나오는 JSON 객체 찾기
    # 텍스트 끝에서부터 역순으로 검색하여 첫 번째 '{'를 찾고, 중괄호 매칭
    last_open_brace = text.rfind('{')
    if last_open_brace == -1:
        # 중괄호가 없으면 원본 반환
        return text
    
    # 중괄호 카운팅으로 올바른 JSON 객체 추출
    brace_count = 0
    start_idx = last_open_brace
    in_string = False
    escape_next = False
    
    for i in range(start_idx, len(text)):
        char = text[i]
        
        if escape_next:
            escape_next = False
            continue
        
        if char == '\\':
            escape_next = True
            continue
        
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        
        if not in_string:
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    # 완전한 JSON 객체를 찾음
                    return text[start_idx:i+1]
    
    # 완전한 JSON 객체를 찾지 못했으면 마지막 '{'부터 끝까지 반환
    return text[start_idx:]

def _parse_json_guard(text: str) -> Any:
    """문자열을 JSON으로 파싱."""
    # 1) JSON 객체 추출 (코드펜스 또는 텍스트 끝의 JSON)
    extracted = _extract_json_from_text(text)

    # 2) 값 위치의 백틱 리터럴만 안전하게 JSON 문자열로 수리
    repaired = _repair_backtick_value_literals(extracted)

    # 3) 우선 JSON으로 시도
    try:
        return json.loads(repaired)
    except Exception:
        pass

    # 4) JSON 실패 시, 파이썬 리터럴 파서로 보조 시도
    try:
        return ast.literal_eval(repaired)
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
        logger.info(f"\n\n🔍 결과 구조화를 위한 작업 진행 = form_id: {form_id}")
        text = getattr(result, "raw", None) or str(result)
        # 2~4) 견고 파싱(코드펜스/백틱-값 수리 포함)
        output_val = _parse_json_guard(text)

        # dict가 아니면 원본 구조로는 의미 없으니 dict로 강제 사용 불가 → 빈 사본
        original_wo_form = dict(output_val) if isinstance(output_val, dict) else {}

        # 4) 폼_데이터 추출/정규화
        form_raw = output_val.get("폼_데이터") if isinstance(output_val, dict) else None
        pure_form_data = _to_form_dict(form_raw)
        pure_form_preview = str(pure_form_data)[:200] + ("..." if len(str(pure_form_data)) > 200 else "")
        logger.info(f"🔍 pure_form_data (처음 200자): {pure_form_preview}")

        # 5) form_id 래핑 (요청사항: form_id로 {} 해서 dict 반환)
        wrapped_form_data = {form_id: pure_form_data} if form_id else pure_form_data
        wrapped_preview = str(wrapped_form_data)[:200] + ("..." if len(str(wrapped_form_data)) > 200 else "")
        logger.info(f"🔍 wrapped_form_data (처음 200자): {wrapped_preview}")


        # 6) 원본에서 '폼_데이터' 제거
        if isinstance(original_wo_form, dict):
            original_wo_form.pop("폼_데이터", None)

        return pure_form_data, wrapped_form_data, original_wo_form

    except Exception as e:
        logger.error(f"❌ Crew 결과 변환 실패: {e}", exc_info=True)
        raise
