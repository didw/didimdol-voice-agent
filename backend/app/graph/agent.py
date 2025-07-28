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


from .chains import (
    json_llm,
    generative_llm
)

# --- Import logger ---
from .logger import log_node_execution

# --- Helper Functions for Information Collection ---

# 키워드 기반 추출 로직 제거 - Entity Agent 사용으로 대체

# --- Import Node Functions ---
from .nodes.orchestrator.entry_point import entry_point_node
from .nodes.orchestrator.main_router import main_agent_router_node
from .nodes.control.end_conversation import end_conversation_node
from .nodes.control.synthesize import synthesize_response_node
from .nodes.control.set_product import set_product_type_node
from .nodes.control.personal_info_correction import personal_info_correction_node
from .nodes.workers.rag_worker import factual_answer_node
from .nodes.workers.web_worker import web_search_node
from .nodes.workers.scenario_agent import call_scenario_agent_node
from .nodes.workers.scenario_logic import process_scenario_logic_node

# --- Import Router ---
from .router import execute_plan_router, route_after_scenario_logic


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
workflow.add_node("personal_info_correction_node", personal_info_correction_node)

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
        "personal_info_correction_node": "personal_info_correction_node",
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
workflow.add_conditional_edges("personal_info_correction_node", execute_plan_router)

app_graph = workflow.compile()

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
    current_state_dict: Optional[Dict[str, Any]] = None,
    input_mode: Optional[str] = "text"
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
        # 입력 모드 추가
        "input_mode": input_mode,
        # 라우터 및 루프 방지
        "router_call_count": current_state_dict.get("router_call_count", 0) if current_state_dict else 0,
        "correction_mode": current_state_dict.get("correction_mode", False) if current_state_dict else False,
        # 수정 관련 상태 복원
        "pending_modifications": current_state_dict.get("pending_modifications") if current_state_dict else None,
        "waiting_for_additional_modifications": current_state_dict.get("waiting_for_additional_modifications") if current_state_dict else None,
        "original_values_before_modification": current_state_dict.get("original_values_before_modification") if current_state_dict else None,
        # 시나리오 연속성 상태 복원
        "scenario_ready_for_continuation": current_state_dict.get("scenario_ready_for_continuation", False) if current_state_dict else False,
        "scenario_awaiting_user_response": current_state_dict.get("scenario_awaiting_user_response", False) if current_state_dict else False,
    })
    

    log_node_execution("Session", f"product={initial_state['current_product_type']}, stage={initial_state.get('current_scenario_stage_id', 'N/A')}")

    final_state: Optional[AgentState] = None
    streamed_text = ""

    try:
        final_state = await app_graph.ainvoke(initial_state)
        
        # Check for stage_response_data and send it first
        if final_state and final_state.get("stage_response_data"):
            yield {"type": "stage_response", "data": final_state["stage_response_data"]}
        
        # Only stream text if there's no stage_response_data
        elif final_state and final_state.get("final_response_text_for_tts"):
            text_to_stream = final_state["final_response_text_for_tts"]
            yield {"type": "stream_start"}
            try:
                for char in text_to_stream:
                    yield char
                    streamed_text += char
                    await asyncio.sleep(0.01)
                yield {"type": "stream_end", "full_text": streamed_text}
            except GeneratorExit:
                # Handle generator cleanup properly
                print(f"Generator exit requested for session {session_id}")
                raise
        else:
            error_msg = final_state.get("error_message", "Failed to generate a response.")
            yield {"type": "error", "message": error_msg}
            if final_state: final_state["final_response_text_for_tts"] = error_msg

    except GeneratorExit:
        # Re-raise GeneratorExit to allow proper cleanup
        print(f"Generator exit for session {session_id}")
        raise
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
            # AgentState를 dict로 변환하여 반환
            if hasattr(final_state, 'to_dict'):
                yield {"type": "final_state", "data": final_state.to_dict()}
            else:
                yield {"type": "final_state", "data": dict(final_state)}
        else:
            final_state = initial_state
            final_state["error_message"] = "Agent execution failed critically, no final state produced."
            final_state["is_final_turn_response"] = True
            if hasattr(final_state, 'to_dict'):
                yield {"type": "final_state", "data": final_state.to_dict()}
            else:
                yield {"type": "final_state", "data": dict(final_state)}
