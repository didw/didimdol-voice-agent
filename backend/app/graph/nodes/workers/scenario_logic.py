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


async def process_partial_response(
    stage_id: str,
    user_input: str,
    required_fields: List[Dict[str, Any]],
    collected_info: Dict[str, Any],
    field_validators: Dict[str, Any] = None
) -> Dict[str, Any]:
    """부분 응답 처리 및 유효성 검증 - TRD 4.4 구현"""
    
    if field_validators is None:
        field_validators = FIELD_VALIDATORS
    
    # 1. Entity Agent를 통한 개별 필드 추출
    extracted_entities = {}
    if user_input:
        try:
            extraction_result = await entity_agent.extract_entities(user_input, required_fields)
            extracted_entities = extraction_result.get("extracted_entities", {})
        except Exception as e:
            print(f"[DEBUG] Entity extraction error in partial response: {e}")
    
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
    if invalid_fields or missing_fields:
        response_text = generate_re_prompt(
            valid_fields, 
            invalid_fields, 
            missing_fields,
            required_fields
        )
    
    return {
        "collected_info": collected_info,
        "valid_fields": valid_fields,
        "invalid_fields": invalid_fields,
        "missing_fields": missing_fields,
        "response_text": response_text,
        "is_complete": not (invalid_fields or missing_fields)
    }


