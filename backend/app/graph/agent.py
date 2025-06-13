# backend/app/graph/agent.py

import asyncio
import traceback
from typing import Dict, Any, Union, AsyncGenerator, cast

from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph, END

from .state import AgentState
from .nodes import (
    entry_point_node,
    main_agent_router_node,
    set_product_type_node,
    call_scenario_agent_node,
    factual_answer_node,
    synthesize_answer_node,
    main_agent_scenario_processing_node,
    prepare_direct_response_node,
    prepare_fallback_response_node,
    prepare_end_conversation_node,
    handle_error_node,
)
from .prompts import (
    # ### START: 이 부분이 수정되었습니다 ###
    # initialize_all_data는 이제 사용하지 않으므로 임포트에서 제거합니다.
    OPENAI_API_KEY,
    json_llm,
    generative_llm
    # ### END: 수정된 부분 끝 ###
)

# --- Initial Data Loading ---
# ### START: 이 부분이 수정되었습니다 ###
# initialize_all_data() 호출을 제거합니다.
# 데이터는 prompts.py 모듈이 임포트될 때 자동으로 로드됩니다.
# ### END: 수정된 부분 끝 ###


# --- Conditional Edge Logic ---
def route_from_entry(state: AgentState) -> str:
    # entry_point_node에서 오류가 발생했는지 확인
    if state.get("is_final_turn_response"):
        return END
    return "main_agent_router_node"

def route_from_main_agent_router(state: AgentState) -> str:
    decision = state.get("main_agent_routing_decision")
    print(f"Main Agent 라우팅 결정: {decision}")
    if state.get("is_final_turn_response"):
        return END

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
    
    if decision in route_map:
        if decision == "invoke_scenario_agent" and not state.get("current_product_type"):
            print("경고: invoke_scenario_agent 요청되었으나 current_product_type 미설정. select_product_type으로 재라우팅.")
            state["main_agent_direct_response"] = "먼저 어떤 상품에 대해 상담하고 싶으신지 알려주시겠어요? (디딤돌 대출, 전세자금 대출, 입출금통장 개설)"
            return "prepare_direct_response_node"
        return route_map[decision]

    return "prepare_fallback_response_node"

def route_from_scenario_agent_call(state: AgentState) -> str:
    scenario_output = state.get("scenario_agent_output")
    if scenario_output and str(scenario_output.get("intent", "")).startswith("error_"):
        err_msg = f"답변 분석 중 오류: {scenario_output.get('intent')}"
        state["error_message"] = err_msg
        state["final_response_text_for_tts"] = err_msg
        return "handle_error_node"
    return "main_agent_scenario_processing_node"

# --- Graph Build ---
workflow = StateGraph(AgentState)

nodes_to_add = [
    ("entry_point_node", entry_point_node),
    ("main_agent_router_node", main_agent_router_node),
    ("set_product_type_node", set_product_type_node),
    ("call_scenario_agent_node", call_scenario_agent_node),
    ("factual_answer_node", factual_answer_node),
    ("synthesize_answer_node", synthesize_answer_node),
    ("main_agent_scenario_processing_node", main_agent_scenario_processing_node),
    ("prepare_direct_response_node", prepare_direct_response_node),
    ("prepare_fallback_response_node", prepare_fallback_response_node),
    ("prepare_end_conversation_node", prepare_end_conversation_node),
    ("handle_error_node", handle_error_node)
]

