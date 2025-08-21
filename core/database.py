import os
import json
import asyncio
import re
import socket
from typing import Optional, List, Dict, Any, Tuple
from dotenv import load_dotenv
from supabase import create_client, Client
from utils.logger import handle_error, log
from typing import Callable, TypeVar, Any as _Any
import random
import uuid

T = TypeVar("T")

async def _async_retry(fn: Callable[[], T], *, name: str, retries: int = 3, base_delay: float = 0.8) -> T | None:
    """간단한 지수 백오프 재시도 (네트워크/HTTP 오류 완화용)"""
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            jitter = random.uniform(0, 0.3)
            delay = base_delay * (2 ** (attempt - 1)) + jitter
            handle_error(f"{name} 재시도 {attempt}/{retries}", e, raise_error=False, extra={"delay": round(delay, 2)})
            await asyncio.sleep(delay)
    handle_error(f"{name} 최종실패", last_err or Exception("unknown"), raise_error=False)
    return None

# ============================================================================
# DB 설정 및 초기화
# ============================================================================

load_dotenv()
_db_client: Client | None = None

def initialize_db() -> None:
    """Supabase 클라이언트 초기화"""
    global _db_client
    if _db_client is not None:
        return
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL/KEY 설정 필요")
    _db_client = create_client(url, key)

def get_db_client() -> Client:
    """DB 클라이언트 반환"""
    if _db_client is None:
        raise RuntimeError("DB 클라이언트 비초기화: initialize_db() 먼저 호출하세요")
    return _db_client

# ============================================================================
# 이벤트 조회 (단건)
# ============================================================================

def fetch_human_response(job_id: str) -> Optional[Dict[str, Any]]:
    """events 테이블에서 동일 job_id의 human_response 단일 레코드 조회"""
    try:
        supabase = get_db_client()
        resp = (
            supabase
            .table('events')
            .select('*')
            .eq('job_id', job_id)
            .eq('event_type', 'human_response')
            .execute()
        )
        # 0개 행일 때도 안전하게 처리
        if resp.data and len(resp.data) > 0:
            return resp.data[0]
        return None
    except Exception as e:
        handle_error("이벤트조회오류", e)
        return None
# ============================================================================
# 작업 조회 및 상태 관리
# ============================================================================

async def fetch_todo_by_id(todo_id: int) -> Optional[Dict[str, Any]]:
    """특정 todolist 항목 조회"""
    try:
        supabase = get_db_client()
        resp = (
            supabase
            .table('todolist')
            .select('*')
            .eq('id', todo_id)
            .single()
            .execute()
        )
        return resp.data if resp.data else None
    except Exception as e:
        handle_error("투두조회오류", e)

async def fetch_pending_task(limit: int = 1) -> Optional[Dict[str, Any]]:
    """대기중인 작업 조회"""
    try:
        supabase = get_db_client()
        consumer_id = socket.gethostname()

        def _call():
            return (
                supabase
                .rpc('crewai_action_fetch_pending_task', {'p_limit': limit, 'p_consumer': consumer_id})
                .execute()
            )

        resp = await _async_retry(_call, name="작업조회")
        if not resp:
            return None
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as e:
        handle_error("작업조회오류", e, raise_error=False)
        return None

async def fetch_task_status(todo_id: int) -> Optional[str]:
    """작업 상태 조회"""
    try:
        supabase = get_db_client()

        def _call():
            return (
                supabase
                .table('todolist')
                .select('draft_status')
                .eq('id', todo_id)
                .single()
                .execute()
            )

        resp = await _async_retry(_call, name="상태조회")
        if not resp:
            return None
        return resp.data.get('draft_status') if resp.data else None
    except Exception as e:
        handle_error("상태조회오류", e, raise_error=False)

async def update_task_completed(todo_id: str) -> None:
    """작업 완료 상태 업데이트"""
    try:
        supabase = get_db_client()
        resp = (
            supabase
            .table('todolist')
            .update({'draft_status': 'COMPLETED', 'consumer': None})
            .eq('id', todo_id)
            .execute()
        )
        log(f"작업 완료 상태 업데이트: {todo_id}")
    except Exception as e:
        handle_error("완료상태오류", e)

async def update_task_error(todo_id: str) -> None:
    """작업 오류 상태 업데이트 (FAILED) - 로그 컬럼은 건드리지 않음"""
    try:
        supabase = get_db_client()
        (
            supabase
            .table('todolist')
            .update({'draft_status': 'FAILED', 'consumer': None})
            .eq('id', todo_id)
            .execute()
        )
        log(f"작업 오류 상태 업데이트: {todo_id}")
    except Exception as e:
        handle_error("오류상태오류", e, raise_error=False)

