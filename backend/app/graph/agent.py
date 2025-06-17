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
from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME
from .models import (
    next_stage_decision_parser,
    initial_task_decision_parser,
    main_router_decision_parser,
    ActionModel
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

# --- LangGraph Node Functions ---

async def entry_point_node(state: AgentState) -> AgentState:
    print("--- Node: Entry Point ---")
    if not ALL_SCENARIOS_DATA or not ALL_PROMPTS:
        error_msg = "Service initialization failed (Cannot load scenarios or prompts)."
        return {**state, "error_message": error_msg, "final_response_text_for_tts": error_msg, "is_final_turn_response": True}

    # Reset turn-specific state
    turn_defaults = {
        "stt_result": None, "main_agent_routing_decision": None, "main_agent_direct_response": None,
        "scenario_agent_output": None, "final_response_text_for_tts": None,
        "is_final_turn_response": False, "error_message": None,
        "active_scenario_data": None, "active_knowledge_base_content": None,
        "loan_selection_is_fresh": False, "factual_response": None, "action_plan": [],
    }
    
    current_product = state.get("current_product_type")
    updated_state = {**state, **turn_defaults, "current_product_type": current_product}
    
    # Load active scenario data if a product is selected
    active_scenario = get_active_scenario_data(updated_state)
    if active_scenario:
        updated_state["active_scenario_data"] = active_scenario
        updated_state["active_scenario_name"] = active_scenario.get("scenario_name", "Unknown Product")
        if not updated_state.get("current_scenario_stage_id"):
            updated_state["current_scenario_stage_id"] = active_scenario.get("initial_stage_id")
    else:
        updated_state["active_scenario_name"] = "Not Selected"

    # Add user input to message history
    user_text = updated_state.get("user_input_text")
    if user_text:
        messages = list(updated_state.get("messages", []))
        if not messages or not (isinstance(messages[-1], HumanMessage) and messages[-1].content == user_text):
            messages.append(HumanMessage(content=user_text))
        updated_state["messages"] = messages
        updated_state["stt_result"] = user_text
        
    return cast(AgentState, updated_state)

async def main_agent_router_node(state: AgentState) -> AgentState:
    print("--- Node: Main Agent Router (Orchestrator) ---")
    if not json_llm:
        return {**state, "error_message": "Router service unavailable (LLM not initialized).", "is_final_turn_response": True}

    user_input = state.get("stt_result", "")
    current_product_type = state.get("current_product_type")

    prompt_key = 'initial_task_selection_prompt' if not current_product_type else 'router_prompt'
    print(f"Main Agent using prompt: '{prompt_key}'")

    prompt_template = ALL_PROMPTS.get('main_agent', {}).get(prompt_key, '')
    if not prompt_template:
        return {**state, "error_message": "Router prompt not found.", "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True}

    parser = initial_task_decision_parser if not current_product_type else main_router_decision_parser
    format_instructions = parser.get_format_instructions()
    
    try:
        prompt_kwargs = {"user_input": user_input, "format_instructions": format_instructions}
        if current_product_type:
             active_scenario_data = get_active_scenario_data(state) or {}
             current_stage_id = state.get("current_scenario_stage_id", "N/A")
             current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
             valid_choices = current_stage_info.get("choices", []) 
             available_types = ", ".join([ALL_SCENARIOS_DATA[pt]["scenario_name"] for pt in state.get("available_product_types", []) if pt in ALL_SCENARIOS_DATA])
             prompt_kwargs.update({
                "active_scenario_name": state.get("active_scenario_name", "Not Selected"),
                "formatted_messages_history": format_messages_for_prompt(state.get("messages", [])[:-1]),
                "current_scenario_stage_id": current_stage_id,
                "current_stage_prompt": current_stage_info.get("prompt", "No prompt"),
                "collected_product_info": str(state.get("collected_product_info", {})),
                "expected_info_key": current_stage_info.get("expected_info_key", "Not specified"),
                "current_stage_valid_choices": str(valid_choices), 
                "available_product_types_display": available_types
             })
        
        prompt_filled = prompt_template.format(**prompt_kwargs)
        response = await json_llm.ainvoke([HumanMessage(content=prompt_filled)])
        raw_content = response.content.strip().replace("```json", "").replace("```", "").strip()
        decision = parser.parse(raw_content)

        # 새로운 ActionModel 구조를 사용하도록 상태 업데이트
        action_plan_models = decision.actions
        action_plan_tools = [action.tool for action in action_plan_models]

        new_state = {}
        if hasattr(decision, 'direct_response') and decision.direct_response:
            new_state["main_agent_direct_response"] = decision.direct_response

        system_log = f"Main Agent Plan: actions={[f'{a.tool}({a.tool_input})' for a in action_plan_models]}"
        updated_messages = list(state.get("messages", [])) + [SystemMessage(content=system_log)]
        new_state["messages"] = updated_messages

        # 초기 상태 분기 처리: action_plan_models 자체를 수정하여 일관성 유지
        if not current_product_type:
            first_action = action_plan_models[0] if action_plan_models else None
            if first_action:
                if first_action.tool == "set_product_type":
                    new_state["loan_selection_is_fresh"] = True
                elif first_action.tool == "invoke_qa_agent_general":
                    # action_plan_models의 tool 이름을 직접 변경
                    first_action.tool = "invoke_qa_agent"
                    new_state["active_scenario_name"] = "General Financial Advice"
                elif first_action.tool == "clarify_product_type":
                    # action_plan_models의 tool 이름을 직접 변경
                    first_action.tool = "select_product_type"

        # 최종적으로 결정된 모델에서 action_plan과 action_plan_struct를 생성
        new_state["action_plan"] = [model.tool for model in action_plan_models]
        new_state["action_plan_struct"] = [model.dict() for model in action_plan_models]

        print(f"Main Agent final plan: {new_state.get('action_plan')}")
        return new_state

    except Exception as e:
        print(f"Main Agent Router Error: {e}"); traceback.print_exc()
        err_msg = "Error processing request. Please try again."
        return {**state, "error_message": err_msg, "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True}

async def factual_answer_node(state: AgentState) -> dict:
    print("--- Node: Factual Answer (QA Tool) ---")
    user_question = state.get("stt_result", "")
    messages = state.get("messages", [])
    chat_history = format_messages_for_prompt(messages[:-1]) if len(messages) > 1 else "No previous conversation."

    product_type = state.get("current_product_type")
    scenario_name = state.get("active_scenario_name", "General Financial Advice")
    factual_response = "Could not find relevant information."

    if not generative_llm:
        return {"factual_response": "Answer generation service is unavailable."}

    try:
        kb_contents = []
        if product_type:
            kb_contents.append(await load_knowledge_base_content_async(product_type))
            if product_type == 'deposit_account':
                kb_contents.append(await load_knowledge_base_content_async('debit_card'))
                kb_contents.append(await load_knowledge_base_content_async('internet_banking'))
        
        context_for_llm = "\n\n---\n\n".join(filter(None, kb_contents))
        if not context_for_llm:
            context_for_llm = "No specific product document provided. Answer based on general financial knowledge."

        rag_prompt_template_str = ALL_PROMPTS.get('qa_agent', {}).get('rag_answer_generation')
        if not rag_prompt_template_str: raise ValueError("RAG prompt not found.")
        
        rag_prompt = ChatPromptTemplate.from_template(rag_prompt_template_str)
        response = await (rag_prompt | generative_llm).ainvoke({
            "scenario_name": scenario_name, 
            "context_for_llm": context_for_llm, 
            "user_question": user_question,
            "chat_history": chat_history
        })
        if response and response.content:
            factual_response = response.content.strip()
        print(f"QA Tool Response: {factual_response}")

    except Exception as e:
        print(f"Factual Answer Node Error: {e}")
        factual_response = "An error occurred while finding information."

    updated_plan = state.get("action_plan", []).copy()
    if updated_plan:
        updated_plan.pop(0)

    return {"factual_response": factual_response, "action_plan": updated_plan}

async def call_scenario_agent_node(state: AgentState) -> AgentState:
    print("--- Node: Call Scenario Agent (Scenario Tool) ---")
    user_input = state.get("stt_result", "")
    active_scenario_data = get_active_scenario_data(state)
    if not active_scenario_data or not user_input:
        return {**state, "scenario_agent_output": cast(ScenarioAgentOutput, {"intent": "error_missing_data", "is_scenario_related": False})}
    
    current_stage_id = state.get("current_scenario_stage_id", active_scenario_data.get("initial_stage_id"))
    current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})

    output = await invoke_scenario_agent_logic(
        user_input=user_input,
        current_stage_prompt=current_stage_info.get("prompt", ""),
        expected_info_key=current_stage_info.get("expected_info_key"),
        messages_history=state.get("messages", [])[:-1],
        scenario_name=active_scenario_data.get("scenario_name", "Consultation")
    )
    return {**state, "scenario_agent_output": output}

async def process_scenario_logic_node(state: AgentState) -> AgentState:
    print("--- Node: Process Scenario Logic ---")
    active_scenario_data = get_active_scenario_data(state)
    current_stage_id = state["current_scenario_stage_id"]
    current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
    collected_info = state.get("collected_product_info", {}).copy()
    scenario_output = state.get("scenario_agent_output")
    user_input = state.get("stt_result", "")

    if scenario_output and scenario_output.get("is_scenario_related"):
        entities = scenario_output.get("entities", {})
        intent = scenario_output.get("intent", "")
        
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
    
    return {
        **state, 
        "collected_product_info": collected_info, 
        "current_scenario_stage_id": determined_next_stage_id,
        "action_plan": updated_plan
    }

async def synthesize_response_node(state: AgentState) -> dict:
    print("--- Node: Synthesize Response ---")
    user_question = state["messages"][-1].content
    factual_answer = state.get("factual_response", "")
    
    contextual_response = ""
    active_scenario_data = get_active_scenario_data(state)
    if active_scenario_data:
        current_stage_id = state.get("current_scenario_stage_id")
        if current_stage_id and not str(current_stage_id).startswith("END_"):
             current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
             contextual_response = current_stage_info.get("prompt", "")
             if "%{" in contextual_response:
                import re
                if "end_scenario_message" in contextual_response:
                    contextual_response = re.sub(r'%\{end_scenario_message\}%', 
                        active_scenario_data.get("end_scenario_message", "상담이 완료되었습니다. 이용해주셔서 감사합니다."), 
                        contextual_response)
                else:
                    contextual_response = re.sub(r'%\{([^}]+)\}%', 
                        lambda m: str(state.get("collected_product_info", {}).get(m.group(1), f"")), 
                        contextual_response)
    
    if not factual_answer or "Could not find" in factual_answer:
        final_answer = contextual_response or state.get("main_agent_direct_response", "죄송합니다, 도움을 드리지 못했습니다.")
    elif not contextual_response:
        final_answer = factual_answer
    else:
        try:
            response = await synthesizer_chain.ainvoke({
                "chat_history": state['messages'][:-1],
                "user_question": user_question,
                "contextual_response": f"After answering, you need to continue the conversation with this prompt: '{contextual_response}'",
                "factual_response": factual_answer,
            })
            final_answer = response.content.strip()
        except Exception as e:
            print(f"Synthesizer Error: {e}")
            final_answer = f"{factual_answer}\n\n{contextual_response}"

    # final_answer가 None이 되지 않도록 보장
    if not final_answer:
        final_answer = "죄송합니다, 응답을 생성하는데 문제가 발생했습니다."

    print(f"Final Synthesized Answer: {final_answer}")
    updated_messages = list(state['messages']) + [AIMessage(content=final_answer)]
    
    return {"final_response_text_for_tts": final_answer, "messages": updated_messages, "is_final_turn_response": True}

async def end_conversation_node(state: AgentState) -> AgentState:
    print("--- Node: End Conversation ---")
    response_text = "상담을 종료합니다. 이용해주셔서 감사합니다."
    
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=response_text)]
    return {
        **state, 
        "final_response_text_for_tts": response_text, 
        "messages": updated_messages, 
        "is_final_turn_response": True
    }

