"""
Answer validation system for testing 디딤돌 voice consultation agent responses.

This module provides comprehensive validation logic to ensure that agent responses
are accurate, appropriate, and meet quality standards for financial consultation.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
import json
import re
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from app.graph.agent import factual_answer_node, synthesize_response_node
from langchain_core.messages import HumanMessage, AIMessage


class ValidationResult(Enum):
    """Validation result status."""
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    SKIP = "SKIP"


@dataclass
class ValidationCriteria:
    """Criteria for validating agent responses."""
    question_type: str
    product_type: str
    required_keywords: List[str]
    forbidden_keywords: List[str]
    min_length: int
    max_length: int
    expected_tone: str  # formal, casual, empathetic
    must_include_numbers: bool
    must_be_polite: bool
    context_awareness_required: bool


@dataclass
class ValidationReport:
    """Detailed validation report."""
    result: ValidationResult
    score: float  # 0.0 to 1.0
    criteria_met: List[str]
    criteria_failed: List[str]
    warnings: List[str]
    details: Dict[str, Any]


class AnswerValidator:
    """Comprehensive answer validation system."""
    
    def __init__(self):
        self.validation_rules = self._initialize_validation_rules()
        self.polite_markers = [
            '습니다', '세요', '십니다', '요', '해요', '드려요', 
            '드립니다', '해드려요', '드리겠습니다', '하겠습니다'
        ]
        self.financial_keywords = {
            'didimdol': {
                'basic': ['디딤돌', '청년', '생애최초', '주택담보대출', '정부지원'],
                'eligibility': ['만39세', '연소득', '신용등급', '자격조건'],
                'rates': ['금리', '연', '%', '우대금리', '기준금리'],
                'limits': ['한도', '최대', '억원', '주택가격', '70%', '80%'],
                'documents': ['서류', '신분증', '소득증명', '재직증명', '주민등록'],
                'process': ['신청', '절차', '방법', '단계', '심사', '승인']
            },
            'jeonse': {
                'basic': ['전세자금대출', '전세', '보증금', '임차'],
                'eligibility': ['자격', '조건', '소득', '신용'],
                'rates': ['금리', '연', '%'],
                'limits': ['한도', '최대', '억원', '보증금의'],
                'documents': ['서류', '임대차계약서', '소득증명'],
                'process': ['신청', '절차', '방법', '단계']
            },
            'account': {
                'basic': ['입출금통장', '계좌개설', '예금계좌'],
                'features': ['체크카드', '인터넷뱅킹', '이체한도'],
                'benefits': ['수수료', '우대', '혜택'],
                'process': ['개설', '신청', '방법']
            }
        }
    
    def _initialize_validation_rules(self) -> Dict[str, ValidationCriteria]:
        """Initialize validation rules for different question types."""
        return {
            'didimdol_basic_info': ValidationCriteria(
                question_type='basic_info',
                product_type='didimdol',
                required_keywords=['디딤돌', '대출'],
                forbidden_keywords=['전세', '계좌개설'],
                min_length=50,
                max_length=500,
                expected_tone='formal',
                must_include_numbers=False,
                must_be_polite=True,
                context_awareness_required=False
            ),
            'didimdol_interest_rate': ValidationCriteria(
                question_type='interest_rate',
                product_type='didimdol',
                required_keywords=['금리', '%'],
                forbidden_keywords=[],
                min_length=30,
                max_length=300,
                expected_tone='formal',
                must_include_numbers=True,
                must_be_polite=True,
                context_awareness_required=False
            ),
            'didimdol_eligibility': ValidationCriteria(
                question_type='eligibility',
                product_type='didimdol',
                required_keywords=['자격', '조건'],
                forbidden_keywords=[],
                min_length=40,
                max_length=400,
                expected_tone='formal',
                must_include_numbers=False,
                must_be_polite=True,
                context_awareness_required=False
            ),
            'jeonse_basic_info': ValidationCriteria(
                question_type='basic_info',
                product_type='jeonse',
                required_keywords=['전세', '대출'],
                forbidden_keywords=['디딤돌', '계좌'],
                min_length=30,
                max_length=400,
                expected_tone='formal',
                must_include_numbers=False,
                must_be_polite=True,
                context_awareness_required=False
            ),
            'account_basic_info': ValidationCriteria(
                question_type='basic_info',
                product_type='account',
                required_keywords=['통장', '계좌'],
                forbidden_keywords=['대출'],
                min_length=20,
                max_length=300,
                expected_tone='formal',
                must_include_numbers=False,
                must_be_polite=True,
                context_awareness_required=False
            ),
            'off_topic': ValidationCriteria(
                question_type='off_topic',
                product_type='general',
                required_keywords=[],
                forbidden_keywords=[],
                min_length=10,
                max_length=200,
                expected_tone='polite',
                must_include_numbers=False,
                must_be_polite=True,
                context_awareness_required=False
            ),
            'multi_turn_context': ValidationCriteria(
                question_type='context_aware',
                product_type='any',
                required_keywords=[],
                forbidden_keywords=[],
                min_length=20,
                max_length=400,
                expected_tone='formal',
                must_include_numbers=False,
                must_be_polite=True,
                context_awareness_required=True
            )
        }
    
    def validate_response(
        self, 
        response: str, 
        validation_key: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> ValidationReport:
        """
        Validate a response against specific criteria.
        
        Args:
            response: The agent's response text
            validation_key: Key to identify validation criteria
            context: Additional context for validation (conversation history, etc.)
        
        Returns:
            ValidationReport with detailed results
        """
        if validation_key not in self.validation_rules:
            return ValidationReport(
                result=ValidationResult.SKIP,
                score=0.0,
                criteria_met=[],
                criteria_failed=[f"Unknown validation key: {validation_key}"],
                warnings=[],
                details={}
            )
        
        criteria = self.validation_rules[validation_key]
        criteria_met = []
        criteria_failed = []
        warnings = []
        score = 0.0
        total_checks = 8  # Number of validation checks
        
        # 1. Length validation
        if criteria.min_length <= len(response) <= criteria.max_length:
            criteria_met.append("Length within acceptable range")
            score += 1
        else:
            criteria_failed.append(f"Length {len(response)} not in range [{criteria.min_length}, {criteria.max_length}]")
        
        # 2. Required keywords validation
        missing_keywords = []
        for keyword in criteria.required_keywords:
            if keyword not in response:
                missing_keywords.append(keyword)
        
        if not missing_keywords:
            criteria_met.append("All required keywords present")
            score += 1
        else:
            criteria_failed.append(f"Missing required keywords: {missing_keywords}")
        
        # 3. Forbidden keywords validation
        found_forbidden = []
        for keyword in criteria.forbidden_keywords:
            if keyword in response:
                found_forbidden.append(keyword)
        
        if not found_forbidden:
            criteria_met.append("No forbidden keywords found")
            score += 1
        else:
            criteria_failed.append(f"Found forbidden keywords: {found_forbidden}")
        
        # 4. Politeness validation
        if criteria.must_be_polite:
            if any(marker in response for marker in self.polite_markers):
                criteria_met.append("Uses polite Korean expressions")
                score += 1
            else:
                criteria_failed.append("Lacks polite Korean expressions")
        else:
            score += 1  # Skip this check
        
        # 5. Number inclusion validation
        if criteria.must_include_numbers:
            number_pattern = r'[\d%.]+|[일이삼사오육칠팔구십백천만억]'
            if re.search(number_pattern, response):
                criteria_met.append("Includes numerical information")
                score += 1
            else:
                criteria_failed.append("Missing required numerical information")
        else:
            score += 1  # Skip this check
        
        # 6. Product-specific keyword validation
        if criteria.product_type in self.financial_keywords:
            product_keywords = self.financial_keywords[criteria.product_type].get(criteria.question_type, [])
            found_product_keywords = [kw for kw in product_keywords if kw in response]
            
            if found_product_keywords or not product_keywords:
                criteria_met.append(f"Contains relevant product keywords: {found_product_keywords}")
                score += 1
            else:
                warnings.append(f"Could include more specific product keywords: {product_keywords}")
                score += 0.5
        else:
            score += 1  # Skip this check
        
        # 7. Tone validation
        if criteria.expected_tone == 'formal':
            formal_markers = ['습니다', '십니다', '세요', '드립니다']
            if any(marker in response for marker in formal_markers):
                criteria_met.append("Uses appropriate formal tone")
                score += 1
            else:
                criteria_failed.append("Lacks formal tone markers")
        elif criteria.expected_tone == 'empathetic':
            empathy_markers = ['이해', '안타깝', '도움', '걱정', '마음']
            if any(marker in response for marker in empathy_markers):
                criteria_met.append("Shows empathetic tone")
                score += 1
            else:
                warnings.append("Could be more empathetic")
                score += 0.5
        else:
            score += 1  # Skip tone check for other types
        
        # 8. Context awareness validation
        if criteria.context_awareness_required and context:
            conversation_history = context.get('conversation_history', [])
            if len(conversation_history) > 1:
                # Check if response relates to previous context
                previous_topics = self._extract_topics_from_history(conversation_history)
                if any(topic in response for topic in previous_topics):
                    criteria_met.append("Shows context awareness")
                    score += 1
                else:
                    warnings.append("Could better reference previous conversation")
                    score += 0.5
            else:
                score += 1  # Skip if no context available
        else:
            score += 1  # Skip this check
        
        # Calculate final score
        final_score = score / total_checks
        
        # Determine overall result
        if final_score >= 0.9:
            result = ValidationResult.PASS
        elif final_score >= 0.7:
            result = ValidationResult.WARNING
        else:
            result = ValidationResult.FAIL
        
        return ValidationReport(
            result=result,
            score=final_score,
            criteria_met=criteria_met,
            criteria_failed=criteria_failed,
            warnings=warnings,
            details={
                'response_length': len(response),
                'validation_key': validation_key,
                'criteria': criteria.__dict__
            }
        )
    
    def _extract_topics_from_history(self, conversation_history: List[Any]) -> List[str]:
        """Extract topics from conversation history for context validation."""
        topics = []
        for message in conversation_history[-3:]:  # Check last 3 messages
            if hasattr(message, 'content'):
                content = message.content.lower()
                if '디딤돌' in content:
                    topics.append('디딤돌')
                if '전세' in content:
                    topics.append('전세')
                if '금리' in content:
                    topics.append('금리')
                if '한도' in content:
                    topics.append('한도')
        return topics
    
    def validate_conversation_flow(
        self, 
        conversation_turns: List[Tuple[str, str]], 
        expected_flow: List[str]
    ) -> ValidationReport:
        """
        Validate entire conversation flow against expected pattern.
        
        Args:
            conversation_turns: List of (user_input, agent_response) tuples
            expected_flow: Expected conversation flow pattern
        
        Returns:
            ValidationReport for conversation flow
        """
        criteria_met = []
        criteria_failed = []
        warnings = []
        score = 0.0
        
        # Check conversation length
        if len(conversation_turns) >= len(expected_flow):
            criteria_met.append("Conversation has adequate length")
            score += 0.2
        else:
            warnings.append("Conversation might be too short")
        
        # Check response relevance
        relevant_responses = 0
        for user_input, agent_response in conversation_turns:
            if self._is_response_relevant(user_input, agent_response):
                relevant_responses += 1
        
        relevance_ratio = relevant_responses / len(conversation_turns) if conversation_turns else 0
        if relevance_ratio >= 0.8:
            criteria_met.append("High response relevance")
            score += 0.3
        elif relevance_ratio >= 0.6:
            warnings.append("Some responses could be more relevant")
            score += 0.2
        else:
            criteria_failed.append("Low response relevance")
        
        # Check conversation coherence
        if self._check_conversation_coherence(conversation_turns):
            criteria_met.append("Conversation maintains coherence")
            score += 0.3
        else:
            criteria_failed.append("Conversation lacks coherence")
        
        # Check information progression
        if self._check_information_progression(conversation_turns):
            criteria_met.append("Information builds progressively")
            score += 0.2
        else:
            warnings.append("Information progression could be improved")
            score += 0.1
        
        # Determine result
        if score >= 0.8:
            result = ValidationResult.PASS
        elif score >= 0.6:
            result = ValidationResult.WARNING
        else:
            result = ValidationResult.FAIL
        
        return ValidationReport(
            result=result,
            score=score,
            criteria_met=criteria_met,
            criteria_failed=criteria_failed,
            warnings=warnings,
            details={
                'conversation_length': len(conversation_turns),
                'relevance_ratio': relevance_ratio
            }
        )
    
    def _is_response_relevant(self, user_input: str, agent_response: str) -> bool:
        """Check if agent response is relevant to user input."""
        user_keywords = self._extract_keywords(user_input)
        response_keywords = self._extract_keywords(agent_response)
        
        # Check keyword overlap
        overlap = set(user_keywords) & set(response_keywords)
        return len(overlap) > 0 or len(response_keywords) > 2
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text."""
        keywords = []
        important_terms = [
            '디딤돌', '전세', '대출', '금리', '한도', '조건', '서류', 
            '신청', '자격', '통장', '계좌', '체크카드'
        ]
        
        for term in important_terms:
            if term in text:
                keywords.append(term)
        
        return keywords
    
    def _check_conversation_coherence(self, conversation_turns: List[Tuple[str, str]]) -> bool:
        """Check if conversation maintains logical coherence."""
        if len(conversation_turns) < 2:
            return True
        
        # Simple coherence check: ensure responses don't contradict each other
        all_responses = [response for _, response in conversation_turns]
        
        # Check for contradictory statements
        contradictions = [
            ('가능합니다', '불가능합니다'),
            ('높습니다', '낮습니다'),
            ('필요합니다', '필요하지 않습니다')
        ]
        
        for positive, negative in contradictions:
            pos_count = sum(1 for response in all_responses if positive in response)
            neg_count = sum(1 for response in all_responses if negative in response)
            if pos_count > 0 and neg_count > 0:
                return False
        
        return True
    
    def _check_information_progression(self, conversation_turns: List[Tuple[str, str]]) -> bool:
        """Check if information builds progressively throughout conversation."""
        if len(conversation_turns) < 2:
            return True
        
        # Check if later responses build on earlier information
        early_responses = [response for _, response in conversation_turns[:len(conversation_turns)//2]]
        later_responses = [response for _, response in conversation_turns[len(conversation_turns)//2:]]
        
        early_keywords = set()
        for response in early_responses:
            early_keywords.update(self._extract_keywords(response))
        
        later_keywords = set()
        for response in later_responses:
            later_keywords.update(self._extract_keywords(response))
        
        # Later responses should either build on or complement early topics
        return len(early_keywords & later_keywords) > 0 or len(later_keywords - early_keywords) > 0


class TestAnswerValidationSystem:
    """Test the answer validation system itself."""
    
    @pytest.fixture
    def validator(self):
        return AnswerValidator()
    
    def test_validator_initialization(self, validator):
        """Test that validator initializes correctly."""
        assert validator is not None
        assert len(validator.validation_rules) > 0
        assert len(validator.polite_markers) > 0
        assert len(validator.financial_keywords) > 0
    
    def test_excellent_response_validation(self, validator):
        """Test validation of an excellent response."""
        excellent_response = (
            "디딤돌 대출은 만39세 이하 청년층을 위한 생애최초 주택담보대출로, "
            "정부지원을 받아 저금리로 제공됩니다. 기본 금리는 연 2.5%부터 시작하며, "
            "소득수준에 따라 우대금리가 적용됩니다. 자세한 상담을 도와드리겠습니다."
        )
        
        result = validator.validate_response(excellent_response, 'didimdol_basic_info')
        
        assert result.result == ValidationResult.PASS
        assert result.score >= 0.8
        assert "All required keywords present" in result.criteria_met
        assert "Uses polite Korean expressions" in result.criteria_met
    
    def test_poor_response_validation(self, validator):
        """Test validation of a poor response."""
        poor_response = "몰라요"
        
        result = validator.validate_response(poor_response, 'didimdol_basic_info')
        
        assert result.result == ValidationResult.FAIL
        assert result.score < 0.5
        assert len(result.criteria_failed) > 0
    
    def test_number_validation(self, validator):
        """Test validation of responses requiring numbers."""
        response_with_numbers = "디딤돌 대출의 기본 금리는 연 2.5%입니다."
        response_without_numbers = "디딤돌 대출의 금리는 낮습니다."
        
        result_with = validator.validate_response(response_with_numbers, 'didimdol_interest_rate')
        result_without = validator.validate_response(response_without_numbers, 'didimdol_interest_rate')
        
        assert "Includes numerical information" in result_with.criteria_met
        assert "Missing required numerical information" in result_without.criteria_failed
    
    def test_forbidden_keywords_validation(self, validator):
        """Test validation catches forbidden keywords."""
        response_with_forbidden = "디딤돌 대출은 전세자금대출과 같습니다."
        
        result = validator.validate_response(response_with_forbidden, 'didimdol_basic_info')
        
        assert any("forbidden keywords" in failure for failure in result.criteria_failed)
    
    def test_conversation_flow_validation(self, validator):
        """Test conversation flow validation."""
        good_conversation = [
            ("디딤돌 대출에 대해 알려주세요", "디딤돌 대출은 청년층을 위한 대출입니다."),
            ("금리는 어떻게 되나요?", "기본 금리는 연 2.5%입니다."),
            ("신청 방법을 알려주세요", "신청서와 필요서류를 준비하시면 됩니다.")
        ]
        
        result = validator.validate_conversation_flow(good_conversation, ['info', 'details', 'process'])
        
        assert result.result in [ValidationResult.PASS, ValidationResult.WARNING]
        assert result.score > 0.5


class TestIntegratedValidationScenarios:
    """Test integrated validation scenarios with realistic agent responses."""
    
    @pytest.fixture
    def validator(self):
        return AnswerValidator()
    
    @pytest.fixture
    def mock_services(self):
        """Mock external services for testing."""
        with patch('app.graph.agent.rag_service') as mock_rag, \
             patch('app.graph.agent.ALL_PROMPTS') as mock_prompts:
            
            mock_rag.is_ready.return_value = True
            mock_rag.answer_question = AsyncMock()
            mock_prompts.return_value = {"qa_agent": {"rag_query_expansion_prompt": "test"}}
            
            yield {'rag': mock_rag, 'prompts': mock_prompts}
    
    @pytest.mark.asyncio
    async def test_validate_real_agent_response_didimdol_basic(self, validator, mock_services):
        """Test validation of real agent response for 디딤돌 basic info."""
        # Mock realistic RAG response
        mock_services['rag'].answer_question.return_value = (
            "디딤돌 대출은 만39세 이하 청년층을 대상으로 한 생애최초 주택담보대출입니다. "
            "정부지원을 받아 시중은행 대비 저금리로 제공되며, 주택가격의 70% 이내에서 "
            "최대 4억원까지 대출이 가능합니다. 자세한 상담을 도와드리겠습니다."
        )
        
        state = {
            "user_input_text": "디딤돌 대출이 뭔가요?",
            "messages": [HumanMessage(content="디딤돌 대출이 뭔가요?")],
            "stt_result": "디딤돌 대출이 뭔가요?",
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result = await factual_answer_node(state)
        response = result["factual_response"]
        
        # Validate the response
        validation_result = validator.validate_response(response, 'didimdol_basic_info')
        
        # Assert validation passes
        assert validation_result.result in [ValidationResult.PASS, ValidationResult.WARNING]
        assert validation_result.score >= 0.7
        assert any("디딤돌" in criterion for criterion in validation_result.criteria_met)
        
        # Print detailed validation results for debugging
        print(f"\nValidation Score: {validation_result.score:.2f}")
        print(f"Result: {validation_result.result.value}")
        print(f"Criteria Met: {validation_result.criteria_met}")
        if validation_result.criteria_failed:
            print(f"Criteria Failed: {validation_result.criteria_failed}")
        if validation_result.warnings:
            print(f"Warnings: {validation_result.warnings}")
    
    @pytest.mark.asyncio
    async def test_validate_real_agent_response_interest_rate(self, validator, mock_services):
        """Test validation of real agent response for interest rate inquiry."""
        # Mock realistic RAG response with numbers
        mock_services['rag'].answer_question.return_value = (
            "디딤돌 대출의 기본 금리는 연 2.5%부터 시작하며, "
            "소득수준과 신용등급에 따라 우대금리 최대 0.5%가 추가로 적용됩니다. "
            "현재 시중은행 주택담보대출 대비 0.5~1.0% 낮은 수준입니다."
        )
        
        state = {
            "user_input_text": "디딤돌 대출 금리가 어떻게 되나요?",
            "messages": [HumanMessage(content="디딤돌 대출 금리가 어떻게 되나요?")],
            "stt_result": "디딤돌 대출 금리가 어떻게 되나요?",
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result = await factual_answer_node(state)
        response = result["factual_response"]
        
        # Validate the response
        validation_result = validator.validate_response(response, 'didimdol_interest_rate')
        
        # Assert validation passes
        assert validation_result.result in [ValidationResult.PASS, ValidationResult.WARNING]
        assert validation_result.score >= 0.7
        assert any("numerical information" in criterion for criterion in validation_result.criteria_met)
    
    @pytest.mark.asyncio
    async def test_validate_multi_turn_conversation(self, validator, mock_services):
        """Test validation of multi-turn conversation."""
        # Setup conversation history
        conversation_turns = []
        
        # First turn - basic info
        mock_services['rag'].answer_question.return_value = (
            "디딤돌 대출은 청년층을 위한 생애최초 주택담보대출입니다."
        )
        
        state1 = {
            "user_input_text": "디딤돌 대출에 대해 알려주세요",
            "messages": [HumanMessage(content="디딤돌 대출에 대해 알려주세요")],
            "stt_result": "디딤돌 대출에 대해 알려주세요",
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result1 = await factual_answer_node(state1)
        conversation_turns.append(("디딤돌 대출에 대해 알려주세요", result1["factual_response"]))
        
        # Second turn - follow-up about interest rate
        mock_services['rag'].answer_question.return_value = (
            "디딤돌 대출의 기본 금리는 연 2.5%부터 시작합니다."
        )
        
        conversation_history = [
            HumanMessage(content="디딤돌 대출에 대해 알려주세요"),
            AIMessage(content=result1["factual_response"]),
            HumanMessage(content="그럼 금리는 어떻게 되나요?")
        ]
        
        state2 = {
            "user_input_text": "그럼 금리는 어떻게 되나요?",
            "messages": conversation_history,
            "stt_result": "그럼 금리는 어떻게 되나요?",
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        result2 = await factual_answer_node(state2)
        conversation_turns.append(("그럼 금리는 어떻게 되나요?", result2["factual_response"]))
        
        # Validate conversation flow
        flow_validation = validator.validate_conversation_flow(
            conversation_turns, 
            ['basic_info', 'interest_rate']
        )
        
        assert flow_validation.result in [ValidationResult.PASS, ValidationResult.WARNING]
        assert flow_validation.score >= 0.6
        
        # Validate individual responses with context
        context = {'conversation_history': conversation_history}
        second_response_validation = validator.validate_response(
            result2["factual_response"], 
            'multi_turn_context', 
            context
        )
        
        assert second_response_validation.result in [ValidationResult.PASS, ValidationResult.WARNING]