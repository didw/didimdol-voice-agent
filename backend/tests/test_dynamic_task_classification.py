"""
Dynamic task classification and QA handling tests for the 디딤돌 voice consultation agent.

This module tests:
- Complex intent classification
- Dynamic QA during task execution
- Context-aware task switching
- Multi-intent handling
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
import json
from typing import List, Dict, Any
from langchain_core.messages import HumanMessage, AIMessage

from app.graph.state import AgentState
from app.graph.agent import (
    main_agent_router_node,
    factual_answer_node,
    process_scenario_logic_node,
    prepare_direct_response_node
)


@pytest.fixture
def base_state() -> AgentState:
    """Base state for testing."""
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


class TestComplexIntentClassification:
    """Test complex intent classification scenarios."""
    
    @pytest.mark.asyncio
    async def test_multi_product_comparison_intent(self, base_state):
        """Test classification of multi-product comparison requests."""
        test_cases = [
            {
                "input": "디딤돌 대출이랑 전세자금대출 중에 뭐가 더 나은가요?",
                "expected_task": "product_comparison",
                "expected_products": ["didimdol", "jeonse"],
                "expected_actions": ["compare_products", "provide_recommendation"]
            },
            {
                "input": "주택 구매용 대출이랑 전세 대출 둘 다 가능한가요? 각각 얼마까지 되나요?",
                "expected_task": "multi_product_inquiry",
                "expected_products": ["didimdol", "jeonse"],
                "expected_actions": ["check_eligibility", "provide_limits"]
            },
            {
                "input": "저는 청약통장도 있고 전세도 살아봤는데 어떤 대출이 맞을까요?",
                "expected_task": "product_recommendation",
                "expected_context": ["has_subscription_account", "has_jeonse_experience"],
                "expected_actions": ["analyze_customer_profile", "recommend_product"]
            }
        ]
        
        for test_case in test_cases:
            state = base_state.copy()
            state["stt_result"] = test_case["input"]
            
            mock_llm = AsyncMock()
            mock_response = Mock()
            mock_response.content = json.dumps({
                "task": test_case["expected_task"],
                "products": test_case.get("expected_products", []),
                "context": test_case.get("expected_context", []),
                "action_plan": test_case["expected_actions"]
            })
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            
            with patch('app.graph.agent.generative_llm', mock_llm):
                result = await main_agent_router_node(state)
                
                assert result["agent_status"] == test_case["expected_task"]
                assert any(action in result["action_plan"] for action in test_case["expected_actions"])
    
    @pytest.mark.asyncio
    async def test_implicit_intent_detection(self, base_state):
        """Test detection of implicit intents from user input."""
        test_cases = [
            {
                "input": "저 내년에 결혼하는데 집 사려구요",
                "implicit_intents": ["wedding_planned", "home_purchase"],
                "recommended_product": "didimdol",
                "additional_info": {"marital_status": "예비부부"}
            },
            {
                "input": "월세 너무 비싸서 전세로 옮기고 싶어요",
                "implicit_intents": ["reduce_housing_cost", "jeonse_transition"],
                "recommended_product": "jeonse",
                "additional_context": "cost_sensitive"
            },
            {
                "input": "부모님이 집 사라고 하시는데 제가 조건이 되나요?",
                "implicit_intents": ["parental_advice", "eligibility_check"],
                "required_action": "check_eligibility_first"
            }
        ]
        
        for test_case in test_cases:
            state = base_state.copy()
            state["stt_result"] = test_case["input"]
            
            mock_llm = AsyncMock()
            mock_response = Mock()
            mock_response.content = json.dumps({
                "implicit_intents": test_case["implicit_intents"],
                "recommended_product": test_case.get("recommended_product", ""),
                "additional_info": test_case.get("additional_info", {}),
                "action_plan": ["analyze_intent", "set_product_type", "invoke_scenario_agent"]
            })
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            
            with patch('app.graph.agent.generative_llm', mock_llm):
                result = await main_agent_router_node(state)
                
                # Verify implicit intent was detected
                assert len(result["action_plan"]) > 0
    
    @pytest.mark.asyncio
    async def test_sequential_intent_handling(self, base_state):
        """Test handling of sequential intents in single input."""
        state = base_state.copy()
        state["stt_result"] = "먼저 제가 대출 자격이 되는지 확인하고, 된다면 금리랑 한도 알려주세요"
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "task": "sequential_inquiry",
            "intents": [
                {"type": "eligibility_check", "priority": 1},
                {"type": "rate_inquiry", "priority": 2},
                {"type": "limit_inquiry", "priority": 2}
            ],
            "action_plan": [
                "check_eligibility",
                "conditional:if_eligible",
                "provide_rate_info",
                "provide_limit_info"
            ]
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        with patch('app.graph.agent.generative_llm', mock_llm):
            result = await main_agent_router_node(state)
            
            # Verify sequential handling
            assert "check_eligibility" in result["action_plan"]
            assert result["action_plan"].index("check_eligibility") < len(result["action_plan"]) - 1


class TestDynamicQAHandling:
    """Test dynamic QA handling during task execution."""
    
    @pytest.mark.asyncio
    async def test_contextual_qa_interruption(self, base_state):
        """Test QA interruption that maintains context."""
        state = base_state.copy()
        state["product_type"] = "didimdol"
        state["scenario_stage_id"] = "info_collection"
        state["info_collection"] = {
            "marital_status": "미혼",
            "annual_income": 5000
        }
        
        # User asks a question mid-collection
        state["stt_result"] = "잠깐, 신용등급이 낮으면 금리가 많이 올라가나요?"
        
        mock_scenario_service = AsyncMock()
        mock_scenario_data = {
            "qa_keywords": ["궁금", "질문", "어떻게", "얼마나"],
            "stages": {
                "info_collection": {
                    "id": "info_collection",
                    "required_info": ["marital_status", "annual_income", "has_home"]
                }
            }
        }
        mock_scenario_service.get_scenario_by_product_type = AsyncMock(return_value=mock_scenario_data)
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "is_related": True,
            "qa_detected": True,
            "qa_response": "신용등급에 따라 금리가 달라질 수 있습니다. 1-2등급은 우대금리를 받을 수 있고, 낮은 등급은 추가 금리가 붙을 수 있습니다.",
            "preserve_context": True,
            "return_to_collection": True
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        with patch('app.graph.agent.scenario_service', mock_scenario_service), \
             patch('app.graph.agent.scenario_logic_llm', mock_llm):
            
            result = await process_scenario_logic_node(state)
            
            # Verify context is preserved
            assert result["info_collection"]["marital_status"] == "미혼"
            assert result["info_collection"]["annual_income"] == 5000
            assert result["scenario_stage_id"] == "info_collection"  # Same stage
    
    @pytest.mark.asyncio
    async def test_qa_priority_handling(self, base_state):
        """Test handling of different QA priorities."""
        qa_scenarios = [
            {
                "input": "지금 당장 대출 받을 수 있나요? 급해요!",
                "priority": "urgent",
                "expected_handling": "immediate_response"
            },
            {
                "input": "나중에 궁금한 거 있으면 물어봐도 되나요?",
                "priority": "low",
                "expected_handling": "acknowledge_and_continue"
            },
            {
                "input": "이 정보는 꼭 알아야 하나요? 개인정보 같은데...",
                "priority": "medium",
                "expected_handling": "explain_and_reassure"
            }
        ]
        
        for scenario in qa_scenarios:
            state = base_state.copy()
            state["stt_result"] = scenario["input"]
            state["scenario_stage_id"] = "info_collection"
            
            mock_llm = AsyncMock()
            mock_response = Mock()
            mock_response.content = json.dumps({
                "qa_priority": scenario["priority"],
                "handling_type": scenario["expected_handling"],
                "response": "적절한 응답",
                "continue_scenario": scenario["priority"] != "urgent"
            })
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            
            with patch('app.graph.agent.generative_llm', mock_llm):
                result = await main_agent_router_node(state)
                
                if scenario["priority"] == "urgent":
                    assert result["is_urgent"] == True
    
    @pytest.mark.asyncio
    async def test_multi_turn_qa_session(self, base_state):
        """Test multi-turn QA session handling."""
        state = base_state.copy()
        state["product_type"] = "didimdol"
        
        qa_sequence = [
            ("디딤돌 대출이 뭐예요?", "basic_info"),
            ("그럼 금리는요?", "follow_up_rate"),
            ("한도는 얼마까지?", "follow_up_limit"),
            ("제가 받을 수 있나요?", "eligibility_check")
        ]
        
        for question, qa_type in qa_sequence:
            state["stt_result"] = question
            state["messages"].append(HumanMessage(content=question))
            
            # Track QA context
            qa_context = [msg.content for msg in state["messages"] if isinstance(msg, HumanMessage)]
            
            mock_rag_service = AsyncMock()
            mock_rag_service.is_ready = Mock(return_value=True)
            
            # Generate contextual response
            if qa_type == "follow_up_rate":
                response = "디딤돌 대출 금리는 연 2.3%부터 시작합니다."
            elif qa_type == "follow_up_limit":
                response = "소득과 주택가격에 따라 최대 4억원까지 가능합니다."
            elif qa_type == "eligibility_check":
                response = "만 39세 이하 무주택자이시면 신청 가능합니다."
            else:
                response = "디딤돌 대출은 청년층을 위한 정부지원 주택담보대출입니다."
            
            mock_rag_service.answer_question = AsyncMock(return_value=response)
            
            with patch('app.graph.agent.rag_service', mock_rag_service):
                result = await factual_answer_node(state)
                
                state["messages"].append(AIMessage(content=result["factual_response"]))
                
                # Verify contextual understanding
                assert len(state["messages"]) == (qa_sequence.index((question, qa_type)) + 1) * 2


class TestContextAwareTaskSwitching:
    """Test context-aware task switching."""
    
    @pytest.mark.asyncio
    async def test_smooth_product_transition(self, base_state):
        """Test smooth transition between products."""
        state = base_state.copy()
        
        # Start with didimdol
        state["product_type"] = "didimdol"
        state["info_collection"] = {"annual_income": 5000}
        state["stt_result"] = "아, 그런데 전세자금대출도 같이 알아볼 수 있나요?"
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "task": "add_product_inquiry",
            "current_product": "didimdol",
            "additional_product": "jeonse",
            "preserve_info": True,
            "action_plan": [
                "save_current_context",
                "acknowledge_multi_product",
                "continue_with_current",
                "prepare_second_product"
            ]
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        with patch('app.graph.agent.generative_llm', mock_llm):
            result = await main_agent_router_node(state)
            
            # Verify context preservation
            assert result["info_collection"]["annual_income"] == 5000
            assert "save_current_context" in result["action_plan"]
    
    @pytest.mark.asyncio
    async def test_task_priority_reordering(self, base_state):
        """Test dynamic reordering of tasks based on priority."""
        state = base_state.copy()
        state["stt_result"] = "전세자금대출 급하게 필요한데, 나중에 주택 구매도 생각 중이에요"
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "tasks_identified": [
                {"type": "jeonse_loan", "priority": "urgent"},
                {"type": "home_purchase", "priority": "future"}
            ],
            "reordered_plan": [
                "set_product_type:jeonse",
                "invoke_scenario_agent",
                "mark_for_followup:didimdol"
            ]
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        with patch('app.graph.agent.generative_llm', mock_llm):
            result = await main_agent_router_node(state)
            
            # Verify urgent task comes first
            assert result["action_plan"][0] == "set_product_type:jeonse"
    
    @pytest.mark.asyncio
    async def test_context_based_recommendations(self, base_state):
        """Test recommendations based on accumulated context."""
        state = base_state.copy()
        state["messages"] = [
            HumanMessage(content="저는 신혼부부예요"),
            AIMessage(content="신혼부부시군요. 도와드리겠습니다."),
            HumanMessage(content="연봉은 부부합산 8천만원이에요"),
            AIMessage(content="부부합산 8천만원 확인했습니다.")
        ]
        state["info_collection"] = {
            "marital_status": "기혼",
            "annual_income": 8000,
            "is_newlywed": True
        }
        state["stt_result"] = "어떤 대출이 저희한테 유리할까요?"
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "task": "personalized_recommendation",
            "customer_profile": "newlywed_high_income",
            "recommendations": [
                {
                    "product": "didimdol",
                    "reason": "신혼부부 우대금리 적용 가능",
                    "benefits": ["낮은 금리", "높은 한도"]
                }
            ],
            "action_plan": ["provide_recommendation", "explain_benefits"]
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        with patch('app.graph.agent.generative_llm', mock_llm):
            result = await main_agent_router_node(state)
            
            assert "provide_recommendation" in result["action_plan"]


class TestErrorHandlingInClassification:
    """Test error handling in task classification."""
    
    @pytest.mark.asyncio
    async def test_ambiguous_input_clarification(self, base_state):
        """Test handling of ambiguous inputs requiring clarification."""
        ambiguous_inputs = [
            "대출",
            "도와주세요",
            "음... 그거 있잖아요",
            "이자 관련해서..."
        ]
        
        for input_text in ambiguous_inputs:
            state = base_state.copy()
            state["stt_result"] = input_text
            
            mock_llm = AsyncMock()
            mock_response = Mock()
            mock_response.content = json.dumps({
                "task": "clarification_needed",
                "ambiguity_type": "insufficient_context",
                "clarification_options": [
                    "주택 구매를 위한 디딤돌 대출",
                    "전세 자금을 위한 전세자금대출",
                    "일반 상담"
                ],
                "response": "어떤 대출 상품에 대해 궁금하신가요?"
            })
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            
            with patch('app.graph.agent.generative_llm', mock_llm):
                result = await main_agent_router_node(state)
                
                assert result["agent_status"] == "clarification_needed"
    
    @pytest.mark.asyncio
    async def test_noise_filtering(self, base_state):
        """Test filtering of noise and irrelevant input."""
        noisy_inputs = [
            "음... 어... 그... 대출... 아니 잠깐만...",
            "아 뭐라고 하지... 그... 있잖아... 대출",
            "(기침소리) 죄송해요 다시..."
        ]
        
        for input_text in noisy_inputs:
            state = base_state.copy()
            state["stt_result"] = input_text
            
            mock_llm = AsyncMock()
            mock_response = Mock()
            mock_response.content = json.dumps({
                "task": "request_repeat",
                "detected_intent": "possible_loan_inquiry",
                "confidence": "low",
                "response": "죄송합니다. 다시 한 번 말씀해 주시겠어요?"
            })
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            
            with patch('app.graph.agent.generative_llm', mock_llm):
                result = await main_agent_router_node(state)
                
                assert "request_repeat" in str(result["agent_status"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])