async def set_product_type_node(state: AgentState) -> AgentState:
    print(f"--- Node: Set Product Type ---")
    
    action_plan_struct = state.get("action_plan_struct", [])
    if not action_plan_struct:
        err_msg = "Action plan is empty in set_product_type_node"
        print(f"ERROR: {err_msg}")
        return {**state, "error_message": err_msg, "is_final_turn_response": True}
    
    # 현재 액션에 맞는 구조 찾기
    current_action_model = ActionModel.parse_obj(action_plan_struct[0])
    
    new_product_type = current_action_model.tool_input.get("product_id")
    
    if not new_product_type:
        err_msg = f"product_id not found in action: {current_action_model.dict()}"
        print(f"ERROR: {err_msg}")
        return {**state, "error_message": err_msg, "is_final_turn_response": True}

    active_scenario = ALL_SCENARIOS_DATA.get(new_product_type)
    
    if not active_scenario:
        err_msg = f"Failed to load scenario for product type: {new_product_type}"
        print(f"ERROR: {err_msg}")
        return {**state, "error_message": err_msg, "is_final_turn_response": True}
        
    print(f"Successfully loaded scenario: {active_scenario.get('scenario_name')}")

    initial_stage_id = active_scenario.get("initial_stage_id")
    response_text = active_scenario.get("stages", {}).get(str(initial_stage_id), {}).get("prompt", "How can I help?")

    print(f"Generated response text: '{response_text[:70]}...'")

    updated_messages = list(state.get("messages", [])) + [AIMessage(content=response_text)]
    
    return {
        **state, "current_product_type": new_product_type, "active_scenario_data": active_scenario,
        "active_scenario_name": active_scenario.get("scenario_name"), "current_scenario_stage_id": initial_stage_id,
        "collected_product_info": {}, "final_response_text_for_tts": response_text,
        "messages": updated_messages, "is_final_turn_response": True
    }
    
