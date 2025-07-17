import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import json

from app.graph.agent import (
    entry_point_node,
    main_agent_router_node,
    factual_answer_node,
    call_scenario_agent_node,
    process_scenario_logic_node,
    set_product_type_node,
    synthesize_response_node,
    web_search_node,
    execute_plan_router
)
from app.graph.state import AgentState
from app.graph.models import ActionModel, InitialTaskDecisionModel, MainRouterDecisionModel, NextStageDecisionModel
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage


class TestEntryPointNode:
    """Test cases for entry_point_node function."""

    @pytest.mark.asyncio
    async def test_entry_point_node_basic_functionality(self, sample_agent_state):
        """Test basic functionality of entry_point_node."""
        state = sample_agent_state.copy()
        state["user_input_text"] = "안녕하세요"
        
        with patch('app.graph.agent.ALL_SCENARIOS_DATA', {"didimdol": {"scenario_name": "test"}}), \
             patch('app.graph.agent.ALL_PROMPTS', {"main_agent": {"test": "prompt"}}):
            
            result = await entry_point_node(state)
            
            assert result["stt_result"] == "안녕하세요"
            assert len(result["messages"]) == 2  # Original + new HumanMessage
            assert isinstance(result["messages"][-1], HumanMessage)
            assert result["messages"][-1].content == "안녕하세요"

    @pytest.mark.asyncio
    async def test_entry_point_node_with_product_type(self, sample_agent_state, sample_scenario_data):
        """Test entry_point_node with existing product type."""
        state = sample_agent_state.copy()
        state["current_product_type"] = "didimdol"
        state["user_input_text"] = "금리가 궁금해요"
        
        with patch('app.graph.utils.ALL_SCENARIOS_DATA', {"didimdol": sample_scenario_data}), \
             patch('app.graph.utils.ALL_PROMPTS', {"main_agent": {"test": "prompt"}}), \
             patch('app.graph.utils.get_active_scenario_data', return_value=sample_scenario_data):
            
            result = await entry_point_node(state)
            
            assert result["current_product_type"] == "didimdol"
            assert result["active_scenario_data"] == sample_scenario_data
            assert result["active_scenario_name"] == "디딤돌 대출 상담"
            assert result["current_scenario_stage_id"] == "welcome"

    @pytest.mark.asyncio
    async def test_entry_point_node_service_failure(self, sample_agent_state):
        """Test entry_point_node when services are not initialized."""
        state = sample_agent_state.copy()
        
        with patch('app.graph.nodes.orchestrator.entry_point.ALL_SCENARIOS_DATA', None), \
             patch('app.graph.nodes.orchestrator.entry_point.ALL_PROMPTS', None):
            
            result = await entry_point_node(state)
            
            assert result["error_message"] is not None
            assert result["is_final_turn_response"] is True
            assert "Service initialization failed" in result["error_message"]


