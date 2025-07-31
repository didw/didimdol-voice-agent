# backend/app/graph/nodes/workers/scenario_logic.py
"""
시나리오 로직 처리 노드 - 복잡한 정보 수집 및 시나리오 진행 관리
"""
import json
from typing import Dict, List, Optional, Any
from langchain_core.messages import HumanMessage

from ...state import AgentState, ScenarioAgentOutput
from ...utils import get_active_scenario_data, ALL_PROMPTS, format_transitions_for_prompt
from ...chains import json_llm
from ...models import next_stage_decision_parser
from ...logger import log_node_execution
from ...simple_scenario_engine import SimpleScenarioEngine
from ....agents.entity_agent import entity_agent
from ....agents.internet_banking_agent import internet_banking_agent
from ....agents.check_card_agent import check_card_agent
from .scenario_helpers import (
    check_required_info_completion,
    get_next_missing_info_group_stage,
    generate_group_specific_prompt,
    check_internet_banking_completion,
    generate_internet_banking_prompt,
    check_check_card_completion,
    generate_check_card_prompt,
    replace_template_variables
)
from ...validators import FIELD_VALIDATORS, get_validator_for_field


def get_expected_field_keys(stage_info: Dict[str, Any]) -> List[str]:
    """
    V3 시나리오 호환: fields_to_collect 또는 expected_info_key에서 필드 키 추출
    """
    # V3 시나리오: fields_to_collect 사용
    if stage_info.get("fields_to_collect"):
        return stage_info["fields_to_collect"]
    
    # 기존 시나리오: expected_info_key 사용
    expected_key = stage_info.get("expected_info_key")
    if expected_key:
        return [expected_key]
    
    return []

async def process_partial_response(
    stage_id: str,
    user_input: str,
    required_fields: List[Dict[str, Any]],
    collected_info: Dict[str, Any],
    field_validators: Dict[str, Any] = None,
    current_stage_info: Dict[str, Any] = None
) -> Dict[str, Any]:
    """부분 응답 처리 및 유효성 검증 - TRD 4.4 구현"""
    
    if field_validators is None:
        field_validators = FIELD_VALIDATORS
    
    # 1. Entity Agent를 통한 개별 필드 추출 (유사도 매칭 포함)
    extracted_entities = {}
    similarity_messages = []
    if user_input:
        try:
            # 현재 스테이지 정보가 있으면 관련 필드만 필터링
            fields_to_extract = required_fields
            if current_stage_info:
                fields_to_extract = get_stage_relevant_fields(current_stage_info, required_fields, stage_id)
                print(f"[process_partial_response] Filtered fields for stage {stage_id}: {[f['key'] for f in fields_to_extract]}")
            
            extraction_result = await entity_agent.extract_entities_with_similarity(user_input, fields_to_extract)
            extracted_entities = extraction_result.get("extracted_entities", {})
            similarity_messages = extraction_result.get("similarity_messages", [])
        except Exception as e:
            print(f"[ERROR] Entity extraction error in partial response: {e}")
    
    # 2. 유효성 검증
    validation_results = {}
    for field in required_fields:
        field_key = field['key']
        value = extracted_entities.get(field_key) or collected_info.get(field_key)
        
        if value is not None:
            validator = get_validator_for_field(field_key, field)
            if validator:
                is_valid, error_message = validator.validate(value)
                validation_results[field_key] = {
                    "is_valid": is_valid,
                    "error_message": error_message,
                    "value": value
                }
            else:
                # 검증기가 없으면 유효한 것으로 간주
                validation_results[field_key] = {
                    "is_valid": True,
                    "error_message": None,
                    "value": value
                }
    
    # 3. 유효한 값만 collected_info에 저장
    valid_fields = []
    invalid_fields = []
    for field_key, result in validation_results.items():
        if result["is_valid"]:
            collected_info[field_key] = result["value"]
            valid_fields.append(field_key)
        else:
            invalid_fields.append({
                "field": field_key,
                "error": result["error_message"]
            })
    
    # 4. 미수집 필드 확인
    missing_fields = [
        field for field in required_fields 
        if field['key'] not in collected_info
    ]
    
    # 5. 재질문 생성
    response_text = None
    if invalid_fields or missing_fields or similarity_messages:
        response_text = generate_re_prompt(
            valid_fields, 
            invalid_fields, 
            missing_fields,
            required_fields,
            similarity_messages
        )
    
    return {
        "collected_info": collected_info,
        "valid_fields": valid_fields,
        "invalid_fields": invalid_fields,
        "missing_fields": missing_fields,
        "response_text": response_text,
        "is_complete": not (invalid_fields or missing_fields),
        "similarity_messages": similarity_messages
    }


def generate_re_prompt(
    valid_fields: List[str],
    invalid_fields: List[Dict[str, str]],
    missing_fields: List[Dict[str, Any]],
    all_fields: List[Dict[str, Any]],
    similarity_messages: List[str] = None
) -> str:
    """재질문 프롬프트 생성"""
    
    response_parts = []
    
    # 필드 정보를 딕셔너리로 변환
    field_info_map = {field['key']: field for field in all_fields}
    
    # 유효한 필드에 대한 확인 메시지
    if valid_fields:
        field_names = []
        for field_key in valid_fields:
            field_info = field_info_map.get(field_key, {})
            display_name = field_info.get('display_name', field_key)
            field_names.append(display_name)
        
        response_parts.append(f"{', '.join(field_names)}은(는) 확인했습니다.")
    
    # 유사도 매칭 메시지 추가
    if similarity_messages:
        response_parts.extend(similarity_messages)
    
    # 유효하지 않은 필드에 대한 재질문
    if invalid_fields:
        for field_info in invalid_fields:
            response_parts.append(field_info["error"])
    
    # 누락된 필드에 대한 질문
    if missing_fields:
        field_names = []
        for field in missing_fields:
            display_name = field.get('display_name', field['key'])
            field_names.append(display_name)
        
        response_parts.append(f"{', '.join(field_names)}도 함께 말씀해주세요.")
    
    return " ".join(response_parts)


async def process_scenario_logic_node(state: AgentState) -> AgentState:
    """
    시나리오 로직 처리 노드
    """
    current_stage_id = state.current_scenario_stage_id or "N/A"
    scenario_name = state.active_scenario_name or "N/A"
    log_node_execution("Scenario_Flow", f"scenario={scenario_name}, stage={current_stage_id}")
    
    
    active_scenario_data = get_active_scenario_data(state.to_dict())
    current_stage_id = state.current_scenario_stage_id
    
    # 스테이지 ID가 없는 경우 초기 스테이지로 설정
    if not current_stage_id:
        current_stage_id = active_scenario_data.get("initial_stage_id", "greeting")
    
    current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
    collected_info = state.collected_product_info.copy()
    
    scenario_output = state.scenario_agent_output
    user_input = state.stt_result or ""
    
    # 개선된 다중 정보 수집 처리
    if current_stage_info.get("collect_multiple_info"):
        result = await process_multiple_info_collection(state, active_scenario_data, current_stage_id, current_stage_info, collected_info, scenario_output, user_input)
        return result
    
    # 기존 단일 정보 수집 처리
    result = await process_single_info_collection(state, active_scenario_data, current_stage_id, current_stage_info, collected_info, scenario_output, user_input)
    return result


def get_stage_relevant_fields(current_stage_info: Dict, required_fields: List[Dict], current_stage_id: str) -> List[Dict]:
    """현재 스테이지에서 관련된 필드만 필터링"""
    # 기본적으로 expected_info_key 필드만 반환
    expected_key = current_stage_info.get("expected_info_key")
    
    # 특별한 스테이지별 처리
    if current_stage_id == "customer_info_check":
        # 고객정보 확인 단계 - modifiable_fields에 정의된 기본 개인정보만
        modifiable_fields = current_stage_info.get("modifiable_fields", [])
        if modifiable_fields:
            return [f for f in required_fields if f['key'] in modifiable_fields]
        # fallback: 기본 개인정보 필드만
        basic_info_fields = ["customer_name", "english_name", "resident_number", "phone_number", "email", "address", "work_address"]
        return [f for f in required_fields if f['key'] in basic_info_fields]
    elif current_stage_id == "ask_transfer_limit":
        # 이체한도 관련 필드만
        return [f for f in required_fields if f['key'] in ["transfer_limit_per_time", "transfer_limit_per_day"]]
    elif current_stage_id == "ask_notification_settings":
        # 알림 설정 관련 필드만
        return [f for f in required_fields if f['key'] in ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]]
    elif expected_key:
        # 기본적으로 expected_info_key에 해당하는 필드만
        return [f for f in required_fields if f['key'] == expected_key]
    else:
        # visible_groups가 있는 경우 해당 그룹의 필드들만
        visible_groups = current_stage_info.get("visible_groups", [])
        if visible_groups:
            stage_fields = []
            for field in required_fields:
                field_group = field.get("group")
                if field_group in visible_groups:
                    stage_fields.append(field)
            return stage_fields
        # 그 외의 경우 모든 필드 (기존 동작)
        return required_fields


