from crewai import Task
import logging

logger = logging.getLogger(__name__)

def create_parse_task(requirement_parser):
    """RequirementParser용 Task 생성"""
    return Task(
        description="""🚨 **단일 테이블 저장 원칙**: 오직 task_instructions에 명시된 테이블에만 데이터를 저장하세요!

작업 지시사항: {task_instructions}
저장될 데이터: {user_request}

**중요**: 
- task_instructions에서 명시된 테이블 (예: "orders 테이블") 외에는 절대 건드리지 마세요
- 다른 테이블(고객, 제품, 카테고리 등)에는 새 데이터를 생성하지 마세요
- 외래키가 필요하면 기존 데이터에서 ID를 찾아서 사용하세요

작업:
1. task_instructions에서 지시된 단일 테이블 확인
2. user_request에서 해당 테이블에 저장할 데이터만 추출
3. 외래키가 필요한 경우 기존 데이터에서 ID 조회 (새로 생성하지 않음)
4. list_tables로 테이블 구조 확인
5. generate_typescript_types로 지시된 테이블의 스키마만 조회
6. 단일 테이블 저장을 위한 구조화된 정보 생성""",
        expected_output="JSON 형태: {operation: 'insert', tables: ['지시된_단일_테이블'], data: {테이블명: {values: {...}, defaults_used: [...]}}}",
        agent=requirement_parser
    )

def create_plan_task(db_planner):
    """DBPlanner용 Task 생성"""
    return Task(
        description="""🚨 **RequirementParser 결과 활용 필수**: RequirementParser가 분석한 정확한 컬럼명을 사용하여 INSERT 쿼리 생성!

**🔥 CRITICAL 작업 규칙:**
1. **RequirementParser의 "columns" 배열에 있는 정확한 컬럼명만 사용**
2. **RequirementParser의 "values" 객체에서 해당 값들 가져오기**
3. **절대로 한글 컬럼명 사용 금지** ("단가", "수량", "고객ID" 등)
4. **절대로 임의 컬럼명 사용 금지** (추측하지 말고 정확히 사용)

**예시:**
```
RequirementParser 출력:
"columns": ["컬럼1", "컬럼2", "컬럼3"]
"values": {"컬럼1": "값1", "컬럼2": "값2", "컬럼3": "값3"}

생성할 SQL:
INSERT INTO 테이블명 ("컬럼1", "컬럼2", "컬럼3") VALUES ('값1', '값2', '값3')
```

**절대 금지**: 고객, 제품, 카테고리 등 다른 테이블 작업""",
        expected_output="JSON 형태: {operation: 'insert', queries: [{table: '지시된_테이블', sql: 'INSERT INTO...'}]}",
        agent=db_planner
    )

def create_execute_task(sql_executor):
    """SQLExecutor용 Task 생성"""
    return Task(
        description="""DBPlanner가 생성한 SQL 쿼리들을 순차적으로 실행:

작업:
- queries 배열을 순서대로 처리
- 각 쿼리별 실행 결과와 에러 처리
- 성공/실패 상태 확인

중요: execute_sql 툴을 실제로 사용하여 모든 쿼리를 실행하세요!""",
        expected_output="각 쿼리별 실행 결과: {테이블명: {성공여부, 영향받은행수, 에러메시지}}",
        agent=sql_executor
    )

