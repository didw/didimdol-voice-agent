# backend/app/graph/nodes/control/end_conversation.py
"""
대화 종료 노드 - 세션을 종료하고 마지막 메시지를 전송
"""
from langchain_core.messages import AIMessage

from ...state import AgentState
from ...logger import node_log as log_node_execution, log_execution_time


@log_execution_time
async def end_conversation_node(state: AgentState) -> AgentState:
    """
    대화 종료 노드
    - 세션 종료
    - 감사 메시지 전송
    """
    log_node_execution("End_Conversation", "terminating session")
    response_text = "상담을 종료합니다. 이용해주셔서 감사합니다."
    
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=response_text)]
    return {
        **state, 
        "final_response_text_for_tts": response_text, 
        "messages": updated_messages, 
        "is_final_turn_response": True
    }