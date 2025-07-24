-- 1) 대기중인 작업 조회 및 상태 변경
CREATE OR REPLACE FUNCTION public.action_fetch_pending_task(
  p_limit    integer,
  p_consumer text
)
RETURNS SETOF todolist AS $$
BEGIN
  RETURN QUERY
    WITH cte AS (
      SELECT *
        FROM todolist
       WHERE status ='IN_PROGRESS'
         AND (agent_mode = 'COMPLETE' AND draft_status IS NULL AND agent_orch = 'crewai-action')
       ORDER BY start_date
       LIMIT p_limit
       FOR UPDATE SKIP LOCKED
    ), upd AS (
      UPDATE todolist
         SET draft_status = 'STARTED',
             consumer     = p_consumer
        FROM cte
       WHERE todolist.id = cte.id
       RETURNING todolist.*
    )
    SELECT * FROM upd;
END;
$$ LANGUAGE plpgsql VOLATILE;

-- 기존 함수 제거
DROP FUNCTION IF EXISTS public.action_fetch_previous_output(uuid);

-- 새로운 이전 단계 output 조회 함수 (proc_inst_id와 start_date 기준)
CREATE OR REPLACE FUNCTION public.action_fetch_previous_output(
  p_proc_inst_id text,
  p_start_date timestamp
)
RETURNS jsonb AS $$
BEGIN
  RETURN (
    SELECT output
      FROM todolist
     WHERE proc_inst_id = p_proc_inst_id
       AND start_date < p_start_date
     ORDER BY start_date DESC
     LIMIT 1
  );
END;
$$ LANGUAGE plpgsql STABLE;

-- 2) 완료된 데이터 조회 (activity_name을 키로 하는 output 반환)
CREATE OR REPLACE FUNCTION public.action_fetch_done_data(
  p_proc_inst_id text
)
RETURNS TABLE (
  activity_name text,
  output jsonb
)
LANGUAGE SQL
AS $$
  SELECT t.activity_name, t.output
    FROM todolist AS t
   WHERE t.proc_inst_id = p_proc_inst_id
     AND t.status = 'DONE'
     AND t.output IS NOT NULL
   ORDER BY t.start_date DESC
$$;

-- 익명(anon) 역할에 실행 권한 부여
GRANT EXECUTE ON FUNCTION public.action_fetch_previous_output(text, timestamp) TO anon;
GRANT EXECUTE ON FUNCTION public.action_fetch_pending_task(integer, text) TO anon;
GRANT EXECUTE ON FUNCTION public.fetch_done_data(text) TO anon;

-- 3) 결과 저장 (agent_mode=COMPLETE 전용)
CREATE OR REPLACE FUNCTION public.action_save_task_result(
  p_todo_id uuid,
  p_payload jsonb
)
RETURNS void AS $$
BEGIN
  -- 최종 결과만 존재하므로 바로 완료 처리
  UPDATE todolist
     SET output       = p_payload,
         status       = 'SUBMITTED',
         draft_status = 'COMPLETED',
         consumer     = NULL
   WHERE id = p_todo_id;
END;
$$ LANGUAGE plpgsql VOLATILE;

-- 익명(anon) 역할에 실행 권한 부여
GRANT EXECUTE ON FUNCTION public.action_save_task_result(uuid, jsonb) TO anon;
