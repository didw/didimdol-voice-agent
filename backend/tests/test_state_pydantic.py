import pytest
from typing import Dict, Any
from datetime import datetime, timedelta

from app.graph.state import AgentState, ScenarioAgentOutput
from app.graph.state_utils import (
    merge_state_updates, convert_scenario_output, validate_state_transition, 
    clean_turn_state, extract_conversation_context
)
from langchain_core.messages import HumanMessage, AIMessage


class TestPydanticStateModels:
    """Test Pydantic state models"""
    
    def test_scenario_agent_output_creation(self):
        """Test ScenarioAgentOutput creation and conversion"""
        # Test creation with defaults
        output = ScenarioAgentOutput()
        assert output.intent is None
        assert output.entities == {}
        assert output.is_scenario_related is False
        
        # Test creation with values
        output = ScenarioAgentOutput(
            intent="test_intent",
            entities={"key": "value"},
            is_scenario_related=True
        )
        assert output.intent == "test_intent"
        assert output.entities == {"key": "value"}
        assert output.is_scenario_related is True
        
    def test_scenario_agent_output_conversion(self):
        """Test conversion between Pydantic and dict"""
        # Pydantic -> dict
        pydantic_output = ScenarioAgentOutput(
            intent="test_intent",
            entities={"key": "value"},
            is_scenario_related=True
        )
        dict_output = pydantic_output.model_dump()
        
        assert isinstance(dict_output, dict)
        assert dict_output["intent"] == "test_intent"
        assert dict_output["entities"] == {"key": "value"}
        assert dict_output["is_scenario_related"] is True
        
        # dict -> Pydantic
        converted_back = ScenarioAgentOutput(**dict_output)
        assert converted_back.intent == "test_intent"
        assert converted_back.entities == {"key": "value"}
        assert converted_back.is_scenario_related is True
        
    def test_agent_state_creation(self):
        """Test AgentState creation with defaults"""
        state = AgentState(session_id="test_session")
        
        assert state.session_id == "test_session"
        assert state.user_input_text is None
        assert state.is_final_turn_response is False
        assert state.available_product_types == ["didimdol", "jeonse", "deposit_account"]
        assert state.collected_product_info == {}
        assert state.action_plan == []
        assert state.messages == []
        assert isinstance(state.created_at, datetime)
        assert isinstance(state.updated_at, datetime)
        
    def test_agent_state_validation(self):
        """Test AgentState validation"""
        # Test messages validation
        state = AgentState(session_id="test", messages=None)
        assert state.messages == []
        
        # Test with actual messages
        from langchain_core.messages import HumanMessage
        messages = [HumanMessage(content="Hello")]
        state = AgentState(session_id="test", messages=messages)
        assert len(state.messages) == 1
        assert state.messages[0].content == "Hello"
        
    def test_agent_state_conversion(self):
        """Test conversion between AgentState and dict"""
        # Create Pydantic model
        pydantic_state = AgentState(
            session_id="test_session",
            user_input_text="Hello",
            current_product_type="didimdol",
            collected_product_info={"key": "value"},
            action_plan=["action1", "action2"]
        )
        
        # Convert to dict
        dict_state = pydantic_state.to_dict()
        assert isinstance(dict_state, dict)
        assert dict_state["session_id"] == "test_session"
        assert dict_state["user_input_text"] == "Hello"
        assert dict_state["current_product_type"] == "didimdol"
        assert dict_state["collected_product_info"] == {"key": "value"}
        assert dict_state["action_plan"] == ["action1", "action2"]
        
        # Should exclude metadata fields
        assert "created_at" not in dict_state
        assert "updated_at" not in dict_state
        
        # Convert back to Pydantic
        converted_back = AgentState.from_dict(dict_state)
        assert converted_back.session_id == "test_session"
        assert converted_back.user_input_text == "Hello"
        assert converted_back.current_product_type == "didimdol"
        
    def test_agent_state_merge_update(self):
        """Test merge_update method"""
        state = AgentState(session_id="test")
        original_time = state.updated_at
        
        # Small delay to ensure timestamp difference
        import time
        time.sleep(0.01)
        
        # Merge updates
        updated_state = state.merge_update({
            "user_input_text": "Hello",
            "current_product_type": "didimdol"
        })
        
        # Should be new instance
        assert updated_state is not state
        assert updated_state.session_id == "test"
        assert updated_state.user_input_text == "Hello"
        assert updated_state.current_product_type == "didimdol"
        assert updated_state.updated_at > original_time
        
    def test_update_timestamp(self):
        """Test timestamp update"""
        state = AgentState(session_id="test")
        original_time = state.updated_at
        
        # Small delay to ensure timestamp difference
        import time
        time.sleep(0.01)
        
        state.update_timestamp()
        assert state.updated_at > original_time


