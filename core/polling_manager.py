import asyncio
import json
import os
import sys
from typing import Optional, Dict
from datetime import datetime
from utils.crew_event_logger import CrewAIEventLogger
from utils.logger import log, handle_error
from utils.context_manager import summarize_query_async
from core.database import (
    initialize_db, 
    fetch_pending_task, 
    fetch_task_status,
    update_task_completed,
    update_task_error,
    fetch_participants_info,
    fetch_form_types,
    fetch_human_users_by_proc_inst_id
)

# ============================================================================
# 설정 및 초기화
# ============================================================================

# 글로벌 상태
current_todo_id: Optional[int] = None
current_process: Optional[asyncio.subprocess.Process] = None
worker_terminated_by_us: bool = False

def initialize_connections():
    """데이터베이스 연결 초기화"""
    try:
        initialize_db()
        log("연결 초기화 완료")
    except Exception as e:
        handle_error("초기화", e)

# ============================================================================
# 작업 처리 메인 로직
# ============================================================================

async def process_new_task(row: Dict):
    """새 작업 처리"""
    global current_process, worker_terminated_by_us, current_todo_id
    
    current_todo_id = row['id']
    todo_id = row['id']
    
    try:
        log(f"새 작업 처리 시작: id={todo_id}")

        # 작업 데이터 준비 (prepare 단계)
        try:
            inputs = await _prepare_task_inputs(row)
        except Exception as e:
            try:
                CrewAIEventLogger().emit_error(
                    stage="prepare",
                    error=e,
                    context={
                        "todo_id": todo_id,
                        "activity": row.get("activity_name", ""),
                    },
                    todo_id=str(todo_id),
                    proc_inst_id=str(row.get('proc_inst_id') or row.get('root_proc_inst_id') or "")
                )
            finally:
                pass
            raise

        # 워커 실행 (execute 단계)
        try:
            await _execute_worker_process(inputs, todo_id)
        except Exception as e:
            try:
                CrewAIEventLogger().emit_error(
                    stage="execute_worker",
                    error=e,
                    context={
                        "todo_id": todo_id,
                        "activity": inputs.get("current_activity_name", "") if isinstance(inputs, dict) else "",
                    },
                    todo_id=str(todo_id),
                    proc_inst_id=str((inputs or {}).get('proc_inst_id') if isinstance(inputs, dict) else "")
                )
            finally:
                pass
            raise

    except Exception as e:
        # 작업 단위 실패는 ERROR로 마킹 후 예외 재던지기(폴링 상위에서 삼킴)
        await update_task_error(todo_id)
        handle_error("작업준비실패", e, raise_error=True)
        
    finally:
        # 글로벌 상태 초기화
        current_process = None
        worker_terminated_by_us = False
        current_todo_id = None

async def _prepare_task_inputs(row: Dict) -> Dict:
    """작업 입력 데이터 준비"""
    todo_id = row['id']
    proc_inst_id = row.get('root_proc_inst_id') or row.get('proc_inst_id') 
    current_activity_name = row.get("activity_name", "")
    original_query = row.get("query")
    log(f"🔍 폴링된 데이터 확인 - 원본 query: {repr(original_query)}")
    agent_ids = row.get("user_id")  # DB 컬럼명은 user_id이지만 변수명은 agent_ids로 사용
    tool_val = row.get("tool", "")
    tenant_id = str(row.get("tenant_id", ""))
    user_list, agent_list = await fetch_participants_info(agent_ids)
    form_id, form_types = await fetch_form_types(tool_val, tenant_id)
    
    # 프로세스의 실제 사용자(is_agent=false) 조회
    human_users = await fetch_human_users_by_proc_inst_id(proc_inst_id)
    
    # Query 요약 처리
    task_instructions = original_query
    if original_query and original_query.strip():
        try:
            task_instructions = await summarize_query_async(original_query, agent_list)
            log(f"📝 Query 요약 완료 - 원본: {len(original_query)}자 → 요약: {len(task_instructions)}자")
        except Exception as e:
            log(f"⚠️ Query 요약 실패, 원본 사용: {e}")
            task_instructions = original_query
    
    # 요약 처리 건너뛰기 - feedback은 원본 그대로 전달
    feedback_summary = row.get('feedback', "")
    
    return {
        "todo_id": todo_id,
        "current_activity_name": current_activity_name,
        "task_instructions": task_instructions,
        "agent_info": agent_list,
        "user_info": user_list,
        "tenant_id": tenant_id,
        "form_id": form_id,
        "form_types": form_types,
        "proc_inst_id": proc_inst_id,
        "human_users": human_users,
        "feedback_summary": feedback_summary,
    }

