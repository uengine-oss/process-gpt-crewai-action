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
        current_activity_name: str = ""
    ) -> tuple[str, str]:
        """모든 정보를 조합하여 최적화된 task 프롬프트 생성"""
        
        # 1. 관련 학습 내용 수집
        learned_knowledge = self._collect_learned_knowledge(agent_info, task_instructions, feedback_summary)
        
        # 2. 컨텍스트 조합
        context = self._build_context(
            task_instructions, agent_info, form_types,
            output_summary, feedback_summary, current_activity_name, learned_knowledge
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
        learned_knowledge: Dict[str, str]
    ) -> str:
        """에이전트가 실수 없이 정확히 처리할 수 있는 명확한 프롬프트 생성"""
        
        # 피드백과 학습 경험 존재 여부 확인
        has_feedback = feedback_summary and feedback_summary.strip() and feedback_summary.strip() != '없음'
        has_learned_knowledge = any(learned_knowledge.values())
        
        # 에이전트 정보와 학습된 경험을 통째로 사용
        agent_info_json = json.dumps(agent_info, ensure_ascii=False, indent=2) if agent_info else '정보 없음'
        learned_knowledge_json = json.dumps(learned_knowledge, ensure_ascii=False, indent=2) if has_learned_knowledge else '관련 경험 없음'
        
        return f"""
다음 정보를 바탕으로 CrewAI Task 프롬프트를 생성하세요:

=== 작업 상황 ===
활동명: {current_activity_name or '일반 작업'}
팀 구성: {agent_info_json}

=== 작업 요구사항 ===

**피드백 (수정 요구사항) - 최우선 처리 필수:**
{feedback_summary if has_feedback else '없음'}
{f'''>> 🚨 중요: 이전 작업지시사항대로 했지만 결과가 만족스럽지 않아서 나온 수정 요구사항입니다!
>> 📋 피드백 처리 원칙:
   - 기존 방식을 완전히 버리고 이 피드백 내용대로만 수정하여 수행
   - 피드백에서 요구하는 변경사항을 100% 반영해야 함
   - 피드백과 작업지시사항이 충돌하면 피드백을 우선적으로 따름
   - 피드백에서 명시한 방법론, 절차, 기준을 정확히 적용
   - 피드백 내용을 임의로 해석하거나 변형하지 않고 그대로 따름

>> 🔄 피드백 동사별 작업지시사항 재해석:
   - 피드백에서 "저장하라" → 작업지시사항을 INSERT 작업으로 재해석, 기존 데이터 수정 금지
   - 피드백에서 "수정하라" → 작업지시사항을 UPDATE 작업으로 재해석, 명시된 레코드·필드만 변경
   - 피드백에서 "삭제하라" → 작업지시사항을 DELETE 작업으로 재해석, 명시된 대상만 삭제
   - 피드백에서 "조회하라" → 작업지시사항을 SELECT 작업으로 재해석, 쓰기 작업 금지
   - 피드백 동사 vs 작업지시사항 동사 충돌 시 → 무조건 피드백 동사 우선 적용''' if has_feedback else ''}

**작업 지시사항 (기본 수행해야 할 일):**
{task_instructions or '명시되지 않음'}

**이전 작업 결과 (핵심 정보 - 절대 생략 금지):**
{output_summary or '없음'}
{f'>> 중요: 이전 작업 결과물에는 현재 작업을 수행하는데 필요한 모든 정보들이 담겨있습니다. 절대로 생략하지 말고 참고하여 작업하세요!' if output_summary and output_summary.strip() and output_summary.strip() != '없음' else ''}

**학습된 경험 (참고 정보):**
{learned_knowledge_json}
{f'>> 참고: 이 경험들은 작업지시사항을 더 디테일하고 정확하게 수행하기 위한 노하우입니다. 작업지시사항 자체는 그대로 하되, 이 경험을 참고해서 더 완벽하게 처리하세요.' if has_learned_knowledge else ''}

**폼 형식:**
{json.dumps(form_types, ensure_ascii=False, indent=2) if form_types else '특별한 형식 제약 없음'}

=== Task 실행 원칙 ===

**1. 작업 범위 엄수 (후속작업 금지)**
{f'''- 🔥 피드백이 있는 경우: 
  * 피드백 요구사항을 최우선으로 하여 작업 수행
  * 피드백에서 명시한 새로운 방법/절차/기준으로 완전 전환
  * 기존 작업지시사항은 피드백에 의해 수정된 범위에서만 참고
  * 피드백 vs 작업지시사항 충돌 시 → 피드백 100% 우선''' if has_feedback else '- 피드백이 없는 경우: 작업지시사항에 명시된 내용만 정확히 수행'}
- 명시되지 않은 연관작업/후속작업은 절대 수행 금지
- 예시: "휴가 정보 저장" 지시 → 오직 휴가정보만 저장, 휴가 잔여일수 수정/알림발송/승인처리 등은 지시에 없으면 금지
- 예시: "주문 정보 저장" 지시 → 오직 주문정보만 저장, 재고감소/포인트적립/알림발송 등은 지시에 없으면 금지
- 판단이 모호한 경우: human_asked 도구로 "이 작업 범위가 맞는지" 사용자에게 확인 후 진행

**2. 데이터 저장/수정 시 정확성 및 완전성 보장**
- 타겟 명확화: 저장/수정 대상(테이블, 레코드, 필드)을 정확히 파악하고, 모호하면 human_asked로 확인
- 데이터 완전성 확보 절차:
  ① 이전 작업 결과물에서 사용 가능한 데이터 최대한 활용
  ② 부족한 데이터는 읽기전용 도구로 조회/검증/보완 (SELECT 쿼리, 검색 API, 메시징 API 등)
  ③ 모든 필요 데이터가 완전해진 후에만 쓰기 작업 수행
- 동사별 작업 범위 엄격 제한:
  * **"저장/등록/추가"** = INSERT만 (신규 데이터 추가)
    - 기존 데이터 변경 절대 금지
    - 오직 새로운 레코드 생성만 수행
    - 예: "휴가정보 저장" → 새 휴가 레코드만 추가, 기존 휴가잔여일수 등 수정 금지
  * **"수정/변경/업데이트"** = 명시된 레코드의 명시된 필드만 UPDATE
    - 명시되지 않은 레코드나 필드는 절대 변경 금지
    - 정확한 WHERE 조건으로 타겟 레코드 특정 필수
    - 예: "사용자 이름 수정" → 해당 사용자의 이름 필드만 변경, 다른 필드/사용자 변경 금지
  * **"삭제/제거"** = 명시된 대상만 DELETE
    - 명시되지 않은 관련 데이터는 절대 삭제 금지
    - 정확한 WHERE 조건으로 타겟 특정 필수
    - 예: "특정 주문 삭제" → 해당 주문만 삭제, 관련 결제/배송정보 등 삭제 금지
  * **범위 위반 시**: human_asked로 "이 범위가 맞는지" 확인 후 진행
- 예시: 고객정보 저장 시 → 고객명으로 기존 데이터 조회, 부서코드 테이블 참조, 완전한 데이터 구성 후 저장

**3. 도구 활용 및 보안 원칙**
- mem0/memento: 참고용으로만 사용, 실제 작업은 주어진 도구 활용
- 실제 작업 도구: DB 쿼리, API 호출, MCP 도구, Slack 등
- 보안/민감 작업: 반드시 human_asked로 사용자 승인 후 수행
- 실패 시 대응: 문제 분석 → 해결방안 모색 → 대안 재시도 → 완료까지 포기하지 않음

=== 프롬프트 생성 지침 ===

**작업 처리 우선순위:**
{f'''🔥 1. 피드백 절대 우선: 
   - 피드백 요구사항이 모든 것보다 우선 (작업지시사항, 학습경험 등 모두 피드백에 종속)
   - 피드백에서 요구한 변경사항을 정확히 이해하고 100% 적용
   - 기존 방식이나 관례를 버리고 피드백이 제시한 새로운 방식으로 완전 전환
   - 피드백 내용과 다른 어떤 지시가 충돌해도 피드백을 최우선으로 따름
   - 🔄 피드백에 동사가 있으면 그 동사에 맞게 작업지시사항 재해석:
     * 피드백 "저장" + 작업지시사항 "수정" → 저장(INSERT) 작업으로 처리
     * 피드백 "수정" + 작업지시사항 "저장" → 수정(UPDATE) 작업으로 처리
     * 피드백 동사가 작업지시사항의 실제 수행 방법을 결정''' if has_feedback else '1. 작업지시사항 그대로 수행'}{f'''
2. 학습된 경험 활용: 피드백 범위 내에서 경험을 참고하여 더 완벽하게 처리''' if has_learned_knowledge and has_feedback else f'''
2. 학습된 경험 활용: 작업지시사항은 그대로 하되, 경험을 참고해서 더 디테일하게 완벽하게 처리''' if has_learned_knowledge else ''}

**달성 목표:**
- 구체적으로 무엇을 완성해야 하는지 (작업지시사항 범위 내에서만)
- 어떤 품질과 기준을 만족해야 하는지
- 특별히 주의해야 할 요구사항이 있는지
- 범위를 벗어난 작업은 절대 수행하지 않을 것
- 데이터 처리 시 완전성과 정확성을 보장할 것

**성공 기준:**
- 명시된 목표들이 전부 달성되어야 함 (일부만 달성하면 실패){f'''
- 피드백 내용을 100% 반영하여 처리''' if has_feedback else ''}
- 요구된 형식으로 결과 제공

JSON 형식으로 응답: {{"description": "명확한 작업 지시와 실행 방법", "expected_output": "구체적인 결과 형식과 성공 기준"}}
"""
    
    def _generate_optimized_prompt(self, context: str) -> tuple[str, str]:
        """LLM 기반 프롬프트 생성"""
        
        system_prompt = """당신은 CrewAI Task description을 작성하는 전문가입니다.

**응답 형식**: 반드시 JSON 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요.

**Task 작성 가이드라인:**
- description: "당신의 임무는..." 형태로 시작하여 구체적 작업 지시 작성
- expected_output: 결과 형식과 성공 기준을 명확히 정의

**피드백 우선순위:**
- 피드백이 있으면: 피드백 요구사항을 최우선으로 하여 처리
- 피드백이 없으면: 작업지시사항 그대로 수행

**핵심 실행 원칙 (description에 반드시 포함):**
- 작업 범위 엄수: 명시된 작업만 수행, 비명시 후속작업 절대 금지
- 데이터 처리 원칙: 이전결과물 활용 → 부족분 조회/검증 → 완전한 데이터로 쓰기
- 동사별 엄격 제한: 저장=INSERT만, 수정=명시된 레코드·필드만, 삭제=명시된 대상만
- 모호성 대응: 불확실하면 human_asked로 사용자 확인 후 진행
- 도구 활용: DB/API/MCP/Slack 등 주어진 도구 적극 활용 (mem0는 참고용)
- 실패 대응: 오류 시 분석·해결·재시도로 반드시 완료

**expected_output 상세 작성 지침:**
- 다음 예시 구조를 반드시 준수하되, 값은 실제 작업 결과로 채워야 한다고 명시:
  ```json
  {
    "상태": "SUCCESS" 또는 "FAILED",
    "수행한_작업": "실제로 수행한 작업들의 구체적인 내용과 수치 및 결과",
    "폼_데이터": {
      // 폼타입에 맞는 실제 데이터 (반드시 key 값을 필드명으로 사용)
      form_key : 실제 데이터 값
    }
  }
  ```
- "아래 구조는 예시이며, 값들은 실제 작업 결과로 대체해야 합니다" 반드시 포함
- 폼_데이터 키 규칙: 폼타입의 'key' 값을 정확히 필드명으로 사용해야 함
- 폼_데이터에는 요구된 폼타입 필드들이 정확히 포함되어야 함을 명시
- 폼_데이터 값이 부족하거나 불확실하면 필요한 데이터를 도구로 조회/생성/검증하여 모두 채우도록 명시
- '수행한_작업'에는 조회/검증 과정과 사용한 도구, 수행한 쓰기 작업의 종류/대상 범위, 명시된 작업만 수행하고 비명시 후속작업을 하지 않았음을 확인하는 문구 포함
- "상태", "수행한_작업", "폼_데이터" 필드명은 변경하지 말고 그대로 사용
- 예시 값을 그대로 복사하지 말고 실제 결과로 채울 것을 강조

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
            # 기본 프롬프트 반환
            return (
                "사용자 요청을 분석하고 팀 에이전트들과 협업하여 처리하세요. 피드백이 있으면 최우선 처리하고, 실제 도구를 사용하여 정확한 결과를 도출하세요.",
                '{"상태": "SUCCESS/FAILED", "수행한_작업": "구체적 내용", "폼_데이터": {}} JSON 형식으로 결과를 제공하세요.'
            )