class TestStateUtils:
    """Test state utility functions"""
    
    def test_merge_state_updates(self):
        """Test merge_state_updates function"""
        base_state: AgentState = {
            "session_id": "test",
            "user_input_text": None,
            "is_final_turn_response": False,
            "current_product_type": None,
            "available_product_types": ["didimdol", "jeonse", "deposit_account"],
            "collected_product_info": {},
            "current_scenario_stage_id": None,
            "loan_selection_is_fresh": None,
            "active_scenario_data": None,
            "active_knowledge_base_content": None,
            "active_scenario_name": None,
            "action_plan": [],
            "main_agent_routing_decision": None,
            "main_agent_direct_response": None,
            "factual_response": None,
            "scenario_agent_output": None,
            "messages": [],
            "final_response_text_for_tts": None,
            "action_plan_struct": [],
            "scenario_ready_for_continuation": None,
            "scenario_awaiting_user_response": None,
            "stt_result": None,
            "error_message": None,
            "user_input_audio_b64": None
        }
        
        updates = {
            "user_input_text": "Hello",
            "current_product_type": "didimdol",
            "is_final_turn_response": True
        }
        
        result = merge_state_updates(base_state, updates)
        
        assert result["session_id"] == "test"
        assert result["user_input_text"] == "Hello"
        assert result["current_product_type"] == "didimdol"
        assert result["is_final_turn_response"] is True
        
        # Original state should be unchanged
        assert base_state["user_input_text"] is None
        assert base_state["current_product_type"] is None
        
    # Note: conversion utilities removed - LangGraph handles Pydantic models directly
        
    def test_convert_scenario_output(self):
        """Test convert_scenario_output function"""
        # Test with None
        result = convert_scenario_output(None)
        assert result is None
        
        # Test with dict
        dict_output = {
            "intent": "test",
            "entities": {"key": "value"},
            "is_scenario_related": True
        }
        
        pydantic_output = convert_scenario_output(dict_output)
        assert isinstance(pydantic_output, ScenarioAgentOutput)
        assert pydantic_output.intent == "test"
        assert pydantic_output.entities == {"key": "value"}
        assert pydantic_output.is_scenario_related is True
        
        # Test with already Pydantic format
        same_output = convert_scenario_output(pydantic_output)
        assert same_output is pydantic_output
        
    def test_validate_state_transition(self):
        """Test validate_state_transition function"""
        base_state: AgentState = {
            "session_id": "test",
            "user_input_text": None,
            "is_final_turn_response": False,
            "current_product_type": None,
            "available_product_types": ["didimdol", "jeonse", "deposit_account"],
            "collected_product_info": {},
            "current_scenario_stage_id": None,
            "loan_selection_is_fresh": None,
            "active_scenario_data": None,
            "active_knowledge_base_content": None,
            "active_scenario_name": None,
            "action_plan": [],
            "main_agent_routing_decision": None,
            "main_agent_direct_response": None,
            "factual_response": None,
            "scenario_agent_output": None,
            "messages": [],
            "final_response_text_for_tts": None,
            "action_plan_struct": [],
            "scenario_ready_for_continuation": None,
            "scenario_awaiting_user_response": None,
            "stt_result": None,
            "error_message": None,
            "user_input_audio_b64": None
        }
        
        # Valid transition
        new_state = base_state.copy()
        new_state["user_input_text"] = "Hello"
        assert validate_state_transition(base_state, new_state) is True
        
        # Invalid transition (different session)
        invalid_state = base_state.copy()
        invalid_state["session_id"] = "different"
        assert validate_state_transition(base_state, invalid_state) is False
        
        # Invalid transition (final to non-final)
        final_state = base_state.copy()
        final_state["is_final_turn_response"] = True
        non_final_state = base_state.copy()
        non_final_state["is_final_turn_response"] = False
        assert validate_state_transition(final_state, non_final_state) is False
        
    def test_clean_turn_state(self):
        """Test clean_turn_state function"""
        dirty_state: AgentState = {
            "session_id": "test",
            "user_input_text": "Hello",
            "is_final_turn_response": True,
            "current_product_type": "didimdol",
            "available_product_types": ["didimdol", "jeonse", "deposit_account"],
            "collected_product_info": {"key": "value"},
            "current_scenario_stage_id": "stage1",
            "loan_selection_is_fresh": True,
            "active_scenario_data": {"data": "value"},
            "active_knowledge_base_content": "content",
            "active_scenario_name": "scenario",
            "action_plan": ["action1", "action2"],
            "main_agent_routing_decision": "decision",
            "main_agent_direct_response": "response",
            "factual_response": "fact",
            "scenario_agent_output": {"intent": "test"},
            "messages": [HumanMessage(content="Hello")],
            "final_response_text_for_tts": "final",
            "action_plan_struct": [{"action": "test"}],
            "scenario_ready_for_continuation": True,
            "scenario_awaiting_user_response": True,
            "stt_result": "result",
            "error_message": "error",
            "user_input_audio_b64": "audio"
        }
        
        cleaned = clean_turn_state(dirty_state)
        
        # Should preserve persistent fields
        assert cleaned["session_id"] == "test"
        assert cleaned["current_product_type"] == "didimdol"
        assert cleaned["collected_product_info"] == {"key": "value"}
        assert cleaned["messages"] == [HumanMessage(content="Hello")]
        
        # Should clear turn-specific fields
        assert cleaned["user_input_text"] is None
        assert cleaned["is_final_turn_response"] is False
        assert cleaned["action_plan"] == []
        assert cleaned["main_agent_routing_decision"] is None
        assert cleaned["final_response_text_for_tts"] is None
        
    def test_extract_conversation_context(self):
        """Test extract_conversation_context function"""
        state: AgentState = {
            "session_id": "test_session",
            "user_input_text": "Hello",
            "is_final_turn_response": False,
            "current_product_type": "didimdol",
            "available_product_types": ["didimdol", "jeonse", "deposit_account"],
            "collected_product_info": {"key": "value"},
            "current_scenario_stage_id": "stage1",
            "loan_selection_is_fresh": None,
            "active_scenario_data": None,
            "active_knowledge_base_content": None,
            "active_scenario_name": "Test Scenario",
            "action_plan": [],
            "main_agent_routing_decision": None,
            "main_agent_direct_response": None,
            "factual_response": None,
            "scenario_agent_output": None,
            "messages": [HumanMessage(content="Hello"), AIMessage(content="Hi")],
            "final_response_text_for_tts": None,
            "action_plan_struct": [],
            "scenario_ready_for_continuation": True,
            "scenario_awaiting_user_response": False,
            "stt_result": None,
            "error_message": None,
            "user_input_audio_b64": None
        }
        
        context = extract_conversation_context(state)
        
        assert context["session_id"] == "test_session"
        assert context["current_product_type"] == "didimdol"
        assert context["current_scenario_stage_id"] == "stage1"
        assert context["collected_product_info"] == {"key": "value"}
        assert context["active_scenario_name"] == "Test Scenario"
        assert context["messages_count"] == 2
        assert context["scenario_ready_for_continuation"] is True
        assert context["scenario_awaiting_user_response"] is False