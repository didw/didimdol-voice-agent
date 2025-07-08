import pytest
from unittest.mock import Mock, AsyncMock, patch
import json

from app.graph.chains import invoke_scenario_agent_logic
from app.graph.models import ActionModel, ScenarioOutputModel
from app.graph.state import ScenarioAgentOutput
from langchain_core.messages import HumanMessage, AIMessage


class TestScenarioAgentLogic:
    """Test cases for scenario agent logic and QA functionality."""

    @pytest.fixture
    def mock_scenario_chain(self):
        """Create a mock scenario chain for testing."""
        mock_chain = AsyncMock()
        return mock_chain

    @pytest.mark.asyncio
    @patch('app.graph.chains.scenario_chain')
    async def test_invoke_scenario_agent_logic_success(self, mock_chain):
        """Test successful scenario agent logic invocation."""
        mock_response = Mock()
        mock_response.content = json.dumps({
            "intent": "inquiry_interest_rate",
            "is_scenario_related": True,
            "entities": {"inquiry_type": "금리 문의"}
        })
        mock_chain.ainvoke = AsyncMock(return_value=mock_response)
        
        result = await invoke_scenario_agent_logic(
            user_input="금리가 얼마인가요?",
            current_stage_prompt="현재 단계 프롬프트",
            expected_info_key="inquiry_type",
            messages_history=[],
            scenario_name="디딤돌 대출 상담"
        )
        
        assert result["intent"] == "inquiry_interest_rate"
        assert result["is_scenario_related"] is True
        assert result["entities"]["inquiry_type"] == "금리 문의"

    @pytest.mark.asyncio
    @patch('app.graph.chains.scenario_chain')
    async def test_invoke_scenario_agent_logic_not_related(self, mock_chain):
        """Test scenario agent logic with non-scenario related input."""
        mock_response = Mock()
        mock_response.content = json.dumps({
            "intent": "general_question",
            "is_scenario_related": False,
            "entities": {}
        })
        mock_chain.ainvoke = AsyncMock(return_value=mock_response)
        
        result = await invoke_scenario_agent_logic(
            user_input="날씨가 어때요?",
            current_stage_prompt="현재 단계 프롬프트",
            expected_info_key="inquiry_type",
            messages_history=[],
            scenario_name="디딤돌 대출 상담"
        )
        
        assert result["intent"] == "general_question"
        assert result["is_scenario_related"] is False
        assert result["entities"] == {}

    @pytest.mark.asyncio
    @patch('app.graph.chains.scenario_chain')
    async def test_invoke_scenario_agent_logic_json_parse_error(self, mock_chain):
        """Test scenario agent logic with JSON parse error."""
        mock_response = Mock()
        mock_response.content = "Invalid JSON response"
        mock_chain.ainvoke = AsyncMock(return_value=mock_response)
        
        result = await invoke_scenario_agent_logic(
            user_input="테스트 입력",
            current_stage_prompt="현재 단계 프롬프트",
            expected_info_key="inquiry_type",
            messages_history=[],
            scenario_name="디딤돌 대출 상담"
        )
        
        assert result["intent"] == "json_parse_error"
        assert result["is_scenario_related"] is False

    @pytest.mark.asyncio
    @patch('app.graph.chains.scenario_chain')
    async def test_invoke_scenario_agent_logic_chain_error(self, mock_chain):
        """Test scenario agent logic with chain execution error."""
        mock_chain.ainvoke = AsyncMock(side_effect=Exception("Chain Error"))
        
        result = await invoke_scenario_agent_logic(
            user_input="테스트 입력",
            current_stage_prompt="현재 단계 프롬프트",
            expected_info_key="inquiry_type",
            messages_history=[],
            scenario_name="디딤돌 대출 상담"
        )
        
        assert result["intent"] == "scenario_agent_error"
        assert result["is_scenario_related"] is False


