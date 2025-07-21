from crewai import Crew, Process
from crew.tasks import create_parse_task, create_plan_task, create_execute_task, create_confirm_task
from crew.agents import create_requirement_parser, create_db_planner, create_sql_executor, create_result_confirmer
from tools.safe_tool_loader import SafeToolLoader
import logging

logger = logging.getLogger(__name__)

def create_crew(tool_names=None):
    logger.info(f"create_crew 호출됨 (tool_names={tool_names})")
    
    # 동적 툴 로딩
    loader = SafeToolLoader()
    if tool_names:
        tools = loader.create_tools_from_names(tool_names)
        logger.info(f"동적 툴 로드 완료: {tool_names} ({len(tools)}개)")
    else:
        tools = loader.create_tools_from_names('supabase')
        logger.info(f"기본 툴 로드 완료: supabase ({len(tools)}개)")
    
    # 툴을 받아서 에이전트 동적 생성
    requirement_parser = create_requirement_parser(tools)
    db_planner = create_db_planner(tools)
    sql_executor = create_sql_executor(tools)
    result_confirmer = create_result_confirmer(tools)
    
    # 에이전트를 받아서 태스크 동적 생성
    parse_task = create_parse_task(requirement_parser)
    plan_task = create_plan_task(db_planner)
    execute_task = create_execute_task(sql_executor)
    confirm_task = create_confirm_task(result_confirmer)
    
    # 태스크 간 context 연결
    plan_task.context = [parse_task]
    execute_task.context = [plan_task]
    confirm_task.context = [execute_task]
    
    return Crew(
        agents=[requirement_parser, db_planner, sql_executor, result_confirmer],
        tasks=[parse_task, plan_task, execute_task, confirm_task],
        process=Process.sequential,
        planning=True,
        verbose=True
    ) 