async def fetch_done_data(proc_inst_id: Optional[str]) -> List[Any]:
    """완료된 데이터 조회 (output만)"""
    if not proc_inst_id:
        return []
    try:
        supabase = get_db_client()
        resp = supabase.rpc(
            'fetch_done_data',
            {'p_proc_inst_id': proc_inst_id}
        ).execute()
        outputs = []
        for row in resp.data or []:
            outputs.append(row.get('output'))
        return outputs
    except Exception as e:
        handle_error("완료데이터오류", e, raise_error=True)
        
# ============================================================================
# 사용자 및 에이전트 정보 조회
# ============================================================================

async def fetch_human_users_by_proc_inst_id(proc_inst_id: str) -> str:
    """proc_inst_id로 해당 프로세스의 실제 사용자(is_agent=false)들의 이메일만 쉼표로 구분하여 반환"""
    if not proc_inst_id:
        return ""
    
    def _sync():
        try:
            supabase = get_db_client()
            
            # 1. proc_inst_id로 todolist에서 user_id들 조회
            resp = (
                supabase
                .table('todolist')
                .select('user_id')
                .eq('proc_inst_id', proc_inst_id)
                .execute()
            )
            
            if not resp.data:
                return ""
            
            # 2. 모든 user_id를 수집 (중복 제거)
            all_user_ids = set()
            for row in resp.data:
                user_id = row.get('user_id', '')
                if user_id:
                    # 쉼표로 구분된 경우 분리
                    ids = [id.strip() for id in user_id.split(',') if id.strip()]
                    all_user_ids.update(ids)
            
            if not all_user_ids:
                return ""
            
            # 3. 각 user_id가 실제 사용자(is_agent=false 또는 null)인지 확인 후 이메일 수집
            human_user_emails = []
            for user_id in all_user_ids:
                # UUID 형식이 아니면 스킵
                if not _is_valid_uuid(user_id):
                    continue
                
                # users 테이블에서 해당 user_id 조회
                user_resp = (
                    supabase
                    .table('users')
                    .select('id, email, is_agent')
                    .eq('id', user_id)
                    .execute()
                )
                
                if user_resp.data:
                    user = user_resp.data[0]
                    is_agent = user.get('is_agent')
                    # is_agent가 false이거나 null인 경우만 실제 사용자로 간주
                    if not is_agent:  # False 또는 None
                        email = (user.get('email') or '').strip()
                        if email:
                            human_user_emails.append(email)
            
            # 4. 쉼표로 구분된 문자열로 반환
            return ','.join(human_user_emails)
            
        except Exception as e:
            handle_error("사용자조회오류", e, raise_error=False)
            return ""
    
    return await asyncio.to_thread(_sync)

async def fetch_participants_info(agent_ids: str) -> tuple[List[Dict], List[Dict]]:
    """사용자 또는 에이전트 정보 조회"""
    def _sync():
        try:
            id_list = [id.strip() for id in agent_ids.split(',') if id.strip()]
            
            user_info_list = []
            agent_info_list = []
            
            for agent_id in id_list:

                # UUID가 아니면 사용자/에이전트 모두 스킵
                if not _is_valid_uuid(agent_id):
                    continue

                # 이메일로 사용자 조회
                user_data = _get_user_by_email(agent_id)
                if user_data:
                    user_info_list.append(user_data)
                    continue
                    
                # ID로 에이전트 조회
                agent_data = _get_agent_by_id(agent_id)
                if agent_data:
                    agent_info_list.append(agent_data)
            
            return user_info_list, agent_info_list
            
        except Exception as e:
            handle_error("참가자정보오류", e, raise_error=True)
            
    return await asyncio.to_thread(_sync)

def _get_user_by_email(agent_id: str) -> Optional[Dict]:
    """이메일로 사용자 조회"""
    supabase = get_db_client()
    resp = supabase.table('users').select('id, email, username').eq('email', agent_id).execute()
    if resp.data:
        user = resp.data[0]
        return {
            'email': user.get('email'),
            'name': user.get('username'),
            'tenant_id': user.get('tenant_id')
        }
    return None

def _get_agent_by_id(agent_id: str) -> Optional[Dict[str, Any]]:
    """ID로 에이전트 조회"""
    supabase = get_db_client()
    resp = supabase.table('users').select(
        'id, username, role, goal, persona, tools, profile, is_agent, model, tenant_id'
    ).eq('id', agent_id).execute()
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

