# backend/app/graph/state.py

from typing import Dict, Optional, Sequence, Literal, Any, List, Union, cast
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field, field_validator, ConfigDict
from datetime import datetime


PRODUCT_TYPES = Literal["didimdol", "jeonse", "deposit_account"]

# === Pydantic Models for Type Safety ===

class ScenarioAgentOutput(BaseModel):
    """Scenario agent output with type safety"""
    intent: Optional[str] = None
    entities: Optional[Dict[str, Any]] = Field(default_factory=dict)
    is_scenario_related: bool = False
    
    # Dict-like interface for backward compatibility
    def get(self, key: str, default: Any = None) -> Any:
        """Get value like dict.get()"""
        try:
            return getattr(self, key)
        except AttributeError:
            return default
    
    def __getitem__(self, key: str) -> Any:
        """Get item like dict[key]"""
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)
    
    def __setitem__(self, key: str, value: Any) -> None:
        """Set item like dict[key] = value"""
        setattr(self, key, value)
    
    def __contains__(self, key: str) -> bool:
        """Check if key exists like 'key' in dict"""
        return hasattr(self, key)


class AgentState(BaseModel):
    """Main agent state with validation and type safety"""
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    # --- Core Session & Input ---
    session_id: str
    user_input_text: Optional[str] = None
    user_input_audio_b64: Optional[str] = None
    input_mode: str = "text"  # text, voice, choice, choice_exact, boolean
    
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
    stage_response_data: Optional[Dict[str, Any]] = None  # Stage response type data
    
    # --- Conversation History & Final Response ---
    messages: Sequence[BaseMessage] = Field(default_factory=list)
    final_response_text_for_tts: Optional[str] = None
    last_llm_prompt: Optional[str] = None  # Store the last prompt shown to user for context
    
    # --- Turn-specific state ---
    action_plan_struct: List[Dict[str, Any]] = Field(default_factory=list)
    
    # --- Router & Loop Prevention ---
    router_call_count: int = 0
    correction_mode: bool = False
    modification_reasoning: Optional[str] = None
    pending_modifications: Optional[Dict[str, Any]] = None
    original_values_before_modification: Optional[Dict[str, Any]] = None  # 수정 전 원본 값 저장
    waiting_for_additional_modifications: Optional[bool] = None  # 추가 수정사항 대기 중인지 여부
    current_modification_context: Optional[str] = None  # 현재 수정 중인 필드 컨텍스트 (work_address, address 등)
    special_response_for_modification: Optional[bool] = None  # 개인정보 수정 요청에 대한 특별 응답 플래그
    
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
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict format for LangGraph compatibility"""
        data = self.model_dump(exclude={'created_at', 'updated_at'})
        # Preserve BaseMessage objects as-is
        data['messages'] = list(self.messages)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentState":
        """Create from dict format"""
        # Handle datetime fields
        now = datetime.now()
        data.setdefault('created_at', now)
        data.setdefault('updated_at', now)
        
        return cls(**data)
    
    def update_timestamp(self) -> None:
        """Update the timestamp"""
        self.updated_at = datetime.now()
    
    def merge_update(self, updates: Dict[str, Any]) -> "AgentState":
        """Merge updates and return new instance"""
        if 'collected_product_info' in updates:
            pass
        
        # Deep copy를 사용하여 중첩된 dict도 제대로 복사
        from copy import deepcopy
        current_data = deepcopy(self.model_dump())
        
        # Updates 적용
        for key, value in updates.items():
            current_data[key] = value
        
        current_data['updated_at'] = datetime.now()
        new_state = AgentState(**current_data)
        
        if 'collected_product_info' in updates:
            pass
        
        return new_state
    
    # Dict-like interface for backward compatibility
    def get(self, key: str, default: Any = None) -> Any:
        """Get value like dict.get()"""
        try:
            return getattr(self, key)
        except AttributeError:
            return default
    
    def __getitem__(self, key: str) -> Any:
        """Get item like dict[key]"""
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)
    
    def __setitem__(self, key: str, value: Any) -> None:
        """Set item like dict[key] = value"""
        setattr(self, key, value)
    
    def __contains__(self, key: str) -> bool:
        """Check if key exists like 'key' in dict"""
        return hasattr(self, key)
    
    def keys(self):
        """Return all field names"""
        return self.model_fields.keys()
    
    def values(self):
        """Return all field values"""
        return [getattr(self, field) for field in self.model_fields.keys()]
    
    def items(self):
        """Return all field items"""
        return [(field, getattr(self, field)) for field in self.model_fields.keys()]
    
    def copy(self) -> "AgentState":
        """Create a copy of this state"""
        return AgentState.model_validate(self.model_dump())
    
    def update(self, other: Dict[str, Any]) -> None:
        """Update this state with values from dict"""
        for key, value in other.items():
            if hasattr(self, key):
                setattr(self, key, value)