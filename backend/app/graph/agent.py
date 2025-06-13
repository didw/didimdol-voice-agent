# agent.py

import json
import asyncio
import traceback
from typing import Dict, Optional, Any, List, Union, cast, AsyncGenerator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END

from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME

# 이 프로젝트의 다른 모듈들을 가져옵니다.
from .utils import (
    AgentState, PRODUCT_TYPES, ScenarioAgentOutput, get_active_scenario_data, 
    load_all_scenarios_sync, ALL_SCENARIOS_DATA, format_messages_for_prompt, 
    format_transitions_for_prompt, load_knowledge_base_content_async, 
    KNOWLEDGE_BASE_FILES, get_active_knowledge_base,
    ALL_SCENARIOS_DATA,
)
from .prompts import (
    initial_task_decision_parser, main_router_decision_parser, 
    next_stage_decision_parser, scenario_output_parser, ALL_PROMPTS, 
    InitialTaskDecisionModel, NextStageDecisionModel, load_all_prompts_sync
)
from .tools import (
    json_llm, generative_llm, synthesizer_chain, 
    invoke_qa_agent_streaming_logic, invoke_scenario_agent_logic
)

# 애플리케이션 시작 시 데이터 동기적으로 로드
load_all_prompts_sync()
load_all_scenarios_sync()


# --- LangGraph 노드 함수 정의 ---

async def entry_point_node(state: AgentState) -> AgentState:
    print("--- 노드: Entry Point ---")
    if not ALL_SCENARIOS_DATA or not ALL_PROMPTS:
        error_msg = "상담 서비스 초기화 실패 (시나리오 또는 프롬프트 데이터 로드 불가)."
        print(f"CRITICAL: 필수 데이터가 로드되지 않았습니다.")
        return {**state, "error_message": error_msg, "final_response_text_for_tts": error_msg, "is_final_turn_response": True}

    turn_specific_defaults: Dict[str, Any] = {
        "stt_result": None, "main_agent_routing_decision": None, "main_agent_direct_response": None,
        "scenario_agent_output": None, "final_response_text_for_tts": None,
        "is_final_turn_response": False, "error_message": None,
        "active_scenario_data": None, "active_knowledge_base_content": None, "active_scenario_name": None,
        "available_product_types": ["didimdol", "jeonse", "deposit_account"],
        "loan_selection_is_fresh": False, "factual_response": None,
    }
    
    current_product_type = state.get("current_product_type")
    updated_state = {**state, **turn_specific_defaults}
    updated_state["current_product_type"] = current_product_type

    if current_product_type:
        active_scenario = ALL_SCENARIOS_DATA.get(current_product_type)
        if active_scenario:
            updated_state["active_scenario_data"] = active_scenario
            updated_state["active_scenario_name"] = active_scenario.get("scenario_name", "알 수 없는 상품")
            if not updated_state.get("current_scenario_stage_id"):
                 updated_state["current_scenario_stage_id"] = active_scenario.get("initial_stage_id")
        else:
            updated_state["error_message"] = f"선택하신 '{current_product_type}' 상품 정보를 불러올 수 없습니다."
            updated_state["current_product_type"] = None
    else:
        updated_state["active_scenario_name"] = "미정"

    user_text_for_turn = updated_state.get("stt_result") or updated_state.get("user_input_text")
    
    current_messages = list(updated_state.get("messages", []))
    if user_text_for_turn:
        if not current_messages or not (isinstance(current_messages[-1], HumanMessage) and current_messages[-1].content == user_text_for_turn):
            current_messages.append(HumanMessage(content=user_text_for_turn))
        updated_state["messages"] = current_messages
        updated_state["stt_result"] = user_text_for_turn
    
    return cast(AgentState, updated_state)

