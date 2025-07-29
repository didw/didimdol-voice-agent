"""
Entity Agent 유사도 매칭 기능 테스트
"""

import pytest
from unittest.mock import AsyncMock, patch
from app.agents.entity_agent import EntityRecognitionAgent


@pytest.fixture
def entity_agent():
    """EntityRecognitionAgent 인스턴스 생성"""
    return EntityRecognitionAgent()


@pytest.fixture
def mock_llm_response():
    """LLM 응답 모킹을 위한 fixture"""
    def _mock_response(content):
        mock = AsyncMock()
        mock.content = content
        return mock
    return _mock_response


@pytest.mark.asyncio
async def test_similarity_matching_high_score(entity_agent, mock_llm_response):
    """높은 유사도 점수로 매칭 성공하는 경우"""
    
    field = {
        'key': 'account_type',
        'display_name': '계좌 종류',
        'type': 'choice',
        'choices': ['입출금통장', '예금', '적금']
    }
    
    # LLM이 높은 유사도로 매칭
    mock_response = mock_llm_response("""
    {
        "best_match": "입출금통장",
        "similarity_score": 0.85,
        "reasoning": "사용자가 '통장'이라고 말했고, 이는 '입출금통장'을 의미할 가능성이 높습니다.",
        "alternative_matches": []
    }
    """)
    
    with patch('app.agents.entity_agent.json_llm.ainvoke', return_value=mock_response):
        result = await entity_agent.match_with_similarity("통장 개설하려고요", field)
    
    assert result['matched'] is True
    assert result['value'] == '입출금통장'
    assert result['score'] == 0.85
    assert result['need_retry'] is False


@pytest.mark.asyncio
async def test_similarity_matching_low_score(entity_agent, mock_llm_response):
    """낮은 유사도 점수로 재질문이 필요한 경우"""
    
    field = {
        'key': 'account_type',
        'display_name': '계좌 종류',
        'type': 'choice',
        'choices': ['입출금통장', '예금', '적금']
    }
    
    # LLM이 낮은 유사도로 매칭 실패
    mock_response = mock_llm_response("""
    {
        "best_match": "입출금통장",
        "similarity_score": 0.2,
        "reasoning": "사용자 입력이 계좌 종류와 관련이 없어 보입니다.",
        "alternative_matches": []
    }
    """)
    
    with patch('app.agents.entity_agent.json_llm.ainvoke', return_value=mock_response):
        result = await entity_agent.match_with_similarity("커피 한잔", field)
    
    assert result['matched'] is False
    assert result['value'] is None
    assert result['score'] == 0.2
    assert result['need_retry'] is True
    assert '선택 가능한 옵션' in result['message']


@pytest.mark.asyncio
async def test_similarity_matching_medium_score(entity_agent, mock_llm_response):
    """중간 유사도 점수로 확인이 필요한 경우"""
    
    field = {
        'key': 'account_type',
        'display_name': '계좌 종류',
        'type': 'choice',
        'choices': ['입출금통장', '예금', '적금']
    }
    
    # LLM이 중간 유사도로 매칭
    mock_response = mock_llm_response("""
    {
        "best_match": "예금",
        "similarity_score": 0.6,
        "reasoning": "정기적인 것을 원한다는 표현이 예금과 관련될 수 있습니다.",
        "alternative_matches": [
            {"value": "적금", "score": 0.5}
        ]
    }
    """)
    
    with patch('app.agents.entity_agent.json_llm.ainvoke', return_value=mock_response):
        result = await entity_agent.match_with_similarity("정기적으로 넣는 거", field)
    
    assert result['matched'] is False
    assert result['value'] == '예금'
    assert result['score'] == 0.6
    assert result['need_retry'] is True
    assert '예금' in result['message']
    assert '적금' in result['message']


@pytest.mark.asyncio
async def test_extract_entities_with_similarity_integration(entity_agent, mock_llm_response):
    """extract_entities_with_similarity 통합 테스트"""
    
    required_fields = [
        {
            'key': 'customer_name',
            'display_name': '고객명',
            'type': 'text',
            'required': True
        },
        {
            'key': 'account_type',
            'display_name': '계좌 종류',
            'type': 'choice',
            'choices': ['입출금통장', '예금', '적금'],
            'required': True
        }
    ]
    
    # 첫 번째 LLM 호출 - 기본 엔티티 추출
    extract_response = mock_llm_response("""
    {
        "extracted_fields": {
            "customer_name": "김철수"
        },
        "confidence": 0.9
    }
    """)
    
    # 두 번째 LLM 호출 - 유사도 매칭
    similarity_response = mock_llm_response("""
    {
        "best_match": "입출금통장",
        "similarity_score": 0.8,
        "reasoning": "자유입출금이라는 표현은 입출금통장을 의미합니다.",
        "alternative_matches": []
    }
    """)
    
    with patch('app.agents.entity_agent.json_llm.ainvoke', side_effect=[extract_response, similarity_response]):
        result = await entity_agent.extract_entities_with_similarity(
            "김철수입니다. 자유입출금 계좌 만들고 싶어요", 
            required_fields
        )
    
    assert result['extracted_entities']['customer_name'] == '김철수'
    assert result['extracted_entities']['account_type'] == '입출금통장'
    assert len(result['similarity_messages']) == 0  # 높은 유사도로 매칭됨


@pytest.mark.asyncio
async def test_process_slot_filling_with_similarity(entity_agent, mock_llm_response):
    """process_slot_filling이 유사도 매칭을 포함하여 작동하는지 테스트"""
    
    required_fields = [
        {
            'key': 'transfer_type',
            'display_name': '이체 종류',
            'type': 'choice',
            'choices': ['당행이체', '타행이체', '해외송금'],
            'required': True
        }
    ]
    
    collected_info = {}
    
    # 엔티티 추출 응답
    extract_response = mock_llm_response("""
    {
        "extracted_fields": {},
        "confidence": 0.5
    }
    """)
    
    # 유사도 매칭 응답
    similarity_response = mock_llm_response("""
    {
        "best_match": "타행이체",
        "similarity_score": 0.25,
        "reasoning": "다른 은행이라는 표현이 타행이체와 관련될 수 있으나 확실하지 않습니다.",
        "alternative_matches": []
    }
    """)
    
    # 검증 응답
    validation_response = mock_llm_response("""
    {
        "valid_entities": {},
        "invalid_entities": {},
        "need_clarification": []
    }
    """)
    
    with patch('app.agents.entity_agent.json_llm.ainvoke', side_effect=[extract_response, similarity_response, validation_response]):
        result = await entity_agent.process_slot_filling(
            "다른 데로 보내고 싶어요",
            required_fields,
            collected_info
        )
    
    assert result['need_clarification'] is True
    assert '선택 가능한 옵션' in result['clarification_message']
    assert '당행이체' in result['clarification_message']
    assert '타행이체' in result['clarification_message']
    assert '해외송금' in result['clarification_message']


@pytest.mark.asyncio
async def test_non_choice_field_skipped(entity_agent):
    """choice 타입이 아닌 필드는 유사도 매칭을 건너뛰는지 테스트"""
    
    field = {
        'key': 'customer_name',
        'display_name': '고객명',
        'type': 'text'  # choice가 아님
    }
    
    result = await entity_agent.match_with_similarity("김철수", field)
    
    assert result['matched'] is False
    assert result['value'] is None
    assert result['score'] == 0.0
    assert result['need_retry'] is False