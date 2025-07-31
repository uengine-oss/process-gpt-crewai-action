import asyncio
import json
import logging
import warnings
from typing import Dict, Any, List
from crews.crew_factory import create_crew
from utils.crew_utils import convert_crew_output
import uuid

import logging

# Supabase 라이브러리의 DeprecationWarning 숨기기
warnings.filterwarnings("ignore", category=DeprecationWarning, module="supabase")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s:%(lineno)d - %(levelname)s: %(message)s"
)

logger = logging.getLogger(__name__)

def create_hardcoded_test_data() -> Dict[str, Any]:
    """하드코딩된 테스트 데이터 생성 - 주문정보 처리"""
    
    # 1. 에이전트 정보 (tools 필드에 콤마로 구분된 툴 이름들)
    agent_info = [
        {
            "id": "b7e6a1c2-3f4d-4e2a-9c1a-123456789abc",
            "tenant_id": "localhost",
            "name": "team_manager",
            "role": "team_manager",
            "goal": "Coordinate team members to efficiently complete order processing tasks by delegating appropriate work to specialized agents",
            "backstory": "A project management expert with 7 years of experience in team coordination and task delegation. Your team consists of 'schema_analyst' and 'sql_executor'. When delegating tasks, you must use these exact names: 'schema_analyst' for database schema analysis and 'sql_executor' for SQL execution. Always delegate tasks to the appropriate team member based on their expertise.\n\n**툴 호출 예시**:\nAction: Delegate work to coworker\nAction Input:\n{{\n  \"coworker\": \"schema_analyst\",\n  \"task\": \"Analyze the orders table schema.\",\n  \"context\": \"Orders 테이블의 필드 정보는 order_id(INT), product_name(TEXT), customer_name(TEXT), quantity(INT)이며, 이전 컨텍스트로는 제품명 'Dell XPS 13', 주문자 '홍길동', 주문수량 '3'이 있습니다.\"\n}}\n\nAction: Delegate work to coworker\nAction Input:\n{{\n  \"coworker\": \"sql_executor\",\n  \"task\": \"Execute the INSERT query to store order.\",\n  \"context\": \"스키마 분석 결과를 바탕으로 orders 테이블에 제품명='Dell XPS 13', 주문자='홍길동', 주문수량=3 데이터를 INSERT하세요.\"\n}}\nMake sure to include all three keys: coworker, task, and context.",
        },
        {
            "id": "c8f7b2d3-4g5e-5f3b-0d2b-234567890def",
            "tenant_id": "localhost", 
            "name": "schema_analyst",
            "role": "schema_analyst",
            "goal": "Analyze table structures and perform accurate mapping between order data and schema",
            "backstory": "An expert with 4 years of experience in various database schema design and analysis tasks. Provides accurate data storage solutions through table structure analysis, column mapping, and data type validation.",
            "tools": "supabase,mem0"  # 실제 사용할 툴들
        },
        {
            "id": "d9g8c3e4-5h6f-6g4c-1e3c-345678901fed",
            "tenant_id": "localhost",
            "name": "sql_executor", 
            "role": "sql_executor",
            "goal": "Generate optimized SQL based on analyzed schema information and execute it safely",
            "backstory": "An expert with 6 years of experience in SQL development and optimization. Ensures stable data processing through complex query writing, performance tuning, and transaction management.",
            "tools": "supabase,mem0"  # 실제 사용할 툴들
        }
    ]
    
    # 2. 작업 지시사항 - 단순한 한줄 지시사항
    task_instructions = "supabase 툴을 이용하여, orders 테이블에 주문 정보를 저장합니다."
    
    # 3. 폼 타입 정보 - 단순한 text 타입
    form_types = {
        "주문된_제품명": {"type": "string", "description": "주문한 제품의 이름"},
        "주문자": {"type": "string", "description": "주문한 고객의 이름"},
        "주문수량": {"type": "string", "description": "주문한 제품의 수량"}
    }
    
    # 4. 현재 활동명
    current_activity_name = "주문정보_저장"
    
    
    # 5. 컨텍스트 요약 - 실제 저장할 주문 데이터
    context_summary = """
이전 컨텍스트:
- 제품명: Dell XPS 13
- 주문자: 홍길동  
- 주문수량: 3개
"""

    # 6. 피드백
    feedback = """
"""
    
    return {
        "agent_info": agent_info,
        "task_instructions": task_instructions,
        "form_types": form_types,
        "current_activity_name": current_activity_name,
        "output_summary": context_summary,  # 기존 context_summary를 output_summary로 사용
        "feedback_summary": feedback,  # 기존 feedback을 feedback_summary로 사용
    }