async def main_agent_router_node(state: AgentState) -> AgentState:
    print("--- 노드: Main Agent Router ---")
    if not json_llm:
        return {**state, "error_message": "라우터 서비스 사용 불가 (LLM 미초기화)", "final_response_text_for_tts": "시스템 설정 오류입니다.", "is_final_turn_response": True}
 
    user_input = state.get("stt_result", "")
    messages_history = state.get("messages", [])
    current_product_type = state.get("current_product_type")
    active_scenario_data = get_active_scenario_data(state)
    session_id = state.get("session_id", "")
    
    prompt_template_key = 'initial_task_selection_prompt' if not current_product_type else 'router_prompt'
    print(f"Main Agent Router: {'상품 유형 미선택' if not current_product_type else f'현재 상품 유형: {current_product_type}'}, '{prompt_template_key}' 사용.")

    prompt_template = ALL_PROMPTS.get('main_agent', {}).get(prompt_template_key, '')
    if not prompt_template:
         return {**state, "error_message": "라우터 프롬프트 로드 실패", "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True}

    history_for_prompt = messages_history[:-1] if messages_history and isinstance(messages_history[-1], HumanMessage) else messages_history
    formatted_history_str = format_messages_for_prompt(history_for_prompt)
    
    current_stage_id = state.get("current_scenario_stage_id", "정보 없음")
    current_stage_prompt = "정보 없음"
    expected_info_key = "정보 없음"
    active_scenario_name = state.get("active_scenario_name", "미정")

    if active_scenario_data:
        current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
        current_stage_prompt = current_stage_info.get("prompt", "안내 없음")
        expected_info_key = current_stage_info.get("expected_info_key", "정보 없음")
    
    available_product_types_display = ", ".join([ALL_SCENARIOS_DATA[lt]["scenario_name"] for lt in state.get("available_product_types", []) if lt in ALL_SCENARIOS_DATA])

    try:
        if prompt_template_key == 'initial_task_selection_prompt':
            parser = initial_task_decision_parser
            format_instructions = parser.get_format_instructions()
            filled_prompt = prompt_template.format(user_input=user_input, format_instructions=format_instructions)
        else: # router_prompt
            parser = main_router_decision_parser
            format_instructions = parser.get_format_instructions()
            filled_prompt = prompt_template.format(
                user_input=user_input, active_scenario_name=active_scenario_name,
                formatted_messages_history=formatted_history_str, current_scenario_stage_id=current_stage_id,
                current_stage_prompt=current_stage_prompt, collected_product_info=str(state.get("collected_product_info", {})),
                expected_info_key=expected_info_key, available_product_types_display=available_product_types_display,
                format_instructions=format_instructions
            )
            
        response = await json_llm.ainvoke([HumanMessage(content=filled_prompt)])
        raw_response = response.content.strip()
        print(f"[{session_id}] LLM Raw Response: {raw_response}")
        
        if raw_response.startswith("```json"):
            raw_response = raw_response.replace("```json", "").replace("```", "").strip()
        
        parsed_decision = parser.parse(raw_response)
        
        new_state: Dict[str, Any] = {"main_agent_routing_decision": parsed_decision.action}
        if hasattr(parsed_decision, 'direct_response') and parsed_decision.direct_response:
            new_state["main_agent_direct_response"] = parsed_decision.direct_response
        
        system_log = f"Main Agent 판단: action='{parsed_decision.action}'"
        updated_messages = list(state.get("messages", [])) + [SystemMessage(content=system_log)]
        new_state["messages"] = updated_messages

        if prompt_template_key == 'initial_task_selection_prompt':
            initial_decision = cast(InitialTaskDecisionModel, parsed_decision)
            action_map = {
                "proceed_with_product_type_didimdol": ("didimdol", "set_product_type_didimdol"),
                "proceed_with_product_type_jeonse": ("jeonse", "set_product_type_jeonse"),
                "proceed_with_product_type_deposit_account": ("deposit_account", "set_product_type_deposit_account"),
            }
            if initial_decision.action in action_map:
                product_type, route_decision = action_map[initial_decision.action]
                new_state.update({
                    "current_product_type": product_type,
                    "main_agent_routing_decision": route_decision,
                    "loan_selection_is_fresh": True
                })
            elif initial_decision.action == "invoke_qa_agent_general":
                new_state.update({"main_agent_routing_decision": "invoke_qa_agent", "active_scenario_name": "일반 금융 상담"})
            elif initial_decision.action == "clarify_product_type":
                new_state.update({
                    "main_agent_routing_decision": "select_product_type",
                    "main_agent_direct_response": initial_decision.direct_response or f"어떤 상품에 대해 안내해 드릴까요? {available_product_types_display} 중에서 선택해주세요."
                })
            elif initial_decision.action == "answer_directly_chit_chat":
                new_state.update({"main_agent_routing_decision": "answer_directly_chit_chat"})
            else: 
                new_state["main_agent_routing_decision"] = "unclear_input"

        print(f"Main Agent 최종 결정: {new_state.get('main_agent_routing_decision')}")
        return {**state, **new_state}

    except Exception as e:
        err_msg = "요청 처리 중 시스템 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        print(f"Main Agent Router 시스템 오류: {e}\n{traceback.format_exc()}")
        return {**state, "error_message": err_msg, "final_response_text_for_tts": err_msg, "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True}


async def call_scenario_agent_node(state: AgentState) -> AgentState:
    print("--- 노드: Scenario Agent 호출 ---")
    active_scenario_data = get_active_scenario_data(state)

    if not active_scenario_data:
        return {**state, "error_message": "시나리오 에이전트 호출 실패: 활성 시나리오 데이터가 없습니다.", "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True}

    current_stage_id = state.get("current_scenario_stage_id", active_scenario_data.get("initial_stage_id"))
    current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})

    output = await invoke_scenario_agent_logic(
        user_input=state.get("stt_result", ""),
        current_stage_prompt=current_stage_info.get("prompt", ""),
        expected_info_key=current_stage_info.get("expected_info_key"),
        messages_history=state.get("messages", [])[:-1],
        scenario_name=active_scenario_data.get("scenario_name", "상담")
    )
    return {**state, "scenario_agent_output": output}

# (이하 생략된 노드 함수들: factual_answer_node, synthesize_answer_node, main_agent_scenario_processing_node, ...)
# ... 제공된 코드의 나머지 노드 함수들을 여기에 그대로 붙여넣습니다. 
# ... (분량 문제로 생략하지만, 제공된 원본 코드와 동일하게 작성되어야 합니다)
# --- (이하 나머지 노드 함수 및 그래프 정의) ---
async def factual_answer_node(state: AgentState) -> dict:
    """QA Agent(RAG)를 호출하여 사실 기반 답변을 생성하고 상태에 저장합니다."""
    print("--- 노드: Factual Answer (QA Agent) ---")
    user_question = state.get("stt_result", "")
    qa_context_product_type = state.get("current_product_type")
    qa_scenario_name = state.get("active_scenario_name", "일반 금융 상담")
    factual_response = "관련 정보를 찾지 못했습니다."

    if not generative_llm:
        print("Factual Answer Node 오류: LLM이 초기화되지 않았습니다.")
        return {"factual_response": "답변 생성 서비스에 문제가 발생했습니다."}

    try:
        kb_content_for_qa = None
        if qa_context_product_type and qa_context_product_type in KNOWLEDGE_BASE_FILES:
            kb_content_for_qa = await load_knowledge_base_content_async(cast(PRODUCT_TYPES, qa_context_product_type))
        
        rag_prompt_template_str = ALL_PROMPTS.get('qa_agent', {}).get('rag_answer_generation')
        if not rag_prompt_template_str: raise ValueError("RAG 프롬프트를 찾을 수 없습니다.")

        context_for_llm = kb_content_for_qa or "특정 상품 문서가 제공되지 않았습니다. 사용자의 질문에만 기반하여 일반적인 답변을 해주세요."

        response = await generative_llm.ainvoke([HumanMessage(content=rag_prompt_template_str.format(
            scenario_name=qa_scenario_name,
            context_for_llm=context_for_llm,
            user_question=user_question
        ))])
        if response and response.content:
            factual_response = response.content.strip()

        print(f"QA Agent 답변: {factual_response}")

    except Exception as e:
        print(f"Factual Answer Node 실행 중 오류 발생: {e}")
        factual_response = "정보를 찾는 중 시스템 오류가 발생했습니다."

    return {"factual_response": factual_response}


async def synthesize_answer_node(state: AgentState) -> dict:
    """문맥적 답변과 사실적 답변을 조합하여 최종 답변을 생성합니다."""
    print("--- 노드: Synthesize Answer ---")
    if not synthesizer_chain:
        print("Synthesize Answer Node 오류: Synthesizer chain이 초기화되지 않았습니다.")
        return {"final_response_text_for_tts": state.get("main_agent_direct_response", "죄송합니다. 답변 생성에 오류가 발생했습니다."), "is_final_turn_response": True}
        
    user_question = state["messages"][-1].content
    contextual_response = state.get("main_agent_direct_response") or "정보 없음"
    factual_response = state.get("factual_response") or "정보 없음"

    final_answer: str
    if contextual_response == "정보 없음" and factual_response == "정보 없음":
         final_answer = "죄송하지만, 문의하신 내용에 대해 지금 답변을 드리기 어렵습니다. 다시 질문해주시겠어요?"
    else:
        response = await synthesizer_chain.ainvoke({
            "chat_history": state['messages'][:-1],
            "user_question": user_question,
            "contextual_response": contextual_response,
            "factual_response": factual_response,
        })
        final_answer = response.content.strip()
        
    print(f"최종 합성 답변: {final_answer}")
    
    updated_messages = list(state['messages']) + [AIMessage(content=final_answer)]
    
    return {"final_response_text_for_tts": final_answer, "messages": updated_messages, "is_final_turn_response": True}


async def main_agent_scenario_processing_node(state: AgentState) -> AgentState:
    print("--- 노드: Main Agent 시나리오 처리 (다음 단계 결정 및 응답 생성) ---")
    if not json_llm:
         return {**state, "error_message": "시나리오 처리 서비스 사용 불가 (LLM 미초기화)", "final_response_text_for_tts": "시스템 설정 오류로 다음 안내를 드릴 수 없습니다.", "is_final_turn_response": True}

    user_input = state.get("stt_result", "")
    scenario_output = state.get("scenario_agent_output")
    active_scenario_data = get_active_scenario_data(state)
    
    if not active_scenario_data:
        return {**state, "error_message": "시나리오 처리 실패: 현재 상품 유형 또는 시나리오 데이터가 없습니다.", "is_final_turn_response": True}

    current_stage_id = state.get("current_scenario_stage_id", active_scenario_data.get("initial_stage_id"))
    stages_data = active_scenario_data.get("stages", {})
    current_stage_info = stages_data.get(str(current_stage_id), {})
    collected_info = state.get("collected_product_info", {}).copy()

    determined_next_stage_id: str = str(current_stage_id)

    if scenario_output and scenario_output.get("is_scenario_related"):
        extracted_entities = scenario_output.get("entities", {})
        for key, value in extracted_entities.items():
            if value is not None:
                collected_info[key] = value
                print(f"정보 업데이트: {key} = {value}")
        
        prompt_template = ALL_PROMPTS.get('main_agent', {}).get('determine_next_scenario_stage', '')
        if not prompt_template:
            print("오류: 다음 단계 결정 프롬프트를 찾을 수 없습니다.")
            determined_next_stage_id = current_stage_info.get("default_next_stage_id", current_stage_id)
        else:
            formatted_transitions_str = format_transitions_for_prompt(
                current_stage_info.get("transitions", []), current_stage_info.get("prompt","")
            )

            llm_prompt = prompt_template.format(
                active_scenario_name=active_scenario_data.get("scenario_name", "상담"),
                current_stage_id=str(current_stage_id),
                current_stage_prompt=current_stage_info.get("prompt", "안내 없음"),
                user_input=user_input,
                scenario_agent_intent=scenario_output.get("intent", "정보 없음"),
                scenario_agent_entities=str(scenario_output.get("entities", {})),
                collected_product_info=str(collected_info),
                formatted_transitions=formatted_transitions_str,
                default_next_stage_id=current_stage_info.get("default_next_stage_id", "None")
            )
            try:
                response = await json_llm.ainvoke([HumanMessage(content=llm_prompt)])
                raw_response = response.content.strip()
                if raw_response.startswith("```json"):
                    raw_response = raw_response.replace("```json", "").replace("```", "").strip()
                decision_data = next_stage_decision_parser.parse(raw_response)
                determined_next_stage_id = decision_data.chosen_next_stage_id
                print(f"LLM 결정 다음 단계 ID: '{determined_next_stage_id}'")
                if determined_next_stage_id not in stages_data and determined_next_stage_id not in ["END_SCENARIO_COMPLETE", "END_SCENARIO_ABORT", f"qa_listen_{state.get('current_product_type')}"]:
                    print(f"경고: LLM이 반환한 ID ('{determined_next_stage_id}')가 유효하지 않습니다. 기본값 사용.")
                    determined_next_stage_id = current_stage_info.get("default_next_stage_id", str(current_stage_id))
            except Exception as e:
                print(f"다음 단계 결정 LLM 오류: {e}. 기본값 사용.")
                determined_next_stage_id = current_stage_info.get("default_next_stage_id", str(current_stage_id))
    
    if not determined_next_stage_id or determined_next_stage_id == "None":
        determined_next_stage_id = "END_SCENARIO_COMPLETE"

    target_stage_info = stages_data.get(determined_next_stage_id, {})
    final_response_text_for_user: str
    if determined_next_stage_id == "END_SCENARIO_COMPLETE":
        final_response_text_for_user = active_scenario_data.get("end_scenario_message", "상담이 완료되었습니다.")
    elif determined_next_stage_id == "END_SCENARIO_ABORT":
        final_response_text_for_user = target_stage_info.get("prompt") or active_scenario_data.get("end_conversation_message", "상담을 종료합니다.")
    else: 
        final_response_text_for_user = target_stage_info.get("prompt", active_scenario_data.get("fallback_message"))
        # Placeholder replacement
        import re
        def replace_placeholder(match):
            key = match.group(1)
            return str(collected_info.get(key, f"%{{{key}}}%"))
        final_response_text_for_user = re.sub(r'%\{([^}]+)\}%', replace_placeholder, final_response_text_for_user)

    print(f"시나리오 처리 결과: 다음 안내 '{final_response_text_for_user[:70]}...', 다음 단계 ID '{determined_next_stage_id}'")
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=final_response_text_for_user)]
    
    return {
        **state, 
        "collected_product_info": collected_info,
        "current_scenario_stage_id": determined_next_stage_id,
        "final_response_text_for_tts": final_response_text_for_user,
        "messages": updated_messages,
        "is_final_turn_response": True
    }

