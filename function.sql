-- 1) 대기중인 작업 조회 및 상태 변경
CREATE OR REPLACE FUNCTION public.crewai_action_fetch_pending_task(
  p_limit    integer,
  p_consumer text
)
RETURNS SETOF todolist AS $$
BEGIN
  RETURN QUERY
    WITH cte AS (
      SELECT *
        FROM todolist
      WHERE status = 'IN_PROGRESS' AND agent_orch = 'crewai-action'
         AND (
           (agent_mode IN ('DRAFT','COMPLETE') AND draft IS NULL AND draft_status IS NULL)
           OR draft_status = 'FB_REQUESTED'
         )       
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


-- 익명(anon) 역할에 실행 권한 부여
GRANT EXECUTE ON FUNCTION public.crewai_action_fetch_pending_task(integer, text) TO anon;

