import os
import uuid
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import logging

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
logger = logging.getLogger(__name__)

class EventLogger:
    """Supabase 이벤트 로깅 시스템"""
    
    def __init__(self):
        """이벤트 로거 초기화"""
        self.supabase_client = self._init_supabase()
        logger.info("🎯 Event Logger 초기화 완료")
        print(f"   - Supabase: {'✅' if self.supabase_client else '❌'}")

    def _init_supabase(self) -> Optional[Client]:
        """Supabase 클라이언트 초기화"""
        try:
            url = os.getenv("SUPABASE_URL")
            key = os.getenv("SUPABASE_KEY")
            
            if not url or not key:
                logger.warning("⚠️ Supabase 자격증명 누락")
                return None
            
            client = create_client(url, key)
            logger.info("✅ Supabase 연결 성공")
            return client
            
        except Exception as e:
            logger.error(f"❌ Supabase 연결 실패: {str(e)}")
            return None

    def _sanitize_data(self, data: Any) -> Any:
        """NULL 문자 제거 및 데이터 정리"""
        if isinstance(data, str):
            # NULL 문자(\u0000) 제거
            return data.replace('\u0000', '').replace('\x00', '')
        elif isinstance(data, dict):
            return {k: self._sanitize_data(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._sanitize_data(item) for item in data]
        else:
            return data

    def emit_event(self, event_type: str, data: Dict[str, Any], 
                     job_id: str = None, crew_type: str = None, 
                     todo_id: str = None, proc_inst_id: str = None) -> None:
        """커스텀 이벤트 발행"""
        try:
            if not self.supabase_client:
                logger.warning("⚠️ Supabase 클라이언트가 없어 이벤트를 기록할 수 없습니다")
                return
            
            # 이벤트 레코드 생성 (NULL 문자 제거)
            event_record = {
                "id": str(uuid.uuid4()),
                "job_id": job_id or str(uuid.uuid4()),
                "todo_id": todo_id,
                "proc_inst_id": proc_inst_id,
                "event_type": event_type,
                "crew_type": crew_type,
                "data": self._sanitize_data(data),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            
            # Supabase에 저장
            self.supabase_client.table("events").insert(event_record).execute()
            
            # 성공 로그
            job_display = (job_id or "unknown")[:8]
            print(f"📝 [{event_type}] [{crew_type or 'N/A'}] {job_display} → Supabase: ✅")
            
        except Exception as e:
            logger.error(f"❌ 이벤트 발행 실패: {str(e)}")
            print(f"📝 [{event_type}] → Supabase: ❌")

# 전역 인스턴스 생성
event_logger = EventLogger() 