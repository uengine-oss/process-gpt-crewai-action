#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import sys
import asyncio
import re
from context_manager import todo_id_var, proc_id_var

# 현재 디렉토리를 Python 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from crew.crew_factory import create_crew
from database import initialize_db, save_task_result


def convert_crew_output(result):
    """CrewOutput 객체에서 raw 속성 추출 및 전체 변환 처리"""
    try:
        # 1. CrewOutput에서 raw 속성 추출
        raw_result = getattr(result, 'raw', result)
        
        # 2. 문자열이 아니면 문자열로 변환
        text = str(raw_result or "")
        
        # 3. 마크다운 코드 블록 제거
        # ```json ... ``` 패턴 제거
        match = re.search(r"```(?:json)?[\r\n]+(.*?)[\r\n]+```", text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1)
        else:
            # 전체 코드 블록 제거
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
        
    except Exception:
        # 모든 처리 실패시 원본 결과 반환
        return result

async def main_async(inputs: dict):
    """
    1) 크루 생성
    2) inputs에서 user_request를 크루에 전달하여 실행
    3) 결과를 form_id로 감싸서 DB에 저장
    """
    # DB 설정 초기화
    initialize_db()
    
    # ContextVar 설정
    todo_id_var.set(inputs.get('todo_id'))
    proc_id_var.set(inputs.get('proc_inst_id'))
    
    # 크루 생성 및 실행 (동적으로 전달된 tools 파라미터 사용)
    tool_names = inputs.get("tools")
    crew = create_crew(tool_names)
    
    # 크루에 필요한 모든 inputs 전달
    crew_inputs = {
        "current_activity_name": inputs.get("current_activity_name", ""),
        "all_previous_outputs": inputs.get("all_previous_outputs", {}),
        "task_instructions": inputs.get("task_instructions", ""),
        "form_types": inputs.get("form_types", {})
    }
    
    # 크루 실행
    result = crew.kickoff(inputs=crew_inputs)
    
    # CrewOutput 객체를 JSON 직렬화 가능한 형태로 변환
    converted_result = convert_crew_output(result)
    
    # 결과를 form_id로 감싸서 저장
    form_id = inputs.get("form_id")
    todo_id = inputs.get("todo_id")
    
    if form_id and todo_id:
        # form_id로 결과 감싸기 (이미 변환된 결과 사용)
        wrapped_result = {form_id: converted_result}
        # DB에 최종 결과 저장
        await save_task_result(todo_id, wrapped_result)
        print(f"✅ 크루 실행 완료 및 결과 저장: {form_id}")
    else:
        print(f"✅ 크루 실행 완료: {converted_result}")
        print("⚠️ form_id 또는 todo_id 없음 - DB 저장 생략")

def main():
    # 1) 커맨드라인 인자로 전달된 JSON 파싱
    parser = argparse.ArgumentParser(description="Run Crew in a subprocess")
    parser.add_argument(
        "--inputs",
        required=True,
        help="JSON-encoded inputs for the crew (e.g. '{\"todo_id\":123, \"user_request\":\"고객 추가\"}')"
    )
    args = parser.parse_args()
    inputs = json.loads(args.inputs)

    # 2) 워커 실행
    asyncio.run(main_async(inputs))

if __name__ == "__main__":
    main()