def generate_re_prompt(
    valid_fields: List[str],
    invalid_fields: List[Dict[str, str]],
    missing_fields: List[Dict[str, Any]],
    all_fields: List[Dict[str, Any]]
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


async def process_multiple_info_collection(state: AgentState, active_scenario_data: Dict, current_stage_id: str, current_stage_info: Dict, collected_info: Dict, scenario_output: Optional[ScenarioAgentOutput], user_input: str) -> AgentState:
    """다중 정보 수집 처리 (개선된 그룹별 방식)"""
    required_fields = active_scenario_data.get("required_info_fields", [])
    
    # 현재 스테이지가 정보 수집 단계인지 확인
    print(f"[DEBUG] Multiple info collection - 현재 스테이지 ID: {current_stage_id}")
    
    # 인터넷뱅킹 정보 수집 스테이지 추가 (greeting 포함)
    info_collection_stages = [
        "greeting", "info_collection_guidance", "process_collected_info", 
        "ask_missing_info_group1", "ask_missing_info_group2", "ask_missing_info_group3", 
        "eligibility_assessment", "collect_internet_banking_info", "ask_remaining_ib_info",
        "collect_check_card_info", "ask_remaining_card_info", "ask_notification_settings",
        "ask_transfer_limit"
    ]
    
    if current_stage_id in info_collection_stages:
        # REQUEST_MODIFY 인텐트는 이제 main_agent_router에서 직접 처리됨
        # scenario_logic에서는 정보 수집에만 집중
        
        # Entity Agent를 사용한 정보 추출
        extraction_result = {"extracted_entities": {}, "collected_info": collected_info}
        
        # ScenarioAgent가 이미 entities를 추출한 경우 Entity Agent 호출 생략
        if scenario_output and hasattr(scenario_output, 'entities') and scenario_output.entities:
            print(f"[DEBUG] Using entities from ScenarioAgent: {scenario_output.entities}")
            
            # entities가 "not specified" 키를 가지고 있고 그 값이 dict인 경우 평탄화
            entities_to_merge = scenario_output.entities.copy()
            if "not specified" in entities_to_merge and isinstance(entities_to_merge["not specified"], dict):
                not_specified_data = entities_to_merge.pop("not specified")
                entities_to_merge.update(not_specified_data)
                print(f"[DEBUG] Flattened entities from 'not specified': {not_specified_data}")
            
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
            try:
                # Entity Agent로 정보 추출 (ScenarioAgent가 추출하지 못한 경우에만)
                print(f"[DEBUG] Calling entity_agent.process_slot_filling with user_input: '{user_input}'")
                extraction_result = await entity_agent.process_slot_filling(user_input, required_fields, collected_info)
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
            print(f"[DEBUG] Entity Agent extraction result - extracted_entities: {extraction_result['extracted_entities']}")
            print(f"[DEBUG] Entity Agent extraction result - valid_entities: {extraction_result.get('valid_entities', {})}")
            print(f"[DEBUG] Entity Agent extraction result - invalid_entities: {extraction_result.get('invalid_entities', {})}")
            
            # 필드명 매핑 적용 (Entity Agent 결과에도)
            _handle_field_name_mapping(collected_info)
            
            print(f"[DEBUG] Final updated collected_info: {collected_info}")
            if extraction_result['extracted_entities']:
                log_node_execution("Entity_Extract", output_info=f"entities={list(extraction_result['extracted_entities'].keys())}")

        # customer_info_check 단계에서 개인정보 확인 처리
        if current_stage_id == "customer_info_check":
            # 추가 수정사항 대기 중인 경우 먼저 체크
            if state.waiting_for_additional_modifications:
                print(f"[DEBUG] Waiting for additional modifications - user input: '{user_input}'")
                
                # 사용자가 추가 수정사항이 없다고 답한 경우
                if user_input and any(word in user_input for word in ["아니", "아니요", "아니야", "없어", "없습니다", "괜찮", "됐어", "충분"]):
                    print(f"[DEBUG] No additional modifications - waiting_for_additional_modifications will be handled in personal_info_correction")
                    # personal_info_correction으로 라우팅하여 처리하도록 함
                    return state.merge_update({
                        "action_plan": ["personal_info_correction"],
                        "action_plan_struct": [{"action": "personal_info_correction", "reason": "Handle no additional modifications"}],
                        "router_call_count": 0,
                        "is_final_turn_response": False
                    })
                elif user_input:
                    # 추가 수정사항이 있는 경우 - personal_info_correction으로 라우팅
                    print(f"[DEBUG] Additional modification requested - routing to personal_info_correction")
                    return state.merge_update({
                        "action_plan": ["personal_info_correction"],
                        "action_plan_struct": [{"action": "personal_info_correction", "reason": "Additional modification requested"}],
                        "router_call_count": 0,
                        "is_final_turn_response": False
                    })
            
            # correction_mode가 활성화된 경우
            # pending_modifications가 있으면 이미 personal_info_correction에서 처리 중이므로 건너뛰기
            elif state.correction_mode and not state.pending_modifications:
                print(f"[DEBUG] Correction mode active - routing to personal_info_correction_node")
                print(f"[DEBUG] Current collected_info: {collected_info}")
                print(f"[DEBUG] Pending modifications: {state.pending_modifications}")
                
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
                print(f"[DEBUG] Natural modification detected in customer_info_check: '{user_input}' - activating correction mode")
                
                return state.merge_update({
                    "correction_mode": True,
                    "action_plan": ["personal_info_correction"],
                    "action_plan_struct": [{"action": "personal_info_correction", "reason": "Natural modification detected"}],
                    "router_call_count": 0,
                    "is_final_turn_response": False
                })
            
            # 이름과 전화번호가 이미 있고, 사용자가 긍정적으로 응답한 경우 바로 다음 단계로
            elif (collected_info.get("customer_name") and 
                  collected_info.get("customer_phone") and
                  (collected_info.get("confirm_personal_info") == True or
                   (user_input and any(word in user_input for word in ["네", "예", "맞아", "맞습니다", "확인"])))):
                
                print(f"[DEBUG] Name and phone confirmed, moving to lifelong account stage")
                
                # confirm_personal_info도 True로 설정
                collected_info["confirm_personal_info"] = True
                
                next_stage_id = "ask_lifelong_account"
                next_stage_prompt = active_scenario_data.get("stages", {}).get("ask_lifelong_account", {}).get("prompt", "평생계좌번호로 등록하시겠어요?")
                
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
            print(f"[DEBUG] Internet Banking Stage - Using specialized agent for: '{user_input}'")
            
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
                        print(f"[DEBUG] IB Agent extracted: {ib_analysis_result['extracted_info']}")
                        
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
            
            print(f"[DEBUG] Internet banking - Complete: {is_ib_complete}, Missing: {missing_ib_fields}")
            print(f"[DEBUG] IB Agent confidence: {ib_analysis_result.get('confidence', 'N/A')}")
            print(f"[DEBUG] Next stage: {next_stage_id}")
            
        elif current_stage_id == "ask_remaining_ib_info":
            # 부족한 인터넷뱅킹 정보 재요청 - 전용 Agent 사용
            print(f"[DEBUG] Remaining IB Info Stage - Using specialized agent for: '{user_input}'")
            
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
                        print(f"[DEBUG] IB Agent extracted (remaining): {ib_analysis_result['extracted_info']}")
                        
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
            print(f"[DEBUG] Check Card Stage - Using specialized agent for: '{user_input}'")
            
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
                            print(f"[DEBUG] Check Card Agent extracted: {field_key} = {value}")
                    
                except Exception as e:
                    print(f"[DEBUG] Check Card Agent error: {e}")
            
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
            
            print(f"[DEBUG] Check card - Complete: {is_cc_complete}, Missing: {missing_cc_fields}")
            print(f"[DEBUG] Next stage: {next_stage_id}")
            
        elif current_stage_id == "ask_remaining_card_info":
            # 부족한 체크카드 정보 재요청 - 전용 Agent 사용
            print(f"[DEBUG] Remaining Card Info Stage - Using specialized agent for: '{user_input}'")
            
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
                            print(f"[DEBUG] Check Card Agent extracted: {field_key} = {value}")
                    
                except Exception as e:
                    print(f"[DEBUG] Check Card Agent error: {e}")
            
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
            
        elif current_stage_id == "ask_transfer_limit":
            # 이체한도 설정 단계 처리 - 개선된 버전
            print(f"[DEBUG] Transfer Limit Stage - Processing: '{user_input}'")
            print(f"[DEBUG] Before processing - collected_info: {collected_info}")
            
            # ScenarioAgent의 entities를 먼저 병합 및 필드명 매핑
            if scenario_output and hasattr(scenario_output, 'entities') and scenario_output.entities:
                print(f"[DEBUG] Found entities from scenario_output: {scenario_output.entities}")
                # "not specified" 중첩 처리
                entities_to_merge = scenario_output.entities.copy()
                if "not specified" in entities_to_merge and isinstance(entities_to_merge["not specified"], dict):
                    not_specified_data = entities_to_merge.pop("not specified")
                    entities_to_merge.update(not_specified_data)
                    print(f"[DEBUG] Flattened entities from 'not specified': {not_specified_data}")
                
                # collected_info에 병합 및 필드명 매핑
                for field_key, value in entities_to_merge.items():
                    if value is not None:
                        # transfer_limits 객체인 경우 특별 처리
                        if field_key == "transfer_limits" and isinstance(value, dict):
                            if "one_time" in value:
                                collected_info["transfer_limit_per_time"] = value["one_time"]
                                print(f"[DEBUG] Extracted transfer_limit_per_time from transfer_limits: {value['one_time']}")
                            if "daily" in value:
                                collected_info["transfer_limit_per_day"] = value["daily"]
                                print(f"[DEBUG] Extracted transfer_limit_per_day from transfer_limits: {value['daily']}")
                        elif field_key in ["transfer_limit_per_time", "transfer_limit_per_day"]:
                            collected_info[field_key] = value
                            print(f"[DEBUG] Merged from scenario_output - {field_key}: {value}")
            
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
                            print(f"[DEBUG] Extracted via Entity Agent - {field_key}: {value}")
                            
                except Exception as e:
                    print(f"[DEBUG] Entity extraction error: {e}")
            
            # 최종 필드명 매핑 재실행 (Entity Agent가 추출한 데이터도 처리)
            _handle_field_name_mapping(collected_info)
            
            per_time_value = collected_info.get("transfer_limit_per_time")
            per_day_value = collected_info.get("transfer_limit_per_day")
            
            print(f"[DEBUG] Current values - per_time: {per_time_value}, per_day: {per_day_value}")
            print(f"[DEBUG] Final collected_info after all processing: {collected_info}")
            
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
            print(f"[DEBUG] === NOTIFICATION SETTINGS STAGE (BOOLEAN TYPE) ===")
            print(f"[DEBUG] User input: '{user_input}'")
            print(f"[DEBUG] Current collected_info: {collected_info}")
            
            # 사용자 입력이 있으면 entities 처리 후 다음 단계로 진행
            if user_input:
                print(f"[DEBUG] Processing user input for notification settings")
                
                # entities 처리 및 boolean 변환
                if scenario_output and scenario_output.entities:
                    entities = scenario_output.entities
                    print(f"[DEBUG] Processing entities: {entities}")
                    
                    # boolean 값들을 collected_info에 저장
                    boolean_fields = ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
                    for field in boolean_fields:
                        if field in entities:
                            value = entities[field]
                            if value in ["신청", "네", "예", "좋아요", "동의"]:
                                collected_info[field] = True
                            elif value in ["미신청", "아니요", "아니", "싫어요", "거부"]:
                                collected_info[field] = False
                            print(f"[DEBUG] Set {field} = {collected_info.get(field)}")
                
                # 다음 단계로 진행
                next_stage_id = current_stage_info.get("default_next_stage_id", "ask_check_card")
                print(f"[DEBUG] Moving to next stage: {next_stage_id}")
                
                # 다음 스테이지 정보 가져오기
                next_stage_info = active_scenario_data.get("stages", {}).get(next_stage_id, {})
                next_stage_prompt = next_stage_info.get("prompt", "")
                
                # 간단한 확인 메시지 + 다음 단계 프롬프트
                response_text = f"알림 설정을 완료했습니다. {next_stage_prompt}"
                
                print(f"[DEBUG] Response: {response_text}")
                print(f"[DEBUG] Updated collected_info: {collected_info}")
                
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
                print(f"[DEBUG] Generated boolean stage_response_data: {stage_response_data}")
                
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
        
        # 다음 스테이지의 stage_response_data 생성
        stage_response_data = None
        if next_stage_id and next_stage_id != current_stage_id:
            next_stage_info = active_scenario_data.get("stages", {}).get(next_stage_id, {})
            if "response_type" in next_stage_info:
                stage_response_data = generate_stage_response(next_stage_info, collected_info, active_scenario_data)
                print(f"[DEBUG] Generated stage_response_data for {next_stage_id}: {stage_response_data}")
        
        # 스테이지가 변경되지 않은 경우와 사용자 입력이 없는 경우에만 is_final_turn_response를 False로 설정
        is_final_response = True
        if next_stage_id == current_stage_id and not user_input:
            is_final_response = False
            print(f"[DEBUG] Same stage and no user input - setting is_final_response = False")
        
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
        print(f"[DEBUG] Stage '{current_stage_id}' not in info_collection_stages, processing as single info collection")
        return await process_single_info_collection(state, active_scenario_data, current_stage_id, current_stage_info, collected_info, state.get("scenario_agent_output"), user_input)


async def process_single_info_collection(state: AgentState, active_scenario_data: Dict, current_stage_id: str, current_stage_info: Dict, collected_info: Dict, scenario_output: Optional[ScenarioAgentOutput], user_input: str) -> AgentState:
    """기존 단일 정보 수집 처리"""

    if scenario_output and scenario_output.get("is_scenario_related"):
        entities = scenario_output.get("entities", {})
        intent = scenario_output.get("intent", "")
        
        print(f"[DEBUG] Single info collection - Stage: {current_stage_id}, Expected key: {current_stage_info.get('expected_info_key')}")
        print(f"[DEBUG] Intent: {intent}, Entities: {entities}")
        
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
                    print(f"--- Entity verification PASSED. Validating against field choices. ---")
                    # Validate entities against field choices
                    engine = SimpleScenarioEngine(active_scenario_data)
                    
                    validation_errors = []
                    for key, value in entities.items():
                        if value is not None:
                            is_valid, error_msg = engine.validate_field_value(key, value)
                            if is_valid:
                                collected_info[key] = value
                                print(f"[DEBUG] Field '{key}' validated successfully, added to collected_info")
                            else:
                                validation_errors.append(f"{key}: {error_msg}")
                                print(f"[DEBUG] Field '{key}' validation failed: {error_msg}")
                    
                    # If there are validation errors, provide guidance
                    if validation_errors:
                        error_response = "죄송합니다, 말씀하신 내용 중 일부를 다시 확인해주세요:\n"
                        error_response += "\n".join(validation_errors)
                        
                        # Stay on current stage and provide guidance
                        return state.merge_update({
                            "current_scenario_stage_id": current_stage_id,
                            "collected_product_info": collected_info,
                            "final_response_text_for_tts": error_response,
                            "is_final_turn_response": True,
                            "action_plan": state.get("action_plan", []),
                            "action_plan_struct": state.get("action_plan_struct", [])
                        })
                else:
                    print(f"--- Entity verification FAILED. Not updating collected info. ---")
            except Exception as e:
                pass

        elif entities:
            # Validate entities against field choices
            engine = SimpleScenarioEngine(active_scenario_data)
            
            validation_errors = []
            for key, value in entities.items():
                if value is not None:
                    is_valid, error_msg = engine.validate_field_value(key, value)
                    if is_valid:
                        collected_info[key] = value
                    else:
                        validation_errors.append(f"{key}: {error_msg}")
            
            # If there are validation errors, provide guidance
            if validation_errors:
                error_response = "죄송합니다, 말씀하신 내용 중 일부를 다시 확인해주세요:\n"
                error_response += "\n".join(validation_errors)
                
                # Stay on current stage and provide guidance
                return state.merge_update({
                    "current_scenario_stage_id": current_stage_id,
                    "collected_product_info": collected_info,
                    "final_response_text_for_tts": error_response,
                    "is_final_turn_response": True,
                    "action_plan": state.get("action_plan", []),
                    "action_plan_struct": state.get("action_plan_struct", [])
                })

        print(f"Updated Info: {collected_info}")
        print(f"Current stage expected_info_key: {current_stage_info.get('expected_info_key')}")
    
    # customer_info_check 단계에서 수정 요청 특별 처리
    if current_stage_id == "customer_info_check":
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
            print(f"[DEBUG] customer_info_check - positive confirmation detected, moving to next stage")
            collected_info["confirm_personal_info"] = True
            
            next_stage_id = "ask_lifelong_account"
            next_stage_prompt = active_scenario_data.get("stages", {}).get("ask_lifelong_account", {}).get("prompt", "평생계좌번호로 등록하시겠어요?")
            
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
                    print(f"[DEBUG] New {field} detected in entities: {entities[field]} (current: {collected_info.get(field)})")
        
        # 위 조건 중 하나라도 해당하면 correction mode로 진입
        if is_negative_response or is_direct_info_provision or has_new_info:
            print(f"[DEBUG] customer_info_check - modification request detected")
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
    
    # 스테이지 전환 로직 결정
    transitions = current_stage_info.get("transitions", [])
    default_next = current_stage_info.get("default_next_stage_id", "None")
    
    # Case 1: 분기가 없는 경우 (transitions가 없거나 1개)
    if len(transitions) <= 1:
        # 필요한 정보가 수집되었는지 확인
        expected_info_key = current_stage_info.get("expected_info_key")
        if expected_info_key and expected_info_key not in collected_info:
            # Boolean 타입 필드에 대한 특별 처리
            if current_stage_info.get("input_type") == "yes_no" and user_input:
                # 사용자 입력에서 boolean 값 직접 추출
                user_lower = user_input.lower().strip()
                if user_lower in ["네", "예", "좋아요", "그래요", "맞아요", "신청", "원해요", "할게요", "하겠어요"]:
                    collected_info[expected_info_key] = True
                    print(f"[DEBUG] Direct boolean extraction for {expected_info_key}: True from '{user_input}'")
                elif user_lower in ["아니요", "아니에요", "안", "필요없", "괜찮", "나중에", "안할", "미신청", "싫어요", "거부"]:
                    collected_info[expected_info_key] = False
                    print(f"[DEBUG] Direct boolean extraction for {expected_info_key}: False from '{user_input}'")
            
            # Choice 타입 필드에 대한 특별 처리
            elif current_stage_info.get("input_type") == "choice" and user_input:
                # 선택지에서 정확한 매칭 확인
                choices = current_stage_info.get("choices", [])
                user_input_clean = user_input.strip()
                
                # 정확한 value 매칭 우선
                for choice in choices:
                    if choice.get("value") == user_input_clean:
                        collected_info[expected_info_key] = user_input_clean
                        print(f"[DEBUG] Direct choice extraction for {expected_info_key}: '{user_input_clean}'")
                        break
                else:
                    # value 매칭 실패시 label 매칭 시도
                    for choice in choices:
                        if choice.get("label") == user_input_clean:
                            collected_info[expected_info_key] = choice.get("value")
                            print(f"[DEBUG] Choice extraction via label for {expected_info_key}: '{choice.get('value')}' from label '{user_input_clean}'")
                            break
                    else:
                        # 부분 문자열 매칭 시도
                        for choice in choices:
                            if user_input_clean in choice.get("value", "") or user_input_clean in choice.get("label", ""):
                                collected_info[expected_info_key] = choice.get("value")
                                print(f"[DEBUG] Choice extraction via partial match for {expected_info_key}: '{choice.get('value')}' from '{user_input_clean}'")
                                break
            
            # 여전히 정보가 수집되지 않았으면 현재 스테이지 유지
            if expected_info_key not in collected_info:
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
    
    # Case 2: 분기가 있는 경우 (transitions가 2개 이상) - LLM 판단
    else:
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
    
    if determined_next_stage_id and not str(determined_next_stage_id).startswith("END"):
        next_stage_info = active_scenario_data.get("stages", {}).get(str(determined_next_stage_id), {})
        next_stage_prompt = next_stage_info.get("prompt", "")
        
        # final_summary 단계인 경우 템플릿 변수 치환
        if determined_next_stage_id == "final_summary":
            next_stage_prompt = replace_template_variables(next_stage_prompt, collected_info)
        
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
    print(f"[DEBUG] Field mapping - Before: {collected_info}")
    
    # "not specified" 객체 내의 값들을 상위 레벨로 이동
    if "not specified" in collected_info and isinstance(collected_info["not specified"], dict):
        not_specified_data = collected_info.pop("not specified")
        # 기존 값이 없는 경우에만 병합
        for key, value in not_specified_data.items():
            if key not in collected_info:
                collected_info[key] = value
        print(f"[DEBUG] Flattened 'not specified' data: {not_specified_data}")
    
    # transfer_limits 객체 처리
    if "transfer_limits" in collected_info and isinstance(collected_info["transfer_limits"], dict):
        transfer_limits = collected_info["transfer_limits"]
        # one_time/daily 필드를 transfer_limit_per_time/day로 변환
        if "one_time" in transfer_limits and "transfer_limit_per_time" not in collected_info:
            collected_info["transfer_limit_per_time"] = transfer_limits["one_time"]
            print(f"[DEBUG] Mapped one_time → transfer_limit_per_time: {transfer_limits['one_time']}")
        if "daily" in transfer_limits and "transfer_limit_per_day" not in collected_info:
            collected_info["transfer_limit_per_day"] = transfer_limits["daily"]
            print(f"[DEBUG] Mapped daily → transfer_limit_per_day: {transfer_limits['daily']}")
        
        # transfer_limits 객체 제거 (이미 변환됨)
        collected_info.pop("transfer_limits", None)
    
    # 한국어 boolean 값을 boolean 타입으로 변환
    boolean_fields = [
        "important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction",
        "limit_account_agreement", "confirm_personal_info", "use_lifelong_account", 
        "use_internet_banking", "use_check_card", "postpaid_transport"
    ]
    
    print(f"[DEBUG] Processing boolean conversion for fields: {boolean_fields}")
    
    for field in boolean_fields:
        if field in collected_info:
            current_value = collected_info[field]
            print(f"[DEBUG] Checking field '{field}': value='{current_value}', type={type(current_value)}")
            
            if isinstance(current_value, str):
                korean_value = current_value.strip()
                if korean_value in ["신청", "네", "예", "true", "True", "좋아요", "동의", "확인"]:
                    collected_info[field] = True
                    print(f"[DEBUG] Converted '{korean_value}' → True for {field}")
                elif korean_value in ["미신청", "아니요", "아니", "false", "False", "싫어요", "거부"]:
                    collected_info[field] = False
                    print(f"[DEBUG] Converted '{korean_value}' → False for {field}")
                else:
                    print(f"[DEBUG] No conversion rule for '{korean_value}' in field {field}")
            else:
                print(f"[DEBUG] Field '{field}' is not a string, skipping conversion")
    
    # 기타 필드명 매핑
    field_mappings = {
        "customer_phone": "phone_number",  # customer_phone → phone_number
        # 필요시 추가 매핑 규칙 추가
    }
    
    for old_key, new_key in field_mappings.items():
        if old_key in collected_info and new_key not in collected_info:
            collected_info[new_key] = collected_info.pop(old_key)
            print(f"[DEBUG] Mapped {old_key} → {new_key}: {collected_info[new_key]}")
    
    # 하위 정보로부터 상위 boolean 값 추론
    # 체크카드 관련 정보가 있으면 use_check_card = True로 추론
    check_card_fields = ["card_type", "card_receive_method", "postpaid_transport", "card_usage_alert", "statement_method"]
    if any(field in collected_info for field in check_card_fields) and "use_check_card" not in collected_info:
        collected_info["use_check_card"] = True
        print(f"[DEBUG] Inferred use_check_card = True from existing card fields: {[f for f in check_card_fields if f in collected_info]}")
    
    # 인터넷뱅킹 관련 정보가 있으면 use_internet_banking = True로 추론
    ib_fields = ["security_medium", "transfer_limit_per_time", "transfer_limit_per_day", 
                 "important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
    if any(field in collected_info for field in ib_fields) and "use_internet_banking" not in collected_info:
        collected_info["use_internet_banking"] = True
        print(f"[DEBUG] Inferred use_internet_banking = True from existing IB fields: {[f for f in ib_fields if f in collected_info]}")
    
    print(f"[DEBUG] Field mapping - After: {collected_info}")


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
            print(f"[DEBUG] Contrast expression pattern match: {pattern}")
            return True
    
    # 직접적인 정보 제공 패턴 확인 (두번째 우선순위)
    for pattern in direct_info_patterns:
        if re.search(pattern, user_input, re.IGNORECASE):
            print(f"[DEBUG] Direct info provision pattern match: {pattern}")
            return True
    
    # 전화번호/이름 패턴 매칭 확인
    for pattern in phone_patterns + name_patterns:
        if re.search(pattern, user_input, re.IGNORECASE):
            print(f"[DEBUG] Pattern match for modification: {pattern}")
            return True
    
    # 수정 키워드 확인
    for keyword in modification_keywords:
        if keyword in user_input:
            print(f"[DEBUG] Modification keyword detected: {keyword}")
            return True
    
    # 이미 수집된 정보와 다른 새로운 정보가 포함된 경우
    # 예: 기존 전화번호 "010-1234-5678"인데 사용자가 "0987" 같은 새로운 번호 언급
    if collected_info.get("customer_phone"):
        # 한국어 숫자를 변환한 버전도 확인
        from ....agents.info_modification_agent import convert_korean_to_digits
        converted = convert_korean_to_digits(user_input)
        phone_digits = re.findall(r'\d{4}', converted)
        if phone_digits and all(digit not in collected_info["customer_phone"] for digit in phone_digits):
            print(f"[DEBUG] New phone number detected that differs from existing: {phone_digits}")
            return True
    
    if collected_info.get("customer_name"):
        # 2글자 이상의 한글 이름 패턴
        names = re.findall(r'[가-힣]{2,4}', user_input)
        for name in names:
            # 일반적인 단어가 아닌 이름일 가능성이 높은 경우
            if (len(name) >= 2 and 
                name != collected_info["customer_name"] and 
                name not in ["이름", "성함", "번호", "전화", "연락처", "정보", "수정", "변경"]):
                print(f"[DEBUG] New name detected that differs from existing: {name}")
                return True
    
    return False


def generate_stage_response(stage_info: Dict[str, Any], collected_info: Dict[str, Any], scenario_data: Dict = None) -> Dict[str, Any]:
    """단계별 응답 유형에 맞는 데이터 생성"""
    response_type = stage_info.get("response_type", "narrative")
    prompt = stage_info.get("prompt", "")
    
    # display_fields가 있는 경우 처리 (bullet 타입)
    if stage_info.get("display_fields"):
        prompt = format_prompt_with_fields(prompt, collected_info, stage_info["display_fields"], scenario_data)
    
    # 템플릿 변수 치환
    prompt = replace_template_variables(prompt, collected_info)
    
    response_data = {
        "stage_id": stage_info.get("id"),
        "response_type": response_type,
        "prompt": prompt,
        "skippable": stage_info.get("skippable", False)
    }
    
    # 선택지가 있는 경우
    if response_type in ["bullet", "boolean"]:
        response_data["choices"] = stage_info.get("choices", [])
    
    # 수정 가능한 필드 정보
    if stage_info.get("modifiable_fields"):
        response_data["modifiable_fields"] = stage_info["modifiable_fields"]
    
    return response_data


def format_prompt_with_fields(prompt: str, collected_info: Dict[str, Any], display_fields: List[str], scenario_data: Dict = None) -> str:
    """프롬프트에 수집된 정보 동적 삽입 (기본값 포함)"""
    field_display = []
    
    field_names = {
        "customer_name": "성함",
        "phone_number": "연락처", 
        "customer_phone": "연락처",
        "address": "집주소"
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