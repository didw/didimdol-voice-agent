# backend/app/graph/nodes/control/set_product.py
"""
제품 타입 설정 노드 - 사용자가 선택한 제품에 대한 시나리오를 로드하고 초기화
"""
from langchain_core.messages import AIMessage

from ...state import AgentState
from ...models import ActionModel
from ...utils import ALL_SCENARIOS_DATA
from ...logger import node_log as log_node_execution, log_execution_time
from ..workers.scenario_logic import generate_stage_response, get_default_choice_display


@log_execution_time
async def set_product_type_node(state: AgentState) -> AgentState:
    """
    제품 타입 설정 노드
    - 제품 ID 추출 및 검증
    - 시나리오 데이터 로드
    - 초기 스테이지 설정
    - 기본값 초기화
    """
    action_plan_struct = state.action_plan_struct
    if action_plan_struct:
        product_id = action_plan_struct[0].get("tool_input", {}).get("product_id", "N/A")
        log_node_execution("Set_Product", f"product={product_id}")
    else:
        log_node_execution("Set_Product", "ERROR: no action plan")
    
    if not action_plan_struct:
        err_msg = "Action plan is empty in set_product_type_node"
        log_node_execution("Set_Product", f"ERROR: {err_msg}")
        return state.merge_update({
            "error_message": err_msg,
            "is_final_turn_response": True
        })
    
    # 현재 액션에 맞는 구조 찾기
    current_action_model = ActionModel.model_validate(action_plan_struct[0])
    
    new_product_type = current_action_model.tool_input.get("product_id")
    
    if not new_product_type:
        err_msg = f"product_id not found in action: {current_action_model.model_dump()}"
        log_node_execution("Set_Product", f"ERROR: {err_msg}")
        return state.merge_update({
            "error_message": err_msg,
            "is_final_turn_response": True
        })

    active_scenario = ALL_SCENARIOS_DATA.get(new_product_type)
    
    if not active_scenario:
        err_msg = f"Failed to load scenario for product type: {new_product_type}"
        log_node_execution("Set_Product", f"ERROR: {err_msg}")
        return state.merge_update({
            "error_message": err_msg,
            "is_final_turn_response": True
        })
        
    log_node_execution("Set_Product", f"loaded scenario: {active_scenario.get('scenario_name')}")

    initial_stage_id = active_scenario.get("initial_stage_id")
    
    # dynamic_prompt 처리
    initial_stage_info = active_scenario.get("stages", {}).get(initial_stage_id, {})
    if initial_stage_info.get("dynamic_prompt"):
        default_choice = get_default_choice_display(initial_stage_info)
        response_text = initial_stage_info["dynamic_prompt"].replace("{default_choice}", default_choice)
    else:
        response_text = initial_stage_info.get("prompt", "무엇을 도와드릴까요?")

    log_node_execution("Set_Product", f"response: '{response_text[:70]}...'")

    updated_messages = list(state.messages) + [AIMessage(content=response_text)]
    
    # Default 값 초기화 - 기존 정보를 유지하면서 기본정보만 추가
    from ....api.V1.chat_utils import initialize_default_values
    
    # 기존 collected_product_info 유지
    existing_info = state.collected_product_info.copy()
    
    temp_state = {
        **state.to_dict(),
        "current_product_type": new_product_type, 
        "active_scenario_data": active_scenario,
        "collected_product_info": existing_info  # 기존 정보 전달
    }
    initialized_info = initialize_default_values(temp_state)
    
    # 기존 정보와 새로운 기본값 병합 (기존 정보 우선)
    merged_info = {**initialized_info, **existing_info}
    log_node_execution("Set_Product", f"merged info (existing + defaults): {merged_info}")
    
    # 시나리오 연속성을 위한 상태 설정
    log_node_execution("Set_Product", f"scenario ready: {active_scenario.get('scenario_name')}")
    
    # stage_response_data 생성 (v3 시나리오용)
    stage_response_data = None
    if initial_stage_info.get("response_type"):
        stage_response_data = generate_stage_response(initial_stage_info, merged_info, active_scenario)
    
    state_updates = {
        "current_product_type": new_product_type,
        "active_scenario_data": active_scenario,
        "active_scenario_name": active_scenario.get("scenario_name"),
        "current_scenario_stage_id": initial_stage_id,
        "collected_product_info": merged_info,  # 기존 정보 + 새 기본값
        "final_response_text_for_tts": response_text,
        "messages": updated_messages,
        "is_final_turn_response": True,
        # 시나리오 연속성 관리
        "scenario_ready_for_continuation": True,
        "scenario_awaiting_user_response": True,
        # v3 시나리오용 stage_response_data
        "stage_response_data": stage_response_data
    }
    
    updated_state = state.merge_update(state_updates)
    return updated_state