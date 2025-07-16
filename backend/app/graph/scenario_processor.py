"""
시나리오 처리 관련 함수들
- 시나리오 로직 처리, 정보 수집, 스테이지 전환 등
"""

import json
from typing import Dict, Any, List, Optional
from langchain_core.messages import HumanMessage
from langchain.output_parsers import PydanticOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field

from ..core.config import get_llm_model
from ..config.prompt_loader import ALL_PROMPTS
from ..services.service_selection_analyzer import service_selection_analyzer
from ..graph.chains import scenario_agent_chain, ScenarioAgentOutput
from .agent_utils import (
    extract_multiple_info_from_text,
    check_required_info_completion,
    generate_missing_info_prompt,
    get_next_missing_info_group_stage,
    generate_group_specific_prompt,
    format_transitions_for_prompt,
    get_active_scenario_data
)
from ..graph.state import AgentState

# json_llm 초기화
json_llm = get_llm_model(response_format={"type": "json_object"})


class NextStageDecision(BaseModel):
    """다음 스테이지 결정 모델"""
    chosen_next_stage_id: str = Field(description="선택된 다음 스테이지 ID")
    reasoning: str = Field(description="결정 이유")


next_stage_decision_parser = PydanticOutputParser(pydantic_object=NextStageDecision)


async def process_multiple_info_collection(
    state: AgentState, 
    active_scenario_data: Dict, 
    current_stage_id: str, 
    current_stage_info: Dict, 
    collected_info: Dict, 
    user_input: str
) -> AgentState:
    """다중 정보 수집 처리 (개선된 그룹별 방식)"""
    required_fields = active_scenario_data.get("required_info_fields", [])
    
    # 현재 스테이지가 정보 수집 단계인지 확인
    print(f"현재 스테이지 ID: {current_stage_id}")
    if current_stage_id in ["info_collection_guidance", "process_collected_info", "ask_missing_info_group1", "ask_missing_info_group2", "ask_missing_info_group3", "eligibility_assessment"]:
        
        # 사용자 입력에서 정보 추출
        if user_input:
            extracted_info = await extract_multiple_info_from_text(user_input, required_fields)
            print(f"LLM 기반 추출된 정보: {extracted_info}")
            
            # 시나리오 에이전트 결과도 활용
            scenario_output = state.get("scenario_agent_output", {})
            if scenario_output and scenario_output.get("entities"):
                scenario_entities = scenario_output["entities"]
                print(f"시나리오 에이전트 추출 정보: {scenario_entities}")
                
                # extracted_info에 없는 정보만 추가
                for key, value in scenario_entities.items():
                    if key not in extracted_info and value is not None:
                        extracted_info[key] = value
                
                # 특별 처리: 혼인상태
                if "marital_status" in scenario_entities:
                    extracted_info["marital_status"] = scenario_entities["marital_status"]
                    print(f"시나리오 에이전트에서 혼인상태 확인: {scenario_entities['marital_status']}")
            
            # 수집된 정보 업데이트
            collected_info.update(extracted_info)
            print(f"최종 업데이트된 수집 정보: {collected_info}")
        
        # 정보 수집 완료 여부 확인
        is_complete, missing_fields = check_required_info_completion(collected_info, required_fields)
        
        if current_stage_id == "info_collection_guidance":
            # 초기 정보 안내 후 바로 다음 그룹 질문 결정
            if is_complete:
                next_stage_id = "eligibility_assessment"
            else:
                next_stage_id = get_next_missing_info_group_stage(collected_info, required_fields)
            
            # 맞춤형 질문 생성
            customized_prompt = generate_group_specific_prompt(next_stage_id, collected_info)
            state["final_response_text_for_tts"] = customized_prompt
        
        elif current_stage_id == "process_collected_info":
            # 정보 수집 프로세스 중 동적 라우팅
            if is_complete:
                next_stage_id = "eligibility_assessment"
            else:
                next_stage_id = get_next_missing_info_group_stage(collected_info, required_fields)
                customized_prompt = generate_group_specific_prompt(next_stage_id, collected_info)
                state["final_response_text_for_tts"] = customized_prompt
        
        elif current_stage_id.startswith("ask_missing_info_group"):
            # 그룹별 질문 처리
            if user_input:
                # 다음 그룹 또는 평가로 이동
                if is_complete:
                    next_stage_id = "eligibility_assessment"
                else:
                    next_stage_id = get_next_missing_info_group_stage(collected_info, required_fields)
                    customized_prompt = generate_group_specific_prompt(next_stage_id, collected_info)
                    
                    # 이미 설정된 프롬프트가 없을 때만 설정
                    if not state.get("final_response_text_for_tts"):
                        state["final_response_text_for_tts"] = customized_prompt
            else:
                # 사용자 입력이 없으면 현재 스테이지 유지
                next_stage_id = current_stage_id
        
        elif current_stage_id == "eligibility_assessment":
            # 자격 평가는 별도 처리
            next_stage_id = current_stage_info.get("next_stage", "loan_recommendation")
        
        else:
            # 기본 다음 스테이지
            next_stage_id = current_stage_info.get("next_stage", "END")
    
    else:
        # 정보 수집 단계가 아닌 경우 기본 다음 스테이지 사용
        next_stage_id = current_stage_info.get("next_stage", "END")
    
    # 액션 플랜 업데이트
    updated_plan = state.get("action_plan", []).copy()
    if updated_plan:
        updated_plan.pop(0)
    
    updated_struct = state.get("action_plan_struct", []).copy()
    if updated_struct:
        updated_struct.pop(0)
    
    return {
        **state,
        "collected_product_info": collected_info,
        "current_scenario_stage_id": next_stage_id,
        "action_plan": updated_plan,
        "action_plan_struct": updated_struct
    }


