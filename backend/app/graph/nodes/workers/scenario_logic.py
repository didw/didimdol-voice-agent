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
from ....config.prompt_loader import load_yaml_file
from pathlib import Path
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

# 리팩토링된 모듈에서 import
from .scenario_utils import (
    create_update_dict_with_last_prompt,
    find_scenario_guidance,
    format_korean_currency,
    format_field_value,
    get_default_choice_display,
    get_expected_field_keys,
    get_stage_relevant_fields
)
from .intent_mapping import (
    map_user_intent_to_choice,
    map_user_intent_to_choice_enhanced,
    handle_additional_services_mapping,
    handle_card_selection_mapping,
    apply_additional_services_values,
    handle_additional_services_fallback,
    fallback_keyword_matching,
    _is_info_modification_request
)
from .response_generation import (
    generate_natural_response,
    generate_choice_clarification_response,
    generate_choice_confirmation_response,
    generate_confirmation_message,
    generate_re_prompt,
    generate_final_confirmation_prompt
)
from .field_extraction import (
    process_partial_response,
    extract_field_value_with_llm,
    extract_any_field_value_with_llm,
    detect_newly_extracted_values,
    _handle_field_name_mapping,
    _map_entity_to_valid_choice,
    _get_default_value_for_field
)
from .stage_response import (
    generate_stage_response,
    format_prompt_with_fields
)


