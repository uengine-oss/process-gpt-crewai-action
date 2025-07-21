#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import sys
import asyncio

# 현재 디렉토리를 Python 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from crew.crew_factory import create_crew
from database import initialize_db

async def main_async(inputs: dict):
    """
    1) 크루 생성
    2) inputs에서 user_request를 크루에 전달하여 실행
    """
    # DB 설정 초기화
    initialize_db()
    
    # 크루 생성 및 실행 (동적으로 전달된 tools 파라미터 사용)
    tool_names = inputs.get("tools")
    crew = create_crew(tool_names)
    
    # user_request만 추출하여 크루에 전달
    crew_inputs = {
        "user_request": inputs.get("user_request", ""),
        "task_instructions": inputs.get("task_instructions", "")
    }
    
    # 크루 실행
    result = crew.kickoff(inputs=crew_inputs)
    
    print(f"✅ 크루 실행 완료: {result}")

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
