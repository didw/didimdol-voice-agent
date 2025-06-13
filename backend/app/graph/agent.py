import json
import yaml
import asyncio
from pathlib import Path
from typing import Dict, Optional, Sequence, Literal, Any, List, Union, cast, AsyncGenerator
import traceback

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, AIMessageChunk
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field as PydanticField

from .state import AgentState, ScenarioAgentOutput, PRODUCT_TYPES
from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME
from ..services.google_services import GOOGLE_SERVICES_AVAILABLE


from .models import (
    next_stage_decision_parser,
    initial_task_decision_parser,
    main_router_decision_parser
)
from .utils import (
    ALL_PROMPTS,
    ALL_SCENARIOS_DATA,
    KNOWLEDGE_BASE_FILES,
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

    turn_defaults = {
        "stt_result": None, "main_agent_routing_decision": None, "main_agent_direct_response": None,
        "scenario_agent_output": None, "final_response_text_for_tts": None,
        "is_final_turn_response": False, "error_message": None,
        "active_scenario_data": None, "active_knowledge_base_content": None,
        "loan_selection_is_fresh": False, "factual_response": None,
    }
    
    current_product = state.get("current_product_type")
    updated_state = {**state, **turn_defaults, "current_product_type": current_product}
    
    active_scenario = get_active_scenario_data(updated_state)
    if active_scenario:
        updated_state["active_scenario_data"] = active_scenario
        updated_state["active_scenario_name"] = active_scenario.get("scenario_name", "Unknown Product")
        if not updated_state.get("current_scenario_stage_id"):
            updated_state["current_scenario_stage_id"] = active_scenario.get("initial_stage_id")
    else:
        updated_state["active_scenario_name"] = "Not Selected"

    user_text = updated_state.get("user_input_text")
    if user_text:
        messages = list(updated_state.get("messages", []))
        if not messages or not (isinstance(messages[-1], HumanMessage) and messages[-1].content == user_text):
            messages.append(HumanMessage(content=user_text))
        updated_state["messages"] = messages
        updated_state["stt_result"] = user_text
        
    return cast(AgentState, updated_state)


async def main_agent_router_node(state: AgentState) -> AgentState:
    print("--- Node: Main Agent Router ---")
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
        if not current_product_type:
            prompt_filled = prompt_template.format(user_input=user_input, format_instructions=format_instructions)
        else:
            active_scenario_data = get_active_scenario_data(state) or {}
            current_stage_id = state.get("current_scenario_stage_id", "N/A")
            current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
            available_types = ", ".join([ALL_SCENARIOS_DATA[pt]["scenario_name"] for pt in state.get("available_product_types", []) if pt in ALL_SCENARIOS_DATA])

            prompt_filled = prompt_template.format(
                user_input=user_input,
                active_scenario_name=state.get("active_scenario_name", "Not Selected"),
                formatted_messages_history=format_messages_for_prompt(state.get("messages", [])[:-1]),
                current_scenario_stage_id=current_stage_id,
                current_stage_prompt=current_stage_info.get("prompt", "No prompt"),
                collected_product_info=str(state.get("collected_product_info", {})),
                expected_info_key=current_stage_info.get("expected_info_key", "Not specified"),
                available_product_types_display=available_types,
                format_instructions=format_instructions
            )

        response = await json_llm.ainvoke([HumanMessage(content=prompt_filled)])
        raw_content = response.content.strip().replace("```json", "").replace("```", "").strip()
        decision = parser.parse(raw_content)

        new_state = {"main_agent_routing_decision": decision.action}
        if hasattr(decision, 'direct_response') and decision.direct_response:
            new_state["main_agent_direct_response"] = decision.direct_response
        
        system_log = f"Main Agent Decision: action='{decision.action}'"
        updated_messages = list(state.get("messages", [])) + [SystemMessage(content=system_log)]
        new_state["messages"] = updated_messages

        if not current_product_type:
            action_map = {
                "proceed_with_product_type_didimdol": ("set_product_type_didimdol", "didimdol"),
                "proceed_with_product_type_jeonse": ("set_product_type_jeonse", "jeonse"),
                "proceed_with_product_type_deposit_account": ("set_product_type_deposit_account", "deposit_account"),
            }
            if decision.action in action_map:
                new_state["main_agent_routing_decision"], new_state["current_product_type"] = action_map[decision.action]
                new_state["loan_selection_is_fresh"] = True
            elif decision.action == "invoke_qa_agent_general":
                new_state["main_agent_routing_decision"] = "invoke_qa_agent"
                new_state["active_scenario_name"] = "General Financial Advice"
            else: # clarify_product_type or answer_directly_chit_chat
                new_state["main_agent_routing_decision"] = "select_product_type" if decision.action == "clarify_product_type" else "answer_directly_chit_chat"

        print(f"Main Agent final decision: {new_state.get('main_agent_routing_decision')}")
        return {**state, **new_state}

    except Exception as e:
        print(f"Main Agent Router Error: {e}"); traceback.print_exc()
        err_msg = "Error processing request. Please try again."
        return {**state, "error_message": err_msg, "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True}


async def call_scenario_agent_node(state: AgentState) -> AgentState:
    print("--- Node: Call Scenario Agent ---")
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


async def factual_answer_node(state: AgentState) -> dict:
    """Invokes the QA Agent (RAG) to generate a fact-based answer."""
    print("--- Node: Factual Answer (QA Agent) ---")
    user_question = state.get("stt_result", "")
    product_type = state.get("current_product_type")
    scenario_name = state.get("active_scenario_name", "General Financial Advice")
    factual_response = "Could not find relevant information."

    if not generative_llm:
        return {"factual_response": "Answer generation service is unavailable."}

    try:
        kb_content = await load_knowledge_base_content_async(product_type) if product_type else None
        context_for_llm = kb_content or "No specific product document provided. Answer based on general knowledge."

        rag_prompt_template_str = ALL_PROMPTS.get('qa_agent', {}).get('rag_answer_generation')
        if not rag_prompt_template_str: raise ValueError("RAG prompt not found.")
        
        rag_prompt = ChatPromptTemplate.from_template(rag_prompt_template_str)
        formatted_prompt = rag_prompt.format(
            scenario_name=scenario_name, context_for_llm=context_for_llm, user_question=user_question
        )
        response = await generative_llm.ainvoke([HumanMessage(content=formatted_prompt)])
        if response and response.content:
            factual_response = response.content.strip()
        print(f"QA Agent Response: {factual_response}")

    except Exception as e:
        print(f"Factual Answer Node Error: {e}")
        factual_response = "An error occurred while finding information."

    return {"factual_response": factual_response}


async def synthesize_answer_node(state: AgentState) -> dict:
    """Combines contextual and factual answers into a final response."""
    print("--- Node: Synthesize Answer ---")
    if not synthesizer_chain:
        return {"final_response_text_for_tts": state.get("main_agent_direct_response", "Error generating response."), "is_final_turn_response": True}
        
    user_question = state["messages"][-1].content
    final_answer = "I'm sorry, I can't seem to find the right information for that. Could you ask again in a different way?"
    
    try:
        response = await synthesizer_chain.ainvoke({
            "chat_history": state['messages'][:-1],
            "user_question": user_question,
            "contextual_response": state.get("main_agent_direct_response", "No contextual response."),
            "factual_response": state.get("factual_response", "No factual response."),
        })
        final_answer = response.content.strip()
    except Exception as e:
        print(f"Synthesizer Error: {e}")

    print(f"Final Synthesized Answer: {final_answer}")
    updated_messages = list(state['messages']) + [AIMessage(content=final_answer)]
    
    return {"final_response_text_for_tts": final_answer, "messages": updated_messages, "is_final_turn_response": True}


async def main_agent_scenario_processing_node(state: AgentState) -> AgentState:
    print("--- Node: Main Agent Scenario Processing ---")
    if not json_llm:
        return {**state, "error_message": "Scenario processing service unavailable.", "is_final_turn_response": True}

    active_scenario_data = get_active_scenario_data(state)
    if not active_scenario_data:
        return {**state, "error_message": "Scenario data is missing for processing.", "is_final_turn_response": True}

    current_stage_id = state.get("current_scenario_stage_id", active_scenario_data.get("initial_stage_id"))
    current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
    collected_info = state.get("collected_product_info", {}).copy()
    
    scenario_output = state.get("scenario_agent_output")
    if scenario_output and scenario_output.get("is_scenario_related"):
        entities = scenario_output.get("entities", {})
        collected_info.update({k: v for k, v in entities.items() if v is not None})
        print(f"Updated Info: {collected_info}")

    prompt_template = ALL_PROMPTS.get('main_agent', {}).get('determine_next_scenario_stage', '')
    if not prompt_template:
        determined_next_stage_id = current_stage_info.get("default_next_stage_id", str(current_stage_id))
    else:
        llm_prompt = prompt_template.format(
            active_scenario_name=active_scenario_data.get("scenario_name", "Consultation"),
            current_stage_id=str(current_stage_id),
            current_stage_prompt=current_stage_info.get("prompt", "No prompt"),
            user_input=state.get("stt_result", ""),
            scenario_agent_intent=scenario_output.get("intent", "N/A") if scenario_output else "N/A",
            scenario_agent_entities=str(scenario_output.get("entities", {})) if scenario_output else "{}",
            collected_product_info=str(collected_info),
            formatted_transitions=format_transitions_for_prompt(current_stage_info.get("transitions", []), current_stage_info.get("prompt", "")),
            default_next_stage_id=current_stage_info.get("default_next_stage_id", "None")
        )
        try:
            response = await json_llm.ainvoke([HumanMessage(content=llm_prompt)])
            raw_content = response.content.strip().replace("```json", "").replace("```", "").strip()
            decision_data = next_stage_decision_parser.parse(raw_content)
            determined_next_stage_id = decision_data.chosen_next_stage_id
            print(f"LLM decided next stage: '{determined_next_stage_id}'")
            if determined_next_stage_id not in active_scenario_data.get("stages", {}) and not determined_next_stage_id.startswith("END_"):
                determined_next_stage_id = current_stage_info.get("default_next_stage_id", str(current_stage_id))
        except Exception as e:
            print(f"Next stage decision LLM error: {e}. Using default.")
            determined_next_stage_id = current_stage_info.get("default_next_stage_id", str(current_stage_id))

    next_stage_info = active_scenario_data.get("stages", {}).get(determined_next_stage_id, {})
    final_response_text = next_stage_info.get("prompt", active_scenario_data.get("fallback_message"))
    
    if determined_next_stage_id.startswith("END_"):
        final_response_text = active_scenario_data.get("end_scenario_message", "Consultation complete.")
    elif "%{" in final_response_text:
        import re
        final_response_text = re.sub(r'%\{([^}]+)\}%', lambda m: str(collected_info.get(m.group(1), f"%{{{m.group(1)}}}%")), final_response_text)
    
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=final_response_text)]
    return {
        **state, "collected_product_info": collected_info, "current_scenario_stage_id": determined_next_stage_id,
        "final_response_text_for_tts": final_response_text, "messages": updated_messages, "is_final_turn_response": True
    }