class TestMainAgentRouterNode:
    """Test cases for main_agent_router_node function."""

    @pytest.mark.asyncio
    async def test_initial_task_selection(self, sample_agent_state, mock_prompts):
        """Test main_agent_router_node for initial task selection."""
        state = sample_agent_state.copy()
        state["stt_result"] = "디딤돌 대출에 대해 알려주세요"
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = '{"actions": [{"tool": "set_product_type", "tool_input": {"product_id": "didimdol"}}]}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        mock_decision = InitialTaskDecisionModel(
            actions=[ActionModel(tool="set_product_type", tool_input={"product_id": "didimdol"})]
        )
        
        with patch('app.graph.nodes.orchestrator.main_router.ALL_PROMPTS', mock_prompts), \
             patch('app.graph.nodes.orchestrator.main_router.json_llm', mock_llm), \
             patch('app.graph.nodes.orchestrator.main_router.initial_task_decision_parser') as mock_parser:
            
            mock_parser.parse.return_value = mock_decision
            mock_parser.get_format_instructions.return_value = "format instructions"
            
            result = await main_agent_router_node(state)
            
            assert result["action_plan"] == ["set_product_type"]
            assert result["loan_selection_is_fresh"] is True
            assert len(result["messages"]) == 2  # Original + system log

    @pytest.mark.asyncio
    async def test_router_with_existing_product(self, sample_agent_state, mock_prompts, sample_scenario_data):
        """Test main_agent_router_node with existing product type."""
        state = sample_agent_state.copy()
        state["current_product_type"] = "didimdol"
        state["stt_result"] = "금리가 얼마인가요?"
        state["current_scenario_stage_id"] = "welcome"
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = '{"actions": [{"tool": "invoke_qa_agent", "tool_input": {"query": "금리"}}]}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        mock_decision = MainRouterDecisionModel(
            actions=[ActionModel(tool="invoke_qa_agent", tool_input={"query": "금리"})]
        )
        
        with patch('app.graph.nodes.orchestrator.main_router.ALL_PROMPTS', mock_prompts), \
             patch('app.graph.nodes.orchestrator.main_router.json_llm', mock_llm), \
             patch('app.graph.nodes.orchestrator.main_router.main_router_decision_parser') as mock_parser, \
             patch('app.graph.nodes.orchestrator.main_router.get_active_scenario_data', return_value=sample_scenario_data), \
             patch('app.graph.nodes.orchestrator.main_router.ALL_SCENARIOS_DATA', {"didimdol": sample_scenario_data}):
            
            mock_parser.parse.return_value = mock_decision
            mock_parser.get_format_instructions.return_value = "format instructions"
            
            result = await main_agent_router_node(state)
            
            assert result["action_plan"] == ["invoke_qa_agent"]
            assert len(result["action_plan_struct"]) == 1

    @pytest.mark.asyncio
    async def test_router_error_handling(self, sample_agent_state, mock_prompts):
        """Test main_agent_router_node error handling."""
        state = sample_agent_state.copy()
        state["stt_result"] = "test input"
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM Error"))
        
        with patch('app.graph.nodes.orchestrator.main_router.ALL_PROMPTS', mock_prompts), \
             patch('app.graph.nodes.orchestrator.main_router.json_llm', mock_llm):
            
            result = await main_agent_router_node(state)
            
            assert result["error_message"] is not None
            assert result["main_agent_routing_decision"] == "unclear_input"
            assert result["is_final_turn_response"] is True


class TestFactualAnswerNode:
    """Test cases for factual_answer_node function."""

    @pytest.mark.asyncio
    async def test_factual_answer_node_success(self, sample_agent_state, mock_rag_service, mock_prompts):
        """Test successful factual answer generation."""
        state = sample_agent_state.copy()
        state["stt_result"] = "디딤돌 대출 금리가 얼마인가요?"
        state["action_plan"] = ["invoke_qa_agent", "synthesize_response"]
        state["action_plan_struct"] = [{"tool": "invoke_qa_agent", "tool_input": {}}]
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = '{"queries": ["디딤돌 대출 금리 정보", "디딤돌 대출 우대금리"]}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        with patch('app.graph.agent.ALL_PROMPTS', mock_prompts), \
             patch('app.graph.agent.rag_service', mock_rag_service), \
             patch('app.graph.agent.json_llm', mock_llm), \
             patch('app.graph.agent.expanded_queries_parser') as mock_parser:
            
            mock_expanded_result = Mock()
            mock_expanded_result.queries = ["디딤돌 대출 금리 정보", "디딤돌 대출 우대금리"]
            mock_parser.parse.return_value = mock_expanded_result
            
            result = await factual_answer_node(state)
            
            assert result["factual_response"] == "디딤돌 대출은 청년층을 위한 정부 지원 대출입니다."
            assert len(result["action_plan"]) == 1  # One action removed
            mock_rag_service.answer_question.assert_called_once()

    @pytest.mark.asyncio
    async def test_factual_answer_node_rag_not_ready(self, sample_agent_state):
        """Test factual answer node when RAG service is not ready."""
        state = sample_agent_state.copy()
        state["stt_result"] = "디딤돌 대출 정보"
        
        mock_rag_service = Mock()
        mock_rag_service.is_ready.return_value = False
        
        with patch('app.graph.agent.rag_service', mock_rag_service):
            result = await factual_answer_node(state)
            
            assert "현재 정보 검색 기능에 문제가 발생" in result["factual_response"]

    @pytest.mark.asyncio
    async def test_factual_answer_node_rag_error(self, sample_agent_state, mock_prompts):
        """Test factual answer node when RAG service raises an error."""
        state = sample_agent_state.copy()
        state["stt_result"] = "디딤돌 대출 정보"
        
        mock_rag_service = Mock()
        mock_rag_service.is_ready.return_value = True
        mock_rag_service.answer_question = AsyncMock(side_effect=Exception("RAG Error"))
        
        with patch('app.graph.agent.rag_service', mock_rag_service), \
             patch('app.graph.agent.ALL_PROMPTS', mock_prompts):
            
            result = await factual_answer_node(state)
            
            assert "정보를 검색하는 중 오류가 발생했습니다" in result["factual_response"]


