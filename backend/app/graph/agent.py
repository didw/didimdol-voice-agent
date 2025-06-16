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
    main_router_decision_parser
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
        "loan_selection_is_fresh": False, "factual_response": None,
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
    # This function's logic remains largely the same, but its output will now route to different nodes.
    # The prompt change in main_agent_prompts.yaml is what makes it smarter.
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
        # Simplified prompt filling logic for clarity
        prompt_kwargs = {"user_input": user_input, "format_instructions": format_instructions}
        if current_product_type:
             active_scenario_data = get_active_scenario_data(state) or {}
             current_stage_id = state.get("current_scenario_stage_id", "N/A")
             current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
             available_types = ", ".join([ALL_SCENARIOS_DATA[pt]["scenario_name"] for pt in state.get("available_product_types", []) if pt in ALL_SCENARIOS_DATA])
             prompt_kwargs.update({
                "active_scenario_name": state.get("active_scenario_name", "Not Selected"),
                "formatted_messages_history": format_messages_for_prompt(state.get("messages", [])[:-1]),
                "current_scenario_stage_id": current_stage_id,
                "current_stage_prompt": current_stage_info.get("prompt", "No prompt"),
                "collected_product_info": str(state.get("collected_product_info", {})),
                "expected_info_key": current_stage_info.get("expected_info_key", "Not specified"),
                "available_product_types_display": available_types
             })
        
        prompt_filled = prompt_template.format(**prompt_kwargs)
        response = await json_llm.ainvoke([HumanMessage(content=prompt_filled)])
        raw_content = response.content.strip().replace("```json", "").replace("```", "").strip()
        decision = parser.parse(raw_content)

        # ✨ 여기가 핵심 수정 부분입니다. ✨
        new_state = {"action_plan": decision.actions}
        if hasattr(decision, 'direct_response') and decision.direct_response:
            new_state["main_agent_direct_response"] = decision.direct_response

        system_log = f"Main Agent Plan: actions={decision.actions}"
        updated_messages = list(state.get("messages", [])) + [SystemMessage(content=system_log)]
        new_state["messages"] = updated_messages

        # 첫 턴에 대한 처리 로직 수정
        if not current_product_type:
            action_map = {
                "proceed_with_product_type_didimdol": "didimdol",
                "proceed_with_product_type_jeonse": "jeonse",
                "proceed_with_product_type_deposit_account": "deposit_account",
            }
            # decision.actions는 리스트이므로 첫 번째 요소를 확인합니다.
            first_action = decision.actions[0] if decision.actions else None
            
            if first_action in action_map:
                # 'set_product_type_...' 액션으로 변경하여 라우팅합니다.
                new_state["action_plan"] = [f"set_product_type_{action_map[first_action]}"]
                new_state["loan_selection_is_fresh"] = True
            elif first_action == "invoke_qa_agent_general":
                new_state["action_plan"] = ["invoke_qa_agent"]
                new_state["active_scenario_name"] = "General Financial Advice"
            elif first_action == "clarify_product_type":
                 new_state["action_plan"] = ["select_product_type"]

        print(f"Main Agent final plan: {new_state.get('action_plan')}")
        return {**state, **new_state}

    except Exception as e:
        print(f"Main Agent Router Error: {e}"); traceback.print_exc()
        err_msg = "Error processing request. Please try again."
        return {**state, "error_message": err_msg, "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True}

# This is our QA Tool node
async def factual_answer_node(state: AgentState) -> dict:
    """Invokes the QA Agent (RAG) to generate a fact-based answer."""
    print("--- Node: Factual Answer (QA Tool) ---")
    user_question = state.get("stt_result", "")
    product_type = state.get("current_product_type")
    scenario_name = state.get("active_scenario_name", "General Financial Advice")
    factual_response = "Could not find relevant information."

    if not generative_llm:
        return {"factual_response": "Answer generation service is unavailable."}

    try:
        # Load all relevant KBs. A more advanced version might select specific KBs.
        kb_contents = []
        if product_type:
            # Load primary product KB
            kb_contents.append(await load_knowledge_base_content_async(product_type))
            # If it's a deposit account, also load related KBs
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
            "scenario_name": scenario_name, "context_for_llm": context_for_llm, "user_question": user_question
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


# This is our Scenario Tool node
async def call_scenario_agent_node(state: AgentState) -> AgentState:
    print("--- Node: Call Scenario Agent (Scenario Tool) ---")
    user_input = state.get("stt_result", "")
    active_scenario_data = get_active_scenario_data(state)
    if not active_scenario_data or not user_input:
        return {**state, "scenario_agent_output": cast(ScenarioAgentOutput, {"intent": "error_missing_data", "is_scenario_related": False})}
    
    current_stage_id = state.get("current_scenario_stage_id", active_scenario_data.get("initial_stage_id"))
    current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})

    # Use the encapsulated logic from chains.py
    output = await invoke_scenario_agent_logic(
        user_input=user_input,
        current_stage_prompt=current_stage_info.get("prompt", ""),
        expected_info_key=current_stage_info.get("expected_info_key"),
        messages_history=state.get("messages", [])[:-1],
        scenario_name=active_scenario_data.get("scenario_name", "Consultation")
    )
    return {**state, "scenario_agent_output": output}