async def prepare_direct_response_node(state: AgentState) -> AgentState:
    print("--- 노드: 직접 응답 준비 ---")
    response_text = state.get("main_agent_direct_response")
    if not response_text:
        active_scenario = get_active_scenario_data(state)
        response_text = active_scenario.get("fallback_message") if active_scenario else "죄송합니다, 잘 이해하지 못했습니다."
        print(f"경고: direct_response 없음. fallback 사용: {response_text}")

    updated_messages = list(state.get("messages", [])) + [AIMessage(content=response_text)]
    return {**state, "final_response_text_for_tts": response_text, "messages": updated_messages, "is_final_turn_response": True}

async def set_product_type_node(state: AgentState) -> AgentState:
    print("--- 노드: 상품 유형 설정 ---")
    routing_decision = state.get("main_agent_routing_decision")
    product_map = {
        "set_product_type_didimdol": "didimdol",
        "set_product_type_jeonse": "jeonse",
        "set_product_type_deposit_account": "deposit_account",
    }
    new_product_type = product_map.get(routing_decision)
    
    if new_product_type and new_product_type in ALL_SCENARIOS_DATA:
        active_scenario = ALL_SCENARIOS_DATA[new_product_type]
        initial_stage_id = active_scenario.get("initial_stage_id")
        initial_stage_info = active_scenario.get("stages", {}).get(str(initial_stage_id), {})
        final_response = ""

        if state.get("loan_selection_is_fresh"):
            final_response += f"네, {active_scenario.get('scenario_name', new_product_type + ' 상품')}에 대해 안내해 드리겠습니다. "
        
        final_response += initial_stage_info.get("prompt", f"{active_scenario.get('scenario_name')} 상담을 시작하겠습니다.")
        
        print(f"상품 유형 '{new_product_type}' 설정. 시작 단계: '{initial_stage_id}', 안내: '{final_response[:70]}...'")
        updated_messages = list(state.get("messages", [])) + [AIMessage(content=final_response)]

        return {
            **state, "current_product_type": new_product_type,
            "active_scenario_data": active_scenario, "active_scenario_name": active_scenario.get("scenario_name"),
            "current_scenario_stage_id": initial_stage_id, "collected_product_info": {},
            "final_response_text_for_tts": final_response, "messages": updated_messages,
            "is_final_turn_response": True 
        }
    else:
        error_msg = f"요청하신 상품 유형('{new_product_type}')을 처리할 수 없습니다."
        print(error_msg)
        updated_messages = list(state.get("messages", [])) + [AIMessage(content=error_msg)]
        return {**state, "error_message": error_msg, "final_response_text_for_tts": error_msg, "messages": updated_messages, "is_final_turn_response": True}

