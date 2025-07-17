# backend/app/graph/agent.py
import json
import yaml
import asyncio
from pathlib import Path
from typing import Dict, Optional, Sequence, Literal, Any, List, Union, cast, AsyncGenerator
import traceback

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END

from .state import AgentState, ScenarioAgentOutput, PRODUCT_TYPES
from .state_utils import ensure_pydantic_state, ensure_dict_state
from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME
from .models import (
    next_stage_decision_parser,
    initial_task_decision_parser,
    main_router_decision_parser,
    ActionModel,
    expanded_queries_parser
)
from .utils import (
    ALL_PROMPTS,
    ALL_SCENARIOS_DATA,
    get_active_scenario_data,
    load_knowledge_base_content_async,
    format_messages_for_prompt,
    format_transitions_for_prompt,
)
from .chains import (
    json_llm,
    generative_llm,
    synthesizer_chain,
    invoke_scenario_agent_logic
)
import re
from ..services.rag_service import rag_service
from ..services.web_search_service import web_search_service

# --- Import logger ---
from .logger import log_node_execution

# --- Helper Functions for Information Collection ---

# 키워드 기반 추출 로직 제거 - Entity Agent 사용으로 대체

def check_required_info_completion(collected_info: Dict, required_fields: List[Dict]) -> tuple[bool, List[str]]:
    """필수 정보 수집 완료 여부 확인"""
    missing_fields = []
    
    for field in required_fields:
        if field["required"] and field["key"] not in collected_info:
            missing_fields.append(field["display_name"])
    
    is_complete = len(missing_fields) == 0
    return is_complete, missing_fields

def generate_missing_info_prompt(missing_fields: List[str], collected_info: Dict) -> str:
    """부족한 정보에 대한 자연스러운 요청 메시지 생성"""
    if len(missing_fields) == 1:
        return f"{missing_fields[0]}에 대해서 알려주시겠어요?"
    elif len(missing_fields) == 2:
        return f"{missing_fields[0]}과(와) {missing_fields[1]}에 대해서 알려주시겠어요?"
    else:
        field_list = ", ".join(missing_fields[:-1])
        return f"{field_list}, 그리고 {missing_fields[-1]}에 대해서 알려주시겠어요?"

def get_next_missing_info_group_stage(collected_info: Dict, required_fields: List[Dict]) -> str:
    """수집된 정보를 바탕으로 다음에 물어볼 그룹 스테이지 결정"""
    # 그룹별 정보 확인
    group1_fields = ["loan_purpose_confirmed", "marital_status"]
    group2_fields = ["has_home", "annual_income"] 
    group3_fields = ["target_home_price"]
    
    print(f"현재 수집된 정보: {collected_info}")
    
    # 각 그룹에서 누락된 정보가 있는지 확인
    group1_missing = any(field not in collected_info for field in group1_fields)
    group2_missing = any(field not in collected_info for field in group2_fields)
    group3_missing = any(field not in collected_info for field in group3_fields)
    
    print(f"그룹별 누락 상태 - Group1: {group1_missing}, Group2: {group2_missing}, Group3: {group3_missing}")
    
    if group1_missing:
        return "ask_missing_info_group1"
    elif group2_missing:
        return "ask_missing_info_group2"
    elif group3_missing:
        return "ask_missing_info_group3"
    else:
        return "eligibility_assessment"

