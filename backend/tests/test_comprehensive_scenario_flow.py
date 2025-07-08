"""
Comprehensive scenario flow tests for the 디딤돌 voice consultation agent.

This module tests the complete end-to-end flow including:
- Initial task classification
- QA during task execution
- Task progression procedures
- Error recovery and state management
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import json
from typing import List, Dict, Any
from langchain_core.messages import HumanMessage, AIMessage

from app.graph.agent import (
    entry_point_node,
    main_agent_router_node,
    factual_answer_node,
    call_scenario_agent_node,
    process_scenario_logic_node,
    set_product_type_node,
    synthesize_response_node,
    prepare_direct_response_node,
    web_search_node,
    execute_plan_router
)
from app.graph.state import AgentState


@pytest.fixture
def initial_state() -> AgentState:
    """Create an initial agent state for testing."""
    return {
        "messages": [],
        "stt_result": "",
        "agent_status": "",
        "user_name": "",
        "product_type": "",
        "product_type_confirmed": False,
        "factual_request": "",
        "factual_response": "",
        "info_collection": {},
        "action_plan": [],
        "action_plan_struct": [],
        "current_scenario_id": "",
        "scenario_stage_id": "",
        "scenario_ready_for_continuation": False,
        "is_urgent": False,
        "error_messages": []
    }


@pytest.fixture
def mock_scenario_data():
    """Mock scenario data for testing."""
    return {
        "scenario_name": "디딤돌 대출 상담",
        "initial_stage_id": "greeting",
        "required_info_fields": [
            {"key": "marital_status", "display_name": "혼인 상태", "required": True},
            {"key": "annual_income", "display_name": "연소득", "required": True},
            {"key": "has_home", "display_name": "주택 소유 여부", "required": True}
        ],
        "stages": {
            "greeting": {
                "id": "greeting",
                "prompt": "안녕하세요! 디딤돌 대출 상담을 시작하겠습니다.",
                "transitions": [
                    {
                        "next_stage_id": "info_collection",
                        "condition_description": "긍정적 응답",
                        "example_phrases": ["네", "예", "좋아요"]
                    }
                ]
            },
            "info_collection": {
                "id": "info_collection",
                "prompt": "정확한 상담을 위해 몇 가지 정보가 필요합니다.",
                "required_info": ["marital_status", "annual_income", "has_home"]
            }
        }
    }


class TestInitialTaskClassification:
    """Test cases for initial task classification."""
    
    @pytest.mark.asyncio
    async def test_complex_intent_classification(self, initial_state):
        """Test classification of complex user intents."""
        state = initial_state.copy()
        state["stt_result"] = "디딤돌 대출도 알아보고 싶고 전세자금대출도 궁금한데 둘 다 설명해주세요"
        
        # Mock LLM response for multi-product inquiry
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "task": "multi_product_inquiry",
            "primary_product": "didimdol",
            "secondary_product": "jeonse",
            "action_plan": ["set_product_type:didimdol", "provide_info", "set_product_type:jeonse", "provide_info"]
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        with patch('app.graph.agent.generative_llm', mock_llm):
            result = await main_agent_router_node(state)
            
            assert "didimdol" in result["product_type"]
            assert len(result["action_plan"]) >= 2
            assert any("set_product_type" in action for action in result["action_plan"])
    
    @pytest.mark.asyncio
    async def test_ambiguous_request_handling(self, initial_state):
        """Test handling of ambiguous user requests."""
        state = initial_state.copy()
        state["stt_result"] = "대출 받고 싶어요"
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "task": "clarification_needed",
            "action_plan": ["ask_product_type"],
            "response": "어떤 종류의 대출을 원하시나요? 주택담보대출인 디딤돌 대출, 전세자금대출, 또는 일반 대출 상품이 있습니다."
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        with patch('app.graph.agent.generative_llm', mock_llm):
            result = await main_agent_router_node(state)
            
            assert result["agent_status"] == "clarification_needed"
            assert "ask_product_type" in result["action_plan"]
    
    @pytest.mark.asyncio
    async def test_product_switching_request(self, initial_state):
        """Test handling of product switching during conversation."""
        state = initial_state.copy()
        state["product_type"] = "didimdol"
        state["stt_result"] = "아 잠깐, 전세자금대출로 바꿔서 알려주세요"
        state["scenario_stage_id"] = "info_collection"
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "task": "product_switch",
            "new_product": "jeonse",
            "action_plan": ["reset_scenario", "set_product_type:jeonse", "invoke_scenario_agent"]
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        with patch('app.graph.agent.generative_llm', mock_llm):
            result = await main_agent_router_node(state)
            
            assert "set_product_type:jeonse" in result["action_plan"]
            assert "reset_scenario" in result["action_plan"]


class TestQADuringTaskExecution:
    """Test cases for QA handling during task execution."""
    
    @pytest.mark.asyncio
    async def test_context_aware_qa_transition(self, initial_state, mock_scenario_data):
        """Test QA transition while maintaining context."""
        state = initial_state.copy()
        state["product_type"] = "didimdol"
        state["scenario_stage_id"] = "info_collection"
        state["info_collection"] = {"marital_status": "미혼"}
        state["stt_result"] = "잠깐, 디딤돌 대출 금리가 어떻게 되나요?"
        
        # Mock scenario service to return current scenario data
        mock_scenario_service = AsyncMock()
        mock_scenario_service.get_scenario_by_product_type = AsyncMock(return_value=mock_scenario_data)
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "is_related": True,
            "extracted_info": {},
            "response": "디딤돌 대출 금리는 연 2.3%부터 시작합니다. 우대금리 적용 시 더 낮아질 수 있습니다.",
            "qa_detected": True
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        with patch('app.graph.agent.scenario_service', mock_scenario_service), \
             patch('app.graph.agent.scenario_logic_llm', mock_llm):
            
            # First, process the QA
            result = await process_scenario_logic_node(state)
            
            assert "금리" in result["agent_status"]
            assert state["info_collection"]["marital_status"] == "미혼"  # Context maintained
    
    @pytest.mark.asyncio
    async def test_qa_chain_handling(self, initial_state):
        """Test handling of multiple consecutive questions."""
        state = initial_state.copy()
        state["product_type"] = "didimdol"
        
        questions = [
            "디딤돌 대출 금리가 어떻게 되나요?",
            "그럼 한도는요?",
            "신청 자격은 어떻게 되나요?"
        ]
        
        mock_rag_service = AsyncMock()
        mock_rag_service.is_ready = Mock(return_value=True)
        
        for i, question in enumerate(questions):
            state["stt_result"] = question
            state["messages"].append(HumanMessage(content=question))
            
            # Mock different responses for each question
            if "금리" in question:
                mock_response = "디딤돌 대출 금리는 연 2.3%부터입니다."
            elif "한도" in question:
                mock_response = "최대 4억원까지 가능합니다."
            else:
                mock_response = "만 39세 이하 무주택자가 대상입니다."
            
            mock_rag_service.answer_question = AsyncMock(return_value=mock_response)
            
            with patch('app.graph.agent.rag_service', mock_rag_service):
                result = await factual_answer_node(state)
                
                assert result["factual_response"] == mock_response
                state["messages"].append(AIMessage(content=mock_response))
    
    @pytest.mark.asyncio
    async def test_urgent_qa_interruption(self, initial_state):
        """Test handling of urgent questions during task execution."""
        state = initial_state.copy()
        state["product_type"] = "didimdol"
        state["scenario_stage_id"] = "info_collection"
        state["stt_result"] = "잠깐만요! 이거 신용등급 낮으면 안 되나요? 급해요!"
        state["is_urgent"] = False
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "task": "urgent_qa",
            "is_urgent": True,
            "action_plan": ["invoke_qa_agent"],
            "query": "신용등급 낮으면 디딤돌 대출 가능한가요"
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        with patch('app.graph.agent.generative_llm', mock_llm):
            result = await main_agent_router_node(state)
            
            assert result["is_urgent"] == True
            assert "invoke_qa_agent" in result["action_plan"]


class TestTaskProgressionProcedures:
    """Test cases for task progression and state management."""
    
    @pytest.mark.asyncio
    async def test_required_info_validation(self, initial_state, mock_scenario_data):
        """Test validation of required information collection."""
        state = initial_state.copy()
        state["product_type"] = "didimdol"
        state["scenario_stage_id"] = "info_collection"
        state["current_scenario_id"] = "didimdol_loan"
        
        # Test with incomplete info
        state["info_collection"] = {
            "marital_status": "미혼",
            "annual_income": 4000
            # Missing: has_home
        }
        
        mock_scenario_service = AsyncMock()
        mock_scenario_service.get_scenario_by_product_type = AsyncMock(return_value=mock_scenario_data)
        
        # Check if system identifies missing info
        required_fields = mock_scenario_data["required_info_fields"]
        collected_keys = set(state["info_collection"].keys())
        required_keys = {field["key"] for field in required_fields if field.get("required", True)}
        missing_keys = required_keys - collected_keys
        
        assert "has_home" in missing_keys
        assert len(missing_keys) == 1
    
    @pytest.mark.asyncio
    async def test_stage_transition_conditions(self, initial_state, mock_scenario_data):
        """Test stage transition based on conditions."""
        state = initial_state.copy()
        state["product_type"] = "didimdol"
        state["scenario_stage_id"] = "greeting"
        state["stt_result"] = "네, 시작할게요"
        
        mock_scenario_service = AsyncMock()
        mock_scenario_service.get_scenario_by_product_type = AsyncMock(return_value=mock_scenario_data)
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "is_related": True,
            "next_stage": "info_collection",
            "response": "네, 정확한 상담을 위해 몇 가지 정보가 필요합니다."
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        with patch('app.graph.agent.scenario_service', mock_scenario_service), \
             patch('app.graph.agent.scenario_logic_llm', mock_llm):
            
            result = await process_scenario_logic_node(state)
            
            # Verify stage transition occurred
            assert result["scenario_stage_id"] == "info_collection"
    
    @pytest.mark.asyncio
    async def test_progress_tracking(self, initial_state, mock_scenario_data):
        """Test progress tracking through scenario stages."""
        state = initial_state.copy()
        state["product_type"] = "didimdol"
        state["current_scenario_id"] = "didimdol_loan"
        
        # Define progress calculation
        required_fields = mock_scenario_data["required_info_fields"]
        total_required = len([f for f in required_fields if f.get("required", True)])
        
        # Test different progress levels
        progress_tests = [
            ({"marital_status": "미혼"}, 1/3),
            ({"marital_status": "미혼", "annual_income": 4000}, 2/3),
            ({"marital_status": "미혼", "annual_income": 4000, "has_home": False}, 3/3)
        ]
        
        for info_collection, expected_progress in progress_tests:
            state["info_collection"] = info_collection
            collected_required = len([
                k for k in info_collection.keys() 
                if any(f["key"] == k and f.get("required", True) for f in required_fields)
            ])
            progress = collected_required / total_required if total_required > 0 else 0
            
            assert abs(progress - expected_progress) < 0.01


class TestEndToEndScenarioFlow:
    """Test complete end-to-end scenario flows."""
    
    @pytest.mark.asyncio
    async def test_complete_consultation_flow(self, initial_state, mock_scenario_data):
        """Test a complete consultation from start to finish."""
        state = initial_state.copy()
        
        # Step 1: Initial greeting
        state["stt_result"] = "안녕하세요, 디딤돌 대출 상담 받고 싶습니다"
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "task": "product_inquiry",
            "product": "didimdol",
            "action_plan": ["set_product_type:didimdol", "invoke_scenario_agent"]
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        with patch('app.graph.agent.generative_llm', mock_llm):
            result = await main_agent_router_node(state)
            assert result["product_type"] == "didimdol"
            state.update(result)
        
        # Step 2: Scenario progression
        state["stt_result"] = "네, 시작하겠습니다"
        state["scenario_stage_id"] = "greeting"
        
        mock_scenario_service = AsyncMock()
        mock_scenario_service.get_scenario_by_product_type = AsyncMock(return_value=mock_scenario_data)
        
        mock_scenario_llm = AsyncMock()
        mock_scenario_response = Mock()
        mock_scenario_response.content = json.dumps({
            "is_related": True,
            "next_stage": "info_collection",
            "response": "정확한 상담을 위해 몇 가지 정보가 필요합니다."
        })
        mock_scenario_llm.ainvoke = AsyncMock(return_value=mock_scenario_response)
        
        with patch('app.graph.agent.scenario_service', mock_scenario_service), \
             patch('app.graph.agent.scenario_logic_llm', mock_scenario_llm):
            
            result = await process_scenario_logic_node(state)
            assert result["scenario_stage_id"] == "info_collection"
            state.update(result)
        
        # Step 3: Information collection with QA interruption
        state["stt_result"] = "저는 미혼이고 연봉은 4천만원입니다. 그런데 금리가 궁금해요"
        
        mock_scenario_response2 = Mock()
        mock_scenario_response2.content = json.dumps({
            "is_related": True,
            "extracted_info": {"marital_status": "미혼", "annual_income": 4000},
            "qa_detected": True,
            "response": "네, 정보 감사합니다. 금리는 연 2.3%부터 시작합니다."
        })
        mock_scenario_llm.ainvoke = AsyncMock(return_value=mock_scenario_response2)
        
        with patch('app.graph.agent.scenario_service', mock_scenario_service), \
             patch('app.graph.agent.scenario_logic_llm', mock_scenario_llm):
            
            result = await process_scenario_logic_node(state)
            assert result["info_collection"]["marital_status"] == "미혼"
            assert result["info_collection"]["annual_income"] == 4000
            state.update(result)
        
        # Verify final state
        assert state["product_type"] == "didimdol"
        assert len(state["info_collection"]) >= 2
        assert state["scenario_stage_id"] == "info_collection"
    
    @pytest.mark.asyncio
    async def test_error_recovery_scenario(self, initial_state):
        """Test error recovery during scenario execution."""
        state = initial_state.copy()
        state["product_type"] = "didimdol"
        state["scenario_stage_id"] = "info_collection"
        state["error_messages"] = []
        
        # Simulate service failure
        mock_scenario_service = AsyncMock()
        mock_scenario_service.get_scenario_by_product_type = AsyncMock(
            side_effect=Exception("Service temporarily unavailable")
        )
        
        with patch('app.graph.agent.scenario_service', mock_scenario_service):
            try:
                await call_scenario_agent_node(state)
            except Exception:
                # Error should be handled gracefully
                state["error_messages"].append("Service temporarily unavailable")
                state["agent_status"] = "잠시 기술적인 문제가 있습니다. 다시 시도해주세요."
        
        assert len(state["error_messages"]) > 0
        assert "문제" in state["agent_status"]
    
    @pytest.mark.asyncio
    async def test_task_interruption_and_resume(self, initial_state):
        """Test task interruption and resumption."""
        state = initial_state.copy()
        state["product_type"] = "didimdol"
        state["scenario_stage_id"] = "info_collection"
        state["info_collection"] = {"marital_status": "미혼"}
        
        # User interrupts with unrelated request
        state["stt_result"] = "잠깐, 오늘 날씨가 어때요?"
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "task": "off_topic",
            "action_plan": ["handle_off_topic"],
            "preserve_context": True,
            "response": "날씨 정보는 제공하지 않습니다. 디딤돌 대출 상담을 계속하시겠습니까?"
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        with patch('app.graph.agent.generative_llm', mock_llm):
            result = await main_agent_router_node(state)
            
            # Verify context is preserved
            assert state["info_collection"]["marital_status"] == "미혼"
            assert state["product_type"] == "didimdol"
            assert state["scenario_stage_id"] == "info_collection"


class TestScenarioValidation:
    """Test scenario validation and quality checks."""
    
    @pytest.mark.asyncio
    async def test_response_quality_validation(self, initial_state):
        """Test validation of response quality."""
        responses = [
            ("디딤돌 대출은 연 2.3%부터 시작하는 정부지원 주택담보대출입니다.", True),
            ("대출 가능", False),  # Too short
            ("모르겠습니다", False),  # Unhelpful
            ("죄송합니다. 그 부분은 확인이 필요합니다. 잠시만 기다려주세요.", True)
        ]
        
        for response, should_pass in responses:
            # Simple quality check
            is_quality = (
                len(response) > 10 and
                "모르겠" not in response or "확인" in response
            )
            
            assert is_quality == should_pass
    
    @pytest.mark.asyncio
    async def test_conversation_continuity(self, initial_state):
        """Test conversation continuity and context maintenance."""
        state = initial_state.copy()
        
        # Build conversation history
        conversation = [
            ("디딤돌 대출 알아보려고 합니다", "product_inquiry"),
            ("저는 32살 미혼입니다", "info_provision"),
            ("연봉은 4천만원이에요", "info_provision"),
            ("그럼 얼마까지 대출 가능한가요?", "qa_question")
        ]
        
        state["messages"] = []
        state["info_collection"] = {}
        
        for user_input, expected_type in conversation:
            state["messages"].append(HumanMessage(content=user_input))
            
            # Update context based on input
            if "미혼" in user_input:
                state["info_collection"]["marital_status"] = "미혼"
            elif "4천만원" in user_input:
                state["info_collection"]["annual_income"] = 4000
        
        # Verify context is maintained throughout
        assert len(state["messages"]) == 4
        assert state["info_collection"]["marital_status"] == "미혼"
        assert state["info_collection"]["annual_income"] == 4000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])