import pytest
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
import tempfile
import json

# Add backend to Python path for testing
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from backend.app.graph.state import AgentState
from backend.app.graph.models import ActionModel
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_environment():
    """Set up test environment variables."""
    original_env = os.environ.copy()
    
    # Set test environment variables
    os.environ["OPENAI_API_KEY"] = "test-api-key"
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/path/to/test/credentials.json"
    os.environ["TAVILY_API_KEY"] = "test-tavily-key"
    
    yield
    
    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def mock_fastapi_app():
    """Create a mock FastAPI app for testing."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    
    app = FastAPI()
    return TestClient(app)


@pytest.fixture
def sample_conversation_session():
    """Create a sample conversation session for testing."""
    return {
        "session_id": "test_session_001",
        "messages": [
            HumanMessage(content="안녕하세요"),
            AIMessage(content="안녕하세요! 디딤돌 음성 상담 에이전트입니다. 무엇을 도와드릴까요?"),
            HumanMessage(content="디딤돌 대출에 대해 알려주세요")
        ],
        "current_product_type": None,
        "current_scenario_stage_id": None,
        "collected_product_info": {},
        "conversation_state": "active"
    }


@pytest.fixture
def complete_scenario_data():
    """Create comprehensive scenario data for testing."""
    return {
        "didimdol": {
            "scenario_name": "디딤돌 대출 상담",
            "initial_stage_id": "welcome",
            "end_scenario_message": "디딤돌 대출 상담을 완료했습니다. 감사합니다.",
            "stages": {
                "welcome": {
                    "prompt": "안녕하세요! 디딤돌 대출 상담을 시작하겠습니다. 어떤 도움이 필요하신가요?",
                    "expected_info_key": "inquiry_type",
                    "choices": ["금리 문의", "한도 문의", "신청 방법", "기타"],
                    "transitions": [
                        {"condition": "inquiry_type == '금리 문의'", "next_stage": "interest_rate_info"},
                        {"condition": "inquiry_type == '한도 문의'", "next_stage": "loan_limit_info"},
                        {"condition": "inquiry_type == '신청 방법'", "next_stage": "application_process"},
                        {"condition": "inquiry_type == '기타'", "next_stage": "general_info"}
                    ],
                    "default_next_stage_id": "general_info"
                },
                "interest_rate_info": {
                    "prompt": "디딤돌 대출의 기본 금리는 연 %{base_rate}%입니다. 소득수준에 따라 우대금리가 적용됩니다. 추가 질문이 있으시면 말씀해 주세요.",
                    "expected_info_key": "additional_question",
                    "choices": ["우대금리 조건", "금리 계산 방법", "상담 종료"],
                    "transitions": [
                        {"condition": "additional_question == '우대금리 조건'", "next_stage": "preferential_rate"},
                        {"condition": "additional_question == '금리 계산 방법'", "next_stage": "rate_calculation"},
                        {"condition": "additional_question == '상담 종료'", "next_stage": "END_CONSULTATION"}
                    ],
                    "default_next_stage_id": "END_CONSULTATION"
                },
                "loan_limit_info": {
                    "prompt": "디딤돌 대출의 한도는 최대 2억원까지 가능합니다. 소득과 신용도에 따라 개인별 한도가 결정됩니다.",
                    "expected_info_key": "limit_inquiry",
                    "choices": ["개인 한도 계산", "한도 증액 방법", "상담 종료"],
                    "transitions": [
                        {"condition": "limit_inquiry == '개인 한도 계산'", "next_stage": "personal_limit"},
                        {"condition": "limit_inquiry == '한도 증액 방법'", "next_stage": "limit_increase"},
                        {"condition": "limit_inquiry == '상담 종료'", "next_stage": "END_CONSULTATION"}
                    ],
                    "default_next_stage_id": "END_CONSULTATION"
                },
                "application_process": {
                    "prompt": "디딤돌 대출 신청은 온라인 또는 영업점에서 가능합니다. 필요 서류와 절차를 안내해드리겠습니다.",
                    "expected_info_key": "application_method",
                    "choices": ["온라인 신청", "영업점 신청", "필요 서류", "상담 종료"],
                    "transitions": [
                        {"condition": "application_method == '온라인 신청'", "next_stage": "online_application"},
                        {"condition": "application_method == '영업점 신청'", "next_stage": "branch_application"},
                        {"condition": "application_method == '필요 서류'", "next_stage": "required_documents"},
                        {"condition": "application_method == '상담 종료'", "next_stage": "END_CONSULTATION"}
                    ],
                    "default_next_stage_id": "END_CONSULTATION"
                },
                "END_CONSULTATION": {
                    "prompt": "%{end_scenario_message}%",
                    "expected_info_key": None,
                    "transitions": [],
                    "default_next_stage_id": None
                }
            }
        },
        "jeonse": {
            "scenario_name": "전세 대출 상담",
            "initial_stage_id": "welcome",
            "end_scenario_message": "전세 대출 상담을 완료했습니다. 감사합니다.",
            "stages": {
                "welcome": {
                    "prompt": "전세 대출 상담을 시작합니다. 어떤 정보가 필요하신가요?",
                    "expected_info_key": "inquiry_type",
                    "choices": ["금리 문의", "한도 문의", "신청 자격"],
                    "transitions": [
                        {"condition": "inquiry_type == '금리 문의'", "next_stage": "interest_rate"},
                        {"condition": "inquiry_type == '한도 문의'", "next_stage": "loan_limit"},
                        {"condition": "inquiry_type == '신청 자격'", "next_stage": "eligibility"}
                    ],
                    "default_next_stage_id": "END_CONSULTATION"
                },
                "END_CONSULTATION": {
                    "prompt": "%{end_scenario_message}%",
                    "expected_info_key": None,
                    "transitions": [],
                    "default_next_stage_id": None
                }
            }
        }
    }


@pytest.fixture
def mock_knowledge_base_data():
    """Create mock knowledge base data for testing."""
    return {
        "didimdol_loan_info": """