# ============================================================================
# 워커 프로세스 관리
# ============================================================================

async def _execute_worker_process(inputs: Dict, todo_id: int):
    """워커 프로세스 실행 및 관리"""
    global current_process, worker_terminated_by_us
    
    try:
        # 워커 프로세스 시작
        worker_terminated_by_us = False
        current_process = await asyncio.create_subprocess_exec(
            sys.executable,
            os.path.join(os.path.dirname(__file__), "worker.py"),
            "--inputs", json.dumps(inputs, ensure_ascii=False),
        )
        
        # 취소 상태 감시 및 워커 대기
        watch_task = asyncio.create_task(_watch_cancel_status())
        log(f"워커 시작 (PID={current_process.pid})")
        
        await current_process.wait()
        if not watch_task.done():
            watch_task.cancel()

        # 종료 결과 처리: 오류/사용자중단/정상 종료 구분
        if worker_terminated_by_us:
            log(f"워커 사용자 중단됨 (PID={current_process.pid})")
            return

        if current_process.returncode != 0:
            print(f"❌ 워커 비정상 종료 (code={current_process.returncode})", flush=True)
            await update_task_error(todo_id)
            return

        # 정상 종료 시 완료 처리 및 이벤트 발행
        ev = CrewAIEventLogger()
        ev.emit_event(
            event_type="crew_completed",
            data={},
            job_id="CREW_FINISHED",
            crew_type="crew",
            todo_id=todo_id,
            proc_inst_id=inputs.get("proc_inst_id")
        )
        log(f"워커 정상 종료 (PID={current_process.pid})")
        await update_task_completed(todo_id)
        
    except Exception as e:
        # 워커 실행/대기 중 예외도 ERROR로 마킹 후 재던지기
        await update_task_error(todo_id)
        handle_error("워커실행실패", e, raise_error=True)

def _log_worker_result():
    """워커 종료 결과 로그"""
    if worker_terminated_by_us:
        log(f"워커 사용자 중단됨 (PID={current_process.pid})")
    elif current_process.returncode != 0:
        print(f"❌ 워커 비정상 종료 (code={current_process.returncode})", flush=True)
    else:
        log(f"워커 정상 종료 (PID={current_process.pid})")

async def _watch_cancel_status():
    """워커 취소 상태 감시"""
    global current_todo_id, current_process, worker_terminated_by_us
    
    todo_id = current_todo_id
    if todo_id is None:
        return
    
    # 주기적으로 취소 상태 확인
    while current_process and current_process.returncode is None and not worker_terminated_by_us:
        await asyncio.sleep(5)
        try:
            draft_status = await fetch_task_status(todo_id)
            if draft_status in ('CANCELLED', 'FB_REQUESTED'):
                log(f"draft_status={draft_status} 감지 (id={todo_id}) → 워커 종료")
                terminate_current_worker()
                break
        except Exception as e:
            handle_error("취소감시오류", e, raise_error=False)

def terminate_current_worker():
    """현재 실행 중인 워커 프로세스 종료"""
    global current_process, worker_terminated_by_us
    
    if current_process and current_process.returncode is None:
        worker_terminated_by_us = True
        current_process.terminate()
        log(f"워커 프로세스 종료 시그널 전송 (PID={current_process.pid})")
    else:
        log("종료할 워커 프로세스가 없습니다")

# ============================================================================
# 폴링 실행
# ============================================================================

async def start_todolist_polling(interval: int = 7):
    """새 작업 처리 폴링 시작"""
    log("TodoList 폴링 시작")
    
    while True:
        try:
            print("todolist 폴링 시도")
            row = await fetch_pending_task()
            if row:
                await process_new_task(row)
                
        except Exception as e:
            handle_error("폴링오류", e, raise_error=False)
            
        await asyncio.sleep(interval)