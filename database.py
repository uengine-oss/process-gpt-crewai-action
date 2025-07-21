import os
import json
import asyncio
import socket
import traceback
from contextvars import ContextVar
from typing import Optional, List, Dict, Any, Tuple
from dotenv import load_dotenv
from supabase import create_client, Client

# ============================================================================  
# 설정 및 초기화  
# ============================================================================  

supabase_client_var = ContextVar('supabase', default=None)

def initialize_db():
    """환경변수 로드 및 Supabase 클라이언트 초기화"""
    try:
        if os.getenv("ENV") != "production":
            load_dotenv()

        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        if not supabase_url or not supabase_key:
            raise RuntimeError("SUPABASE_URL 및 SUPABASE_KEY를 .env에 설정하세요.")
        supabase: Client = create_client(supabase_url, supabase_key)
        supabase_client_var.set(supabase)

    except Exception as e:
        print(f"❌ DB 초기화 실패: {e}")
        print(f"상세 정보: {traceback.format_exc()}")
        raise

def _handle_db_error(operation: str, error: Exception) -> None:
    """통합 DB 에러 처리"""
    error_msg = f"❌ [{operation}] DB 오류 발생: {error}"
    print(error_msg)
    print(f"상세 정보: {traceback.format_exc()}")
    raise Exception(f"{operation} 실패: {error}")

# ============================================================================  
# 작업 조회 및 상태 관리  
# ============================================================================  

async def fetch_pending_task(limit: int = 1) -> Optional[Dict[str, Any]]:
    """Supabase RPC로 대기중인 작업 조회 및 상태 업데이트"""
    try:
        supabase = supabase_client_var.get()
        consumer_id = socket.gethostname()
        resp = supabase.rpc(
            'action_fetch_pending_task',
            {'p_limit': limit, 'p_consumer': consumer_id}
        ).execute()
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        _handle_db_error("작업조회", e)

async def fetch_task_status(todo_id: int) -> Optional[str]:
    """Supabase 테이블 조회로 작업 상태 조회"""
    try:
        supabase = supabase_client_var.get()
        resp = (
            supabase
            .table('todolist')
            .select('draft_status')
            .eq('id', todo_id)
            .single()
            .execute()
        )
        return resp.data.get('draft_status') if resp.data else None
    except Exception as e:
        _handle_db_error("상태조회", e)

async def update_task_completed(todo_id: str) -> None:
    """작업 완료 상태로 업데이트 (단순히 draft_status만 COMPLETED로 변경)"""
    try:
        supabase = supabase_client_var.get()
        resp = (
            supabase
            .table('todolist')
            .update({'draft_status': 'COMPLETED', 'consumer': None})
            .eq('id', todo_id)
            .execute()
        )
        print(f"✅ 작업 완료 상태 업데이트: {todo_id}")
    except Exception as e:
        _handle_db_error("작업완료업데이트", e)

async def fetch_previous_output(proc_inst_id: str, start_date: str) -> Optional[dict]:
    """이전 단계 output 조회 (proc_inst_id와 start_date 기준)"""
    try:
        supabase = supabase_client_var.get()
        resp = supabase.rpc(
            'action_fetch_previous_output',
            {'p_proc_inst_id': proc_inst_id, 'p_start_date': start_date}
        ).execute()
        # RPC 함수가 jsonb를 직접 반환하므로 resp.data가 바로 결과
        return resp.data if resp.data else None
    except Exception as e:
        _handle_db_error("이전출력조회", e)


# ============================================================================
# 사용자 및 에이전트 정보 조회 (Supabase)
# ============================================================================
async def fetch_participants_info(user_ids: str) -> Dict:
    """사용자 또는 에이전트 정보 조회"""
    def _sync():
        try:
            supabase = supabase_client_var.get()
            id_list = [id.strip() for id in user_ids.split(',') if id.strip()]
            
            user_info_list = []
            agent_info_list = []
            
            for user_id in id_list:
                # 이메일로 사용자 조회
                user_data = _get_user_by_email(supabase, user_id)
                if user_data:
                    user_info_list.append(user_data)
                    continue
                    
                # ID로 에이전트 조회
                agent_data = _get_agent_by_id(supabase, user_id)
                if agent_data:
                    agent_info_list.append(agent_data)
            
            result = {}
            if user_info_list:
                result['user_info'] = user_info_list
            if agent_info_list:
                result['agent_info'] = agent_info_list
            
            return result
            
        except Exception as e:
            _handle_db_error("참가자정보조회", e)
            
    return await asyncio.to_thread(_sync)

def _get_user_by_email(supabase: Client, user_id: str) -> Optional[Dict]:
    """이메일로 사용자 조회"""
    resp = supabase.table('users').select('id, email, username').eq('email', user_id).execute()
    if resp.data:
        user = resp.data[0]
        return {
            'email': user.get('email'),
            'name': user.get('username'),
            'tenant_id': user.get('tenant_id')
        }
    return None

def _get_agent_by_id(supabase: Client, user_id: str) -> Optional[Dict]:
    """ID로 에이전트 조회"""
    resp = supabase.table('users').select(
        'id, username, role, goal, persona, tools, profile, is_agent, model, tenant_id'
    ).eq('id', user_id).execute()
    
    if resp.data and resp.data[0].get('is_agent'):
        agent = resp.data[0]
        return {
            'id': agent.get('id'),
            'name': agent.get('username'),
            'role': agent.get('role'),
            'goal': agent.get('goal'),
            'persona': agent.get('persona'),
            'tools': agent.get('tools'),
            'profile': agent.get('profile'),
            'model': agent.get('model'),
            'tenant_id': agent.get('tenant_id')
        }
    return None