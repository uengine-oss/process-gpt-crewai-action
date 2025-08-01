import re
import json
from utils.logger import handle_error

# Markdown JSON 코드 블록을 추출하는 정규식
RE_CODE_BLOCK = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)

def convert_crew_output(result, form_id=None):
    """CrewOutput 객체를 JSON으로 변환하고, 필요시 form_data를 wrapper로 반환"""
    try:
        # 1) raw 속성 또는 문자열 결과 확보
        text = getattr(result, 'raw', None) or str(result)
        # 2) 코드 블록 제거
        match = RE_CODE_BLOCK.search(text)
        if match:
            text = match.group(1)
        # 3) JSON 파싱 시도, 실패 시 원본 텍스트 사용
        try:
            output_val = json.loads(text)
        except:
            output_val = text
        # 4) form_id가 주어지고 '폼_데이터' 키가 있으면 wrapper 적용
        if form_id and isinstance(output_val, dict) and '폼_데이터' in output_val:
            form_data = output_val['폼_데이터']
            # dict 형태인 경우 그대로 사용
            if isinstance(form_data, dict):
                return {form_id: form_data}
            # list 형태인 경우 key/text 매핑
            if isinstance(form_data, list):
                return {form_id: {item.get('key'): item.get('text') for item in form_data if isinstance(item, dict)}}
        return output_val
    
    except Exception as e:
        handle_error("크루결과변환", e)
        return result 