class TestWebSearchNode:
    """Test cases for web_search_node function."""

    @pytest.mark.asyncio
    async def test_web_search_node_success(self, sample_agent_state, mock_web_search_service):
        """Test successful web search."""
        state = sample_agent_state.copy()
        state["action_plan_struct"] = [{"tool_input": {"query": "최신 금리 정보"}}]
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = "최신 금리 정보에 대한 웹 검색 결과입니다."
        
        # synthesis_chain의 ainvoke를 모킹
        mock_chain = AsyncMock()
        mock_chain.ainvoke = AsyncMock(return_value=mock_response)
        
        with patch('app.graph.agent.web_search_service', mock_web_search_service), \
             patch('app.graph.agent.generative_llm', mock_llm), \
             patch('app.graph.agent.ChatPromptTemplate') as mock_prompt:
            
            # ChatPromptTemplate의 체인 동작 모킹
            mock_prompt.from_messages.return_value.__or__.return_value = mock_chain
            
            result = await web_search_node(state)
            
            assert result["factual_response"] == "최신 금리 정보에 대한 웹 검색 결과입니다."
            mock_web_search_service.asearch.assert_called_once_with("최신 금리 정보")

    @pytest.mark.asyncio
    async def test_web_search_node_no_query(self, sample_agent_state):
        """Test web search node without query."""
        state = sample_agent_state.copy()
        state["action_plan_struct"] = [{"tool_input": {}}]
        
        result = await web_search_node(state)
        
        assert result["factual_response"] == "무엇에 대해 검색할지 알려주세요."

    @pytest.mark.asyncio
    async def test_web_search_node_synthesis_error(self, sample_agent_state, mock_web_search_service):
        """Test web search node when synthesis fails."""
        state = sample_agent_state.copy()
        state["action_plan_struct"] = [{"tool_input": {"query": "검색어"}}]
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("Synthesis Error"))
        
        with patch('app.graph.agent.web_search_service', mock_web_search_service), \
             patch('app.graph.agent.generative_llm', mock_llm):
            
            result = await web_search_node(state)
            
            assert "웹 검색 결과를 요약하는 중 오류가 발생했습니다" in result["factual_response"]


