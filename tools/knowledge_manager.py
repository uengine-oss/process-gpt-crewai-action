import os
from typing import Optional, List, Type
from pydantic import BaseModel, Field, PrivateAttr
from crewai.tools import BaseTool
from dotenv import load_dotenv
from mem0 import Memory
import requests
from utils.logger import log, handle_error

# ============================================================================
# 설정 및 초기화
# ============================================================================

load_dotenv()

# 데이터베이스 연결 정보
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

if not all([DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME]):
    raise ValueError("❌ DB 연결 환경 변수가 설정되지 않았습니다. .env 파일을 확인해주세요.")

CONNECTION_STRING = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# ============================================================================
# 스키마 정의
# ============================================================================

class KnowledgeQuerySchema(BaseModel):
    query: str = Field(..., description="검색할 지식 쿼리")

# ============================================================================
# 지식 검색 도구
# ============================================================================

class Mem0Tool(BaseTool):
    """Supabase 기반 mem0 지식 검색 도구 - 에이전트별"""
    name: str = "mem0"
    description: str = "에이전트별 개인 지식을 검색하여 전체 결과를 반환합니다."
    args_schema: Type[KnowledgeQuerySchema] = KnowledgeQuerySchema
    _tenant_id: Optional[str] = PrivateAttr()
    _user_id: Optional[str] = PrivateAttr()
    _namespace: Optional[str] = PrivateAttr()
    _memory: Memory = PrivateAttr()

    def __init__(self, tenant_id: str = None, user_id: str = None, **kwargs):
        super().__init__(**kwargs)
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._namespace = user_id
        self._memory = self._initialize_memory()
        log(f"Mem0Tool 초기화: user_id={self._user_id}, namespace={self._namespace}")

    def _initialize_memory(self) -> Memory:
        """Memory 인스턴스 초기화 - 에이전트별"""
        config = {
            "vector_store": {
                "provider": "supabase",
                "config": {
                    "connection_string": CONNECTION_STRING,
                    "collection_name": "memories",
                    "index_method": "hnsw",
                    "index_measure": "cosine_distance"
                }
            }
        }
        return Memory.from_config(config_dict=config)

    def _run(self, query: str) -> str:
        """지식 검색 및 결과 반환 - 에이전트별 메모리에서"""
        if not query:
            return "검색할 쿼리를 입력해주세요."
        
        try:
            # 검색 실행
            log(f"에이전트별 검색 시작: user_id={self._user_id}, query='{query}'")
            results = self._memory.search(query, user_id=self._user_id)
            hits = results.get("results", [])
            
            # hybrid 필터링 적용: threshold=0.6, 최소 5개 보장
            THRESHOLD = 0.5
            MIN_RESULTS = 5
            # 1) 유사도 내림차순 정렬
            hits_sorted = sorted(hits, key=lambda x: x.get("score", 0), reverse=True)
            # 2) Threshold 이상 항목 필터
            filtered_hits = [h for h in hits_sorted if h.get("score", 0) >= THRESHOLD]
            # 3) 최소 개수 보장
            if len(filtered_hits) < MIN_RESULTS:
                filtered_hits = hits_sorted[:MIN_RESULTS]
            hits = filtered_hits

            log(f"에이전트별 검색 결과: {len(hits)}개 항목 발견")
            
            # 결과 처리
            if not hits:
                return f"'{query}'에 대한 개인 지식이 없습니다."
            
            return self._format_results(hits)
            
        except Exception as e:
            handle_error("에이전트별지식검색", e)
            return f"에이전트별지식검색 실패: {e}"

    def _format_results(self, hits: List[dict]) -> str:
        """검색 결과 포맷팅"""
        items = []
        for idx, hit in enumerate(hits, start=1):
            memory_text = hit.get("memory", "")
            score = hit.get("score", 0)
            items.append(f"개인지식 {idx} (관련도: {score:.2f})\n{memory_text}")
        
        return "\n\n".join(items)

# ============================================================================
# 사내 문서 검색 (memento) 도구
# ============================================================================

class MementoQuerySchema(BaseModel):
    query: str = Field(..., description="검색 키워드 또는 질문")

class MementoTool(BaseTool):
    """사내 문서 검색을 수행하는 도구"""
    name: str = "memento"
    description: str = "사내 문서 검색을 위한 도구"
    args_schema: Type[MementoQuerySchema] = MementoQuerySchema
    _tenant_id: str = PrivateAttr()

    def __init__(self, tenant_id: str = "localhost", **kwargs):
        super().__init__(**kwargs)
        self._tenant_id = tenant_id
        log(f"MementoTool 초기화: tenant_id={self._tenant_id}")

    def _run(self, query: str) -> str:
        try:
            log(f"Memento 문서 검색 시작: tenant_id='{self._tenant_id}', query='{query}'")
            response = requests.post(
                "http://memento.process-gpt.io/retrieve",
                # "http://localhost:8005/retrieve",
                json={"query": query, "options": {"tenant_id": self._tenant_id}}
            )
            if response.status_code != 200:
                return f"API 오류: {response.status_code}"
            data = response.json()
            if not data.get("response"):
                return f"테넌트 '{self._tenant_id}'에서 '{query}' 검색 결과가 없습니다."
            results = []
            docs = data.get("response", [])
            log(f"Memento 검색 결과 개수: {len(docs)}")
            for doc in docs:
                fname = doc.get('metadata', {}).get('file_name', 'unknown')
                idx = doc.get('metadata', {}).get('chunk_index', 'unknown')
                content = doc.get('page_content', '')
                results.append(f"📄 파일: {fname} (청크 #{idx})\n내용: {content}\n---")
            return f"테넌트 '{self._tenant_id}'에서 '{query}' 검색 결과:\n\n" + "\n".join(results)
        except Exception as e:
            handle_error("Memento문서검색", e)
            return f"검색 중 오류 발생: {e}"
