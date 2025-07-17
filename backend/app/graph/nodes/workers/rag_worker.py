# backend/app/graph/nodes/workers/rag_worker.py
"""
RAG Worker 노드 - 지식 기반 정보 검색 및 답변 생성
"""
from langchain_core.prompts import ChatPromptTemplate

from ...state import AgentState
from ...state_utils import ensure_pydantic_state, ensure_dict_state
from ....services.rag_service import rag_service
from ...utils import ALL_PROMPTS, format_messages_for_prompt
from ...chains import json_llm
from ...models import expanded_queries_parser
from ...logger import node_log as log_node_execution, log_execution_time


@log_execution_time
async def factual_answer_node(state: AgentState) -> AgentState:
    """
    사실 기반 답변 생성 노드 - Pydantic 버전
    - 질문 확장 (Query Expansion)
    - RAG 파이프라인 실행
    - 에러 처리 및 폴백
    """
    # Convert to Pydantic for internal processing
    pydantic_state = ensure_pydantic_state(state)
    
    original_question = pydantic_state.stt_result or ""
    log_node_execution("RAG_Worker", f"query='{original_question[:30]}...'")
    
    messages = pydantic_state.messages
    chat_history = format_messages_for_prompt(list(messages)[:-1]) if len(messages) > 1 else "No previous conversation."
    scenario_name = pydantic_state.active_scenario_name or "General Financial Advice"

    if not rag_service.is_ready():
        log_node_execution("RAG_Worker", "WARNING: RAG service not ready")
        state_updates = {"factual_response": "죄송합니다, 현재 정보 검색 기능에 문제가 발생하여 답변을 드릴 수 없습니다. 잠시 후 다시 시도해 주세요."}
        return ensure_dict_state(pydantic_state.merge_update(state_updates))

    all_queries = [original_question]
    try:
        # 1. 질문 확장
        log_node_execution("RAG_Worker", "expanding queries...")
        expansion_prompt_template = ALL_PROMPTS.get('qa_agent', {}).get('rag_query_expansion_prompt')
        if not expansion_prompt_template:
            raise ValueError("RAG query expansion prompt not found.")
        
        expansion_prompt = ChatPromptTemplate.from_template(expansion_prompt_template)
        
        expansion_chain = expansion_prompt | json_llm | expanded_queries_parser
        expanded_result = await expansion_chain.ainvoke({
            "scenario_name": scenario_name,
            "chat_history": chat_history,
            "user_question": original_question
        })
        
        if expanded_result and expanded_result.queries:
            all_queries.extend(expanded_result.queries)
            log_node_execution("RAG_Worker", f"expanded to {len(all_queries)} queries")
        else:
            log_node_execution("RAG_Worker", "no expansion, using original query")

    except Exception as e:
        # 질문 확장에 실패하더라도, 원본 질문으로 계속 진행
        log_node_execution("RAG_Worker", f"expansion error: {e}")

    try:
        # 2. RAG 파이프라인 호출 (원본 + 확장 질문)
        log_node_execution("RAG_Worker", f"invoking RAG with {len(all_queries)} queries")
        factual_response = await rag_service.answer_question(all_queries, original_question)
    except Exception as e:
        log_node_execution("RAG_Worker", f"ERROR: {e}")
        factual_response = "정보를 검색하는 중 오류가 발생했습니다."

    # 다음 액션을 위해 plan과 struct에서 현재 액션 제거
    updated_plan = pydantic_state.action_plan.copy()
    if updated_plan:
        updated_plan.pop(0)
    
    updated_struct = pydantic_state.action_plan_struct.copy()
    if updated_struct:
        updated_struct.pop(0)

    log_node_execution("RAG_Worker", output_info=f"response='{factual_response[:40]}...'")
    
    state_updates = {
        "factual_response": factual_response,
        "action_plan": updated_plan,
        "action_plan_struct": updated_struct
    }
    
    updated_state = pydantic_state.merge_update(state_updates)
    return ensure_dict_state(updated_state)