class TestScenarioNodes:
    """Test cases for scenario-related node functions."""

    @pytest.mark.asyncio
    async def test_call_scenario_agent_node(self, sample_agent_state, sample_scenario_data):
        """Test call_scenario_agent_node function."""
        state = sample_agent_state.copy()
        state["stt_result"] = "금리 문의"
        state["current_product_type"] = "didimdol"
        
        mock_output = {
            "intent": "inquiry_interest_rate",
            "is_scenario_related": True,
            "entities": {"inquiry_type": "금리 문의"}
        }
        
        with patch('app.graph.agent.get_active_scenario_data', return_value=sample_scenario_data), \
             patch('app.graph.agent.invoke_scenario_agent_logic', return_value=mock_output) as mock_invoke:
            
            result = await call_scenario_agent_node(state)
            
            assert result["scenario_agent_output"] == mock_output
            mock_invoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_scenario_agent_node_missing_data(self, sample_agent_state):
        """Test call_scenario_agent_node with missing data."""
        state = sample_agent_state.copy()
        state["stt_result"] = None
        
        with patch('app.graph.agent.get_active_scenario_data', return_value=None):
            result = await call_scenario_agent_node(state)
            
            assert result["scenario_agent_output"]["intent"] == "error_missing_data"
            assert result["scenario_agent_output"]["is_scenario_related"] is False

    @pytest.mark.asyncio
    async def test_process_scenario_logic_node(self, sample_agent_state, sample_scenario_data):
        """Test process_scenario_logic_node function."""
        state = sample_agent_state.copy()
        state["current_scenario_stage_id"] = "welcome"
        state["stt_result"] = "금리 문의"
        state["scenario_agent_output"] = {
            "intent": "inquiry_interest_rate",
            "is_scenario_related": True,
            "entities": {"inquiry_type": "금리 문의"}
        }
        state["action_plan"] = ["invoke_scenario_agent", "synthesize_response"]
        state["action_plan_struct"] = [{"tool": "invoke_scenario_agent"}]
        
        # 엔티티 검증용 mock
        mock_verification_response = Mock()
        mock_verification_response.content = '{"is_confirmed": true}'
        
        # 다음 스테이지 결정용 mock
        mock_stage_response = Mock()
        mock_stage_response.content = '{"chosen_next_stage_id": "interest_rate"}'
        
        mock_llm = AsyncMock()
        # 첫 번째 호출은 엔티티 검증, 두 번째 호출은 다음 스테이지 결정
        mock_llm.ainvoke = AsyncMock(side_effect=[mock_verification_response, mock_stage_response])
        
        mock_decision = NextStageDecisionModel(chosen_next_stage_id="interest_rate")
        
        with patch('app.graph.agent.get_active_scenario_data', return_value=sample_scenario_data), \
             patch('app.graph.agent.ALL_PROMPTS', {"main_agent": {"determine_next_scenario_stage": "test prompt"}}), \
             patch('app.graph.agent.json_llm', mock_llm), \
             patch('app.graph.agent.next_stage_decision_parser') as mock_parser:
            
            mock_parser.parse.return_value = mock_decision
            
            result = await process_scenario_logic_node(state)
            
            assert result["current_scenario_stage_id"] == "interest_rate"
            assert result["collected_product_info"]["inquiry_type"] == "금리 문의"
            assert len(result["action_plan"]) == 1  # One action removed