# This node now only determines the NEXT stage, it doesn't generate the response itself.
async def process_scenario_logic_node(state: AgentState) -> AgentState:
    print("--- Node: Process Scenario Logic ---")
    # This node is responsible for updating the state after the scenario tool runs.
    # It updates collected_info and determines the next stage ID.
    active_scenario_data = get_active_scenario_data(state)
    current_stage_id = state["current_scenario_stage_id"]
    current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
    collected_info = state.get("collected_product_info", {}).copy()
    
    scenario_output = state.get("scenario_agent_output")
    if scenario_output and scenario_output.get("is_scenario_related"):
        entities = scenario_output.get("entities", {})
        collected_info.update({k: v for k, v in entities.items() if v is not None})
        print(f"Updated Info from Scenario Tool: {collected_info}")
    
    # Use LLM to determine the next stage ID
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
    determined_next_stage_id = decision_data.chosen_next_stage_id

    updated_plan = state.get("action_plan", []).copy()
    if updated_plan:
        updated_plan.pop(0)
    
    return {
        **state, 
        "collected_product_info": collected_info, 
        "current_scenario_stage_id": determined_next_stage_id,
        "action_plan": updated_plan
    }


# --- NEW: Synthesis Node ---
async def synthesize_response_node(state: AgentState) -> dict:
    """Combines contextual and factual answers into a final response."""
    print("--- Node: Synthesize Response ---")
    user_question = state["messages"][-1].content
    factual_answer = state.get("factual_response", "")
    
    # Determine the contextual part of the response
    contextual_response = ""
    active_scenario_data = get_active_scenario_data(state)
    if active_scenario_data:
        current_stage_id = state.get("current_scenario_stage_id")
        # Check if the QA was asked in the middle of a scenario
        if current_stage_id and not str(current_stage_id).startswith("END_"):
             current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
             contextual_response = current_stage_info.get("prompt", "")
             # Format the prompt with any collected data
             if "%{" in contextual_response:
                import re
                contextual_response = re.sub(r'%\{([^}]+)\}%', lambda m: str(state.get("collected_product_info", {}).get(m.group(1), f"")), contextual_response)
    
    # If there's no factual answer, the contextual one is the final one.
    if not factual_answer or "Could not find" in factual_answer:
        final_answer = contextual_response or state.get("main_agent_direct_response", "Sorry, I am not sure how to help with that.")
    # If there is no contextual answer (e.g. general QA), the factual one is final.
    elif not contextual_response:
        final_answer = factual_answer
    # If we have both, we synthesize them.
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
            final_answer = f"{factual_answer}\n\n{contextual_response}" # Fallback concatenation

    print(f"Final Synthesized Answer: {final_answer}")
    updated_messages = list(state['messages']) + [AIMessage(content=final_answer)]
    
    return {"final_response_text_for_tts": final_answer, "messages": updated_messages, "is_final_turn_response": True}
    


async def end_conversation_node(state: AgentState) -> AgentState:
    """Prepares a final goodbye message and ends the conversation."""
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
    
    action_plan = state.get("action_plan", [])
    if not action_plan:
        err_msg = "Action plan is empty in set_product_type_node"
        print(f"ERROR: {err_msg}")
        return {**state, "error_message": err_msg, "is_final_turn_response": True}
    
    current_action = action_plan[0]
    
    type_map = {
        "set_product_type_didimdol": "didimdol", 
        "set_product_type_jeonse": "jeonse", 
        "set_product_type_deposit_account": "deposit_account"
    }
    new_product_type = type_map.get(current_action)
    
    active_scenario = ALL_SCENARIOS_DATA.get(new_product_type)
    
    if not active_scenario:
        err_msg = f"Failed to load scenario for product type: {new_product_type}"
        print(f"ERROR: {err_msg}")
        return {**state, "error_message": err_msg, "is_final_turn_response": True}
        
    # --- 💡 디버깅 로그 추가 시작 💡 ---
    print(f"Successfully loaded scenario: {active_scenario.get('scenario_name')}")

    initial_stage_id = active_scenario.get("initial_stage_id")
    response_text = active_scenario.get("stages", {}).get(str(initial_stage_id), {}).get("prompt", "How can I help?")

    print(f"Generated response text: '{response_text[:70]}...'")
    # --- 💡 디버깅 로그 추가 종료 💡 ---

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
        "end_conversation": END # Can end directly
    }
    return route_map.get(decision, "prepare_direct_response_node")

def route_after_scenario_logic(state: AgentState) -> str:
    # After processing scenario logic, we always synthesize the response
    return "synthesize_response_node"



