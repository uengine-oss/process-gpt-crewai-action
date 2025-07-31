import re
import json
from utils.logger import handle_error


def convert_crew_output(result):
    """CrewOutput 객체에서 raw 속성 추출 및 전체 변환 처리"""
    try:
        # 1. CrewOutput에서 raw 속성 추출
        raw_result = getattr(result, 'raw', result)

        # 2. 문자열이 아니면 문자열로 변환
        text = str(raw_result or "")

        # 3. 마크다운 코드 블록 제거
        match = re.search(r"```(?:json)?[\r\n]+(.*?)[\r\n]+```", text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1)
        else:
            stripped = text.strip()
            if stripped.startswith("```") and stripped.endswith("```"):
                lines = stripped.split("\n")
                text = "\n".join(lines[1:-1])

        # 4. JSON 파싱 시도
        cleaned_text = text.strip()
        if cleaned_text:
            try:
                return json.loads(cleaned_text)
            except (json.JSONDecodeError, ValueError):
                # JSON 파싱 실패시 원본 텍스트 반환
                return cleaned_text

        # 5. 빈 텍스트인 경우 원본 결과 반환
        return raw_result

    except Exception as e:
        # 모든 처리 실패시 원본 결과 반환
        handle_error("크루결과변환", e)
        return result 