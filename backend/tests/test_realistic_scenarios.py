"""
Realistic Korean conversation test scenarios for the 디딤돌 voice consultation agent.

This module contains comprehensive test scenarios that simulate real user interactions
with the voice consultation agent, including various conversation flows, edge cases,
and validation of correct responses.
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


class RealisticScenarioValidator:
    """Helper class to validate agent responses for realistic scenarios."""
    
    def __init__(self):
        self.didimdol_keywords = {
            'basic_info': ['디딤돌', '청년', '정부지원', '주택담보대출', '만39세', '생애최초'],
            'interest_rate': ['금리', '연', '%', '우대금리', '변동금리', '고정금리'],
            'limit': ['한도', '최대', '억원', '주택가격', '70%', '80%'],
            'eligibility': ['자격', '조건', '소득', '신용', '만39세', '생애최초'],
            'documents': ['서류', '필요', '증명서', '소득증명', '재직증명', '주민등록'],
            'process': ['신청', '방법', '절차', '단계', '기간', '심사']
        }
        
        self.jeonse_keywords = {
            'basic_info': ['전세자금대출', '전세', '보증금', '임차'],
            'interest_rate': ['금리', '연', '%'],
            'limit': ['한도', '최대', '억원', '전세보증금'],
            'eligibility': ['자격', '조건', '소득', '신용'],
            'documents': ['서류', '필요', '증명서', '임대차계약서'],
            'process': ['신청', '방법', '절차', '단계']
        }
        
        self.account_keywords = {
            'basic_info': ['입출금통장', '계좌개설', '예금계좌'],
            'features': ['체크카드', '인터넷뱅킹', '온라인뱅킹', '이체한도'],
            'benefits': ['수수료', '우대', '혜택'],
            'process': ['개설', '신청', '방법', '절차']
        }
    
    def validate_response(self, response: str, category: str, product_type: str) -> Dict[str, Any]:
        """
        Validate if the response contains appropriate keywords for the given category and product.
        
        Args:
            response: The agent's response text
            category: The category of question (e.g., 'basic_info', 'interest_rate')
            product_type: The product type ('didimdol', 'jeonse', 'account')
            
        Returns:
            Dictionary with validation results
        """
        keywords_map = {
            'didimdol': self.didimdol_keywords,
            'jeonse': self.jeonse_keywords,
            'account': self.account_keywords
        }
        
        if product_type not in keywords_map:
            return {'valid': False, 'reason': f'Unknown product type: {product_type}'}
        
        expected_keywords = keywords_map[product_type].get(category, [])
        if not expected_keywords:
            return {'valid': False, 'reason': f'Unknown category: {category}'}
        
        found_keywords = []
        for keyword in expected_keywords:
            if keyword in response:
                found_keywords.append(keyword)
        
        # At least 1 relevant keyword should be present
        is_valid = len(found_keywords) >= 1
        
        return {
            'valid': is_valid,
            'found_keywords': found_keywords,
            'expected_keywords': expected_keywords,
            'coverage': len(found_keywords) / len(expected_keywords) if expected_keywords else 0
        }
    
    def validate_politeness(self, response: str) -> bool:
        """Check if the response uses appropriate Korean politeness markers."""
        polite_markers = ['습니다', '합니다', '됩니다', '입니다', '세요', '십니다', '요', '해요', '드려요', '드립니다', '해드려요']
        return any(marker in response for marker in polite_markers)
    
    def validate_completeness(self, response: str, question_type: str) -> bool:
        """Check if the response provides complete information for the question type."""
        if question_type == 'interest_rate':
            return '금리' in response and any(marker in response for marker in ['%', '연', '기준'])
        elif question_type == 'limit':
            return '한도' in response and any(marker in response for marker in ['억', '원', '최대'])
        elif question_type == 'eligibility':
            return '자격' in response or '조건' in response
        elif question_type == 'documents':
            return '서류' in response or '필요' in response
        elif question_type == 'process':
            return any(marker in response for marker in ['신청', '방법', '절차', '단계'])
        return True


class TestRealisticDidimdolScenarios:
    """Test realistic conversation scenarios for 디딤돌 주택담보대출."""
    
    @pytest.fixture
    def validator(self):
        return RealisticScenarioValidator()
    
    @pytest.fixture
    def mock_services(self):
        """Mock all external services for testing."""
        with patch('app.graph.agent.rag_service') as mock_rag, \
             patch('app.graph.agent.web_search_service') as mock_web, \
             patch('app.graph.agent.ALL_PROMPTS') as mock_prompts, \
             patch('app.graph.agent.ALL_SCENARIOS_DATA') as mock_scenarios, \
             patch('app.graph.agent.json_llm') as mock_json_llm, \
             patch('app.graph.agent.expanded_queries_parser') as mock_parser:
            
            # Setup RAG service
            mock_rag.is_ready.return_value = True
            mock_rag.answer_question = AsyncMock()
            
            # Setup web search service
            mock_web.asearch = AsyncMock(return_value="웹 검색 결과")
            
            # Setup prompts - mock as dictionary with proper structure
            mock_prompts_data = {
                'qa_agent': {
                    'rag_query_expansion_prompt': """
