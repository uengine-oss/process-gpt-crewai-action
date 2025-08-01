#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import sys
import asyncio

# 프로젝트 루트 디렉토리를 Python 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

from utils.context_manager import todo_id_var, proc_id_var
from utils.crew_utils import convert_crew_output
from utils.logger import log

from crews.crew_factory import create_crew
from core.database import initialize_db, save_task_result


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
    
    # 크루 생성 및 실행 (동적으로 전달된 inputs 사용)
    agent_info = inputs.get("agent_info")
    task_instructions = inputs.get("task_instructions")
    form_types = inputs.get("form_types")
    current_activity_name = inputs.get("current_activity_name")
    crew = create_crew(
        agent_info=agent_info,
        task_instructions=task_instructions,
        form_types=form_types,
        current_activity_name=current_activity_name,
        output_summary=inputs.get("output_summary", ""),
        feedback_summary=inputs.get("feedback_summary", "")
    )
    
    # 크루에 필요한 모든 inputs 전달
    crew_inputs = {
        "current_activity_name": inputs.get("current_activity_name", ""),
        "task_instructions": inputs.get("task_instructions", ""),
        "form_types": inputs.get("form_types", {}),
        "output_summary": inputs.get("output_summary", ""),
        "feedback_summary": inputs.get("feedback_summary", "")
    }
    
    # 크루 실행
    result = crew.kickoff(inputs=crew_inputs)
    
    # 최종 결과 변환 및 저장
    form_id = inputs.get("form_id")
    todo_id = inputs.get("todo_id")
    # form_id가 있으면 convert_crew_output에 넘겨 wrapper 적용
    converted_result = convert_crew_output(result, form_id)
    if form_id and todo_id:
        await save_task_result(todo_id, converted_result)
        log(f"크루 실행 완료 및 결과 저장: {form_id}")
    else:
        log(f"크루 실행 완료: {converted_result}")
        log("form_id 또는 todo_id 없음 - DB 저장 생략")

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
