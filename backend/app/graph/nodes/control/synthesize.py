# backend/app/graph/nodes/control/synthesize.py
"""
응답 합성 노드 - 사실 기반 응답과 문맥 응답을 결합하여 최종 응답 생성
"""
import re
from langchain_core.messages import AIMessage

from ...state import AgentState
from ...utils import get_active_scenario_data
from ...chains import synthesizer_chain
from ...logger import node_log as log_node_execution, log_execution_time


@log_execution_time
async def synthesize_response_node(state: AgentState) -> dict:
    """
    응답 합성 노드
    - 우선순위 기반 응답 선택
    - 사실 기반 응답과 문맥 응답 결합
    - 최종 응답 생성
    """
    has_factual = bool(state.get("factual_response"))
    has_contextual = bool(state.get("current_product_type"))
    has_direct = bool(state.get("main_agent_direct_response"))
    log_node_execution("Synthesizer", f"factual={has_factual}, contextual={has_contextual}, direct={has_direct}")
    
    # 1. 이미 final_response_text_for_tts가 설정되어 있으면 그것을 우선 사용
    existing_response = state.get("final_response_text_for_tts")
    if existing_response:
        log_node_execution("Synthesizer", f"using existing response: {existing_response[:50]}...")
        updated_messages = list(state['messages']) + [AIMessage(content=existing_response)]
        return {"final_response_text_for_tts": existing_response, "messages": updated_messages, "is_final_turn_response": True}
    
    # 2. main_agent_direct_response가 있으면 우선 사용 (business_guidance에서 생성된 응답)
    direct_response = state.get("main_agent_direct_response")
    if direct_response:
        log_node_execution("Synthesizer", f"using direct response: {direct_response[:50]}...")
        updated_messages = list(state['messages']) + [AIMessage(content=direct_response)]
        return {"final_response_text_for_tts": direct_response, "messages": updated_messages, "is_final_turn_response": True}
    
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
                if "end_scenario_message" in contextual_response:
                    contextual_response = re.sub(r'%\{end_scenario_message\}%', 
                        active_scenario_data.get("end_scenario_message", "상담이 완료되었습니다. 이용해주셔서 감사합니다."), 
                        contextual_response)
                else:
                    contextual_response = re.sub(r'%\{([^}]+)\}%', 
                        lambda m: str(state.get("collected_product_info", {}).get(m.group(1), f"")), 
                        contextual_response)
    
    if not factual_answer or "Could not find" in factual_answer:
        final_answer = contextual_response or "죄송합니다, 도움을 드리지 못했습니다."
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
            log_node_execution("Synthesizer", f"ERROR: {e}")
            final_answer = f"{factual_answer}\n\n{contextual_response}"

    # final_answer가 None이 되지 않도록 보장
    if not final_answer:
        final_answer = "죄송합니다, 응답을 생성하는데 문제가 발생했습니다."

    log_node_execution("Synthesizer", output_info=f"response='{final_answer[:40]}...'")
    updated_messages = list(state['messages']) + [AIMessage(content=final_answer)]
    
    return {"final_response_text_for_tts": final_answer, "messages": updated_messages, "is_final_turn_response": True}