def generate_group_specific_prompt(stage_id: str, collected_info: Dict) -> str:
    """그룹별로 이미 수집된 정보를 제외하고 맞춤형 질문 생성"""
    print(f"질문 생성 - stage_id: {stage_id}, collected_info: {collected_info}")
    
    if stage_id == "ask_missing_info_group1":
        missing = []
        has_loan_purpose = collected_info.get("loan_purpose_confirmed", False)
        has_marital_status = "marital_status" in collected_info
        
        if not has_loan_purpose:
            missing.append("대출 목적(주택 구입용인지)")
        if not has_marital_status:
            missing.append("혼인 상태")
        
        print(f"Group1 누락 정보: {missing}")
        
        if len(missing) == 2:
            return "몇 가지 더 확인해볼게요. 대출 목적과 혼인 상태는 어떻게 되시나요?"
        elif "대출 목적(주택 구입용인지)" in missing:
            return "대출 목적을 확인해볼게요. 주택 구입 목적이 맞으신가요?"
        elif "혼인 상태" in missing:
            return "혼인 상태는 어떻게 되시나요? (미혼/기혼/예비부부)"
        else:
            # Group1의 모든 정보가 수집된 경우 Group2로 넘어가야 함
            return "추가 정보를 알려주시겠어요?"
            
    elif stage_id == "ask_missing_info_group2":
        missing = []
        if "has_home" not in collected_info:
            missing.append("주택 소유 여부")
        if "annual_income" not in collected_info:
            missing.append("연소득")
            
        if len(missing) == 2:
            return "현재 주택 소유 여부와 연소득은 어느 정도 되시나요?"
        elif "주택 소유 여부" in missing:
            return "현재 소유하고 계신 주택이 있으신가요?"
        else:
            return "연소득은 어느 정도 되시나요? (세전 기준)"
            
    elif stage_id == "ask_missing_info_group3":
        return "구매 예정이신 주택 가격은 어느 정도로 생각하고 계신가요?"
    
    return "추가 정보를 알려주시겠어요?"

# --- Import Node Functions ---
from .nodes.orchestrator.entry_point import entry_point_node
from .nodes.orchestrator.main_router import main_agent_router_node
from .nodes.control.end_conversation import end_conversation_node
from .nodes.control.synthesize import synthesize_response_node
from .nodes.control.set_product import set_product_type_node
from .nodes.workers.rag_worker import factual_answer_node
from .nodes.workers.web_worker import web_search_node

# --- Import Router ---
from .router import execute_plan_router, route_after_scenario_logic

# --- LangGraph Node Functions ---

async def call_scenario_agent_node(state: AgentState) -> AgentState:
    """
    시나리오 에이전트 호출 노드 - Pydantic 버전
    """
    # Convert to Pydantic for internal processing
    pydantic_state = ensure_pydantic_state(state)
    
    user_input = pydantic_state.stt_result or ""
    scenario_name = pydantic_state.active_scenario_name or "N/A"
    # user_input이 None인 경우 처리
    input_preview = user_input[:20] if user_input else ""
    log_node_execution("Scenario_NLU", f"scenario={scenario_name}, input='{input_preview}...'")
    active_scenario_data = get_active_scenario_data(pydantic_state.to_dict())
    if not active_scenario_data or not user_input:
        state_updates = {"scenario_agent_output": cast(ScenarioAgentOutput, {"intent": "error_missing_data", "is_scenario_related": False})}
        return ensure_dict_state(pydantic_state.merge_update(state_updates))
    
    current_stage_id = pydantic_state.current_scenario_stage_id or active_scenario_data.get("initial_stage_id")
    current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})

    output = await invoke_scenario_agent_logic(
        user_input=user_input,
        current_stage_prompt=current_stage_info.get("prompt", ""),
        expected_info_key=current_stage_info.get("expected_info_key"),
        messages_history=list(pydantic_state.messages)[:-1],
        scenario_name=active_scenario_data.get("scenario_name", "Consultation")
    )
    intent = output.get("intent", "N/A")
    
    entities = list(output.get("entities", {}).keys())
    log_node_execution("Scenario_NLU", output_info=f"intent={intent}, entities={entities}")
    
    state_updates = {"scenario_agent_output": output}
    return ensure_dict_state(pydantic_state.merge_update(state_updates))

