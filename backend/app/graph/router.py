# backend/app/graph/router.py
"""
라우팅 로직 - 액션 플랜에 따라 적절한 워커 노드로 라우팅
"""
from .state import AgentState
from .logger import node_log as log_node_execution


# Worker 중심 라우팅 맵
WORKER_ROUTING_MAP = {
    "invoke_scenario_agent": "scenario_worker",
    "invoke_qa_agent": "rag_worker", 
    "invoke_web_search": "web_worker",
    "set_product_type": "set_product_type_node",
    "end_conversation": "end_conversation_node"
}


def execute_plan_router(state: AgentState) -> str:
    """
    간소화된 라우터 - Worker 중심 라우팅
    
    Args:
        state: 현재 에이전트 상태
        
    Returns:
        다음에 실행할 노드 이름
    """
    plan = state.get("action_plan", [])
    if not plan:
        log_node_execution("Router", "plan_complete → synthesizer")
        return "synthesize_response_node"

    next_action = plan[0] 
    target_node = WORKER_ROUTING_MAP.get(next_action, "synthesize_response_node")
    
    log_node_execution("Router", f"{next_action} → {target_node.replace('_node', '').replace('_worker', '')}")
    return target_node


def route_after_scenario_logic(state: AgentState) -> str:
    """
    시나리오 로직 처리 후 라우팅
    현재는 항상 synthesize_response_node로 라우팅
    """
    return "synthesize_response_node"