async def prepare_fallback_response_node(state: AgentState) -> AgentState:
    print("--- 노드: 폴백 응답 준비 ---")
    active_scenario = get_active_scenario_data(state)
    default_fallback = "죄송합니다, 잘 이해하지 못했습니다. 다시 말씀해주시겠어요?"
    response_text = state.get("error_message") or (active_scenario.get("fallback_message") if active_scenario else default_fallback)
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=response_text)]
    return {**state, "final_response_text_for_tts": response_text, "messages": updated_messages, "is_final_turn_response": True}

async def prepare_end_conversation_node(state: AgentState) -> AgentState:
    print("--- 노드: 대화 종료 메시지 준비 ---")
    active_scenario = get_active_scenario_data(state)
    default_end_msg = "상담을 종료합니다. 이용해주셔서 감사합니다."
    response_text = (active_scenario.get("end_conversation_message") if active_scenario else default_end_msg) or default_end_msg
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=response_text)]
    return {**state, "final_response_text_for_tts": response_text, "messages": updated_messages, "is_final_turn_response": True, "current_scenario_stage_id": "END_SCENARIO_ABORT"}

async def handle_error_node(state: AgentState) -> AgentState:
    print("--- 노드: 에러 핸들링 (최종) ---")
    error_msg = state.get("error_message", "알 수 없는 오류가 발생했습니다. 죄송합니다.")
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=error_msg)]
    return {**state, "final_response_text_for_tts": error_msg, "is_final_turn_response": True, "messages": updated_messages}

