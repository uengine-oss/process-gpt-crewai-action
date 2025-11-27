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

def _parse_multiple_json_objects(text: str) -> Dict[str, Any]:
    """여러 JSON 객체가 줄바꿈으로 연결된 문자열을 파싱하여 병합."""
    merged = {}
    text = text.strip()
    
    # "}\n{" 또는 "}\r\n{" 패턴으로 분리
    import re
    # JSON 객체 경계 찾기: } 다음에 줄바꿈, 그 다음 {
    pattern = r'\}\s*\n\s*\{'
    parts = re.split(pattern, text)
    
    for i, part in enumerate(parts):
        part = part.strip()
        
        # 첫 번째가 아니면 앞에 { 추가
        if i > 0:
            part = '{' + part
        # 마지막이 아니면 뒤에 } 추가
        if i < len(parts) - 1:
            part = part + '}'
        
        # JSON 파싱 시도
        try:
            obj = json.loads(part)
            if isinstance(obj, dict):
                merged.update(obj)
        except Exception as e:
            # 파싱 실패 시 무시하고 계속
            logger.warning(f"⚠️ JSON 객체 파싱 실패 (무시): {str(e)[:100]}")
            continue
    
    return merged

def _parse_json_guard(text: str) -> Any:
    """문자열을 JSON으로 파싱. 여러 JSON 객체가 연결된 경우도 처리."""
    repaired = _repair_backtick_value_literals(text)

    # 1) 우선 JSON으로 시도
    try:
        return json.loads(repaired)
    except Exception:
        pass

    # 2) 여러 JSON 객체가 줄바꿈으로 연결된 경우 처리
    # "}\n{" 패턴이 있으면 여러 JSON 객체로 간주
    if '}\n{' in repaired or '}\r\n{' in repaired:
        try:
            return _parse_multiple_json_objects(repaired)
        except Exception:
            pass

    # 3) JSON 실패 시, 파이썬 리터럴 파서로 보조 시도
    try:
        return ast.literal_eval(repaired)
    except Exception as e:
        raise ValueError(f"JSON 파싱 실패: {e}")

def _to_form_dict(form_data: Any) -> Dict[str, Any]:
    """'폼_데이터'가 dict이면 그대로, list면 {'key':'text'} 매핑. str이면 {'content': str}. 그 외 타입은 빈 dict."""
    if isinstance(form_data, dict):
        return form_data
    if isinstance(form_data, list):
        return {
            (item.get("key") if isinstance(item, dict) else None): 
            (item.get("text") if isinstance(item, dict) else None)
            for item in form_data
            if isinstance(item, dict) and "key" in item
        }
    if isinstance(form_data, str):
        return {"content": form_data}
    return {}

