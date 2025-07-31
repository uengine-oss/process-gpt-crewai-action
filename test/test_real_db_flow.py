import os
import sys
import pytest
from dotenv import load_dotenv

# 프로젝트 루트 경로를 sys.path에 추가 (모듈 import를 위해)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 테스트 환경 설정
os.environ['ENV'] = 'test'
load_dotenv('.env.test', override=True)

from core.database import initialize_db, get_db_client
from core.polling_manager import _prepare_task_inputs
from crews.crew_factory import create_crew
from utils.crew_utils import convert_crew_output
from utils.context_manager import todo_id_var, proc_id_var

# DB 초기화
initialize_db()

# ============================================================================
# 테스트 케이스들
# ============================================================================

@pytest.mark.asyncio
async def test_prepare_phase():
    """
    1) todolist 테이블에서 실제 todo_id로 row를 가져와,
    2) _prepare_task_inputs가 올바른 dict 구조를 반환하는지 검증
    """
    todo_id = "ec00001f-d3d6-4d8e-b0d6-75b3829fb7c4"  # 실제 존재하는 todo_id로 변경 필요
    client = get_db_client()
    resp = (
        client
        .table('todolist')
        .select('*')
        .eq('id', todo_id)
        .single()
        .execute()
    )
    row = resp.data
    assert row, f"Todo ID {todo_id}가 DB에 없습니다"
    
    # Row 입력 확인
    print("\n" + "="*50)
    print("입력 Row 확인:")
    print(f"  activity_name: '{row.get('activity_name')}'")
    print(f"  tool: '{row.get('tool')}'")
    print(f"  user_id: '{row.get('user_id')}'")
    print(f"  tenant_id: '{row.get('tenant_id')}'")
    print(f"  description: '{row.get('description')}'")
    print("="*50)
    
    # _prepare_task_inputs 실행 및 결과 검증
    inputs = await _prepare_task_inputs(row)
    print("\n" + "="*50)
    print("결과 검증:")
    print("="*50)
    
    problems = []
    
    # 각 필드 출력하면서 동시에 검증
    todo_id = inputs.get('todo_id')
    print(f"  todo_id: '{todo_id}' {'✓' if todo_id else '❌ 빈값'}")
    if not todo_id:
        problems.append("todo_id 빈값")
    
    proc_inst_id = inputs.get('proc_inst_id')
    print(f"  proc_inst_id: '{proc_inst_id}' {'✓' if proc_inst_id else '❌ 없음'}")
    if not proc_inst_id:
        problems.append("proc_inst_id 없음")
    
    task_instructions = inputs.get('task_instructions')
    print(f"  task_instructions: '{task_instructions}' {'✓' if task_instructions else '❌ 빈값'}")
    if not task_instructions:
        problems.append("task_instructions 빈값")
    
    form_id = inputs.get('form_id')
    print(f"  form_id: '{form_id}' {'✓' if form_id else '❌ 없음'}")
    if not form_id:
        problems.append("form_id 없음")
    
    form_types = inputs.get('form_types', {})
    is_default = len(form_types) == 1 and form_types.get('type') == 'default'
    print(f"  form_types: {'❌ 기본값' if is_default else f'✓ {len(form_types)}개'} {form_types}")
    if is_default:
        problems.append("form_types 기본값")
    
    agent_info = inputs.get('agent_info', [])
    has_agents = agent_info and len(agent_info) > 0
    print(f"  agent_info: {'✓' if has_agents else '❌ 없음'} {len(agent_info)}개")
    if not has_agents:
        problems.append("agent_info 없음")
    
    print(f"  output_summary: {len(inputs.get('output_summary', ''))}자")
    print(f"  feedback_summary: {len(inputs.get('feedback_summary', ''))}자")
    
    # 문제 있으면 바로 실패
    if problems:
        assert False, f"❌ 문제 발견: {', '.join(problems)}"
    print(f"✓ 모든 검증 통과")

@pytest.mark.asyncio
async def test_full_crew_phase():
    """
    CrewAI 전체 실행 흐름 테스트
    """
    todo_id = "ec00001f-d3d6-4d8e-b0d6-75b3829fb7c4"  # 실제 존재하는 todo_id로 변경 필요
    client = get_db_client()
    row = (
        client
        .table('todolist')
        .select('*')
        .eq('id', todo_id)
        .single()
        .execute()
    ).data
    inputs = await _prepare_task_inputs(row)

    print(f"\n크루 실행 단계별 테스트:")
    problems = []

    # ContextVar 설정
    todo_id_var.set(inputs.get('todo_id'))
    proc_id_var.set(inputs.get('proc_inst_id'))

    # 1. create_crew
    crew = create_crew(
        agent_info=inputs.get('agent_info'),
        task_instructions=inputs.get('task_instructions'),
        form_types=inputs.get('form_types'),
        current_activity_name=inputs.get('current_activity_name'),
        output_summary=inputs.get('output_summary'),
        feedback_summary=inputs.get('feedback_summary')
    )
    has_crew = crew is not None
    print(f"  create_crew: {'✓' if has_crew else '❌ 생성 실패'}")
    if not has_crew:
        problems.append("crew 생성 실패")

    # 2. crew.kickoff
    if has_crew:
        crew_inputs = {
            "current_activity_name": inputs.get('current_activity_name'),
            "task_instructions": inputs.get('task_instructions'),
            "form_types": inputs.get('form_types'),
            "output_summary": inputs.get('output_summary'),
            "feedback_summary": inputs.get('feedback_summary')
        }
        
        result = crew.kickoff(inputs=crew_inputs)
        has_result = result is not None
        print(f"  crew.kickoff: {'✓' if has_result else '❌ 실행 실패'}")
        if not has_result:
            problems.append("crew 실행 실패")

        # 3. convert_crew_output
        if has_result:
            converted_result = convert_crew_output(result)
            has_converted = converted_result is not None
            result_size = len(str(converted_result)) if converted_result else 0
            print(f"  convert_crew_output: {'✓' if has_converted else '❌ 변환 실패'} ({result_size}자)")
            if not has_converted:
                problems.append("결과 변환 실패")

    # 문제 있으면 바로 실패
    if problems:
        assert False, f"❌ 크루 실행 실패: {', '.join(problems)}"
    
    print(f"✓ 전체 크루 실행 성공")