# 디딤돌 대출 정보

## 개요
디딤돌 대출은 청년층의 주거 안정을 위한 정부 지원 대출 상품입니다.

## 대출 조건
- 대상: 만 19세 이상 34세 이하 청년
- 소득: 연소득 5천만원 이하
- 신용등급: 1~7등급

## 금리 정보
- 기본 금리: 연 2.5%
- 우대금리: 최대 0.5% 할인
- 변동금리 적용

## 대출 한도
- 최대 2억원
- 개인별 소득 및 신용도에 따라 차등 적용

## 신청 방법
1. 온라인 신청: 인터넷뱅킹 또는 모바일 앱
2. 영업점 방문: 가까운 지점 방문 신청
3. 전화 신청: 고객센터 1588-0000

## 필요 서류
- 신분증
- 소득증명서
- 재직증명서
- 주민등록등본
- 임대차계약서
""",
        "interest_rate_details": """
# 디딤돌 대출 금리 상세 정보

## 기본 금리
- 기준금리: 연 2.5%
- 적용 방식: 변동금리

## 우대금리 조건
1. 소득 구간별 우대
   - 연소득 3천만원 이하: 0.3% 할인
   - 연소득 2천만원 이하: 0.5% 할인

2. 신용등급별 우대
   - 1~3등급: 0.2% 할인
   - 4~6등급: 0.1% 할인

3. 기타 우대 조건
   - 청년 우대: 0.1% 할인
   - 장기 거주 우대: 0.1% 할인

## 금리 계산 예시
- 기본 상황: 연소득 4천만원, 신용등급 4등급
- 적용 금리: 2.5% - 0.1% = 2.4%
"""
    }


@pytest.fixture
def mock_web_search_results():
    """Create mock web search results for testing."""
    return [
        {
            "title": "2024년 디딤돌 대출 최신 정보",
            "url": "https://example.com/didimdol-2024",
            "content": "2024년 디딤돌 대출의 최신 정보를 제공합니다. 금리는 연 2.5%부터 시작하며..."
        },
        {
            "title": "청년 대출 상품 비교",
            "url": "https://example.com/youth-loans",
            "content": "다양한 청년 대출 상품을 비교 분석합니다. 디딤돌 대출의 장단점..."
        },
        {
            "title": "대출 신청 방법 안내",
            "url": "https://example.com/loan-application",
            "content": "온라인 대출 신청 방법을 단계별로 안내합니다. 필요 서류와 절차..."
        }
    ]


@pytest.fixture
def mock_audio_data():
    """Create mock audio data for testing."""
    return {
        "audio_base64": "mock_audio_base64_data",
        "sample_rate": 16000,
        "duration": 3.5,
        "text_transcript": "안녕하세요, 디딤돌 대출에 대해 알려주세요"
    }


@pytest.fixture
def integration_test_scenarios():
    """Create integration test scenarios covering various user flows."""
    return {
        "new_user_inquiry": {
            "description": "새로운 사용자가 디딤돌 대출에 대해 문의하는 시나리오",
            "steps": [
                {"input": "안녕하세요", "expected_type": "greeting"},
                {"input": "디딤돌 대출에 대해 알려주세요", "expected_type": "product_selection"},
                {"input": "금리가 궁금해요", "expected_type": "qa_response"},
                {"input": "신청하고 싶어요", "expected_type": "scenario_progression"}
            ]
        },
        "existing_user_followup": {
            "description": "기존 상담 중인 사용자의 추가 문의 시나리오",
            "steps": [
                {"input": "우대금리 조건이 궁금해요", "expected_type": "qa_response"},
                {"input": "제 소득으로 얼마까지 대출 가능한가요?", "expected_type": "qa_response"},
                {"input": "신청 방법을 알려주세요", "expected_type": "scenario_progression"}
            ]
        },
        "multi_product_comparison": {
            "description": "여러 상품을 비교하는 시나리오",
            "steps": [
                {"input": "디딤돌 대출과 전세 대출의 차이점이 뭔가요?", "expected_type": "qa_response"},
                {"input": "저에게 더 적합한 상품은 뭔가요?", "expected_type": "qa_response"},
                {"input": "전세 대출로 상담을 진행하고 싶어요", "expected_type": "product_selection"}
            ]
        },
        "error_recovery": {
            "description": "오류 상황에서의 복구 시나리오",
            "steps": [
                {"input": "잘못된 정보를 말씀드렸어요", "expected_type": "clarification"},
                {"input": "다시 처음부터 시작하고 싶어요", "expected_type": "reset"},
                {"input": "상담을 종료하고 싶어요", "expected_type": "end_conversation"}
            ]
        }
    }


@pytest.fixture
def performance_test_data():
    """Create data for performance testing."""
    return {
        "concurrent_users": 10,
        "requests_per_user": 5,
        "test_duration": 60,  # seconds
        "sample_inputs": [
            "디딤돌 대출 정보를 알려주세요",
            "금리가 얼마인가요?",
            "신청 방법을 알려주세요",
            "필요 서류가 뭔가요?",
            "한도는 얼마인가요?"
        ]
    }


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Clean up test data after each test."""
    yield
    # Add cleanup logic here if needed
    pass