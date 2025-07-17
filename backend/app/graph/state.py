# backend/app/graph/state.py

from typing import Dict, TypedDict, Optional, Sequence, Literal, Any, List, Union, cast
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field, field_validator, ConfigDict
from datetime import datetime


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

    # --- Turn-specific state (cleared at the start of each turn) ---
    action_plan_struct: List[Dict[str, Any]] # Holds the full action details
    
    # --- Scenario Continuation Management ---
    scenario_ready_for_continuation: Optional[bool] # True if scenario should continue next turn
    scenario_awaiting_user_response: Optional[bool] # True if waiting for user input to continue scenario


# === Pydantic Models for Enhanced Type Safety ===

class ScenarioAgentOutputModel(BaseModel):
    """Pydantic version of ScenarioAgentOutput"""
    intent: Optional[str] = None
    entities: Optional[Dict[str, Any]] = Field(default_factory=dict)
    is_scenario_related: bool = False
    
    def to_dict(self) -> ScenarioAgentOutput:
        """Convert to TypedDict format"""
        return cast(ScenarioAgentOutput, self.model_dump(exclude_none=True))
    
    @classmethod
    def from_dict(cls, data: Optional[ScenarioAgentOutput]) -> Optional["ScenarioAgentOutputModel"]:
        """Create from TypedDict format"""
        if data is None:
            return None
        return cls(**data)


class AgentStateModel(BaseModel):
    """Pydantic version of AgentState with validation and type safety"""
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    # --- Core Session & Input ---
    session_id: str
    user_input_text: Optional[str] = None
    user_input_audio_b64: Optional[str] = None
    
    # --- Turn-specific State ---
    stt_result: Optional[str] = None
    error_message: Optional[str] = None
    is_final_turn_response: bool = False
    
    # --- Product & Scenario Management ---
    current_product_type: Optional[PRODUCT_TYPES] = None
    available_product_types: List[PRODUCT_TYPES] = Field(default_factory=lambda: ["didimdol", "jeonse", "deposit_account"])
    collected_product_info: Dict[str, Any] = Field(default_factory=dict)
    current_scenario_stage_id: Optional[str] = None
    loan_selection_is_fresh: Optional[bool] = None
    
    # --- Dynamic Data (Loaded per turn) ---
    active_scenario_data: Optional[Dict] = None
    active_knowledge_base_content: Optional[str] = None
    active_scenario_name: Optional[str] = None
    
    # --- Agent & Tool Outputs ---
    action_plan: List[str] = Field(default_factory=list)
    main_agent_routing_decision: Optional[str] = None
    main_agent_direct_response: Optional[str] = None
    factual_response: Optional[str] = None
    scenario_agent_output: Optional[ScenarioAgentOutput] = None
    
    # --- Conversation History & Final Response ---
    messages: Sequence[BaseMessage] = Field(default_factory=list)
    final_response_text_for_tts: Optional[str] = None
    
    # --- Turn-specific state ---
    action_plan_struct: List[Dict[str, Any]] = Field(default_factory=list)
    
    # --- Scenario Continuation Management ---
    scenario_ready_for_continuation: Optional[bool] = None
    scenario_awaiting_user_response: Optional[bool] = None
    
    # --- Metadata ---
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    @field_validator('messages', mode='before')
    @classmethod
    def validate_messages(cls, v):
        """Validate messages field"""
        if v is None:
            return []
        return v
    
    def to_dict(self) -> AgentState:
        """Convert to TypedDict format for LangGraph compatibility"""
        data = self.model_dump(exclude={'created_at', 'updated_at'})
        return cast(AgentState, data)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentStateModel":
        """Create from TypedDict format"""
        # Handle datetime fields
        now = datetime.now()
        data.setdefault('created_at', now)
        data.setdefault('updated_at', now)
        
        return cls(**data)
    
    def update_timestamp(self) -> None:
        """Update the timestamp"""
        self.updated_at = datetime.now()
    
    def merge_update(self, updates: Dict[str, Any]) -> "AgentStateModel":
        """Merge updates and return new instance"""
        current_data = self.model_dump()
        current_data.update(updates)
        current_data['updated_at'] = datetime.now()
        return AgentStateModel(**current_data)