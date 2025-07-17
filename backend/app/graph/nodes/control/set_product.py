# backend/app/graph/nodes/control/set_product.py
"""
제품 타입 설정 노드 - 사용자가 선택한 제품에 대한 시나리오를 로드하고 초기화
"""
from langchain_core.messages import AIMessage

from ...state import AgentState
from ...state_utils import ensure_pydantic_state, ensure_dict_state
from ...models import ActionModel
from ...utils import ALL_SCENARIOS_DATA
from ...logger import node_log as log_node_execution, log_execution_time


@log_execution_time
async def set_product_type_node(state: AgentState) -> AgentState:
    """
    제품 타입 설정 노드 - Pydantic 버전
    - 제품 ID 추출 및 검증
    - 시나리오 데이터 로드
    - 초기 스테이지 설정
    - 기본값 초기화
    """
    # Convert to Pydantic for internal processing
    pydantic_state = ensure_pydantic_state(state)
    
    action_plan_struct = pydantic_state.action_plan_struct
    if action_plan_struct:
        product_id = action_plan_struct[0].get("tool_input", {}).get("product_id", "N/A")
        log_node_execution("Set_Product", f"product={product_id}")
    else:
        log_node_execution("Set_Product", "ERROR: no action plan")
    
    if not action_plan_struct:
        err_msg = "Action plan is empty in set_product_type_node"
        log_node_execution("Set_Product", f"ERROR: {err_msg}")
        return ensure_dict_state(pydantic_state.merge_update({
            "error_message": err_msg,
            "is_final_turn_response": True
        }))
    
    # 현재 액션에 맞는 구조 찾기
    current_action_model = ActionModel.model_validate(action_plan_struct[0])
    
    new_product_type = current_action_model.tool_input.get("product_id")
    
    if not new_product_type:
        err_msg = f"product_id not found in action: {current_action_model.model_dump()}"
        log_node_execution("Set_Product", f"ERROR: {err_msg}")
        return ensure_dict_state(pydantic_state.merge_update({
            "error_message": err_msg,
            "is_final_turn_response": True
        }))

    active_scenario = ALL_SCENARIOS_DATA.get(new_product_type)
    
    if not active_scenario:
        err_msg = f"Failed to load scenario for product type: {new_product_type}"
        log_node_execution("Set_Product", f"ERROR: {err_msg}")
        return ensure_dict_state(pydantic_state.merge_update({
            "error_message": err_msg,
            "is_final_turn_response": True
        }))
        
    log_node_execution("Set_Product", f"loaded scenario: {active_scenario.get('scenario_name')}")

    initial_stage_id = active_scenario.get("initial_stage_id")
    response_text = active_scenario.get("stages", {}).get(str(initial_stage_id), {}).get("prompt", "How can I help?")

    log_node_execution("Set_Product", f"response: '{response_text[:70]}...'")

    updated_messages = list(pydantic_state.messages) + [AIMessage(content=response_text)]
    
    # Default 값 초기화
    from ....api.V1.chat_utils import initialize_default_values
    temp_state = {
        **pydantic_state.to_dict(),
        "current_product_type": new_product_type, 
        "active_scenario_data": active_scenario
    }
    initialized_info = initialize_default_values(temp_state)
    log_node_execution("Set_Product", f"initialized defaults: {initialized_info}")
    
    # 시나리오 연속성을 위한 상태 설정
    log_node_execution("Set_Product", f"scenario ready: {active_scenario.get('scenario_name')}")
    
    state_updates = {
        "current_product_type": new_product_type,
        "active_scenario_data": active_scenario,
        "active_scenario_name": active_scenario.get("scenario_name"),
        "current_scenario_stage_id": initial_stage_id,
        "collected_product_info": initialized_info,
        "final_response_text_for_tts": response_text,
        "messages": updated_messages,
        "is_final_turn_response": True,
        # 시나리오 연속성 관리
        "scenario_ready_for_continuation": True,
        "scenario_awaiting_user_response": True
    }
    
    updated_state = pydantic_state.merge_update(state_updates)
    return ensure_dict_state(updated_state)