async def process_multiple_info_collection(state: AgentState, active_scenario_data: Dict, current_stage_id: str, current_stage_info: Dict, collected_info: Dict, scenario_output: Optional[ScenarioAgentOutput], user_input: str) -> AgentState:
    """다중 정보 수집 처리 (개선된 그룹별 방식)"""
    required_fields = active_scenario_data.get("required_info_fields", [])
    
    # 현재 스테이지가 정보 수집 단계인지 확인
    
    # 인터넷뱅킹 정보 수집 스테이지 추가 (greeting 포함)
    info_collection_stages = [
        "greeting", "info_collection_guidance", "process_collected_info", 
        "ask_missing_info_group1", "ask_missing_info_group2", "ask_missing_info_group3", 
        "eligibility_assessment", "collect_internet_banking_info", "ask_remaining_ib_info",
        "collect_check_card_info", "ask_remaining_card_info", "ask_notification_settings",
        "ask_transfer_limit", "ask_withdrawal_account"  # ask_withdrawal_account 추가
    ]
    
    if current_stage_id in info_collection_stages:
        # REQUEST_MODIFY 인텐트는 이제 main_agent_router에서 직접 처리됨
        # scenario_logic에서는 정보 수집에만 집중
        
        # Entity Agent를 사용한 정보 추출
        extraction_result = {"extracted_entities": {}, "collected_info": collected_info}
        
        # ScenarioAgent가 이미 entities를 추출한 경우 Entity Agent 호출 생략
        if scenario_output and hasattr(scenario_output, 'entities') and scenario_output.entities:
            
            # entities가 "not specified" 키를 가지고 있고 그 값이 dict인 경우 평탄화
            entities_to_merge = scenario_output.entities.copy()
            if "not specified" in entities_to_merge and isinstance(entities_to_merge["not specified"], dict):
                not_specified_data = entities_to_merge.pop("not specified")
                entities_to_merge.update(not_specified_data)
            
            extraction_result = {
                "extracted_entities": entities_to_merge,
                "collected_info": {**collected_info, **entities_to_merge},
                "valid_entities": entities_to_merge,
                "invalid_entities": {},
                "missing_fields": [],
                "extraction_confidence": 0.9,
                "is_complete": False
            }
            collected_info = extraction_result["collected_info"]
            
            # 필드명 매핑 적용
            _handle_field_name_mapping(collected_info)
        elif user_input and len(user_input.strip()) > 0:
            # 먼저 user_input이 현재 stage의 valid choice 중 하나와 정확히 일치하는지 확인
            exact_choice_match = False
            if current_stage_info.get("choices"):
                choices = current_stage_info.get("choices", [])
                expected_field_keys = get_expected_field_keys(current_stage_info)
                expected_field = expected_field_keys[0] if expected_field_keys else None
                
                for choice in choices:
                    choice_value = choice.get("value", "") if isinstance(choice, dict) else str(choice)
                    if user_input.strip() == choice_value:
                        # 정확한 매치 발견 - Entity Agent를 거치지 않고 직접 저장
                        print(f"✅ [EXACT_CHOICE_MATCH] Found exact match: '{user_input}' for field '{expected_field}'")
                        if expected_field:
                            collected_info[expected_field] = user_input.strip()
                            extraction_result = {
                                "collected_info": collected_info,
                                "extracted_entities": {expected_field: user_input.strip()},
                                "message": "Exact choice match found"
                            }
                            exact_choice_match = True
                            break
            
            if not exact_choice_match:
                try:
                    # Entity Agent로 정보 추출 (정확한 choice 매치가 없는 경우에만)
                    print(f"🤖 [ENTITY_AGENT] About to call entity_agent.process_slot_filling")
                    print(f"  current_stage_id: {current_stage_id}")
                    print(f"  user_input: '{user_input}'")
                    print(f"  collected_info BEFORE Entity Agent: {collected_info}")
                    
                    # 현재 스테이지에 관련된 필드만 필터링
                    stage_relevant_fields = get_stage_relevant_fields(current_stage_info, required_fields, current_stage_id)
                    print(f"🤖 [ENTITY_AGENT] Filtered fields for stage: {[f['key'] for f in stage_relevant_fields]}")
                    
                    extraction_result = await entity_agent.process_slot_filling(user_input, stage_relevant_fields, collected_info)
                    
                    # Entity Agent 결과 디버깅
                    print(f"🤖 [ENTITY_AGENT] Entity Agent completed")
                    print(f"  extraction_result: {extraction_result}")
                    if 'collected_info' in extraction_result:
                        print(f"  collected_info AFTER Entity Agent: {extraction_result['collected_info']}")
                        
                except Exception as e:
                    print(f"[ERROR] Entity agent process_slot_filling failed: {type(e).__name__}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    # 에러 발생 시 빈 결과 반환
                    extraction_result = {
                        "collected_info": collected_info,
                        "extracted_entities": {},
                        "message": f"정보 추출 중 오류가 발생했습니다: {str(e)}"
                    }
                
                # 추출된 정보 업데이트
                collected_info = extraction_result["collected_info"]
                
                # 필드명 매핑 적용 (Entity Agent 결과에도)
                _handle_field_name_mapping(collected_info)
            
            if extraction_result['extracted_entities']:
                log_node_execution("Entity_Extract", output_info=f"entities={list(extraction_result['extracted_entities'].keys())}")

        # customer_info_check 단계에서 개인정보 확인 처리
        if current_stage_id == "customer_info_check":
            intent = scenario_output.get("intent", "") if scenario_output else ""
            print(f"  waiting_for_additional_modifications: {state.waiting_for_additional_modifications}")
            print(f"  collected_info has customer_name: {bool(collected_info.get('customer_name'))}")
            print(f"  collected_info has phone_number: {bool(collected_info.get('phone_number'))}")
            print(f"  confirm_personal_info: {collected_info.get('confirm_personal_info')}")
            print(f"  correction_mode: {state.correction_mode}")
            print(f"  pending_modifications: {state.pending_modifications}")
            # 추가 수정사항 대기 중인 경우 먼저 체크
            if state.waiting_for_additional_modifications:
                
                # 사용자가 추가 수정사항이 없다고 답한 경우
                if user_input and any(word in user_input for word in ["아니", "아니요", "아니야", "없어", "없습니다", "괜찮", "됐어", "충분"]):
                    # personal_info_correction으로 라우팅하여 처리하도록 함
                    return state.merge_update({
                        "action_plan": ["personal_info_correction"],
                        "action_plan_struct": [{"action": "personal_info_correction", "reason": "Handle no additional modifications"}],
                        "router_call_count": 0,
                        "is_final_turn_response": False
                    })
                elif user_input:
                    # 추가 수정사항이 있는 경우 - personal_info_correction으로 라우팅
                    return state.merge_update({
                        "action_plan": ["personal_info_correction"],
                        "action_plan_struct": [{"action": "personal_info_correction", "reason": "Additional modification requested"}],
                        "router_call_count": 0,
                        "is_final_turn_response": False
                    })
            
            # correction_mode가 활성화된 경우
            # pending_modifications가 있으면 이미 personal_info_correction에서 처리 중이므로 건너뛰기
            elif state.correction_mode and not state.pending_modifications:
                
                # 그 외의 경우 personal_info_correction_node로 라우팅
                return state.merge_update({
                    "action_plan": ["personal_info_correction"],
                    "action_plan_struct": [{"action": "personal_info_correction", "reason": "Correction mode active - processing modification"}],
                    "router_call_count": 0,
                    "is_final_turn_response": False
                })
            
            # 자연스러운 정보 수정 감지 (correction_mode가 아닌 상태에서도)
            # pending_modifications가 있으면 이미 처리 중이므로 수정 요청으로 감지하지 않음
            elif not state.correction_mode and not state.pending_modifications and _is_info_modification_request(user_input, collected_info):
                
                return state.merge_update({
                    "correction_mode": True,
                    "action_plan": ["personal_info_correction"],
                    "action_plan_struct": [{"action": "personal_info_correction", "reason": "Natural modification detected"}],
                    "router_call_count": 0,
                    "is_final_turn_response": False
                })
            
            # 이름과 전화번호가 이미 있고, 사용자가 긍정적으로 응답한 경우 바로 다음 단계로
            elif (collected_info.get("customer_name") and 
                  collected_info.get("phone_number") and
                  (collected_info.get("confirm_personal_info") == True or
                   (user_input and any(word in user_input for word in ["네", "예", "맞아", "맞습니다", "확인"])))):
                
                # confirm_personal_info도 True로 설정
                collected_info["confirm_personal_info"] = True
                
                # 시나리오 JSON에서 정의된 다음 단계로 이동
                transitions = current_stage_info.get("transitions", [])
                default_next = current_stage_info.get("default_next_stage_id", "ask_security_medium")
                
                # 긍정 응답에 해당하는 transition 찾기
                next_stage_id = default_next
                for transition in transitions:
                    if "맞다고 확인" in transition.get("condition_description", ""):
                        next_stage_id = transition.get("next_stage_id", default_next)
                        break
                
                next_stage_info = active_scenario_data.get("stages", {}).get(next_stage_id, {})
                
                # ask_security_medium 스테이지라면 stage_response_data 생성
                if next_stage_id == "ask_security_medium":
                    stage_response_data = generate_stage_response(next_stage_info, collected_info, active_scenario_data)
                    
                    return state.merge_update({
                        "current_scenario_stage_id": next_stage_id,
                        "collected_product_info": collected_info,
                        "stage_response_data": stage_response_data,
                        "is_final_turn_response": True,
                        "action_plan": [],
                        "action_plan_struct": [],
                        "correction_mode": False  # 수정 모드 해제
                    })
                else:
                    next_stage_prompt = next_stage_info.get("prompt", "")
                    return state.merge_update({
                        "current_scenario_stage_id": next_stage_id,
                        "collected_product_info": collected_info,
                        "final_response_text_for_tts": next_stage_prompt,
                        "is_final_turn_response": True,
                        "action_plan": [],
                        "action_plan_struct": [],
                        "correction_mode": False  # 수정 모드 해제
                    })
            # confirm_personal_info가 false인 경우는 기존 시나리오 전환 로직을 따름
        
        
        # 정보 수집 완료 여부 확인
        is_complete, missing_field_names = check_required_info_completion(collected_info, required_fields)
        
        if current_stage_id == "info_collection_guidance":
            # 초기 정보 안내 후 바로 다음 그룹 질문 결정
            if is_complete:
                next_stage_id = "eligibility_assessment"
                response_text = "네, 모든 정보가 수집되었습니다. 이제 자격 요건을 확인해보겠습니다."
            else:
                # 수집된 정보에 따라 다음 그룹 질문 결정
                next_stage_id = get_next_missing_info_group_stage(collected_info, required_fields)
                if next_stage_id == "eligibility_assessment":
                    response_text = "네, 모든 정보를 확인했습니다! 말씀해주신 조건으로 디딤돌 대출 신청이 가능해 보입니다. 이제 신청에 필요한 서류와 절차를 안내해드릴게요."
                else:
                    response_text = f"네, 말씀해주신 정보 확인했습니다! {generate_group_specific_prompt(next_stage_id, collected_info)}"
                
        elif current_stage_id == "process_collected_info":
            # 수집된 정보를 바탕으로 다음 그룹 결정
            if is_complete:
                next_stage_id = "eligibility_assessment"
                response_text = "네, 모든 정보를 확인했습니다! 말씀해주신 조건으로 디딤돌 대출 신청이 가능해 보입니다. 이제 신청에 필요한 서류와 절차를 안내해드릴게요."
            else:
                next_stage_id = get_next_missing_info_group_stage(collected_info, required_fields)
                response_text = generate_group_specific_prompt(next_stage_id, collected_info)
                
        elif current_stage_id.startswith("ask_missing_info_group"):
            # 그룹별 질문 처리 후 다음 단계 결정
            if is_complete:
                next_stage_id = "eligibility_assessment"
                response_text = "네, 모든 정보를 확인했습니다! 말씀해주신 조건으로 디딤돌 대출 신청이 가능해 보입니다. 이제 신청에 필요한 서류와 절차를 안내해드릴게요."
            else:
                next_stage_id = get_next_missing_info_group_stage(collected_info, required_fields)
                # 같은 그룹이면 그대로, 다른 그룹이면 새로운 질문
                if next_stage_id == current_stage_id:
                    # 같은 그룹 내에서 아직 더 수집할 정보가 있는 경우
                    response_text = generate_group_specific_prompt(next_stage_id, collected_info)
                else:
                    # 다음 그룹으로 넘어가는 경우
                    response_text = generate_group_specific_prompt(next_stage_id, collected_info)
                    
        elif current_stage_id == "collect_internet_banking_info":
            # 인터넷뱅킹 정보 수집 처리 - 전용 Agent 사용
            
            # InternetBankingAgent로 정보 분석 및 추출
            ib_analysis_result = {}
            if user_input:
                try:
                    ib_analysis_result = await internet_banking_agent.analyze_internet_banking_info(
                        user_input, collected_info, required_fields
                    )
                    
                    # 추출된 정보를 collected_info에 통합
                    if ib_analysis_result.get("extracted_info"):
                        collected_info.update(ib_analysis_result["extracted_info"])
                        
                except Exception as e:
                    print(f"[ERROR] Internet Banking Agent failed: {e}")
                    ib_analysis_result = {"error": str(e)}
            
            # 완료 여부 재확인
            is_ib_complete, missing_ib_fields = check_internet_banking_completion(collected_info, required_fields)
            
            if is_ib_complete:
                next_stage_id = "ask_check_card"
                # 다음 스테이지의 프롬프트를 가져와서 함께 표시
                next_stage_prompt = active_scenario_data.get("stages", {}).get("ask_check_card", {}).get("prompt", "체크카드를 신청하시겠어요?")
                response_text = f"인터넷뱅킹 설정이 완료되었습니다. {next_stage_prompt}"
            else:
                # 분석 결과에 안내 메시지가 있으면 사용, 없으면 기본 메시지
                if ib_analysis_result.get("guidance_message"):
                    response_text = ib_analysis_result["guidance_message"]
                else:
                    response_text = generate_internet_banking_prompt(missing_ib_fields)
                
                # 정보 추출이 있었다면 현재 스테이지 유지, 없으면 ask_remaining으로 이동
                if ib_analysis_result.get("extracted_info"):
                    next_stage_id = "collect_internet_banking_info"  # 같은 스테이지 유지
                else:
                    next_stage_id = "ask_remaining_ib_info"
            
            
        elif current_stage_id == "ask_remaining_ib_info":
            # 부족한 인터넷뱅킹 정보 재요청 - 전용 Agent 사용
            
            # InternetBankingAgent로 정보 분석 및 추출
            ib_analysis_result = {}
            if user_input:
                try:
                    ib_analysis_result = await internet_banking_agent.analyze_internet_banking_info(
                        user_input, collected_info, required_fields
                    )
                    
                    # 추출된 정보를 collected_info에 통합
                    if ib_analysis_result.get("extracted_info"):
                        collected_info.update(ib_analysis_result["extracted_info"])
                        
                except Exception as e:
                    print(f"[ERROR] Internet Banking Agent failed (remaining): {e}")
                    ib_analysis_result = {"error": str(e)}
            
            # 완료 여부 재확인
            is_ib_complete, missing_ib_fields = check_internet_banking_completion(collected_info, required_fields)
            
            if is_ib_complete:
                next_stage_id = "ask_check_card"
                # 다음 스테이지의 프롬프트를 가져와서 함께 표시
                next_stage_prompt = active_scenario_data.get("stages", {}).get("ask_check_card", {}).get("prompt", "체크카드를 신청하시겠어요?")
                response_text = f"인터넷뱅킹 설정이 완료되었습니다. {next_stage_prompt}"
            else:
                next_stage_id = "ask_remaining_ib_info"
                
                # 분석 결과에 안내 메시지가 있으면 사용, 없으면 기본 메시지
                if ib_analysis_result.get("guidance_message"):
                    response_text = ib_analysis_result["guidance_message"]
                else:
                    response_text = generate_internet_banking_prompt(missing_ib_fields)
            
        elif current_stage_id == "collect_check_card_info":
            # 체크카드 정보 수집 처리 - 전용 Agent 사용
            
            # CheckCardAgent로 정보 분석 및 추출
            cc_analysis_result = {}
            if user_input:
                try:
                    cc_analysis_result = await check_card_agent.analyze_check_card_info(
                        user_input, collected_info, required_fields
                    )
                    
                    # 추출된 정보를 collected_info에 통합
                    if cc_analysis_result.get("extracted_info"):
                        for field_key, value in cc_analysis_result["extracted_info"].items():
                            collected_info[field_key] = value
                    
                except Exception as e:
                    print(f"[ERROR] Check Card Agent error: {e}")
            
            # 완료 여부 재확인
            is_cc_complete, missing_cc_fields = check_check_card_completion(collected_info, required_fields)
            
            if is_cc_complete:
                next_stage_id = "final_summary"
                # final_summary 프롬프트를 가져와서 변수들을 치환
                summary_prompt = active_scenario_data.get("stages", {}).get("final_summary", {}).get("prompt", "")
                summary_prompt = replace_template_variables(summary_prompt, collected_info)
                response_text = f"체크카드 설정이 완료되었습니다.\n\n{summary_prompt}"
            else:
                # 분석 결과에 안내 메시지가 있으면 사용, 없으면 기본 메시지
                if cc_analysis_result.get("guidance_message"):
                    response_text = cc_analysis_result["guidance_message"]
                else:
                    response_text = generate_check_card_prompt(missing_cc_fields)
                
                # 사용자가 일부 정보를 제공한 경우 같은 스테이지 유지
                if cc_analysis_result.get("extracted_info"):
                    next_stage_id = "collect_check_card_info"
                else:
                    next_stage_id = "ask_remaining_card_info"
            
            
        elif current_stage_id == "ask_remaining_card_info":
            # 부족한 체크카드 정보 재요청 - 전용 Agent 사용
            
            # CheckCardAgent로 정보 분석 및 추출
            cc_analysis_result = {}
            if user_input:
                try:
                    cc_analysis_result = await check_card_agent.analyze_check_card_info(
                        user_input, collected_info, required_fields
                    )
                    
                    # 추출된 정보를 collected_info에 통합
                    if cc_analysis_result.get("extracted_info"):
                        for field_key, value in cc_analysis_result["extracted_info"].items():
                            collected_info[field_key] = value
                    
                except Exception as e:
                    print(f"[ERROR] Check Card Agent error: {e}")
            
            # 완료 여부 재확인
            is_cc_complete, missing_cc_fields = check_check_card_completion(collected_info, required_fields)
            
            if is_cc_complete:
                next_stage_id = "final_summary"
                # final_summary 프롬프트를 가져와서 변수들을 치환
                summary_prompt = active_scenario_data.get("stages", {}).get("final_summary", {}).get("prompt", "")
                summary_prompt = replace_template_variables(summary_prompt, collected_info)
                response_text = f"체크카드 설정이 완료되었습니다.\n\n{summary_prompt}"
            else:
                next_stage_id = "ask_remaining_card_info"
                
                # 분석 결과에 안내 메시지가 있으면 사용, 없으면 기본 메시지
                if cc_analysis_result.get("guidance_message"):
                    response_text = cc_analysis_result["guidance_message"]
                else:
                    response_text = generate_check_card_prompt(missing_cc_fields)
            
        elif current_stage_id == "ask_security_medium":
            # ask_security_medium 단계 처리
            print(f"🔐 [SECURITY_MEDIUM] Special handling for ask_security_medium stage")
            print(f"🔐 [SECURITY_MEDIUM] collected_info: {collected_info}")
            print(f"🔐 [SECURITY_MEDIUM] security_medium value: {collected_info.get('security_medium', 'NOT_SET')}")
            
            # security_medium이 수집되었는지 확인
            if 'security_medium' in collected_info:
                # 다음 단계로 진행
                next_stage_id = current_stage_info.get("default_next_stage_id", "ask_transfer_limit")
                next_stage_info = active_scenario_data.get("stages", {}).get(next_stage_id, {})
                
                response_text = f"보안매체를 {collected_info['security_medium']}(으)로 등록하겠습니다. "
                
                # 다음 단계 프롬프트 추가
                next_prompt = next_stage_info.get("prompt", "")
                response_text += next_prompt
                
                print(f"🔐 [SECURITY_MEDIUM] Moving to next stage: {next_stage_id}")
                
                return state.merge_update({
                    "current_scenario_stage_id": next_stage_id,
                    "collected_product_info": collected_info,
                    "final_response_text_for_tts": response_text,
                    "is_final_turn_response": True,
                    "action_plan": [],
                    "action_plan_struct": [],
                    "router_call_count": 0
                })
            else:
                # security_medium이 없으면 stage response 보여주기
                stage_response_data = generate_stage_response(current_stage_info, collected_info, active_scenario_data)
                print(f"🔐 [SECURITY_MEDIUM] No security_medium collected, showing stage response")
                
                return state.merge_update({
                    "stage_response_data": stage_response_data,
                    "is_final_turn_response": True,
                    "action_plan": [],
                    "action_plan_struct": []
                })
        
        elif current_stage_id == "ask_transfer_limit":
            # 이체한도 설정 단계 처리 - 개선된 버전
            
            # "네" 응답 시 최대한도로 설정
            if user_input and any(word in user_input for word in ["네", "예", "응", "어", "최대로", "최대한도로", "최고로", "좋아요", "그렇게 해주세요"]):
                collected_info["transfer_limit_per_time"] = 5000
                collected_info["transfer_limit_per_day"] = 10000
                print(f"[TRANSFER_LIMIT] User confirmed maximum limits: 1회 5000만원, 1일 10000만원")
            
            # ScenarioAgent의 entities를 먼저 병합 및 필드명 매핑
            if scenario_output and hasattr(scenario_output, 'entities') and scenario_output.entities:
                # "not specified" 중첩 처리
                entities_to_merge = scenario_output.entities.copy()
                if "not specified" in entities_to_merge and isinstance(entities_to_merge["not specified"], dict):
                    not_specified_data = entities_to_merge.pop("not specified")
                    entities_to_merge.update(not_specified_data)
                
                # collected_info에 병합 및 필드명 매핑
                for field_key, value in entities_to_merge.items():
                    if value is not None:
                        # transfer_limits 객체인 경우 특별 처리
                        if field_key == "transfer_limits" and isinstance(value, dict):
                            if "one_time" in value:
                                collected_info["transfer_limit_per_time"] = value["one_time"]
                            if "daily" in value:
                                collected_info["transfer_limit_per_day"] = value["daily"]
                        elif field_key in ["transfer_limit_per_time", "transfer_limit_per_day"]:
                            collected_info[field_key] = value
            
            # collected_info의 "not specified" 객체 처리 및 필드명 매핑
            _handle_field_name_mapping(collected_info)
            
            # 필요한 필드 정의
            transfer_limit_fields = [
                {"key": "transfer_limit_per_time", "display_name": "1회 이체한도", "type": "number"},
                {"key": "transfer_limit_per_day", "display_name": "1일 이체한도", "type": "number"}
            ]
            
            # Entity Agent를 사용한 추출 (scenario_output에 entities가 없거나 부족한 경우)
            if user_input and (not collected_info.get("transfer_limit_per_time") or not collected_info.get("transfer_limit_per_day")):
                try:
                    extraction_result = await entity_agent.extract_entities(user_input, transfer_limit_fields)
                    extracted_entities = extraction_result.get("extracted_entities", {})
                    
                    # 추출된 엔티티를 collected_info에 병합
                    for field_key, value in extracted_entities.items():
                        if value is not None and field_key not in collected_info:
                            collected_info[field_key] = value
                            
                except Exception as e:
                    print(f"[ERROR] Entity extraction error: {e}")
            
            # 최종 필드명 매핑 재실행 (Entity Agent가 추출한 데이터도 처리)
            _handle_field_name_mapping(collected_info)
            
            per_time_value = collected_info.get("transfer_limit_per_time")
            per_day_value = collected_info.get("transfer_limit_per_day")
            
            
            # 유효성 검증
            valid_fields = []
            invalid_fields = []
            error_messages = []
            
            # 1회 이체한도 검증
            if per_time_value is not None:
                validator = FIELD_VALIDATORS.get("transfer_limit_per_time")
                if validator:
                    is_valid, error_msg = validator.validate(per_time_value)
                    if is_valid:
                        valid_fields.append({"key": "transfer_limit_per_time", "value": per_time_value})
                    else:
                        invalid_fields.append("transfer_limit_per_time")
                        error_messages.append(error_msg)
                        # 유효하지 않은 값은 제거
                        collected_info.pop("transfer_limit_per_time", None)
            
            # 1일 이체한도 검증
            if per_day_value is not None:
                validator = FIELD_VALIDATORS.get("transfer_limit_per_day")
                if validator:
                    is_valid, error_msg = validator.validate(per_day_value)
                    if is_valid:
                        valid_fields.append({"key": "transfer_limit_per_day", "value": per_day_value})
                    else:
                        invalid_fields.append("transfer_limit_per_day")
                        error_messages.append(error_msg)
                        # 유효하지 않은 값은 제거
                        collected_info.pop("transfer_limit_per_day", None)
            
            # 응답 생성
            collected_messages = []
            missing_fields = []
            
            # 유효한 값들에 대한 확인 메시지
            for field in valid_fields:
                if field["key"] == "transfer_limit_per_time":
                    value = field["value"]
                    # 값은 이미 만원 단위로 저장되어 있음
                    collected_messages.append(f"1회 이체한도 {value:,}만원")
                elif field["key"] == "transfer_limit_per_day":
                    value = field["value"]
                    # 값은 이미 만원 단위로 저장되어 있음
                    collected_messages.append(f"1일 이체한도 {value:,}만원")
            
            # 누락된 필드 확인
            if "transfer_limit_per_time" not in [f["key"] for f in valid_fields]:
                missing_fields.append("1회 이체한도")
            if "transfer_limit_per_day" not in [f["key"] for f in valid_fields]:
                missing_fields.append("1일 이체한도")
            
            # 모든 정보가 수집되고 유효한 경우
            if not missing_fields and not invalid_fields:
                next_stage_id = current_stage_info.get("default_next_stage_id", "ask_notification_settings")
                # 다음 스테이지가 boolean 타입이면 텍스트 응답 없이 stage_response_data만 생성
                next_stage_info = active_scenario_data.get("stages", {}).get(next_stage_id, {})
                if next_stage_info.get("response_type") == "boolean":
                    response_text = f"{', '.join(collected_messages)}으로 설정되었습니다."
                else:
                    next_stage_prompt = next_stage_info.get("prompt", "")
                    response_text = f"{', '.join(collected_messages)}으로 설정되었습니다. {next_stage_prompt}"
            else:
                # 부분 응답 처리
                response_parts = []
                
                # 유효한 값에 대한 확인
                if collected_messages:
                    response_parts.append(f"{', '.join(collected_messages)}으로 설정했습니다.")
                
                # 유효성 검증 실패 메시지
                if error_messages:
                    response_parts.extend(error_messages)
                
                # 누락된 정보 요청
                if missing_fields:
                    response_parts.append(f"{', '.join(missing_fields)}도 말씀해주세요.")
                
                next_stage_id = "ask_transfer_limit"  # 같은 스테이지 유지
                response_text = " ".join(response_parts)
            
        elif current_stage_id == "ask_notification_settings":
            # 알림 설정 단계 처리 - Boolean 타입 단계로 올바르게 처리
            print(f"🔥🔥🔥🔥🔥 [STAGE] === NOTIFICATION SETTINGS STAGE ENTERED ===")
            print(f"🔥🔥🔥🔥🔥 [STAGE] User input: '{user_input}'")
            print(f"🔥🔥🔥🔥🔥 [STAGE] Current collected_info BEFORE: {collected_info}")
            
            # === 무조건 강제 Boolean 변환 (모든 조건 무시) ===
            boolean_fields = ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
            
            print(f"🔥🔥🔥 [FORCE] === UNCONDITIONAL BOOLEAN CONVERSION START ===")
            for field in boolean_fields:
                if field in collected_info and isinstance(collected_info[field], str):
                    str_value = collected_info[field].strip()
                    print(f"🔥🔥🔥 [FORCE] Converting {field}: '{str_value}'")
                    
                    if str_value in ["신청", "네", "예", "좋아요", "동의", "하겠습니다", "필요해요", "받을게요"]:
                        collected_info[field] = True
                        print(f"🔥🔥🔥 [FORCE] ✅ {field}: '{str_value}' → TRUE")
                    elif str_value in ["미신청", "아니요", "아니", "싫어요", "거부", "안할게요", "필요없어요", "안받을게요"]:
                        collected_info[field] = False  
                        print(f"🔥🔥🔥 [FORCE] ✅ {field}: '{str_value}' → FALSE")
                    else:
                        print(f"🔥🔥🔥 [FORCE] ❌ Unknown value: {field} = '{str_value}'")
                elif field in collected_info:
                    print(f"🔥🔥🔥 [FORCE] {field} = {collected_info[field]} ({type(collected_info[field]).__name__}) - already boolean")
                else:
                    print(f"🔥🔥🔥 [FORCE] {field} not found in collected_info")
            
            print(f"🔥🔥🔥 [FORCE] === UNCONDITIONAL BOOLEAN CONVERSION END ===")
            
            # === "네" 응답 처리: 모든 알림을 true로 설정 ===
            if user_input and any(word in user_input for word in ["네", "예", "좋아요", "모두", "전부", "다", "신청", "하겠습니다"]):
                print(f"🔥 [YES_RESPONSE] User said yes - setting all notifications to true")
                for field in boolean_fields:
                    collected_info[field] = True
                    print(f"🔥 [YES_RESPONSE] Set {field} = True")
            
            # === 간단한 다음 단계 진행 로직 ===
            if user_input:
                # 다음 단계로 진행
                next_stage_id = current_stage_info.get("default_next_stage_id", "ask_check_card")
                
                # 다음 스테이지 정보 가져오기
                next_stage_info = active_scenario_data.get("stages", {}).get(next_stage_id, {})
                next_stage_prompt = next_stage_info.get("prompt", "")
                
                # 간단한 확인 메시지 + 다음 단계 프롬프트
                response_text = f"알림 설정을 완료했습니다. {next_stage_prompt}"
                
                
                return state.merge_update({
                    "current_scenario_stage_id": next_stage_id,
                    "collected_product_info": collected_info,
                    "final_response_text_for_tts": response_text,
                    "is_final_turn_response": True,
                    "action_plan": [],
                    "action_plan_struct": [],
                    "router_call_count": 0
                })
            
            else:
                # 사용자 입력이 없는 경우 - boolean UI 표시를 위해 stage_response_data 생성
                next_stage_id = current_stage_id
                stage_response_data = generate_stage_response(current_stage_info, collected_info, active_scenario_data)
                
                return state.merge_update({
                    "current_scenario_stage_id": next_stage_id,
                    "collected_product_info": collected_info,
                    "stage_response_data": stage_response_data,
                    "is_final_turn_response": True,
                    "action_plan": [],
                    "action_plan_struct": [],
                    "router_call_count": 0
                })
                
        elif current_stage_id == "eligibility_assessment":
            # 자격 검토 완료 후 서류 안내로 자동 진행
            next_stage_id = "application_documents_guidance"
            response_text = active_scenario_data.get("stages", {}).get("application_documents_guidance", {}).get("prompt", "서류 안내를 진행하겠습니다.")
            
        else:
            next_stage_id = current_stage_info.get("default_next_stage_id", "eligibility_assessment")
            response_text = current_stage_info.get("prompt", "")
        
        # 응답 텍스트가 설정되지 않은 경우 기본값 사용
        if "response_text" not in locals():
            response_text = current_stage_info.get("prompt", "추가 정보를 알려주시겠어요?")
        
        # 다음 액션을 위해 plan과 struct에서 현재 액션 제거 (무한 루프 방지)
        updated_plan = state.get("action_plan", []).copy()
        if updated_plan:
            updated_plan.pop(0)
        
        updated_struct = state.get("action_plan_struct", []).copy()
        if updated_struct:
            updated_struct.pop(0)
            
        # 스테이지 변경 시 로그
        if next_stage_id != current_stage_id:
            log_node_execution("Stage_Change", f"{current_stage_id} → {next_stage_id}")
            # Clear action plan to prevent re-routing when stage changes
            updated_plan = []
            updated_struct = []
        
        
        # 다음 스테이지의 stage_response_data 생성
        stage_response_data = None
        if next_stage_id and next_stage_id != current_stage_id:
            next_stage_info = active_scenario_data.get("stages", {}).get(next_stage_id, {})
            # bullet 또는 boolean 타입이면 stage_response_data 생성
            if next_stage_info.get("response_type") in ["bullet", "boolean"]:
                stage_response_data = generate_stage_response(next_stage_info, collected_info, active_scenario_data)
                print(f"🎯 [STAGE_RESPONSE] Generated stage response data for {next_stage_id} (type: {next_stage_info.get('response_type')})")
            elif "response_type" in next_stage_info:
                stage_response_data = generate_stage_response(next_stage_info, collected_info, active_scenario_data)
        
        # 스테이지가 변경되지 않은 경우와 사용자 입력이 없는 경우에만 is_final_turn_response를 False로 설정
        is_final_response = True
        if next_stage_id == current_stage_id and not user_input:
            is_final_response = False
        
        # stage_response_data가 있으면 텍스트 응답 대신 사용
        if stage_response_data:
            return state.merge_update({
                "current_scenario_stage_id": next_stage_id,
                "collected_product_info": collected_info,
                "stage_response_data": stage_response_data,
                "is_final_turn_response": is_final_response,
                "action_plan": updated_plan,
                "action_plan_struct": updated_struct,
                "router_call_count": 0  # 라우터 카운트 초기화
            })
        else:
            return state.merge_update({
                "current_scenario_stage_id": next_stage_id,
                "collected_product_info": collected_info,
                "final_response_text_for_tts": response_text,
                "is_final_turn_response": is_final_response,
                "action_plan": updated_plan,
                "action_plan_struct": updated_struct,
                "router_call_count": 0  # 라우터 카운트 초기화
            })
        
    else:
        # 일반 스테이지는 기존 로직으로 처리
        return await process_single_info_collection(state, active_scenario_data, current_stage_id, current_stage_info, collected_info, state.get("scenario_agent_output"), user_input)


async def process_single_info_collection(state: AgentState, active_scenario_data: Dict, current_stage_id: str, current_stage_info: Dict, collected_info: Dict, scenario_output: Optional[ScenarioAgentOutput], user_input: str) -> AgentState:
    """기존 단일 정보 수집 처리"""
    print(f"🔍 PROCESS_SINGLE_INFO_COLLECTION called for stage: {current_stage_id}")
    
    # narrative 타입에서 yes/no 응답 처리 (confirm_personal_info, card_password_setting 등)
    if user_input and current_stage_info.get("response_type") == "narrative":
        user_lower = user_input.lower().strip()
        
        # confirm_personal_info 단계
        if current_stage_id == "confirm_personal_info":
            # 직접적인 항목 수정 요청 확인 (예: "휴대폰번호 틀렸어", "이름이 잘못됐어")
            field_names = {
                "이름": ["이름", "성명"],
                "영문이름": ["영문이름", "영문명", "영어이름"],
                "주민번호": ["주민번호", "주민등록번호", "생년월일"],
                "휴대폰번호": ["휴대폰번호", "전화번호", "핸드폰번호", "폰번호", "연락처"],
                "이메일": ["이메일", "메일"],
                "주소": ["주소", "집주소"],
                "직장주소": ["직장주소", "회사주소", "근무지"]
            }
            
            # 특정 필드가 언급되고 수정 관련 단어가 있는지 확인
            field_mentioned = False
            for field, keywords in field_names.items():
                if any(kw in user_lower for kw in keywords) and any(word in user_lower for word in ["틀렸", "틀려", "잘못", "수정", "변경", "다르"]):
                    field_mentioned = True
                    break
            
            if field_mentioned:
                # 특정 항목 수정 요청인 경우
                collected_info["personal_info_confirmed"] = False
                print(f"[CONFIRM_PERSONAL_INFO] Specific field modification request detected")
                state["special_response_for_modification"] = True
            elif any(word in user_lower for word in ["네", "예", "응", "어", "그래", "좋아", "맞아", "알겠", "확인"]):
                collected_info["personal_info_confirmed"] = True
                print(f"[CONFIRM_PERSONAL_INFO] '네' response -> personal_info_confirmed = True")
                
                # display_fields의 개인정보를 collected_info에 병합
                if current_stage_info.get("display_fields") and isinstance(current_stage_info["display_fields"], dict):
                    display_fields = current_stage_info["display_fields"]
                    for field_key, field_value in display_fields.items():
                        if field_key not in collected_info:  # 기존 값이 없는 경우에만 추가
                            collected_info[field_key] = field_value
                    print(f"[CONFIRM_PERSONAL_INFO] Merged display_fields: {list(display_fields.keys())}")
                    
            elif any(word in user_lower for word in ["아니", "틀려", "수정", "변경", "다르"]):
                collected_info["personal_info_confirmed"] = False
                print(f"[CONFIRM_PERSONAL_INFO] '아니' response -> personal_info_confirmed = False")
                # 수정 요청 시 특별한 응답 설정
                state["special_response_for_modification"] = True
        
        # card_password_setting 단계
        elif current_stage_id == "card_password_setting":
            if any(word in user_lower for word in ["네", "예", "응", "어", "그래", "좋아", "맞아", "알겠", "동일", "같게"]):
                collected_info["card_password_same_as_account"] = True
                print(f"[CARD_PASSWORD] '네' response -> card_password_same_as_account = True")
            elif any(word in user_lower for word in ["아니", "다르게", "따로", "별도"]):
                collected_info["card_password_same_as_account"] = False
                print(f"[CARD_PASSWORD] '아니' response -> card_password_same_as_account = False")
        
        # additional_services 단계 - V3는 boolean 처리
        elif current_stage_id == "additional_services":
            # V3 시나리오에서는 boolean 타입으로 처리
            if any(word in user_lower for word in ["네", "예", "응", "어", "그래", "좋아", "맞아", "알겠", "모두", "전부", "다"]):
                # 모든 서비스 신청 (true)
                collected_info["important_transaction_alert"] = True
                collected_info["withdrawal_alert"] = True
                collected_info["overseas_ip_restriction"] = True
                print(f"[ADDITIONAL_SERVICES] '네' response -> all services = True")
            elif any(word in user_lower for word in ["아니", "안", "필요없", "괜찮"]):
                # 모든 서비스 미신청 (false)
                collected_info["important_transaction_alert"] = False
                collected_info["withdrawal_alert"] = False
                collected_info["overseas_ip_restriction"] = False
                print(f"[ADDITIONAL_SERVICES] '아니' response -> all services = False")
    
    # 사용자가 '네' 응답을 한 경우 기본값 처리 (모든 bullet/choice 단계)
    if user_input and current_stage_info.get("response_type") in ["bullet", "boolean"]:
        user_lower = user_input.lower().strip()
        if any(word in user_lower for word in ["네", "예", "응", "어", "그래", "좋아", "맞아", "알겠", "할게"]):
            # V3 시나리오: fields_to_collect를 사용하는 경우
            fields_to_collect = current_stage_info.get("fields_to_collect", [])
            if fields_to_collect:
                # security_medium_registration 단계 특별 처리
                if current_stage_id == "security_medium_registration":
                    # 기본 보안매체 선택
                    default_choice = None
                    default_metadata = None
                    if current_stage_info.get("choice_groups"):
                        for group in current_stage_info.get("choice_groups", []):
                            for choice in group.get("choices", []):
                                if choice.get("default"):
                                    default_choice = choice.get("value")
                                    default_metadata = choice.get("metadata", {})
                                    break
                            if default_choice:
                                break
                    
                    if default_choice:
                        # 각 필드별로 적절한 값 설정
                        for field_key in fields_to_collect:
                            if field_key not in collected_info:
                                if field_key == "security_medium":
                                    collected_info[field_key] = default_choice
                                    print(f"[DEFAULT_SELECTION] Stage {current_stage_id}: '네' response mapped {field_key} to: {default_choice}")
                                elif field_key == "transfer_limit_once" and default_metadata.get("transfer_limit_once"):
                                    collected_info[field_key] = default_metadata["transfer_limit_once"]
                                    print(f"[DEFAULT_SELECTION] Stage {current_stage_id}: '네' response mapped {field_key} to: {default_metadata['transfer_limit_once']}")
                                elif field_key == "transfer_limit_daily" and default_metadata.get("transfer_limit_daily"):
                                    collected_info[field_key] = default_metadata["transfer_limit_daily"]
                                    print(f"[DEFAULT_SELECTION] Stage {current_stage_id}: '네' response mapped {field_key} to: {default_metadata['transfer_limit_daily']}")
                
                # card_selection 단계 특별 처리
                elif current_stage_id == "card_selection":
                    # 기본 카드 선택
                    default_choice = None
                    default_metadata = None
                    if current_stage_info.get("choices"):
                        for choice in current_stage_info.get("choices", []):
                            if choice.get("default"):
                                default_choice = choice.get("value")
                                default_metadata = choice.get("metadata", {})
                                break
                    
                    if default_choice:
                        # 각 필드별로 적절한 값 설정
                        for field_key in fields_to_collect:
                            if field_key not in collected_info:
                                if field_key == "card_selection":
                                    collected_info[field_key] = default_choice
                                    print(f"[DEFAULT_SELECTION] Stage {current_stage_id}: '네' response mapped {field_key} to: {default_choice}")
                                elif field_key == "card_receipt_method" and default_metadata.get("receipt_method"):
                                    collected_info[field_key] = default_metadata["receipt_method"]
                                    print(f"[DEFAULT_SELECTION] Stage {current_stage_id}: '네' response mapped {field_key} to: {default_metadata['receipt_method']}")
                                elif field_key == "transit_function" and "transit_enabled" in default_metadata:
                                    collected_info[field_key] = default_metadata["transit_enabled"]
                                    print(f"[DEFAULT_SELECTION] Stage {current_stage_id}: '네' response mapped {field_key} to: {default_metadata['transit_enabled']}")
                
                # statement_delivery 단계 특별 처리
                elif current_stage_id == "statement_delivery":
                    # 기본 수령 방법 선택
                    default_choice = None
                    if current_stage_info.get("choices"):
                        for choice in current_stage_info.get("choices", []):
                            if choice.get("default"):
                                default_choice = choice.get("value")
                                break
                    
                    # default_values에서 statement_delivery_date 가져오기
                    default_values = current_stage_info.get("default_values", {})
                    
                    if default_choice or default_values:
                        # 각 필드별로 적절한 값 설정
                        for field_key in fields_to_collect:
                            if field_key not in collected_info:
                                if field_key == "statement_delivery_method" and default_choice:
                                    collected_info[field_key] = default_choice
                                    print(f"[DEFAULT_SELECTION] Stage {current_stage_id}: '네' response mapped {field_key} to: {default_choice}")
                                elif field_key == "statement_delivery_date" and default_values.get("statement_delivery_date"):
                                    collected_info[field_key] = default_values["statement_delivery_date"]
                                    print(f"[DEFAULT_SELECTION] Stage {current_stage_id}: '네' response mapped {field_key} to: {default_values['statement_delivery_date']}")
                                    print(f"🔥 [STATEMENT_DATE_DEBUG] collected_info now contains: {collected_info.get('statement_delivery_date')}")
                else:
                    # 다른 단계들은 기존 로직 사용
                    for field_key in fields_to_collect:
                        if field_key not in collected_info:
                            # choice_groups에서 기본값 찾기
                            default_value = None
                            if current_stage_info.get("choice_groups"):
                                for group in current_stage_info.get("choice_groups", []):
                                    for choice in group.get("choices", []):
                                        if choice.get("default"):
                                            default_value = choice.get("value")
                                            break
                                    if default_value:
                                        break
                            # choices에서 기본값 찾기
                            elif current_stage_info.get("choices"):
                                for choice in current_stage_info.get("choices", []):
                                    if isinstance(choice, dict) and choice.get("default"):
                                        default_value = choice.get("value")
                                        break
                            
                            if default_value:
                                collected_info[field_key] = default_value
                                print(f"[DEFAULT_SELECTION] Stage {current_stage_id}: '네' response mapped {field_key} to default: {default_value}")
            
            # 기존 로직: expected_info_key를 사용하는 경우
            expected_info_key = current_stage_info.get("expected_info_key")
            if expected_info_key and expected_info_key not in collected_info:
                # choice_groups에서 기본값 찾기
                default_value = None
                if current_stage_info.get("choice_groups"):
                    for group in current_stage_info.get("choice_groups", []):
                        for choice in group.get("choices", []):
                            if choice.get("default"):
                                default_value = choice.get("value")
                                break
                        if default_value:
                            break
                # choices에서 기본값 찾기
                elif current_stage_info.get("choices"):
                    for choice in current_stage_info.get("choices", []):
                        if isinstance(choice, dict) and choice.get("default"):
                            default_value = choice.get("value")
                            break
                
                if default_value:
                    collected_info[expected_info_key] = default_value
                    print(f"[DEFAULT_SELECTION] Stage {current_stage_id}: '네' response mapped to default: {default_value}")
    
    # choice_exact 모드이거나 user_input이 현재 stage의 choice와 정확히 일치하는 경우 특별 처리
    if state.get("input_mode") == "choice_exact" or (user_input and (current_stage_info.get("choices") or current_stage_info.get("choice_groups"))):
        # choices 중에 정확히 일치하는지 확인
        choices = current_stage_info.get("choices", [])
        # choice_groups가 있는 경우 모든 choices를 평면화
        if current_stage_info.get("choice_groups"):
            for group in current_stage_info.get("choice_groups", []):
                group_choices = group.get("choices", [])
                choices.extend(group_choices)
                print(f"🎯 [CHOICE_GROUPS] Added {len(group_choices)} choices from group '{group.get('group_name', 'Unknown')}'")
        
        # Get the first field to collect as the primary field for this choice
        fields_to_collect = current_stage_info.get("fields_to_collect", [])
        expected_field = fields_to_collect[0] if fields_to_collect else None
        print(f"🎯 [EXACT_MATCH] fields_to_collect: {fields_to_collect}")
        
        # 디버깅: card_selection 단계일 때 상세 정보 출력
        if current_stage_id == "card_selection":
            print(f"🎯 [CARD_SELECTION_DEBUG] fields_to_collect: {fields_to_collect}")
            print(f"🎯 [CARD_SELECTION_DEBUG] current_stage_info keys: {list(current_stage_info.keys())}")
            # 시나리오 데이터 소스 확인
            print(f"🎯 [CARD_SELECTION_DEBUG] active_scenario_data source: {active_scenario_data.get('version', 'unknown')}")
            print(f"🎯 [CARD_SELECTION_DEBUG] Full stage info: {json.dumps(current_stage_info, ensure_ascii=False, indent=2)[:500]}...")
        
        print(f"🎯 [EXACT_MATCH] Looking for '{user_input.strip()}' in {len(choices)} total choices")
        print(f"🎯 [EXACT_MATCH] Expected field: {expected_field}")
        
        for choice in choices:
            choice_value = choice.get("value", "") if isinstance(choice, dict) else str(choice)
            if user_input.strip() == choice_value:
                # 정확한 매치 발견 - Entity Agent 결과 대신 직접 사용
                print(f"🎯 [EXACT_MATCH] {expected_field}: '{user_input}' is already a valid choice")
                if expected_field:
                    entities = {expected_field: user_input.strip()}
                    intent = "정보제공"
                    
                    # 선택한 choice의 metadata도 함께 처리 (security_medium_registration 등)
                    if isinstance(choice, dict) and choice.get("metadata"):
                        choice_metadata = choice.get("metadata", {})
                        print(f"🎯 [EXACT_MATCH] Found metadata for choice '{choice_value}': {choice_metadata}")
                        
                        # security_medium_registration 단계의 경우 metadata를 entities에 추가
                        if current_stage_id == "security_medium_registration":
                            if "transfer_limit_once" in choice_metadata:
                                entities["transfer_limit_once"] = choice_metadata["transfer_limit_once"]
                            if "transfer_limit_daily" in choice_metadata:
                                entities["transfer_limit_daily"] = choice_metadata["transfer_limit_daily"]
                            print(f"🎯 [EXACT_MATCH] Added transfer limits to entities: {entities}")
                        
                        # card_selection 단계의 경우 metadata를 entities에 추가
                        elif current_stage_id == "card_selection":
                            # card_selection 필드에 선택한 카드 value 저장
                            entities["card_selection"] = choice_value
                            print(f"🎯 [EXACT_MATCH] Set card_selection to: {choice_value}")
                            
                            if "receipt_method" in choice_metadata:
                                entities["card_receipt_method"] = choice_metadata["receipt_method"]
                            if "transit_enabled" in choice_metadata:
                                entities["transit_function"] = choice_metadata["transit_enabled"]
                            print(f"🎯 [EXACT_MATCH] Added card metadata to entities: {entities}")
                    
                    # scenario_output 재정의
                    scenario_output = ScenarioAgentOutput(
                        intent=intent,
                        entities=entities,
                        is_scenario_related=True
                    )
                    
                    # choice_exact 모드에서는 즉시 entities를 collected_info에 저장
                    if state.get("input_mode") == "choice_exact":
                        print(f"🎯 [CHOICE_EXACT] Exact match found. Storing entities immediately: {entities}")
                        for key, value in entities.items():
                            if value is not None:
                                collected_info[key] = value
                                print(f"✅ [CHOICE_EXACT_STORED] {key}: '{value}'")
                        
                        # 현재 단계의 default_values 처리
                        # fields_to_collect에 있지만 entities에 없는 필드들에 대해 default_values 적용
                        default_values = current_stage_info.get("default_values", {})
                        if default_values and fields_to_collect:
                            for field_key in fields_to_collect:
                                if field_key not in entities and field_key not in collected_info and field_key in default_values:
                                    collected_info[field_key] = default_values[field_key]
                                    print(f"✅ [CHOICE_EXACT_DEFAULT] {field_key}: '{default_values[field_key]}' (from default_values)")
                        
                        # statement_delivery 단계 특별 처리 (추가 보장)
                        if current_stage_id == "statement_delivery" and "statement_delivery_method" in entities:
                            if "statement_delivery_date" in default_values and "statement_delivery_date" not in collected_info:
                                collected_info["statement_delivery_date"] = default_values["statement_delivery_date"]
                                print(f"✅ [CHOICE_EXACT_DEFAULT] statement_delivery_date: '{default_values['statement_delivery_date']}' (special handling for statement_delivery)")
                    break
        else:
            # 정확한 매치가 없는 경우에만 원래 scenario_output 사용
            if scenario_output and scenario_output.get("is_scenario_related"):
                entities = scenario_output.get("entities", {})
                intent = scenario_output.get("intent", "")
            else:
                entities = {}
                intent = ""
    elif scenario_output and scenario_output.get("is_scenario_related"):
        entities = scenario_output.get("entities", {})
        intent = scenario_output.get("intent", "")
        
        
        if entities and user_input:
            verification_prompt_template = """
You are an exceptionally discerning assistant tasked with interpreting a user's intent. Your goal is to determine if the user has made a definitive choice or is simply asking a question about an option.

Here is the conversational context:
- The agent asked the user: "{agent_question}"
- The user replied: "{user_response}"
- From the user's reply, the following information was extracted: {entities}

Your task is to analyze the user's reply carefully. Has the user **committed** to the choice represented by the extracted information?

Consider these rules:
1.  **Direct questions are not commitments.** If the user asks "What is [option]?" or "Are there fees for [option]?", they have NOT committed.
2.  **Hypotheticals can be commitments.** If the user asks "If I choose [option], what happens next?", they ARE committing to that option for the sake of continuing the conversation.
3.  **Ambiguity means no commitment.** If it's unclear, err on the side of caution and decide it's not a commitment.

You MUST respond in JSON format with a single key "is_confirmed" (boolean). Example: {{"is_confirmed": true}}
"""
            verification_prompt = verification_prompt_template.format(
                agent_question=current_stage_info.get("prompt", ""),
                user_response=user_input,
                entities=str(entities)
            )
            
            try:
                response = await json_llm.ainvoke([HumanMessage(content=verification_prompt)])
                raw_content = response.content.strip().replace("```json", "").replace("```", "").strip()
                decision = json.loads(raw_content)
                is_confirmed = decision.get("is_confirmed", False)
                
                if is_confirmed:
                    # Validate entities against field choices
                    engine = SimpleScenarioEngine(active_scenario_data)
                    
                    validation_errors = []
                    for key, value in entities.items():
                        if value is not None:
                            # 특별한 매칭 로직 적용
                            mapped_value = _map_entity_to_valid_choice(key, value, current_stage_info)
                            if mapped_value:
                                collected_info[key] = mapped_value
                                print(f"✅ [ENTITY_MAPPING] {key}: '{value}' → '{mapped_value}'")
                            else:
                                is_valid, error_msg = engine.validate_field_value(key, value)
                                if is_valid:
                                    collected_info[key] = value
                                else:
                                    print(f"❌ [VALIDATION_ERROR] {key}: {error_msg}")
                                    # validation 에러가 있어도 무한루프를 방지하기 위해 기본값 사용
                                    default_value = _get_default_value_for_field(key, current_stage_info)
                                    if default_value:
                                        collected_info[key] = default_value
                                        print(f"🔄 [FALLBACK] {key}: using default '{default_value}'")
                    
                    # validation_errors는 이제 사용하지 않음 (무한루프 방지)
                else:
                    print(f"--- Entity verification FAILED. Not updating collected info. ---")
            except Exception as e:
                pass

        elif entities:
            # Validate entities against field choices with improved mapping
            for key, value in entities.items():
                if value is not None:
                    # 특별한 매핑 로직 적용
                    mapped_value = _map_entity_to_valid_choice(key, value, current_stage_info)
                    if mapped_value:
                        collected_info[key] = mapped_value
                        print(f"✅ [ENTITY_MAPPING] {key}: '{value}' → '{mapped_value}'")
                    else:
                        # 기본 validation 시도
                        engine = SimpleScenarioEngine(active_scenario_data)
                        is_valid, error_msg = engine.validate_field_value(key, value)
                        if is_valid:
                            collected_info[key] = value
                        else:
                            print(f"❌ [VALIDATION_ERROR] {key}: {error_msg}")
                            # validation 에러가 있어도 무한루프를 방지하기 위해 기본값 사용
                            default_value = _get_default_value_for_field(key, current_stage_info)
                            if default_value:
                                collected_info[key] = default_value
                                print(f"🔄 [FALLBACK] {key}: using default '{default_value}'")

    
    # customer_info_check 단계에서 수정 요청 특별 처리
    if current_stage_id == "customer_info_check":
        print(f"🔍 SINGLE_INFO: customer_info_check processing")
        print(f"  user_input: {user_input}")
        print(f"  collected_info keys: {list(collected_info.keys())}")
        print(f"  scenario_output: {scenario_output}")
        # customer_info_check 단계 진입 시 default 값 설정
        display_fields = current_stage_info.get("display_fields", [])
        if display_fields:
            for field_key in display_fields:
                if field_key not in collected_info:
                    # 시나리오에서 해당 필드의 default 값 찾기
                    for field in active_scenario_data.get("required_info_fields", []):
                        if field.get("key") == field_key and "default" in field:
                            collected_info[field_key] = field["default"]
        
        intent = scenario_output.get("intent", "") if scenario_output else ""
        entities = scenario_output.get("entities", {}) if scenario_output else {}
        
        # 먼저 긍정적 확인 응답을 체크
        is_positive_confirmation = (
            intent == "확인_긍정" or 
            entities.get("confirm_personal_info") == True or
            (user_input and any(word in user_input for word in ["네", "예", "맞아", "맞습니다", "맞어요", "확인", "좋아요"]))
        )
        
        # 긍정적 확인이면 바로 다음 단계로 진행
        if is_positive_confirmation:
            print(f"🔍 SINGLE_INFO: Positive confirmation detected")
            collected_info["confirm_personal_info"] = True
            
            # 시나리오 JSON에서 정의된 다음 단계로 이동
            transitions = current_stage_info.get("transitions", [])
            default_next = current_stage_info.get("default_next_stage_id", "ask_security_medium")
            
            # 긍정 응답에 해당하는 transition 찾기
            next_stage_id = default_next
            for transition in transitions:
                if "맞다고 확인" in transition.get("condition_description", ""):
                    next_stage_id = transition.get("next_stage_id", default_next)
                    break
            
            print(f"🔍 SINGLE_INFO: Transitioning to {next_stage_id}")
            next_stage_info = active_scenario_data.get("stages", {}).get(next_stage_id, {})
            
            # ask_security_medium 스테이지라면 stage_response_data 생성
            if next_stage_id == "ask_security_medium":
                stage_response_data = generate_stage_response(next_stage_info, collected_info, active_scenario_data)
                
                return state.merge_update({
                    "current_scenario_stage_id": next_stage_id,
                    "collected_product_info": collected_info,
                    "stage_response_data": stage_response_data,
                    "is_final_turn_response": True,
                    "action_plan": [],
                    "action_plan_struct": [],
                    "correction_mode": False
                })
            else:
                next_stage_prompt = next_stage_info.get("prompt", "")
                return state.merge_update({
                    "current_scenario_stage_id": next_stage_id,
                    "collected_product_info": collected_info,
                    "final_response_text_for_tts": next_stage_prompt,
                    "is_final_turn_response": True,
                    "action_plan": [],
                    "action_plan_struct": [],
                    "correction_mode": False
                })
        
        # 부정적 응답이나 수정 요청인 경우에만 correction mode 진입
        # 1. 명시적 부정 응답
        is_negative_response = (
            intent == "확인_부정" or 
            entities.get("confirm_personal_info") == False or
            (user_input and any(word in user_input for word in ["아니", "틀렸", "다르", "수정", "변경"]))
        )
        
        # 2. 직접적인 정보 제공 (자연스러운 수정 요청)
        is_direct_info_provision = _is_info_modification_request(user_input, collected_info)
        
        # 3. 새로운 정보가 entities에 포함된 경우
        has_new_info = False
        if entities:
            # customer_name이나 customer_phone이 entities에 있고 기존 정보와 다른 경우
            # confirm_personal_info는 제외 (단순 확인이므로 수정으로 인식하지 않음)
            for field in ["customer_name", "customer_phone"]:
                if field in entities and entities[field] != collected_info.get(field):
                    has_new_info = True
        
        # 위 조건 중 하나라도 해당하면 correction mode로 진입
        if is_negative_response or is_direct_info_provision or has_new_info:
            print(f"  - Negative response: {is_negative_response}")
            print(f"  - Direct info provision: {is_direct_info_provision}")
            print(f"  - Has new info: {has_new_info}")
            
            return state.merge_update({
                "correction_mode": True,
                "action_plan": ["personal_info_correction"],
                "action_plan_struct": [{"action": "personal_info_correction", "reason": "Customer wants to modify info"}],
                "router_call_count": 0,
                "is_final_turn_response": False
            })
    
    # ask_security_medium 단계에서 "네" 응답 처리
    if current_stage_id == "ask_security_medium":
        print(f"🔐 [SECURITY_MEDIUM] Processing with input: '{user_input}'")
        
        expected_info_key = current_stage_info.get("expected_info_key")
        
        # 긍정 응답 처리 ("응...", "네", "예" 등)
        if expected_info_key and user_input and any(word in user_input.lower() for word in ["네", "예", "응", "어", "좋아요", "그래요", "하겠습니다", "등록", "좋아", "알겠"]):
            # 기본값: '신한 OTP' (scenario의 default_choice 사용)
            default_security_medium = current_stage_info.get("default_choice", "신한 OTP")
            collected_info[expected_info_key] = default_security_medium
            print(f"🔐 [SECURITY_MEDIUM] Set {expected_info_key} = {default_security_medium} (user said yes)")
            
        # 부정 응답 처리
        elif expected_info_key and user_input and any(word in user_input.lower() for word in ["아니", "안", "싫", "필요없"]):
            # 부정 응답인 경우 보안카드를 기본으로 설정
            collected_info[expected_info_key] = "보안카드"
            print(f"🔐 [SECURITY_MEDIUM] Set {expected_info_key} = 보안카드 (user said no)")
    
    # additional_services 단계에서 "네" 응답 처리
    if current_stage_id == "additional_services":
        print(f"[ADDITIONAL_SERVICES] Processing with input: '{user_input}'")
        
        service_fields = ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
        has_specific_selections = any(field in collected_info for field in service_fields)
        
        if (not has_specific_selections and user_input and 
            any(word in user_input for word in ["네", "예", "응", "어", "좋아요", "모두", "전부", "다", "신청", "하겠습니다"])):
            # V3 시나리오: choices에서 default 값 확인
            choices = current_stage_info.get("choices", [])
            if choices:
                # boolean 타입 choices 처리
                for choice in choices:
                    field_key = choice.get("key")
                    if field_key and choice.get("default", False):
                        collected_info[field_key] = True
                        print(f"[ADDITIONAL_SERVICES] Set {field_key} = True (from choice default)")
            else:
                # 기존 방식: default_values 사용
                default_values = current_stage_info.get("default_values", {})
                for field in service_fields:
                    if field in default_values:
                        collected_info[field] = default_values[field]
                        print(f"[ADDITIONAL_SERVICES] Set {field} = {default_values[field]}")
    
    # ask_notification_settings 단계에서 "네" 응답 처리 (Entity Agent 결과가 없는 경우에만)
    if current_stage_id == "ask_notification_settings":
        print(f"🔔 [NOTIFICATION] Processing with input: '{user_input}'")
        
        # Entity Agent가 구체적인 선택을 추출하지 못한 경우에만 "네" 처리
        notification_fields = ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
        has_specific_selections = any(field in collected_info for field in notification_fields)
        
        if (not has_specific_selections and user_input and 
            any(word in user_input for word in ["네", "예", "응", "어", "좋아요", "모두", "전부", "다", "신청", "하겠습니다"])):
            # Entity Agent가 선택을 추출하지 못하고 사용자가 일반적인 동의 표현을 한 경우에만 모든 알림을 true로 설정
            print(f"🔔 [NOTIFICATION] No specific selections found, user said yes - setting all notifications to true")
            for field in notification_fields:
                collected_info[field] = True
                print(f"🔔 [NOTIFICATION] Set {field} = True")
        elif has_specific_selections:
            print(f"🔔 [NOTIFICATION] Specific selections found, keeping Entity Agent results")
    
    # 체크카드 관련 단계에서 "네" 응답 처리 (Entity Agent 결과가 없는 경우에만)
    check_card_stages = ["ask_card_receive_method", "ask_card_type", "ask_statement_method", "ask_card_usage_alert", "ask_card_password"]
    if current_stage_id in check_card_stages:
        print(f"💳 [CHECK_CARD] Processing {current_stage_id} with input: '{user_input}'")
        
        expected_info_key = current_stage_info.get("expected_info_key")
        
        
        # Entity Agent가 구체적인 선택을 추출한 경우에는 그 값을 우선시
        if expected_info_key and expected_info_key in collected_info:
            print(f"💳 [CHECK_CARD] Entity Agent found specific value for {expected_info_key}: {collected_info[expected_info_key]}")
        elif (expected_info_key and user_input and 
              any(word in user_input for word in ["네", "예", "응", "어", "좋아요", "그래요", "하겠습니다"])):
            # Entity Agent가 값을 추출하지 못하고 사용자가 일반적인 동의 표현을 한 경우에만 기본값 설정
            default_values = {
                "card_receive_method": "즉시수령",
                "card_type": "S-Line (후불교통)", 
                "statement_method": "휴대폰",
                "card_usage_alert": "5만원 이상 결제 시 발송 (무료)",
                "card_password_same_as_account": True
            }
            
            if expected_info_key in default_values:
                collected_info[expected_info_key] = default_values[expected_info_key]
                print(f"💳 [CHECK_CARD] No specific selection found, set {expected_info_key} = {default_values[expected_info_key]} (user said yes)")
        
    
    # ask_withdrawal_account 단계 특별 처리
    if current_stage_id == "ask_withdrawal_account":
        print(f"🏦 [WITHDRAWAL_ACCOUNT] Processing user input: '{user_input}'")
        print(f"🏦 [WITHDRAWAL_ACCOUNT] Current collected_info: {collected_info}")
        print(f"🏦 [WITHDRAWAL_ACCOUNT] withdrawal_account_registration value: {collected_info.get('withdrawal_account_registration', 'NOT_SET')}")
        
        # Entity Agent가 처리하지 못한 경우에만 폴백 처리
        if 'withdrawal_account_registration' not in collected_info and user_input:
            # "아니요" 응답 처리 - 부정 패턴을 먼저 확인
            if any(word in user_input for word in ["아니", "아니요", "안", "필요없", "괜찮", "나중에", "안할", "미신청"]):
                collected_info["withdrawal_account_registration"] = False
                print(f"🏦 [WITHDRAWAL_ACCOUNT] Fallback: Set withdrawal_account_registration = False")
            # "네" 응답 처리 - 짧은 응답 포함
            elif any(word in user_input for word in ["네", "예", "어", "응", "그래", "좋아", "좋아요", "등록", "추가", "신청", "하겠습니다", "도와", "부탁", "해줘", "해주세요", "알겠", "할게"]):
                collected_info["withdrawal_account_registration"] = True
                print(f"🏦 [WITHDRAWAL_ACCOUNT] Fallback: Set withdrawal_account_registration = True")
    
    # 스테이지 전환 로직 결정
    transitions = current_stage_info.get("transitions", [])
    default_next = current_stage_info.get("default_next_stage_id", "None")
    
    # V3 시나리오의 next_step 처리
    if current_stage_info.get("next_step"):
        next_step = current_stage_info.get("next_step")
        print(f"[V3_NEXT_STEP] Stage: {current_stage_id}, next_step: {next_step}")
        # next_step이 dict 타입인 경우 (값에 따른 분기)
        if isinstance(next_step, dict):
            # V3 시나리오 호환: fields_to_collect 또는 expected_info_key 사용
            expected_field_keys = get_expected_field_keys(current_stage_info)
            main_field_key = expected_field_keys[0] if expected_field_keys else None
            print(f"[V3_NEXT_STEP] main_field_key: {main_field_key}, collected_info: {collected_info}")
            
            # additional_services 특별 처리 - services_selected 값에 따라 분기
            if current_stage_id == "additional_services":
                services_selected = collected_info.get("services_selected")
                print(f"[V3_NEXT_STEP] additional_services branching - services_selected: {services_selected}")
                if services_selected in ["all", "card_only"]:
                    next_stage_id = "card_selection"
                else:
                    next_stage_id = "completion"
            # confirm_personal_info 특별 처리 - 중첩된 next_step 구조
            elif current_stage_id == "confirm_personal_info":
                personal_info_confirmed = collected_info.get("personal_info_confirmed")
                services_selected = collected_info.get("services_selected")
                print(f"[V3_NEXT_STEP] confirm_personal_info - confirmed: {personal_info_confirmed} (type: {type(personal_info_confirmed)}), services: {services_selected}")
                
                # boolean 값을 문자열로 변환하여 next_step과 매핑
                if personal_info_confirmed == True:
                    confirmed_key = "true"
                elif personal_info_confirmed == False:
                    confirmed_key = "false"
                else:
                    # 정보가 수집되지 않았으면 현재 스테이지 유지
                    next_stage_id = current_stage_id
                    print(f"[V3_NEXT_STEP] No personal_info_confirmed value, staying at {current_stage_id}")
                    confirmed_key = None
                
                if confirmed_key:
                    print(f"[V3_NEXT_STEP] Using key '{confirmed_key}' for next_step lookup")
                    if confirmed_key == "true":
                        # true인 경우 services_selected에 따라 분기
                        true_next = next_step.get("true", {})
                        print(f"[V3_NEXT_STEP] true_next structure: {true_next}")
                        if isinstance(true_next, dict):
                            next_stage_id = true_next.get(services_selected, true_next.get("all", "security_medium_registration"))
                            print(f"[V3_NEXT_STEP] Selected next_stage_id: {next_stage_id} for services: {services_selected}")
                        else:
                            next_stage_id = true_next
                    elif confirmed_key == "false":
                        # 개인정보 수정 요청에 대한 특별한 응답 처리
                        if state.get("special_response_for_modification"):
                            print(f"[V3_NEXT_STEP] Special response for personal info modification")
                            return state.merge_update({
                                "final_response_text_for_tts": "[은행 고객정보 변경] 화면으로 이동해드리겠습니다.",
                                "is_final_turn_response": True,
                                "current_scenario_stage_id": current_stage_id,  # 현재 단계 유지
                                "action_plan": [],
                                "action_plan_struct": [],
                                "special_response_for_modification": False  # 플래그 리셋
                            })
                        next_stage_id = next_step.get("false", "customer_info_update")
                        print(f"[V3_NEXT_STEP] False branch - next_stage_id: {next_stage_id}")
            elif main_field_key and main_field_key in collected_info:
                collected_value = collected_info[main_field_key]
                print(f"[V3_NEXT_STEP] collected_value: {collected_value} for field: {main_field_key}")
                next_stage_id = next_step.get(collected_value, default_next)
                print(f"[V3_NEXT_STEP] next_stage_id: {next_stage_id}")
            else:
                # 정보가 수집되지 않았으면 현재 스테이지 유지
                next_stage_id = current_stage_id
                print(f"[V3_NEXT_STEP] No info collected, staying at {current_stage_id}")
        else:
            # next_step이 string인 경우 바로 이동
            next_stage_id = next_step
        
        # V3 시나리오에서 next_step을 사용한 경우 바로 처리하고 반환
        print(f"[V3_NEXT_STEP] Final next_stage_id: {next_stage_id}")
        determined_next_stage_id = next_stage_id
        
        # 스테이지 변경 시 로그
        if determined_next_stage_id != current_stage_id:
            log_node_execution("Stage_Change", f"{current_stage_id} → {determined_next_stage_id}")
        
        # 다음 스테이지 정보 가져오기
        next_stage_info = active_scenario_data.get("stages", {}).get(str(determined_next_stage_id), {})
        
        # stage_response_data 생성
        stage_response_data = None
        if "response_type" in next_stage_info:
            stage_response_data = generate_stage_response(next_stage_info, collected_info, active_scenario_data)
            print(f"🎯 [V3_STAGE_RESPONSE] Generated stage response data for {determined_next_stage_id}")
        
        # 응답 프롬프트 준비
        next_stage_prompt = next_stage_info.get("prompt", "")
        
        # Action plan 정리
        updated_plan = state.get("action_plan", []).copy()
        updated_struct = state.get("action_plan_struct", []).copy()
        if updated_plan:
            updated_plan.pop(0)
        if updated_struct:
            updated_struct.pop(0)
        # Clear action plan when stage changes to prevent re-routing
        if determined_next_stage_id != current_stage_id:
            updated_plan = []
            updated_struct = []
        
        # 최종 응답 생성
        if stage_response_data:
            update_dict = {
                "collected_product_info": collected_info,
                "current_scenario_stage_id": determined_next_stage_id,
                "stage_response_data": stage_response_data,
                "is_final_turn_response": True,
                "action_plan": updated_plan,
                "action_plan_struct": updated_struct
            }
            # bullet 타입인 경우 prompt도 함께 설정
            if next_stage_info.get("response_type") == "bullet" and next_stage_prompt:
                update_dict["final_response_text_for_tts"] = next_stage_prompt
                print(f"🎯 [V3_BULLET_PROMPT] Set final_response_text_for_tts: '{next_stage_prompt[:100]}...'")
            elif next_stage_prompt:  # 다른 response_type이라도 prompt가 있으면 설정
                update_dict["final_response_text_for_tts"] = next_stage_prompt
                print(f"🎯 [V3_PROMPT] Set final_response_text_for_tts: '{next_stage_prompt[:100]}...'")
            return state.merge_update(update_dict)
        else:
            return state.merge_update({
                "collected_product_info": collected_info,
                "current_scenario_stage_id": determined_next_stage_id,
                "final_response_text_for_tts": next_stage_prompt,
                "is_final_turn_response": True,
                "action_plan": updated_plan,
                "action_plan_struct": updated_struct
            })
    
    # Case 1: 분기가 없는 경우 (transitions가 없거나 1개)
    elif len(transitions) <= 1:
        # 필요한 정보가 수집되었는지 확인 (V3 시나리오 호환)
        expected_field_keys = get_expected_field_keys(current_stage_info)
        main_field_key = expected_field_keys[0] if expected_field_keys else None
        if main_field_key and main_field_key not in collected_info:
            # Boolean 타입 필드에 대한 특별 처리
            if current_stage_info.get("input_type") == "yes_no" and user_input:
                # 사용자 입력에서 boolean 값 직접 추출
                user_lower = user_input.lower().strip()
                if user_lower in ["네", "예", "좋아요", "그래요", "맞아요", "신청", "원해요", "할게요", "하겠어요"]:
                    collected_info[main_field_key] = True
                elif user_lower in ["아니요", "아니에요", "안", "필요없", "괜찮", "나중에", "안할", "미신청", "싫어요", "거부"]:
                    collected_info[main_field_key] = False
            
            # Choice 타입 필드에 대한 특별 처리
            elif current_stage_info.get("input_type") == "choice" and user_input:
                # 선택지에서 정확한 매칭 확인
                choices = current_stage_info.get("choices", [])
                user_input_clean = user_input.strip()
                
                # 정확한 value 매칭 우선
                for choice in choices:
                    if choice.get("value") == user_input_clean:
                        collected_info[main_field_key] = user_input_clean
                        break
                else:
                    # value 매칭 실패시 label 매칭 시도
                    for choice in choices:
                        if choice.get("label") == user_input_clean:
                            collected_info[main_field_key] = choice.get("value")
                            break
                    else:
                        # 부분 문자열 매칭 시도
                        for choice in choices:
                            if user_input_clean in choice.get("value", "") or user_input_clean in choice.get("label", ""):
                                collected_info[main_field_key] = choice.get("value")
                                break
            
            # 여전히 정보가 수집되지 않았으면 현재 스테이지 유지
            if main_field_key not in collected_info:
                next_stage_id = current_stage_id
            else:
                # 정보가 수집되었으면 다음 단계로 진행
                if len(transitions) == 1:
                    next_stage_id = transitions[0].get("next_stage_id", default_next)
                else:
                    next_stage_id = default_next
        elif len(transitions) == 1:
            # 단일 전환 경로가 있으면 자동 진행
            next_stage_id = transitions[0].get("next_stage_id", default_next)
        else:
            # transitions이 없으면 default로 진행
            next_stage_id = default_next
    
    # Case 2: 분기가 있는 경우 (transitions가 2개 이상)
    else:
        # ask_card_receive_method 특별 처리
        if current_stage_id == "ask_card_receive_method" and "card_receive_method" in collected_info:
            card_method = collected_info.get("card_receive_method")
            print(f"📦 [CARD_DELIVERY] Processing card delivery method: {card_method}")
            
            # 배송 방법에 따른 분기
            if card_method == "즉시수령":
                next_stage_id = "ask_card_type"
            elif card_method == "집으로 배송":
                next_stage_id = "confirm_home_address"
            elif card_method == "직장으로 배송":
                next_stage_id = "confirm_work_address"
            else:
                next_stage_id = default_next
                
            print(f"📦 [CARD_DELIVERY] Next stage: {next_stage_id}")
        # confirm_home_address 특별 처리
        elif current_stage_id == "confirm_home_address":
            # 사용자의 확인 응답 처리
            if user_input and any(word in user_input.lower() for word in ["네", "예", "맞아요", "맞습니다"]):
                next_stage_id = "ask_card_type"
                print(f"📦 [ADDRESS_CONFIRM] Home address confirmed, proceeding to card type")
            elif user_input and any(word in user_input.lower() for word in ["아니요", "아니", "틀려요", "다른", "수정"]):
                next_stage_id = "update_home_address"
                print(f"📦 [ADDRESS_CONFIRM] Home address needs update")
            else:
                next_stage_id = default_next
        # confirm_work_address 특별 처리
        elif current_stage_id == "confirm_work_address":
            # 사용자의 확인 응답 처리
            if user_input and any(word in user_input.lower() for word in ["네", "예", "맞아요", "맞습니다"]):
                next_stage_id = "ask_card_type"
                print(f"📦 [ADDRESS_CONFIRM] Work address confirmed, proceeding to card type")
            elif user_input and any(word in user_input.lower() for word in ["아니요", "아니", "틀려요", "다른", "수정"]):
                next_stage_id = "update_work_address"
                print(f"📦 [ADDRESS_CONFIRM] Work address needs update")
            else:
                next_stage_id = default_next
        else:
            # 기타 분기가 있는 경우 LLM 판단
            prompt_template = ALL_PROMPTS.get('main_agent', {}).get('determine_next_scenario_stage', '')
            llm_prompt = prompt_template.format(
                active_scenario_name=active_scenario_data.get("scenario_name"),
                current_stage_id=str(current_stage_id),
                current_stage_prompt=current_stage_info.get("prompt", "No prompt"),
                user_input=state.get("stt_result", ""),
                scenario_agent_intent=scenario_output.get("intent", "N/A") if scenario_output else "N/A",
                scenario_agent_entities=str(scenario_output.get("entities", {}) if scenario_output else {}),
                collected_product_info=str(collected_info),
                formatted_transitions=format_transitions_for_prompt(transitions, current_stage_info.get("prompt", "")),
                default_next_stage_id=default_next
            )
            response = await json_llm.ainvoke([HumanMessage(content=llm_prompt)])
            decision_data = next_stage_decision_parser.parse(response.content)
            next_stage_id = decision_data.chosen_next_stage_id

    # --- 로직 전용 스테이지 처리 루프 ---
    while True:
        if not next_stage_id or str(next_stage_id).startswith("END"):
            break  # 종료 상태에 도달하면 루프 탈출

        next_stage_info = active_scenario_data.get("stages", {}).get(str(next_stage_id), {})
        
        # 스테이지에 `prompt`가 있으면 '말하는 스테이지'로 간주하고 루프 탈출
        if next_stage_info.get("prompt"):
            break
        
        # `prompt`가 없는 로직 전용 스테이지인 경우, 자동으로 다음 단계 진행
        
        current_stage_id_for_prompt = str(next_stage_id)
        
        # 루프 내에서 prompt_template 재설정
        prompt_template = ALL_PROMPTS.get('main_agent', {}).get('determine_next_scenario_stage', '')
        llm_prompt = prompt_template.format(
            active_scenario_name=active_scenario_data.get("scenario_name"),
            current_stage_id=current_stage_id_for_prompt,
            current_stage_prompt=next_stage_info.get("prompt", "No prompt"),
            user_input="<NO_USER_INPUT_PROCEED_AUTOMATICALLY>", # 사용자 입력이 없음을 명시
            scenario_agent_intent="automatic_transition",
            scenario_agent_entities=str({}),
            collected_product_info=str(collected_info),
            formatted_transitions=format_transitions_for_prompt(next_stage_info.get("transitions", []), next_stage_info.get("prompt", "")),
            default_next_stage_id=next_stage_info.get("default_next_stage_id", "None")
        )
        response = await json_llm.ainvoke([HumanMessage(content=llm_prompt)])
        decision_data = next_stage_decision_parser.parse(response.content)
        
        next_stage_id = decision_data.chosen_next_stage_id # 다음 스테이지 ID를 갱신하고 루프 계속

    # 최종적으로 결정된 '말하는' 스테이지 ID
    determined_next_stage_id = next_stage_id
    
    # 스테이지 변경 시 로그
    if determined_next_stage_id != current_stage_id:
        log_node_execution("Stage_Change", f"{current_stage_id} → {determined_next_stage_id}")
    
    updated_plan = state.get("action_plan", []).copy()
    if updated_plan:
        updated_plan.pop(0)
    
    updated_struct = state.get("action_plan_struct", []).copy()
    if updated_struct:
        updated_struct.pop(0)
    
    # Clear action plan when stage changes to prevent re-routing
    if determined_next_stage_id != current_stage_id:
        updated_plan = []
        updated_struct = []
    
    # END_SCENARIO에 도달한 경우 end_conversation을 action_plan에 추가
    if str(determined_next_stage_id).startswith("END_SCENARIO"):
        print(f"🔚 [ScenarioLogic] END_SCENARIO detected. Adding end_conversation to action plan.")
        updated_plan.append("end_conversation")
        updated_struct.append({
            "action": "end_conversation",
            "reasoning": "시나리오가 완료되어 상담을 종료합니다."
        })

    # 다음 스테이지의 프롬프트와 response_type 가져오기
    next_stage_prompt = ""
    stage_response_data = None
    
    # 현재 스테이지에 머무는 경우 stage_response_data 생성 (bullet/boolean 타입)
    if determined_next_stage_id == current_stage_id:
        current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
        if current_stage_info.get("response_type") in ["bullet", "boolean"]:
            stage_response_data = generate_stage_response(current_stage_info, collected_info, active_scenario_data)
            print(f"🎯 [STAY_CURRENT_STAGE] Generated stage response data for current stage {current_stage_id} (type: {current_stage_info.get('response_type')})")
            # 현재 단계에 머무는 경우 prompt도 설정
            if current_stage_info.get("prompt") or current_stage_info.get("dynamic_prompt"):
                if current_stage_info.get("dynamic_prompt"):
                    default_choice = get_default_choice_display(current_stage_info)
                    current_prompt = current_stage_info["dynamic_prompt"].replace("{default_choice}", default_choice)
                else:
                    current_prompt = current_stage_info.get("prompt", "")
                next_stage_prompt = current_prompt
                print(f"🎯 [STAY_CURRENT_STAGE] Set prompt for current stage: '{current_prompt[:100]}...')")
    
    # 스테이지별 확인 메시지 추가
    confirmation_msg = ""
    
    # limit_account_guide에서 전환된 경우
    if current_stage_id == "limit_account_guide" and collected_info.get("limit_account_agreement"):
        confirmation_msg = "네, 한도계좌로 진행하겠습니다. "
    
    # ask_transfer_limit에서 전환된 경우
    elif current_stage_id == "ask_transfer_limit":
        per_time = collected_info.get("transfer_limit_per_time")
        per_day = collected_info.get("transfer_limit_per_day")
        if per_time and per_day:
            confirmation_msg = f"1회 이체한도 {per_time:,}만원, 1일 이체한도 {per_day:,}만원으로 설정했습니다. "
        elif per_time:
            confirmation_msg = f"1회 이체한도를 {per_time:,}만원으로 설정했습니다. "
        elif per_day:
            confirmation_msg = f"1일 이체한도를 {per_day:,}만원으로 설정했습니다. "
    
    # ask_notification_settings에서 전환된 경우
    elif current_stage_id == "ask_notification_settings" and determined_next_stage_id == "ask_withdrawal_account":
        notification_settings = []
        if collected_info.get("important_transaction_alert"):
            notification_settings.append("중요거래 알림")
        if collected_info.get("withdrawal_alert"):
            notification_settings.append("출금내역 알림")
        if collected_info.get("overseas_ip_restriction"):
            notification_settings.append("해외IP 제한")
        
        if notification_settings:
            confirmation_msg = f"{', '.join(notification_settings)}을 신청했습니다. "
        else:
            confirmation_msg = "알림 설정을 완료했습니다. "
    
    # ask_card_receive_method에서 전환된 경우
    elif current_stage_id == "ask_card_receive_method" and collected_info.get("card_receive_method"):
        card_method = collected_info.get("card_receive_method")
        if card_method == "즉시수령":
            confirmation_msg = "즉시 수령 가능한 카드로 발급해드리겠습니다. "
        elif card_method == "집으로 배송":
            confirmation_msg = "카드를 집으로 배송해드리겠습니다. "
        elif card_method == "직장으로 배송":
            confirmation_msg = "카드를 직장으로 배송해드리겠습니다. "
    
    # 다른 체크카드 관련 단계들
    elif current_stage_id == "ask_card_type" and collected_info.get("card_type"):
        confirmation_msg = f"{collected_info.get('card_type')} 카드로 발급해드리겠습니다. "
    elif current_stage_id == "ask_statement_method" and collected_info.get("statement_method"):
        confirmation_msg = f"명세서는 {collected_info.get('statement_method')}으로 받으시겠습니다. "
    elif current_stage_id == "ask_card_usage_alert" and collected_info.get("card_usage_alert"):
        confirmation_msg = f"카드 사용 알림을 설정했습니다. "
    elif current_stage_id == "ask_card_password" and "card_password_same_as_account" in collected_info:
        if collected_info.get("card_password_same_as_account"):
            confirmation_msg = "카드 비밀번호를 계좌 비밀번호와 동일하게 설정하겠습니다. "
        else:
            confirmation_msg = "카드 비밀번호를 별도로 설정하겠습니다. "
    
    if determined_next_stage_id and not str(determined_next_stage_id).startswith("END"):
        next_stage_info = active_scenario_data.get("stages", {}).get(str(determined_next_stage_id), {})
        next_stage_prompt = next_stage_info.get("prompt", "")
        
        # final_summary 단계인 경우 템플릿 변수 치환
        if determined_next_stage_id == "final_summary":
            next_stage_prompt = replace_template_variables(next_stage_prompt, collected_info)
        
        # 확인 메시지가 있으면 추가
        if confirmation_msg:
            next_stage_prompt = confirmation_msg + next_stage_prompt
        
        # response_type이 있는 경우 stage_response_data 생성
        if "response_type" in next_stage_info:
            stage_response_data = generate_stage_response(next_stage_info, collected_info, active_scenario_data)
    
    # stage_response_data가 있으면 일반 텍스트 대신 stage_response만 사용
    if stage_response_data:
        update_dict = {
            "collected_product_info": collected_info, 
            "current_scenario_stage_id": determined_next_stage_id,
            "stage_response_data": stage_response_data,
            "is_final_turn_response": True,
            "action_plan": updated_plan,
            "action_plan_struct": updated_struct
        }
        
        # prompt가 있는 경우 final_response_text_for_tts에 설정 (narrative 및 bullet 타입 모두)
        if next_stage_prompt:
            update_dict["final_response_text_for_tts"] = next_stage_prompt
            print(f"🎯 [STAGE_RESPONSE_WITH_TEXT] Set final_response_text_for_tts: '{next_stage_prompt[:100]}...'")
        # 현재 단계에 머무는 경우의 prompt 처리
        elif determined_next_stage_id == current_stage_id and stage_response_data:
            current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
            if current_stage_info.get("dynamic_prompt"):
                default_choice = get_default_choice_display(current_stage_info)
                current_prompt = current_stage_info["dynamic_prompt"].replace("{default_choice}", default_choice)
                update_dict["final_response_text_for_tts"] = current_prompt
                print(f"🎯 [CURRENT_STAGE_DYNAMIC_PROMPT] Set final_response_text_for_tts: '{current_prompt[:100]}...'")
            elif current_stage_info.get("prompt"):
                update_dict["final_response_text_for_tts"] = current_stage_info.get("prompt")
                print(f"🎯 [CURRENT_STAGE_PROMPT] Set final_response_text_for_tts: '{current_stage_info.get('prompt')[:100]}...')")
    else:
        update_dict = {
            "collected_product_info": collected_info, 
            "current_scenario_stage_id": determined_next_stage_id,
            "final_response_text_for_tts": next_stage_prompt,
            "is_final_turn_response": True,
            "action_plan": updated_plan,
            "action_plan_struct": updated_struct
        }
    
    return state.merge_update(update_dict)


def _handle_field_name_mapping(collected_info: Dict[str, Any]) -> None:
    """
    필드명 매핑 처리 - 다양한 형태의 필드명을 표준화된 형태로 변환
    """
    
    # "not specified" 객체 내의 값들을 상위 레벨로 이동
    if "not specified" in collected_info and isinstance(collected_info["not specified"], dict):
        not_specified_data = collected_info.pop("not specified")
        # 기존 값이 없는 경우에만 병합
        for key, value in not_specified_data.items():
            if key not in collected_info:
                collected_info[key] = value
    
    # transfer_limits 객체 처리
    if "transfer_limits" in collected_info and isinstance(collected_info["transfer_limits"], dict):
        transfer_limits = collected_info["transfer_limits"]
        # one_time/daily 필드를 transfer_limit_per_time/day로 변환
        if "one_time" in transfer_limits and "transfer_limit_per_time" not in collected_info:
            collected_info["transfer_limit_per_time"] = transfer_limits["one_time"]
        if "daily" in transfer_limits and "transfer_limit_per_day" not in collected_info:
            collected_info["transfer_limit_per_day"] = transfer_limits["daily"]
        
        # transfer_limits 객체 제거 (이미 변환됨)
        collected_info.pop("transfer_limits", None)
    
    # 한국어 boolean 값을 boolean 타입으로 변환
    boolean_fields = [
        "important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction",
        "limit_account_agreement", "confirm_personal_info", "use_lifelong_account", 
        "use_internet_banking", "use_check_card", "postpaid_transport",
        "withdrawal_account_registration", "card_password_same_as_account"
    ]
    
    
    for field in boolean_fields:
        if field in collected_info:
            current_value = collected_info[field]
            
            if isinstance(current_value, str):
                korean_value = current_value.strip()
                if korean_value in ["신청", "네", "예", "true", "True", "좋아요", "동의", "확인"]:
                    collected_info[field] = True
                elif korean_value in ["미신청", "아니요", "아니", "false", "False", "싫어요", "거부"]:
                    collected_info[field] = False
                else:
                    pass  # 다른 값은 그대로 유지
            else:
                pass  # 스트링 타입이 아닌 경우 그대로 유지
    
    # 기타 필드명 매핑
    field_mappings = {
        "customer_phone": "phone_number",  # customer_phone → phone_number
        # 필요시 추가 매핑 규칙 추가
    }
    
    for old_key, new_key in field_mappings.items():
        if old_key in collected_info and new_key not in collected_info:
            collected_info[new_key] = collected_info.pop(old_key)
    
    # 하위 정보로부터 상위 boolean 값 추론
    # 체크카드 관련 정보가 있으면 use_check_card = True로 추론
    check_card_fields = ["card_type", "card_receive_method", "postpaid_transport", "card_usage_alert", "statement_method"]
    if any(field in collected_info for field in check_card_fields) and "use_check_card" not in collected_info:
        collected_info["use_check_card"] = True
    
    # 인터넷뱅킹 관련 정보가 있으면 use_internet_banking = True로 추론
    ib_fields = ["security_medium", "transfer_limit_per_time", "transfer_limit_per_day", 
                 "important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
    if any(field in collected_info for field in ib_fields) and "use_internet_banking" not in collected_info:
        collected_info["use_internet_banking"] = True
    


def _map_entity_to_valid_choice(field_key: str, entity_value, stage_info: Dict[str, Any]) -> Optional[str]:
    """
    Entity 값을 유효한 choice로 매핑하는 함수 (boolean 값도 처리)
    """
    if entity_value is None or not stage_info.get("choices"):
        return None
    
    choices = stage_info.get("choices", [])
    
    # Boolean 값 특별 처리
    if isinstance(entity_value, bool):
        if field_key == "card_usage_alert":
            if entity_value == False:  # False는 "받지 않음"을 의미
                mapped_value = "결제내역 문자 받지 않음"
                print(f"🔄 [BOOLEAN_MAPPING] {field_key}: {entity_value} → '{mapped_value}'")
                return mapped_value
            else:  # True는 기본값을 의미
                mapped_value = "5만원 이상 결제 시 발송 (무료)"
                print(f"🔄 [BOOLEAN_MAPPING] {field_key}: {entity_value} → '{mapped_value}'")
                return mapped_value
        # 다른 boolean 필드들에 대한 처리도 필요시 여기에 추가
        return None
    
    # 문자열이 아닌 경우 문자열로 변환
    entity_str = str(entity_value)
    entity_lower = entity_str.lower()
    
    # 이미 entity_value가 choices 중 하나와 정확히 일치하는 경우 그대로 반환
    for choice in choices:
        choice_value = choice.get("value", "") if isinstance(choice, dict) else str(choice)
        if entity_str == choice_value:
            print(f"🎯 [EXACT_MATCH] {field_key}: '{entity_value}' is already a valid choice")
            return choice_value
    
    # 각 choice와 부분 매칭 시도
    for choice in choices:
        choice_value = choice.get("value", "") if isinstance(choice, dict) else str(choice)
        choice_lower = choice_value.lower()
        
        # 정확한 매칭 (대소문자 무시)
        if entity_lower == choice_lower:
            return choice_value
        
        # entity가 choice의 핵심 부분과 일치하는 경우에만 매칭
        # 예: "신한 OTP" -> "신한 OTP (비대면 채널용)"
        # 단, 괄호 앞 부분까지만 비교
        choice_core = choice_value.split('(')[0].strip().lower()
        if entity_lower == choice_core:
            print(f"🔍 [CORE_MATCH] {field_key}: '{entity_value}' matches core of '{choice_value}'")
            return choice_value
    
    # 특별한 매핑 규칙
    mapping_rules = {
        "card_type": {
            "s-line 후불": "S-Line (후불교통)",
            "s라인 후불": "S-Line (후불교통)",
            "에스라인 후불": "S-Line (후불교통)",
            "후불교통": "S-Line (후불교통)",
            "s-line 일반": "S-Line (일반)",
            "s라인 일반": "S-Line (일반)",
            "에스라인 일반": "S-Line (일반)",
            "에스라인": "S-Line (후불교통)",  # 기본값은 후불교통
            "s-line": "S-Line (후불교통)",  # 기본값은 후불교통
            "s라인": "S-Line (후불교통)",  # 기본값은 후불교통
            "s-line 카드": "S-Line (후불교통)",  # 기본값은 후불교통
            "s라인 카드": "S-Line (후불교통)",  # 기본값은 후불교통
            "에스라인 카드": "S-Line (후불교통)",  # 기본값은 후불교통
            "딥드립 후불": "딥드립 (후불교통)",
            "딥드립 일반": "딥드립 (일반)",
            "딥드립": "딥드립 (후불교통)",  # 기본값은 후불교통
            "신한카드1": "신한카드1",
            "신한카드2": "신한카드2",
            "신한카드": "신한카드1"  # 기본값은 신한카드1
        },
        "statement_method": {
            "휴대폰": "휴대폰",
            "문자": "휴대폰", 
            "이메일": "이메일",
            "메일": "이메일",
            "홈페이지": "홈페이지",
            "인터넷": "홈페이지"
        },
        "card_receive_method": {
            "즉시": "즉시수령",
            "바로": "즉시수령",
            "지금": "즉시수령",
            "집": "집으로 배송",
            "자택": "집으로 배송",
            "회사": "직장으로 배송",
            "직장": "직장으로 배송"
        },
        "card_usage_alert": {
            "5만원": "5만원 이상 결제 시 발송 (무료)",
            "무료": "5만원 이상 결제 시 발송 (무료)",
            "모든": "모든 내역 발송 (200원, 포인트 우선 차감)",
            "전체": "모든 내역 발송 (200원, 포인트 우선 차감)",
            "200원": "모든 내역 발송 (200원, 포인트 우선 차감)",
            "안받음": "결제내역 문자 받지 않음",
            "받지않음": "결제내역 문자 받지 않음",
            "필요없어요": "결제내역 문자 받지 않음",
            "안해요": "결제내역 문자 받지 않음"
        },
        "security_medium": {
            "신한 otp": "신한 OTP",
            "신한otp": "신한 OTP",
            "otp": "신한 OTP",
            "하나 otp": "하나 OTP",
            "하나otp": "하나 OTP",
            "보안카드": "보안카드",
            "신한플레이": "신한플레이",
            "만원": "신한 OTP (10,000원)",
            "10000원": "신한 OTP (10,000원)"
        }
    }
    
    if field_key in mapping_rules:
        for keyword, mapped_value in mapping_rules[field_key].items():
            if keyword in entity_lower:
                return mapped_value
    
    # 매핑되지 않은 경우 원본 값 그대로 반환 (choices에 있는 경우에만)
    for choice in choices:
        choice_value = choice.get("value", "") if isinstance(choice, dict) else str(choice)
        choice_lower = choice_value.lower()
        
        # 부분 매칭 (entity에 choice가 포함되어 있는 경우)
        if choice_lower in entity_lower:
            return choice_value
        
        # choice에 entity가 포함되어 있는 경우
        if entity_lower in choice_lower:
            return choice_value
    
    return None


def _get_default_value_for_field(field_key: str, stage_info: Dict[str, Any]) -> Optional[str]:
    """
    필드의 기본값을 반환하는 함수
    """
    defaults = {
        "card_type": "S-Line (후불교통)",
        "statement_method": "휴대폰", 
        "card_receive_method": "즉시수령",
        "card_usage_alert": "5만원 이상 결제 시 발송 (무료)",
        "security_medium": "신한 OTP"
    }
    
    return defaults.get(field_key)


def _is_info_modification_request(user_input: str, collected_info: Dict[str, Any]) -> bool:
    """
    자연스러운 정보 수정 요청인지 감지하는 헬퍼 함수
    """
    if not user_input:
        return False
    
    # 간단한 패턴 기반 수정 요청 감지
    import re
    
    # 전화번호 관련 패턴
    phone_patterns = [
        r"뒷번호\s*[\d가-힣]+",
        r"뒤\s*\d{4}",
        r"마지막\s*\d{4}",
        r"끝번호\s*\d{4}",
        r"010[-\s]*\d{3,4}[-\s]*\d{4}",
        r"\d{3}[-\s]*\d{4}[-\s]*\d{4}",
        r"전화번호.*\d{4}",
        r"번호.*\d{4}",
        r"내\s*번호",
        r"제\s*번호"
    ]
    
    # 이름 관련 패턴
    name_patterns = [
        r"이름\s*[가-힣]{2,4}",
        r"성함\s*[가-힣]{2,4}",
        r"제\s*이름",
        r"내\s*이름",
        r"[가-힣]{2,4}\s*(입니다|이에요|예요|라고|야|이야)"
    ]
    
    # 직접적인 정보 제공 패턴 (수정 키워드 없이)
    direct_info_patterns = [
        r"^[가-힣]{2,4}(입니다|이에요|예요|야|이야)$",  # "홍길동이야"
        r"^010[-\s]*\d{3,4}[-\s]*\d{4}$",  # "010-1234-5678"
        r"^\d{4}(이야|예요|이에요)?$",  # "5678이야"
        r"^(내|제)\s*(번호|전화번호|연락처|이름|성함)",  # "내 번호는..."
    ]
    
    # 대조 표현 패턴 (예: "오육칠팔이 아니라 이이오구야")
    contrast_patterns = [
        r"[\d가-힣]+\s*(이|가)?\s*아니라\s*[\d가-힣]+",  # "5678이 아니라 2259"
        r"[\d가-힣]+\s*(이|가)?\s*아니고\s*[\d가-힣]+",  # "5678이 아니고 2259"
        r"[\d가-힣]+\s*(이|가)?\s*아니야\s*[\d가-힣]+",  # "5678이 아니야 2259"
        r"[\d가-힣]+\s*말고\s*[\d가-힣]+",  # "5678 말고 2259"
    ]
    
    # 일반적인 수정 키워드
    modification_keywords = [
        "아니", "틀렸", "다릅", "바꾸", "수정", "변경", "잘못",
        "다시", "아니야"
    ]
    
    user_lower = user_input.lower()
    
    # 대조 표현 패턴 확인 (최우선순위 - "~가 아니라 ~야" 형태)
    for pattern in contrast_patterns:
        if re.search(pattern, user_input, re.IGNORECASE):
            return True
    
    # 직접적인 정보 제공 패턴 확인 (두번째 우선순위)
    for pattern in direct_info_patterns:
        if re.search(pattern, user_input, re.IGNORECASE):
            return True
    
    # 전화번호/이름 패턴 매칭 확인
    for pattern in phone_patterns + name_patterns:
        if re.search(pattern, user_input, re.IGNORECASE):
            return True
    
    # 수정 키워드 확인
    for keyword in modification_keywords:
        if keyword in user_input:
            return True
    
    # 이미 수집된 정보와 다른 새로운 정보가 포함된 경우
    # 예: 기존 전화번호 "010-1234-5678"인데 사용자가 "0987" 같은 새로운 번호 언급
    if collected_info.get("customer_phone"):
        # 한국어 숫자를 변환한 버전도 확인
        from ....agents.info_modification_agent import convert_korean_to_digits
        converted = convert_korean_to_digits(user_input)
        phone_digits = re.findall(r'\d{4}', converted)
        if phone_digits and all(digit not in collected_info["customer_phone"] for digit in phone_digits):
            return True
    
    if collected_info.get("customer_name"):
        # 2글자 이상의 한글 이름 패턴
        names = re.findall(r'[가-힣]{2,4}', user_input)
        for name in names:
            # 일반적인 단어가 아닌 이름일 가능성이 높은 경우
            if (len(name) >= 2 and 
                name != collected_info["customer_name"] and 
                name not in ["이름", "성함", "번호", "전화", "연락처", "정보", "수정", "변경"]):
                return True
    
    return False


def get_default_choice_display(stage_info: Dict[str, Any]) -> str:
    """
    스테이지 정보에서 기본 선택지의 display 텍스트를 반환
    choice_groups 또는 choices에서 default=true인 항목의 display 값을 찾음
    """
    # choice_groups에서 찾기
    if stage_info.get("choice_groups"):
        for group in stage_info["choice_groups"]:
            for choice in group.get("choices", []):
                if choice.get("default"):
                    return choice.get("display", "")
    
    # choices에서 찾기
    if stage_info.get("choices"):
        for choice in stage_info["choices"]:
            if isinstance(choice, dict) and choice.get("default"):
                return choice.get("display", "")
    
    return ""


def generate_stage_response(stage_info: Dict[str, Any], collected_info: Dict[str, Any], scenario_data: Dict = None) -> Dict[str, Any]:
    """단계별 응답 유형에 맞는 데이터 생성"""
    response_type = stage_info.get("response_type", "narrative")
    stage_id = stage_info.get("stage_id", "unknown")
    
    print(f"🎯 [GENERATE_STAGE_RESPONSE] Stage: {stage_id}, Type: {response_type}")
    print(f"🎯 [GENERATE_STAGE_RESPONSE] Has choice_groups: {bool(stage_info.get('choice_groups'))}")
    print(f"🎯 [GENERATE_STAGE_RESPONSE] Has dynamic_prompt: {bool(stage_info.get('dynamic_prompt'))}")
    
    # dynamic_prompt 처리 우선 (V3 시나리오)
    if stage_info.get("dynamic_prompt"):
        default_choice = get_default_choice_display(stage_info)
        prompt = stage_info["dynamic_prompt"].replace("{default_choice}", default_choice)
        print(f"🎯 [DYNAMIC_PROMPT] Used dynamic_prompt with default_choice: '{default_choice}'")
    else:
        prompt = stage_info.get("prompt", "")
    
    
    
    # display_fields가 있는 경우 처리 (bullet 타입)
    if stage_info.get("display_fields"):
        # V3 시나리오: display_fields가 dict인 경우 (실제 값이 포함됨)
        if isinstance(stage_info["display_fields"], dict):
            # display_fields의 값들을 collected_info에 기본값으로 추가
            display_values = stage_info["display_fields"]
            merged_info = {**display_values, **collected_info}  # collected_info가 우선
            prompt = format_prompt_with_fields(prompt, merged_info, list(display_values.keys()), scenario_data)
        else:
            # 기존 방식: display_fields가 list인 경우
            prompt = format_prompt_with_fields(prompt, collected_info, stage_info["display_fields"], scenario_data)
    
    # 템플릿 변수 치환
    prompt = replace_template_variables(prompt, collected_info)
    
    response_data = {
        "stage_id": stage_info.get("stage_id"),
        "stageId": stage_info.get("stage_id"),  # camelCase for frontend compatibility
        "response_type": response_type,
        "responseType": response_type,  # camelCase for frontend compatibility  
        "prompt": prompt,
        "skippable": stage_info.get("skippable", False)
    }
    
    # 선택지가 있는 경우
    if response_type in ["bullet", "boolean"]:
        response_data["choices"] = stage_info.get("choices", [])
        # choice_groups가 있는 경우 추가 (frontend 형식으로 변환)
        if stage_info.get("choice_groups"):
            print(f"🎯 [CHOICE_GROUPS] Found choice_groups in stage_info: {stage_info.get('choice_groups')}")
            choice_groups = []
            for group in stage_info.get("choice_groups", []):
                # choices도 frontend 형식으로 변환
                transformed_choices = []
                for choice in group.get("choices", []):
                    transformed_choice = {
                        "value": choice.get("value", ""),
                        "label": choice.get("display", choice.get("label", "")),
                        "display": choice.get("display", choice.get("label", "")),
                        "default": choice.get("default", False)
                    }
                    # metadata가 있으면 포함
                    if choice.get("metadata"):
                        transformed_choice["metadata"] = choice.get("metadata")
                    transformed_choices.append(transformed_choice)
                    print(f"🎯 [CHOICE_GROUPS] Transformed choice: {transformed_choice}")
                
                transformed_group = {
                    "title": group.get("group_name", ""),
                    "items": transformed_choices
                }
                choice_groups.append(transformed_group)
                print(f"🎯 [CHOICE_GROUPS] Transformed group: {transformed_group}")
            
            response_data["choice_groups"] = choice_groups
            response_data["choiceGroups"] = choice_groups  # camelCase for frontend compatibility
            
            # choice_groups에서 default choice 찾아서 top-level에 설정
            default_choice_value = None
            for group in choice_groups:
                for item in group.get("items", []):
                    if item.get("default"):
                        default_choice_value = item.get("value")
                        break
                if default_choice_value:
                    break
            
            if default_choice_value:
                response_data["default_choice"] = default_choice_value
                response_data["defaultChoice"] = default_choice_value  # camelCase for frontend compatibility
                print(f"🎯 [CHOICE_GROUPS] Set default choice from choice_groups: {default_choice_value}")
            
            print(f"🎯 [CHOICE_GROUPS] Final choice_groups in response_data: {response_data['choice_groups']}")
            print(f"🎯 [CHOICE_GROUPS] Added choiceGroups (camelCase) for frontend compatibility")
            print(f"🎯 [CHOICE_GROUPS] Transformed {len(choice_groups)} groups with {sum(len(g['items']) for g in choice_groups)} total choices for frontend")
        # default_choice가 있는 경우 추가
        if stage_info.get("default_choice"):
            response_data["default_choice"] = stage_info.get("default_choice")
            response_data["defaultChoice"] = stage_info.get("default_choice")  # camelCase for frontend compatibility
        
    
    # 수정 가능한 필드 정보
    if stage_info.get("modifiable_fields"):
        response_data["modifiable_fields"] = stage_info["modifiable_fields"]
        response_data["modifiableFields"] = stage_info["modifiable_fields"]  # camelCase for frontend compatibility
    
    # display_fields 정보 추가 (V3 시나리오)
    if stage_info.get("display_fields"):
        if isinstance(stage_info["display_fields"], dict):
            # V3: display_fields가 실제 값을 포함하는 경우
            display_values = stage_info["display_fields"]
            merged_values = {**display_values, **collected_info}  # collected_info가 우선
            response_data["display_fields"] = merged_values
        else:
            # 기존: display_fields가 필드명 리스트인 경우
            response_data["display_fields"] = stage_info["display_fields"]
    
    return response_data


def format_prompt_with_fields(prompt: str, collected_info: Dict[str, Any], display_fields: List[str], scenario_data: Dict = None) -> str:
    """프롬프트에 수집된 정보 동적 삽입 (기본값 포함)"""
    field_display = []
    
    field_names = {
        "customer_name": "이름",
        "english_name": "영문이름", 
        "resident_number": "주민등록번호",
        "phone_number": "휴대폰번호", 
        "customer_phone": "휴대폰번호",
        "email": "이메일",
        "address": "집주소",
        "work_address": "직장주소"
    }
    
    # 기본값 매핑
    default_values = {
        "customer_name": "홍길동",
        "phone_number": "010-1234-5678", 
        "address": "서울특별시 종로구 숭인동 123"
    }
    
    # 시나리오 데이터에서 기본값 가져오기
    if scenario_data:
        for field in scenario_data.get("required_info_fields", []):
            if field.get("key") in display_fields and field.get("default"):
                default_values[field["key"]] = field["default"]
    
    # 프롬프트에 이미 필드 정보가 포함되어 있는지 확인
    # "- 성함:" 같은 패턴이 이미 있으면 중복 추가하지 않음
    prompt_has_fields = False
    for field_key in display_fields:
        field_name = field_names.get(field_key, field_key)
        if f"- {field_name}:" in prompt:
            prompt_has_fields = True
            break
    
    # 프롬프트에 필드 정보가 없을 때만 추가
    if not prompt_has_fields:
        for field_key in display_fields:
            # 수집된 정보가 있으면 사용, 없으면 기본값 사용
            value = collected_info.get(field_key)
            if not value and field_key in default_values:
                value = default_values[field_key]
            if not value:
                value = "미입력"
                
            field_name = field_names.get(field_key, field_key)
            field_display.append(f"- {field_name}: {value}")
        
        if field_display:
            prompt += "\n" + "\n".join(field_display)
    
    return prompt