-- 기존 함수가 있다면 먼저 삭제
DROP FUNCTION IF EXISTS public.crewai_action_fetch_pending_task(integer, text);

CREATE OR REPLACE FUNCTION public.crewai_action_fetch_pending_task(
  p_limit    integer,
  p_consumer text
)
RETURNS TABLE (
  id uuid,
  user_id text,
  proc_inst_id text,
  proc_def_id text,
  activity_id text,
  activity_name text,
  start_date timestamp without time zone,
  end_date timestamp without time zone,
  description text,
  tool text,
  due_date timestamp without time zone,
  tenant_id text,
  reference_ids text[],
  adhoc boolean,
  assignees jsonb,
  duration integer,
  output jsonb,
  retry integer,
  consumer text,
  log text,
  draft jsonb,
  project_id uuid,
  feedback jsonb,
  updated_at timestamp with time zone,
  username text,
  status public.todo_status,
  agent_mode public.agent_mode,
  agent_orch public.agent_orch,
  temp_feedback text,
  draft_status public.draft_status,
  -- 가상 컬럼(업데이트 전 값)
  task_type public.draft_status
) AS $$
BEGIN
  RETURN QUERY
    WITH cte AS (
      SELECT
        t.*,
        t.draft_status AS task_type   -- 원본 보관
      FROM todolist AS t
      WHERE t.status = 'IN_PROGRESS'
        AND t.agent_orch = 'crewai-action'
        AND (
          (t.agent_mode IN ('DRAFT','COMPLETE') AND t.draft IS NULL AND t.draft_status IS NULL)
          OR t.draft_status = 'FB_REQUESTED'
        )
      ORDER BY t.start_date
      LIMIT p_limit
      FOR UPDATE SKIP LOCKED
    ),
    upd AS (
      UPDATE todolist AS t
         SET draft_status = 'STARTED',
             consumer     = p_consumer
        FROM cte
       WHERE t.id = cte.id
       RETURNING
         t.id,
         t.user_id,
         t.proc_inst_id,
         t.proc_def_id,
         t.activity_id,
         t.activity_name,
         t.start_date,
         t.end_date,
         t.description,
         t.tool,
         t.due_date,
         t.tenant_id,
         t.reference_ids,
         t.adhoc,
         t.assignees,
         t.duration,
         t.output,
         t.retry,
         t.consumer,
         t.log,
         t.draft,
         t.project_id,
         t.feedback,
         t.updated_at,
         t.username,
         t.status,
         t.agent_mode,
         t.agent_orch,
         t.temp_feedback,
         t.draft_status,              -- 변경 후 값 (STARTED)
         cte.task_type      -- 변경 전 값
    )
    SELECT * FROM upd;
END;
$$ LANGUAGE plpgsql VOLATILE;

GRANT EXECUTE ON FUNCTION public.crewai_action_fetch_pending_task(integer, text) TO anon;
