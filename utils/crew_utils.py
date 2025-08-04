import re
import json
from utils.logger import handle_error

# Markdown JSON 코드 블록을 추출하는 정규식
RE_CODE_BLOCK = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)

def convert_crew_output(result, form_id=None):
    """CrewOutput 객체를 JSON으로 변환하고, 순수 폼 데이터와 wrapper 적용 결과를 모두 반환"""
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
        
        # 4) 폼_데이터 추출
        pure_form_data = output_val
        wrapped_result = output_val
        
        if isinstance(output_val, dict) and '폼_데이터' in output_val:
            form_data = output_val['폼_데이터']
            
            # dict 형태인 경우
            if isinstance(form_data, dict):
                pure_form_data = form_data
                wrapped_result = {form_id: form_data} if form_id else form_data
            # list 형태인 경우 key/text 매핑
            elif isinstance(form_data, list):
                mapped_data = {item.get('key'): item.get('text') for item in form_data if isinstance(item, dict)}
                pure_form_data = mapped_data
                wrapped_result = {form_id: mapped_data} if form_id else mapped_data
        
        # 순수 폼 데이터와 wrapper 적용 결과를 모두 반환
        return pure_form_data, wrapped_result
    
    except Exception as e:
        handle_error("크루결과변환", e)
        return result, result 