import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
import json

from backend.app.graph.agent import run_agent_streaming
from backend.app.graph.state import AgentState
from langchain_core.messages import HumanMessage, AIMessage


class TestAgentIntegrationFlows:
    """Integration tests for complete agent conversation flows."""

    @pytest.mark.asyncio
    async def test_new_user_didimdol_inquiry_flow(self, test_environment, complete_scenario_data, mock_knowledge_base_data):
        """Test complete flow for new user inquiring about 디딤돌 대출."""
        
        # Mock all required services
        mock_rag_service = Mock()
        mock_rag_service.is_ready.return_value = True
        mock_rag_service.answer_question = AsyncMock()
        
        mock_web_search_service = Mock()
        mock_web_search_service.asearch = AsyncMock()
        
        # Setup prompts
        mock_prompts = {
            "main_agent": {
                "initial_task_selection_prompt": """
사용자 입력: {user_input}
사용 가능한 상품 유형: {available_product_types_list}

다음 중 하나를 선택하세요:
{format_instructions}
""",
                "router_prompt": """
사용자 입력: {user_input}
현재 활성 시나리오: {active_scenario_name}

{format_instructions}
""",
                "determine_next_scenario_stage": """
현재 스테이지: {current_stage_id}
사용자 입력: {user_input}

다음 스테이지를 결정하세요:
{format_instructions}
"""
            },
            "qa_agent": {
                "rag_query_expansion_prompt": """
시나리오: {scenario_name}
사용자 질문: {user_question}

확장된 질문들을 생성하세요.
""",
                "simple_chitchat_prompt": """
사용자 입력: {user_input}

친근한 대화 응답을 생성하세요.
"""
            }
        }
        
        # Mock LLM responses for different stages
        def mock_llm_response(content):
            response = Mock()
            response.content = content
            return response
        
        mock_json_llm = AsyncMock()
        mock_generative_llm = AsyncMock()
        
        # Response for initial task selection (choose didimdol)
        initial_response = json.dumps({
            "actions": [{"tool": "set_product_type", "tool_input": {"product_id": "didimdol"}}]
        })
        
        # Response for subsequent QA
        qa_response = "디딤돌 대출은 청년층을 위한 정부 지원 대출 상품입니다. 연 2.5%의 저금리를 제공합니다."
        
        mock_json_llm.ainvoke.side_effect = [
            mock_llm_response(initial_response)
        ]
        
        mock_generative_llm.ainvoke.return_value = mock_llm_response(qa_response)
        mock_rag_service.answer_question.return_value = qa_response
        
        # Mock parsers
        from backend.app.graph.models import InitialTaskDecisionModel, ActionModel
        
        mock_decision = InitialTaskDecisionModel(
            actions=[ActionModel(tool="set_product_type", tool_input={"product_id": "didimdol"})]
        )
        
        with patch('backend.app.graph.agent.ALL_PROMPTS', mock_prompts), \
             patch('backend.app.graph.agent.ALL_SCENARIOS_DATA', complete_scenario_data), \
             patch('backend.app.graph.agent.json_llm', mock_json_llm), \
             patch('backend.app.graph.agent.generative_llm', mock_generative_llm), \
             patch('backend.app.graph.agent.rag_service', mock_rag_service), \
             patch('backend.app.graph.agent.web_search_service', mock_web_search_service), \
             patch('backend.app.graph.agent.initial_task_decision_parser') as mock_parser:
            
            mock_parser.parse.return_value = mock_decision
            mock_parser.get_format_instructions.return_value = "format instructions"
            
            # Start conversation
            responses = []
            async for response in run_agent_streaming(
                user_input_text="디딤돌 대출에 대해 알려주세요",
                session_id="test_new_user_flow"
            ):
                responses.append(response)
            
            # Verify flow
            assert len(responses) > 0
            
            # Check that we got a final state
            final_state = None
            for response in responses:
                if isinstance(response, dict) and response.get("type") == "final_state":
                    final_state = response["data"]
                    break
            
            assert final_state is not None
            assert final_state["current_product_type"] == "didimdol"
            assert final_state["is_final_turn_response"] is True

    @pytest.mark.asyncio
    async def test_multi_turn_qa_conversation(self, test_environment, complete_scenario_data, mock_knowledge_base_data):
        """Test multi-turn QA conversation with context preservation."""
        
        mock_rag_service = Mock()
        mock_rag_service.is_ready.return_value = True
        
        # Different responses for different questions
        qa_responses = [
            "디딤돌 대출의 기본 금리는 연 2.5%입니다.",
            "우대금리는 소득 수준에 따라 최대 0.5% 할인이 가능합니다.",
            "신청 방법은 온라인, 영업점 방문, 전화 신청이 있습니다."
        ]
        
        mock_rag_service.answer_question = AsyncMock(side_effect=qa_responses)
        
        mock_prompts = {
            "main_agent": {
                "router_prompt": """
사용자 입력: {user_input}
현재 시나리오: {active_scenario_name}
채팅 기록: {formatted_messages_history}

{format_instructions}
"""
            },
            "qa_agent": {
                "rag_query_expansion_prompt": """
질문: {user_question}
기록: {chat_history}

확장 질문을 생성하세요.
"""
            }
        }
        
        # Simulate multi-turn conversation
        conversation_state = {
            "messages": [
                HumanMessage(content="디딤돌 대출을 선택했어요"),
                AIMessage(content="디딤돌 대출 상담을 시작하겠습니다.")
            ],
            "current_product_type": "didimdol",
            "current_scenario_stage_id": "welcome",
            "collected_product_info": {}
        }
        
        questions = [
            "금리가 얼마인가요?",
            "우대금리는 어떻게 받나요?",
            "신청은 어떻게 하나요?"
        ]
        
        with patch('backend.app.graph.agent.ALL_PROMPTS', mock_prompts), \
             patch('backend.app.graph.agent.ALL_SCENARIOS_DATA', complete_scenario_data), \
             patch('backend.app.graph.agent.rag_service', mock_rag_service):
            
            for i, question in enumerate(questions):
                responses = []
                async for response in run_agent_streaming(
                    user_input_text=question,
                    session_id=f"test_multi_turn_{i}",
                    current_state_dict=conversation_state
                ):
                    responses.append(response)
                
                # Update conversation state for next turn
                final_state = None
                for response in responses:
                    if isinstance(response, dict) and response.get("type") == "final_state":
                        final_state = response["data"]
                        break
                
                if final_state:
                    conversation_state["messages"] = final_state["messages"]
                    
                # Verify response contains relevant information
                text_responses = [r for r in responses if isinstance(r, str)]
                full_response = "".join(text_responses)
                
                if i == 0:  # First question about interest rate
                    assert "금리" in full_response or "2.5%" in full_response
                elif i == 1:  # Second question about preferential rate
                    assert "우대" in full_response or "할인" in full_response
                elif i == 2:  # Third question about application
                    assert "신청" in full_response

    @pytest.mark.asyncio
    async def test_scenario_progression_flow(self, test_environment, complete_scenario_data):
        """Test complete scenario progression from start to finish."""
        
        mock_rag_service = Mock()
        mock_rag_service.is_ready.return_value = True
        mock_rag_service.answer_question = AsyncMock(return_value="디딤돌 대출 정보입니다.")
        
        mock_prompts = {
            "main_agent": {
                "router_prompt": """
사용자: {user_input}
시나리오: {active_scenario_name}
현재 단계: {current_scenario_stage_id}

{format_instructions}
""",
                "determine_next_scenario_stage": """
현재: {current_stage_id}
입력: {user_input}
정보: {collected_product_info}

{format_instructions}
"""
            }
        }
        
        # Mock scenario agent output
        mock_scenario_output = {
            "intent": "inquiry_interest_rate",
            "is_scenario_related": True,
            "entities": {"inquiry_type": "금리 문의"}
        }
        
        # Mock stage transition decision
        from backend.app.graph.models import NextStageDecisionModel
        mock_next_stage = NextStageDecisionModel(chosen_next_stage_id="interest_rate_info")
        
        mock_json_llm = AsyncMock()
        mock_json_llm.ainvoke.return_value = Mock(content='{"chosen_next_stage_id": "interest_rate_info"}')
        
        with patch('backend.app.graph.agent.ALL_PROMPTS', mock_prompts), \
             patch('backend.app.graph.agent.ALL_SCENARIOS_DATA', complete_scenario_data), \
             patch('backend.app.graph.agent.rag_service', mock_rag_service), \
             patch('backend.app.graph.agent.invoke_scenario_agent_logic', return_value=mock_scenario_output), \
             patch('backend.app.graph.agent.json_llm', mock_json_llm), \
             patch('backend.app.graph.agent.next_stage_decision_parser') as mock_parser:
            
            mock_parser.parse.return_value = mock_next_stage
            
            # Start with product already selected
            initial_state = {
                "messages": [],
                "current_product_type": "didimdol",
                "current_scenario_stage_id": "welcome",
                "collected_product_info": {}
            }
            
            responses = []
            async for response in run_agent_streaming(
                user_input_text="금리가 궁금해요",
                session_id="test_scenario_progression",
                current_state_dict=initial_state
            ):
                responses.append(response)
            
            # Verify scenario progression
            final_state = None
            for response in responses:
                if isinstance(response, dict) and response.get("type") == "final_state":
                    final_state = response["data"]
                    break
            
            assert final_state is not None
            assert final_state["current_scenario_stage_id"] == "interest_rate_info"
            assert "inquiry_type" in final_state["collected_product_info"]

    @pytest.mark.asyncio
    async def test_web_search_integration(self, test_environment, mock_web_search_results):
        """Test web search integration for out-of-domain queries."""
        
        mock_web_search_service = Mock()
        mock_web_search_service.asearch = AsyncMock(return_value="최신 대출 정보를 검색했습니다.")
        
        mock_prompts = {
            "main_agent": {
                "router_prompt": """
사용자 입력: {user_input}

{format_instructions}
"""
            }
        }
        
        # Mock decision to use web search
        from backend.app.graph.models import MainRouterDecisionModel, ActionModel
        mock_decision = MainRouterDecision(
            actions=[ActionModel(tool="invoke_web_search", tool_input={"query": "최신 대출 정보"})]
        )
        
        mock_json_llm = AsyncMock()
        mock_json_llm.ainvoke.return_value = Mock(content='{"actions": [{"tool": "invoke_web_search", "tool_input": {"query": "최신 대출 정보"}}]}')
        
        mock_generative_llm = AsyncMock()
        mock_generative_llm.ainvoke.return_value = Mock(content="웹 검색으로 찾은 최신 정보를 정리해드렸습니다.")
        
        with patch('backend.app.graph.agent.ALL_PROMPTS', mock_prompts), \
             patch('backend.app.graph.agent.web_search_service', mock_web_search_service), \
             patch('backend.app.graph.agent.json_llm', mock_json_llm), \
             patch('backend.app.graph.agent.generative_llm', mock_generative_llm), \
             patch('backend.app.graph.agent.main_router_decision_parser') as mock_parser:
            
            mock_parser.parse.return_value = mock_decision
            mock_parser.get_format_instructions.return_value = "format instructions"
            
            responses = []
            async for response in run_agent_streaming(
                user_input_text="2024년 최신 대출 정책이 궁금해요",
                session_id="test_web_search"
            ):
                responses.append(response)
            
            # Verify web search was used
            mock_web_search_service.asearch.assert_called_once()
            
            # Verify response contains search results
            text_responses = [r for r in responses if isinstance(r, str)]
            full_response = "".join(text_responses)
            assert len(full_response) > 0

    @pytest.mark.asyncio
    async def test_error_handling_and_recovery(self, test_environment):
        """Test error handling and recovery mechanisms."""
        
        # Mock services that will fail
        mock_rag_service = Mock()
        mock_rag_service.is_ready.return_value = False
        
        mock_prompts = {
            "main_agent": {
                "router_prompt": """
사용자 입력: {user_input}

{format_instructions}
"""
            }
        }
        
        with patch('backend.app.graph.agent.ALL_PROMPTS', mock_prompts), \
             patch('backend.app.graph.agent.rag_service', mock_rag_service):
            
            responses = []
            async for response in run_agent_streaming(
                user_input_text="디딤돌 대출 정보를 알려주세요",
                session_id="test_error_handling"
            ):
                responses.append(response)
            
            # Should handle error gracefully
            error_response = None
            for response in responses:
                if isinstance(response, dict) and response.get("type") == "error":
                    error_response = response
                    break
            
            # Should get some kind of response even with service failures
            assert len(responses) > 0

    @pytest.mark.asyncio
    async def test_conversation_state_persistence(self, test_environment, complete_scenario_data):
        """Test that conversation state is properly maintained across turns."""
        
        mock_rag_service = Mock()
        mock_rag_service.is_ready.return_value = True
        mock_rag_service.answer_question = AsyncMock(return_value="답변입니다.")
        
        # Initial conversation state
        initial_state = {
            "messages": [
                HumanMessage(content="디딤돌 대출을 선택했어요"),
                AIMessage(content="디딤돌 대출 상담을 시작하겠습니다.")
            ],
            "current_product_type": "didimdol",
            "current_scenario_stage_id": "welcome",
            "collected_product_info": {"inquiry_type": "금리 문의"}
        }
        
        with patch('backend.app.graph.agent.ALL_SCENARIOS_DATA', complete_scenario_data), \
             patch('backend.app.graph.agent.rag_service', mock_rag_service):
            
            responses = []
            async for response in run_agent_streaming(
                user_input_text="추가 질문이 있어요",
                session_id="test_state_persistence",
                current_state_dict=initial_state
            ):
                responses.append(response)
            
            # Get final state
            final_state = None
            for response in responses:
                if isinstance(response, dict) and response.get("type") == "final_state":
                    final_state = response["data"]
                    break
            
            assert final_state is not None
            
            # Verify state persistence
            assert final_state["current_product_type"] == "didimdol"
            assert final_state["current_scenario_stage_id"] == "welcome"
            assert "inquiry_type" in final_state["collected_product_info"]
            
            # Verify message history is maintained
            assert len(final_state["messages"]) > len(initial_state["messages"])
            
            # Previous messages should be preserved
            for i, original_msg in enumerate(initial_state["messages"]):
                assert final_state["messages"][i].content == original_msg.content