You are an AI expert specializing in search query optimization.
Generate search queries based on the user's question and conversation history.

Context:
- Current Topic: {scenario_name}
- Chat History: {chat_history}  
- User's Latest Question: "{user_question}"

Please provide your response in JSON format with key "queries" containing a list of query strings:
{{
  "queries": [
    "specific detailed query",
    "general high-level query",
    "rephrased alternative query"
  ]
}}
"""
                },
                'main_agent': {'test': 'prompt'}
            }
            
            # Mock dictionary access methods
            mock_prompts.get = Mock(side_effect=lambda key, default=None: mock_prompts_data.get(key, default))
            mock_prompts.__getitem__ = Mock(side_effect=lambda key: mock_prompts_data[key])
            
            # Setup JSON LLM to fail gracefully so original question is used
            # This simulates the real error handling in the code
            mock_json_llm.ainvoke = AsyncMock(side_effect=Exception("Mocked expansion failure"))
            
            # Setup expanded queries parser (not used due to above exception)
            mock_parser.parse = Mock()
            
            # Setup scenarios
            mock_scenarios.return_value = {
                'didimdol': {
                    'scenario_name': '디딤돌 대출 상담',
                    'stages': {'welcome': {'prompt': 'test'}}
                }
            }
            
            yield {
                'rag': mock_rag,
                'web': mock_web,
                'prompts': mock_prompts,
                'scenarios': mock_scenarios,
                'json_llm': mock_json_llm,
                'parser': mock_parser
            }
    
    @pytest.mark.asyncio
    async def test_didimdol_basic_info_inquiry(self, validator, mock_services):
        """Test basic information inquiry about 디딤돌 대출."""
        # User asks about basic 디딤돌 loan information
        user_input = "디딤돌 대출이 뭔가요? 처음 들어보는데 자세히 알려주세요."
        
        # Mock RAG response
        mock_services['rag'].answer_question.return_value = (
            "디딤돌 대출은 만39세 이하 청년층을 대상으로 한 생애최초 주택담보대출로, "
            "정부지원을 받아 저금리로 제공되는 대출상품입니다. "
            "주택가격의 70% 이내에서 최대 4억원까지 대출이 가능합니다."
        )
        
        state = {
            "user_input_text": user_input,
            "messages": [HumanMessage(content=user_input)],
            "stt_result": user_input,
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result = await factual_answer_node(state)
        response = result["factual_response"]
        
        # Validate response
        validation = validator.validate_response(response, 'basic_info', 'didimdol')
        assert validation['valid'], f"Response lacks relevant keywords: {validation}"
        assert validator.validate_politeness(response), "Response should use polite Korean"
        assert validator.validate_completeness(response, 'basic_info'), "Response should be complete"
        
        # Check specific expectations
        assert '디딤돌' in response, "Should mention 디딤돌"
        assert '청년' in response or '39세' in response, "Should mention age requirement"
        assert '정부지원' in response or '저금리' in response, "Should mention government support"
    
    @pytest.mark.asyncio
    async def test_didimdol_interest_rate_inquiry(self, validator, mock_services):
        """Test interest rate inquiry with follow-up questions."""
        # User asks about interest rates
        user_input = "디딤돌 대출 금리가 어떻게 되나요? 다른 은행이랑 비교해서 어떤가요?"
        
        # Mock RAG response
        mock_services['rag'].answer_question.return_value = (
            "디딤돌 대출의 기본 금리는 연 2.5%부터 시작하며, "
            "소득수준과 신용등급에 따라 우대금리가 적용됩니다. "
            "일반 시중은행 주택담보대출 대비 0.5~1.0% 낮은 수준입니다."
        )
        
        state = {
            "user_input_text": user_input,
            "messages": [HumanMessage(content=user_input)],
            "stt_result": user_input,
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result = await factual_answer_node(state)
        response = result["factual_response"]
        
        # Validate response
        validation = validator.validate_response(response, 'interest_rate', 'didimdol')
        assert validation['valid'], f"Response lacks interest rate keywords: {validation}"
        assert validator.validate_politeness(response), "Response should use polite Korean"
        assert validator.validate_completeness(response, 'interest_rate'), "Response should include rate info"
        
        # Check specific expectations
        assert '금리' in response, "Should mention interest rate"
        assert '%' in response or '연' in response, "Should include rate details"
        assert '우대' in response or '할인' in response, "Should mention preferential rates"
    
    @pytest.mark.asyncio
    async def test_didimdol_eligibility_detailed_inquiry(self, validator, mock_services):
        """Test detailed eligibility inquiry with personal situation."""
        # User asks about eligibility with personal details
        user_input = "저는 32살이고 연봉 4천만원인데, 디딤돌 대출 받을 수 있나요? 신용등급은 2등급이에요."
        
        # Mock RAG response
        mock_services['rag'].answer_question.return_value = (
            "디딤돌 대출 자격조건은 다음과 같습니다: "
            "만39세 이하 청년, 생애최초 주택구입자, 연소득 7천만원 이하, "
            "신용등급 1~4등급입니다. 고객님의 조건으로는 신청 가능하십니다."
        )
        
        state = {
            "user_input_text": user_input,
            "messages": [HumanMessage(content=user_input)],
            "stt_result": user_input,
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result = await factual_answer_node(state)
        response = result["factual_response"]
        
        # Validate response
        validation = validator.validate_response(response, 'eligibility', 'didimdol')
        assert validation['valid'], f"Response lacks eligibility keywords: {validation}"
        assert validator.validate_politeness(response), "Response should use polite Korean"
        assert validator.validate_completeness(response, 'eligibility'), "Response should cover eligibility"
        
        # Check specific expectations
        assert '자격' in response or '조건' in response, "Should mention eligibility"
        assert '신용등급' in response or '신용' in response, "Should address credit rating"
        assert '연소득' in response or '소득' in response, "Should mention income requirements"
    
    @pytest.mark.asyncio
    async def test_didimdol_multi_turn_conversation(self, validator, mock_services):
        """Test multi-turn conversation with context awareness."""
        # First question about basic info
        first_input = "디딤돌 대출에 대해 알고 싶어요."
        
        # Mock RAG response for first question
        mock_services['rag'].answer_question.return_value = (
            "디딤돌 대출은 청년층을 위한 생애최초 주택담보대출입니다."
        )
        
        # Simulate first turn
        state = {
            "user_input_text": first_input,
            "messages": [HumanMessage(content=first_input)],
            "stt_result": first_input,
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        first_result = await factual_answer_node(state)
        first_response = first_result["factual_response"]
        
        # Second question with context (follow-up)
        second_input = "그럼 금리는 어떻게 되나요?"
        
        # Update conversation history
        conversation_history = [
            HumanMessage(content=first_input),
            AIMessage(content=first_response),
            HumanMessage(content=second_input)
        ]
        
        # Mock RAG response for second question
        mock_services['rag'].answer_question.return_value = (
            "디딤돌 대출의 기본 금리는 연 2.5%부터 시작하며, "
            "소득수준에 따라 우대금리가 적용됩니다."
        )
        
        # Simulate second turn
        state.update({
            "user_input_text": second_input,
            "messages": conversation_history,
            "stt_result": second_input,
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        })
        
        second_result = await factual_answer_node(state)
        second_response = second_result["factual_response"]
        
        # Validate both responses
        first_validation = validator.validate_response(first_response, 'basic_info', 'didimdol')
        second_validation = validator.validate_response(second_response, 'interest_rate', 'didimdol')
        
        assert first_validation['valid'], "First response should contain basic info"
        assert second_validation['valid'], "Second response should contain interest rate info"
        assert validator.validate_politeness(second_response), "Should maintain politeness"
        
        # Check context awareness
        assert '금리' in second_response, "Should answer the follow-up question"
        assert '%' in second_response or '연' in second_response, "Should include rate details"
    
    @pytest.mark.asyncio
    async def test_didimdol_document_requirements_inquiry(self, validator, mock_services):
        """Test inquiry about required documents."""
        user_input = "디딤돌 대출 신청하려면 어떤 서류가 필요한가요? 미리 준비해두고 싶어요."
        
        # Mock RAG response
        mock_services['rag'].answer_question.return_value = (
            "디딤돌 대출 신청시 필요한 서류는 다음과 같습니다: "
            "신분증, 주민등록등본, 재직증명서, 소득증명서(근로소득원천징수영수증), "
            "주택 관련 서류(부동산매매계약서, 등기부등본) 등이 필요합니다."
        )
        
        state = {
            "user_input_text": user_input,
            "messages": [HumanMessage(content=user_input)],
            "stt_result": user_input,
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result = await factual_answer_node(state)
        response = result["factual_response"]
        
        # Validate response
        validation = validator.validate_response(response, 'documents', 'didimdol')
        assert validation['valid'], f"Response lacks document keywords: {validation}"
        assert validator.validate_politeness(response), "Response should use polite Korean"
        assert validator.validate_completeness(response, 'documents'), "Response should list documents"
        
        # Check specific expectations
        assert '서류' in response, "Should mention documents"
        assert '신분증' in response or '주민등록' in response, "Should mention ID documents"
        assert '소득증명' in response or '재직증명' in response, "Should mention income proof"


class TestRealisticJeonseScenarios:
    """Test realistic conversation scenarios for 전세자금대출."""
    
    @pytest.fixture
    def validator(self):
        return RealisticScenarioValidator()
    
    @pytest.fixture
    def mock_services(self):
        """Mock all external services for testing."""
        with patch('app.graph.agent.rag_service') as mock_rag, \
             patch('app.graph.agent.web_search_service') as mock_web, \
             patch('app.graph.agent.ALL_PROMPTS') as mock_prompts, \
             patch('app.graph.agent.ALL_SCENARIOS_DATA') as mock_scenarios:
            
            mock_rag.is_ready.return_value = True
            mock_rag.answer_question = AsyncMock()
            mock_web.asearch = AsyncMock(return_value="웹 검색 결과")
            mock_prompts.return_value = {'main_agent': {'test': 'prompt'}}
            mock_scenarios.return_value = {
                'jeonse': {
                    'scenario_name': '전세자금대출 상담',
                    'stages': {'welcome': {'prompt': 'test'}}
                }
            }
            
            yield {
                'rag': mock_rag,
                'web': mock_web,
                'prompts': mock_prompts,
                'scenarios': mock_scenarios
            }
    
    @pytest.mark.asyncio
    async def test_jeonse_basic_info_inquiry(self, validator, mock_services):
        """Test basic information inquiry about 전세자금대출."""
        user_input = "전세자금대출이 뭔가요? 전세 보증금 대출받을 수 있나요?"
        
        # Mock RAG response
        mock_services['rag'].answer_question.return_value = (
            "전세자금대출은 전세 보증금 마련을 위한 대출상품입니다. "
            "전세보증금의 80% 이내에서 최대 5억원까지 대출이 가능하며, "
            "임대차계약서가 필요합니다."
        )
        
        state = {
            "user_input_text": user_input,
            "messages": [HumanMessage(content=user_input)],
            "stt_result": user_input,
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result = await factual_answer_node(state)
        response = result["factual_response"]
        
        # Validate response
        validation = validator.validate_response(response, 'basic_info', 'jeonse')
        assert validation['valid'], f"Response lacks relevant keywords: {validation}"
        assert validator.validate_politeness(response), "Response should use polite Korean"
        
        # Check specific expectations
        assert '전세' in response, "Should mention 전세"
        assert '보증금' in response, "Should mention deposit"
        assert '대출' in response, "Should mention loan"
    
    @pytest.mark.asyncio
    async def test_jeonse_urgent_inquiry(self, validator, mock_services):
        """Test urgent inquiry about 전세자금대출."""
        user_input = "다음 주에 전세 계약해야 하는데, 전세자금대출 얼마나 빨리 받을 수 있나요?"
        
        # Mock RAG response
        mock_services['rag'].answer_question.return_value = (
            "전세자금대출은 서류 준비 완료 후 대출 신청부터 실행까지 "
            "약 3-5영업일 소요됩니다. 임대차계약서, 소득증명서 등 "
            "필요서류를 미리 준비하시면 더 빠른 처리가 가능합니다."
        )
        
        state = {
            "user_input_text": user_input,
            "messages": [HumanMessage(content=user_input)],
            "stt_result": user_input,
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result = await factual_answer_node(state)
        response = result["factual_response"]
        
        # Validate response
        validation = validator.validate_response(response, 'process', 'jeonse')
        assert validation['valid'], f"Response lacks process keywords: {validation}"
        assert validator.validate_politeness(response), "Response should use polite Korean"
        
        # Check urgency handling
        assert '영업일' in response or '기간' in response, "Should mention timeframe"
        assert '서류' in response, "Should mention required documents"


class TestRealisticAccountScenarios:
    """Test realistic conversation scenarios for 입출금통장."""
    
    @pytest.fixture
    def validator(self):
        return RealisticScenarioValidator()
    
    @pytest.fixture
    def mock_services(self):
        """Mock all external services for testing."""
        with patch('app.graph.agent.rag_service') as mock_rag, \
             patch('app.graph.agent.web_search_service') as mock_web, \
             patch('app.graph.agent.ALL_PROMPTS') as mock_prompts, \
             patch('app.graph.agent.ALL_SCENARIOS_DATA') as mock_scenarios:
            
            mock_rag.is_ready.return_value = True
            mock_rag.answer_question = AsyncMock()
            mock_web.asearch = AsyncMock(return_value="웹 검색 결과")
            mock_prompts.return_value = {'main_agent': {'test': 'prompt'}}
            mock_scenarios.return_value = {
                'account': {
                    'scenario_name': '입출금통장 개설',
                    'stages': {'welcome': {'prompt': 'test'}}
                }
            }
            
            yield {
                'rag': mock_rag,
                'web': mock_web,
                'prompts': mock_prompts,
                'scenarios': mock_scenarios
            }
    
    @pytest.mark.asyncio
    async def test_account_opening_inquiry(self, validator, mock_services):
        """Test account opening inquiry."""
        user_input = "계좌 개설하고 싶은데, 어떤 통장이 좋을까요? 체크카드도 같이 만들 수 있나요?"
        
        # Mock RAG response
        mock_services['rag'].answer_question.return_value = (
            "입출금통장은 다양한 혜택과 함께 개설 가능합니다. "
            "체크카드 발급, 인터넷뱅킹 가입, 자동이체 설정 등 "
            "편리한 서비스를 함께 이용하실 수 있습니다."
        )
        
        state = {
            "user_input_text": user_input,
            "messages": [HumanMessage(content=user_input)],
            "stt_result": user_input,
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result = await factual_answer_node(state)
        response = result["factual_response"]
        
        # Validate response
        validation = validator.validate_response(response, 'basic_info', 'account')
        assert validation['valid'], f"Response lacks relevant keywords: {validation}"
        assert validator.validate_politeness(response), "Response should use polite Korean"
        
        # Check specific expectations
        assert '통장' in response or '계좌' in response, "Should mention account"
        assert '체크카드' in response, "Should address check card question"


class TestRealisticEdgeCases:
    """Test edge cases and error scenarios."""
    
    @pytest.fixture
    def validator(self):
        return RealisticScenarioValidator()
    
    @pytest.fixture
    def mock_services(self):
        """Mock all external services for testing."""
        with patch('app.graph.agent.rag_service') as mock_rag, \
             patch('app.graph.agent.web_search_service') as mock_web, \
             patch('app.graph.agent.ALL_PROMPTS') as mock_prompts, \
             patch('app.graph.agent.ALL_SCENARIOS_DATA') as mock_scenarios:
            
            mock_rag.is_ready.return_value = True
            mock_rag.answer_question = AsyncMock()
            mock_web.asearch = AsyncMock(return_value="웹 검색 결과")
            mock_prompts.return_value = {'main_agent': {'test': 'prompt'}}
            mock_scenarios.return_value = {}
            
            yield {
                'rag': mock_rag,
                'web': mock_web,
                'prompts': mock_prompts,
                'scenarios': mock_scenarios
            }
    
    @pytest.mark.asyncio
    async def test_unclear_input_handling(self, validator, mock_services):
        """Test handling of unclear or ambiguous input."""
        user_input = "어... 그... 뭔가 대출 같은 거 있나요?"
        
        # Mock RAG response for unclear input
        mock_services['rag'].answer_question.return_value = (
            "저희 은행에서는 디딤돌 대출, 전세자금대출 등 다양한 대출상품을 제공하고 있습니다. "
            "어떤 용도의 대출을 원하시는지 구체적으로 말씀해 주시면 더 정확한 안내를 드릴 수 있습니다."
        )
        
        state = {
            "user_input_text": user_input,
            "messages": [HumanMessage(content=user_input)],
            "stt_result": user_input,
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result = await factual_answer_node(state)
        response = result["factual_response"]
        
        # Validate response
        assert validator.validate_politeness(response), "Response should use polite Korean"
        assert '대출' in response, "Should mention loan products"
        assert '안내' in response or '도움' in response, "Should offer to help"
    
    @pytest.mark.asyncio
    async def test_off_topic_inquiry(self, validator, mock_services):
        """Test handling of off-topic inquiries."""
        user_input = "오늘 날씨가 어때요? 비 올까요?"
        
        # Mock web search for off-topic query
        mock_services['web'].asearch.return_value = (
            "오늘 날씨 정보:\n"
            "서울 기준 맑음, 최고기온 25도\n"
            "강수확률 10%"
        )
        
        state = {
            "user_input_text": user_input,
            "messages": [HumanMessage(content=user_input)],
            "stt_result": user_input,
            "action_plan": ["invoke_web_search"],
            "action_plan_struct": [{"tool": "invoke_web_search", "tool_input": {"query": "날씨"}}]
        }
        
        result = await web_search_node(state)
        response = result["factual_response"]
        
        # Validate response
        assert validator.validate_politeness(response), "Response should use polite Korean"
        assert '날씨' in response, "Should address weather question"
        
        # Should also guide back to banking topics
        assert '도움' in response or '상담' in response or '대출' in response, "Should guide back to banking"
    
    @pytest.mark.asyncio
    async def test_complex_multi_product_inquiry(self, validator, mock_services):
        """Test handling of complex inquiry involving multiple products."""
        user_input = "디딤돌 대출이랑 전세자금대출 둘 다 받을 수 있나요? 그리고 새 통장도 만들고 싶어요."
        
        # Mock RAG response for multi-product inquiry
        mock_services['rag'].answer_question.return_value = (
            "디딤돌 대출과 전세자금대출은 서로 다른 용도의 대출상품입니다. "
            "동시 이용 가능 여부는 개별 심사를 통해 결정됩니다. "
            "입출금통장 개설은 별도로 진행 가능합니다. "
            "구체적인 상담을 위해 각 상품별로 안내해 드리겠습니다."
        )
        
        state = {
            "user_input_text": user_input,
            "messages": [HumanMessage(content=user_input)],
            "stt_result": user_input,
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result = await factual_answer_node(state)
        response = result["factual_response"]
        
        # Validate response addresses multiple products
        assert validator.validate_politeness(response), "Response should use polite Korean"
        assert '디딤돌' in response, "Should mention didimdol loan"
        assert '전세' in response, "Should mention jeonse loan"
        assert '통장' in response or '계좌' in response, "Should mention account"
        assert '상담' in response or '안내' in response, "Should offer consultation"
    
    @pytest.mark.asyncio
    async def test_emotional_user_input(self, validator, mock_services):
        """Test handling of emotional or frustrated user input."""
        user_input = "대출 심사에서 떨어졌어요... 너무 속상해요. 다른 방법 없을까요?"
        
        # Mock RAG response for emotional input
        mock_services['rag'].answer_question.return_value = (
            "대출 심사 결과에 대해 속상한 마음을 이해합니다. "
            "다른 대출 상품이나 대안을 함께 찾아보겠습니다. "
            "신용개선 방법이나 추가 서류 준비 등으로 재신청도 가능합니다."
        )
        
        state = {
            "user_input_text": user_input,
            "messages": [HumanMessage(content=user_input)],
            "stt_result": user_input,
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result = await factual_answer_node(state)
        response = result["factual_response"]
        
        # Validate empathetic response
        assert validator.validate_politeness(response), "Response should use polite Korean"
        assert '이해' in response or '안타깝' in response, "Should show empathy"
        assert '방법' in response or '대안' in response, "Should offer alternatives"
        assert '도움' in response or '상담' in response, "Should offer help"
    
    @pytest.mark.asyncio
    async def test_number_recognition_amounts(self, validator, mock_services):
        """Test handling of Korean number expressions for amounts."""
        user_input = "오천만원 대출 받고 싶은데, 디딤돌 대출 한도가 어떻게 되나요?"
        
        # Mock RAG response
        mock_services['rag'].answer_question.return_value = (
            "디딤돌 대출 한도는 최대 4억원까지 가능하며, "
            "주택가격의 70% 이내에서 승인됩니다. "
            "5천만원 대출은 조건 충족시 가능합니다."
        )
        
        state = {
            "user_input_text": user_input,
            "messages": [HumanMessage(content=user_input)],
            "stt_result": user_input,
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result = await factual_answer_node(state)
        response = result["factual_response"]
        
        # Validate number handling
        assert validator.validate_politeness(response), "Response should use polite Korean"
        assert '한도' in response, "Should mention loan limit"
        assert '억원' in response or '원' in response, "Should include amount information"
        assert '5천만원' in response or '오천만원' in response, "Should address specific amount"


class TestConversationContextManagement:
    """Test conversation context and state management."""
    
    @pytest.fixture
    def validator(self):
        return RealisticScenarioValidator()
    
    @pytest.fixture
    def mock_services(self):
        """Mock all external services for testing."""
        with patch('app.graph.agent.rag_service') as mock_rag, \
             patch('app.graph.agent.web_search_service') as mock_web, \
             patch('app.graph.agent.ALL_PROMPTS') as mock_prompts, \
             patch('app.graph.agent.ALL_SCENARIOS_DATA') as mock_scenarios:
            
            mock_rag.is_ready.return_value = True
            mock_rag.answer_question = AsyncMock()
            mock_web.asearch = AsyncMock(return_value="웹 검색 결과")
            mock_prompts.return_value = {'main_agent': {'test': 'prompt'}}
            mock_scenarios.return_value = {
                'didimdol': {
                    'scenario_name': '디딤돌 대출 상담',
                    'stages': {'welcome': {'prompt': 'test'}}
                }
            }
            
            yield {
                'rag': mock_rag,
                'web': mock_web,
                'prompts': mock_prompts,
                'scenarios': mock_scenarios
            }
    
    @pytest.mark.asyncio
    async def test_context_awareness_in_conversation(self, validator, mock_services):
        """Test that agent maintains context across multiple turns."""
        # Build conversation history
        conversation_history = [
            HumanMessage(content="디딤돌 대출 상담 받고 싶어요"),
            AIMessage(content="네, 디딤돌 대출 상담을 도와드리겠습니다. 어떤 부분이 궁금하신가요?"),
            HumanMessage(content="자격 조건이 어떻게 되나요?"),
            AIMessage(content="디딤돌 대출은 만39세 이하 청년층을 대상으로 합니다."),
            HumanMessage(content="그럼 필요한 서류는 뭔가요?")
        ]
        
        # Mock RAG response that shows context awareness
        mock_services['rag'].answer_question.return_value = (
            "디딤돌 대출 신청을 위해서는 다음 서류가 필요합니다: "
            "신분증, 주민등록등본, 재직증명서, 소득증명서, "
            "부동산매매계약서 등입니다."
        )
        
        state = {
            "user_input_text": "그럼 필요한 서류는 뭔가요?",
            "messages": conversation_history,
            "stt_result": "그럼 필요한 서류는 뭔가요?",
            "current_product_type": "didimdol",
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result = await factual_answer_node(state)
        response = result["factual_response"]
        
        # Validate context-aware response
        assert validator.validate_politeness(response), "Response should use polite Korean"
        assert '서류' in response, "Should answer about documents"
        assert '디딤돌' in response, "Should maintain product context"
        assert '신분증' in response or '증명서' in response, "Should list specific documents"
    
    @pytest.mark.asyncio
    async def test_product_switching_in_conversation(self, validator, mock_services):
        """Test switching between different products in the same conversation."""
        # User starts with didimdol, then asks about jeonse
        user_input = "디딤돌 대출 말고 전세자금대출도 있나요? 그것도 설명해 주세요."
        
        # Mock RAG response that addresses product switching
        mock_services['rag'].answer_question.return_value = (
            "네, 전세자금대출도 있습니다. "
            "디딤돌 대출은 주택 구입용이고, 전세자금대출은 전세 보증금 마련용입니다. "
            "전세자금대출은 보증금의 80% 이내에서 대출이 가능합니다."
        )
        
        state = {
            "user_input_text": user_input,
            "messages": [
                HumanMessage(content="디딤돌 대출 상담 받고 싶어요"),
                AIMessage(content="디딤돌 대출을 안내해 드리겠습니다."),
                HumanMessage(content=user_input)
            ],
            "stt_result": user_input,
            "current_product_type": "didimdol",
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result = await factual_answer_node(state)
        response = result["factual_response"]
        
        # Validate product comparison response
        assert validator.validate_politeness(response), "Response should use polite Korean"
        assert '디딤돌' in response, "Should mention didimdol"
        assert '전세' in response, "Should mention jeonse"
        assert '차이' in response or '다른' in response or '구입' in response, "Should explain differences"