from ...chains import generative_llm, json_llm


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
            # [DISABLED] - Exact match를 비활성화하고 항상 LLM을 통해 의미를 이해하도록 변경
            exact_choice_match = False
            # if current_stage_info.get("choices"):
            #     choices = current_stage_info.get("choices", [])
            #     expected_field_keys = get_expected_field_keys(current_stage_info)
            #     expected_field = expected_field_keys[0] if expected_field_keys else None
            #     
            #     for choice in choices:
            #         choice_value = choice.get("value", "") if isinstance(choice, dict) else str(choice)
            #         if user_input.strip() == choice_value:
            #             # 정확한 매치 발견 - Entity Agent를 거치지 않고 직접 저장
            #             print(f"✅ [EXACT_CHOICE_MATCH] Found exact match: '{user_input}' for field '{expected_field}'")
            #             if expected_field:
            #                 collected_info[expected_field] = user_input.strip()
            #                 extraction_result = {
            #                     "collected_info": collected_info,
            #                     "extracted_entities": {expected_field: user_input.strip()},
            #                     "message": "Exact choice match found"
            #                 }
            #                 exact_choice_match = True
            #                 break
            
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
                    
                    # 유연한 추출 방식 사용
                    extraction_result = await entity_agent.extract_entities_flexibly(
                        user_input, 
                        stage_relevant_fields,
                        current_stage_id,
                        current_stage_info,
                        state.last_llm_prompt  # 이전 AI 질문 전달
                    )
                    
                    # 의도 분석 결과를 extraction_result에 추가 (자연어 응답 생성에 활용)
                    if hasattr(entity_agent, 'last_intent_analysis') and entity_agent.last_intent_analysis:
                        extraction_result['intent_analysis'] = entity_agent.last_intent_analysis
                    
                    # 추출된 엔티티를 collected_info에 병합
                    if extraction_result.get("extracted_entities"):
                        collected_info.update(extraction_result["extracted_entities"])
                        extraction_result["collected_info"] = collected_info
                    
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

        # final_confirmation 단계에서 최종 확인 메시지 생성
        if current_stage_id == "final_confirmation":
            confirmation_prompt = generate_final_confirmation_prompt(collected_info)
            current_stage_info["prompt"] = confirmation_prompt
            print(f"🎯 [FINAL_CONFIRMATION] Generated dynamic prompt: {confirmation_prompt}")
            
            # 사용자 응답이 있으면 final_confirmation 필드 설정
            if user_input:
                positive_keywords = ["네", "예", "좋아요", "그래요", "맞아요", "진행", "할게요", "하겠어요", "확인"]
                negative_keywords = ["아니요", "아니에요", "안", "수정", "다시", "아직", "잠깐"]
                
                user_input_lower = user_input.lower().strip()
                
                # 부정 키워드 우선 체크
                if any(keyword in user_input_lower for keyword in negative_keywords):
                    collected_info["final_confirmation"] = False
                    print(f"🎯 [FINAL_CONFIRMATION] User declined: {user_input}")
                    # 사용자가 수정을 원하는 경우 수정 모드로 전환
                    state.correction_mode = True
                    response_data["response_type"] = "narrative"
                    response_data["prompt"] = "어떤 부분을 수정하고 싶으신가요? 수정하실 항목을 말씀해주세요."
                # 긍정 키워드 체크
                elif any(keyword in user_input_lower for keyword in positive_keywords):
                    collected_info["final_confirmation"] = True
                    print(f"🎯 [FINAL_CONFIRMATION] User confirmed: {user_input}")
                else:
                    print(f"🎯 [FINAL_CONFIRMATION] Unclear response: {user_input}")
                    # 명확하지 않은 응답의 경우 Entity Agent에게 처리를 맡김
        
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
            # statement_delivery, card_selection, additional_services 등 시나리오 단계에서는 개인정보 수정으로 판단하지 않음
            else:
                scenario_stages_exclude = ["statement_delivery", "card_selection", "additional_services", "card_usage_alert", "security_medium_registration"]
                if (not state.correction_mode and 
                      not state.pending_modifications and 
                      current_stage_id not in scenario_stages_exclude and
                      _is_info_modification_request(user_input, collected_info)):
                    
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
                        update_dict = {
                            "current_scenario_stage_id": next_stage_id,
                            "collected_product_info": collected_info,
                            "final_response_text_for_tts": next_stage_prompt,
                            "is_final_turn_response": True,
                            "action_plan": [],
                            "action_plan_struct": [],
                            "correction_mode": False  # 수정 모드 해제
                        }
                        # last_llm_prompt 저장
                        update_dict = create_update_dict_with_last_prompt(update_dict)
                        return state.merge_update(update_dict)
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
                
                update_dict = {
                    "current_scenario_stage_id": next_stage_id,
                    "collected_product_info": collected_info,
                    "final_response_text_for_tts": response_text,
                    "is_final_turn_response": True,
                    "action_plan": [],
                    "action_plan_struct": [],
                    "router_call_count": 0
                }
                # last_llm_prompt 저장
                update_dict = create_update_dict_with_last_prompt(update_dict)
                return state.merge_update(update_dict)
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
                        print(f"🔥🔥🔥 [FORCE] ✅ {field}: '{str_value}' -> TRUE")
                    elif str_value in ["미신청", "아니요", "아니", "싫어요", "거부", "안할게요", "필요없어요", "안받을게요"]:
                        collected_info[field] = False  
                        print(f"🔥🔥🔥 [FORCE] ✅ {field}: '{str_value}' -> FALSE")
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
                
                
                update_dict = {
                    "current_scenario_stage_id": next_stage_id,
                    "collected_product_info": collected_info,
                    "final_response_text_for_tts": response_text,
                    "is_final_turn_response": True,
                    "action_plan": [],
                    "action_plan_struct": [],
                    "router_call_count": 0
                }
                # last_llm_prompt 저장
                update_dict = create_update_dict_with_last_prompt(update_dict)
                return state.merge_update(update_dict)
            
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
            log_node_execution("Stage_Change", f"{current_stage_id} -> {next_stage_id}")
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
        
        # card_password_setting 단계 - LLM 기반 유연한 처리
        elif current_stage_id == "card_password_setting":
            try:
                # EntityRecognitionAgent 임포트
                from app.agents.entity_agent import EntityRecognitionAgent
                entity_agent = EntityRecognitionAgent()
                
                intent_result = await entity_agent.analyze_user_intent(
                    user_input,
                    current_stage_id,
                    current_stage_info,
                    collected_info
                )
                
                # "똑같이 해줘" 같은 표현 처리
                if intent_result.get("intent") == "긍정" or intent_result.get("intent") == "동일_비밀번호":
                    collected_info["card_password_same_as_account"] = True
                    print(f"[CARD_PASSWORD] LLM detected same password request -> True")
                elif intent_result.get("intent") == "다른_비밀번호" or intent_result.get("intent") == "부정":
                    collected_info["card_password_same_as_account"] = False
                    print(f"[CARD_PASSWORD] LLM detected different password request -> False")
                else:
                    # Fallback to pattern matching
                    if any(word in user_lower for word in ["네", "예", "응", "어", "그래", "좋아", "맞아", "알겠", "동일", "같게", "똑같이"]):
                        collected_info["card_password_same_as_account"] = True
                        print(f"[CARD_PASSWORD] Pattern match '네' -> True")
                    elif any(word in user_lower for word in ["아니", "다르게", "따로", "별도"]):
                        collected_info["card_password_same_as_account"] = False
                        print(f"[CARD_PASSWORD] Pattern match '아니' -> False")
            except Exception as e:
                print(f"[CARD_PASSWORD] Intent analysis failed: {e}")
                # Fallback
                if any(word in user_lower for word in ["네", "예", "응", "어", "그래", "좋아", "맞아", "알겠", "동일", "같게"]):
                    collected_info["card_password_same_as_account"] = True
                elif any(word in user_lower for word in ["아니", "다르게", "따로", "별도"]):
                    collected_info["card_password_same_as_account"] = False
        
        # additional_services 단계 - 새로운 LLM 기반 처리로 대체됨
        elif current_stage_id == "additional_services":
            # 이전 entity_agent 로직은 비활성화됨 - 새로운 LLM 기반 선택적 처리 사용
            print(f"[ADDITIONAL_SERVICES] Stage processing - delegating to new LLM-based selective processing")
            pass
    
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
                    if current_stage_info.get("choice_groups"):
                        for group in current_stage_info.get("choice_groups", []):
                            for choice in group.get("choices", []):
                                if choice.get("default"):
                                    default_choice = choice.get("value")
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
                                # 모든 보안매체에 대해 최대 이체한도 설정
                                elif field_key == "transfer_limit_once":
                                    collected_info[field_key] = "50000000"  # 5천만원
                                    print(f"[DEFAULT_SELECTION] Stage {current_stage_id}: '네' response mapped {field_key} to: 50000000")
                                elif field_key == "transfer_limit_daily":
                                    collected_info[field_key] = "100000000"  # 1억원
                                    print(f"[DEFAULT_SELECTION] Stage {current_stage_id}: '네' response mapped {field_key} to: 100000000")
                
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
                    
                    if default_choice:
                        # 각 필드별로 적절한 값 설정
                        for field_key in fields_to_collect:
                            if field_key not in collected_info:
                                if field_key == "statement_delivery_method":
                                    collected_info[field_key] = default_choice
                                    print(f"[DEFAULT_SELECTION] Stage {current_stage_id}: '네' response mapped {field_key} to: {default_choice}")
                                # 모든 수령방법에 대해 발송일 10일로 설정
                                elif field_key == "statement_delivery_date":
                                    collected_info[field_key] = "10"
                                    print(f"[DEFAULT_SELECTION] Stage {current_stage_id}: '네' response mapped {field_key} to: 10")
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
        print(f"🎯 [V3_CHOICE_PROCESSING] fields_to_collect: {fields_to_collect}")
        print(f"🎯 [V3_CHOICE_PROCESSING] user_input: '{user_input}'")
        
        # LLM 기반 자연어 필드 추출 - 복수 필드 동시 추출 가능
        choice_mapping = None
        extracted_fields = {}  # 여러 필드 저장용
        
        # 카드 선택 단계 특별 처리 - choices value와 직접 매칭 먼저 시도
        if current_stage_id == "card_selection":
            choice_mapping = handle_card_selection_mapping(user_input, choices, current_stage_info, collected_info)
            if choice_mapping:
                print(f"🎯 [CARD_SELECTION] Direct choice mapping successful: {choice_mapping}")
        
        # 복수 필드 추출을 위한 LLM 분석 먼저 시도
        if user_input and not choice_mapping:
            # Entity Agent를 통한 의도 분석
            from app.agents.entity_agent import EntityRecognitionAgent
            entity_agent = EntityRecognitionAgent()
            
            intent_analysis = await entity_agent.analyze_user_intent(
                user_input=user_input,
                current_stage=current_stage_id,
                stage_info=current_stage_info,
                collected_info=collected_info
            )
            
            # 추출된 정보가 있으면 처리
            if intent_analysis.get("extracted_info"):
                print(f"🎯 [MULTI_FIELD_EXTRACTION] Extracted info: {intent_analysis['extracted_info']}")
                
                # 각 필드를 확인하고 저장
                for field_key, field_value in intent_analysis["extracted_info"].items():
                    # 현재 단계에서 수집 가능한 필드인지 확인
                    if field_key in fields_to_collect:
                        extracted_fields[field_key] = field_value
                        print(f"✅ [MULTI_FIELD_STORED] {field_key}: '{field_value}'")
            
            # statement_delivery 단계에서 LLM이 실패한 경우 간단한 패턴 매칭 시도
            if current_stage_id == "statement_delivery" and not extracted_fields:
                import re
                # 날짜 추출
                date_match = re.search(r'(\d+)일', user_input)
                if date_match:
                    date_value = date_match.group(1)
                    if 1 <= int(date_value) <= 31:
                        extracted_fields["statement_delivery_date"] = date_value
                        print(f"✅ [FALLBACK_EXTRACTION] statement_delivery_date: '{date_value}'")
                
                # 배송 방법 추출
                if "이메일" in user_input:
                    extracted_fields["statement_delivery_method"] = "email"
                    print(f"✅ [FALLBACK_EXTRACTION] statement_delivery_method: 'email'")
                elif "휴대폰" in user_input or "모바일" in user_input or "문자" in user_input:
                    extracted_fields["statement_delivery_method"] = "mobile"
                    print(f"✅ [FALLBACK_EXTRACTION] statement_delivery_method: 'mobile'")
                elif "홈페이지" in user_input or "웹" in user_input:
                    extracted_fields["statement_delivery_method"] = "website"
                    print(f"✅ [FALLBACK_EXTRACTION] statement_delivery_method: 'website'")
                
                # 주 필드 (expected_field) 값 설정
                if expected_field and expected_field in extracted_fields:
                    choice_mapping = extracted_fields[expected_field]
            
            # "똑같이 해줘" 같은 표현 처리
            if intent_analysis.get("intent") == "긍정" and not choice_mapping:
                # 현재 질문에 기본값이 제시되어 있는지 확인
                prompt = current_stage_info.get("prompt", "")
                # 예: "카드 비밀번호는 계좌 비밀번호와 동일하게 설정하시겠어요?"
                if "동일하게" in prompt or "같게" in prompt:
                    # 기본값을 true로 설정
                    if expected_field == "card_password_same_as_account":
                        choice_mapping = "true"
                        print(f"🎯 [DEFAULT_ACCEPTANCE] '똑같이 해줘' -> {expected_field}: true")
        
        if not choice_mapping:
            # select_services 단계에서 명확한 키워드가 있으면 직접 매핑
            if current_stage_id == "select_services" and user_input:
                user_lower = user_input.lower().strip()
                if "체크카드만" in user_lower or "카드만" in user_lower:
                    choice_mapping = "card_only"
                    print(f"🎯 [DIRECT_MAPPING] '체크카드만/카드만' detected -> card_only")
                elif "계좌만" in user_lower or "통장만" in user_lower or "입출금만" in user_lower:
                    choice_mapping = "account_only"
                    print(f"🎯 [DIRECT_MAPPING] '계좌만/통장만/입출금만' detected -> account_only")
                elif "모바일만" in user_lower or "앱만" in user_lower:
                    choice_mapping = "mobile_only"
                    print(f"🎯 [DIRECT_MAPPING] '모바일만/앱만' detected -> mobile_only")
                elif any(word in user_lower for word in ["다", "모두", "전부", "함께"]):
                    choice_mapping = "all"
                    print(f"🎯 [DIRECT_MAPPING] '다/모두/전부/함께' detected -> all")
            
            # 직접 매핑이 안된 경우에만 LLM 사용
            if not choice_mapping:
                # 시나리오의 extraction_prompt 활용
                extraction_prompt = current_stage_info.get("extraction_prompt", "")
                if extraction_prompt:
                    # field_info 구성
                    field_info = {
                        "type": "choice",
                        "choices": choices,
                        "display_name": expected_field,
                        "extraction_prompt": extraction_prompt
                    }
                    choice_mapping = await extract_field_value_with_llm(
                        user_input, 
                        expected_field,
                        field_info,
                        collected_info,
                        current_stage_id
                    )
        else:
            # 기본 LLM 기반 매핑
            choice_mapping = await map_user_intent_to_choice_enhanced(
                user_input, 
                choices, 
                expected_field,
                None,  # keyword_mapping
                current_stage_info,  # stage_info
                collected_info  # collected_info
            )
        
        # DEFAULT_SELECTION으로 이미 값이 설정된 경우 LLM 매핑 건너뛰기
        already_default_selected = False
        if expected_field and expected_field in collected_info:
            # 긍정 응답인 경우 DEFAULT_SELECTION 값 유지
            if user_input and any(word in user_input.lower() for word in ["네", "예", "응", "어", "좋아", "맞아", "알겠"]):
                already_default_selected = True
                print(f"🎯 [DEFAULT_PROTECTED] {expected_field} already set by DEFAULT_SELECTION: '{collected_info[expected_field]}', skipping LLM mapping")
        
        # DEFAULT_SELECTION으로 값이 설정된 경우 확인 응답 생성
        if already_default_selected:
            print(f"🎯 [DEFAULT_SELECTION_CONFIRMATION] Generating confirmation response for DEFAULT_SELECTION")
            
            # card_selection 단계 특별 확인 응답
            if current_stage_id == "card_selection":
                # 카드 선택 확인 메시지 생성
                card_selection_value = collected_info.get("card_selection")
                receipt_method_value = collected_info.get("card_receipt_method")
                transit_function_value = collected_info.get("transit_function")
                
                # 카드명 표시용 매핑
                card_display_names = {
                    "sline_transit": "S-Line 후불교통카드",
                    "sline_general": "S-Line 일반카드",
                    "deepdrip_transit": "딥드립 후불교통카드",
                    "deepdrip_general": "딥드립 일반카드"
                }
                
                card_name = card_display_names.get(card_selection_value, card_selection_value)
                receipt_method_display = "즉시발급" if receipt_method_value == "즉시발급" else "배송"
                
                if transit_function_value:
                    confirmation_response = f"네, {card_name}를 {receipt_method_display}으로 신청해드리겠습니다. 후불교통 기능도 함께 설정됩니다."
                else:
                    confirmation_response = f"네, {card_name}를 {receipt_method_display}으로 신청해드리겠습니다."
                    
                print(f"🎯 [DEFAULT_SELECTION_CONFIRMATION] Generated card_selection confirmation: {confirmation_response}")
            
            # 다른 단계들의 기본 확인 응답
            else:
                field_value = collected_info[expected_field]
                # choice_display 찾기
                choice_display = field_value
                for choice in choices:
                    if isinstance(choice, dict) and choice.get("value") == field_value:
                        choice_display = choice.get("display", field_value)
                        break
                
                confirmation_response = generate_choice_confirmation_response(
                    choice_value=field_value,
                    choice_display=choice_display,
                    field_key=expected_field,
                    stage_info=current_stage_info
                )
                print(f"🎯 [DEFAULT_SELECTION_CONFIRMATION] Generated generic confirmation: {confirmation_response}")
            
            # 다음 단계 확인
            next_step = current_stage_info.get("next_step")
            next_stage_id = current_stage_id  # 기본값은 현재 단계 유지
            
            if next_step:
                if isinstance(next_step, dict):
                    # expected_field 값에 따른 분기 처리
                    field_value = collected_info[expected_field]
                    next_stage_id = next_step.get(field_value, next_step.get("default", current_stage_id))
                    print(f"🎯 [DEFAULT_SELECTION_NEXT] {expected_field}='{field_value}' -> next_stage: {next_stage_id}")
                elif isinstance(next_step, str):
                    next_stage_id = next_step
                    print(f"🎯 [DEFAULT_SELECTION_NEXT] Direct next_stage: {next_stage_id}")
            else:
                # next_step이 없으면 transitions나 default_next_stage_id 사용
                transitions = current_stage_info.get("transitions", [])
                default_next = current_stage_info.get("default_next_stage_id")
                
                # 긍정 응답에 해당하는 transition 찾기
                positive_transition = None
                for transition in transitions:
                    if transition.get("condition") == "positive" or transition.get("condition") == "yes":
                        positive_transition = transition.get("next_stage_id")
                        break
                
                if positive_transition:
                    next_stage_id = positive_transition
                elif default_next:
                    next_stage_id = default_next
                else:
                    next_stage_id = current_stage_id  # 기본값은 현재 단계 유지
                    
                print(f"🎯 [DEFAULT_SELECTION_NEXT] Determined next_stage: {next_stage_id}")
            
            # 단계 전환 및 응답 데이터 준비
            if next_stage_id and next_stage_id != current_stage_id:
                # 다음 단계로 전환
                next_stage_info = active_scenario_data.get("stages", {}).get(next_stage_id, {})
                print(f"🎯 [DEFAULT_SELECTION_TRANSITION] {current_stage_id} -> {next_stage_id}")
                
                # stage_response_data 생성
                stage_response_data = None
                if "response_type" in next_stage_info:
                    stage_response_data = generate_stage_response(next_stage_info, collected_info, active_scenario_data)
                    print(f"🎯 [DEFAULT_SELECTION_STAGE_RESPONSE] Generated stage response data for {next_stage_id}")
                    
                    # 확인 메시지를 stage_response_data의 prompt에 추가
                    if stage_response_data and confirmation_response:
                        original_prompt = stage_response_data.get("prompt", "")
                        stage_response_data["prompt"] = f"{confirmation_response}\n\n{original_prompt}" if original_prompt else confirmation_response
                        print(f"🎯 [DEFAULT_SELECTION_STAGE_RESPONSE] Added confirmation to stage prompt")
                
                # 응답 프롬프트 준비
                next_stage_prompt = next_stage_info.get("prompt", "")
                if next_stage_prompt:
                    response_text = f"{confirmation_response}\n\n{next_stage_prompt}"
                else:
                    response_text = confirmation_response
                
                # 상태 업데이트하여 반환
                update_dict = {
                    "current_scenario_stage_id": next_stage_id,
                    "collected_product_info": collected_info,
                    "response_text": response_text,
                    "is_final_turn_response": True,
                    "action_plan": [],
                    "action_plan_struct": [],
                    "scenario_awaiting_user_response": True,
                    "scenario_ready_for_continuation": True
                }
                
                if stage_response_data:
                    update_dict["stage_response_data"] = stage_response_data
                
                # last_llm_prompt 저장
                update_dict = create_update_dict_with_last_prompt(update_dict)
                return state.merge_update(update_dict)
            
            else:
                # 현재 단계에 머무는 경우 - 단순 확인 응답만 제공
                print(f"🎯 [DEFAULT_SELECTION_STAY] Staying at current stage {current_stage_id}")
                
                update_dict = {
                    "current_scenario_stage_id": current_stage_id,
                    "collected_product_info": collected_info,
                    "response_text": confirmation_response,
                    "is_final_turn_response": True,
                    "action_plan": [],
                    "action_plan_struct": [],
                    "scenario_awaiting_user_response": True,
                    "scenario_ready_for_continuation": True
                }
                
                # last_llm_prompt 저장
                update_dict = create_update_dict_with_last_prompt(update_dict)
                return state.merge_update(update_dict)
        
        # 모든 단계에서 일관되게 개선된 LLM 기반 매핑 사용 (DEFAULT_SELECTION이 없는 경우에만)
        if not choice_mapping and expected_field and not already_default_selected:
            choice_mapping = await map_user_intent_to_choice_enhanced(
                user_input, 
                choices, 
                expected_field,
                None,  # keyword_mapping
                current_stage_info,  # stage_info
                collected_info  # collected_info
            )
        
        # extracted_fields가 있으면 choice_mapping 없어도 처리
        if extracted_fields and not choice_mapping:
            print(f"🎯 [V3_EXTRACTED_FIELDS] Processing extracted fields without choice_mapping")
            
            # 수정 의도가 명확한 경우 (날짜 변경 등)
            is_modification_intent = any(keyword in user_input.lower() for keyword in ["바꿀래", "변경", "수정", "바꿔", "로 할래", "로 해줘"])
            
            # additional_services 단계에서는 항상 extracted_fields 처리
            if current_stage_id == "additional_services" or is_modification_intent or len(extracted_fields) > 0:
                # extracted_fields의 모든 값을 collected_info에 저장
                for field_key, field_value in extracted_fields.items():
                    if field_key in fields_to_collect:
                        # security_medium_registration 단계에서 긍정 응답으로 이미 디폴트 값이 설정된 경우 유지
                        if (current_stage_id == "security_medium_registration" and 
                            field_key in collected_info and
                            field_value in ["등록", "네", "응", "예", "좋아"]):
                            print(f"🎯 [V3_EXTRACTED_SKIPPED] {field_key}: keeping default value '{collected_info[field_key]}' (ignoring extracted '{field_value}')")
                            continue
                        
                        # 추출된 값이 유효한 choice인지 확인
                        if choices:
                            valid_choice_values = []
                            for choice in choices:
                                if isinstance(choice, dict):
                                    valid_choice_values.append(choice.get("value", ""))
                                else:
                                    valid_choice_values.append(str(choice))
                            
                            # 추출된 값이 유효한 choice가 아니고, 이미 값이 있으면 기존 값 유지
                            if (field_value not in valid_choice_values and 
                                field_key in collected_info):
                                print(f"🎯 [V3_EXTRACTED_INVALID] {field_key}: '{field_value}' is not a valid choice, keeping existing value '{collected_info[field_key]}'")
                                continue
                        
                        collected_info[field_key] = field_value
                        print(f"✅ [V3_EXTRACTED_STORED] {field_key}: '{field_value}' (from extracted_fields)")
                
                # statement_delivery 단계에서 기본값 설정
                if current_stage_id == "statement_delivery":
                    # 날짜가 없으면 기존 값 유지 또는 기본값 설정
                    if "statement_delivery_date" not in collected_info:
                        collected_info["statement_delivery_date"] = "10"
                        print(f"✅ [V3_EXTRACTED_STORED] Set default statement_delivery_date: 10")
                    
                    # 방법이 없으면 기존 값 유지 또는 기본값 설정
                    if "statement_delivery_method" not in collected_info:
                        # 이전 프롬프트에서 언급된 방법 찾기
                        if state.last_llm_prompt and "휴대폰" in state.last_llm_prompt:
                            collected_info["statement_delivery_method"] = "mobile"
                        else:
                            collected_info["statement_delivery_method"] = "mobile"  # 기본값
                        print(f"✅ [V3_EXTRACTED_STORED] Set default statement_delivery_method: mobile")
                
                # 확인 응답 생성
                if current_stage_id == "statement_delivery" and "statement_delivery_date" in collected_info:
                    date = collected_info["statement_delivery_date"]
                    method = collected_info.get("statement_delivery_method", "mobile")
                    method_display = "이메일" if method == "email" else "휴대폰" if method == "mobile" else "홈페이지"
                    confirmation_response = f"네, 카드 명세서를 매월 {date}일에 {method_display}로 받아보시도록 변경해드리겠습니다."
                elif current_stage_id == "additional_services":
                    # 모든 서비스가 False인지 확인
                    all_false = all(
                        collected_info.get(field, False) == False 
                        for field in ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
                    )
                    if all_false:
                        confirmation_response = "네, 추가 알림 서비스는 신청하지 않겠습니다."
                    else:
                        # 신청한 서비스 나열
                        services = []
                        if collected_info.get("important_transaction_alert"):
                            services.append("중요거래 알림")
                        if collected_info.get("withdrawal_alert"):
                            services.append("출금 알림")
                        if collected_info.get("overseas_ip_restriction"):
                            services.append("해외IP 제한")
                        if services:
                            confirmation_response = f"네, {', '.join(services)}을 신청해드리겠습니다."
                        else:
                            confirmation_response = "네, 추가 알림 서비스는 신청하지 않겠습니다."
                elif current_stage_id == "security_medium_registration":
                    # 보안매체 등록 확인 메시지
                    confirmations = []
                    
                    # 보안매체 이름
                    if "security_medium" in collected_info:
                        from ....data.deposit_account_fields import CHOICE_VALUE_DISPLAY_MAPPING
                        security_medium = collected_info["security_medium"]
                        display_name = CHOICE_VALUE_DISPLAY_MAPPING.get(security_medium, security_medium)
                        confirmations.append(f"{display_name}로 설정")
                    
                    # 이체한도 정보
                    if "transfer_limit_once" in collected_info or "transfer_limit_daily" in collected_info:
                        limit_parts = []
                        
                        if "transfer_limit_once" in collected_info:
                            once_limit = int(collected_info["transfer_limit_once"])
                            if once_limit >= 10000:
                                once_limit_str = f"{once_limit // 10000}만원"
                            else:
                                once_limit_str = f"{once_limit:,}원"
                            limit_parts.append(f"1회 {once_limit_str}")
                        
                        if "transfer_limit_daily" in collected_info:
                            daily_limit = int(collected_info["transfer_limit_daily"]) 
                            if daily_limit >= 100000000:
                                daily_limit_str = f"{daily_limit // 100000000}억원"
                            elif daily_limit >= 10000:
                                daily_limit_str = f"{daily_limit // 10000}만원"
                            else:
                                daily_limit_str = f"{daily_limit:,}원"
                            limit_parts.append(f"1일 {daily_limit_str}")
                        
                        if limit_parts:
                            confirmations.append(f"{', '.join(limit_parts)} 한도")
                    
                    if confirmations:
                        confirmation_response = f"{confirmations[0]}해드리겠습니다." + (f" {confirmations[1]}로 설정됩니다." if len(confirmations) > 1 else "")
                    else:
                        confirmation_response = "네, 설정해드리겠습니다."
                else:
                    confirmation_response = "네, 변경해드리겠습니다."
                
                print(f"🎯 [V3_EXTRACTED_CONFIRMED] Generated confirmation: {confirmation_response}")
                
                # 다음 단계 확인
                # V3 시나리오의 next_step 처리
                next_step = current_stage_info.get("next_step")
                next_stage_id = current_stage_id  # 기본값은 현재 단계 유지
                
                if next_step:
                    if isinstance(next_step, str):
                        # 필수 필드가 모두 수집되었는지 확인
                        required_fields_collected = True
                        for field in fields_to_collect:
                            if field not in collected_info or collected_info.get(field) is None:
                                required_fields_collected = False
                                print(f"[V3_NEXT_STEP] Required field '{field}' not collected")
                                break
                        
                        if required_fields_collected:
                            next_stage_id = next_step
                            print(f"[V3_NEXT_STEP] All required fields collected, moving to {next_stage_id}")
                        else:
                            print(f"[V3_NEXT_STEP] Required fields not collected, staying at {current_stage_id}")
                    else:
                        # next_step이 dict인 경우 - additional_services의 경우 services_selected 값에 따라 분기
                        if current_stage_id == "additional_services":
                            # 모든 필드가 수집되었는지 확인
                            required_fields = ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
                            all_fields_collected = all(field in collected_info for field in required_fields)
                            
                            if all_fields_collected:
                                services_selected = collected_info.get("services_selected", "all")
                                next_stage_id = next_step.get(services_selected, next_step.get("all", current_stage_id))
                                print(f"[V3_NEXT_STEP] additional_services completed, services_selected='{services_selected}' -> {next_stage_id}")
                            else:
                                next_stage_id = current_stage_id
                                print(f"[V3_NEXT_STEP] additional_services not all fields collected, staying at {current_stage_id}")
                        else:
                            next_stage_id = current_stage_id
                
                # 다음 단계로 진행하는 경우
                if next_stage_id != current_stage_id:
                    # 다음 스테이지 정보 가져오기
                    next_stage_info = active_scenario_data.get("stages", {}).get(str(next_stage_id), {})
                    next_stage_prompt = next_stage_info.get("prompt", "")
                    
                    print(f"🎯 [V3_STAGE_TRANSITION] {current_stage_id} -> {next_stage_id}")
                    
                    # stage_response_data 생성
                    stage_response_data = None
                    if "response_type" in next_stage_info:
                        stage_response_data = generate_stage_response(next_stage_info, collected_info, active_scenario_data)
                        print(f"🎯 [V3_STAGE_RESPONSE] Generated stage response data for {next_stage_id}")
                        
                        # 확인 메시지를 stage_response_data의 prompt에 추가
                        if stage_response_data and confirmation_response:
                            original_prompt = stage_response_data.get("prompt", "")
                            stage_response_data["prompt"] = f"{confirmation_response}\n\n{original_prompt}" if original_prompt else confirmation_response
                            print(f"🎯 [V3_STAGE_RESPONSE] Added confirmation to prompt: {confirmation_response}")
                    
                    final_response = f"{confirmation_response} {next_stage_prompt}" if next_stage_prompt else confirmation_response
                    
                    update_dict = {
                        "final_response_text_for_tts": final_response,
                        "is_final_turn_response": True,
                        "current_scenario_stage_id": next_stage_id,
                        "collected_product_info": collected_info,
                        "action_plan": [],
                        "action_plan_struct": [],
                        "scenario_awaiting_user_response": True,
                        "scenario_ready_for_continuation": True
                    }
                    
                    if stage_response_data:
                        update_dict["stage_response_data"] = stage_response_data
                    
                    # last_llm_prompt 저장
                    update_dict = create_update_dict_with_last_prompt(update_dict, stage_response_data)
                    
                    return state.merge_update(update_dict)
                else:
                    # 현재 단계 유지 - 하지만 additional_services는 예외
                    # additional_services 단계에서 모든 필드가 수집되었는지 확인
                    if current_stage_id == "additional_services":
                        required_fields = ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
                        all_fields_collected = all(field in collected_info for field in required_fields)
                        
                        if all_fields_collected:
                            # services_selected 값에 따라 다음 단계 결정
                            services_selected = collected_info.get("services_selected", "all")
                            next_stage_id = "card_selection" if services_selected == "all" else "final_confirmation"
                            
                            print(f"🎯 [ADDITIONAL_SERVICES_COMPLETE] All fields collected, moving to {next_stage_id}")
                            
                            # 다음 스테이지 정보 가져오기
                            next_stage_info = active_scenario_data.get("stages", {}).get(str(next_stage_id), {})
                            next_stage_prompt = next_stage_info.get("prompt", "")
                            
                            # stage_response_data 생성
                            stage_response_data = None
                            if "response_type" in next_stage_info:
                                stage_response_data = generate_stage_response(next_stage_info, collected_info, active_scenario_data)
                                print(f"🎯 [STAGE_RESPONSE] Generated stage response data for {next_stage_id}")
                                
                                # 확인 메시지를 stage_response_data의 prompt에 추가
                                if stage_response_data and confirmation_response:
                                    original_prompt = stage_response_data.get("prompt", "")
                                    stage_response_data["prompt"] = f"{confirmation_response}\n\n{original_prompt}" if original_prompt else confirmation_response
                            
                            final_response = f"{confirmation_response} {next_stage_prompt}" if next_stage_prompt else confirmation_response
                            
                            update_dict = {
                                "final_response_text_for_tts": final_response,
                                "is_final_turn_response": True,
                                "current_scenario_stage_id": next_stage_id,
                                "collected_product_info": collected_info,
                                "action_plan": [],
                                "action_plan_struct": [],
                                "scenario_awaiting_user_response": True,
                                "scenario_ready_for_continuation": True
                            }
                            
                            if stage_response_data:
                                update_dict["stage_response_data"] = stage_response_data
                            
                            # last_llm_prompt 저장
                            update_dict = create_update_dict_with_last_prompt(update_dict, stage_response_data)
                            
                            return state.merge_update(update_dict)
                    
                    # 다른 단계는 현재 단계 유지
                    update_dict = {
                        "final_response_text_for_tts": confirmation_response,
                        "is_final_turn_response": True,
                        "current_scenario_stage_id": current_stage_id,
                        "collected_product_info": collected_info,
                        "action_plan": [],
                        "action_plan_struct": [],
                        "scenario_awaiting_user_response": True,
                        "scenario_ready_for_continuation": True
                    }
                    # last_llm_prompt 저장
                    update_dict = create_update_dict_with_last_prompt(update_dict)
                    return state.merge_update(update_dict)
        
        if choice_mapping:
            print(f"🎯 [V3_CHOICE_MAPPING] Mapped '{user_input}' to '{choice_mapping}'")
            if expected_field:
                entities = {expected_field: choice_mapping}
                intent = "정보제공"
                
                # scenario_output 생성
                scenario_output = ScenarioAgentOutput(
                    intent=intent,
                    entities=entities,
                    is_scenario_related=True
                )
                
                # additional_services 단계의 특별 처리
                if current_stage_id == "additional_services" and choice_mapping in ["all_true", "all_false", "important_only", "withdrawal_only", "overseas_only", "exclude_important", "exclude_withdrawal", "exclude_overseas"]:
                    # 복합 필드 값 설정
                    collected_info = apply_additional_services_values(choice_mapping, collected_info)
                    print(f"✅ [V3_CHOICE_STORED] Applied additional_services mapping: '{choice_mapping}'")
                # security_medium_registration 단계의 특별 처리
                elif current_stage_id == "security_medium_registration":
                    # 보안매체 선택
                    collected_info[expected_field] = choice_mapping
                    print(f"✅ [V3_CHOICE_STORED] {expected_field}: '{choice_mapping}'")
                    
                    # 모든 보안매체에 대해 최대 이체한도 설정 (사용자가 수정 요청하지 않은 경우)
                    if "transfer_limit_once" not in collected_info:
                        collected_info["transfer_limit_once"] = "50000000"  # 5천만원
                        print(f"✅ [V3_CHOICE_STORED] Set default transfer_limit_once: 50000000")
                    if "transfer_limit_daily" not in collected_info:
                        collected_info["transfer_limit_daily"] = "100000000"  # 1억원
                        print(f"✅ [V3_CHOICE_STORED] Set default transfer_limit_daily: 100000000")
                        
                # statement_delivery 단계의 특별 처리  
                elif current_stage_id == "statement_delivery":
                    # 명세서 수령방법 선택
                    collected_info[expected_field] = choice_mapping
                    print(f"✅ [V3_CHOICE_STORED] {expected_field}: '{choice_mapping}'")
                    
                    # 추출된 다른 필드들도 저장 (예: statement_delivery_date)
                    for field_key, field_value in extracted_fields.items():
                        if field_key != expected_field and field_key in fields_to_collect:
                            collected_info[field_key] = field_value
                            print(f"✅ [V3_CHOICE_STORED] {field_key}: '{field_value}' (from multi-field extraction)")
                    
                    # 날짜가 추출되지 않았지만 사용자 입력에 숫자가 있으면 추출 시도
                    if "statement_delivery_date" not in collected_info:
                        import re
                        # "30일", "매월 30일" 등에서 숫자 추출
                        date_match = re.search(r'(\d+)일', user_input)
                        if date_match:
                            date_value = date_match.group(1)
                            # 1-31 범위 검증
                            if 1 <= int(date_value) <= 31:
                                collected_info["statement_delivery_date"] = date_value
                                print(f"✅ [V3_CHOICE_STORED] Extracted statement_delivery_date from input: {date_value}")
                            else:
                                collected_info["statement_delivery_date"] = "10"
                                print(f"✅ [V3_CHOICE_STORED] Invalid date {date_value}, using default: 10")
                        else:
                            collected_info["statement_delivery_date"] = "10"
                            print(f"✅ [V3_CHOICE_STORED] Set default statement_delivery_date: 10")
                        
                # card_selection 단계의 특별 처리 - 이미 handle_card_selection_mapping에서 처리됨
                elif current_stage_id == "card_selection":
                    # 카드 선택은 이미 handle_card_selection_mapping에서 여러 필드가 설정됨
                    print(f"✅ [V3_CHOICE_STORED] Card selection fields already set by handle_card_selection_mapping")
                else:
                    # 일반적인 필드 저장
                    collected_info[expected_field] = choice_mapping
                    print(f"✅ [V3_CHOICE_STORED] {expected_field}: '{choice_mapping}'")
                    
                    # 추출된 다른 필드들도 저장
                    for field_key, field_value in extracted_fields.items():
                        if field_key != expected_field and field_key in fields_to_collect:
                            collected_info[field_key] = field_value
                            print(f"✅ [V3_CHOICE_STORED] {field_key}: '{field_value}' (from multi-field extraction)")
                
                # 자연스러운 확인 응답 생성
                # statement_delivery 단계에서는 날짜도 함께 확인
                if current_stage_id == "statement_delivery" and "statement_delivery_date" in collected_info:
                    date = collected_info["statement_delivery_date"]
                    method_display = "이메일" if choice_mapping == "email" else "휴대폰" if choice_mapping == "mobile" else "홈페이지"
                    confirmation_response = f"네, {method_display}로 매월 {date}일에 받아보시겠습니다."
                else:
                    # choice_display 찾기
                    choice_display = choice_mapping
                    for choice in choices:
                        if isinstance(choice, dict) and choice.get("value") == choice_mapping:
                            choice_display = choice.get("display", choice_mapping)
                            break
                    
                    confirmation_response = generate_choice_confirmation_response(
                        choice_value=choice_mapping,
                        choice_display=choice_display,
                        field_key=expected_field,
                        stage_info=current_stage_info
                    )
                
                print(f"🎯 [V3_CHOICE_CONFIRMED] Generated confirmation: {confirmation_response}")
                
                # 다음 단계 확인
                next_step = current_stage_info.get("next_step")
                next_stage_id = current_stage_id  # 기본값은 현재 단계 유지
                
                if next_step:
                    if isinstance(next_step, dict):
                        # services_selected 값에 따른 분기
                        if expected_field == "services_selected":
                            next_stage_id = next_step.get(choice_mapping, next_step.get("all", current_stage_id))
                            print(f"🎯 [V3_NEXT_STAGE] {expected_field}='{choice_mapping}' -> next_stage: {next_stage_id}")
                        # additional_services 단계 특별 처리 - services_selected 기준으로 분기
                        elif current_stage_id == "additional_services":
                            # 먼저 필수 필드가 모두 수집되었는지 확인
                            required_fields = ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
                            missing_fields = [field for field in required_fields if field not in collected_info or collected_info.get(field) is None]
                            
                            if missing_fields:
                                # 필수 필드가 누락된 경우 현재 단계 유지
                                next_stage_id = current_stage_id
                                print(f"🎯 [V3_NEXT_STAGE] additional_services - missing fields: {missing_fields}, staying at {current_stage_id}")
                            else:
                                # 모든 필드가 수집된 경우 다음 단계로 진행
                                services_selected = collected_info.get("services_selected", "all")
                                next_stage_id = next_step.get(services_selected, next_step.get("all", current_stage_id))
                                print(f"🎯 [V3_NEXT_STAGE] additional_services - all fields collected, services_selected='{services_selected}' -> next_stage: {next_stage_id}")
                        else:
                            next_stage_id = next_step.get(choice_mapping, current_stage_id)
                    else:
                        # 단순 문자열인 경우
                        next_stage_id = next_step
                        print(f"🎯 [V3_NEXT_STAGE] Direct transition -> {next_stage_id}")
                
                # 다음 단계로 진행하는 경우
                if next_stage_id != current_stage_id:
                    # 다음 스테이지 정보 가져오기
                    next_stage_info = active_scenario_data.get("stages", {}).get(str(next_stage_id), {})
                    next_stage_prompt = next_stage_info.get("prompt", "")
                    
                    print(f"🎯 [V3_STAGE_TRANSITION] {current_stage_id} -> {next_stage_id}")
                    
                    # stage_response_data 생성 (개인정보 표시 등을 위해 필요)
                    stage_response_data = None
                    if "response_type" in next_stage_info:
                        stage_response_data = generate_stage_response(next_stage_info, collected_info, active_scenario_data)
                        print(f"🎯 [V3_STAGE_RESPONSE] Generated stage response data for {next_stage_id}")
                        
                        # 확인 메시지를 stage_response_data의 prompt에 추가
                        if stage_response_data and confirmation_response:
                            original_prompt = stage_response_data.get("prompt", "")
                            stage_response_data["prompt"] = f"{confirmation_response}\n\n{original_prompt}" if original_prompt else confirmation_response
                            print(f"🎯 [V3_STAGE_RESPONSE] Added confirmation to prompt: {confirmation_response}")
                    
                    # 확인 메시지와 다음 단계 프롬프트를 함께 표시
                    final_response = f"{confirmation_response} {next_stage_prompt}" if next_stage_prompt else confirmation_response
                    
                    update_dict = {
                        "final_response_text_for_tts": final_response,
                        "is_final_turn_response": True,
                        "current_scenario_stage_id": next_stage_id,  # 다음 단계로 진행
                        "collected_product_info": collected_info,
                        "action_plan": [],
                        "action_plan_struct": [],
                        "scenario_awaiting_user_response": True,
                        "scenario_ready_for_continuation": True
                    }
                    
                    if stage_response_data:
                        update_dict["stage_response_data"] = stage_response_data
                    
                    # last_llm_prompt 저장
                    update_dict = create_update_dict_with_last_prompt(update_dict, stage_response_data)
                    
                    return state.merge_update(update_dict)
                else:
                    # 현재 단계 유지 - 하지만 additional_services는 예외
                    # additional_services 단계에서 모든 필드가 수집되었는지 확인
                    if current_stage_id == "additional_services":
                        required_fields = ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
                        all_fields_collected = all(field in collected_info for field in required_fields)
                        
                        if all_fields_collected:
                            # services_selected 값에 따라 다음 단계 결정
                            services_selected = collected_info.get("services_selected", "all")
                            next_stage_id = "card_selection" if services_selected == "all" else "final_confirmation"
                            
                            print(f"🎯 [ADDITIONAL_SERVICES_COMPLETE] All fields collected, moving to {next_stage_id}")
                            
                            # 다음 스테이지 정보 가져오기
                            next_stage_info = active_scenario_data.get("stages", {}).get(str(next_stage_id), {})
                            next_stage_prompt = next_stage_info.get("prompt", "")
                            
                            # stage_response_data 생성
                            stage_response_data = None
                            if "response_type" in next_stage_info:
                                stage_response_data = generate_stage_response(next_stage_info, collected_info, active_scenario_data)
                                print(f"🎯 [STAGE_RESPONSE] Generated stage response data for {next_stage_id}")
                                
                                # 확인 메시지를 stage_response_data의 prompt에 추가
                                if stage_response_data and confirmation_response:
                                    original_prompt = stage_response_data.get("prompt", "")
                                    stage_response_data["prompt"] = f"{confirmation_response}\n\n{original_prompt}" if original_prompt else confirmation_response
                            
                            final_response = f"{confirmation_response} {next_stage_prompt}" if next_stage_prompt else confirmation_response
                            
                            update_dict = {
                                "final_response_text_for_tts": final_response,
                                "is_final_turn_response": True,
                                "current_scenario_stage_id": next_stage_id,
                                "collected_product_info": collected_info,
                                "action_plan": [],
                                "action_plan_struct": [],
                                "scenario_awaiting_user_response": True,
                                "scenario_ready_for_continuation": True
                            }
                            
                            if stage_response_data:
                                update_dict["stage_response_data"] = stage_response_data
                            
                            # last_llm_prompt 저장
                            update_dict = create_update_dict_with_last_prompt(update_dict, stage_response_data)
                            
                            return state.merge_update(update_dict)
                    
                    # 다른 단계는 현재 단계 유지
                    update_dict = {
                        "final_response_text_for_tts": confirmation_response,
                        "is_final_turn_response": True,
                        "current_scenario_stage_id": current_stage_id,
                        "collected_product_info": collected_info,
                        "action_plan": [],
                        "action_plan_struct": [],
                        "scenario_awaiting_user_response": True,
                        "scenario_ready_for_continuation": True
                    }
                    # last_llm_prompt 저장
                    update_dict = create_update_dict_with_last_prompt(update_dict)
                    return state.merge_update(update_dict)
        else:
            # additional_services 단계에서 choice_mapping 실패 시 직접 처리
            if current_stage_id == "additional_services":
                handled = handle_additional_services_fallback(user_input, collected_info)
                if handled:
                    print(f"🎯 [ADDITIONAL_SERVICES_FALLBACK] Successfully processed: {user_input}")
                    update_dict = {
                        "final_response_text_for_tts": "네, 설정해드렸습니다.",
                        "is_final_turn_response": True,
                        "current_scenario_stage_id": current_stage_id,
                        "collected_product_info": collected_info,
                        "action_plan": [],
                        "action_plan_struct": [],
                        "scenario_awaiting_user_response": True,
                        "scenario_ready_for_continuation": True
                    }
                    # last_llm_prompt 저장
                    update_dict = create_update_dict_with_last_prompt(update_dict)
                    return state.merge_update(update_dict)
            
            # 정확한 매치가 없는 경우 - 애매한 지시어 검사
            ambiguous_keywords = ["그걸로", "그것으로", "그거", "그렇게", "저걸로", "저것으로", "저거", "위에꺼", "아래꺼", "첫번째", "두번째"]
            is_ambiguous_reference = any(keyword in user_input.lower() for keyword in ambiguous_keywords)
            
            # 대명사가 있지만 명확한 문맥이 있는 경우 체크
            has_clear_context = False
            if is_ambiguous_reference and state.last_llm_prompt:
                # card_selection 단계에서는 대명사가 이전 프롬프트의 카드를 가리킬 가능성이 높음
                if current_stage_id == "card_selection":
                    # 이전 프롬프트에 특정 카드가 언급되었는지 확인
                    card_keywords = ["S-Line", "에스라인", "Deep Dream", "딥드림", "Hey Young", "헤이영", "후불교통", "교통카드"]
                    has_card_mention = any(keyword in state.last_llm_prompt for keyword in card_keywords)
                    if has_card_mention:
                        has_clear_context = True
                        print(f"🎯 [V3_CONTEXT] Clear card reference found in previous prompt, treating pronoun as contextual")
                
                # 다른 단계에서도 선택지가 명확히 제시된 경우
                elif choices and len(choices) <= 3:  # 선택지가 적은 경우
                    # 이전 프롬프트에 선택지가 언급되었는지 확인
                    for choice in choices:
                        choice_str = str(choice.get("display", choice.get("value", ""))) if isinstance(choice, dict) else str(choice)
                        if choice_str and choice_str in state.last_llm_prompt:
                            has_clear_context = True
                            print(f"🎯 [V3_CONTEXT] Clear choice reference found in previous prompt")
                            break
            
            # 문맥이 명확한 경우 ambiguous로 처리하지 않음
            if has_clear_context:
                is_ambiguous_reference = False
            
            if is_ambiguous_reference or (scenario_output and not scenario_output.get("is_scenario_related")):
                # 애매한 지시어나 무관한 발화인 경우 명확한 선택 유도 응답 생성
                print(f"🎯 [V3_AMBIGUOUS] Ambiguous reference or deviation detected: '{user_input}'")
                
                # 선택지 명확화 유도 응답 생성
                clarification_response = await generate_choice_clarification_response(
                    user_input=user_input,
                    current_stage=current_stage_id,
                    current_stage_info=current_stage_info,
                    choices=choices,
                    is_ambiguous=is_ambiguous_reference
                )
                
                # 현재 단계 유지하고 명확화 유도 응답 반환
                update_dict = {
                    "final_response_text_for_tts": clarification_response,
                    "is_final_turn_response": True,
                    "current_scenario_stage_id": current_stage_id,  # 현재 단계 유지
                    "collected_product_info": collected_info,
                    "action_plan": [],
                    "action_plan_struct": [],
                    "scenario_awaiting_user_response": True,
                    "scenario_ready_for_continuation": True
                }
                # last_llm_prompt 저장
                update_dict = create_update_dict_with_last_prompt(update_dict)
                return state.merge_update(update_dict)
            elif scenario_output and scenario_output.get("is_scenario_related"):
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
                                print(f"✅ [ENTITY_MAPPING] {key}: '{value}' -> '{mapped_value}'")
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
                        print(f"✅ [ENTITY_MAPPING] {key}: '{value}' -> '{mapped_value}'")
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
    
    # additional_services 단계에서 "네" 응답 처리 - 더 엄격한 조건
    if current_stage_id == "additional_services":
        print(f"[ADDITIONAL_SERVICES] Processing with input: '{user_input}'")
        
        service_fields = ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
        has_specific_selections = any(field in collected_info for field in service_fields)
        
        # 새로운 LLM 처리나 키워드 매핑이 이미 처리했다면 여기서는 처리하지 않음
        if not has_specific_selections and user_input:
            user_lower = user_input.lower().strip()
            # 매우 단순한 긍정 응답만 처리 (구체적 언급이 없는 경우)
            simple_yes_words = ["네", "예", "응", "어", "좋아요"]
            specific_mentions = ["만", "알림", "내역", "거래", "해외", "ip", "제한", "출금", "중요"]
            
            # 단순한 긍정 응답이면서 구체적 언급이 없는 경우에만 기본값 적용
            if (any(word == user_lower for word in simple_yes_words) and 
                not any(mention in user_lower for mention in specific_mentions)):
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
            else:
                print(f"[ADDITIONAL_SERVICES] Skipping default processing - user input contains specific mentions or not simple yes")
    
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
        
    
    # select_services 단계에서 선택이 없는 경우 재질문
    if current_stage_id == "select_services" and 'services_selected' not in collected_info and user_input:
        print(f"🎯 [SELECT_SERVICES] No service selected, generating clarification response")
        
        # 재질문 응답 생성
        clarification_response = await generate_choice_clarification_response(
            user_input=user_input,
            current_stage=current_stage_id,
            current_stage_info=current_stage_info,
            choices=choices,
            is_ambiguous=True
        )
        
        # 현재 단계 유지하고 재질문 응답 반환
        update_dict = {
            "final_response_text_for_tts": clarification_response,
            "is_final_turn_response": True,
            "current_scenario_stage_id": current_stage_id,  # 현재 단계 유지
            "collected_product_info": collected_info,
            "action_plan": [],
            "action_plan_struct": [],
            "scenario_awaiting_user_response": True,
            "scenario_ready_for_continuation": True
        }
        
        # last_llm_prompt 저장
        update_dict = create_update_dict_with_last_prompt(update_dict)
        return state.merge_update(update_dict)
    
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
            
            # select_services 처리 - services_selected 값에 따라 JSON의 next_step 분기 사용
            if current_stage_id == "select_services":
                services_selected = collected_info.get("services_selected")
                # services_selected가 None이면 현재 단계 유지 (재질문)
                if services_selected is None:
                    print(f"[V3_NEXT_STEP] select_services - No service selected, staying in current stage")
                    next_stage_id = current_stage_id  # 현재 단계 유지
                else:
                    print(f"[V3_NEXT_STEP] select_services branching - services_selected: {services_selected}")
                    next_stage_id = next_step.get(services_selected, next_step.get("all", "completion"))
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
            # additional_services 특별 처리 - services_selected 값에 따라 분기
            elif current_stage_id == "additional_services":
                services_selected = collected_info.get("services_selected")
                print(f"[V3_NEXT_STEP] additional_services branching - services_selected: {services_selected}")
                
                # services_selected 값에 따라 적절한 다음 단계 결정
                if services_selected in ["all", "card_only"]:
                    next_stage_id = next_step.get("all", "card_selection")
                elif services_selected == "mobile_only":
                    next_stage_id = next_step.get("mobile_only", "final_confirmation")
                else:
                    # 기본값: all 처리 (card_selection으로 이동)
                    next_stage_id = next_step.get("all", "card_selection")
                    
                print(f"[V3_NEXT_STEP] additional_services - next_stage_id: {next_stage_id}")
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
            # next_step이 string인 경우
            # 필수 필드가 수집되었는지 확인
            fields_to_collect = get_expected_field_keys(current_stage_info)
            required_fields_collected = True
            
            for field in fields_to_collect:
                if field not in collected_info or collected_info.get(field) is None:
                    required_fields_collected = False
                    print(f"[V3_NEXT_STEP] Required field '{field}' not collected")
                    break
            
            if required_fields_collected:
                # 모든 필수 필드가 수집된 경우에만 다음 단계로 이동
                next_stage_id = next_step
                print(f"[V3_NEXT_STEP] All required fields collected, moving to {next_stage_id}")
            else:
                # 필수 필드가 수집되지 않았으면 현재 단계에 머무름
                next_stage_id = current_stage_id
                print(f"[V3_NEXT_STEP] Required fields not collected, staying at {current_stage_id}")
        
        # V3 시나리오에서 next_step을 사용한 경우 바로 처리하고 반환
        print(f"[V3_NEXT_STEP] Final next_stage_id: {next_stage_id}")
        determined_next_stage_id = next_stage_id
        
        # 스테이지 변경 시 로그
        if determined_next_stage_id != current_stage_id:
            log_node_execution("Stage_Change", f"{current_stage_id} -> {determined_next_stage_id}")
        
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
            # last_llm_prompt 저장
            update_dict = create_update_dict_with_last_prompt(update_dict, stage_response_data)
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
            # LLM 기반 자연어 필드 값 추출
            extracted_value = await extract_any_field_value_with_llm(
                user_input,
                main_field_key,
                current_stage_info,
                current_stage_id
            )
            
            if extracted_value is not None:
                collected_info[main_field_key] = extracted_value
                print(f"🎯 [LLM_FIELD_EXTRACTION] {main_field_key}: '{user_input}' -> {extracted_value}")
            
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
        log_node_execution("Stage_Change", f"{current_stage_id} -> {determined_next_stage_id}")
    
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
    
    # LLM 기반 자연스러운 응답 생성을 위한 정보 준비
    natural_response_info = {
        "user_input": user_input,
        "current_stage": current_stage_id,
        "stage_info": current_stage_info,
        "collected_info": collected_info,
        "extraction_result": extraction_result if 'extraction_result' in locals() else {},
        "next_stage_id": determined_next_stage_id
    }
    
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
            
            # 확인 메시지를 stage_response_data의 prompt에 추가
            if stage_response_data and confirmation_msg:
                original_prompt = stage_response_data.get("prompt", "")
                stage_response_data["prompt"] = f"{confirmation_msg}\n\n{original_prompt}" if original_prompt else confirmation_msg
                print(f"🎯 [STAGE_RESPONSE] Added confirmation to prompt: {confirmation_msg}")
    
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
        
        # stage_response_data가 있으면 prompt 정보 추출
        stage_prompt = stage_response_data.get("prompt", "") if stage_response_data else ""
        
        # prompt가 있는 경우 final_response_text_for_tts에 설정 (narrative 및 bullet 타입 모두)
        if next_stage_prompt or stage_prompt:
            # stage_response_data의 prompt를 우선 사용
            effective_prompt = stage_prompt if stage_prompt else next_stage_prompt
            
            # 사용자 입력이 있을 때 LLM 기반 자연스러운 응답 생성 시도
            if user_input and determined_next_stage_id != current_stage_id:
                try:
                    next_stage_info = active_scenario_data.get("stages", {}).get(str(determined_next_stage_id), {})
                    natural_response = await generate_natural_response(
                        natural_response_info["user_input"],
                        natural_response_info["current_stage"],
                        natural_response_info["stage_info"],
                        natural_response_info["collected_info"],
                        natural_response_info["extraction_result"],
                        next_stage_info
                    )
                    update_dict["final_response_text_for_tts"] = natural_response
                    print(f"🎯 [NATURAL_RESPONSE] Generated: '{natural_response[:100]}...'")
                except Exception as e:
                    print(f"🎯 [NATURAL_RESPONSE] Failed, using template: {e}")
                    update_dict["final_response_text_for_tts"] = effective_prompt
            else:
                update_dict["final_response_text_for_tts"] = effective_prompt
                print(f"🎯 [STAGE_RESPONSE_WITH_TEXT] Set final_response_text_for_tts: '{effective_prompt[:100]}...'")
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
    
    # 확인 메시지 생성 및 추가
    try:
        # 새로 추출된 값들 감지
        original_collected_info = state.collected_product_info or {}
        newly_extracted_values = detect_newly_extracted_values(original_collected_info, collected_info)
        
        # 확인 메시지 생성
        if newly_extracted_values and user_input:  # 사용자 입력이 있는 경우에만
            confirmation_message = generate_confirmation_message(
                newly_extracted_values, 
                active_scenario_data, 
                current_stage_id
            )
            
            if confirmation_message:
                # 기존 응답과 확인 메시지 결합
                existing_response = update_dict.get("final_response_text_for_tts", "")
                if existing_response:
                    # 확인 메시지를 기존 응답 앞에 추가
                    combined_response = f"{confirmation_message}\n\n{existing_response}"
                    update_dict["final_response_text_for_tts"] = combined_response
                    print(f"[CONFIRMATION] Added confirmation message: '{confirmation_message}'")
                else:
                    # 기존 응답이 없으면 확인 메시지만 설정
                    update_dict["final_response_text_for_tts"] = confirmation_message
                    print(f"[CONFIRMATION] Set confirmation message only: '{confirmation_message}'")
    
    except Exception as e:
        print(f"[CONFIRMATION] Error generating confirmation message: {e}")
        # 에러가 발생해도 기본 플로우는 계속 진행
    
    return state.merge_update(update_dict)