for name, node_func in nodes_to_add:
    workflow.add_node(name, node_func)

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
    user_input_text: str | None = None,
    user_input_audio_b64: str | None = None,
    session_id: str | None = "default_session",
    current_state_dict: Dict[str, Any] | None = None
) -> AsyncGenerator[Union[Dict[str, Any], str], None]:
    
    if not OPENAI_API_KEY or not json_llm or not generative_llm:
        error_msg = "LLM 서비스가 초기화되지 않았습니다. API 키 설정을 확인하세요."
        yield {"type": "error", "session_id": session_id, "message": error_msg}
        yield {"type": "final_state", "session_id": session_id, "data": {"error_message": error_msg, "is_final_turn_response": True, "messages": [AIMessage(content=error_msg)]}}
        return

    initial_messages = list(current_state_dict.get("messages", [])) if current_state_dict else []

    initial_input_for_graph: AgentState = cast(AgentState, {
        "session_id": session_id or "default_session",
        "user_input_text": user_input_text,
        "user_input_audio_b64": user_input_audio_b64,
        "stt_result": user_input_text,
        "messages": initial_messages,
        "current_product_type": current_state_dict.get("current_product_type") if current_state_dict else None,
        "current_scenario_stage_id": current_state_dict.get("current_scenario_stage_id") if current_state_dict else None,
        "collected_product_info": current_state_dict.get("collected_product_info", {}) if current_state_dict else {},
        "available_product_types": ["didimdol", "jeonse", "deposit_account"],
    })
    
    print(f"\n--- [{session_id}] Agent Turn 시작 ---")
    print(f"초기 입력 상태 (요약): product_type='{initial_input_for_graph.get('current_product_type')}', stage='{initial_input_for_graph.get('current_scenario_stage_id')}', text='{user_input_text}'")

    full_response_text_streamed = ""
    final_state_to_yield = None

    try:
        async for event in app_graph.astream(initial_input_for_graph):
            node_name = list(event.keys())[0]
            current_state_from_node = event[node_name]

            if current_state_from_node.get('is_final_turn_response'):
                final_state_to_yield = current_state_from_node

        if final_state_to_yield:
            text_to_stream = final_state_to_yield.get("final_response_text_for_tts")
            if text_to_stream:
                yield {"type": "stream_start", "stream_type": "general_response"}
                full_response_text_streamed = text_to_stream
                
                chunk_size = 20
                for i in range(0, len(text_to_stream), chunk_size):
                    chunk = text_to_stream[i:i+chunk_size]
                    yield chunk
                    await asyncio.sleep(0.02)
                yield {"type": "stream_end", "full_text": full_response_text_streamed}
                
                yield {"type": "final_state", "session_id": session_id, "data": final_state_to_yield}
        else:
            print(f"CRITICAL: Graph finished without a final response for session {session_id}")
            error_response = "죄송합니다, 응답을 생성하는 데 실패했습니다. 그래프 로직을 확인해주세요."
            yield {"type": "stream_start", "stream_type": "critical_error"}
            yield error_response
            yield {"type": "stream_end", "full_text": error_response}
            final_graph_output_state = cast(AgentState, initial_input_for_graph.copy())
            final_graph_output_state["error_message"] = error_response
            yield {"type": "final_state", "session_id": session_id, "data": final_graph_output_state}

    except Exception as e:
        print(f"CRITICAL error in run_agent_streaming for session {session_id}: {e}")
        traceback.print_exc()
        error_response = "죄송합니다, 에이전트 처리 중 심각한 시스템 오류가 발생했습니다."
        yield {"type": "stream_start", "stream_type": "critical_error"}
        yield error_response
        yield {"type": "stream_end", "full_text": error_response}
        
        final_graph_output_state = cast(AgentState, initial_input_for_graph.copy())
        final_graph_output_state["error_message"] = str(e)
        final_graph_output_state["final_response_text_for_tts"] = error_response
        final_graph_output_state["is_final_turn_response"] = True
        current_messages_on_error = list(initial_input_for_graph.get("messages", []))
        current_messages_on_error.append(AIMessage(content=error_response))
        final_graph_output_state["messages"] = current_messages_on_error
        yield {"type": "final_state", "session_id": session_id, "data": final_graph_output_state}

    print(f"--- [{session_id}] Agent Turn 종료 (최종 AI 응답 텍스트 길이: {len(full_response_text_streamed)}) ---")