async def prepare_direct_response_node(state: AgentState) -> AgentState:
    print("--- Node: Prepare Direct Response ---")
    response_text = state.get("main_agent_direct_response", "Sorry, I didn't understand. Could you rephrase?")
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=response_text)]
    return {**state, "final_response_text_for_tts": response_text, "messages": updated_messages, "is_final_turn_response": True}

# --- Conditional Edges ---
def route_from_main_agent_router(state: AgentState) -> str:
    decision = state.get("main_agent_routing_decision")
    print(f"Routing from Main Agent based on: '{decision}'")
    if state.get("is_final_turn_response"): return END
    
    route_map = {
        "set_product_type_didimdol": "set_product_type_node",
        "set_product_type_jeonse": "set_product_type_node",
        "set_product_type_deposit_account": "set_product_type_node",
        "select_product_type": "prepare_direct_response_node",
        "answer_directly_chit_chat": "prepare_direct_response_node",
        "invoke_scenario_agent": "call_scenario_agent_node",
        "invoke_qa_agent": "factual_answer_node",
        "end_conversation": END
    }
    return route_map.get(decision, "prepare_direct_response_node")

def route_after_scenario_logic(state: AgentState) -> str:
    return "synthesize_response_node"

def execute_plan_router(state: AgentState) -> str:
    plan = state.get("action_plan", [])
    if not plan:
        print("Routing: Plan complete -> Synthesize Response")
        return "synthesize_response_node"

    next_action = plan[0] 
    print(f"Routing: Inspecting next action '{next_action}' from plan.")
    
    action_to_node_map = {
        "invoke_scenario_agent": "call_scenario_agent_node",
        "invoke_qa_agent": "factual_answer_node",
        "clarify_and_requery": "prepare_direct_response_node",
        "answer_directly_chit_chat": "prepare_direct_response_node",
        "select_product_type": "prepare_direct_response_node", # clarify_product_type에서 변환됨
        "set_product_type": "set_product_type_node",
        "end_conversation": "end_conversation_node",
    }
    return action_to_node_map.get(next_action, "prepare_direct_response_node")

