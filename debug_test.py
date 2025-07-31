#!/usr/bin/env python3
"""
디버그용 테스트 파일 - 직접 실행 가능
pytest 대신 일반 파이썬 디버그 방식으로 CrewAI 흐름을 테스트합니다.
"""

import os
import sys
import asyncio
from dotenv import load_dotenv

# 프로젝트 루트 경로를 sys.path에 추가
project_root = os.path.dirname(os.path.abspath(__file__))
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


class DebugTester:
    def __init__(self):
        self.todo_id = "ec00001f-d3d6-4d8e-b0d6-75b3829fb7c4"  # 실제 존재하는 todo_id로 변경 필요
        self.client = None
        
    def setup(self):
        """초기 설정"""
        print("=" * 60)
        print("🔧 디버그 테스트 시작")
        print("=" * 60)
        
        # DB 초기화
        initialize_db()
        self.client = get_db_client()
        print("✅ DB 클라이언트 초기화 완료")
        
    async def test_prepare_phase(self):
        """데이터 준비 단계 테스트"""
        print("\n📋 1단계: 데이터 준비 단계 테스트")
        print("-" * 40)
        
        try:
            # DB에서 todo 데이터 가져오기
            resp = (
                self.client
                .table('todolist')
                .select('*')
                .eq('id', self.todo_id)
                .single()
                .execute()
            )
            row = resp.data
            
            if not row:
                print(f"❌ Todo ID {self.todo_id}가 DB에 없습니다")
                return None
                
            print("✅ DB에서 todo 데이터 조회 성공")
            
            # Row 정보 출력
            print(f"  📌 activity_name: '{row.get('activity_name')}'")
            print(f"  📌 tool: '{row.get('tool')}'")
            print(f"  📌 user_id: '{row.get('user_id')}'")
            print(f"  📌 tenant_id: '{row.get('tenant_id')}'")
            print(f"  📌 description: '{row.get('description')}'")
            
            # _prepare_task_inputs 실행
            print("\n🔄 데이터 준비 중...")
            inputs = await _prepare_task_inputs(row)
            
            # 결과 검증
            problems = []
            print("\n📊 결과 검증:")
            
            todo_id = inputs.get('todo_id')
            print(f"  🔸 todo_id: '{todo_id}' {'✅' if todo_id else '❌ 빈값'}")
            if not todo_id:
                problems.append("todo_id 빈값")
            
            proc_inst_id = inputs.get('proc_inst_id')
            print(f"  🔸 proc_inst_id: '{proc_inst_id}' {'✅' if proc_inst_id else '❌ 없음'}")
            if not proc_inst_id:
                problems.append("proc_inst_id 없음")
            
            task_instructions = inputs.get('task_instructions')
            print(f"  🔸 task_instructions: '{task_instructions}' {'✅' if task_instructions else '❌ 빈값'}")
            if not task_instructions:
                problems.append("task_instructions 빈값")
            
            form_id = inputs.get('form_id')
            print(f"  🔸 form_id: '{form_id}' {'✅' if form_id else '❌ 없음'}")
            if not form_id:
                problems.append("form_id 없음")
            
            form_types = inputs.get('form_types', {})
            is_default = len(form_types) == 1 and form_types.get('type') == 'default'
            print(f"  🔸 form_types: {'❌ 기본값' if is_default else f'✅ {len(form_types)}개'} {form_types}")
            if is_default:
                problems.append("form_types 기본값")
            
            agent_info = inputs.get('agent_info', [])
            has_agents = agent_info and len(agent_info) > 0
            print(f"  🔸 agent_info: {'✅' if has_agents else '❌ 없음'} {len(agent_info)}개")
            if not has_agents:
                problems.append("agent_info 없음")
            
            print(f"  🔸 output_summary: {len(inputs.get('output_summary', ''))}자")
            print(f"  🔸 feedback_summary: {len(inputs.get('feedback_summary', ''))}자")
            
            if problems:
                print(f"\n❌ 문제 발견: {', '.join(problems)}")
                return None
            else:
                print(f"\n✅ 모든 검증 통과 - 데이터 준비 완료")
                return inputs
                
        except Exception as e:
            print(f"❌ 데이터 준비 단계 오류: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def test_crew_execution(self, inputs):
        """CrewAI 실행 단계 테스트"""
        print("\n🚀 2단계: CrewAI 실행 단계 테스트")
        print("-" * 40)
        
        try:
            # ContextVar 설정
            todo_id_var.set(inputs.get('todo_id'))
            proc_id_var.set(inputs.get('proc_inst_id'))
            print("✅ ContextVar 설정 완료")
            
            # 1. create_crew
            print("\n🔧 크루 생성 중...")
            crew = create_crew(
                agent_info=inputs.get('agent_info'),
                task_instructions=inputs.get('task_instructions'),
                form_types=inputs.get('form_types'),
                current_activity_name=inputs.get('current_activity_name'),
                output_summary=inputs.get('output_summary'),
                feedback_summary=inputs.get('feedback_summary')
            )
            
            if not crew:
                print("❌ 크루 생성 실패")
                return None
            print("✅ 크루 생성 성공")
            
            # 2. crew.kickoff
            print("\n🏃 크루 실행 중...")
            crew_inputs = {
                "current_activity_name": inputs.get('current_activity_name'),
                "task_instructions": inputs.get('task_instructions'),
                "form_types": inputs.get('form_types'),
                "output_summary": inputs.get('output_summary'),
                "feedback_summary": inputs.get('feedback_summary')
            }
            
            result = crew.kickoff(inputs=crew_inputs)
            
            if not result:
                print("❌ 크루 실행 실패")
                return None
            print("✅ 크루 실행 성공")
            
            # 3. convert_crew_output
            print("\n🔄 결과 변환 중...")
            converted_result = convert_crew_output(result)
            
            if not converted_result:
                print("❌ 결과 변환 실패")
                return None
                
            result_size = len(str(converted_result))
            print(f"✅ 결과 변환 성공 ({result_size}자)")
            
            return converted_result
            
        except Exception as e:
            print(f"❌ CrewAI 실행 단계 오류: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def run_full_test(self):
        """전체 테스트 실행"""
        self.setup()
        
        # 1단계: 데이터 준비
        inputs = await self.test_prepare_phase()
        if not inputs:
            print("\n💥 1단계 실패로 테스트 중단")
            return
        
        # 2단계: CrewAI 실행
        result = await self.test_crew_execution(inputs)
        if not result:
            print("\n💥 2단계 실패로 테스트 중단")
            return
        
        # 완료
        print("\n" + "=" * 60)
        print("🎉 전체 테스트 성공!")
        print("=" * 60)
        print(f"📋 최종 결과 요약:")
        print(f"  - Todo ID: {inputs.get('todo_id')}")
        print(f"  - 결과 크기: {len(str(result))}자")
        print(f"  - 결과 타입: {type(result)}")
        
        # 결과 일부만 출력 (너무 길면 잘라서)
        result_str = str(result)
        if len(result_str) > 500:
            print(f"  - 결과 미리보기: {result_str[:500]}...")
        else:
            print(f"  - 결과 전체: {result_str}")


def main():
    """메인 실행 함수"""
    print("🐍 Python 디버그 모드로 CrewAI 테스트 시작")
    
    tester = DebugTester()
    
    try:
        # 비동기 실행
        asyncio.run(tester.run_full_test())
    except KeyboardInterrupt:
        print("\n🛑 사용자가 테스트를 중단했습니다")
    except Exception as e:
        print(f"\n💥 예상치 못한 오류: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()