async def process_single_info_collection(
    state: AgentState, 
    active_scenario_data: Dict, 
    current_stage_id: str, 
    current_stage_info: Dict, 
    collected_info: Dict, 
    scenario_output: Optional[ScenarioAgentOutput], 
    user_input: str
) -> AgentState:
    """기존 단일 정보 수집 처리 (LLM 기반 서비스 선택 분석 포함)"""

    if scenario_output and scenario_output.get("is_scenario_related"):
        entities = scenario_output.get("entities", {})
        intent = scenario_output.get("intent", "")
        
        # 🔥 LLM 기반 부가서비스 선택 분석 (입출금통장 시나리오 전용)
        if (current_stage_id in ["greeting_deposit", "clarify_services"] and 
            "additional_services_choice" in entities and 
            user_input and
            active_scenario_data.get("scenario_name") == "신한은행 입출금통장 신규 상담"):
            
            print(f"🔥 [LLM-based Service Analysis] Processing input: '{user_input}'")
            
            try:
                # LLM 기반 분석 수행
                normalized_value, next_stage_id, processing_info = await service_selection_analyzer.process_additional_services_input(
                    user_input=user_input,
                    collected_info=collected_info
                )
                
                print(f"🔥 [LLM Analysis] Result: value='{normalized_value}', next_stage='{next_stage_id}'")
                print(f"🔥 [LLM Analysis] Confidence: {processing_info.get('confidence', 0.0)}")
                
                if normalized_value:
                    # 정규화된 값으로 업데이트
                    entities["additional_services_choice"] = normalized_value
                    print(f"🔥 [LLM Analysis] Updated entity: additional_services_choice = '{normalized_value}'")
                else:
                    # 명확화가 필요한 경우 entities에서 제거
                    entities.pop("additional_services_choice", None)
                    print(f"🔥 [LLM Analysis] Unclear choice, entity removed for clarification")
                
                # 처리 정보를 상태에 저장 (디버깅용)
                state["llm_service_analysis"] = processing_info
                
            except Exception as e:
                print(f"🔥 [LLM Analysis] Error: {e}")
                # 오류 발생 시 기존 방식으로 fallback
        
        if entities and user_input:
            print(f"--- Verifying extracted entities: {entities} ---")
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
                    print(f"--- Entity verification PASSED. Updating collected info. ---")
                    # deposit_account 시나리오의 경우 엔티티 매핑 적용
                    if state.get("current_product_type") == "deposit_account":
                        entity_mapping = {
                            "name": "customer_name",
                            "contact": "phone_number"
                        }
                        mapped_entities = {}
                        for k, v in entities.items():
                            mapped_key = entity_mapping.get(k, k)
                            if v is not None:
                                mapped_entities[mapped_key] = v
                                print(f"Mapping: {k} -> {mapped_key} = {v}")
                        collected_info.update(mapped_entities)
                        print(f"Mapped entities: {mapped_entities}")
                    else:
                        collected_info.update({k: v for k, v in entities.items() if v is not None})
                else:
                    print(f"--- Entity verification FAILED. Not updating collected info. ---")
            except Exception as e:
                print(f"Error during entity verification: {e}. Assuming not confirmed.")

        elif entities:
            # deposit_account 시나리오의 경우 엔티티 매핑
            if state.get("current_product_type") == "deposit_account":
                entity_mapping = {
                    "name": "customer_name",
                    "contact": "phone_number"
                }
                mapped_entities = {}
                for k, v in entities.items():
                    mapped_key = entity_mapping.get(k, k)
                    if v is not None:
                        mapped_entities[mapped_key] = v
                collected_info.update(mapped_entities)
            else:
                collected_info.update({k: v for k, v in entities.items() if v is not None})
        
        # deposit_account의 yes/no 질문에 대한 LLM 기반 처리
        if (state.get("current_product_type") == "deposit_account" and 
            current_stage_id == "collect_basic" and 
            "use_lifelong_account" not in collected_info and
            len(collected_info) >= 2):
            
            print(f"🔍 [LLM-based Analysis] Processing yes/no response for use_lifelong_account")
            
            # LLM을 통한 yes/no 분석
            yes_no_prompt = f"""
사용자에게 평생계좌 서비스 사용 여부를 물어봤고, 사용자가 다음과 같이 답변했습니다:
"{user_input}"

이 답변이 긍정(예/동의)인지 부정(아니오/거부)인지 판단해주세요.

다음 JSON 형식으로만 응답하세요:
{{
    "is_positive": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "판단 근거"
}}
"""
            try:
                response = await json_llm.ainvoke([HumanMessage(content=yes_no_prompt)])
                result = json.loads(response.content.strip().replace("```json", "").replace("```", ""))
                
                is_positive = result.get("is_positive", None)
                confidence = result.get("confidence", 0.0)
                reasoning = result.get("reasoning", "")
                
                print(f"🔍 [LLM Analysis] Result: {'긍정' if is_positive else '부정'}, Confidence: {confidence}")
                print(f"🔍 [LLM Analysis] Reasoning: {reasoning}")
                
                if confidence >= 0.7 and is_positive is not None:
                    collected_info["use_lifelong_account"] = is_positive
                    print(f"평생계좌 사용 {'동의' if is_positive else '거부'}로 해석: use_lifelong_account = {is_positive}")
                else:
                    print(f"🔍 [LLM Analysis] Confidence too low ({confidence}), skipping field update")
                    
            except Exception as e:
                print(f"🔍 [LLM Analysis] Error: {e}")

        print(f"Updated Info: {collected_info}")
    
    # slot_filling 타입 스테이지 처리
    if current_stage_info.get("type") == "slot_filling":
        print(f"--- Slot Filling Stage: {current_stage_id} ---")
        required_fields = current_stage_info.get("required_fields", [])
        
        # 현재 스테이지의 필수 필드만 확인
        stage_fields = []
        all_fields = active_scenario_data.get("slot_fields", [])
        for field in all_fields:
            if field["key"] in required_fields:
                stage_fields.append(field)
        
        # 필수 필드 수집 완료 여부 확인
        all_collected = True
        for field_key in required_fields:
            if field_key not in collected_info:
                all_collected = False
                break
        
        print(f"Required fields: {required_fields}")
        print(f"Collected info keys: {list(collected_info.keys())}")
        print(f"Collected info full: {collected_info}")
        print(f"All collected: {all_collected}")
        
        if all_collected:
            # 모든 필수 필드가 수집되었으면 다음 스테이지로 진행
            determined_next_stage_id = current_stage_info.get("next_stage", "END")
            print(f"All required fields collected. Moving to next stage: {determined_next_stage_id}")
        else:
            # 아직 수집되지 않은 필드가 있으면 현재 스테이지 유지
            determined_next_stage_id = current_stage_id
            print(f"Missing some required fields. Staying at current stage: {current_stage_id}")
        
        # 응답 메시지 생성
        if all_collected:
            # 모든 필드가 수집되면 완료 메시지
            state["final_response_text_for_tts"] = current_stage_info.get("completion_message", "기본 정보 확인이 완료되었습니다.")
        else:
            # 수집되지 않은 필드에 따른 메시지
            if "customer_name" not in collected_info or "phone_number" not in collected_info:
                # 이름이나 연락처가 없으면 기본 메시지
                state["final_response_text_for_tts"] = current_stage_info.get("message", "")
            elif "use_lifelong_account" not in collected_info:
                # 이름과 연락처는 있지만 평생계좌 사용 여부가 없으면
                state["final_response_text_for_tts"] = "평생계좌 서비스를 이용하시겠어요? 휴대폰번호를 계좌번호로 사용할 수 있어 편리합니다."
    else:
        # 기존 로직으로 처리
        determined_next_stage_id = None
    
    # 기존 LLM 기반 다음 스테이지 결정 (slot_filling이 아닌 경우만)
    if determined_next_stage_id is None:
        # 먼저 LLM을 통해 다음 스테이지를 결정
        prompt_template = ALL_PROMPTS.get('main_agent', {}).get('determine_next_scenario_stage', '')
        llm_prompt = prompt_template.format(
            active_scenario_name=active_scenario_data.get("scenario_name"),
            current_stage_id=str(current_stage_id),
            current_stage_prompt=current_stage_info.get("prompt", "No prompt"),
            user_input=state.get("stt_result", ""),
            scenario_agent_intent=scenario_output.get("intent", "N/A"),
            scenario_agent_entities=str(scenario_output.get("entities", {})),
            collected_product_info=str(collected_info),
            formatted_transitions=format_transitions_for_prompt(current_stage_info.get("transitions", []), current_stage_info.get("prompt", "")),
            default_next_stage_id=current_stage_info.get("default_next_stage_id", "None")
        )
        response = await json_llm.ainvoke([HumanMessage(content=llm_prompt)])
        decision_data = next_stage_decision_parser.parse(response.content)
        next_stage_id = decision_data.chosen_next_stage_id
    else:
        # slot_filling에서 이미 결정된 다음 스테이지 사용
        next_stage_id = determined_next_stage_id

    # --- 로직 전용 스테이지 처리 루프 ---
    while True:
        if not next_stage_id or str(next_stage_id).startswith("END"):
            break  # 종료 상태에 도달하면 루프 탈출

        next_stage_info = active_scenario_data.get("stages", {}).get(str(next_stage_id), {})
        
        # 스테이지에 `prompt` 또는 `message`가 있으면 '말하는 스테이지'로 간주하고 루프 탈출
        if next_stage_info.get("prompt") or next_stage_info.get("message"):
            break
        
        # `prompt`가 없는 로직 전용 스테이지인 경우, 자동으로 다음 단계 진행
        print(f"--- Logic Stage Detected: '{next_stage_id}'. Resolving next step automatically. ---")
        
        current_stage_id_for_prompt = str(next_stage_id)
        
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
    
    updated_plan = state.get("action_plan", []).copy()
    if updated_plan:
        updated_plan.pop(0)
    
    updated_struct = state.get("action_plan_struct", []).copy()
    if updated_struct:
        updated_struct.pop(0)

    return {
        **state, 
        "collected_product_info": collected_info, 
        "current_scenario_stage_id": determined_next_stage_id,
        "action_plan": updated_plan,
        "action_plan_struct": updated_struct
    }


