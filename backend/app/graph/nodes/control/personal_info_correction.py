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
    
    print(f"[PersonalInfoCorrection] ===== START =====")
    print(f"[PersonalInfoCorrection] User input: '{user_input}'")
    print(f"[PersonalInfoCorrection] Current stage: {current_stage_id}")
    print(f"[PersonalInfoCorrection] Pending modifications: {state.pending_modifications}")
    print(f"[PersonalInfoCorrection] Waiting for additional modifications: {state.waiting_for_additional_modifications}")
    print(f"[PersonalInfoCorrection] Correction mode: {state.correction_mode}")
    print(f"[PersonalInfoCorrection] Current modification context: {state.current_modification_context}")
    
    # 시나리오 데이터 가져오기
    active_scenario_data = get_active_scenario_data(state.to_dict())
    required_fields = active_scenario_data.get("required_info_fields", []) if active_scenario_data else []
    
    # customer_info_check 단계가 아닌데 수정 관련 플래그가 남아있으면 정리
    if current_stage_id != "customer_info_check" and (state.waiting_for_additional_modifications or state.pending_modifications):
        print(f"[PersonalInfoCorrection] Cleaning up modification flags - current stage: {current_stage_id}")
        return state.merge_update({
            "waiting_for_additional_modifications": None,
            "pending_modifications": None,
            "original_values_before_modification": None,
            "correction_mode": False,
            "action_plan": ["invoke_scenario_agent"],
            "action_plan_struct": [{"action": "invoke_scenario_agent", "reason": "Resume normal scenario flow"}],
            "router_call_count": 0,
            "is_final_turn_response": False
        })
    
    # 0-1. 추가 수정사항 대기 중인 경우
    if state.waiting_for_additional_modifications and current_stage_id == "customer_info_check":
        print(f"[PersonalInfoCorrection] Waiting for additional modifications, user input: '{user_input}'")
        
        # pending_modifications가 있으면서 추가 수정사항을 대기 중인 특수한 경우
        # 사용자가 수정 확인 응답 대신 다른 수정 요청을 한 경우
        if state.pending_modifications and user_input and any(word in user_input for word in ["틀", "다르", "수정", "변경", "바꿔", "바꿀"]):
            print(f"[PersonalInfoCorrection] User requesting additional modification while pending modifications exist")
            # pending_modifications를 먼저 적용하고, 새로운 수정 요청을 처리하도록 아래 로직으로 진행
            # 기존 pending_modifications 적용
            from copy import deepcopy
            updated_info = deepcopy(collected_info)
            updated_info.update(state.pending_modifications)
            collected_info = updated_info
            # 플래그들을 리셋하고 새로운 수정 요청 처리로 진행
            state = state.merge_update({
                "collected_product_info": collected_info,
                "pending_modifications": None,
                "waiting_for_additional_modifications": None,
                "correction_mode": True
            })
            # 아래의 수정 로직으로 계속 진행
        
        # 사용자가 "아니요"라고 답한 경우 - 다음 단계로 진행
        # "잘못됐어", "틀렸어" 등은 수정 요청이므로 제외
        elif user_input and (
            any(word in user_input for word in ["아니", "아니요", "아니야", "없어", "없습니다", "괜찮", "충분"]) or
            (user_input.strip() == "됐어" or user_input.strip() == "됐습니다")  # 단독으로 "됐어"만 있는 경우
        ) and not any(word in user_input for word in ["잘못", "틀렸", "다르", "수정", "변경", "바꿔", "바꿀"]):
            print(f"[PersonalInfoCorrection] User said no additional modifications needed, proceeding to next stage")
            
            # confirm_personal_info를 True로 설정하여 다음 단계로
            collected_info["confirm_personal_info"] = True
            
            # 시나리오 JSON에서 정의된 다음 단계로 이동
            current_stage_info = active_scenario_data.get("stages", {}).get("customer_info_check", {})
            transitions = current_stage_info.get("transitions", [])
            default_next = current_stage_info.get("default_next_stage_id", "ask_security_medium")
            
            # 긍정 응답에 해당하는 transition 찾기
            next_stage_id = default_next
            for transition in transitions:
                if "맞다고 확인" in transition.get("condition_description", ""):
                    next_stage_id = transition.get("next_stage_id", default_next)
                    break
            
            # active_scenario_data가 없을 때를 대비한 안전한 처리
            if active_scenario_data and "stages" in active_scenario_data:
                next_stage_prompt = active_scenario_data.get("stages", {}).get(next_stage_id, {}).get("prompt", "")
            else:
                next_stage_prompt = ""
            
            # 시나리오 프롬프트에 이미 "다음으로"가 있으면 중복 방지
            if next_stage_prompt.startswith("다음으로"):
                response_text = f"네, {next_stage_prompt}"
            else:
                response_text = f"네, 다음으로, {next_stage_prompt}"
            
            return state.merge_update({
                "current_scenario_stage_id": next_stage_id,
                "collected_product_info": collected_info,
                "waiting_for_additional_modifications": None,  # 플래그 클리어
                "final_response_text_for_tts": response_text,
                "is_final_turn_response": True,
                "action_plan": [],
                "action_plan_struct": [],
                "router_call_count": 0,
                "correction_mode": False  # 수정 모드 해제
            })
        
        # 사용자가 추가 수정사항을 말한 경우 - 아래의 수정 로직으로 진행
        elif user_input and any(word in user_input for word in ["틀", "다르", "수정", "변경", "바꿔", "바꿀"]):
            print(f"[PersonalInfoCorrection] User requesting additional modification: '{user_input}'")
            # 추가 수정사항 대기 상태를 해제하고 새로운 수정 요청을 처리
            state = state.merge_update({
                "waiting_for_additional_modifications": None,
                "correction_mode": True
            })
            # 아래의 수정 로직으로 계속 진행
        # (기존 로직으로 계속 진행)
    
    # 0-2. pending_modifications가 있는 경우 - 사용자 확인 대기 중
    if state.pending_modifications:
        print(f"[PersonalInfoCorrection] Pending modifications found: {state.pending_modifications}")
        # 사용자가 확인한 경우 - 더 정확한 매칭을 위해 수정 키워드 제외
        confirmation_words = ["네", "예", "맞아", "맞습니다", "좋아", "확인", "그래"]
        modification_words = ["바꿔", "바꾸", "수정", "변경", "틀렸", "다르", "잘못"]
        
        # 확인 키워드가 있지만 수정 키워드가 없는 경우만 확인으로 처리
        has_confirmation = any(word in user_input for word in confirmation_words)
        has_modification = any(word in user_input for word in modification_words)
        
        # 단독으로 "어"나 "응"이 있는 경우도 확인으로 처리 (하지만 다른 단어와 함께 있으면 제외)
        standalone_confirmation = (user_input.strip() in ["어", "응"]) or (len(user_input.strip()) <= 2 and any(word == user_input.strip() for word in ["네", "예"]))
        
        if user_input and ((has_confirmation and not has_modification) or standalone_confirmation):
            print(f"[PersonalInfoCorrection] ✅ User confirmed modification")
            print(f"[PersonalInfoCorrection] ✅ BEFORE - collected_info: {collected_info}")
            print(f"[PersonalInfoCorrection] ✅ BEFORE - pending_modifications: {state.pending_modifications}")
            
            # 수정사항 적용
            print(f"[PersonalInfoCorrection] BEFORE update - collected_info: {collected_info}")
            print(f"[PersonalInfoCorrection] pending_modifications: {state.pending_modifications}")
            from copy import deepcopy
            updated_info = deepcopy(collected_info)
            updated_info.update(state.pending_modifications)
            print(f"[PersonalInfoCorrection] AFTER update - updated_info: {updated_info}")
            
            # customer_info_check 단계라면 추가 수정사항을 물어봄
            if current_stage_id == "customer_info_check":
                # 수정사항 확인 메시지
                modification_text = ""
                for field, new_value in state.pending_modifications.items():
                    if field == "customer_phone":
                        modification_text = "연락처를 변경하겠습니다"
                    elif field == "customer_name":
                        modification_text = "성함을 변경하겠습니다"
                    else:
                        display_name = info_modification_agent._get_field_display_name(field)
                        modification_text = f"{display_name}을 변경하겠습니다"
                
                response_text = f"{modification_text}. 다른 수정사항 있으실까요?"
                
                print(f"[PersonalInfoCorrection] About to return with updated_info: {updated_info}")
                print(f"[PersonalInfoCorrection] State before merge_update - collected_product_info: {state.collected_product_info}")
                # 수정 컨텍스트 정리
                if "_last_modification_context" in updated_info:
                    del updated_info["_last_modification_context"]
                
                result = state.merge_update({
                    "current_scenario_stage_id": current_stage_id,  # 같은 단계 유지
                    "collected_product_info": updated_info,
                    "pending_modifications": None,  # 대기 중인 수정사항 클리어
                    "original_values_before_modification": None,  # 원본 값 정보도 클리어
                    "final_response_text_for_tts": response_text,
                    "is_final_turn_response": True,
                    "action_plan": [],  # 이번 턴은 종료
                    "action_plan_struct": [],
                    "router_call_count": 0,
                    "correction_mode": False,  # 수정 모드 일시 해제 (다음 턴에서 다시 활성화)
                    "waiting_for_additional_modifications": True,  # 추가 수정사항 대기 플래그
                    "current_modification_context": None  # 수정 컨텍스트 클리어
                })
                print(f"[PersonalInfoCorrection] After merge_update - result.collected_product_info: {result.collected_product_info}")
                print(f"[PersonalInfoCorrection] ✅ Successfully applied modifications and returning state")
                print(f"[PersonalInfoCorrection] ✅ RETURNING final_response_text_for_tts: '{result.final_response_text_for_tts}'")
                print(f"[PersonalInfoCorrection] ✅ RETURNING is_final_turn_response: {result.is_final_turn_response}")
                print(f"[PersonalInfoCorrection] ===== END =====")
                return result
            else:
                # 다른 단계에서는 수정만 적용
                print(f"[PersonalInfoCorrection] Non-customer_info_check stage - applying modifications")
                print(f"[PersonalInfoCorrection] updated_info: {updated_info}")
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
        
        # 사용자가 거부한 경우 - 원래 값으로 롤백
        elif user_input and any(word in user_input for word in ["아니", "아니요", "아니야", "다시", "틀렸", "잘못"]):
            print(f"[PersonalInfoCorrection] User rejected modification, rolling back")
            
            # 원본 값으로 롤백
            from copy import deepcopy
            rolled_back_info = deepcopy(collected_info)
            
            # original_values_before_modification에 저장된 원본 값으로 복원
            if state.original_values_before_modification:
                rolled_back_info.update(state.original_values_before_modification)
                print(f"[PersonalInfoCorrection] Rolled back to original values: {state.original_values_before_modification}")
                print(f"[PersonalInfoCorrection] After rollback: {rolled_back_info}")
            
            return state.merge_update({
                "current_scenario_stage_id": current_stage_id,
                "collected_product_info": rolled_back_info,  # 원본 값으로 롤백
                "pending_modifications": None,  # 대기 중인 수정사항 클리어
                "original_values_before_modification": None,  # 원본 값 정보도 클리어
                "final_response_text_for_tts": "네, 알겠습니다. 어떤 정보를 수정하고 싶으신지 다시 말씀해주세요.",
                "is_final_turn_response": True,
                "action_plan": [],
                "action_plan_struct": [],
                "router_call_count": 0,
                "correction_mode": True
            })
        else:
            # 사용자가 다른 수정 요청을 한 경우 확인
            if user_input and any(word in user_input for word in ["틀", "다르", "수정", "변경", "바꿔", "바꿀"]):
                print(f"[PersonalInfoCorrection] User requesting different modification, applying pending changes first")
                # 기존 pending_modifications를 먼저 적용
                from copy import deepcopy
                updated_info = deepcopy(collected_info)
                updated_info.update(state.pending_modifications)
                
                # state를 업데이트하고 새로운 수정 요청 처리로 진행
                state = state.merge_update({
                    "collected_product_info": updated_info,
                    "pending_modifications": None,
                    "original_values_before_modification": None,
                    "correction_mode": True
                })
                collected_info = updated_info
                # 아래의 수정 로직으로 계속 진행
            # 수정 컨텍스트가 있고 사용자가 값을 제공한 경우
            elif state.current_modification_context and user_input and user_input.strip():
                print(f"[PersonalInfoCorrection] User providing value for {state.current_modification_context}: '{user_input}'")
                # 기존 pending_modifications를 먼저 적용
                from copy import deepcopy
                updated_info = deepcopy(collected_info)
                updated_info.update(state.pending_modifications)
                
                # 수정 컨텍스트를 사용하여 새로운 수정 요청 처리
                state = state.merge_update({
                    "collected_product_info": updated_info,
                    "pending_modifications": None,
                    "waiting_for_additional_modifications": None,
                    "correction_mode": True
                })
                collected_info = updated_info
                # 아래의 수정 로직으로 계속 진행하여 새로운 값 처리
            else:
                # 사용자가 수정 가능한 정보를 제공한 경우 확인
                import re
                address_pattern = re.compile(r'([가-힣]+(?:동|로|길)\s*\d+)', re.IGNORECASE)
                email_pattern = re.compile(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', re.IGNORECASE)
                phone_pattern = re.compile(r'(\d{3,4})', re.IGNORECASE)
                name_pattern = re.compile(r'([가-힣]{2,4})', re.IGNORECASE)
                
                # 수정 요청 키워드 체크
                has_modification_request = any(keyword in user_input for keyword in ["바꿔", "바꾸", "수정", "변경", "틀렸", "다르", "잘못"])
                # 필드 언급 체크
                has_field_mention = any(field in user_input for field in ["이메일", "메일", "전화", "번호", "이름", "성함", "주소"])
                # 대조 표현 체크 (A에서 B로, A를 B로)
                contrast_pattern = re.compile(r'([가-힣]+(?:동|로|길))[에서|을|를]\s*([가-힣]+(?:동|로|길))(?:으로|로)', re.IGNORECASE)
                has_contrast_expression = contrast_pattern.search(user_input)
                
                if (address_pattern.search(user_input) or 
                    email_pattern.search(user_input) or 
                    (phone_pattern.search(user_input) and any(keyword in user_input for keyword in ["가운데", "뒷번호", "뒤", "마지막", "뒷자리", "끝번호"])) or
                    (name_pattern.search(user_input) and any(keyword in user_input for keyword in ["이름", "성함"])) or
                    (has_modification_request and has_field_mention) or
                    has_contrast_expression):
                    print(f"[PersonalInfoCorrection] User providing new modification value, treating as new modification")
                    # 기존 pending_modifications를 먼저 취소하고 새로운 수정 요청 처리
                    state = state.merge_update({
                        "pending_modifications": None,
                        "original_values_before_modification": None,
                        "correction_mode": True
                    })
                    # 아래의 수정 로직으로 계속 진행
                else:
                    # 그 외의 경우 - 다시 질문
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
            # 이전 대화 컨텍스트 확인 - 특정 필드에 대한 재질의가 있었는지
            previous_response = state.final_response_text_for_tts or ""
            inferred_context = None
            
            # 이전 응답에서 어떤 필드를 물어봤는지 추론
            if "직장주소를 어떻게 수정해드릴까요?" in previous_response:
                inferred_context = "work_address"
                print(f"[PersonalInfoCorrection] Inferred context from previous response: work_address")
            elif "집주소를 어떻게 수정해드릴까요?" in previous_response:
                inferred_context = "address"
                print(f"[PersonalInfoCorrection] Inferred context from previous response: address")
            elif "전화번호를 어떻게 수정해드릴까요?" in previous_response:
                inferred_context = "phone_number"
                print(f"[PersonalInfoCorrection] Inferred context from previous response: phone_number")
            
            # 추가: pending_modifications에서 컨텍스트 추론
            if not inferred_context and state.pending_modifications:
                # pending_modifications에 work_address가 있었다면
                if "work_address" in state.pending_modifications:
                    inferred_context = "work_address"
                    print(f"[PersonalInfoCorrection] Inferred context from pending modifications: work_address")
                elif "address" in state.pending_modifications:
                    inferred_context = "address"
                    print(f"[PersonalInfoCorrection] Inferred context from pending modifications: address")
            
            # collected_info에서 마지막 수정 컨텍스트 확인
            if not inferred_context and collected_info.get("_last_modification_context"):
                inferred_context = collected_info.get("_last_modification_context")
                print(f"[PersonalInfoCorrection] Inferred context from collected_info: {inferred_context}")
            
            # 가장 강력한 추론: 사용자 입력에서 직접 확인
            if not inferred_context:
                # 이전 턴의 사용자 입력을 시뮬레이션 (로그에서 확인)
                if state.correction_mode and ("동" in user_input or "로" in user_input or "길" in user_input):
                    # 주소 형태의 입력이고 correction_mode인 경우
                    # 기본적으로 직장주소로 추론 (대부분의 케이스에서 집주소는 이미 있고 직장주소를 변경하려는 경우가 많음)
                    print(f"[PersonalInfoCorrection] WARNING: No context found, using heuristic for address field")
                    if "직장" in str(state.messages[-2:]) if state.messages else False:
                        inferred_context = "work_address"
                        print(f"[PersonalInfoCorrection] Heuristic: found '직장' in recent messages")
            
            # 실제 컨텍스트가 없으면 추론된 컨텍스트 사용
            effective_context = state.current_modification_context or inferred_context
            print(f"[PersonalInfoCorrection] Effective modification context: {effective_context}")
            
            # collected_info가 비어있거나 기본값이 없는 경우, 시나리오 기본값 사용
            if not collected_info or all(k == "limit_account_agreement" for k in collected_info.keys()):
                # customer_info_check 단계에서는 기본 개인정보 필드만 로딩
                if current_stage_id == "customer_info_check":
                    basic_info_fields = ["customer_name", "english_name", "resident_number", "phone_number", "email", "address", "work_address"]
                    for field in required_fields:
                        field_key = field.get("key")
                        default_value = field.get("default")
                        if field_key and default_value and field_key in basic_info_fields and field_key not in collected_info:
                            collected_info[field_key] = default_value
                    print(f"[PersonalInfoCorrection] Loaded basic info default values only")
                else:
                    # 다른 단계에서는 모든 기본값 로딩
                    for field in required_fields:
                        field_key = field.get("key")
                        default_value = field.get("default")
                        if field_key and default_value and field_key not in collected_info:
                            collected_info[field_key] = default_value
                    print(f"[PersonalInfoCorrection] Loaded default values from scenario")
            
            # InfoModificationAgent로 수정 요청 분석
            print(f"[PersonalInfoCorrection] Analyzing modification request: '{user_input}'")
            print(f"[PersonalInfoCorrection] Current collected_info: {collected_info}")
            
            modification_result = await info_modification_agent.analyze_modification_request(
                user_input, collected_info, required_fields, effective_context, state.correction_mode
            )
            
            print(f"[PersonalInfoCorrection] Modification result: {modification_result}")
            
            modified_fields = modification_result.get("modified_fields", {})
            confidence = modification_result.get("confidence", 0.0)
            reasoning = modification_result.get("reasoning", "")
            suggestions = modification_result.get("suggestions", [])
            
            # 수정된 필드가 있는 경우 - 사용자 확인을 받은 후 적용
            if modified_fields and confidence > 0.6:
                print(f"[PersonalInfoCorrection] Setting pending modifications for user confirmation: {modified_fields}")
                
                # null 값이 있는지 확인 (수정하려는 필드는 알지만 새 값이 없는 경우)
                fields_needing_value = []
                fields_with_value = {}
                
                for field, new_value in modified_fields.items():
                    if new_value is None or new_value == "null" or new_value == "틀려" or new_value == "다르다":
                        fields_needing_value.append(field)
                    else:
                        fields_with_value[field] = new_value
                
                # 새 값이 없는 필드가 있는 경우 - 값을 물어봄
                print(f"[PersonalInfoCorrection] fields_needing_value: {fields_needing_value}")
                print(f"[PersonalInfoCorrection] fields_with_value: {fields_with_value}")
                if fields_needing_value:
                    clarification_messages = []
                    for field in fields_needing_value:
                        if field == "english_name":
                            clarification_messages.append("영문이름을 어떻게 수정해드릴까요?")
                        elif field == "customer_name":
                            clarification_messages.append("성함을 어떻게 수정해드릴까요?")
                        elif field == "phone_number":
                            clarification_messages.append("전화번호를 어떻게 수정해드릴까요?")
                        elif field == "address":
                            clarification_messages.append("집주소를 어떻게 수정해드릴까요?")
                        elif field == "work_address":
                            clarification_messages.append("직장주소를 어떻게 수정해드릴까요?")
                        elif field == "email":
                            clarification_messages.append("이메일을 어떻게 수정해드릴까요?")
                        else:
                            display_name = info_modification_agent._get_field_display_name(field)
                            clarification_messages.append(f"{display_name}을(를) 어떻게 수정해드릴까요?")
                    
                    clarification_message = " ".join(clarification_messages)
                    
                    # 수정 컨텍스트 설정 (첫 번째 필드)
                    modification_context = fields_needing_value[0] if fields_needing_value else None
                    print(f"[PersonalInfoCorrection] Setting modification_context to: {modification_context}")
                    
                    # 수정 컨텍스트를 collected_info에도 저장 (상태 유지를 위해)
                    if modification_context:
                        collected_info["_last_modification_context"] = modification_context
                    
                    return state.merge_update({
                        "current_scenario_stage_id": current_stage_id,
                        "collected_product_info": collected_info,  # 수정된 collected_info 반영
                        "final_response_text_for_tts": clarification_message,
                        "is_final_turn_response": True,
                        "action_plan": [],
                        "action_plan_struct": [],
                        "router_call_count": 0,
                        "correction_mode": True,
                        "modification_reasoning": reasoning,
                        "current_modification_context": modification_context
                    })
                
                # 모든 필드에 새 값이 있는 경우에만 확인 메시지 생성
                if fields_with_value:
                    # 수정 확인 메시지 생성
                    modification_messages = []
                    for field, new_value in fields_with_value.items():
                        old_value = collected_info.get(field, "없음")
                        if field == "phone_number":
                            modification_messages.append(f"전화번호를 {old_value}에서 {new_value}(으)로 변경")
                        elif field == "customer_name":
                            modification_messages.append(f"성함을 {old_value}에서 {new_value}(으)로 변경")
                        elif field == "address":
                            # 주소 변경 시 기존 주소와 비교하여 변경 부분만 표시
                            if old_value != "없음" and old_value:
                                # 기존 주소가 있는 경우
                                modification_messages.append(f"집주소를 {new_value}(으)로 변경")
                            else:
                                modification_messages.append(f"집주소를 {new_value}(으)로 설정")
                        elif field == "work_address":
                            if old_value != "없음" and old_value:
                                modification_messages.append(f"직장주소를 {new_value}(으)로 변경")
                            else:
                                modification_messages.append(f"직장주소를 {new_value}(으)로 설정")
                        elif field == "email":
                            modification_messages.append(f"이메일을 {old_value}에서 {new_value}(으)로 변경")
                        elif field == "english_name":
                            modification_messages.append(f"영문이름을 {old_value}에서 {new_value}(으)로 변경")
                        elif field == "resident_number":
                            modification_messages.append(f"주민등록번호를 {old_value}에서 {new_value}(으)로 변경")
                        else:
                            display_name = info_modification_agent._get_field_display_name(field)
                            modification_messages.append(f"{display_name}을(를) {old_value}에서 {new_value}(으)로 변경")
                    
                    modification_text = ". ".join(modification_messages)
                    confirmation_message = f"네, {modification_text} 맞으실까요?"
                
                    # 수정된 정보를 즉시 적용하면서 사용자 확인 요청
                    # fields_with_value만 collected_info에 즉시 반영
                    from copy import deepcopy
                    updated_info_for_confirmation = deepcopy(collected_info)
                    
                    # 원본 값 저장 (롤백을 위해)
                    original_values = {}
                    for field in fields_with_value.keys():
                        if field in collected_info:
                            original_values[field] = collected_info[field]
                    
                    # 수정사항 적용 (fields_with_value만)
                    updated_info_for_confirmation.update(fields_with_value)
                
                    print(f"[PersonalInfoCorrection] Immediately applying modifications to collected_product_info")
                    print(f"[PersonalInfoCorrection] Before: {collected_info}")
                    print(f"[PersonalInfoCorrection] Modified fields: {fields_with_value}")
                    print(f"[PersonalInfoCorrection] Original values saved: {original_values}")
                    print(f"[PersonalInfoCorrection] After: {updated_info_for_confirmation}")
                    
                    return state.merge_update({
                        "current_scenario_stage_id": current_stage_id,
                        "collected_product_info": updated_info_for_confirmation,  # 수정사항 즉시 반영
                        "pending_modifications": fields_with_value,  # 롤백을 위한 대기 중인 수정사항
                        "original_values_before_modification": original_values,  # 원본 값 저장
                        "final_response_text_for_tts": confirmation_message,
                        "is_final_turn_response": True,
                        "action_plan": [],
                        "action_plan_struct": [],
                        "router_call_count": 0,
                        "correction_mode": True,  # 수정 모드 유지
                        "modification_reasoning": reasoning
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