class TestQAScenarios:
    """Test cases for QA scenarios and question answering."""

    @pytest.fixture
    def sample_qa_scenarios(self):
        """Create sample QA scenarios for testing."""
        return {
            "didimdol_basic_info": {
                "question": "디딤돌 대출이란 무엇인가요?",
                "expected_keywords": ["청년", "정부 지원", "대출"],
                "category": "기본 정보"
            },
            "interest_rate_inquiry": {
                "question": "디딤돌 대출 금리가 얼마인가요?",
                "expected_keywords": ["금리", "연 %", "우대"],
                "category": "금리 정보"
            },
            "loan_limit_inquiry": {
                "question": "디딤돌 대출 한도는 얼마인가요?",
                "expected_keywords": ["한도", "최대", "억원"],
                "category": "한도 정보"
            },
            "application_process": {
                "question": "디딤돌 대출 신청 방법을 알려주세요",
                "expected_keywords": ["신청", "방법", "절차"],
                "category": "신청 정보"
            }
        }

    @pytest.mark.asyncio
    async def test_qa_scenario_basic_info(self, sample_qa_scenarios, mock_rag_service):
        """Test QA scenario for basic information inquiry."""
        scenario = sample_qa_scenarios["didimdol_basic_info"]
        
        mock_rag_service.answer_question.return_value = (
            "디딤돌 대출은 청년층을 대상으로 하는 정부 지원 대출 상품입니다. "
            "주거 안정을 위해 저금리로 제공됩니다."
        )
        
        from app.graph.agent import factual_answer_node
        
        state = {
            "stt_result": scenario["question"],
            "messages": [HumanMessage(content=scenario["question"])],
            "active_scenario_name": "디딤돌 대출 상담",
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        with patch('app.graph.agent.rag_service', mock_rag_service), \
             patch('app.graph.agent.ALL_PROMPTS', {"qa_agent": {"rag_query_expansion_prompt": "test"}}):
            
            result = await factual_answer_node(state)
            
            response = result["factual_response"]
            
            # Check if expected keywords are present in the response
            for keyword in scenario["expected_keywords"]:
                assert keyword in response or any(k in response for k in [keyword, keyword.lower(), keyword.upper()])

    @pytest.mark.asyncio
    async def test_qa_scenario_interest_rate(self, sample_qa_scenarios, mock_rag_service):
        """Test QA scenario for interest rate inquiry."""
        scenario = sample_qa_scenarios["interest_rate_inquiry"]
        
        mock_rag_service.answer_question.return_value = (
            "디딤돌 대출의 기본 금리는 연 2.5%입니다. "
            "소득 수준과 우대 조건에 따라 최대 0.5% 할인이 가능합니다."
        )
        
        from app.graph.agent import factual_answer_node
        
        state = {
            "stt_result": scenario["question"],
            "messages": [HumanMessage(content=scenario["question"])],
            "active_scenario_name": "디딤돌 대출 상담",
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        with patch('app.graph.agent.rag_service', mock_rag_service), \
             patch('app.graph.agent.ALL_PROMPTS', {"qa_agent": {"rag_query_expansion_prompt": "test"}}):
            
            result = await factual_answer_node(state)
            
            response = result["factual_response"]
            
            # Should contain interest rate information
            assert any(keyword in response for keyword in ["금리", "연", "%"])

    @pytest.mark.asyncio
    async def test_qa_multi_turn_conversation(self, mock_rag_service):
        """Test QA in multi-turn conversation context."""
        # Simulate a conversation where user asks follow-up questions
        conversation_history = [
            HumanMessage(content="디딤돌 대출에 대해 알려주세요"),
            AIMessage(content="디딤돌 대출은 청년층을 위한 정부 지원 대출입니다."),
            HumanMessage(content="그럼 금리는 얼마인가요?")
        ]
        
        mock_rag_service.answer_question.return_value = (
            "디딤돌 대출의 금리는 연 2.5%부터 시작하며, "
            "소득 수준에 따라 우대금리가 적용됩니다."
        )
        
        from app.graph.agent import factual_answer_node
        
        state = {
            "stt_result": "그럼 금리는 얼마인가요?",
            "messages": conversation_history,
            "active_scenario_name": "디딤돌 대출 상담",
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        with patch('app.graph.agent.rag_service', mock_rag_service), \
             patch('app.graph.agent.ALL_PROMPTS', {"qa_agent": {"rag_query_expansion_prompt": "test"}}):
            
            result = await factual_answer_node(state)
            
            response = result["factual_response"]
            
            # Should provide relevant answer in context
            assert "금리" in response
            assert "%" in response

    @pytest.mark.asyncio
    async def test_scenario_qa_integration(self, sample_scenario_data, mock_rag_service):
        """Test integration between scenario logic and QA functionality."""
        # Test a scenario where user is in a consultation stage and asks a question
        state = {
            "current_product_type": "didimdol",
            "current_scenario_stage_id": "welcome",
            "stt_result": "금리가 궁금한데 자세한 정보를 알려주세요",
            "messages": [HumanMessage(content="금리가 궁금한데 자세한 정보를 알려주세요")],
            "collected_product_info": {"inquiry_type": "금리 문의"},
            "scenario_agent_output": {
                "intent": "inquiry_interest_rate",
                "is_scenario_related": True,
                "entities": {"inquiry_type": "금리 문의"}
            },
            "action_plan": ["invoke_qa_agent", "invoke_scenario_agent"],
            "action_plan_struct": [
                {"tool": "invoke_qa_agent", "tool_input": {}},
                {"tool": "invoke_scenario_agent", "tool_input": {}}
            ]
        }
        
        mock_rag_service.answer_question.return_value = (
            "디딤돌 대출의 기본 금리는 연 2.5%이며, 소득 수준에 따라 "
            "우대금리 최대 0.5%가 추가로 적용됩니다."
        )
        
        from app.graph.agent import factual_answer_node, synthesize_response_node
        
        with patch('app.graph.agent.rag_service', mock_rag_service), \
             patch('app.graph.agent.ALL_PROMPTS', {"qa_agent": {"rag_query_expansion_prompt": "test"}}), \
             patch('app.graph.agent.get_active_scenario_data', return_value=sample_scenario_data):
            
            # First get factual answer
            qa_result = await factual_answer_node(state)
            
            # Then synthesize with scenario context
            state.update(qa_result)
            
            mock_synthesizer = AsyncMock()
            mock_response = Mock()
            mock_response.content = (
                "디딤돌 대출의 금리는 연 2.5%부터 시작합니다. "
                "추가로 궁금한 사항이 있으시면 말씀해 주세요."
            )
            mock_synthesizer.ainvoke = AsyncMock(return_value=mock_response)
            
            with patch('app.graph.agent.synthesizer_chain', mock_synthesizer):
                final_result = await synthesize_response_node(state)
                
                assert final_result["final_response_text_for_tts"] is not None
                assert final_result["is_final_turn_response"] is True

    def test_qa_scenario_categorization(self, sample_qa_scenarios):
        """Test that QA scenarios are properly categorized."""
        categories = {}
        for scenario_name, scenario_data in sample_qa_scenarios.items():
            category = scenario_data["category"]
            if category not in categories:
                categories[category] = []
            categories[category].append(scenario_name)
        
        # Check that we have different categories
        assert len(categories) > 1
        assert "기본 정보" in categories
        assert "금리 정보" in categories
        assert "한도 정보" in categories
        assert "신청 정보" in categories

    def test_qa_scenario_keyword_coverage(self, sample_qa_scenarios):
        """Test that QA scenarios have comprehensive keyword coverage."""
        all_keywords = set()
        for scenario_data in sample_qa_scenarios.values():
            all_keywords.update(scenario_data["expected_keywords"])
        
        # Should cover main aspects of loan consultation
        financial_keywords = {"금리", "한도", "대출"}
        process_keywords = {"신청", "방법", "절차"}
        target_keywords = {"청년", "정부"}
        
        assert any(keyword in all_keywords for keyword in financial_keywords)
        assert any(keyword in all_keywords for keyword in process_keywords)
        assert any(keyword in all_keywords for keyword in target_keywords)