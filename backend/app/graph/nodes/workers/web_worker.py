# backend/app/graph/nodes/workers/web_worker.py
"""
Web Search Worker 노드 - 외부 웹 검색 및 정보 요약
"""
from langchain_core.prompts import ChatPromptTemplate

from ...state import AgentState
from ...state_utils import ensure_pydantic_state, ensure_dict_state
from ....services.web_search_service import web_search_service
from ...chains import generative_llm
from ...logger import node_log as log_node_execution, log_execution_time


@log_execution_time
async def web_search_node(state: AgentState) -> AgentState:
    """
    Web Search Worker - 외부 정보 검색 전문 처리 - Pydantic 버전
    - 웹 검색 실행
    - 검색 결과 요약
    - 에러 처리
    """
    # Convert to Pydantic for internal processing
    pydantic_state = ensure_pydantic_state(state)
    
    action_struct = pydantic_state.action_plan_struct[0] if pydantic_state.action_plan_struct else {}
    query = action_struct.get("tool_input", {}).get("query", "")
    log_node_execution("Web_Worker", f"query='{query[:30]}...'")
    
    if not query:
        state_updates = {"factual_response": "무엇에 대해 검색할지 알려주세요."}
        return ensure_dict_state(pydantic_state.merge_update(state_updates))

    # 1. Perform web search
    search_results = await web_search_service.asearch(query)
    
    # 2. Synthesize a natural language answer from the results
    try:
        synthesis_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a helpful AI assistant. Your task is to synthesize the provided web search results into a concise and natural-sounding answer to the user's question. Respond in Korean."),
            ("human", "User Question: {query}\n\nWeb Search Results:\n---\n{search_results}\n---\n\nSynthesized Answer:")
        ])
        
        synthesis_chain = synthesis_prompt | generative_llm
        response = await synthesis_chain.ainvoke({"query": query, "search_results": search_results})
        final_answer = response.content.strip()
        log_node_execution("Web_Worker", f"synthesized answer length: {len(final_answer)}")

    except Exception as e:
        log_node_execution("Web_Worker", f"ERROR synthesizing: {e}")
        final_answer = "웹 검색 결과를 요약하는 중 오류가 발생했습니다. 원본 검색 결과는 다음과 같습니다.\n\n" + search_results

    # 다음 액션을 위해 plan과 struct에서 현재 액션 제거
    updated_plan = pydantic_state.action_plan.copy()
    if updated_plan:
        updated_plan.pop(0)
    
    updated_struct = pydantic_state.action_plan_struct.copy()
    if updated_struct:
        updated_struct.pop(0)
        
    # 웹 검색 결과를 사실 기반 답변으로 간주하여 factual_response에 저장
    log_node_execution("Web_Worker", output_info=f"response='{final_answer[:40]}...'")
    
    state_updates = {
        "factual_response": final_answer,
        "action_plan": updated_plan,
        "action_plan_struct": updated_struct
    }
    
    updated_state = pydantic_state.merge_update(state_updates)
    return ensure_dict_state(updated_state)