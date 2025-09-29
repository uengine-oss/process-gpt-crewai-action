# CrewAI Action 서버

CrewAI를 활용한 자연어 처리 액션 서버입니다. 사용자의 요청을 받아 CrewAI 에이전트들이 협업하여 작업을 수행하고 결과를 반환합니다.

## 📊 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                    CrewAI Action 서버 흐름도                      │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Process-GPT   │───▶│ CrewAI Action    │───▶│   CrewAI        │
│   Agent SDK     │    │   Server         │    │   Factory       │
│   (폴링)        │    │                  │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │                       ▼
         │                       │              ┌─────────────────┐
         │                       │              │  Dynamic       │
         │                       │              │  Prompt        │
         │                       │              │  Generator     │
         │                       │              └─────────────────┘
         │                       │                       │
         │                       ▼                       │
         │              ┌──────────────────┐             │
         │              │ CrewAI Action    │◀────────────┘
         │              │ Executor         │
         │              │                  │
         │              └──────────────────┘
         │                       │
         │                       ▼
         │              ┌──────────────────┐
         └──────────────▶│   Event Queue    │
                        │   (결과 반환)     │
                        └──────────────────┘
```

## 📁 파일 구조 및 역할

### 🚀 메인 실행 파일들

#### `crewai_action_server.py` - 서버 엔트리포인트
- **역할**: 메인 서버 실행 파일
- **기능**: 
  - ProcessGPT Agent SDK를 사용한 폴링 기반 서버
  - 5초 간격으로 새 작업 확인
  - CrewAI Action Executor를 생성하고 연결
- **실행**: `python crewai_action_server.py`

#### `crewai_action_executor.py` - 작업 실행기
- **역할**: 실제 CrewAI 작업을 수행하는 핵심 컴포넌트
- **기능**:
  - Context에서 사용자 요청과 메타데이터 추출
  - CrewAI 크루 생성 및 실행
  - 결과를 이벤트 큐로 반환
  - 에러 처리 및 로깅

### 🏭 크루 관리 파일들

#### `crew_factory.py` - 크루 생성 팩토리
- **역할**: CrewAI 에이전트와 크루를 동적으로 생성
- **주요 클래스/함수**:
  - `AgentWithProfile`: 프로필 정보를 가진 Agent 서브클래스
  - `create_dynamic_agent()`: 에이전트 정보로 Agent 객체 생성
  - `create_user_task()`: 사용자 요청 기반 Task 생성
  - `create_crew()`: 최종 크루 조립 및 반환

#### `prompt_generator.py` - 동적 프롬프트 생성기
- **역할**: LLM을 활용한 동적 Task 프롬프트 생성
- **주요 기능**:
  - `DynamicPromptGenerator`: LLM 기반 프롬프트 최적화
  - 학습된 지식(Mem0) 통합
  - 피드백 우선순위 처리
  - 폼 형식에 맞는 결과 구조 생성

#### `utils.py` - 유틸리티 함수들
- **역할**: CrewAI 결과 처리 및 변환
- **주요 기능**:
  - `convert_crew_output()`: CrewAI 출력을 표준 JSON 형식으로 변환
  - 코드 블록 제거 및 JSON 파싱
  - 폼 데이터 정규화

## 🔄 실행 흐름 상세

### 1단계: 서버 시작
```bash
python crewai_action_server.py
```
- ProcessGPT Agent SDK 폴링 서버 시작
- 5초마다 새 작업 확인

### 2단계: 작업 수신 및 파싱
```python
# crewai_action_executor.py에서
query = context.get_user_input()           # 사용자 요청
context_data = context.get_context_data()  # 메타데이터
```

### 3단계: 에이전트 및 크루 생성
```python
# crew_factory.py에서
agents = []  # 에이전트들 생성
for agent_info in agent_info_list:
    agent = create_dynamic_agent(agent_info, tools)
    agents.append(agent)

crew = Crew(agents=agents, tasks=[task], process=Process.sequential)
```

### 4단계: 동적 프롬프트 생성
```python
# prompt_generator.py에서
prompt_generator = DynamicPromptGenerator(llm=agent._llm_raw)
description, expected_output = prompt_generator.generate_task_prompt(
    task_instructions=query,
    agent_info=agent_info,
    form_types=form_types,
    # ... 기타 파라미터들
)
```

### 5단계: CrewAI 실행
```python
result = crew.kickoff()  # 실제 CrewAI 실행
```

### 6단계: 결과 처리 및 반환
```python
# utils.py에서
pure_form_data, wrapped_result, original_wo_form = convert_crew_output(result, form_id)

# 이벤트 큐로 결과 전송
event_queue.enqueue_event(TaskStatusUpdateEvent(...))
event_queue.enqueue_event(TaskArtifactUpdateEvent(...))
```

## 🛠 설치 및 실행

### 1. 환경 설정
```bash
# 가상환경 생성
uv venv

# 의존성 설치
uv pip install -r requirements.txt

# 가상환경 활성화 (Windows)
source .venv/Scripts/activate

# 가상환경 비활성화
deactivate
```

### 2. 환경변수 설정
`.env` 파일에 필요한 환경변수 설정:
```bash
# OpenAI API 설정
OPENAI_API_KEY=your_openai_api_key_here

# LANGSMITH 설정 (선택사항)
LANGSMITH_API_KEY=your_langsmith_api_key_here
LANGSMITH_PROJECT=crewai-process-gpt
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

### 3. 서버 실행
```bash
python crewai_action_server.py
```

### 4. 로그 확인
```bash
# 실시간 로그 확인
kubectl logs -f crewai-action-deployment-<pod-id>

# 로그 파일로 출력
python crewai_action_server.py > output.log 2>&1
```

## 🔧 주요 특징

### ✅ 장점
- **동적 에이전트 생성**: 런타임에 에이전트 구성 변경 가능
- **지능형 프롬프트**: LLM 기반 동적 프롬프트 최적화
- **학습 지식 통합**: Mem0를 통한 과거 경험 활용
- **피드백 우선 처리**: 사용자 피드백을 최우선으로 반영
- **견고한 에러 처리**: 재시도 로직과 상세한 로깅

### 🎯 핵심 기능
- **폴링 기반 서버**: ProcessGPT Agent SDK와 연동
- **멀티 에이전트 협업**: 여러 AI 에이전트의 협업 작업
- **폼 데이터 처리**: 구조화된 결과 데이터 생성
- **이벤트 기반 통신**: 비동기 결과 전달

## 📝 개발 참고사항

### 에러 처리
- 모든 주요 함수에서 예외 발생 시 상세 로깅
- CrewAI 실행 실패 시 원인 분석 정보 제공
- 재시도 로직으로 일시적 오류 대응

### 로깅
- 구조화된 로깅으로 디버깅 용이
- 각 단계별 진행 상황 추적
- 성능 메트릭 수집 (실행 시간, 토큰 사용량 등)

### 확장성
- 새로운 도구 추가 시 SafeToolLoader 활용
- 에이전트 프로필 확장 가능
- 다양한 LLM 프로바이더 지원