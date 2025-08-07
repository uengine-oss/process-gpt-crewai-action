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

=== 작업 상황 분석 ===
활동명: {current_activity_name or '일반 작업'}
팀 구성 (에이전트 정보):
{agent_info_json}

=== 작업 요구사항 분석 ===

🚨 **피드백 (수정 요구사항)**:
{feedback_summary if has_feedback else '없음'}
{f'📌 중요: 이전에 작업지시사항대로 했지만 결과가 만족스럽지 않아서 나온 수정 요구사항입니다. 기존 방식을 버리고 이 피드백대로 수정해야 합니다!' if has_feedback else ''}

📋 **작업 지시사항 (기본 수행해야 할 일)**:
{task_instructions or '명시되지 않음'}

📊 **이전 작업 결과 (작업에 필요한 핵심 정보 - 절대 생략 금지)**:
{output_summary or '없음'}
{f'🚨 중요: 이전 작업 결과물에는 현재 작업을 수행하는데 필요한 모든 정보들이 담겨있습니다. 절대로 생략하지 말고 참고하여 작업하세요!' if output_summary and output_summary.strip() and output_summary.strip() != '없음' else ''}

💡 **학습된 경험 (더 잘하기 위한 참고 정보)**:
{learned_knowledge_json}
{f'📝 참고: 이 경험들은 작업지시사항을 더 디테일하고 정확하게 수행하기 위한 노하우입니다. 작업지시사항 자체는 그대로 하되, 이 경험을 참고해서 더 완벽하게 처리하세요.' if has_learned_knowledge else ''}

📄 **결과 형식**:
{json.dumps(form_types, ensure_ascii=False, indent=2) if form_types else '특별한 형식 제약 없음'}

=== 프롬프트 생성 지침 ===

**에이전트가 정확히 이해하도록 다음 구조로 지시하세요:**

🎯 **작업 처리 방식**:
{f'- 피드백 최우선: 작업지시사항을 피드백 내용에 맞게 수정하여 수행' if has_feedback else '- 작업지시사항 그대로 수행'}
{f'- 학습된 경험 활용: 작업지시사항은 그대로 하되, 경험을 참고해서 더 디테일하게 완벽하게 처리' if has_learned_knowledge else ''}
- 🔍 **mem0/memento 정보**: 참고용 정보로만 활용. 실제 작업은 다른 도구들(데이터베이스, API 등)을 사용하여 수행
- ⛔ **작업 범위 엄격 준수**: 작업지시사항에 명시된 작업만 수행. 추가/후속 작업 절대 금지

🎯 **달성해야 할 목표**:
- 구체적으로 무엇을 완성해야 하는지 (작업지시사항 범위 내에서만)
- 어떤 품질과 기준을 만족해야 하는지  
- 특별히 주의해야 할 요구사항이 있는지
- 📊 **이전 작업 결과 활용 필수**: 이전 결과물의 정보들을 빠뜨리지 말고 모두 활용할 것
- 🔄 **실패 시 대응**: 작업 중 오류나 실패가 발생하면 넘어가지 말고 문제를 분석하여 해결하거나 다른 방법으로 재시도할 것
- ⚠️ 명시되지 않은 연관 작업이나 후속 작업은 절대 수행하지 말 것

✅ **성공 기준과 결과 형식**:
- 최종 결과물이 만족해야 할 조건
- 요구된 형식으로 결과 제공