def create_confirm_task(result_confirmer):
    """ResultConfirmer용 Task 생성"""
    return Task(
        description="""이전 task 결과를 활용하여 SQL 실행 결과를 검증하고 최종 결과를 사용자에게 제공:

**🔥 CRITICAL: 이전 결과 활용 방법**
1. **RequirementParser 결과에서 식별값 추출**:
   - `{"order_id": "ORD-123"}` → WHERE order_id = 'ORD-123'
   - `{"customer_id": "CUST-456"}` → WHERE customer_id = 'CUST-456'
   
2. **SQLExecutor 결과 확인**:
   - `{"성공여부": "성공", "영향받은행수": 1}` → INSERT 성공 확인

**🚨 CRITICAL: 모든 form_types 필드 강제 포함 규칙**
1. **form_types에 정의된 모든 필드를 반드시 포함해야 합니다**
2. **단 하나의 필드도 누락되면 안됩니다**
3. **각 필드에 대해 적절한 값을 제공해야 합니다**
4. **처리되지 않은 필드는 명시적으로 "처리되지 않음" 또는 기본값으로 표시**

**작업 순서:**
1. 이전 task 결과에서 SELECT 조건 추출 (order_id, customer_code 등)
2. 해당 조건으로 SELECT * FROM 테이블명 WHERE 조건 쿼리 생성
3. execute_sql 툴로 실제 데이터 조회
4. **form_types의 모든 필드를 하나씩 처리 (필수)**:
   - form_types: {form_types}
   - **각 필드의 id를 키로 하여 결과 매핑**
   - **누락된 필드 없이 완전한 결과 구성**
   
**필드별 완전 매핑 전략:**
   **처리 관련 필드**: 실제 DB 결과를 기반으로 해당 타입에 맞게 포맷팅
   **관련 없는 필드**: "이 작업과 관련 없음" 또는 적절한 설명
   **빈 데이터 필드**: "데이터 없음" 또는 해당 타입의 기본값
   **미처리 필드**: "처리되지 않음" 명시
   
   **폼 타입별 데이터 형식 주의사항:**
   - text/textarea: 문자열 내용 (예: "주문 내용: 노트북 2대")
   - number: 숫자 값 (예: "총 금액: 1,500,000원", "수량: 5개")
   - select/dropdown: 선택된 옵션명 (예: "배송방법: 택배")
   - checkbox: 체크된 항목들 (예: "선택옵션: 포장지, 영수증")
   - radio: 선택된 라디오 값 (예: "결제방법: 신용카드")
   - date: 날짜 정보 (예: "배송일: 2024-01-15")
   - file: 파일 정보 (예: "첨부파일: document.pdf")
   - email: 이메일 주소 (예: "연락처: hong@example.com")
   - report: 보고서 형태 상세 내용
   - slide: 프레젠테이션 형태 요약 내용
   
   **작업별 매핑 예시:**
   
   **저장 작업 (INSERT):**
   - order_id: "주문 ORD-123이 성공적으로 저장되었습니다"
   - order_details: "상품: 노트북, 수량: 2개, 단가: 1,500,000원, 총액: 3,000,000원"
   - customer_info: "고객: 홍길동 (hong@example.com)"
   - payment_method: "결제방법: 신용카드"
   - delivery_options: "배송옵션: 빠른배송, 포장지 포함"
   - order_date: "주문일: 2024-01-15"
   - unrelated_field: "이 작업과 관련 없음"
   
   **수정 작업 (UPDATE):**
   - update_result: "주문 ORD-123의 수량이 2개 → 3개로 수정되었습니다"
   - updated_values: "변경 전: 2개 (3,000,000원) → 변경 후: 3개 (4,500,000원)"
   - status_change: "주문상태: 대기중 → 처리중"
   - unrelated_field: "이 수정 작업과 관련 없음"
   
   **조회 작업 (SELECT):**
   - search_result: "고객 홍길동의 정보를 조회했습니다"
   - found_data: "이메일: hong@example.com, 전화: 010-1234-5678"
   - unrelated_field: "이 조회 작업과 관련 없음"
   
   **삭제 작업 (DELETE):**
   - delete_result: "주문 ORD-123이 성공적으로 삭제되었습니다"
   - deleted_info: "삭제된 주문: 노트북 2개 (총 3,000,000원)"
   - unrelated_field: "이 삭제 작업과 관련 없음"

**최종 결과 검증:**
1. form_types 필드 개수와 결과 필드 개수가 일치하는지 확인
2. 모든 필드 id가 결과에 포함되어 있는지 확인
3. 각 필드에 적절한 값이 할당되어 있는지 확인

**절대 금지**: created_at, updated_at 등 존재하지 않는 컬럼 사용, 필드 누락""",
        expected_output="""**CRITICAL: 모든 form_types 필드 포함 필수**

JSON 형식으로 반환하되, form_types에 정의된 **모든 필드를 빠짐없이 포함**:

**필수 검증 사항:**
1. form_types 필드 개수 = 결과 필드 개수 (완전 일치)
2. 모든 필드 id가 결과에 존재
3. 각 필드에 적절한 타입별 값 할당

**타입별 반환 형식:**
- text/textarea: "필드명: 처리된 텍스트 내용" 또는 "이 작업과 관련 없음"
- number: "필드명: 숫자값 (단위 포함)" 또는 "처리되지 않음"
- select/dropdown: "필드명: 선택된_옵션명" 또는 "선택 없음"
- checkbox: "필드명: 선택된항목1, 선택된항목2" 또는 "체크 없음"
- radio: "필드명: 선택된_단일값" 또는 "선택 없음"
- date: "필드명: YYYY-MM-DD 형식" 또는 "날짜 정보 없음"
- email: "필드명: 이메일@주소.com" 또는 "이메일 정보 없음"
- file: "필드명: 파일명.확장자" 또는 "파일 없음"
- report: "상세한 보고서 형태 내용" 또는 "보고서 관련 없음"
- slide: "요약된 프레젠테이션 내용" 또는 "프레젠테이션 관련 없음"

**최종 JSON 구조 (모든 필드 포함 필수):** 
{
  "form_field_id1": "타입에_맞는_처리결과1",
  "form_field_id2": "타입에_맞는_처리결과2",
  "form_field_id3": "이_작업과_관련_없음",
  "form_field_id4": "처리되지_않음",
  ...
  // form_types의 모든 필드 반드시 포함
}

**검증 결과 예시:**
- 총 필드 수: form_types 필드 개수와 정확히 일치
- 누락된 필드: 0개 (반드시)
- 처리된 필드: 실제 작업 관련 필드들
- 관련없는 필드: 명시적 표시""",
        agent=result_confirmer
    )

# Task factory functions are ready 