def execute_plan_router(state: AgentState) -> str:
    """
    Action Plan을 보고 다음에 실행할 노드를 결정합니다.
    Plan이 비어있으면, 종합 노드로 이동합니다.
    """
    plan = state.get("action_plan", [])
    if not plan:
        print("Routing: Plan complete -> Synthesize Response")
        return "synthesize_response_node"

    # --- 💡 수정: .pop(0) 대신 [0]을 사용하여 계획을 수정하지 않고 확인만 합니다. ---
    next_action = plan[0] 
    print(f"Routing: Inspecting next action '{next_action}' from plan.")
    
    action_to_node_map = {
        "invoke_scenario_agent": "call_scenario_agent_node",
        "invoke_qa_agent": "factual_answer_node",
        "answer_directly_chit_chat": "prepare_direct_response_node",
        "select_product_type": "prepare_direct_response_node",
        "set_product_type_didimdol": "set_product_type_node",
        "set_product_type_jeonse": "set_product_type_node",
        "set_product_type_deposit_account": "set_product_type_node",
        "end_conversation": "end_conversation_node",
    }
    return action_to_node_map.get(next_action, "prepare_direct_response_node")


# --- Graph Build (재구성) ---
workflow = StateGraph(AgentState)

# 1. 노드 추가 (이전과 동일)
workflow.add_node("entry_point_node", entry_point_node)
workflow.add_node("main_agent_router_node", main_agent_router_node)
workflow.add_node("call_scenario_agent_node", call_scenario_agent_node)
workflow.add_node("process_scenario_logic_node", process_scenario_logic_node)
workflow.add_node("factual_answer_node", factual_answer_node)
workflow.add_node("synthesize_response_node", synthesize_response_node)
workflow.add_node("set_product_type_node", set_product_type_node)
workflow.add_node("prepare_direct_response_node", prepare_direct_response_node)
workflow.add_node("end_conversation_node", end_conversation_node)

# 2. 엣지 연결
workflow.set_entry_point("entry_point_node")
workflow.add_edge("entry_point_node", "main_agent_router_node")

# 3. 메인 라우터는 항상 새로운 Plan 실행 라우터로 연결
workflow.add_conditional_edges(
    "main_agent_router_node",
    execute_plan_router, # Plan 실행 라우터를 첫 번째 엣지로 사용
    {
        "call_scenario_agent_node": "call_scenario_agent_node",
        "factual_answer_node": "factual_answer_node",
        "synthesize_response_node": "synthesize_response_node", # Plan이 처음부터 비어있을 경우
        "prepare_direct_response_node": "prepare_direct_response_node",
        "set_product_type_node": "set_product_type_node",
        "end_conversation_node": "end_conversation_node",
    }
)

# 4. 각 Tool 노드는 실행 후 다시 Plan 실행 라우터로 돌아와서 다음 작업을 확인
workflow.add_edge("call_scenario_agent_node", "process_scenario_logic_node")
workflow.add_conditional_edges("process_scenario_logic_node", execute_plan_router) # 시나리오 처리 후 다시 Plan 라우터로
workflow.add_conditional_edges("factual_answer_node", execute_plan_router)     # QA 처리 후 다시 Plan 라우터로

# 5. 최종 노드들
workflow.add_edge("synthesize_response_node", END)
workflow.add_edge("set_product_type_node", END) # 상품 설정은 그 자체로 한 턴의 응답이 됨
workflow.add_edge("prepare_direct_response_node", END) # 직접 응답도 한 턴의 응답이 됨
workflow.add_edge("end_conversation_node", END)

app_graph = workflow.compile()
print("--- LangGraph compiled successfully (Multi-Action Orchestrator model). ---")


# --- Main Execution Function (run_agent_streaming) ---
# The existing run_agent_streaming function can be used with minimal changes,
# as it's designed to stream the final state's `final_response_text_for_tts`.
# The main change is how that text is generated by the new graph.
# The existing function is already well-structured for this.
async def run_agent_streaming(
    user_input_text: Optional[str] = None,
    user_input_audio_b64: Optional[str] = None,
    session_id: Optional[str] = "default_session",
    current_state_dict: Optional[Dict[str, Any]] = None
) -> AsyncGenerator[Union[Dict[str, Any], str], None]:
    
    # ... The implementation of this function from the original file is fine ...
    # It will now execute the new, more powerful graph.
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
    })

    print(f"\n--- [{session_id}] Agent Turn Start ---")
    print(f"Initial State Summary: product='{initial_state['current_product_type']}', stage='{initial_state['current_scenario_stage_id']}', text='{user_input_text}'")

    final_state: Optional[AgentState] = None
    streamed_text = ""

    try:
        # Invoke the new graph
        final_state = await app_graph.ainvoke(initial_state)
        
        if final_state and final_state.get("final_response_text_for_tts"):
            text_to_stream = final_state["final_response_text_for_tts"]
            yield {"type": "stream_start"}
            # Simulate streaming character by character for UI responsiveness
            for char in text_to_stream:
                yield char
                streamed_text += char
                await asyncio.sleep(0.01) # Adjust delay for desired speed
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
            # Create a fallback final state if everything failed
            final_state = initial_state
            final_state["error_message"] = "Agent execution failed critically, no final state produced."
            final_state["is_final_turn_response"] = True
            yield {"type": "final_state", "data": final_state}
        print(f"--- [{session_id}] Agent Turn End ---")