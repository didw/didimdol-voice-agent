# backend/app/graph/nodes/orchestrator/entry_point.py
"""
진입점 노드 - 사용자 입력을 받아 초기 상태를 설정하고 턴별 상태를 리셋
"""
from typing import cast, Dict, Any
from langchain_core.messages import HumanMessage

from ...state import AgentState, AgentStateModel
from ...state_utils import ensure_pydantic_state, ensure_dict_state
from ...utils import ALL_PROMPTS, ALL_SCENARIOS_DATA, get_active_scenario_data
from ...logger import node_log, log_execution_time


def _check_scenario_continuation(prev_state: AgentStateModel, current_state: AgentStateModel) -> Dict[str, Any]:
    """시나리오 연속 진행이 필요한지 확인하고 자동 설정"""
    
    # 이전 상태에서 시나리오 연속성이 준비되어 있고, 현재 사용자 입력이 있는 경우
    if (prev_state.scenario_ready_for_continuation and 
        prev_state.current_product_type and 
        current_state.user_input_text):
        
        node_log("Scenario Continuation", 
                f"product={prev_state.current_product_type}, "
                f"scenario={prev_state.active_scenario_name}")
        
        return {
            "action_plan": ["invoke_scenario_agent"],
            "scenario_ready_for_continuation": False,  # 자동 진행 후 리셋
            "scenario_awaiting_user_response": False,
            # 이전 상태에서 필요한 정보 복원
            "current_product_type": prev_state.current_product_type,
            "current_scenario_stage_id": prev_state.current_scenario_stage_id,
            "collected_product_info": prev_state.collected_product_info
        }
    
    return {}


@log_execution_time
async def entry_point_node(state: AgentState) -> AgentState:
    """
    진입점 노드 - Pydantic 버전
    - 사용자 입력 처리
    - 턴별 상태 초기화
    - 시나리오 데이터 로드
    - 메시지 히스토리 업데이트
    """
    # Convert to Pydantic for internal processing
    pydantic_state = ensure_pydantic_state(state)
    
    user_text = pydantic_state.user_input_text or ""
    product = pydantic_state.current_product_type or "None"
    node_log("Entry", input_info=f"input='{user_text[:20]}...', product={product}")
    
    if not ALL_SCENARIOS_DATA or not ALL_PROMPTS:
        error_msg = "Service initialization failed (Cannot load scenarios or prompts)."
        return ensure_dict_state(pydantic_state.merge_update({
            "error_message": error_msg,
            "final_response_text_for_tts": error_msg,
            "is_final_turn_response": True
        }))

    # Reset turn-specific state using Pydantic merge
    turn_defaults = {
        "stt_result": None,
        "main_agent_routing_decision": None,
        "main_agent_direct_response": None,
        "scenario_agent_output": None,
        "final_response_text_for_tts": None,
        "is_final_turn_response": False,
        "error_message": None,
        "active_scenario_data": None,
        "active_knowledge_base_content": None,
        "loan_selection_is_fresh": False,
        "factual_response": None,
        "action_plan": [],
    }
    
    # Update state with turn defaults
    updated_state = pydantic_state.merge_update(turn_defaults)
    
    # Load active scenario data if a product is selected
    active_scenario = get_active_scenario_data(updated_state.to_dict())
    if active_scenario:
        updated_state = updated_state.merge_update({
            "active_scenario_data": active_scenario,
            "active_scenario_name": active_scenario.get("scenario_name", "Unknown Product")
        })
        
        if not updated_state.current_scenario_stage_id:
            updated_state = updated_state.merge_update({
                "current_scenario_stage_id": active_scenario.get("initial_stage_id")
            })
    else:
        updated_state = updated_state.merge_update({
            "active_scenario_name": "Not Selected"
        })

    # Add user input to message history
    if updated_state.user_input_text:
        messages = list(updated_state.messages)
        if not messages or not (isinstance(messages[-1], HumanMessage) and messages[-1].content == updated_state.user_input_text):
            messages.append(HumanMessage(content=updated_state.user_input_text))
        
        updated_state = updated_state.merge_update({
            "messages": messages,
            "stt_result": updated_state.user_input_text
        })
    
    # 시나리오 자동 진행 로직
    scenario_continuation = _check_scenario_continuation(pydantic_state, updated_state)
    if scenario_continuation:
        updated_state = updated_state.merge_update(scenario_continuation)
        
    return ensure_dict_state(updated_state)