{f'⚠️ 피드백 반영 필수: 이전 방식으로 하면 안 되고, 반드시 피드백 내용대로 수정해서 처리해야 함' if has_feedback else ''}
{f'💡 경험 활용 권장: 학습된 경험을 참고해서 작업지시사항을 더 완벽하게 수행' if has_learned_knowledge else ''}
📊 **이전 결과물 완전 활용**: 이전 작업 결과에 담긴 모든 정보들을 빠뜨리지 말고 활용하여 작업할 것
🔄 **실패 시 포기 금지**: 작업 중 오류나 실패가 발생하면 넘어가지 말고, 문제를 분석하고 해결하거나 다른 방법으로 재시도하여 반드시 완료할 것
🔍 **도구 활용 가이드**: mem0/memento로 얻은 정보는 참고용으로만 활용하고, 실제 작업은 다른 도구들(데이터베이스, API, 파일 처리 등)을 사용하여 수행할 것
🚨 **범위 제한 엄수**: 작업지시사항에 없는 추가 작업, 후속 작업, 연관 작업은 절대 수행하지 말 것

JSON 형식으로 응답: {{"description": "명확한 작업 지시와 실행 방법", "expected_output": "구체적인 결과 형식과 성공 기준"}}
"""
    
    def _generate_optimized_prompt(self, context: str) -> tuple[str, str]:
        """LLM 기반 프롬프트 생성"""
        
        system_prompt = """당신은 CrewAI Task description을 작성하는 전문가입니다.

🚨 중요: 반드시 JSON 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요.

에이전트가 구체적으로 무엇을 해야 하는지 Task 형식으로 작성하세요.

**피드백 처리:**
- 피드백이 있으면: 기존 방식 수정, 피드백 요구사항대로 처리
- 피드백이 없으면: 작업지시사항 그대로 수행

**description 작성 원칙:**
- "당신의 임무는..." 형태로 시작
- 🚨 **작업 범위 엄격 준수**: 작업지시사항에 명시된 작업만 정확히 수행. 추가 작업 절대 금지
- 🔍 **도구 활용 방법**: mem0/memento 정보는 참고용으로만 활용하고, 실제 작업은 다른 도구들(데이터베이스, API 등)을 사용하여 수행할 것을 명시
- 📊 **이전 결과물 활용 필수**: 이전 작업 결과에 담긴 정보들을 절대 생략하지 말고 모두 활용하여 작업할 것을 명시
- 🔄 **실패 처리 방침**: 작업 중 오류가 발생하면 포기하지 말고 문제를 분석하여 해결하거나 대안 방법으로 재시도할 것을 명시
- 피드백의 맥락을 정확히 파악하여 적절한 작업 동사 선택 (저장/수정/보완/조회 등)
- 피드백이 수정을 요구하면 "수정", "보완", "업데이트" 등으로 표현
- 반드시 피드백을 우선시로 하여, 하나의 완전한 작업으로 작성
- 학습된 경험은 작업지시사항의 품질 향상용으로만 활용. 범위 확장 금지
- 메타적 언급("피드백에 따라", "이전 방식은") 없이 구체적인 작업 내용과 품질 기준 명시
- ⛔ 명시되지 않은 후속 작업이나 연관 작업은 절대 포함하지 말 것

**expected_output 작성:**
- 다음 예시 구조를 반드시 준수하되, 값은 실제 작업 결과로 채워야 한다고 명시:
  ```json
  {
    "상태": "SUCCESS" 또는 "FAILED",
    "수행한_작업": "실제로 수행한 작업들의 구체적인 내용과 수치 및 결과 및 데이터",
    "폼_데이터": {
      // 폼타입에 맞는 실제 데이터 (반드시 key 값을 필드명으로 사용)
      form_key : 실제 데이터 값
    }
  }
  ```
- "아래 구조는 예시이며, 값들은 실제 작업 결과로 대체해야 합니다" 반드시 포함
- 🚨 **폼_데이터 키 규칙**: 폼타입의 'key' 값을 정확히 필드명으로 사용해야 함 (text 아님)
- 폼_데이터에는 요구된 폼타입 필드들이 정확히 포함되어야 함을 명시
- "상태", "수행한_작업", "폼_데이터" 필드명은 변경하지 말고 그대로 사용
- 예시 값을 그대로 복사하지 말고 실제 결과로 채울 것을 강조

🚨🚨🚨 필수: 오직 이 JSON 형식으로만 응답하세요:
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