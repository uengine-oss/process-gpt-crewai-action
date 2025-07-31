# My Supabase Service with CrewAI

## 개요
CrewAI를 활용해 자연어 요구사항을 Supabase에 저장하고 결과를 검증하는 서비스입니다.

## 설치
1. `.env` 파일에 환경변수 설정
2. `pip install -r requirements.txt`

## 실행
```bash
python main.py > output.log 2>&1
python test_crew_hardcoded.py > output.log 2>&1
set PYTHONIOENCODING=utf-8 && python test_crew_hardcoded.py > output.log 2>&1
export PYTHONIOENCODING=utf-8
python test_crew_hardcoded.py > output.log 2>&1
``` 


kubectl get pods -l app=crewai-action
kubectl logs crewai-action-deployment-5b8489dc96-rgmlc
kubectl logs -f crewai-deep-research-deployment-b85b89599-gvvh9 > output.log 2>&1