class TestUtilityNodes:
    """Test cases for utility node functions."""

    @pytest.mark.asyncio
    async def test_set_product_type_node(self, sample_agent_state, sample_scenario_data):
        """Test set_product_type_node function."""
        state = sample_agent_state.copy()
        state["action_plan_struct"] = [{"tool": "set_product_type", "tool_input": {"product_id": "didimdol"}}]
        
        with patch('app.graph.nodes.control.set_product.ALL_SCENARIOS_DATA', {"didimdol": sample_scenario_data}), \
             patch('app.api.V1.chat_utils.initialize_default_values', return_value={}):
            result = await set_product_type_node(state)
            
            assert result["current_product_type"] == "didimdol"
            assert result["active_scenario_data"] == sample_scenario_data
            assert result["active_scenario_name"] == "디딤돌 대출 상담"
            assert result["current_scenario_stage_id"] == "welcome"
            assert result["is_final_turn_response"] is True

    @pytest.mark.asyncio
    async def test_set_product_type_node_invalid_product(self, sample_agent_state):
        """Test set_product_type_node with invalid product type."""
        state = sample_agent_state.copy()
        state["action_plan_struct"] = [{"tool": "set_product_type", "tool_input": {"product_id": "invalid"}}]
        
        with patch('app.graph.nodes.control.set_product.ALL_SCENARIOS_DATA', {}):
            result = await set_product_type_node(state)
            
            assert result["error_message"] is not None
            assert "Failed to load scenario" in result["error_message"]
            assert result["is_final_turn_response"] is True

    # NOTE: prepare_direct_response_node was removed in refactoring
    # @pytest.mark.asyncio
    # async def test_prepare_direct_response_node(self, sample_agent_state):
    #     """Test prepare_direct_response_node function."""
    #     state = sample_agent_state.copy()
    #     state["main_agent_direct_response"] = "직접 응답입니다."
    #     
    #     result = await prepare_direct_response_node(state)
    #     
    #     assert result["final_response_text_for_tts"] == "직접 응답입니다."
    #     assert result["is_final_turn_response"] is True
    #     assert len(result["messages"]) == 2

    # NOTE: prepare_direct_response_node was removed in refactoring
    # @pytest.mark.asyncio
    # async def test_prepare_direct_response_node_chitchat(self, sample_agent_state, mock_prompts):
    #     """Test prepare_direct_response_node for chitchat."""
    #     state = sample_agent_state.copy()
    #     state["stt_result"] = "안녕하세요"
    #     
    #     mock_llm = AsyncMock()
    #     mock_response = Mock()
    #     mock_response.content = "안녕하세요! 무엇을 도와드릴까요?"
    #     mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    #     
    #     with patch('app.graph.agent.ALL_PROMPTS', mock_prompts), \
    #          patch('app.graph.agent.generative_llm', mock_llm):
    #         
    #         result = await prepare_direct_response_node(state)
    #         
    #         assert result["final_response_text_for_tts"] == "안녕하세요! 무엇을 도와드릴까요?"

    @pytest.mark.asyncio
    async def test_synthesize_response_node(self, sample_agent_state, sample_scenario_data):
        """Test synthesize_response_node function."""
        state = sample_agent_state.copy()
        state["factual_response"] = "디딤돌 대출 정보입니다."
        state["current_product_type"] = "didimdol"
        state["current_scenario_stage_id"] = "welcome"
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = "종합된 응답입니다."
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        with patch('app.graph.nodes.control.synthesize.get_active_scenario_data', return_value=sample_scenario_data), \
             patch('app.graph.nodes.control.synthesize.synthesizer_chain', mock_llm):
            
            result = await synthesize_response_node(state)
            
            assert result["final_response_text_for_tts"] == "종합된 응답입니다."
            assert result["is_final_turn_response"] is True
            assert len(result["messages"]) == 2


class TestRoutingFunctions:
    """Test cases for routing functions."""

    def test_execute_plan_router_empty_plan(self, sample_agent_state):
        """Test execute_plan_router with empty plan."""
        state = sample_agent_state.copy()
        state["action_plan"] = []
        
        result = execute_plan_router(state)
        
        assert result == "synthesize_response_node"

    def test_execute_plan_router_with_actions(self, sample_agent_state):
        """Test execute_plan_router with various actions."""
        test_cases = [
            ("invoke_scenario_agent", "scenario_worker"),
            ("invoke_qa_agent", "rag_worker"),
            ("set_product_type", "set_product_type_node"),
            ("invoke_web_search", "web_worker"),
            ("end_conversation", "end_conversation_node"),
            ("unknown_action", "synthesize_response_node")
        ]
        
        for action, expected_node in test_cases:
            state = sample_agent_state.copy()
            state["action_plan"] = [action]
            
            result = execute_plan_router(state)
            
            assert result == expected_node