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
        result = await process_multiple_info_collection(state, active_scenario_data, current_stage_id, current_stage_info, collected_info, user_input)
        return result
    
    # 기존 단일 정보 수집 처리
    result = await process_single_info_collection(state, active_scenario_data, current_stage_id, current_stage_info, collected_info, scenario_output, user_input)
    return result


async def process_multiple_info_collection(state: AgentState, active_scenario_data: Dict, current_stage_id: str, current_stage_info: Dict, collected_info: Dict, user_input: str) -> AgentState:
    """다중 정보 수집 처리 (개선된 그룹별 방식)"""
    required_fields = active_scenario_data.get("required_info_fields", [])
    
    # 현재 스테이지가 정보 수집 단계인지 확인
    print(f"[DEBUG] Multiple info collection - 현재 스테이지 ID: {current_stage_id}")
    
    # 인터넷뱅킹 정보 수집 스테이지 추가 (greeting 포함)
    info_collection_stages = [
        "greeting", "info_collection_guidance", "process_collected_info", 
        "ask_missing_info_group1", "ask_missing_info_group2", "ask_missing_info_group3", 
        "eligibility_assessment", "collect_internet_banking_info", "ask_remaining_ib_info",
        "collect_check_card_info", "ask_remaining_card_info"
    ]
    
    if current_stage_id in info_collection_stages:
        
        # REQUEST_MODIFY 인텐트 또는 기본정보 수정 요청 처리 (Entity Agent 처리 전에 확인)
        scenario_output = state.scenario_agent_output
        print(f"[DEBUG] Scenario output type: {type(scenario_output)}, value: {scenario_output}")
        if scenario_output and (isinstance(scenario_output, dict) or hasattr(scenario_output, 'get')):
            intent = scenario_output.get("intent") if hasattr(scenario_output, 'get') else getattr(scenario_output, 'intent', None)
            print(f"[DEBUG] Scenario output intent: '{intent}'")
            
            # 1. REQUEST_MODIFY 인텐트 감지 - 전용 노드로 안전하게 라우팅
            if intent == "REQUEST_MODIFY":
                print(f"[DEBUG] REQUEST_MODIFY intent detected in stage: {current_stage_id} - routing to correction node")
                
                # 무한루프 방지를 위해 전용 correction 노드로 라우팅
                return state.merge_update({
                    "action_plan": ["personal_info_correction"],
                    "action_plan_struct": [{"action": "personal_info_correction", "reason": "User requested info correction"}],
                    "router_call_count": 0,  # 라우터 카운트 초기화
                    "is_final_turn_response": False  # 계속 처리하도록 설정
                })
    
        # Entity Agent를 사용한 정보 추출
        extraction_result = {"extracted_entities": {}, "collected_info": collected_info}
        
        if user_input:
            try:
                # Entity Agent로 정보 추출
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
            print(f"[DEBUG] Final updated collected_info: {collected_info}")
            if extraction_result['extracted_entities']:
                log_node_execution("Entity_Extract", output_info=f"entities={list(extraction_result['extracted_entities'].keys())}")

        # greeting 단계에서 개인정보 확인 처리
        if current_stage_id == "greeting":
            # correction_mode가 활성화된 경우 InfoModificationAgent로 라우팅
            if state.correction_mode:
                print(f"[DEBUG] Correction mode active - routing to personal_info_correction_node")
                
                # 수정 완료 확인 처리
                if user_input and ("확인" in user_input or "완료" in user_input or "끝" in user_input):
                    # 수정 완료 의사 표시 - 다음 단계로 진행
                    next_stage_id = "ask_lifelong_account"
                    next_stage_prompt = active_scenario_data.get("stages", {}).get("ask_lifelong_account", {}).get("prompt", "평생계좌번호로 등록하시겠어요?")
                    
                    return state.merge_update({
                        "current_scenario_stage_id": next_stage_id,
                        "final_response_text_for_tts": f"네, 기본정보 수정이 완료되었습니다. {next_stage_prompt}",
                        "is_final_turn_response": True,
                        "action_plan": [],
                        "action_plan_struct": [],
                        "router_call_count": 0,
                        "correction_mode": False  # 수정 모드 해제
                    })
                
                # 그 외의 경우 personal_info_correction_node로 라우팅
                return state.merge_update({
                    "action_plan": ["personal_info_correction"],
                    "action_plan_struct": [{"action": "personal_info_correction", "reason": "Correction mode active - processing modification"}],
                    "router_call_count": 0,
                    "is_final_turn_response": False
                })
            
            # confirm_personal_info가 true인 경우 평생계좌 단계로 이동
            elif collected_info.get("confirm_personal_info") == True:
                print(f"[DEBUG] Personal info confirmed, moving to lifelong account stage")
                
                next_stage_id = "ask_lifelong_account"
                next_stage_prompt = active_scenario_data.get("stages", {}).get("ask_lifelong_account", {}).get("prompt", "평생계좌번호로 등록하시겠어요?")
                
                return state.merge_update({
                    "current_scenario_stage_id": next_stage_id,
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
            # 체크카드 정보 수집 처리
            is_cc_complete, missing_cc_fields = check_check_card_completion(collected_info, required_fields)
            
            if is_cc_complete:
                next_stage_id = "final_summary"
                # final_summary 프롬프트를 가져와서 변수들을 치환
                summary_prompt = active_scenario_data.get("stages", {}).get("final_summary", {}).get("prompt", "")
                summary_prompt = replace_template_variables(summary_prompt, collected_info)
                response_text = f"체크카드 설정이 완료되었습니다.\n\n{summary_prompt}"
            else:
                # 첫 응답에서는 현재 스테이지에 머물면서 추가 정보 요청
                if extraction_result.get("extracted_entities"):
                    # 사용자가 일부 정보를 제공한 경우
                    next_stage_id = "collect_check_card_info"  # 같은 스테이지 유지
                    response_text = f"네, 알겠습니다. {generate_check_card_prompt(missing_cc_fields)}"
                else:
                    # 사용자가 정보를 제공하지 않은 경우
                    next_stage_id = "ask_remaining_card_info"
                    response_text = generate_check_card_prompt(missing_cc_fields)
            
            print(f"[DEBUG] Check card - Complete: {is_cc_complete}, Missing: {missing_cc_fields}")
            print(f"[DEBUG] Next stage: {next_stage_id}")
            
        elif current_stage_id == "ask_remaining_card_info":
            # 부족한 체크카드 정보 재요청
            is_cc_complete, missing_cc_fields = check_check_card_completion(collected_info, required_fields)
            
            if is_cc_complete:
                next_stage_id = "final_summary"
                # final_summary 프롬프트를 가져와서 변수들을 치환
                summary_prompt = active_scenario_data.get("stages", {}).get("final_summary", {}).get("prompt", "")
                summary_prompt = replace_template_variables(summary_prompt, collected_info)
                response_text = f"체크카드 설정이 완료되었습니다.\n\n{summary_prompt}"
            else:
                next_stage_id = "ask_remaining_card_info"
                response_text = generate_check_card_prompt(missing_cc_fields)
            
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
        
        return state.merge_update({
            "current_scenario_stage_id": next_stage_id,
            "collected_product_info": collected_info,
            "final_response_text_for_tts": response_text,
            "is_final_turn_response": True,
            "action_plan": updated_plan,
            "action_plan_struct": updated_struct,
            "router_call_count": 0  # 라우터 카운트 초기화
        })
    
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
    
    # 스테이지 전환 로직 결정
    transitions = current_stage_info.get("transitions", [])
    default_next = current_stage_info.get("default_next_stage_id", "None")
    
    # Case 1: 분기가 없는 경우 (transitions가 없거나 1개)
    if len(transitions) <= 1:
        # 필요한 정보가 수집되었는지 확인
        expected_info_key = current_stage_info.get("expected_info_key")
        if expected_info_key and expected_info_key not in collected_info:
            # 필요한 정보가 아직 수집되지 않았으면 현재 스테이지 유지
            next_stage_id = current_stage_id
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

    return state.merge_update({
        "collected_product_info": collected_info, 
        "current_scenario_stage_id": determined_next_stage_id,
        "action_plan": updated_plan,
        "action_plan_struct": updated_struct
    })