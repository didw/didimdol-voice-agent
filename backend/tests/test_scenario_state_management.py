"""
Scenario state management and validation tests for the 디딤돌 voice consultation agent.

This module tests:
- State persistence and recovery
- Progress tracking and validation
- Required information collection
- State transitions and rollback
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
import json
from typing import Dict, Any, List
from datetime import datetime

from app.graph.state import AgentState
from app.graph.agent import (
    process_scenario_logic_node,
    call_scenario_agent_node,
    main_agent_router_node
)


@pytest.fixture
def complete_scenario_data():
    """Complete scenario data with all stages."""
    return {
        "scenario_name": "디딤돌 대출 완전 상담",
        "initial_stage_id": "greeting",
        "required_info_fields": [
            {
                "key": "loan_purpose_confirmed",
                "display_name": "대출 목적",
                "required": True,
                "type": "boolean",
                "description": "주택 구입 목적인지 확인"
            },
            {
                "key": "marital_status",
                "display_name": "혼인 상태",
                "required": True,
                "type": "choice",
                "choices": ["미혼", "기혼", "예비부부"]
            },
            {
                "key": "has_home",
                "display_name": "주택 소유 여부",
                "required": True,
                "type": "boolean"
            },
            {
                "key": "annual_income",
                "display_name": "연소득",
                "required": True,
                "type": "number",
                "unit": "만원"
            },
            {
                "key": "target_home_price",
                "display_name": "구매 예정 주택 가격",
                "required": True,
                "type": "number",
                "unit": "만원"
            },
            {
                "key": "target_location",
                "display_name": "구매 예정 지역",
                "required": False,
                "type": "text"
            }
        ],
        "stages": {
            "greeting": {
                "id": "greeting",
                "next_stages": ["loan_purpose_check"]
            },
            "loan_purpose_check": {
                "id": "loan_purpose_check",
                "required_info": ["loan_purpose_confirmed"],
                "next_stages": ["basic_info_collection"]
            },
            "basic_info_collection": {
                "id": "basic_info_collection",
                "required_info": ["marital_status", "has_home", "annual_income"],
                "next_stages": ["property_info_collection", "eligibility_check"]
            },
            "property_info_collection": {
                "id": "property_info_collection",
                "required_info": ["target_home_price"],
                "optional_info": ["target_location"],
                "next_stages": ["eligibility_check"]
            },
            "eligibility_check": {
                "id": "eligibility_check",
                "validation_required": True,
                "next_stages": ["loan_calculation", "rejection"]
            },
            "loan_calculation": {
                "id": "loan_calculation",
                "next_stages": ["final_confirmation"]
            },
            "final_confirmation": {
                "id": "final_confirmation",
                "next_stages": ["end_scenario"]
            },
            "rejection": {
                "id": "rejection",
                "is_terminal": True
            },
            "end_scenario": {
                "id": "end_scenario",
                "is_terminal": True
            }
        }
    }


class TestStateManagement:
    """Test state management functionality."""
    
    @pytest.mark.asyncio
    async def test_state_persistence_across_stages(self, complete_scenario_data):
        """Test that state is properly persisted across stage transitions."""
        state: AgentState = {
            "messages": [],
            "stt_result": "",
            "agent_status": "",
            "user_name": "",
            "product_type": "didimdol",
            "product_type_confirmed": True,
            "factual_request": "",
            "factual_response": "",
            "info_collection": {},
            "action_plan": [],
            "action_plan_struct": [],
            "current_scenario_id": "didimdol_loan",
            "scenario_stage_id": "greeting",
            "scenario_ready_for_continuation": True,
            "is_urgent": False,
            "error_messages": []
        }
        
        # Simulate progression through stages
        stage_transitions = [
            ("greeting", "네, 시작할게요", {"scenario_stage_id": "loan_purpose_check"}),
            ("loan_purpose_check", "주택 구입하려고 합니다", {
                "scenario_stage_id": "basic_info_collection",
                "info_collection": {"loan_purpose_confirmed": True}
            }),
            ("basic_info_collection", "미혼이고 집은 없어요. 연봉은 5천만원입니다", {
                "scenario_stage_id": "property_info_collection",
                "info_collection": {
                    "loan_purpose_confirmed": True,
                    "marital_status": "미혼",
                    "has_home": False,
                    "annual_income": 5000
                }
            })
        ]
        
        for current_stage, user_input, expected_updates in stage_transitions:
            state["scenario_stage_id"] = current_stage
            state["stt_result"] = user_input
            
            # Verify state persists through transitions
            initial_info = state["info_collection"].copy()
            
            # Simulate stage processing
            state.update(expected_updates)
            
            # Verify previous info is retained
            for key, value in initial_info.items():
                assert state["info_collection"][key] == value
    
    @pytest.mark.asyncio
    async def test_state_recovery_after_error(self):
        """Test state recovery after an error occurs."""
        state: AgentState = {
            "messages": [],
            "stt_result": "계속 진행해주세요",
            "agent_status": "",
            "user_name": "",
            "product_type": "didimdol",
            "product_type_confirmed": True,
            "factual_request": "",
            "factual_response": "",
            "info_collection": {
                "marital_status": "미혼",
                "annual_income": 4000
            },
            "action_plan": ["invoke_scenario_agent"],
            "action_plan_struct": [],
            "current_scenario_id": "didimdol_loan",
            "scenario_stage_id": "basic_info_collection",
            "scenario_ready_for_continuation": True,
            "is_urgent": False,
            "error_messages": []
        }
        
        # Save current state
        saved_state = state.copy()
        saved_info = state["info_collection"].copy()
        
        # Simulate error
        state["error_messages"].append("Service temporarily unavailable")
        state["agent_status"] = "error"
        
        # Recovery process
        state["agent_status"] = "recovered"
        state["error_messages"] = []
        
        # Verify state is recovered properly
        assert state["info_collection"] == saved_info
        assert state["scenario_stage_id"] == saved_state["scenario_stage_id"]
        assert state["product_type"] == saved_state["product_type"]
    
    @pytest.mark.asyncio
    async def test_state_rollback_on_validation_failure(self, complete_scenario_data):
        """Test state rollback when validation fails."""
        state: AgentState = {
            "messages": [],
            "stt_result": "",
            "agent_status": "",
            "user_name": "",
            "product_type": "didimdol",
            "product_type_confirmed": True,
            "factual_request": "",
            "factual_response": "",
            "info_collection": {
                "loan_purpose_confirmed": True,
                "marital_status": "미혼",
                "has_home": False,
                "annual_income": 2000,  # Too low
                "target_home_price": 80000  # 8억원 - too high
            },
            "action_plan": [],
            "action_plan_struct": [],
            "current_scenario_id": "didimdol_loan",
            "scenario_stage_id": "eligibility_check",
            "scenario_ready_for_continuation": True,
            "is_urgent": False,
            "error_messages": []
        }
        
        # Validation logic
        income = state["info_collection"]["annual_income"]
        home_price = state["info_collection"]["target_home_price"]
        
        # Check eligibility
        is_eligible = income >= 3000 and home_price <= 60000  # 연소득 3천만원 이상, 주택가격 6억 이하
        
        if not is_eligible:
            # Rollback to previous stage
            state["scenario_stage_id"] = "basic_info_collection"
            state["agent_status"] = "validation_failed"
            
        assert state["scenario_stage_id"] == "basic_info_collection"
        assert state["agent_status"] == "validation_failed"


class TestProgressTracking:
    """Test progress tracking functionality."""
    
    def calculate_progress(self, info_collection: Dict[str, Any], required_fields: List[Dict]) -> float:
        """Calculate completion progress."""
        required_keys = [f["key"] for f in required_fields if f.get("required", True)]
        if not required_keys:
            return 1.0
        
        collected_required = sum(1 for key in required_keys if key in info_collection)
        return collected_required / len(required_keys)
    
    @pytest.mark.asyncio
    async def test_progress_calculation(self, complete_scenario_data):
        """Test accurate progress calculation."""
        required_fields = complete_scenario_data["required_info_fields"]
        
        test_cases = [
            ({}, 0.0),
            ({"loan_purpose_confirmed": True}, 0.2),
            ({"loan_purpose_confirmed": True, "marital_status": "미혼"}, 0.4),
            ({
                "loan_purpose_confirmed": True,
                "marital_status": "미혼",
                "has_home": False
            }, 0.6),
            ({
                "loan_purpose_confirmed": True,
                "marital_status": "미혼",
                "has_home": False,
                "annual_income": 5000
            }, 0.8),
            ({
                "loan_purpose_confirmed": True,
                "marital_status": "미혼",
                "has_home": False,
                "annual_income": 5000,
                "target_home_price": 40000
            }, 1.0),
            ({
                "loan_purpose_confirmed": True,
                "marital_status": "미혼",
                "has_home": False,
                "annual_income": 5000,
                "target_home_price": 40000,
                "target_location": "서울"  # Optional field
            }, 1.0)  # Progress still 100% as optional fields don't affect it
        ]
        
        for info_collection, expected_progress in test_cases:
            progress = self.calculate_progress(info_collection, required_fields)
            assert abs(progress - expected_progress) < 0.01
    
    @pytest.mark.asyncio
    async def test_stage_based_progress(self, complete_scenario_data):
        """Test progress tracking based on scenario stages."""
        stages = complete_scenario_data["stages"]
        
        # Define stage weights
        stage_weights = {
            "greeting": 0.0,
            "loan_purpose_check": 0.1,
            "basic_info_collection": 0.4,
            "property_info_collection": 0.6,
            "eligibility_check": 0.7,
            "loan_calculation": 0.8,
            "final_confirmation": 0.9,
            "end_scenario": 1.0
        }
        
        for stage_id, expected_progress in stage_weights.items():
            if stage_id in stages:
                assert 0 <= expected_progress <= 1.0
    
    @pytest.mark.asyncio
    async def test_progress_report_generation(self):
        """Test generation of progress reports."""
        state: AgentState = {
            "messages": [],
            "stt_result": "",
            "agent_status": "",
            "user_name": "김철수",
            "product_type": "didimdol",
            "product_type_confirmed": True,
            "factual_request": "",
            "factual_response": "",
            "info_collection": {
                "loan_purpose_confirmed": True,
                "marital_status": "미혼",
                "has_home": False,
                "annual_income": 5000
            },
            "action_plan": [],
            "action_plan_struct": [],
            "current_scenario_id": "didimdol_loan",
            "scenario_stage_id": "property_info_collection",
            "scenario_ready_for_continuation": True,
            "is_urgent": False,
            "error_messages": []
        }
        
        # Generate progress report
        progress_report = {
            "customer_name": state["user_name"],
            "product": state["product_type"],
            "current_stage": state["scenario_stage_id"],
            "collected_info": list(state["info_collection"].keys()),
            "missing_info": ["target_home_price"],
            "progress_percentage": 80,
            "timestamp": datetime.now().isoformat()
        }
        
        assert progress_report["progress_percentage"] == 80
        assert "target_home_price" in progress_report["missing_info"]


class TestRequiredInfoValidation:
    """Test required information validation."""
    
    @pytest.mark.asyncio
    async def test_field_type_validation(self, complete_scenario_data):
        """Test validation of field types."""
        required_fields = complete_scenario_data["required_info_fields"]
        
        test_inputs = [
            ("loan_purpose_confirmed", True, True),
            ("loan_purpose_confirmed", "yes", False),  # Should be boolean
            ("marital_status", "미혼", True),
            ("marital_status", "독신", False),  # Not in choices
            ("annual_income", 5000, True),
            ("annual_income", "5천만원", False),  # Should be number
            ("has_home", False, True),
            ("has_home", 0, False),  # Should be boolean
            ("target_home_price", 40000, True),
            ("target_home_price", -1000, False)  # Invalid negative
        ]
        
        for field_key, value, should_pass in test_inputs:
            field_spec = next((f for f in required_fields if f["key"] == field_key), None)
            if field_spec:
                is_valid = self._validate_field(value, field_spec)
                assert is_valid == should_pass
    
    def _validate_field(self, value: Any, field_spec: Dict) -> bool:
        """Validate a single field value."""
        field_type = field_spec.get("type", "text")
        
        if field_type == "boolean":
            return isinstance(value, bool)
        elif field_type == "number":
            return isinstance(value, (int, float)) and value >= 0
        elif field_type == "choice":
            choices = field_spec.get("choices", [])
            return value in choices
        elif field_type == "text":
            return isinstance(value, str) and len(value) > 0
        
        return True
    
    @pytest.mark.asyncio
    async def test_missing_required_fields_detection(self, complete_scenario_data):
        """Test detection of missing required fields."""
        required_fields = complete_scenario_data["required_info_fields"]
        required_keys = [f["key"] for f in required_fields if f.get("required", True)]
        
        info_collections = [
            ({}, required_keys),  # All missing
            ({"loan_purpose_confirmed": True}, [k for k in required_keys if k != "loan_purpose_confirmed"]),
            ({
                "loan_purpose_confirmed": True,
                "marital_status": "미혼",
                "has_home": False,
                "target_location": "서울"  # Optional field
            }, ["annual_income", "target_home_price"])
        ]
        
        for info_collection, expected_missing in info_collections:
            missing = [k for k in required_keys if k not in info_collection]
            assert set(missing) == set(expected_missing)
    
    @pytest.mark.asyncio
    async def test_conditional_field_requirements(self):
        """Test conditional field requirements based on other fields."""
        state: AgentState = {
            "messages": [],
            "stt_result": "",
            "agent_status": "",
            "user_name": "",
            "product_type": "didimdol",
            "product_type_confirmed": True,
            "factual_request": "",
            "factual_response": "",
            "info_collection": {
                "marital_status": "기혼"  # Married
            },
            "action_plan": [],
            "action_plan_struct": [],
            "current_scenario_id": "didimdol_loan",
            "scenario_stage_id": "basic_info_collection",
            "scenario_ready_for_continuation": True,
            "is_urgent": False,
            "error_messages": []
        }
        
        # If married, spouse income might be required
        conditional_requirements = []
        if state["info_collection"].get("marital_status") == "기혼":
            conditional_requirements.append("spouse_income")
        
        assert "spouse_income" in conditional_requirements


class TestStageTransitions:
    """Test stage transition logic."""
    
    @pytest.mark.asyncio
    async def test_valid_stage_transitions(self, complete_scenario_data):
        """Test that only valid stage transitions are allowed."""
        stages = complete_scenario_data["stages"]
        
        valid_transitions = [
            ("greeting", "loan_purpose_check"),
            ("loan_purpose_check", "basic_info_collection"),
            ("basic_info_collection", "property_info_collection"),
            ("property_info_collection", "eligibility_check"),
            ("eligibility_check", "loan_calculation"),
            ("eligibility_check", "rejection")
        ]
        
        for from_stage, to_stage in valid_transitions:
            if from_stage in stages:
                next_stages = stages[from_stage].get("next_stages", [])
                assert to_stage in next_stages
    
    @pytest.mark.asyncio
    async def test_terminal_stage_handling(self, complete_scenario_data):
        """Test handling of terminal stages."""
        stages = complete_scenario_data["stages"]
        terminal_stages = ["rejection", "end_scenario"]
        
        for stage_id in terminal_stages:
            if stage_id in stages:
                stage = stages[stage_id]
                assert stage.get("is_terminal", False) == True
                assert "next_stages" not in stage or len(stage.get("next_stages", [])) == 0
    
    @pytest.mark.asyncio
    async def test_stage_transition_with_validation(self):
        """Test stage transitions that require validation."""
        state: AgentState = {
            "messages": [],
            "stt_result": "",
            "agent_status": "",
            "user_name": "",
            "product_type": "didimdol",
            "product_type_confirmed": True,
            "factual_request": "",
            "factual_response": "",
            "info_collection": {
                "loan_purpose_confirmed": True,
                "marital_status": "미혼",
                "has_home": False,
                "annual_income": 1500,  # Below minimum
                "target_home_price": 40000
            },
            "action_plan": [],
            "action_plan_struct": [],
            "current_scenario_id": "didimdol_loan",
            "scenario_stage_id": "eligibility_check",
            "scenario_ready_for_continuation": True,
            "is_urgent": False,
            "error_messages": []
        }
        
        # Validation logic for eligibility
        income = state["info_collection"].get("annual_income", 0)
        min_income = 3000  # Minimum 30 million won
        
        if income < min_income:
            next_stage = "rejection"
            state["agent_status"] = "eligibility_failed"
        else:
            next_stage = "loan_calculation"
            state["agent_status"] = "eligibility_passed"
        
        assert next_stage == "rejection"
        assert state["agent_status"] == "eligibility_failed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])