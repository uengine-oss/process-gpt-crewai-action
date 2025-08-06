import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.prompt_generator import DynamicPromptGenerator

def test_prompt_generator():
    """간단한 프롬프트 생성 테스트"""
    
    generator = DynamicPromptGenerator()
    
    # 테스트 입력값 (여기를 수정해서 테스트)
    test_input = {
        "task_instructions": "orders 테이블에서 주문 정보 저장 및 product 테이블에서 주문된 제품 재고 조회",
        "agent_info": [
            {
                "role": "SQL 전문가",
                "goal": "데이터베이스 조회 및 분석",
                "tools": "sql_executor, list_tables",
                "id": "28f68ce5-9c64-4f32-ad1e-2be81a67b63b",
                "tenant_id": "localhost"
            }
        ],
        "form_types": {"product_name": "string", "stock_count": "number"},
        "output_summary": "안치윤 고객이 금형세트 제품을 50개 주문했습니다.",
        "feedback_summary": "",
        "current_activity_name": "재고 확인"
    }
    
    print("=== 프롬프트 생성 테스트 ===")
    description, expected_output = generator.generate_task_prompt(**test_input)
    
    print(f"📝 Description:\n{description}")
    print(f"\n📋 Expected Output:\n{expected_output}")

if __name__ == "__main__":
    test_prompt_generator()