def convert_crew_output(result, form_id: str = None, form_types: Dict = None) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    CrewOutput/문자열 -> JSON 파싱 -> '폼_데이터'만 추출/정규화 -> form_id로 래핑
    + 원본 JSON에서 '폼_데이터' 키 제거한 사본도 함께 반환.
    + 리포트/슬라이드 필드를 분리하여 별도로 반환.
    
    Returns:
        Tuple[pure_form_data, wrapped_form_data, original_wo_form, report_fields, slide_fields]
    """
    try:
        # 1) 문자열 확보
        logger.info(f"\n\n🔍 결과 구조화를 위한 작업 진행 = form_id: {form_id}")
        text = getattr(result, "raw", None) or str(result)
        # 2~4) 견고 파싱(코드펜스/백틱-값 수리 포함)
        output_val = _parse_json_guard(text)

        # 일부 모델/도구는 결과를 최상위가 아닌 'result' 키 아래에 감싸서 반환한다.
        # 이 경우 실제 유의미한 페이로드는 output_val['result'] 이므로 이를 기준으로 처리한다.
        result_data = None
        if isinstance(output_val, dict) and "result" in output_val:
            result_value = output_val["result"]
            
            # result 값이 문자열인 경우 (여러 JSON 객체가 연결된 형태일 수 있음)
            if isinstance(result_value, str):
                try:
                    # 문자열을 JSON으로 파싱 시도
                    result_data = _parse_json_guard(result_value)
                    if not isinstance(result_data, dict):
                        result_data = {}
                except Exception as e:
                    logger.warning(f"⚠️ result 문자열 파싱 실패, 빈 dict 사용: {e}")
                    result_data = {}
            elif isinstance(result_value, dict):
                result_data = result_value
            else:
                result_data = {}
            
            # result_data가 dict인 경우 처리
            if isinstance(result_data, dict):
                # result 안에 폼_데이터가 있으면 그대로 사용, 없으면 result 전체를 폼_데이터로 간주
                if "폼_데이터" in result_data:
                    output_val = {
                        "폼_데이터": result_data.get("폼_데이터"),
                        **{k: v for k, v in result_data.items() if k != "폼_데이터"}
                    }
                else:
                    output_val = {
                        "폼_데이터": result_data
                    }
        else:
            result_data = output_val if isinstance(output_val, dict) else {}

        # dict가 아니면 원본 구조로는 의미 없으니 dict로 강제 사용 불가 → 빈 사본
        original_wo_form = dict(output_val) if isinstance(output_val, dict) else {}

        # 리포트/슬라이드 필드 키 목록 추출 (form_types에서)
        report_field_keys = []
        slide_field_keys = []
        if form_types:
            form_fields = None
            if isinstance(form_types, dict) and ("fields" in form_types or "html" in form_types):
                form_fields = form_types.get("fields")
            else:
                form_fields = form_types if form_types else None
            
            if form_fields and isinstance(form_fields, list):
                for field in form_fields:
                    if isinstance(field, dict):
                        field_type = field.get("type", "").lower()
                        field_key = field.get("key", "")
                        if field_key:
                            if field_type in ["report", "document"]:
                                report_field_keys.append(field_key)
                            elif field_type in ["slide", "presentation"]:
                                slide_field_keys.append(field_key)

        # 4) 폼_데이터 추출/정규화
        form_raw = output_val.get("폼_데이터") if isinstance(output_val, dict) else None
        pure_form_data = _to_form_dict(form_raw)
        
        # 리포트/슬라이드 필드 분리 (form_types 기반으로만 처리)
        report_fields = {}
        slide_fields = {}
        
        # result_data에서 리포트/슬라이드 필드 추출 (result 객체 내부에 있을 수 있음)
        if isinstance(result_data, dict):
            for key, value in result_data.items():
                if key == "폼_데이터" or key == "상태" or key == "수행한_작업":
                    continue
                # form_types에서 정의된 리포트 필드인지 확인
                if key in report_field_keys:
                    report_fields[key] = value
                # form_types에서 정의된 슬라이드 필드인지 확인
                elif key in slide_field_keys:
                    slide_fields[key] = value
        
        # 폼_데이터에서도 리포트/슬라이드 필드 제거 (프롬프트에서 별도 반환하도록 지시했으므로)
        if isinstance(pure_form_data, dict):
            for key in list(pure_form_data.keys()):
                if key in report_field_keys or key in slide_field_keys:
                    # 폼_데이터에 포함되어 있다면 별도 필드로 이동
                    if key in report_field_keys and key not in report_fields:
                        report_fields[key] = pure_form_data.pop(key, None)
                    elif key in slide_field_keys and key not in slide_fields:
                        slide_fields[key] = pure_form_data.pop(key, None)
                    else:
                        pure_form_data.pop(key, None)
        
        pure_form_preview = str(pure_form_data)[:200] + ("..." if len(str(pure_form_data)) > 200 else "")
        logger.info(f"🔍 pure_form_data (처음 200자): {pure_form_preview}")
        logger.info(f"🔍 리포트 필드: {list(report_fields.keys())}")
        logger.info(f"🔍 슬라이드 필드: {list(slide_fields.keys())}")

        # 5) form_id 래핑 (요청사항: form_id로 {} 해서 dict 반환)
        wrapped_form_data = {form_id: pure_form_data} if form_id else pure_form_data
        wrapped_preview = str(wrapped_form_data)[:200] + ("..." if len(str(wrapped_form_data)) > 200 else "")
        logger.info(f"🔍 wrapped_form_data (처음 200자): {wrapped_preview}")
        
        # 6) 원본에서 '폼_데이터' 제거
        if isinstance(original_wo_form, dict):
            original_wo_form.pop("폼_데이터", None)

        return pure_form_data, wrapped_form_data, original_wo_form, report_fields, slide_fields

    except Exception as e:
        logger.error(f"❌ Crew 결과 변환 실패: {e}", exc_info=True)
        raise
