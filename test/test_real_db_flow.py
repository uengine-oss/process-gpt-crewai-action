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
from utils.crew_event_logger import CrewAIEventLogger
import uuid
from utils.context_manager import todo_id_var, proc_id_var

# DB 초기화
initialize_db()

# ============================================================================
# 테스트 케이스들
# ============================================================================

@pytest.mark.asyncio
async def test_prepare_phase():
    """
    준비 단계 실행만 수행하고 핵심 값들을 로그로 출력 (검증/어서션 없음)
    """
    todo_id = "9d316565-b891-43c6-8e70-cf91f9256bb9"  # 환경에 맞게 변경 가능
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
    if not row:
        print(f"⚠️ Todo ID {todo_id}가 DB에 없음. 테스트 스킵")
        return

    print("\n" + "="*50)
    print("입력 Row 확인:")
    print(f"  activity_name: '{row.get('activity_name')}'")
    print(f"  tool: '{row.get('tool')}'")
    print(f"  user_id: '{row.get('user_id')}'")
    print(f"  tenant_id: '{row.get('tenant_id')}'")
    print(f"  description: '{row.get('description')}'")
    print("="*50)

    inputs = await _prepare_task_inputs(row)

    agent_info = inputs.get('agent_info', [])
    print(f"\n🔍 agent_info: {len(agent_info)}개")
    for i, agent in enumerate(agent_info):
        print(f"  Agent {i+1}: id='{agent.get('id')}', role='{agent.get('role')}'")

    print("\n=== 준비 결과 요약 ===")
    print(f"  todo_id: {inputs.get('todo_id')}")
    print(f"  proc_inst_id: {inputs.get('proc_inst_id')}")
    print(f"  current_activity_name: {inputs.get('current_activity_name')}")
    print(f"  task_instructions: {bool(inputs.get('task_instructions'))}")
    print(f"  form_id: {inputs.get('form_id')}")
    form_types = inputs.get('form_types')
    if isinstance(form_types, dict):
        fields = form_types.get('fields') or []
        html = form_types.get('html')
        print(f"  form_types.fields: {len(fields)}개")
        print(f"  form_types.html: {'있음' if html else '없음'}")
    else:
        print(f"  form_types(raw): {type(form_types)}")
    print(f"  output_summary: {len(inputs.get('output_summary', '') or '')}자")
    print(f"  feedback_summary: {len(inputs.get('feedback_summary', '') or '')}자")

@pytest.mark.asyncio
async def test_full_crew_phase():
    """
    CrewAI 전체 실행 흐름을 실행하고 주요 단계 로그만 출력 (검증/어서션 없음)
    """
    todo_id = "9d316565-b891-43c6-8e70-cf91f9256bb9"  # 환경에 맞게 변경 가능
    client = get_db_client()
    row = (
        client
        .table('todolist')
        .select('*')
        .eq('id', todo_id)
        .single()
        .execute()
    ).data
    if not row:
        print(f"⚠️ Todo ID {todo_id}가 DB에 없음. 테스트 스킵")
        return

    inputs = await _prepare_task_inputs(row)

    print(f"\n크루 실행 단계별 로그:")

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
    print(f"  create_crew: {'성공' if crew else '실패'}")
    if not crew:
        return

    # 2. crew.kickoff
    crew_inputs = {
        "current_activity_name": inputs.get('current_activity_name'),
        "task_instructions": inputs.get('task_instructions'),
        "form_types": inputs.get('form_types'),
        "output_summary": inputs.get('output_summary'),
        "feedback_summary": inputs.get('feedback_summary')
    }
    try:
        result = crew.kickoff(inputs=crew_inputs)
        print("  crew.kickoff: 완료")
    except Exception as e:
        print(f"  crew.kickoff: 예외 발생 - {e}")
        return

    # 3. convert_crew_output
    try:
        pure_form_data, wrapped_result = convert_crew_output(result)
        result_size = len(str(wrapped_result)) if wrapped_result is not None else 0
        print(f"  convert_crew_output: 완료 ({result_size}자)")

        # 결과 이벤트 발행 (worker.py와 동일한 result 타입 흐름)
        try:
            event_logger = CrewAIEventLogger()
            job_uuid = str(uuid.uuid4())
            job_id = f"action_{job_uuid}"

            event_logger.emit_event(
                event_type="task_started",
                data={
                    "role": "최종 결과 반환",
                    "name": "최종 결과 반환",
                    "goal": "요청된 폼 형식에 맞는 최종 결과를 반환합니다.",
                    "agent_profile": "/images/chat-icon.png"
                },
                job_id=job_id,
                crew_type="result",
                todo_id=str(inputs.get('todo_id')) if inputs.get('todo_id') else None,
                proc_inst_id=str(inputs.get('proc_inst_id')) if inputs.get('proc_inst_id') else None
            )

            event_logger.emit_event(
                event_type="task_completed",
                data=pure_form_data if pure_form_data is not None else {},
                job_id=job_id,
                crew_type="result",
                todo_id=str(inputs.get('todo_id')) if inputs.get('todo_id') else None,
                proc_inst_id=str(inputs.get('proc_inst_id')) if inputs.get('proc_inst_id') else None
            )
            print("  result 이벤트 발행: 완료 (task_started, task_completed)")
        except Exception as ev_err:
            print(f"  result 이벤트 발행: 예외 발생 - {ev_err}")
    except Exception as e:
        print(f"  convert_crew_output: 예외 발생 - {e}")

# 디버그 실행을 위한 메인 함수들
async def debug_prepare_phase():
    """디버그용 prepare phase 테스트"""
    print("🚀 Prepare Phase 디버그 테스트 시작...")
    await test_prepare_phase()
    print("✅ Prepare Phase 디버그 테스트 완료!")

async def debug_full_crew_phase():
    """디버그용 full crew phase 테스트"""
    print("🚀 Full Crew Phase 디버그 테스트 시작...")
    await test_full_crew_phase()
    print("✅ Full Crew Phase 디버그 테스트 완료!")

async def debug_all_tests():
    """모든 테스트 디버그 실행"""
    print("🚀 전체 테스트 디버그 실행 시작...")
    try:
        # await debug_prepare_phase()
        # print("\n" + "="*60 + "\n")
        await debug_full_crew_phase()
        print("\n🎉 모든 테스트 성공적으로 완료!")
    except Exception as e:
        print(f"\n❌ 테스트 실행 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import asyncio
    
    print("=" * 60)
    print("🔧 Real DB Flow 디버그 테스트")
    print("=" * 60)
    
    # 개별 테스트 실행 (원하는 테스트만 주석 해제)
    # asyncio.run(debug_prepare_phase())
    # asyncio.run(debug_full_crew_phase())
    
    # 전체 테스트 실행
    asyncio.run(debug_all_tests())