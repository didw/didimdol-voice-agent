# backend/app/graph/state_utils.py
"""
State conversion utilities for hybrid TypedDict/Pydantic approach
"""

from typing import Dict, Any, Optional, Union
from .state import AgentState, AgentStateModel, ScenarioAgentOutput, ScenarioAgentOutputModel


def merge_state_updates(base_state: AgentState, updates: Dict[str, Any]) -> AgentState:
    """
    Merge updates into base state safely.
    
    Args:
        base_state: Base AgentState
        updates: Updates to merge
        
    Returns:
        Updated AgentState
    """
    result = base_state.copy()
    result.update(updates)
    return result


def ensure_pydantic_state(state: Union[AgentState, AgentStateModel]) -> AgentStateModel:
    """
    Ensure state is in Pydantic format.
    
    Args:
        state: State in either TypedDict or Pydantic format
        
    Returns:
        AgentStateModel instance
    """
    if isinstance(state, AgentStateModel):
        return state
    
    # Convert from TypedDict to Pydantic
    return AgentStateModel.from_dict(state)


def ensure_dict_state(state: Union[AgentState, AgentStateModel]) -> AgentState:
    """
    Ensure state is in TypedDict format.
    
    Args:
        state: State in either TypedDict or Pydantic format
        
    Returns:
        AgentState (TypedDict) instance
    """
    if isinstance(state, AgentStateModel):
        return state.to_dict()
    
    # Already in TypedDict format
    return state


def convert_scenario_output(output: Optional[Union[ScenarioAgentOutput, ScenarioAgentOutputModel]]) -> Optional[ScenarioAgentOutput]:
    """
    Convert scenario output to TypedDict format.
    
    Args:
        output: Scenario output in either format
        
    Returns:
        ScenarioAgentOutput or None
    """
    if output is None:
        return None
    
    if isinstance(output, ScenarioAgentOutputModel):
        return output.to_dict()
    
    return output


def validate_state_transition(old_state: AgentState, new_state: AgentState) -> bool:
    """
    Validate that a state transition is valid.
    
    Args:
        old_state: Previous state
        new_state: New state
        
    Returns:
        True if transition is valid
    """
    # Basic validation rules
    if old_state.get("session_id") != new_state.get("session_id"):
        return False
    
    # Turn progression validation
    if old_state.get("is_final_turn_response") and not new_state.get("is_final_turn_response"):
        # Can't go from final turn to non-final turn
        return False
    
    return True


def clean_turn_state(state: AgentState) -> AgentState:
    """
    Clean turn-specific state for new turn.
    
    Args:
        state: Current state
        
    Returns:
        State with turn-specific fields cleared
    """
    cleaned = state.copy()
    
    # Clear turn-specific fields
    turn_fields = [
        "user_input_text",
        "user_input_audio_b64", 
        "stt_result",
        "error_message",
        "is_final_turn_response",
        "action_plan",
        "action_plan_struct",
        "main_agent_routing_decision",
        "main_agent_direct_response",
        "factual_response",
        "scenario_agent_output",
        "final_response_text_for_tts"
    ]
    
    for field in turn_fields:
        if field in cleaned:
            if field in ["action_plan", "action_plan_struct"]:
                cleaned[field] = []
            elif field == "is_final_turn_response":
                cleaned[field] = False
            else:
                cleaned[field] = None
    
    return cleaned


def extract_conversation_context(state: AgentState) -> Dict[str, Any]:
    """
    Extract conversation context from state.
    
    Args:
        state: Current state
        
    Returns:
        Conversation context dictionary
    """
    return {
        "session_id": state.get("session_id"),
        "current_product_type": state.get("current_product_type"),
        "current_scenario_stage_id": state.get("current_scenario_stage_id"),
        "collected_product_info": state.get("collected_product_info", {}),
        "active_scenario_name": state.get("active_scenario_name"),
        "messages_count": len(state.get("messages", [])),
        "scenario_ready_for_continuation": state.get("scenario_ready_for_continuation"),
        "scenario_awaiting_user_response": state.get("scenario_awaiting_user_response")
    }