async def process_scenario_logic_node(state: AgentState) -> AgentState:
    """
    시나리오 로직 처리 노드 - Pydantic 버전
    """
    # Convert to Pydantic for internal processing
    pydantic_state = ensure_pydantic_state(state)
    
    current_stage_id = pydantic_state.current_scenario_stage_id or "N/A"
    scenario_name = pydantic_state.active_scenario_name or "N/A"
    log_node_execution("Scenario_Flow", f"scenario={scenario_name}, stage={current_stage_id}")
    active_scenario_data = get_active_scenario_data(pydantic_state.to_dict())
    current_stage_id = pydantic_state.current_scenario_stage_id
    
    # 스테이지 ID가 없는 경우 초기 스테이지로 설정
    if not current_stage_id:
        current_stage_id = active_scenario_data.get("initial_stage_id", "greeting")
        print(f"스테이지 ID가 없어서 초기 스테이지로 설정: {current_stage_id}")
    
    current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
    print(f"현재 스테이지: {current_stage_id}, 스테이지 정보: {current_stage_info.keys()}")
    collected_info = pydantic_state.collected_product_info.copy()
    scenario_output = pydantic_state.scenario_agent_output
    user_input = pydantic_state.stt_result or ""
    
    # 개선된 다중 정보 수집 처리
    print(f"스테이지 정보 확인 - collect_multiple_info: {current_stage_info.get('collect_multiple_info')}")
    if current_stage_info.get("collect_multiple_info"):
        print("--- 다중 정보 수집 모드 ---")
        result = await process_multiple_info_collection(pydantic_state.to_dict(), active_scenario_data, current_stage_id, current_stage_info, collected_info, user_input)
        return result
    
    # 기존 단일 정보 수집 처리
    result = await process_single_info_collection(pydantic_state.to_dict(), active_scenario_data, current_stage_id, current_stage_info, collected_info, scenario_output, user_input)
    return result

async def process_multiple_info_collection(state: AgentState, active_scenario_data: Dict, current_stage_id: str, current_stage_info: Dict, collected_info: Dict, user_input: str) -> AgentState:
    """다중 정보 수집 처리 (개선된 그룹별 방식)"""
    required_fields = active_scenario_data.get("required_info_fields", [])
    
    # 현재 스테이지가 정보 수집 단계인지 확인
    print(f"현재 스테이지 ID: {current_stage_id}")
    if current_stage_id in ["info_collection_guidance", "process_collected_info", "ask_missing_info_group1", "ask_missing_info_group2", "ask_missing_info_group3", "eligibility_assessment"]:
        
        # Entity Agent를 사용한 정보 추출
        if user_input:
            from ..agents.entity_agent import entity_agent
            
            # Entity Agent로 정보 추출
            extraction_result = await entity_agent.process_slot_filling(user_input, required_fields, collected_info)
            
            # 추출된 정보 업데이트
            collected_info = extraction_result["collected_info"]
            print(f"Entity Agent 추출 결과: {extraction_result['extracted_entities']}")
            print(f"최종 업데이트된 수집 정보: {collected_info}")
        
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
                print(f"info_collection_guidance -> {next_stage_id}, 응답: {response_text}")
                
        elif current_stage_id == "process_collected_info":
            # 수집된 정보를 바탕으로 다음 그룹 결정
            if is_complete:
                next_stage_id = "eligibility_assessment"
                response_text = "네, 모든 정보를 확인했습니다! 말씀해주신 조건으로 디딤돌 대출 신청이 가능해 보입니다. 이제 신청에 필요한 서류와 절차를 안내해드릴게요."
            else:
                next_stage_id = get_next_missing_info_group_stage(collected_info, required_fields)
                response_text = generate_group_specific_prompt(next_stage_id, collected_info)
                print(f"다음 단계로 이동: {next_stage_id}, 질문: {response_text}")
                
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
                    
        elif current_stage_id == "eligibility_assessment":
            # 자격 검토 완료 후 서류 안내로 자동 진행
            next_stage_id = "application_documents_guidance"
            response_text = active_scenario_data.get("stages", {}).get("application_documents_guidance", {}).get("prompt", "서류 안내를 진행하겠습니다.")
            print(f"자격 검토 완료 -> 서류 안내 단계로 이동")
            
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
            
        return {
            **state, 
            "current_scenario_stage_id": next_stage_id,
            "collected_product_info": collected_info,
            "final_response_text_for_tts": response_text,
            "is_final_turn_response": True,
            "action_plan": updated_plan,
            "action_plan_struct": updated_struct
        }
    
    # 일반 스테이지는 기존 로직으로 처리
    return await process_single_info_collection(state, active_scenario_data, current_stage_id, current_stage_info, collected_info, state.get("scenario_agent_output"), user_input)

