from crewai import Task
import logging

logger = logging.getLogger(__name__)

def create_parse_task(requirement_parser):
    """RequirementParser용 Task 생성"""
    return Task(
        description="""사용자 요구사항을 정확히 분석하여 실제 정보 추출:

작업 지시사항: {task_instructions}
저장될 데이터: {user_request}

작업:
- 작업 지시사항({task_instructions})을 참고하여 어떤 테이블에 어떤 방식으로 작업할지 결정
- 저장될 데이터({user_request})에서 작업 유형(저장/조회/수정/삭제)과 관련 데이터를 파싱
- 누락된 필수 정보에 대해 적절한 기본값 설정 (수량: 1, 가격: 제품별 추정, 이메일: 이름 기반 생성 등)
- list_tables로 테이블·관계 조회 → 관련 테이블 선별
- generate_typescript_types로 스키마 조회 → 실행 순서 결정
- 실제 추출한 데이터와 기본값을 결합하여 구조화된 정보 생성 (템플릿 텍스트나 예시 데이터 사용 금지)

중요: 작업 지시사항을 기반으로 적절한 테이블과 작업 방식을 선택하고, 저장될 데이터에서 실제 값과 의도된 작업 유형을 정확히 추출하여 처리하세요!""",
        expected_output="JSON 형태: {operation: insert|update|select|delete, tables: [순서대로], relationships: [FK정보], data: {테이블별 실제값/조건, defaults_used: [기본값컬럼들]}}",
        agent=requirement_parser
    )

def create_plan_task(db_planner):
    """DBPlanner용 Task 생성"""
    return Task(
        description="""RequirementParser 결과를 받아 PostgreSQL DML 쿼리 생성:

작업:
- 파싱된 operation과 테이블 순서를 바탕으로 외래키 의존성 고려
- 각 테이블별 데이터에서 values와 conditions 구분하여 SQL 생성
- RETURNING 절과 플레이스홀더(:변수명) 포함한 완전한 쿼리 작성
- 기존 데이터 중복 체크 결과(existing_check)를 활용한 UPSERT 처리

중요: PostgreSQL 표준 문법을 준수하고, 의존 순서를 정확히 반영하여 안전한 쿼리를 생성하세요!""",
        expected_output="JSON 형태: {operation: string, queries: [{table, sql, returns, depends_on, uses_existing?, skip_if_exists?}]}",
        agent=db_planner
    )

def create_execute_task(sql_executor):
    """SQLExecutor용 Task 생성"""
    return Task(
        description="""DBPlanner가 생성한 SQL 쿼리들을 순차적으로 실행:

작업:
- queries 배열을 순서대로 처리
- RETURNING 절에서 받은 값을 다음 쿼리의 플레이스홀더에 대입
- 중복 체크 결과에 따른 조건부 실행 (skip_if_exists, uses_existing 활용)
- 각 쿼리별 실행 결과와 에러 처리

중요: execute_sql 툴을 실제로 사용하여 모든 쿼리를 실행하고, 실제 RETURNING 값만 사용하세요!""",
        expected_output="각 쿼리별 실행 결과: {테이블명: {성공여부, 영향받은행수, RETURNING값, 에러메시지}}",
        agent=sql_executor
    )

def create_confirm_task(result_confirmer):
    """ResultConfirmer용 Task 생성"""
    return Task(
        description="""SQL 실행 결과를 검증하고 최종 결과를 사용자에게 제공:

작업:
- SQLExecutor의 실행 결과에서 삽입/수정된 레코드 ID 파악
- SELECT 쿼리로 실제 데이터베이스에 반영된 최종 결과 조회
- 사용자가 이해하기 쉬운 형태로 결과 요약

중요: execute_sql 툴을 사용하여 실제 데이터를 조회하고, 올바른 컬럼명을 사용하세요!""",
        expected_output="최종 작업 결과 요약 (실제 DB 데이터 기반)",
        agent=result_confirmer
    )

# Task factory functions are ready 