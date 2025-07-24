from crewai import Task
import logging

logger = logging.getLogger(__name__)

def create_parse_task(requirement_parser):
    """RequirementParser용 Task 생성"""
    return Task(
        description="""🔥 **지능형 작업 분석**: 이전 결과물과 작업 지시사항을 종합하여 최적의 데이터베이스 작업을 계획하세요!

현재 작업: {current_activity_name}
작업 지시사항: {task_instructions}
이전 결과들: {all_previous_outputs}

**🚨 핵심 작업 전략:**

**1. 이전 결과물 활용 (필수):**
- all_previous_outputs에서 현재 작업에 필요한 정보 추출
- 고객정보, 제품정보, 주문정보, 재고정보 등 관련 데이터 파악
- 이전 단계의 결과를 바탕으로 현재 단계에서 무엇을 해야 하는지 결정

**2. 작업 범위 결정:**
- **다중 테이블 작업**: task_instructions에 여러 테이블 명시 또는 의미상 여러 작업 포함
  - 예: "주문 저장하고 재고 감소", "orders 테이블과 product 테이블 작업"
- **단일 테이블 작업**: 명확히 하나의 테이블/작업만 지시된 경우

**3. 테이블명 지능형 유추:**
테이블명이 명시되지 않은 경우:
- 전달된 데이터 유형 분석 (고객정보 → customers, 제품정보 → product 등)
- 작업 성격 파악 (주문처리 → orders, 재고관리 → product 등)
- 이전 결과물에서 유사 작업 패턴 참조

**4. 외래키 자동 해결 (중요):**
필수 필드가 누락된 경우 다른 테이블에서 자동 조회:
- 고객명/이메일 → customers 테이블에서 customer_id 조회
- 제품명/제품코드 → product 테이블에서 product_id, 가격, 재고 조회
- 카테고리명 → categories 테이블에서 category_id 조회
- 기타 참조 정보들을 적절한 테이블에서 조회

**5. 새로운 ID 생성 전략 (INSERT 작업용):**
신규 레코드 생성 시 기존 데이터의 ID 스타일을 참고하여 일관성 유지:
- 기존 ID 패턴 분석: 해당 테이블의 최근 ID들 확인하여 형식 파악
- 패턴별 생성: 순번형/날짜형/UUID형 등 기존 스타일에 맞춰 생성
- 고유성 보장: 중복 확인 후 고유한 ID 생성
- 예: orders 테이블에 "ORD-20240115-001" 패턴이 있으면 "ORD-20240115-002" 생성

**작업 프로세스:**
1. **현재 상황 파악**: current_activity_name과 이전 결과들로 현재 단계 이해
2. **데이터베이스 구조 조회**: list_tables로 모든 테이블 파악
3. **작업 대상 테이블 결정**: 지시사항 분석 + 데이터 유형 분석
4. **테이블 스키마 조회**: generate_typescript_types로 관련 테이블들의 구조 파악
5. **외래키 정보 수집**: execute_sql로 누락된 참조 정보 조회
6. **새로운 ID 생성** (INSERT 시): 기존 ID 패턴 분석하여 일관된 새 ID 생성
7. **완전한 작업 계획 수립**: 모든 필요 정보가 포함된 작업 계획 생성

**실제 작업 예시:**

**예시 1 - 주문 처리 (외래키 자동 해결 + ID 생성):**
- 이전 결과: 고객 선택, 제품 선택 완료
- 현재 단계: 주문 저장
- 전달 데이터: {"고객명": "홍길동", "제품명": "노트북", "수량": 2}
- 자동 처리: 
  - customers에서 customer_id 조회 ("CUST-001")
  - product에서 product_id와 가격 조회 ("PROD-ELE-001", 1500000)
  - orders 테이블 기존 ID 패턴 확인 ("ORD-20240115-001", "ORD-20240115-002")
  - 새로운 order_id 생성 ("ORD-20240115-003")
- 최종 결과: orders 테이블에 완전한 주문 정보 저장

**예시 2 - 다중 테이블 작업:**
- 지시사항: "주문을 저장하고 해당 제품의 재고를 감소시켜주세요"
- 테이블1: orders (INSERT) - 주문 정보 저장
- 테이블2: product (UPDATE) - 재고 수량 감소

**예시 3 - 테이블명 유추:**
- 지시사항: "신규 고객 정보를 등록해주세요"
- 데이터 분석: 고객명, 이메일, 전화번호 포함
- 결과: customers 테이블로 유추하여 INSERT 작업

**중요 지침:**
- 반드시 list_tables, generate_typescript_types, execute_sql 툴을 실제로 사용
- 이전 결과물의 맥락을 충분히 고려
- 누락된 정보는 적극적으로 다른 테이블에서 조회
- 작업의 완전성을 위해 필요한 모든 테이블 작업 계획""",
        expected_output="""JSON 형태로 완전한 작업 계획 반환:

**단일 테이블 작업:**
{
  "operation": "insert|update|select|delete",
  "tables": ["대상_테이블"],
  "relationships": [],
  "data": {
    "테이블명": {
      "columns": ["실제_컬럼들"],
      "values": {"column1": "값1", "column2": "값2"},
      "foreign_keys": {"fk_column": "조회된_외래키_값"},
      "generated_ids": {"id_column": "새로생성된_ID"},
      "defaults_used": ["기본값_사용된_컬럼들"]
    }
  }
}

**다중 테이블 작업:**
{
  "operation": "multi",
  "tables": ["테이블1", "테이블2"],
  "relationships": ["테이블간_관계_설명"],
  "data": {
    "테이블1": {
      "operation": "insert|update|select|delete",
      "columns": ["컬럼들"],
      "values": {...},
      "foreign_keys": {...},
      "generated_ids": {...}
    },
    "테이블2": {
      "operation": "update",
      "columns": ["컬럼들"],
      "conditions": {"where_column": "조건값"},
      "values": {"update_column": "새값"}
    }
  }
}""",
        agent=requirement_parser
    )