async def process_scenario_logic_node(state: AgentState) -> AgentState:
    """시나리오 로직 처리를 위한 메인 함수"""
    print("--- Node: Process Scenario Logic ---")
    
    active_scenario_data = get_active_scenario_data(state)
    current_stage_id = state.get("current_scenario_stage_id")
    
    # 스테이지 ID가 없는 경우 초기 스테이지로 설정
    if not current_stage_id:
        current_stage_id = active_scenario_data.get("initial_stage_id", "greeting")
        print(f"스테이지 ID가 없어서 초기 스테이지로 설정: {current_stage_id}")
    
    current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
    print(f"현재 스테이지: {current_stage_id}, 스테이지 정보: {current_stage_info.keys()}")
    collected_info = state.get("collected_product_info", {}).copy()
    scenario_output = state.get("scenario_agent_output")
    user_input = state.get("stt_result", "")
    
    # 개선된 다중 정보 수집 처리
    print(f"스테이지 정보 확인 - collect_multiple_info: {current_stage_info.get('collect_multiple_info')}")
    if current_stage_info.get("collect_multiple_info"):
        print("--- 다중 정보 수집 모드 ---")
        return await process_multiple_info_collection(state, active_scenario_data, current_stage_id, current_stage_info, collected_info, user_input)
    
    # 기존 단일 정보 수집 처리
    return await process_single_info_collection(state, active_scenario_data, current_stage_id, current_stage_info, collected_info, scenario_output, user_input)