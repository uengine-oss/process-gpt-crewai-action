import time
import json
import logging
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from processgpt_agent_utils.tools.knowledge_manager import Mem0Tool

# 로깅 설정
logger = logging.getLogger(__name__)


class DynamicPromptGenerator:
    """동적 프롬프트 생성기 주어진 입력들을 바탕으로 Task용 description과 expected_output을 생성합니다."""

    def __init__(self, llm):
        self.llm = llm


    async def generate_task_prompt(
        self,
        task_instructions: str,
        agent_info: List[Dict],
        form_types: Dict = None,
        form_html: str = "",
        feedback_summary: str = "",
        current_activity_name: str = "",
        user_info: Optional[List[Dict]] = None,
    ) -> Tuple[str, str]:
        """두 LLM 호출로 설명/결과물을 분리 생성하고 asyncio.gather로 병렬 실행."""

        learned_knowledge = self._collect_learned_knowledge(
            agent_info=agent_info,
            task_instructions=task_instructions,
            feedback_summary=feedback_summary,
        )

        # 설명용 브리프: 폼 정보 제외
        desc_brief = self._build_description_prompt(
            task_instructions=task_instructions,
            agent_info=agent_info,
            user_info=user_info or [],
            feedback_summary=feedback_summary,
            current_activity_name=current_activity_name,
            learned_knowledge=learned_knowledge,
        )

        # 결과물용 브리프: 폼 정보만 포함
        expected_brief = self._build_expected_output_prompt(
            form_types=form_types,
            form_html=form_html,
        )

        description_system = self._build_system_prompt_description()
        expected_system = self._build_system_prompt_expected_output()

        async def ainvoke_text(system_prompt: str, user_prompt: str) -> str:
            """LLM을 호출해 순수 텍스트 응답을 받아요"""
            
            start_time = time.time()
            response = await self.llm.ainvoke([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ])
            raw = getattr(response, "content", response)
            text = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in raw) if isinstance(raw, list) else str(raw)
            text = (text or "").strip()
            logger.info("📝 LLM(ainvoke) 완료 - %.2fs, %d chars", time.time() - start_time, len(text))
            if not text:
                logger.error("❌ LLM 빈 응답 수신: system_prompt 길이=%d, user_prompt 길이=%d", len(system_prompt), len(user_prompt), exc_info=False)
                raise ValueError("Empty response from LLM")
            return text

        desc_task = asyncio.create_task(ainvoke_text(description_system, f"[ROLE=description]\n{desc_brief}\n설명만 한 문단으로."))
        out_task  = asyncio.create_task(ainvoke_text(expected_system, f"[ROLE=expected_output]\n{expected_brief}"))
        
        try:
            description, expected_output = await asyncio.gather(desc_task, out_task)
            logger.info("✅ 비동기 분리 프롬프트 생성 완료")
            return description, expected_output
        except Exception as e:
            logger.error("❌ 동적 Task description/expected_output 생성 실패(raise): %s", e, exc_info=True)
            raise

    # ----------------------------
    # 내부 로직
    # ----------------------------
    def _collect_learned_knowledge(
        self,
        agent_info: List[Dict],
        task_instructions: str,
        feedback_summary: str,
    ) -> Dict[str, str]:
        """에이전트별 관련 학습 내용 수집"""
        if not task_instructions or not task_instructions.strip():
            return {}

        query = f"{task_instructions.strip()}\n{feedback_summary.strip()}"
        logger.info("🧠 mem0 사전 훈련 데이터 검색 시작")

        learned: Dict[str, str] = {}
        for ag in agent_info:
            agent_id = ag.get("id")
            tenant_id = ag.get("tenant_id")
            role = ag.get("role", "Unknown")

            if not (agent_id and tenant_id):
                continue

            try:
                mem0_tool = Mem0Tool(tenant_id=tenant_id, user_id=agent_id)
                result = mem0_tool._run(query)
                if result and "지식이 없습니다" not in result:
                    learned[role] = result
            except Exception as e:
                logger.warning("⚠️ 에이전트 %s 메모리 검색 실패: %s", role, e)

        return learned


    def _build_description_prompt(
        self,
        task_instructions: str,
        agent_info: List[Dict],
        user_info: List[Dict],
        feedback_summary: str,
        current_activity_name: str,
        learned_knowledge: Dict[str, Any],
    ) -> str:
        """설명 프롬프트: form_types/form_html 제외, 나머지 컨텍스트를 원문 스타일로 포함."""
        
        has_feedback = bool(feedback_summary and feedback_summary.strip() and feedback_summary.strip() != '없음')
        has_learned = bool(learned_knowledge and any(str(v).strip() for v in learned_knowledge.values()))
        agent_info_json = json.dumps(agent_info or [], ensure_ascii=False, indent=2) if agent_info else '정보 없음'
        user_info_json = json.dumps(user_info or [], ensure_ascii=False, indent=2) if user_info else '정보 없음'
        learned_json = json.dumps(learned_knowledge or {}, ensure_ascii=False, indent=2) if has_learned else '관련 경험 없음'

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

        if has_learned and has_feedback:
            second_priority_text = """2순위 - 학습된 경험 활용:
   - 피드백 범위 내에서 경험을 참고하여 더 완벽하게 처리
   - 피드백이 요구하는 방향성을 유지하면서 경험으로 디테일 보완"""
        elif has_learned:
            second_priority_text = """2순위 - 학습된 경험 활용:
   - 또는 작업지시사항은 그대로 하되, 경험을 참고해서 더 디테일하고 완벽하게 처리
   - 경험에서 얻은 노하우로 품질과 정확성 향상"""
        else:
            second_priority_text = "2순위 - 일반 배경지식 활용"

        return f"""
다음 정보를 바탕으로 CrewAI Task description 프롬프트를 생성하세요:

=== 📋 섹션 1: 입력값 설명 ===

**활동명 (current_activity_name):**
- 값: {current_activity_name or '일반 작업'}
- 역할: 현재 수행중인 업무 이름을 나타냄
- 활용: 이름이 의미하는 작업의 배경과 목적 설명에 사용

**팀 구성 (agent_info):**
- 값: {agent_info_json}
- 역할: 협업할 에이전트들의 역할, ID, 테넌트 정보 제공
- 활용: 각 에이전트의 전문성을 고려한 작업 분배 및 협업 지시에 사용

**담당자(Owner) (user_info):**
- 값: {user_info_json}
- 역할: 현재 업무의 실제 담당자 정보(담당자 표기, 연락/검토 지점 반영)
- 활용: 결과물에 담당자/참가자 정보가 요구되면 적절히 반영

**작업 지시사항 (task_instructions):**
- 값: {task_instructions or '명시되지 않음'}
- 역할: 기본적으로 수행해야 할 핵심 업무 내용과 지침 및 이전 결과물들에 대한 정리본
- 활용: Task의 주요 목표와 수행 방법의 기준점 (단, 피드백이 있으면 피드백에 의해 재해석됨)

**학습된 경험 (learned_knowledge):**
- 값: {learned_json}
- 역할: 에이전트별 관련 업무 경험과 노하우 제공
- 활용: 작업 품질 향상과 실수 방지를 위한 참고 자료
{('- 참고: 현재 수행할 작업을 더 완벽하게 수행하기 위한 디테일 보완에 활용' if has_learned else '- 참고: 학습 자료 부족 시에도 작업 중단 금지, 일반 지식으로 초안 작성')}

**피드백 (feedback_summary):**
- 값: {feedback_summary if has_feedback else '없음'}
- 역할: 이전 작업에 대한 수정 요구사항 (최고 우선순위)
- 활용: 모든 다른 지시사항보다 우선하여 작업 방향과 방법을 결정
{f'- 🔥 최우선: 피드백이 있으면 모든 작업은 이 피드백 내용에 따라 재정의됨' if has_feedback else ''}
- 처리방식: 피드백 동사(저장/수정/삭제/조회 등..)가 있으면 그에 맞게 작업지시사항 재해석
- 충돌해결: 피드백 vs 작업지시사항 충돌 시 → 무조건 피드백 우선 적용

=== 🎯 섹션 2: 작업 범위 및 방향 ===

**우선순위 체계:**
{first_priority_text}

{second_priority_text}

**작업 범위 제한 원칙:**
- 오로지지 작업 지시사항과 피드백만의 작업 방향을 결정
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

**데이터 완전성 확보 절차:**
1. 작업 지시사항에서 필요한 모든 데이터 파악
2. 부족한 데이터는 읽기전용 도구로 조회/검증/보완 (SELECT 쿼리, 검색 API, 메시징 API 등)
3. 모든 필요 데이터가 완전해진 후에만 쓰기 작업 수행
4. 데이터를 저장 및 수정할 경우, 주어진 값을 최대한 활용해서 다른 테이블의 값을 조회하는 등, 툴을 적극 활용해서 완전한 데이터를 생성 및 수정해야 함, 절대 누락되는 컬럼이나 데이터가 있어서는 안됩니다.
5. INSERT/UPDATE/DELETE(저장/수정/삭제) 수행 전, 반드시 human_asked(type="confirm")로 사용자 승인 획득(승인 없으면 절대 실행 금지)

=== 🎨 섹션 4: 콘텐츠 생성 시 가이드라인 ===

**폼 형식별 창의적 콘텐츠 생성 원칙:**

**슬라이드 형식 (presentation, slide 등):**
- **구조**: 제목 슬라이드 → 목차 → 본문 슬라이드들 → 결론/질의응답 슬라이드
- **분량**: 최소 10장 이상 구성(많을 수록 좋음)
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
  * 마크다운 내용을直接 출력하세요 (코드 블록 없이)
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
  * 보안 및 비밀번호, 개인정보 등 민감한 정보를 다루거나, 데이터 쓰기(INSERT/UPDATE/DELETE) 작업을 수행할 때는 human_asked 도구를 사용하여 질문 후 작업을 진행
  * 모든 도구룰 활용하고도, 정보가 없거나 부족할 경우, 배경 지식과 주어진 문맥 흐름을 기반으로 작를를
  * 도구에만 의존하지말고, 배경 지식과 주어진 문맥 흐름을 기반으로도 작성
  * 실제로 에이전트에게 주어진 모든 도구를 반드시 활용
  * 단! 메모리 관련 도구(mem0, memento)는 참고용으로, 이 결과가 없더라도 작업 중단 및 실패 금지
  * 폼 요구사항과 작업 맥락에 맞는 적절한 내용 생성
  * 여러 도구를 사용하여, 최대한 많은 정보를 수집
  (예 : DB 조회 관련 작업이면, supabase 툴을 사용하여 데이터를 조회)

=== 📤 프롬프트 생성 최종 지침 ===

**달성 목표 (작업지시사항 범위 내에서만):**
- 구체적으로 무엇을 완성해야 하는지
- 어떤 품질과 기준을 만족해야 하는지
- 특별히 주의해야 할 요구사항이 있는지
- 범위를 벗어난 작업은 절대 수행하지 않을 것
- 데이터 처리 시 완전성과 정확성을 보장할 것

**성공 기준:**
- 명시된 목표들이 전부 달성되어야 함 (일부만 달성하면 실패이며, 실패 시 반드시 사유를 디테일하게 명시)
{('- 피드백 내용을 100% 반영하여 처리' if has_feedback else '')}
- 요구된 형식으로 결과 제공
- 작업 범위 엄수 확인
"""

    def _build_expected_output_prompt(
        self,
        form_types: Optional[Dict],
        form_html: str,
    ) -> str:
        """결과물 프롬프트: form_types/form_html만 포함(원문 폼 섹션 + 선택형 규칙)."""
        
        has_form_types = bool(form_types)
        form_fields = None
        form_html_text = form_html or ""
        if isinstance(form_types, dict) and ("fields" in form_types or "html" in form_types):
            form_fields = form_types.get("fields")
            html = form_types.get("html")
            if html and isinstance(html, str) and html.strip():
                form_html_text = html
        else:
            form_fields = form_types if form_types else None
        is_multidata_mode = bool(form_html_text and 'is_multidata_mode="true"' in form_html_text)

        form_fields_json = json.dumps(form_fields, ensure_ascii=False, indent=2) if form_fields else '특별한 형식 제약 없음'
        multidata_notice = (
            '- 🚨 다중 데이터 모드: is_multidata_mode="true" 속성이 있으면 해당 필드는 배열 형태로 반환해야 함\n\n'
            if is_multidata_mode else ''
        )

        return (
            "다음 정보를 바탕으로 CrewAI Task expected_output 프롬프트를 생성하세요:\n\n"
            "=== 📋 폼 섹션 (expected_output 전용) ===\n\n"
            "섹션 1) 폼 형식(form_types)\n"
            f"- 값(필드 정의): {form_fields_json}\n"
            f"- 값(HTML): {form_html_text if form_html_text else '없음'}\n"
            "- 역할: 최종 결과물의 구조와 필드 정의, 선택형 항목(items) 제공\n"
            "- 활용: expected_output 구조 설계와 폼_데이터 키/값 결정에 사용\n"
            f"{('- 주의: key 값을 변경 없이 정확히 필드명으로 사용해야 함' if has_form_types else '')}\n"
            f"{multidata_notice}"
            "섹션 2) 선택형(radio/select) 처리\n"
            "- form_fields의 type이 'radio' 또는 'select'인 경우, 값 목록은 form_types의 HTML에서 추출\n"
            "- 예: <radio-field name=\"review_result\" items=\"[{{{'approve':'승인'}}},{{{'reject':'반려'}}}]\" ...>\n"
            "- 파싱 규칙:\n"
            "  1) HTML의 items 속성 문자열을 JSON으로 변환(단일따옴표 → 쌍따옴표) 후 파싱\n"
            "  2) 항목 객체의 key가 실제 저장 값, value는 한글 라벨\n"
            "  3) 최종 폼_데이터에는 key 값 사용 (예: 'approve' 또는 'reject')\n"
            "  4) radio/select 외 필드는 type에 맞는 적절한 텍스트/숫자 형식 사용\n"
            "  5) user-select-field는 담당자(Owner)의 식별자 사용 (id 우선, 없으면 email)\n\n"
            "섹션 3) expected_output 상세 작성 지침\n"
            "- 반드시 JSON 객체(object)로만 작성하세요. 문자열 포장/백틱/코드블록 금지\n"
            "- 아래 예시는 구조 예시이며, 값은 반드시 실제 작업 결과로 채워야 합니다\n\n"
            "[일반 모드 예시 (is_multidata_mode=\"false\" 또는 없음)]\n"
            "{\n  \"상태\": \"SUCCESS\" 또는 \"FAILED\",\n  \"수행한_작업\": \"읽기 좋은 자연어 텍스트로 수행 내역을 문단/불릿 형태로 서술\",\n  \"폼_데이터\": {\n    // 폼타입에 맞는 실제 데이터 (반드시 key 값을 필드명으로 사용)\n    form_key : 실제 데이터 값\n  }\n}\n\n"
            "[다중 데이터 모드 예시 (is_multidata_mode=\"true\")]\n"
            "{\n  \"상태\": \"SUCCESS\" 또는 \"FAILED\", \n  \"수행한_작업\": \"읽기 좋은 자연어 텍스트로 수행 내역을 문단/불릿 형태로 서술\",\n  \"폼_데이터\": {\n    // 일반 필드\n    normal_field : 실제 데이터 값,\n    // 다중 데이터 모드 필드는 배열 형태로 반환 (HTML의 실제 name 속성 사용 임의로 생성 금지)\n    real_multidata_field_name : [\n      {\n        \"property1\": \"실제 속성 값\",\n        \"property2\": \"실제 속성 값\",\n        \"property3\": \"실제 속성 값\"\n      },\n      {\n        \"property1\": \"실제 속성 값2\",\n        \"property2\": \"실제 속성 값2\",\n        \"property3\": \"실제 속성 값2\",\n      }\n    ]\n  }\n}\n\n"
            "- 위 구조는 예시입니다. 예시 값을 그대로 사용하지 말고 실제 결과로 대체하세요\n"
            "- 폼_데이터 키 규칙: 폼타입의 'key' 값을 변경 없이 원본 그대로 정확히 필드명으로 사용\n"
            "- 폼_데이터에는 요구된 폼타입 필드들이 정확히 포함되어야 함\n"
            "- '수행한_작업'은 가독성 좋은 자연어 한 문자열(불릿/번호 허용)로 작성\n"
            "- 작업지시사항에서 추출한 모든 원자 작업을 누락 없이 서술(누락 시 FAILED 간주)\n"
            "- 다중 데이터 모드: is_multidata_mode=\"true\" 필드는 반드시 배열 형태로 반환(HTML의 실제 name 사용)\n\n"
            "섹션 4) 선택형(radio/select) 값 결정 지침\n"
            "- form_types에 HTML이 제공되면 해당 필드의 items를 HTML에서 파싱하여 실제 선택 가능한 값 목록 결정\n"
            "- items 예시: [{\"approve\":\"승인\"},{\"reject\":\"반려\"}] → 폼_데이터 값은 \"approve\" 또는 \"reject\" 중 하나여야 함\n\n"
            "섹션 5) 다중 데이터 모드 필드 처리 지침\n"
            "- HTML에서 is_multidata_mode=\"true\" 속성이 있는 필드는 반드시 배열 형태로 반환\n"
            "- 배열 내 각 객체는 해당 섹션의 모든 필드를 포함해야 함\n"
            "- 다중 데이터 모드 필드의 각 배열 요소는 독립적인 완전한 데이터 객체여야 함\n"
            "- 필드명은 HTML의 name 속성을 그대로 사용하고, 해당 섹션의 모든 하위 필드들을 포함하여 배열 요소로 구성\n"
            "- 🚨 중요: multidata_field는 실제 HTML의 name 속성을 활용하세요. 임의로 생성하지 말고 HTML을 그대로 적극 활용하여 구조를 구성\n\n"
            "섹션 6) 응답 형식\n"
            "- 오직 expected_output 객체(JSON)만 응답하세요. 다른 텍스트 포함 금지\n"
            "예: {\n  \"상태\": \"SUCCESS\" 또는 \"FAILED\",\n  \"수행한_작업\": \"읽기 좋은 자연어 텍스트\",\n  \"폼_데이터\": { /* 폼 필드 키/값 */ }\n}\n"
            "- 문자열로 감싸지 말고, 백틱을 사용하지 마세요. 순수 JSON 객체만 반환하세요."
        )

    def _build_system_prompt_description(self) -> str:
        """description 전용 시스템 프롬프트 생성"""
        return (
            "당신은 CrewAI Task description을 작성하는 전문가입니다.\n\n"
            "역할: 주어진 컨텍스트 정보를 바탕으로 에이전트가 수행할 구체적인 작업 지시(description)를 생성합니다.\n"
            "응답 형식: 설명 텍스트 한 문단으로만 응답하세요. 백틱/코드블록/JSON 포장 금지."
        )

    def _build_system_prompt_expected_output(self) -> str:
        """expected_output 전용 시스템 프롬프트 생성"""
        return (
            "당신은 CrewAI Task expected_output을 작성하는 전문가입니다.\n\n"
            "역할: 주어진 폼 정보(form_types/form_html)만을 바탕으로 결과 형식(expected_output)을 생성합니다.\n"
            "응답 형식: 오직 JSON 객체로만 응답하세요. 백틱/코드블록/문자열 포장 금지."
        )