def _is_valid_uuid(value: str) -> bool:
    """UUID 문자열 형식 검증 (v1~v8 포함)"""
    try:
        uuid.UUID(value)
        return True
    except Exception:
        return False

# ============================================================================
# 폼 타입 조회
# ============================================================================

async def fetch_form_types(tool_val: str, tenant_id: str) -> tuple[str, Dict[str, Any]]:
    """폼 타입 정보 조회 및 정규화 - form_id와 form_types 함께 반환

    form_types 반환 형식:
      { "fields": <fields_json 리스트>, "html": <html 문자열 또는 None> }
    """
    def _sync():
        try:
            supabase = get_db_client()
            form_id = tool_val[12:] if tool_val.startswith('formHandler:') else tool_val
            
            resp = (
                supabase
                .table('form_def')
                .select('fields_json, html')
                .eq('id', form_id)
                .eq('tenant_id', tenant_id)
                .execute()
            )
            log(f'✅ 폼 타입 조회 완료: {resp}')
            fields_json = resp.data[0].get('fields_json') if resp.data else None
            html = resp.data[0].get('html') if resp.data else None
            log(f'✅ 폼 필드 JSON: {fields_json}')
            log(f'✅ 폼 HTML: {(html[:120] + "...") if isinstance(html, str) and len(html) > 120 else html}')
            if not fields_json:
                return form_id, {"fields": [{"key": form_id, "type": "default", "text": ""}], "html": html}

            return form_id, {"fields": fields_json, "html": html}
            
        except Exception as e:
            handle_error("폼타입조회", e, raise_error=True)
            
    return await asyncio.to_thread(_sync)

# ============================================================================
# 테넌트 정보 조회
# ============================================================================

def fetch_tenant_mcp_config(tenant_id: str) -> Optional[Dict[str, Any]]:
    """테넌트 MCP 설정 조회"""
    try:
        supabase = get_db_client()
        resp = (
            supabase
            .table('tenants')
            .select('mcp')
            .eq('id', tenant_id)
            .single()
            .execute()
        )
        return resp.data.get('mcp') if resp.data else None
    except Exception as e:
        handle_error("테넌트설정오류", e)

# ============================================================================
# 결과 저장
# ============================================================================

async def save_task_result(todo_id: int, result: Any) -> None:
    """작업 결과 저장"""
    def _sync():
        try:
            supabase = get_db_client()
            
            # JSON 직렬화 처리
            if isinstance(result, (dict, list)):
                payload = result
            else:
                payload = json.loads(json.dumps(result, default=str))
            
            supabase.rpc(
                'save_task_result',
                {
                    'p_todo_id': todo_id,
                    'p_payload': payload,
                    'p_final': True
                }
            ).execute()
            log(f"결과 저장 완료: todo_id={todo_id}")
        except Exception as e:
            handle_error("결과저장오류", e)

    await asyncio.to_thread(_sync)

# ============================================================================
# 알림 저장
# ============================================================================

def save_notification(
    *,
    title: str,
    notif_type: str,
    description: Optional[str] = None,
    user_ids_csv: Optional[str] = None,
    tenant_id: Optional[str] = None,
    url: Optional[str] = None,
    from_user_id: Optional[str] = None,
) -> None:
    """notifications 테이블에 알림 저장

    - user_ids_csv: 쉼표로 구분된 사용자 ID 목록. 비어있으면 저장 생략
    - 테이블 스키마는 다음 컬럼을 가정: user_id, tenant_id, title, description, type, url, from_user_id
    """
    try:
        # 대상 사용자가 없으면 작업 생략
        if not user_ids_csv:
            log(f"알림 저장 생략: 대상 사용자 없음 (user_ids_csv={user_ids_csv})")
            return

        supabase = get_db_client()

        user_ids: List[str] = [uid.strip() for uid in user_ids_csv.split(',') if uid and uid.strip()]
        if not user_ids:
            log(f"알림 저장 생략: 유효한 사용자 ID 없음 (user_ids_csv={user_ids_csv})")
            return
        
        rows: List[Dict[str, Any]] = []
        for uid in user_ids:
            rows.append(
                {
                    "id": str(uuid.uuid4()),  # UUID 자동 생성
                    "user_id": uid,
                    "tenant_id": tenant_id,
                    "title": title,
                    "description": description,
                    "type": notif_type,
                    "url": url,
                    "from_user_id": from_user_id,
                }
            )

        supabase.table("notifications").insert(rows).execute()
        log(f"알림 저장 완료: {len(rows)}건")
    except Exception as e:
        # 알림 저장 실패는 치명적이지 않으므로 오류만 로깅
        handle_error("알림저장오류", e, raise_error=False)