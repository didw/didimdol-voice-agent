# backend/app/graph/state.py
from typing import Dict, TypedDict, Optional, Sequence, Literal, Any, List
from langchain_core.messages import BaseMessage


PRODUCT_TYPES = Literal["didimdol", "jeonse", "deposit_account"] # 상품 유형 확장


# Scenario Agent의 예상 출력 구조
class ScenarioAgentOutput(TypedDict, total=False):
    intent: Optional[str]
    entities: Optional[Dict[str, Any]]
    is_scenario_related: bool
    # user_sentiment: Optional[Literal['positive', 'negative', 'neutral']] # 필요시 추가

# QA Agent의 예상 출력 (스트리밍에서는 사용되지 않을 수 있음, 결과는 직접 텍스트로)
class QAAgentOutput(TypedDict, total=False):
    answer: Optional[str]
    # retrieved_context_summary: Optional[str] # 디버깅용

class AgentState(TypedDict):
    # --- 초기 입력 및 세션 정보 ---
    session_id: str
    user_input_text: Optional[str]
    user_input_audio_b64: Optional[str]
    loan_selection_is_fresh: Optional[bool] # 이제 product_selection_is_fresh로 명칭 변경 고려

    # --- STT 결과 ---
    stt_result: Optional[str]

    # --- Product Type Selection ---
    current_product_type: Optional[PRODUCT_TYPES] # 필드명 변경 완료
    available_product_types: List[PRODUCT_TYPES]  # 필드명 변경 완료

    # --- Main Agent (라우터) 판단 ---
    main_agent_routing_decision: Optional[Literal[
        "invoke_scenario_agent",
        "invoke_qa_agent",
        "answer_directly_chit_chat",
        "process_next_scenario_step",
        "select_loan_type",         # 이제 select_product_type으로 명칭 변경 고려
        "set_loan_type_didimdol",   # 이제 set_product_type_didimdol 등으로 변경 고려
        "set_loan_type_jeonse",
        "set_loan_type_deposit_account", # 신규 추가
        "end_conversation",
        "unclear_input"
    ]]
    main_agent_direct_response: Optional[str]
    factual_response: Optional[str]
    
    # --- Scenario Agent (NLU) 출력 ---
    scenario_agent_output: Optional[ScenarioAgentOutput]

    # --- 대화 상태 ---
    messages: Sequence[BaseMessage]
    current_scenario_stage_id: Optional[str]
    collected_product_info: Dict[str, Any] # 필드명 변경 완료
    
    # --- Dynamic Data based on current_product_type ---
    active_scenario_data: Optional[Dict]
    active_knowledge_base_content: Optional[str]
    active_scenario_name: Optional[str]

    # --- 최종 응답 ---
    final_response_text_for_tts: Optional[str]

    # --- 오류 상태 ---
    error_message: Optional[str]
    is_final_turn_response: bool
    