# --- 조건부 엣지 로직 ---
def route_from_entry(state: AgentState) -> str:
    return END if state.get("is_final_turn_response") else "main_agent_router_node"

def route_from_main_agent_router(state: AgentState) -> str:
    decision = state.get("main_agent_routing_decision")
    print(f"Main Agent 라우팅 결정: {decision}")
    if state.get("is_final_turn_response"): return END

    route_map = {
        "set_product_type_didimdol": "set_product_type_node",
        "set_product_type_jeonse": "set_product_type_node",
        "set_product_type_deposit_account": "set_product_type_node",
        "select_product_type": "prepare_direct_response_node",
        "answer_directly_chit_chat": "prepare_direct_response_node",
        "invoke_scenario_agent": "call_scenario_agent_node",
        "invoke_qa_agent": "factual_answer_node",
        "end_conversation": "prepare_end_conversation_node",
    }
    
    if decision == "invoke_scenario_agent" and not state.get("current_product_type"):
        print("경고: invoke_scenario_agent 요청되었으나 current_product_type 미설정. 재라우팅.")
        state["main_agent_direct_response"] = "먼저 어떤 상품에 대해 상담하고 싶으신지 알려주시겠어요?"
        return "prepare_direct_response_node"
        
    return route_map.get(decision, "prepare_fallback_response_node")

