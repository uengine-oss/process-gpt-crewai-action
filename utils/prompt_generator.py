from typing import Dict, List
from langchain_openai import ChatOpenAI
from config.config import settings
from tools.knowledge_manager import Mem0Tool
from utils.logger import log
import json

class DynamicPromptGenerator:
    """동적 프롬프트 생성 클래스"""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4.1",
            temperature=0.1,
            api_key=settings.openai_api_key
        )
    
    def generate_task_prompt(
        self,
        task_instructions: str,
        agent_info: List[Dict],
        form_types: Dict = None,
        output_summary: str = "",
        feedback_summary: str = "",
        current_activity_name: str = "",
        user_info: List[Dict] | None = None
    ) -> tuple[str, str]:
        """모든 정보를 조합하여 최적화된 task 프롬프트 생성"""
        
        # 1. 관련 학습 내용 수집
        learned_knowledge = self._collect_learned_knowledge(agent_info, task_instructions, feedback_summary)
        
        # 2. 컨텍스트 조합
        context = self._build_context(
            task_instructions, agent_info, form_types,
            output_summary, feedback_summary, current_activity_name, learned_knowledge,
            user_info or []
        )
        
        # 3. LLM 기반 프롬프트 생성
        return self._generate_optimized_prompt(context)
    
    def _collect_learned_knowledge(self, agent_info: List[Dict], task_instructions: str, feedback_summary: str) -> Dict[str, str]:
        """에이전트별 관련 학습 내용 수집"""
        
        # 검색 쿼리 생성
        if not task_instructions or not task_instructions.strip():
            return {}
        
        search_query = task_instructions.strip()
        log(f"mem0 검색 쿼리: '{search_query}'")
        
        learned_knowledge = {}
        for agent in agent_info:
            agent_id = agent.get('id')
            tenant_id = agent.get('tenant_id')
            role = agent.get('role', 'Unknown')
            
            if agent_id and tenant_id:
                try:
                    mem0_tool = Mem0Tool(tenant_id=tenant_id, user_id=agent_id)
                    result = mem0_tool._run(search_query)
                    if result and "지식이 없습니다" not in result:
                        learned_knowledge[role] = result
                except Exception as e:
                    log(f"에이전트 {role} 메모리 검색 실패: {e}")
        
        return learned_knowledge
    
    def _build_context(
        self,
        task_instructions: str,
        agent_info: List[Dict],
        form_types: Dict,
        output_summary: str,
        feedback_summary: str,
        current_activity_name: str,
        learned_knowledge: Dict[str, str],
        user_info: List[Dict]
    ) -> str:
        """섹션별로 체계화된 명확한 프롬프트 생성"""
        
        # 입력값 존재 여부 확인
        has_feedback = feedback_summary and feedback_summary.strip() and feedback_summary.strip() != '없음'
        has_learned_knowledge = any(learned_knowledge.values())
        has_output_summary = output_summary and output_summary.strip() and output_summary.strip() != '없음'
        # form_types는 리스트 또는 딕셔너리일 수 있음
        has_form_types = bool(form_types)
        # 표준 구조 지원: {"fields": [...], "html": "..."}
        form_fields = None
        form_html = None
        if isinstance(form_types, dict) and ("fields" in form_types or "html" in form_types):
            form_fields = form_types.get("fields")
            form_html = form_types.get("html")
        else:
            form_fields = form_types if form_types else None
        
        # JSON 형식으로 변환
        agent_info_json = json.dumps(agent_info, ensure_ascii=False, indent=2) if agent_info else '정보 없음'
        user_info_json = json.dumps(user_info, ensure_ascii=False, indent=2) if user_info else '정보 없음'
        learned_knowledge_json = json.dumps(learned_knowledge, ensure_ascii=False, indent=2) if has_learned_knowledge else '관련 경험 없음'
        # 폼 필드/HTML 직렬화 (HTML은 스니펫 없이 전체 전달)
        form_fields_json = json.dumps(form_fields, ensure_ascii=False, indent=2) if form_fields else '특별한 형식 제약 없음'
        form_html_text = form_html if isinstance(form_html, str) and form_html.strip() else ''

        # 우선순위 텍스트 사전 계산 (내용 동일, f-string 단순화)
        if has_feedback:
            first_priority_text = """🔥 1순위 - 피드백 절대 우선:
   - 피드백 요구사항이 모든 지시사항보다 우선 (작업지시사항, 학습경험 등 모두 피드백에 종속)
   - 피드백에서 요구한 변경사항을 정확히 이해하고 100% 적용
   - 기존 방식/관례를 완전히 버리고 피드백이 제시한 새로운 방식으로 전환
   - 피드백 vs 다른 지시사항 충돌 시 → 무조건 피드백 우선
   
   🔄 피드백 동사별 작업지시사항 재해석 규칙:
   - 피드백 "저장" + 작업지시사항 "수정" → INSERT 작업으로 처리
   - 피드백 "수정" + 작업지시사항 "저장" → UPDATE 작업으로 처리
   - 피드백 "삭제" + 작업지시사항 "저장" → DELETE 작업으로 처리
   - 피드백 "조회" + 작업지시사항 "저장" → SELECT 작업으로 처리
   - 여러가지 동사가 있으면 피드백의 동사가 실제 수행할 작업 유형을 최종 결정
   - 피드백의 동사가 실제 수행할 작업 유형을 최종 결정"""
        else:
            first_priority_text = "1순위 - 작업지시사항 그대로 수행"

        if has_learned_knowledge and has_feedback:
            second_priority_text = """2순위 - 학습된 경험 활용:
   - 피드백 범위 내에서 경험을 참고하여 더 완벽하게 처리
   - 피드백이 요구하는 방향성을 유지하면서 경험으로 디테일 보완"""
        elif has_learned_knowledge:
            second_priority_text = """2순위 - 학습된 경험 활용:
   - 또는 작업지시사항은 그대로 하되, 경험을 참고해서 더 디테일하고 완벽하게 처리
   - 경험에서 얻은 노하우로 품질과 정확성 향상"""
        else:
            second_priority_text = "2순위 - 일반 배경지식 활용"
        
        return f"""
다음 정보를 바탕으로 CrewAI Task 프롬프트를 생성하세요:

=== 📋 섹션 1: 입력값 설명 ===

**활동명 (current_activity_name):**
- 값: {current_activity_name or '일반 작업'}
- 역할: 현재 수행중인 업무의 맥락과 목적을 나타냄
- 활용: Task description에서 작업의 배경과 목적 설명에 사용

**팀 구성 (agent_info):**
- 값: {agent_info_json}
- 역할: 협업할 에이전트들의 역할, ID, 테넌트 정보 제공
- 활용: 각 에이전트의 전문성을 고려한 작업 분배 및 협업 지시에 사용

**참가자(실사용자) 정보 (user_info):**
- 값: {user_info_json}
- 역할: 현재 업무의 실제 담당자/참가자 식별 정보(담당자 표기, 연락/검토 지점 반영)
- 활용: 결과물에 담당자/참가자 정보가 요구되면 적절히 반영

**담당자(Owner) 규칙:**
- 담당자 결정: user_info의 사용자들이 현재 작업의 담당자(Owner)로 간주
- 담당자 식별자 우선순위: id → email → name (사용 가능 항목 사용)
- user-select-field 처리: 값은 담당자 식별자 사용 (id가 있으면 id, 없으면 email 사용)
- 텍스트 작성 시: 필요하면 담당자 이름/이메일을 자연스럽게 포함하되 과도한 노출은 피함

**작업 지시사항 (task_instructions):**
- 값: {task_instructions or '명시되지 않음'}
- 역할: 기본적으로 수행해야 할 핵심 업무 내용
- 활용: Task의 주요 목표와 수행 방법의 기준점 (단, 피드백이 있으면 피드백에 의해 재해석됨)

**이전 작업 결과 (output_summary):**
- 값: {output_summary or '없음'}
- 역할: 현재 작업에 필요한 기존 데이터와 컨텍스트 제공
- 활용: 데이터 보완, 연속성 유지, 중복 작업 방지에 핵심적으로 활용
{f'- 🚨 중요: 이전 결과물에는 현재 작업 수행에 필요한 모든 정보가 담겨있음. 절대 생략 금지' if has_output_summary else ''}

**학습된 경험 (learned_knowledge):**
- 값: {learned_knowledge_json}
- 역할: 에이전트별 관련 업무 경험과 노하우 제공
- 활용: 작업 품질 향상과 실수 방지를 위한 참고 자료
{f'- 참고: 현재 수행할 작업을 더 완벽하게 수행하기 위한 디테일 보완에 활용' if has_learned_knowledge else '- 참고: 학습 자료 부족 시에도 작업 중단 금지, 일반 지식으로 초안 작성'}

**피드백 (feedback_summary):**
- 값: {feedback_summary if has_feedback else '없음'}
- 역할: 이전 작업 결과에 대한 수정 요구사항 (최고 우선순위)
- 활용: 모든 다른 지시사항보다 우선하여 작업 방향과 방법을 결정
{f'- 🔥 최우선: 피드백이 있으면 모든 작업은 이 피드백 내용에 따라 재정의됨' if has_feedback else ''}
- 처리방식: 피드백 동사(저장/수정/삭제/조회 등..)가 있으면 그에 맞게 작업지시사항 재해석
- 충돌해결: 피드백 vs 작업지시사항 충돌 시 → 무조건 피드백 우선 적용

**폼 형식 (form_types):**
- 값(필드 정의): {form_fields_json}
- 값(HTML): {form_html_text if form_html_text else '없음'}
- 역할: 최종 결과물의 구조와 필드 정의, 선택형 항목(items) 제공
- 활용: expected_output 구조 설계와 폼_데이터 키/값 결정에 사용
{f'- 주의: key 값을 변경 없이 정확히 필드명으로 사용해야 함' if has_form_types else ''}

**선택형 필드 처리 규칙:**
- form_fields의 type이 'radio' 또는 'select'인 경우, 값 목록은 form_types의 HTML에서 추출
- 예: <radio-field name="review_result" items="[{{'approve':'승인'}},{{'reject':'반려'}}]" ...>
- 파싱 규칙:
  1) HTML의 items 속성 문자열을 JSON으로 변환(단일따옴표 → 쌍따옴표) 후 파싱
  2) 항목 객체의 key가 실제 저장 값, value는 한글 라벨
  3) 최종 폼_데이터에는 key 값 사용 (예: 'approve' 또는 'reject')
  4) radio/select 외 필드는 type에 맞는 적절한 텍스트/숫자 형식 사용
  5) user-select-field는 담당자(Owner)의 식별자 사용 (id 우선, 없으면 email)

=== 🎯 섹션 2: 작업 범위 및 방향 ===

**우선순위 체계:**
{first_priority_text}

{second_priority_text}


**작업 범위 제한 원칙:**
- 명시된 작업만 수행, 비명시 연관작업/후속작업 절대 금지
- 예시 1: "휴가 정보 저장" → 오직 휴가정보만 저장, 휴가잔여일수 수정/알림발송/승인처리 등 금지
- 예시 2: "주문 정보 저장" → 오직 주문정보만 저장, 재고감소/포인트적립/알림발송 등 금지
- 예시 3: "사용자 정보 수정" → 명시된 사용자의 명시된 필드만 수정, 다른 사용자/필드 수정 금지
- 범위 모호 시: human_asked 도구로 "이 작업 범위가 맞는지" 사용자 확인 후 진행 (text 형식으로 질문)

**다중 작업 처리 원칙:**
- 반드시 작업지시사항에서 실행 동사를 기준으로 원자 작업을 모두 추출하여 목록화(예: 저장, 확인, 조회 등)
- 모든 원자 작업을 반드시 수행해야 함 
- 즉, 작업지시에 여러 작업이 있을 경우 해당 작업을 모두 수행해야 함
- 작업 간 선후관계/의존성을 파악하여 올바른 순서로 실행
- 쓰기 작업(INSERT/UPDATE/DELETE)은 human_asked(type="confirm") 승인 후에만 수행

=== 💾 섹션 3: 데이터 쓰기/수정 시 정확성 보장 ===

**데이터 완전성 확보 4단계 절차:**
1. 이전 작업 결과물에서 사용 가능한 데이터 최대한 활용
2. 부족한 데이터는 읽기전용 도구로 조회/검증/보완 (SELECT 쿼리, 검색 API, 메시징 API 등)
3. 모든 필요 데이터가 완전해진 후에만 쓰기 작업 수행
4. 데이터를 저장 및 수정할 경우, 주어진 값을 최대한 활용해서 다른 테이블의 값을 조회하는 등, 툴을 적극 활용해서 완전한 데이터를 생성 및 수정해야 함, 절대 누락되는 컬럼이나 데이터가 있어서는 안됩니다.
5. INSERT/UPDATE/DELETE(저장/수정/삭제) 수행 전, 반드시 human_asked(type="confirm")로 사용자 승인 획득(승인 없으면 절대 실행 금지)


=== 🎨 섹션 4: 콘텐츠 생성 시 가이드라인 ===

**폼 형식별 창의적 콘텐츠 생성 원칙:**

**슬라이드 형식 (presentation, slide 등):**
- **구조**: 제목 슬라이드 → 목차 → 본문 슬라이드들 → 결론/질의응답 슬라이드
- **분량**: 최소 15장 이상 구성(많을 수록 좋음)
- **형식**: reveal.js 마크다운 형식으로 결과물 생성
- **내용 기반**: 보고서가 있을 경우 보고서 내용을 기반으로 슬라이드 생성, 없으면 주제에 맞게 적절히 생성
- **기술적 요구사항**:
  * reveal.js 구문 사용 (새 슬라이드용 ---, 수직 슬라이드용 --)
  * 불릿 포인트, 헤더, 강조 형식 적절히 활용
  * 논리적 슬라이드 전환과 흐름
  * 깔끔하고 전문적인 프레젠테이션 구조
  * 적절한 경우 사용자 정보 통합(발표자 이름, 부서 등)
- **🚨 중요한 출력 형식 규칙**:
  * 절대로 ```markdown, ```html, ``` 같은 코드 블록으로 결과를 감싸지 마세요
  * 마크다운 내용을 직접 출력하세요 (코드 블록 없이)
  * reveal.js 마크다운 구문을 그대로 사용하되, 코드 블록으로 감싸지 말 것
  * HTML 주석이나 코드 블록 형태의 감싸기는 절대 금지

**리포트 형식 (report, document 등):**
- **형식**: 마크다운(Markdown) 형식으로 결과물 생성
- **기본 구조**: 서론 → 본론 → 결론 형식
- **소제목과 목차**: 내용에 맞게 유연하게 적절히 알아서 생성
- **내용 작성 원칙**:
  * 데이터 기반 객관적 서술
  * 논리적 흐름과 근거 제시
  * 내용이 많을수록 좋음 (상세하고 풍부한 내용 작성)
- **출처 표기**: 내용을 검색이나 참고자료에서 가져왔다면 반드시 출처 명시
  * 마크다운 링크 형식: `[출처명](URL)` 또는 각주 형식 사용
  * 참고문헌 섹션에 모든 출처 정리

**일반 폼 데이터 생성:**
- 폼 타입의 이름과 용도에 맞는 적절한 내용 생성
- 폼 타입의 모든 필수 필드 완전히 채움
- 실제 업무에서 사용할 수 있는 현실적인 데이터 생성
- 일관성 있는 데이터 관계 유지 (예: 부서-직책-권한 매칭)
- 폼의 목적과 맥락에 부합하는 의미 있는 데이터 생성

**콘텐츠 생성 시 주의사항:**
- 모든 가용 도구를 적극 활용하여 정보 수집:
  * 검색 도구들 (search)
  * 데이터베이스 조회 도구
  * API 호출 도구들
  * 메시징/커뮤니케이션 도구
  * mem0/memento 등 메모리 도구
- 도구 결과가 부족하거나 없어도 작업 중단 및 실패 금지
- 일반적 배경지식과 주어진 문맥 흐름을 기반으로 초안 작성
- 폼 요구사항과 작업 맥락에 맞는 적절한 내용 생성

=== 🛠️ 섹션 5: 도구 사용 가이드라인 ===

**모든 가용 도구 적극 활용 원칙:**
- **검색 도구들**: search 등 모든 검색 도구 적극 활용
- **데이터베이스 도구**: SELECT 쿼리 등 데이터 조회 도구 활용
- **API 호출 도구**: 검색 API, 조회 API 등 외부 연동 도구 활용
- **메시징/커뮤니케이션 도구**: 정보 수집 및 확인용 도구 활용
- **mem0/memento 도구**: 메모리 기반 정보 검색 도구 활용
- **기타 모든 읽기전용 도구들**: 정보 수집에 도움이 되는 모든 도구 활용

**도구 사용 시 주의사항:**
- 반드시 적극적으로 도구를 활용하되, 도구 결과가 부족하거나 없어도 작업 중단 및 실패 금지
- 여러 도구를 조합하여 최대한 많은 정보 수집
- 도구 결과에만 의존하지 말고 일반 배경지식도 활용

**human_asked 도구:**
- 사용 시점:
  * 작업 범위가 모호할 때
  * 보안/민감 작업 수행 전
  * 특정 데이터를 쓰거나 수정하기 전
- 질문 형식: 부족한 정보 및 승인 요청을 사용자로 부터 받기 위해 3가지 타입중 선택
 - 필수 규칙(쓰기 작업): INSERT/UPDATE/DELETE(저장/수정/삭제) 전에는 반드시 type="confirm"으로 승인 요청 → ✅ 승인 시에만 실행, ❌ 거절 또는 미응답 시 즉시 중단

=== 📤 프롬프트 생성 최종 지침 ===

**달성 목표 (작업지시사항 범위 내에서만):**
- 구체적으로 무엇을 완성해야 하는지
- 어떤 품질과 기준을 만족해야 하는지
- 특별히 주의해야 할 요구사항이 있는지
- 범위를 벗어난 작업은 절대 수행하지 않을 것
- 데이터 처리 시 완전성과 정확성을 보장할 것

**성공 기준:**
- 명시된 목표들이 전부 달성되어야 함 (일부만 달성하면 실패)
{f'- 피드백 내용을 100% 반영하여 처리' if has_feedback else ''}
- 요구된 형식으로 결과 제공
- 작업 범위 엄수 확인

JSON 형식으로 응답: {{"description": "명확한 작업 지시와 실행 방법", "expected_output": "구체적인 결과 형식과 성공 기준"}}
"""
    
    def _generate_optimized_prompt(self, context: str) -> tuple[str, str]:
        """LLM 기반 프롬프트 생성"""
        
        system_prompt = """당신은 CrewAI Task description을 작성하는 전문가입니다.

**역할**: 주어진 컨텍스트 정보를 바탕으로 에이전트가 수행할 구체적인 작업 지시(description)와 결과 형식(expected_output)을 생성합니다.
**응답 형식**: 반드시 JSON 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요.
**주의사항**: 모든 가용 도구를 적극 활용하되, 도구 결과가 부족하거나 없어도 작업 중단 및 실패 금지 -> 일반 배경지식 및 문맥 흐름으로 초안 작성

**expected_output 상세 작성 지침:**
- 다음 예시 구조를 반드시 준수하되, 값은 실제 작업 결과로 채워야 한다고 명시:
  ```json
  {
    "상태": "SUCCESS" 또는 "FAILED",
    "수행한_작업": "읽기 좋은 자연어 텍스트로 수행 내역을 문단/불릿 형태로 서술",
    "폼_데이터": {
      // 폼타입에 맞는 실제 데이터 (반드시 key 값을 필드명으로 사용)
      form_key : 실제 데이터 값
    }
  }
  ```
- "위 구조는 예시이며, 예시 값들을 그대로 사용하지 말고, 실제 작업 결과로 대체해야 합니다"
- 폼_데이터 키 규칙: 폼타입의 'key' 값을 변경 없이 원본 그대로 정확히 필드명으로 사용해야 함
- 폼_데이터에는 요구된 폼타입 필드들이 정확히 포함되어야 함을 명시
- 수행한_작업 형식: 반드시 '문자열 텍스트'로만 작성. 배열/객체/리스트 금지. 불릿(-) 또는 번호를 사용한 가독성 좋은 서술 권장
- 수행한_작업에는 작업지시사항에서 추출한 모든 원자 작업이 누락 없이 포함되어야 하며, 누락 시 FAILED로 간주

**선택형(radio/select) 값 결정 지침:**
- form_types에 HTML이 제공되면 해당 필드의 items를 HTML에서 파싱하여 실제 선택 가능한 값 목록을 결정
- items 예시: [{"approve":"승인"},{"reject":"반려"}] → 폼_데이터 값은 "approve" 또는 "reject" 중 하나여야 함

**응답 형식**: 오직 다음 JSON만 응답하세요:
{"description": "Task 형식의 구체적 작업 지시", "expected_output": "결과 형식 안내"}

어떤 설명이나 추가 텍스트도 포함하지 마세요. 순수 JSON만 응답하세요."""
        
        try:
            response = self.llm.invoke([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context}
            ])
            
            # 응답 확인을 위한 디버깅 로그
            response_text = response.content.strip()
            log(f"LLM 원본 응답: {response_text}")  # 처음 200자만 로그
            
            # JSON 파싱
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                json_text = response_text[start:end].strip()
            else:
                json_text = response_text
            
            data = json.loads(json_text)
            description = data.get("description", "")
            expected_output = data.get("expected_output", "")
            
            log("동적 프롬프트 생성 완료")
            return description, expected_output
            
        except Exception as e:
            log(f"프롬프트 생성 실패: {e}")
            log(f"응답 텍스트: {response_text if 'response_text' in locals() else 'N/A'}")
            # 기본 프롬프트 반환 (간단한 형태)
            return (
                "사용자 요청을 분석하고 팀 에이전트들과 협업하여 처리하세요. 피드백이 있으면 최우선 처리하고, 실제 도구를 사용하여 정확한 결과를 도출하세요.",
                '{"상태": "SUCCESS/FAILED", "수행한_작업": "구체적 내용", "폼_데이터": {}} JSON 형식으로 결과를 제공하세요.'
            )