async def run_order_test():
    """주문 처리 테스트 실행"""
    
    print("🛒 주문 정보 저장 테스트 시작")
    print("="*60)
    
    # 테스트 데이터 생성
    test_data = create_hardcoded_test_data()
    
    try:
        result = await run_crew_test(test_data, "주문정보 저장")
        
        # 결과 출력
        if result['success']:
            print(f"\n✅ 테스트 성공!")
            print(f"결과: {result['crew_result']}")
        else:
            print(f"\n❌ 테스트 실패!")
            print(f"오류: {result.get('error', 'Unknown error')}")
            
        return result
        
    except Exception as e:
        print(f"❌ 테스트 실행 중 오류: {e}")
        return {
            'success': False,
            'error': str(e),
            'message': "테스트 실행 실패"
        }



def log_test_data_info(test_data: Dict[str, Any], test_name: str):
    """테스트 데이터 정보 로깅"""
    logger.info(f"\n{'='*60}")
    logger.info(f"📋 {test_name} 테스트 데이터 정보")
    logger.info(f"{'='*60}")
    
    # 에이전트 정보
    agents = test_data['agent_info']
    logger.info(f"👥 에이전트 개수: {len(agents)}개")
    
    total_tools = 0
    for i, agent in enumerate(agents, 1):
        tools_str = agent.get('tools', '')
        tools_list = [tool.strip() for tool in tools_str.split(',') if tool.strip()] if tools_str else []
        total_tools += len(tools_list)
        
        logger.info(f"  {i}. {agent.get('name', 'Unknown')}")
        logger.info(f"     - 역할: {agent.get('role', 'N/A')}")
        logger.info(f"     - 툴: {tools_list} ({len(tools_list)}개)")
    
    logger.info(f"🔧 총 툴 개수: {total_tools}개")
    
    # 작업 정보
    logger.info(f"📝 작업 지시사항: {test_data['task_instructions'][:100]}...")
    logger.info(f"📊 현재 활동: {test_data['current_activity_name']}")
    
    # 폼 타입
    form_types = test_data.get('form_types', {})
    logger.info(f"📋 폼 필드 개수: {len(form_types)}개")
    
    # 컨텍스트
    output_context = test_data.get('output_summary', '')
    feedback_context = test_data.get('feedback_summary', '')
    if output_context:
        logger.info(f"💭 이전 결과: {output_context[:100]}...")
    else:
        logger.info(f"💭 이전 결과: 없음")
    
    if feedback_context:
        logger.info(f"💬 피드백: {feedback_context[:100]}...")
    else:
        logger.info(f"💬 피드백: 없음")

async def run_crew_test(test_data: Dict[str, Any], test_name: str) -> Dict[str, Any]:
    """크루 테스트 실행"""
    try:
        logger.info(f"\n🚀 {test_name} 크루 실행 시작")
        
        # 1. 테스트 데이터 정보 출력
        log_test_data_info(test_data, test_name)
        
        # 2. 크루 생성
        logger.info(f"\n🔄 크루 생성 중...")
        crew = create_crew(
            agent_info=test_data['agent_info'],
            task_instructions=test_data['task_instructions'],
            form_types=test_data['form_types'],
            current_activity_name=test_data['current_activity_name'],
            output_summary=test_data['output_summary'],
            feedback_summary=test_data['feedback_summary']
        )
        logger.info("✅ 크루 생성 완료")
        
        # 3. 크루 실행
        logger.info(f"\n⚡ 크루 실행 중...")
        
        # 크루 실행을 위한 입력값 준비
        crew_inputs = {
            "current_activity_name": test_data['current_activity_name'],
            "task_instructions": test_data['task_instructions'],
            "form_types": test_data['form_types'],
            "output_summary": test_data['output_summary'],
            "feedback_summary": test_data['feedback_summary']
        }
        
        result = crew.kickoff(inputs=crew_inputs)
        logger.info("✅ 크루 실행 완료")
        
        # 4. 결과 변환
        converted_result = convert_crew_output(result)
        
        # 5. 결과 반환
        test_result = {
            'success': True,
            'test_name': test_name,
            'test_data': test_data,
            'crew_result': converted_result,
            'message': f"{test_name} 크루 실행 성공"
        }
        
        logger.info(f"🎉 {test_name} 테스트 완료!")
        return test_result
        
    except Exception as e:
        error_result = {
            'success': False,
            'test_name': test_name,
            'error': str(e),
            'message': f"{test_name} 크루 실행 실패"
        }
        logger.error(f"❌ {test_name} 테스트 실패: {e}")
        return error_result



# 실행 예제
if __name__ == "__main__":
    print("🛒 주문 정보 저장 테스트 실행")
    result = asyncio.run(run_order_test()) 