def route_from_scenario_agent_call(state: AgentState) -> str:
    scenario_output = state.get("scenario_agent_output")
    if scenario_output and scenario_output.get("intent", "").startswith("error_"):
        state["error_message"] = f"답변 분석 중 오류: {scenario_output.get('intent')}"
        return "handle_error_node"
    return "main_agent_scenario_processing_node"

# --- 그래프 빌드 ---
workflow = StateGraph(AgentState)
workflow.add_node("entry_point_node", entry_point_node)
workflow.add_node("main_agent_router_node", main_agent_router_node)
workflow.add_node("set_product_type_node", set_product_type_node)
workflow.add_node("call_scenario_agent_node", call_scenario_agent_node)
workflow.add_node("factual_answer_node", factual_answer_node)
workflow.add_node("synthesize_answer_node", synthesize_answer_node)
workflow.add_node("main_agent_scenario_processing_node", main_agent_scenario_processing_node)
workflow.add_node("prepare_direct_response_node", prepare_direct_response_node)
workflow.add_node("prepare_fallback_response_node", prepare_fallback_response_node)
workflow.add_node("prepare_end_conversation_node", prepare_end_conversation_node)
workflow.add_node("handle_error_node", handle_error_node)

workflow.set_entry_point("entry_point_node")

workflow.add_conditional_edges("entry_point_node", route_from_entry)
workflow.add_conditional_edges("main_agent_router_node", route_from_main_agent_router)
workflow.add_conditional_edges("call_scenario_agent_node", route_from_scenario_agent_call)