async def process_single_info_collection(state: AgentState, active_scenario_data: Dict, current_stage_id: str, current_stage_info: Dict, collected_info: Dict, scenario_output: Optional[ScenarioAgentOutput], user_input: str) -> AgentState:
    """기존 단일 정보 수집 처리"""

    if scenario_output and scenario_output.get("is_scenario_related"):
        entities = scenario_output.get("entities", {})
        intent = scenario_output.get("intent", "")
        
        print(f"Single info collection - intent: {intent}, entities: {entities}")
        
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
                    collected_info.update({k: v for k, v in entities.items() if v is not None})
                else:
                    print(f"--- Entity verification FAILED. Not updating collected info. ---")
            except Exception as e:
                print(f"Error during entity verification: {e}. Assuming not confirmed.")

        elif entities:
             collected_info.update({k: v for k, v in entities.items() if v is not None})

        print(f"Updated Info: {collected_info}")
    
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
            print(f"--- 자동 진행 차단: '{expected_info_key}' 정보 미수집 ---")
        elif len(transitions) == 1:
            # 단일 전환 경로가 있으면 자동 진행
            next_stage_id = transitions[0].get("next_stage_id", default_next)
            print(f"--- 자동 진행: 단일 경로 '{current_stage_id}' → '{next_stage_id}' ---")
        else:
            # transitions이 없으면 default로 진행
            next_stage_id = default_next
            print(f"--- 자동 진행: 기본 경로 '{current_stage_id}' → '{next_stage_id}' ---")
    
    # Case 2: 분기가 있는 경우 (transitions가 2개 이상) - LLM 판단
    else:
        print(f"--- LLM 판단 필요: {len(transitions)}개 분기 존재 ---")
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
        print(f"--- Logic Stage Detected: '{next_stage_id}'. Resolving next step automatically. ---")
        
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

# synthesize_response_node is now imported from .nodes.control.synthesize

# end_conversation_node is now imported from .nodes.control.end_conversation

# set_product_type_node is now imported from .nodes.control.set_product
    

# route_after_scenario_logic and execute_plan_router are now imported from .router

# --- Orchestration-Worker Graph Build ---
workflow = StateGraph(AgentState)

# Core Orchestrator
workflow.add_node("entry_point_node", entry_point_node)
workflow.add_node("main_agent_router_node", main_agent_router_node)

# Specialized Workers
workflow.add_node("scenario_worker", call_scenario_agent_node)
workflow.add_node("scenario_flow_worker", process_scenario_logic_node) 
workflow.add_node("rag_worker", factual_answer_node)
workflow.add_node("web_worker", web_search_node)

# Response & Control Nodes
workflow.add_node("synthesize_response_node", synthesize_response_node)
workflow.add_node("set_product_type_node", set_product_type_node)
workflow.add_node("end_conversation_node", end_conversation_node)

# Orchestrator Flow
workflow.set_entry_point("entry_point_node")
workflow.add_edge("entry_point_node", "main_agent_router_node")

# Orchestrator to Workers
workflow.add_conditional_edges(
    "main_agent_router_node",
    execute_plan_router,
    {
        "scenario_worker": "scenario_worker",
        "rag_worker": "rag_worker", 
        "web_worker": "web_worker",
        "synthesize_response_node": "synthesize_response_node",
        "set_product_type_node": "set_product_type_node",
        "end_conversation_node": "end_conversation_node",
    }
)

# Worker Flows
workflow.add_edge("scenario_worker", "scenario_flow_worker")
workflow.add_conditional_edges("scenario_flow_worker", execute_plan_router)
workflow.add_conditional_edges("rag_worker", execute_plan_router)
workflow.add_conditional_edges("web_worker", execute_plan_router)

