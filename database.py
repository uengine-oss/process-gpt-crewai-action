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

load_dotenv()
_db_client: Client | None = None

def initialize_db() -> None:
    """환경변수 로드 후, 최초 1회만 Supabase 클라이언트 생성"""
    global _db_client
    if _db_client is not None:
        return
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL/KEY 설정 필요")
    _db_client = create_client(url, key)

def _handle_db_error(operation: str, error: Exception) -> None:
    """통합 DB 에러 처리"""
    error_msg = f"❌ [{operation}] DB 오류 발생: {error}"
    print(error_msg)
    print(f"상세 정보: {traceback.format_exc()}")
    raise Exception(f"{operation} 실패: {error}")

def get_db_client() -> Client:
    """이미 생성된 클라이언트를 반환, 미생성 시 오류"""
    if _db_client is None:
        raise RuntimeError("DB 클라이언트 비초기화: initialize_db() 먼저 호출하세요")
    return _db_client
# ============================================================================  
# 작업 조회 및 상태 관리  
# ============================================================================  

async def fetch_pending_task(limit: int = 1) -> Optional[Dict[str, Any]]:
    """Supabase RPC로 대기중인 작업 조회 및 상태 업데이트"""
    try:
        supabase = get_db_client()
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
        supabase = get_db_client()
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
        supabase = get_db_client()
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

async def fetch_previous_output(proc_inst_id: str) -> Dict[str, Any]:
    """완료된 모든 output 조회 (proc_inst_id 기준) - activity_name을 키로 하는 딕셔너리 반환"""
    try:
        supabase = get_db_client()
        resp = supabase.rpc(
            'action_fetch_done_data',
            {'p_proc_inst_id': proc_inst_id}
        ).execute()
        activity_outputs = {}
        for row in (resp.data or []):
            output = row.get('output')
            if output and isinstance(output, dict):
                # output 객체 안의 각 키가 activity_name, 값이 실제 output
                for activity_name, activity_output in output.items():
                    activity_outputs[activity_name] = activity_output
        return activity_outputs
    except Exception as e:
        _handle_db_error("완료된출력조회", e)


# ============================================================================
# 사용자 및 에이전트 정보 조회 (Supabase)
# ============================================================================
async def fetch_participants_info(user_ids: str) -> Dict:
    """사용자 또는 에이전트 정보 조회"""
    def _sync():
        try:
            supabase = get_db_client()
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

def _get_agent_by_id(supabase: Client, user_id: str) -> Optional[Dict[str, Any]]:
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

# ============================================================================
# 폼 타입 조회 (Supabase)
# ============================================================================

async def fetch_form_types(tool_val: str, tenant_id: str) -> tuple[str, list[Dict[str, Any]]]:
    """폼 타입 정보 조회 및 정규화 - form_id와 form_types 함께 반환"""
    def _sync():
        try:
            supabase = get_db_client()
            form_id = tool_val[12:] if tool_val.startswith('formHandler:') else tool_val
            
            resp = (
                supabase
                .table('form_def')
                .select('fields_json')
                .eq('id', form_id)
                .eq('tenant_id', tenant_id)
                .execute()
            )
            fields_json = resp.data[0].get('fields_json') if resp.data else None
            
            if not fields_json:
                return form_id, [{'id': form_id, 'type': 'default'}]
            
            form_types = []
            for field in fields_json:
                field_type = field.get('type', '').lower()
                normalized_type = field_type if field_type in ['report', 'slide'] else 'text'
                form_types.append({
                    'id': field.get('key'),
                    'type': normalized_type,
                    'key': field.get('key'),
                    'text': field.get('text', '')
                })
            
            return form_id, form_types
            
        except Exception as e:
            _handle_db_error("폼타입조회", e)
            
    return await asyncio.to_thread(_sync)

# ============================================================================  
# 결과 저장  
# ============================================================================  

async def save_task_result(todo_id: int, result: Any) -> None:
    """Supabase RPC로 작업 결과 저장 호출 (agent_mode=COMPLETE 전용)"""
    def _sync():
        try:
            supabase = get_db_client()
            
            # 간단한 JSON 직렬화 처리
            if isinstance(result, (dict, list)):
                payload = result
            else:
                payload = json.loads(json.dumps(result, default=str))
            
            supabase.rpc(
                'action_save_task_result',
                {
                    'p_todo_id': todo_id,
                    'p_payload': payload
                }
            ).execute()
            print(f"✅ 결과 저장 완료: todo_id={todo_id}")
        except Exception as e:
            _handle_db_error("결과저장", e)

    await asyncio.to_thread(_sync)