workflow.add_edge("factual_answer_node", "synthesize_answer_node")
workflow.add_edge("synthesize_answer_node", END)
workflow.add_edge("set_product_type_node", END)
workflow.add_edge("main_agent_scenario_processing_node", END)
workflow.add_edge("prepare_direct_response_node", END)
workflow.add_edge("prepare_fallback_response_node", END)
workflow.add_edge("prepare_end_conversation_node", END)
workflow.add_edge("handle_error_node", END)

app_graph = workflow.compile()
print("--- LangGraph 컴파일 완료 (다중 업무 지원) ---")


async def run_agent_streaming(
    user_input_text: Optional[str] = None,
    user_input_audio_b64: Optional[str] = None,
    session_id: Optional[str] = "default_session",
    current_state_dict: Optional[Dict[str, Any]] = None
) -> AsyncGenerator[Union[Dict[str, Any], str], None]:
    
    if not OPENAI_API_KEY or not json_llm or not generative_llm: #
        error_msg = "LLM 서비스가 초기화되지 않았습니다. API 키 설정을 확인하세요." #
        yield {"type": "error", "session_id": session_id, "message": error_msg} #
        yield {"type": "final_state", "session_id": session_id, "data": {"error_message": error_msg, "is_final_turn_response": True, "messages": [AIMessage(content=error_msg)]}} #
        return

    if not ALL_SCENARIOS_DATA: #
        try: load_all_scenarios_sync() #
        except Exception as e: #
            yield {"type": "error", "session_id": session_id, "message": f"상담 서비스 초기화 실패 (시나리오 로드): {e}"} #
            return
    
    initial_messages: List[BaseMessage] = [] #
    current_product_type_from_session: Optional[Literal["didimdol", "jeonse"]] = None #
    current_stage_id_from_session: Optional[str] = None #
    collected_info_from_session: Dict[str, Any] = {} #

    if current_state_dict: #
        initial_messages = list(current_state_dict.get("messages", [])) #
        current_product_type_from_session = current_state_dict.get("current_product_type") #
        current_stage_id_from_session = current_state_dict.get("current_scenario_stage_id") #
        collected_info_from_session = current_state_dict.get("collected_product_info", {}) #

    initial_input_for_graph: AgentState = cast(AgentState, { #
        "session_id": session_id or "default_session", #
        "user_input_text": user_input_text, #
        "user_input_audio_b64": user_input_audio_b64, #
        "stt_result": user_input_text, #
        "messages": initial_messages, #
        
        "current_product_type": current_product_type_from_session, #
        "current_scenario_stage_id": current_stage_id_from_session, #
        "collected_product_info": collected_info_from_session, #
        "available_product_types": ["didimdol", "jeonse", "deposit_account"], # 


        "active_scenario_data": None, #
        "active_knowledge_base_content": None, #
        "active_scenario_name": None, #

        "main_agent_routing_decision": None, "main_agent_direct_response": None, #
        "scenario_agent_output": None,  #
        "final_response_text_for_tts": None, "is_final_turn_response": False, "error_message": None, #
    })
    
    print(f"\n--- [{session_id}] Agent Turn 시작 ---") #
    print(f"초기 입력 상태 (요약): product_type='{current_product_type_from_session}', stage='{current_stage_id_from_session}', text='{user_input_text}'") #

    final_graph_output_state: Optional[AgentState] = None #
    full_response_text_streamed = "" #

    try:
        final_graph_output_state = await app_graph.ainvoke(initial_input_for_graph)

        print(f"LangGraph 실행 완료. 라우팅: '{final_graph_output_state.get('main_agent_routing_decision')}', 다음 단계 ID: '{final_graph_output_state.get('current_scenario_stage_id')}'")
        
        # 그래프 실행 후, 생성된 최종 응답 텍스트를 스트리밍
        if final_graph_output_state.get("final_response_text_for_tts"):
            text_to_stream = final_graph_output_state["final_response_text_for_tts"]
            yield {"type": "stream_start", "stream_type": "general_response"}
            
            chunk_size = 20
            for i in range(0, len(text_to_stream), chunk_size):
                chunk = text_to_stream[i:i+chunk_size]
                yield chunk
                await asyncio.sleep(0.02)
                full_response_text_streamed += chunk
        else:
            # 최종 응답이 없는 경우 (오류 또는 예외 상황)
            error_message_fallback = final_graph_output_state.get("error_message", "응답을 생성하지 못했습니다.")
            yield {"type": "stream_start", "stream_type": "critical_error"}
            for char_chunk in error_message_fallback: yield char_chunk; await asyncio.sleep(0.01)
            full_response_text_streamed = error_message_fallback
            final_graph_output_state["final_response_text_for_tts"] = full_response_text_streamed
            final_graph_output_state["error_message"] = error_message_fallback
            final_graph_output_state["is_final_turn_response"] = True
        
        yield {"type": "stream_end", "full_text": full_response_text_streamed}

    except Exception as e:
        print(f"CRITICAL error in run_agent_streaming for session {session_id}: {e}") #
        import traceback; traceback.print_exc() #
        error_response = f"죄송합니다, 에이전트 처리 중 심각한 시스템 오류가 발생했습니다." #
        yield {"type": "stream_start", "stream_type": "critical_error"} #
        for char_chunk in error_response: yield char_chunk; await asyncio.sleep(0.01) #
        yield {"type": "stream_end", "full_text": error_response} #
        
        final_graph_output_state = cast(AgentState, initial_input_for_graph.copy()) #
        final_graph_output_state["error_message"] = error_response #
        final_graph_output_state["final_response_text_for_tts"] = error_response #
        final_graph_output_state["is_final_turn_response"] = True #
        current_messages_on_error = list(initial_input_for_graph.get("messages", [])) #
        if not current_messages_on_error or not (isinstance(current_messages_on_error[-1], AIMessage) and current_messages_on_error[-1].content == error_response): #
            current_messages_on_error.append(AIMessage(content=error_response)) #
        final_graph_output_state["messages"] = current_messages_on_error #

    finally:
        if final_graph_output_state: #
            yield {"type": "final_state", "session_id": session_id, "data": final_graph_output_state} #
        else: #
             yield {"type": "final_state", "session_id": session_id, "data": {"error_message": "Agent 실행 중 심각한 오류로 최종 상태 기록 불가", "is_final_turn_response": True}} #

        print(f"--- [{session_id}] Agent Turn 종료 (최종 AI 응답 텍스트 길이: {len(full_response_text_streamed)}) ---") #