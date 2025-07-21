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
         AND (agent_mode = 'COMPLETED' AND draft_status IS NULL AND agent_orch = 'crewai-action')
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

-- 익명(anon) 역할에 실행 권한 부여
GRANT EXECUTE ON FUNCTION public.action_fetch_previous_output(text, timestamp) TO anon;
GRANT EXECUTE ON FUNCTION public.action_fetch_pending_task(integer, text) TO anon;
