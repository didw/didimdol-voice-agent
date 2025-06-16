# backend/app/graph/state.py

from typing import Dict, TypedDict, Optional, Sequence, Literal, Any, List
from langchain_core.messages import BaseMessage


PRODUCT_TYPES = Literal["didimdol", "jeonse", "deposit_account"] # Existing

class ScenarioAgentOutput(TypedDict, total=False):
    intent: Optional[str]
    entities: Optional[Dict[str, Any]]
    is_scenario_related: bool

class AgentState(TypedDict):
    # --- Core Session & Input ---
    session_id: str
    user_input_text: Optional[str]
    user_input_audio_b64: Optional[str] # Retained for completeness
    
    # --- Turn-specific State ---
    stt_result: Optional[str]
    error_message: Optional[str]
    is_final_turn_response: bool
    
    # --- Product & Scenario Management ---
    current_product_type: Optional[PRODUCT_TYPES]
    available_product_types: List[PRODUCT_TYPES]
    collected_product_info: Dict[str, Any]
    current_scenario_stage_id: Optional[str]
    loan_selection_is_fresh: Optional[bool] # True if product was just selected

    # --- Dynamic Data (Loaded per turn) ---
    active_scenario_data: Optional[Dict]
    active_knowledge_base_content: Optional[str]
    active_scenario_name: Optional[str]
    
    # --- Agent & Tool Outputs (Major Change) ---

    # NEW: The plan of actions to execute for the turn
    action_plan: List[str]
    
    # The Main Agent's routing decision
    main_agent_routing_decision: Optional[str] 
    # A direct response if the action is simple (e.g., chit-chat)
    main_agent_direct_response: Optional[str] 
    # The factual answer from the QA tool/chain
    factual_response: Optional[str]
    # The output from the Scenario NLU tool
    scenario_agent_output: Optional[ScenarioAgentOutput]
    
    # --- Conversation History & Final Response ---
    messages: Sequence[BaseMessage]
    final_response_text_for_tts: Optional[str]