async def set_product_type_node(state: AgentState) -> AgentState:
    print(f"--- Node: Set Product Type ---")
    routing_decision = state.get("main_agent_routing_decision")
    type_map = {
        "set_product_type_didimdol": "didimdol",
        "set_product_type_jeonse": "jeonse",
        "set_product_type_deposit_account": "deposit_account"
    }
    new_product_type = type_map.get(routing_decision)

    if new_product_type and new_product_type in ALL_SCENARIOS_DATA:
        active_scenario = ALL_SCENARIOS_DATA[new_product_type]
        initial_stage_id = active_scenario.get("initial_stage_id")
        initial_prompt = active_scenario.get("stages", {}).get(str(initial_stage_id), {}).get("prompt", "How can I help?")

        response_text = initial_prompt if state.get("loan_selection_is_fresh") else initial_prompt

        updated_messages = list(state.get("messages", [])) + [AIMessage(content=response_text)]
        return {
            **state, "current_product_type": new_product_type, "active_scenario_data": active_scenario,
            "active_scenario_name": active_scenario.get("scenario_name"), "current_scenario_stage_id": initial_stage_id,
            "collected_product_info": {}, "final_response_text_for_tts": response_text,
            "messages": updated_messages, "is_final_turn_response": True
        }
    else:
        error_msg = f"Cannot handle the requested product type: '{new_product_type}'."
        updated_messages = list(state.get("messages", [])) + [AIMessage(content=error_msg)]
        return {**state, "error_message": error_msg, "final_response_text_for_tts": error_msg, "messages": updated_messages, "is_final_turn_response": True}