workflow.add_edge("synthesize_response_node", END)
workflow.add_edge("set_product_type_node", END)
workflow.add_edge("end_conversation_node", END)

app_graph = workflow.compile()
print("--- LangGraph compiled successfully (Orchestration-Worker Architecture). ---")

# --- Backward Compatibility Exports ---
# 테스트와의 호환성을 위해 임시로 노드 함수들을 re-export
__all__ = [
    'entry_point_node', 
    'main_agent_router_node', 
    'synthesize_response_node',
    'set_product_type_node',
    'end_conversation_node',
    'execute_plan_router',
    'route_after_scenario_logic',
    'app_graph', 
    'run_agent_streaming'
]

async def run_agent_streaming(
    user_input_text: Optional[str] = None,
    user_input_audio_b64: Optional[str] = None,
    session_id: Optional[str] = "default_session",
    current_state_dict: Optional[Dict[str, Any]] = None
) -> AsyncGenerator[Union[Dict[str, Any], str], None]:
    
    if not OPENAI_API_KEY or not json_llm or not generative_llm:
        error_msg = "LLM service is not initialized. Please check API key."
        yield {"type": "error", "message": error_msg}
        yield {"type": "final_state", "data": {"error_message": error_msg, "is_final_turn_response": True}}
        return

    initial_state = cast(AgentState, {
        "session_id": session_id or "default_session",
        "user_input_text": user_input_text,
        "user_input_audio_b64": user_input_audio_b64,
        "messages": current_state_dict.get("messages", []) if current_state_dict else [],
        "current_product_type": current_state_dict.get("current_product_type") if current_state_dict else None,
        "current_scenario_stage_id": current_state_dict.get("current_scenario_stage_id") if current_state_dict else None,
        "collected_product_info": current_state_dict.get("collected_product_info", {}) if current_state_dict else {},
        "available_product_types": ["didimdol", "jeonse", "deposit_account"],
        "action_plan": [],
        "action_plan_struct": [],
        # 시나리오 연속성 상태 복원
        "scenario_ready_for_continuation": current_state_dict.get("scenario_ready_for_continuation", False) if current_state_dict else False,
        "scenario_awaiting_user_response": current_state_dict.get("scenario_awaiting_user_response", False) if current_state_dict else False,
    })

    print(f"\n🚀 ===== AGENT FLOW START [{session_id}] =====")
    log_node_execution("Session", f"product={initial_state['current_product_type']}, input='{user_input_text[:30]}...'")

    final_state: Optional[AgentState] = None
    streamed_text = ""

    try:
        final_state = await app_graph.ainvoke(initial_state)
        
        if final_state and final_state.get("final_response_text_for_tts"):
            text_to_stream = final_state["final_response_text_for_tts"]
            yield {"type": "stream_start"}
            for char in text_to_stream:
                yield char
                streamed_text += char
                await asyncio.sleep(0.01)
            yield {"type": "stream_end", "full_text": streamed_text}
        else:
            error_msg = final_state.get("error_message", "Failed to generate a response.")
            yield {"type": "error", "message": error_msg}
            if final_state: final_state["final_response_text_for_tts"] = error_msg

    except Exception as e:
        print(f"CRITICAL error in run_agent_streaming for session {session_id}: {e}")
        traceback.print_exc()
        error_response = "A critical system error occurred during processing."
        yield {"type": "error", "message": error_response}
        final_state = cast(AgentState, initial_state.copy())
        final_state["error_message"] = error_response
        final_state["is_final_turn_response"] = True
        final_state["messages"] = list(initial_state.get("messages", [])) + [AIMessage(content=error_response)]
    
    finally:
        if final_state:
            yield {"type": "final_state", "data": final_state}
        else:
            final_state = initial_state
            final_state["error_message"] = "Agent execution failed critically, no final state produced."
            final_state["is_final_turn_response"] = True
            yield {"type": "final_state", "data": final_state}
        print(f"🏁 ===== AGENT FLOW END [{session_id}] =====")