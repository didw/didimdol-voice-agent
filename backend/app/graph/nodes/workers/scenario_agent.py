# backend/app/graph/nodes/workers/scenario_agent.py
"""
시나리오 에이전트 노드 - 사용자 입력을 시나리오별로 처리하고 의도/개체 추출
"""
from typing import cast

from ...state import AgentState, ScenarioAgentOutput
from ...utils import get_active_scenario_data
from ...chains import invoke_scenario_agent_logic
from ...logger import log_node_execution


async def call_scenario_agent_node(state: AgentState) -> AgentState:
    """
    시나리오 에이전트 호출 노드
    """
    user_input = state.stt_result or ""
    scenario_name = state.active_scenario_name or "N/A"
    # user_input이 None인 경우 처리
    input_preview = user_input[:20] if user_input else ""
    log_node_execution("Scenario_NLU", f"scenario={scenario_name}, input='{input_preview}...'")
    active_scenario_data = get_active_scenario_data(state.to_dict())
    if not active_scenario_data or not user_input:
        state_updates = {"scenario_agent_output": cast(ScenarioAgentOutput, {"intent": "error_missing_data", "is_scenario_related": False})}
        return state.merge_update(state_updates)
    
    current_stage_id = state.current_scenario_stage_id or active_scenario_data.get("initial_stage_id")
    current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})

    output = await invoke_scenario_agent_logic(
        user_input=user_input,
        current_stage_prompt=current_stage_info.get("prompt", ""),
        expected_info_key=current_stage_info.get("expected_info_key"),
        messages_history=list(state.messages)[:-1],
        scenario_name=active_scenario_data.get("scenario_name", "Consultation")
    )
    intent = output.get("intent", "N/A")
    
    entities = list(output.get("entities", {}).keys())
    log_node_execution("Scenario_NLU", output_info=f"intent={intent}, entities={entities}")
    
    state_updates = {"scenario_agent_output": output}
    return state.merge_update(state_updates)