def create_plan_task(db_planner):
    """DBPlanner용 Task 생성"""
    return Task(
        description="""🚨 **지능형 SQL 생성**: RequirementParser 결과와 이전 작업 결과들을 종합하여 최적의 PostgreSQL 쿼리들을 생성하세요!

현재 작업: {current_activity_name}
작업 지시사항: {task_instructions}
이전 결과들: {all_previous_outputs}

**🔥 핵심 생성 전략:**

**0. 이전 작업 결과 종합 분석 (최우선):**
- **all_previous_outputs에서 작업 맥락 파악**: 이전 단계에서 어떤 작업이 수행되었는지 확인
- **관련 데이터 추출**: 고객정보, 제품정보, 주문정보, 재고정보 등 현재 SQL 생성에 필요한 정보 수집
- **작업 연속성 보장**: 이전 단계의 결과를 바탕으로 현재 단계에서 수행할 작업의 정확한 컨텍스트 이해
- **데이터 일관성 확인**: 이전 결과와 현재 요청 사항 간의 일관성 검증
- **작업 순서 최적화**: 이전 작업의 결과를 고려하여 현재 SQL 실행 순서 결정


**1. RequirementParser 결과 완전 활용:**
- "operation" 필드로 단일/다중 테이블 작업 구분
- "tables" 배열의 모든 테이블에 대한 쿼리 생성
- "data" 객체에서 각 테이블별 정확한 컬럼명과 값 추출
- "foreign_keys" 정보를 활용한 참조 무결성 보장

**2. 작업 유형별 쿼리 생성:**

**단일 테이블 작업:**
- INSERT: 새 레코드 삽입
- UPDATE: 기존 레코드 수정 (재고 감소/증가 등)
- SELECT: 데이터 조회
- DELETE: 레코드 삭제

**다중 테이블 작업 (operation: "multi"):**
- 외래키 의존성 분석 후 실행 순서 결정
- 부모 테이블 → 자식 테이블 순서로 INSERT
- 자식 테이블 → 부모 테이블 순서로 DELETE
- UPDATE는 의존성에 따라 적절한 순서 결정

**3. 실행 순서 최적화:**
- 외래키 제약 조건 분석
- 참조 무결성 위반 방지
- 트랜잭션 안전성 보장

**4. PostgreSQL 표준 준수:**
- 정확한 문법 사용
- 큰따옴표로 컬럼명 감싸기
- 작은따옴표로 문자열 값 감싸기
- WHERE 절 필수 포함 (UPDATE/DELETE)

**실제 쿼리 생성 예시:**

**예시 0 - 이전 결과 활용한 쿼리 생성:**
```
이전 작업 결과 (all_previous_outputs):
- 1단계: "고객 홍길동 선택됨 (customer_id: CUST-001)"
- 2단계: "제품 노트북 선택됨 (product_id: PROD-ELE-001, 가격: 1,500,000원)"
- 3단계: "수량 2개 확정됨"

현재 작업 지시사항 (task_instructions):
"주문 정보를 저장하고 재고를 감소시켜주세요"

RequirementParser 결과:
"operation": "multi"
"tables": ["orders", "products"]

생성할 쿼리 (이전 결과 반영):
1. INSERT INTO orders ("order_id", "customer_id", "product_id", "quantity", "unit_price", "total_price")
   VALUES ('ORD-20240115-003', 'CUST-001', 'PROD-ELE-001', 2, 1500000, 3000000)
2. UPDATE products SET "stock_quantity" = stock_quantity - 2 WHERE "product_id" = 'PROD-ELE-001'
```

**예시 1 - 단일 테이블 INSERT:**
```
RequirementParser 결과:
"operation": "insert"
"tables": ["orders"]
"data": {
  "orders": {
    "columns": ["order_id", "customer_id", "product_id", "quantity"],
    "values": {"order_id": "ORD-123", "customer_id": "CUST-001", "product_id": "PROD-001", "quantity": 2}
  }
}

생성할 쿼리:
INSERT INTO orders ("order_id", "customer_id", "product_id", "quantity") 
VALUES ('ORD-123', 'CUST-001', 'PROD-001', 2)
```

**예시 2 - 다중 테이블 작업:**
```
RequirementParser 결과:
"operation": "multi"
"tables": ["orders", "product"]
"data": {
  "orders": {
    "operation": "insert",
    "columns": ["order_id", "customer_id", "product_id", "quantity"],
    "values": {...}
  },
  "product": {
    "operation": "update",
    "columns": ["stock_quantity"],
    "conditions": {"product_id": "PROD-001"},
    "values": {"stock_quantity": "stock_quantity - 2"}
  }
}

생성할 쿼리:
1. INSERT INTO orders (...) VALUES (...)
2. UPDATE product SET "stock_quantity" = stock_quantity - 2 WHERE "product_id" = 'PROD-001'
```

**중요 규칙:**
- **이전 작업 결과 최우선 반영**: all_previous_outputs에서 추출한 정보를 SQL 생성에 적극 활용
- **작업 맥락 연속성 보장**: 이전 단계와 현재 단계 간의 논리적 연결성 유지
- RequirementParser의 "columns" 배열 정확히 사용
- 절대로 한글 컬럼명 사용 금지
- 외래키 관계 고려한 실행 순서
- 모든 테이블 작업을 빠짐없이 포함
- **이전 결과에서 누락된 정보가 있다면 적절한 기본값 또는 조회 로직 포함**""",
        expected_output="""JSON 형태로 실행 가능한 쿼리 계획 반환:

**단일 테이블:**
{
  "operation": "insert|update|select|delete",
  "execution_order": ["테이블명"],
  "queries": [
    {
      "table": "테이블명",
      "sql": "정확한_PostgreSQL_쿼리",
      "dependencies": []
    }
  ]
}

**다중 테이블:**
{
  "operation": "multi",
  "execution_order": ["테이블1", "테이블2", "테이블3"],
  "queries": [
    {
      "table": "테이블1",
      "sql": "첫번째_쿼리",
      "dependencies": []
    },
    {
      "table": "테이블2", 
      "sql": "두번째_쿼리",
      "dependencies": ["테이블1"]
    }
  ]
}""",
        agent=db_planner
    )