async def prepare_direct_response_node(state: AgentState) -> AgentState:
    print("--- Node: Prepare Direct Response ---")
    response_text = state.get("main_agent_direct_response", "Sorry, I didn't understand. Could you rephrase?")
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=response_text)]
    return {**state, "final_response_text_for_tts": response_text, "messages": updated_messages, "is_final_turn_response": True}

async def prepare_end_conversation_node(state: AgentState) -> AgentState:
    print("--- Node: Prepare End Conversation ---")
    response_text = "Thank you for using our service. Goodbye!"
    active_scenario = get_active_scenario_data(state)
    if active_scenario:
        response_text = active_scenario.get("end_conversation_message", response_text)
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=response_text)]
    return {**state, "final_response_text_for_tts": response_text, "messages": updated_messages, "is_final_turn_response": True}


# --- Conditional Edges ---
def route_from_main_agent_router(state: AgentState) -> str:
    decision = state.get("main_agent_routing_decision")
    print(f"Routing from Main Agent based on: {decision}")
    if state.get("is_final_turn_response"): return END
    
    route_map = {
        "set_product_type_didimdol": "set_product_type_node",
        "set_product_type_jeonse": "set_product_type_node",
        "set_product_type_deposit_account": "set_product_type_node",
        "select_product_type": "prepare_direct_response_node",
        "answer_directly_chit_chat": "prepare_direct_response_node",
        "invoke_scenario_agent": "call_scenario_agent_node",
        "invoke_qa_agent": "factual_answer_node",
        "end_conversation": "prepare_end_conversation_node"
    }
    return route_map.get(decision, "prepare_direct_response_node")


