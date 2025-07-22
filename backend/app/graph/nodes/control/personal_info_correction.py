# backend/app/graph/nodes/control/personal_info_correction.py
"""
개인정보 수정 요청 처리 노드 - 무한루프 방지를 위한 안전한 처리
"""

from ...state import AgentState
from ...logger import log_node_execution
from ...utils import get_active_scenario_data
from ....agents.info_modification_agent import info_modification_agent


async def personal_info_correction_node(state: AgentState) -> AgentState:
    """
    개인정보 수정 요청을 지능적으로 처리하는 노드
    
    InfoModificationAgent를 사용하여 자연스러운 수정 요청을 파악하고 처리
    """
    log_node_execution("PersonalInfoCorrection", "Processing personal info correction request")
    
    current_stage_id = state.current_scenario_stage_id or "greeting"
    collected_info = state.collected_product_info or {}
    user_input = state.stt_result or ""
    
    # 시나리오 데이터 가져오기
    active_scenario_data = get_active_scenario_data(state.to_dict())
    required_fields = active_scenario_data.get("required_info_fields", []) if active_scenario_data else []
    
    # 1. 사용자가 구체적인 수정 정보를 제공한 경우
    if user_input and len(user_input.strip()) > 0:
        try:
            # InfoModificationAgent로 수정 요청 분석
            modification_result = await info_modification_agent.analyze_modification_request(
                user_input, collected_info, required_fields
            )
            
            modified_fields = modification_result.get("modified_fields", {})
            confidence = modification_result.get("confidence", 0.0)
            reasoning = modification_result.get("reasoning", "")
            suggestions = modification_result.get("suggestions", [])
            
            # 수정된 필드가 있는 경우
            if modified_fields and confidence > 0.6:
                # 기존 정보 업데이트
                updated_info = collected_info.copy()
                updated_info.update(modified_fields)
                
                # 수정 확인 메시지 생성
                if suggestions:
                    confirmation_message = suggestions[0]  # 첫 번째 제안 사용
                else:
                    field_names = [info_modification_agent._get_field_display_name(k) for k in modified_fields.keys()]
                    confirmation_message = f"네, {', '.join(field_names)} 정보를 수정했습니다."
                
                confirmation_message += " 다른 수정할 내용이 있으시면 말씀해주세요. 수정이 완료되셨으면 '확인'이라고 말씀해주세요."
                
                return state.merge_update({
                    "current_scenario_stage_id": current_stage_id,
                    "collected_product_info": updated_info,
                    "final_response_text_for_tts": confirmation_message,
                    "is_final_turn_response": True,
                    "action_plan": [],
                    "action_plan_struct": [],
                    "router_call_count": 0,
                    "correction_mode": True,
                    "modification_reasoning": reasoning  # 디버깅용
                })
            
            # 신뢰도가 낮거나 수정 필드를 찾지 못한 경우
            else:
                clarification_message = "어떤 정보를 수정하고 싶으신지 구체적으로 말씀해주세요. 예를 들어 '이름을 홍길동으로 바꿔주세요' 또는 '뒷번호 0987이야'라고 말씀해주시면 됩니다."
                
                return state.merge_update({
                    "current_scenario_stage_id": current_stage_id,
                    "final_response_text_for_tts": clarification_message,
                    "is_final_turn_response": True,
                    "action_plan": [],
                    "action_plan_struct": [],
                    "router_call_count": 0,
                    "correction_mode": True,
                    "modification_reasoning": reasoning  # 디버깅용
                })
                
        except Exception as e:
            print(f"[PersonalInfoCorrection] Error analyzing modification: {e}")
            # 에러 발생 시 기본 응답
            error_message = "죄송합니다. 수정 요청을 처리하는 중 문제가 발생했습니다. 다시 한번 말씀해주시겠어요?"
            
            return state.merge_update({
                "current_scenario_stage_id": current_stage_id,
                "final_response_text_for_tts": error_message,
                "is_final_turn_response": True,
                "action_plan": [],
                "action_plan_struct": [],
                "router_call_count": 0,
                "correction_mode": True
            })
    
    # 2. 초기 수정 모드 진입 또는 일반적인 수정 요청
    if current_stage_id == "greeting":
        # 자연스러운 응답 생성
        if collected_info:
            # 이미 정보가 있는 경우
            correction_message = "네, 알겠습니다. 기본정보 변경 단계로 도와드리겠습니다. 어떤 부분을 수정하시겠어요?"
        else:
            # 아직 정보가 없는 경우
            correction_message = "네, 기본정보를 다시 확인하겠습니다. 어떤 정보를 수정하고 싶으신가요?"
        
        return state.merge_update({
            "current_scenario_stage_id": current_stage_id,  # 단계 변경 없음
            "final_response_text_for_tts": correction_message,
            "is_final_turn_response": True,
            "action_plan": [],  # 완전히 비우기
            "action_plan_struct": [],
            "router_call_count": 0,  # 라우터 카운트 초기화
            "correction_mode": True  # 수정 모드 활성화
        })
    
    # 3. 다른 단계에서의 수정 요청
    else:
        correction_message = "네, 알겠습니다. 기본정보 변경 단계로 도와드리겠습니다."
        
        return state.merge_update({
            "current_scenario_stage_id": "greeting",  # 기본정보 단계로 이동
            "final_response_text_for_tts": correction_message,
            "is_final_turn_response": True,
            "action_plan": [],
            "action_plan_struct": [],
            "router_call_count": 0,
            "correction_mode": True
        })