def create_execute_task(sql_executor):
    """SQLExecutor용 Task 생성"""
    return Task(
        description="""DBPlanner가 생성한 SQL 쿼리들을 순차적으로 실행:

현재 작업: {current_activity_name}

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

현재 작업: {current_activity_name}
이전 결과들: {all_previous_outputs}

**🔥 CRITICAL: 이전 결과 활용 방법**
1. **RequirementParser 결과에서 식별값 추출**:
   - `{"order_id": "ORD-123"}` → WHERE order_id = 'ORD-123'
   - `{"customer_id": "CUST-456"}` → WHERE customer_id = 'CUST-456'
   
2. **SQLExecutor 결과 확인**:
   - `{"성공여부": "성공", "영향받은행수": 1}` → INSERT 성공 확인

3. 이전 결과를 활용해서 결과에 포함을 시켜야할 게 있으면 포함시켜야함 (예 : 주문수량 같은 정보)
즉, select문 결과에 대해서 다 매칭을 처리하고 나고 남은 필드는 이전 결과에서 찾아서 포함시켜야함

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
   
   **🚨 CRITICAL: 폼 ID와 값만 매핑 (추가 텍스트 금지)**
   각 form_id에 대해 단순히 값만 반환하세요. "필드명:" 같은 추가 텍스트는 절대 포함하지 마세요!
   
   **폼 타입별 올바른 값 형식:**
   - text/textarea: 실제 내용만 (예: "노트북 2대")
   - number: 숫자값만 (예: "1500000" 또는 "5")
   - select/dropdown: 선택된 옵션만 (예: "택배")
   - checkbox: 선택된 항목들만 (예: "포장지, 영수증")
   - radio: 선택된 값만 (예: "신용카드")
   - date: 날짜값만 (예: "2024-01-15")
   - file: 파일명만 (예: "document.pdf")
   - email: 이메일 주소만 (예: "hong@example.com")
   - report: 보고서 내용만
   - slide: 프레젠테이션 내용만
   
   **올바른 매핑 예시:**
   
   **저장 작업 (INSERT):**
   - order_id: "ORD-123"
   - order_details: "노트북 2개, 단가 1,500,000원, 총액 3,000,000원"
   - customer_info: "홍길동 (hong@example.com)"
   - payment_method: "신용카드"
   - delivery_options: "빠른배송, 포장지 포함"
   - order_date: "2024-01-15"
   - unrelated_field: "이 작업과 관련 없음"
   
   **수정 작업 (UPDATE):**
   - update_result: "수량이 2개에서 3개로 수정됨"
   - updated_values: "변경 전: 2개 → 변경 후: 3개"
   - status_change: "대기중에서 처리중으로 변경"
   - unrelated_field: "이 수정 작업과 관련 없음"
   
   **조회 작업 (SELECT):**
   - search_result: "홍길동 정보 조회 완료"
   - found_data: "hong@example.com, 010-1234-5678"
   - unrelated_field: "이 조회 작업과 관련 없음"
   
   **삭제 작업 (DELETE):**
   - delete_result: "ORD-123 삭제 완료"
   - deleted_info: "노트북 2개 (총 3,000,000원)"
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

**🚨 CRITICAL: 값만 반환 (필드명 포함 금지)**
각 form_id에 대해 순수한 값만 반환하세요. "필드명:" 같은 텍스트는 절대 포함하지 마세요!

**타입별 올바른 값 반환 형식:**
- text/textarea: "처리된 텍스트 내용" 또는 "이 작업과 관련 없음"
- number: "숫자값" 또는 "처리되지 않음"
- select/dropdown: "선택된_옵션명" 또는 "선택 없음"
- checkbox: "선택된항목1, 선택된항목2" 또는 "체크 없음"
- radio: "선택된_단일값" 또는 "선택 없음"
- date: "YYYY-MM-DD" 또는 "날짜 정보 없음"
- email: "이메일@주소.com" 또는 "이메일 정보 없음"
- file: "파일명.확장자" 또는 "파일 없음"
- report: "상세한 보고서 형태 내용" 또는 "보고서 관련 없음"
- slide: "요약된 프레젠테이션 내용" 또는 "프레젠테이션 관련 없음"

**최종 JSON 구조 (모든 필드 포함 필수):** 
{
  "form_field_id1": "순수한_값만",
  "form_field_id2": "처리결과_값만",
  "form_field_id3": "이_작업과_관련_없음",
  "form_field_id4": "처리되지_않음",
  ...
  // form_types의 모든 필드 반드시 포함
  // "필드명:" 같은 추가 텍스트는 절대 포함하지 말 것
}

**검증 결과 예시:**
- 총 필드 수: form_types 필드 개수와 정확히 일치
- 누락된 필드: 0개 (반드시)
- 처리된 필드: 실제 작업 관련 필드들
- 관련없는 필드: 명시적 표시""",
        agent=result_confirmer
    )

# Task factory functions are ready 