# --- Graph Build ---
workflow = StateGraph(AgentState)
workflow.add_node("entry_point_node", entry_point_node)
workflow.add_node("main_agent_router_node", main_agent_router_node)
workflow.add_node("call_scenario_agent_node", call_scenario_agent_node)
workflow.add_node("main_agent_scenario_processing_node", main_agent_scenario_processing_node)
workflow.add_node("set_product_type_node", set_product_type_node)
workflow.add_node("factual_answer_node", factual_answer_node)
workflow.add_node("synthesize_answer_node", synthesize_answer_node)
workflow.add_node("prepare_direct_response_node", prepare_direct_response_node)
workflow.add_node("prepare_end_conversation_node", prepare_end_conversation_node)

workflow.set_entry_point("entry_point_node")
workflow.add_edge("entry_point_node", "main_agent_router_node")
workflow.add_conditional_edges("main_agent_router_node", route_from_main_agent_router)
workflow.add_edge("call_scenario_agent_node", "main_agent_scenario_processing_node")
workflow.add_edge("factual_answer_node", "synthesize_answer_node")

# Terminal nodes
workflow.add_edge("main_agent_scenario_processing_node", END)
workflow.add_edge("set_product_type_node", END)
workflow.add_edge("synthesize_answer_node", END)
workflow.add_edge("prepare_direct_response_node", END)
workflow.add_edge("prepare_end_conversation_node", END)

app_graph = workflow.compile()
print("--- LangGraph compiled successfully (modular structure). ---")


# --- Main Execution Function ---
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
            # Simulate streaming character by character for responsiveness
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
            yield {"type": "final_state", "data": {"error_message": "Agent execution failed critically.", "is_final_turn_response": True}}
        print(f"--- [{session_id}] Agent Turn End ---")