# --- Graph Build ---
workflow = StateGraph(AgentState)

workflow.add_node("entry_point_node", entry_point_node)
workflow.add_node("main_agent_router_node", main_agent_router_node)
workflow.add_node("call_scenario_agent_node", call_scenario_agent_node)
workflow.add_node("process_scenario_logic_node", process_scenario_logic_node)
workflow.add_node("factual_answer_node", factual_answer_node)
workflow.add_node("synthesize_response_node", synthesize_response_node)
workflow.add_node("set_product_type_node", set_product_type_node)
workflow.add_node("prepare_direct_response_node", prepare_direct_response_node)
workflow.add_node("end_conversation_node", end_conversation_node)

workflow.set_entry_point("entry_point_node")
workflow.add_edge("entry_point_node", "main_agent_router_node")

workflow.add_conditional_edges(
    "main_agent_router_node",
    execute_plan_router,
    {
        "call_scenario_agent_node": "call_scenario_agent_node",
        "factual_answer_node": "factual_answer_node",
        "synthesize_response_node": "synthesize_response_node",
        "prepare_direct_response_node": "prepare_direct_response_node",
        "set_product_type_node": "set_product_type_node",
        "end_conversation_node": "end_conversation_node",
    }
)

workflow.add_edge("call_scenario_agent_node", "process_scenario_logic_node")
workflow.add_conditional_edges("process_scenario_logic_node", execute_plan_router)
workflow.add_conditional_edges("factual_answer_node", execute_plan_router)

workflow.add_edge("synthesize_response_node", END)
workflow.add_edge("set_product_type_node", END)
workflow.add_edge("prepare_direct_response_node", END)
workflow.add_edge("end_conversation_node", END)

app_graph = workflow.compile()
print("--- LangGraph compiled successfully (Multi-Action Orchestrator model). ---")

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
    })

    print(f"\n--- [{session_id}] Agent Turn Start ---")
    print(f"Initial State Summary: product='{initial_state['current_product_type']}', stage='{initial_state['current_scenario_stage_id']}', text='{user_input_text}'")

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
        print(f"--- [{session_id}] Agent Turn End ---")