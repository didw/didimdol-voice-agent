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
    
    # 0. pending_modifications가 있는 경우 - 사용자 확인 대기 중
    if state.pending_modifications:
        print(f"[PersonalInfoCorrection] Pending modifications found: {state.pending_modifications}")
        # 사용자가 확인한 경우
        if user_input and any(word in user_input for word in ["네", "예", "맞아", "맞습니다", "좋아", "확인", "그래"]):
            print(f"[PersonalInfoCorrection] User confirmed modification")
            # 수정사항 적용
            updated_info = collected_info.copy()
            updated_info.update(state.pending_modifications)
            print(f"[PersonalInfoCorrection] Updated info: {updated_info}")
            
            # customer_info_check 단계라면 다음 단계로 진행
            if current_stage_id == "customer_info_check":
                # confirm_personal_info를 True로 설정
                updated_info["confirm_personal_info"] = True
                
                # 수정된 내용을 구체적으로 설명
                modification_messages = []
                for field, new_value in state.pending_modifications.items():
                    old_value = collected_info.get(field, "없음")
                    if field == "customer_phone":
                        modification_messages.append(f"연락처를 {old_value}에서 {new_value}(으)로 변경해드렸습니다")
                    elif field == "customer_name":
                        modification_messages.append(f"성함을 {old_value}에서 {new_value}(으)로 변경해드렸습니다")
                    else:
                        display_name = info_modification_agent._get_field_display_name(field)
                        modification_messages.append(f"{display_name}을(를) {old_value}에서 {new_value}(으)로 변경해드렸습니다")
                
                modification_text = ". ".join(modification_messages)
                
                next_stage_id = "ask_lifelong_account"
                next_stage_prompt = active_scenario_data.get("stages", {}).get(next_stage_id, {}).get("prompt", "평생계좌번호로 등록하시겠어요?")
                response_text = f"네, {modification_text}. 다음으로, {next_stage_prompt}"
                
                return state.merge_update({
                    "current_scenario_stage_id": next_stage_id,
                    "collected_product_info": updated_info,
                    "pending_modifications": None,  # 대기 중인 수정사항 클리어
                    "final_response_text_for_tts": response_text,
                    "is_final_turn_response": True,
                    "action_plan": [],
                    "action_plan_struct": [],
                    "router_call_count": 0,
                    "correction_mode": False  # 수정 모드 해제
                })
            else:
                # 다른 단계에서는 수정만 적용
                return state.merge_update({
                    "current_scenario_stage_id": current_stage_id,
                    "collected_product_info": updated_info,
                    "pending_modifications": None,
                    "final_response_text_for_tts": "네, 정보를 수정했습니다. 추가로 수정하실 내용이 있으신가요?",
                    "is_final_turn_response": True,
                    "action_plan": [],
                    "action_plan_struct": [],
                    "router_call_count": 0,
                    "correction_mode": True
                })
        
        # 사용자가 거부한 경우
        elif user_input and any(word in user_input for word in ["아니", "아니요", "아니야", "다시", "틀렸", "잘못"]):
            print(f"[PersonalInfoCorrection] User rejected modification")
            return state.merge_update({
                "current_scenario_stage_id": current_stage_id,
                "pending_modifications": None,  # 대기 중인 수정사항 클리어
                "final_response_text_for_tts": "네, 알겠습니다. 어떤 정보를 수정하고 싶으신지 다시 말씀해주세요.",
                "is_final_turn_response": True,
                "action_plan": [],
                "action_plan_struct": [],
                "router_call_count": 0,
                "correction_mode": True
            })
        else:
            # 사용자가 확인도 거부도 하지 않은 경우 - 다시 질문
            print(f"[PersonalInfoCorrection] User response unclear, asking again")
            return state.merge_update({
                "current_scenario_stage_id": current_stage_id,
                "final_response_text_for_tts": "변경사항을 확인해주세요. 맞으시면 '네'라고 말씀해주시고, 다시 수정하시려면 '아니요'라고 말씀해주세요.",
                "is_final_turn_response": True,
                "action_plan": [],
                "action_plan_struct": [],
                "router_call_count": 0,
                "correction_mode": True
            })
    
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
            
            # 수정된 필드가 있는 경우 - 바로 적용하고 다음 단계로 진행
            if modified_fields and confidence > 0.6:
                # 기존 정보 업데이트
                updated_info = collected_info.copy()
                updated_info.update(modified_fields)
                
                print(f"[PersonalInfoCorrection] Directly applying modifications: {modified_fields}")
                
                # customer_info_check 단계라면 다음 단계로 진행
                if current_stage_id == "customer_info_check":
                    # confirm_personal_info를 True로 설정
                    updated_info["confirm_personal_info"] = True
                    
                    # 수정된 내용을 구체적으로 설명
                    modification_messages = []
                    for field, new_value in modified_fields.items():
                        old_value = collected_info.get(field, "없음")
                        if field == "customer_phone":
                            modification_messages.append(f"연락처를 {old_value}에서 {new_value}(으)로 변경해드렸습니다")
                        elif field == "customer_name":
                            modification_messages.append(f"성함을 {old_value}에서 {new_value}(으)로 변경해드렸습니다")
                        else:
                            display_name = info_modification_agent._get_field_display_name(field)
                            modification_messages.append(f"{display_name}을(를) {old_value}에서 {new_value}(으)로 변경해드렸습니다")
                    
                    modification_text = ". ".join(modification_messages)
                    
                    next_stage_id = "ask_lifelong_account"
                    next_stage_prompt = active_scenario_data.get("stages", {}).get(next_stage_id, {}).get("prompt", "평생계좌번호로 등록하시겠어요?")
                    # 시나리오 프롬프트에 이미 "다음으로"가 있으면 중복 방지
                    if next_stage_prompt.startswith("다음으로"):
                        response_text = f"네, {modification_text}. {next_stage_prompt}"
                    else:
                        response_text = f"네, {modification_text}. 다음으로, {next_stage_prompt}"
                    
                    return state.merge_update({
                        "current_scenario_stage_id": next_stage_id,
                        "collected_product_info": updated_info,
                        "pending_modifications": None,  # 수정사항 클리어
                        "final_response_text_for_tts": response_text,
                        "is_final_turn_response": True,
                        "action_plan": [],
                        "action_plan_struct": [],
                        "router_call_count": 0,
                        "correction_mode": False  # 수정 모드 해제
                    })
                else:
                    # 다른 단계에서의 수정
                    field_names = [info_modification_agent._get_field_display_name(k) for k in modified_fields.keys()]
                    response_text = f"네, {', '.join(field_names)} 정보를 수정했습니다. 추가로 수정하실 내용이 있으신가요?"
                    
                    return state.merge_update({
                        "current_scenario_stage_id": current_stage_id,
                        "collected_product_info": updated_info,
                        "pending_modifications": None,
                        "final_response_text_for_tts": response_text,
                        "is_final_turn_response": True,
                        "action_plan": [],
                        "action_plan_struct": [],
                        "router_call_count": 0,
                        "correction_mode": True
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
    if current_stage_id == "customer_info_check":
        # 자연스러운 응답 생성
        if collected_info:
            # 이미 정보가 있는 경우
            name = collected_info.get("customer_name", "고객님")
            phone = collected_info.get("customer_phone", "")
            correction_message = f"네, 알겠습니다. 현재 성함은 {name}, 연락처는 {phone}로 되어있는데, 어떤 정보를 수정하시겠어요?"
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
            "current_scenario_stage_id": "customer_info_check",  # 기본정보 단계로 이동
            "final_response_text_for_tts": correction_message,
            "is_final_turn_response": True,
            "action_plan": [],
            "action_plan_struct": [],
            "router_call_count": 0,
            "correction_mode": True
        })