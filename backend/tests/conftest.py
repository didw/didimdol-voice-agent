import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from pathlib import Path
import tempfile
import os
from typing import Dict, Any, List

from app.graph.state import AgentState
from app.graph.models import ActionModel
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_openai_api_key():
    """Mock OpenAI API key for testing."""
    return "test-api-key"


@pytest.fixture
def sample_agent_state():
    """Create a sample AgentState for testing."""
    return {
        "session_id": "test_session",
        "messages": [
            HumanMessage(content="안녕하세요, 디딤돌 대출에 대해 알려주세요."),
        ],
        "user_input_text": "안녕하세요, 디딤돌 대출에 대해 알려주세요.",
        "current_product_type": None,
        "current_scenario_stage_id": None,
        "collected_product_info": {},
        "available_product_types": ["didimdol", "jeonse", "deposit_account"],
        "action_plan": [],
        "action_plan_struct": [],
        "stt_result": None,
        "main_agent_routing_decision": None,
        "main_agent_direct_response": None,
        "scenario_agent_output": None,
        "final_response_text_for_tts": None,
        "is_final_turn_response": False,
        "error_message": None,
        "active_scenario_data": None,
        "active_knowledge_base_content": None,
        "loan_selection_is_fresh": False,
        "factual_response": None,
        "active_scenario_name": "Not Selected"
    }


@pytest.fixture
def sample_scenario_data():
    """Create sample scenario data for testing."""
    return {
        "scenario_name": "디딤돌 대출 상담",
        "initial_stage_id": "welcome",
        "end_scenario_message": "상담이 완료되었습니다. 감사합니다.",
        "stages": {
            "welcome": {
                "prompt": "안녕하세요! 디딤돌 대출 상담을 시작하겠습니다. 어떤 도움이 필요하신가요?",
                "expected_info_key": "inquiry_type",
                "choices": ["금리 문의", "한도 문의", "신청 방법"],
                "transitions": [
                    {"condition": "inquiry_type == '금리 문의'", "next_stage": "interest_rate"},
                    {"condition": "inquiry_type == '한도 문의'", "next_stage": "loan_limit"},
                    {"condition": "inquiry_type == '신청 방법'", "next_stage": "application_method"}
                ],
                "default_next_stage_id": "general_info"
            },
            "interest_rate": {
                "prompt": "디딤돌 대출 금리는 연 %{interest_rate}%입니다. 추가 질문이 있으시면 말씀해 주세요.",
                "expected_info_key": None,
                "transitions": [],
                "default_next_stage_id": "END_CONSULTATION"
            }
        }
    }


@pytest.fixture
def mock_llm():
    """Create a mock LLM for testing."""
    mock = AsyncMock()
    mock.ainvoke = AsyncMock()
    return mock


@pytest.fixture
def mock_rag_service():
    """Create a mock RAG service for testing."""
    mock = Mock()
    mock.is_ready = Mock(return_value=True)
    mock.answer_question = AsyncMock(return_value="디딤돌 대출은 청년층을 위한 정부 지원 대출입니다.")
    return mock


@pytest.fixture
def mock_web_search_service():
    """Create a mock web search service for testing."""
    mock = Mock()
    mock.asearch = AsyncMock(return_value="웹 검색 결과입니다.")
    return mock


@pytest.fixture
def mock_vector_store():
    """Create a mock vector store for testing."""
    mock = Mock()
    mock.as_retriever = Mock()
    mock.as_retriever.return_value.ainvoke = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def temp_data_dir():
    """Create a temporary directory with test data files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create test markdown files
        test_md_content = """# 디딤돌 대출 정보

## 개요
디딤돌 대출은 청년층을 위한 정부 지원 대출 상품입니다.

## 금리
- 기본 금리: 연 2.5%
- 우대 금리: 최대 0.5% 할인

## 대출 한도
- 최대 2억원까지 가능
"""
        
        test_file_path = Path(temp_dir) / "didimdol.md"
        test_file_path.write_text(test_md_content, encoding="utf-8")
        
        yield temp_dir


@pytest.fixture
def sample_action_plan():
    """Create a sample action plan for testing."""
    return [
        ActionModel(
            tool="invoke_qa_agent",
            tool_input={"query": "디딤돌 대출 정보"}
        ),
        ActionModel(
            tool="invoke_scenario_agent",
            tool_input={}
        )
    ]


@pytest.fixture
def mock_prompts():
    """Create mock prompts for testing."""
    return {
        "main_agent": {
            "initial_task_selection_prompt": """
사용자 입력: {user_input}
사용 가능한 상품: {available_product_types_list}

{format_instructions}
""",
            "router_prompt": """
사용자 입력: {user_input}
현재 상품: {active_scenario_name}

{format_instructions}
""",
            "determine_next_scenario_stage": """
현재 스테이지: {current_stage_id}
사용자 입력: {user_input}
수집된 정보: {collected_product_info}

{format_instructions}
"""
        },
        "qa_agent": {
            "rag_query_expansion_prompt": """
시나리오: {scenario_name}
채팅 기록: {chat_history}
사용자 질문: {user_question}

확장된 질문들을 생성하세요.
""",
            "simple_chitchat_prompt": """
사용자 입력: {user_input}

간단한 대화 응답을 생성하세요.
"""
        }
    }


@pytest.fixture
def mock_scenarios_data(sample_scenario_data):
    """Create mock scenarios data for testing."""
    return {
        "didimdol": sample_scenario_data,
        "jeonse": {
            "scenario_name": "전세 대출 상담",
            "initial_stage_id": "welcome",
            "stages": {
                "welcome": {
                    "prompt": "전세 대출 상담을 시작합니다.",
                    "expected_info_key": "property_type",
                    "transitions": [],
                    "default_next_stage_id": "END_CONSULTATION"
                }
            }
        }
    }


@pytest.fixture(autouse=True)
def mock_environment_variables(monkeypatch):
    """Mock environment variables for testing."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/path/to/test/credentials.json")


@pytest.fixture
def realistic_scenario_config():
    """Load realistic scenario configuration from YAML file."""
    import yaml
    config_path = Path(__file__).parent / "test_scenarios_config.yaml"
    
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    else:
        # Fallback configuration if YAML file doesn't exist
        return {
            "realistic_scenarios": {
                "didimdol_scenarios": {
                    "basic_info_inquiries": [
                        {
                            "question": "디딤돌 대출이 뭔가요?",
                            "expected_keywords": ["디딤돌", "청년", "대출"],
                            "validation_type": "didimdol_basic_info"
                        }
                    ]
                }
            }
        }


@pytest.fixture
def mock_comprehensive_services():
    """Create comprehensive mock services for realistic testing."""
    services = {}
    
    # Mock RAG Service
    rag_mock = Mock()
    rag_mock.is_ready.return_value = True
    rag_mock.answer_question = AsyncMock()
    services['rag'] = rag_mock
    
    # Mock Web Search Service  
    web_mock = Mock()
    web_mock.asearch = AsyncMock()
    services['web'] = web_mock
    
    # Mock LLM Services
    llm_mock = AsyncMock()
    json_llm_mock = AsyncMock()
    services['llm'] = llm_mock
    services['json_llm'] = json_llm_mock
    
    # Mock Prompts
    services['prompts'] = {
        'main_agent': {
            'initial_task_selection_prompt': 'test prompt',
            'router_prompt': 'test prompt',
            'determine_next_scenario_stage': 'test prompt',
            'chitchat_prompt': 'test prompt'
        },
        'qa_agent': {
            'rag_query_expansion_prompt': 'test prompt'
        }
    }
    
    # Mock Scenarios
    services['scenarios'] = {
        'didimdol': {
            'scenario_name': '디딤돌 대출 상담',
            'stages': {'welcome': {'prompt': 'test'}}
        },
        'jeonse': {
            'scenario_name': '전세자금대출 상담', 
            'stages': {'welcome': {'prompt': 'test'}}
        },
        'account': {
            'scenario_name': '입출금통장 개설',
            'stages': {'welcome': {'prompt': 'test'}}
        }
    }
    
    return services


@pytest.fixture
def conversation_context():
    """Create conversation context for multi-turn testing."""
    return {
        'session_id': 'test_session_123',
        'user_id': 'test_user',
        'conversation_history': [],
        'current_product_context': None,
        'collected_information': {},
        'conversation_stage': 'initial'
    }


@pytest.fixture
def korean_test_inputs():
    """Provide various Korean test inputs for edge case testing."""
    return {
        'polite_formal': [
            "디딤돌 대출에 대해 알려주세요.",
            "금리 정보를 문의드립니다.",
            "상담을 받고 싶습니다."
        ],
        'casual': [
            "디딤돌 대출 뭐야?",
            "금리 얼마야?",
            "대출 받을 수 있어?"
        ],
        'emotional': [
            "대출 떨어져서 너무 속상해요...",
            "집값이 너무 올라서 걱정이에요.",
            "정말 도움이 필요해요."
        ],
        'unclear': [
            "어... 그... 뭔가...",
            "대출 관련해서... 음...",
            "집... 그런거..."
        ],
        'numbers': [
            "5천만원 대출 받고 싶어요",
            "금리가 2.5프로 맞나요?",
            "한도가 삼억원인가요?"
        ],
        'mixed_language': [
            "디딤돌 loan 정보 주세요",
            "interest rate 얼마인가요?",
            "Account opening 하고 싶어요"
        ]
    }


@pytest.fixture
def performance_benchmarks():
    """Define performance benchmarks for testing."""
    return {
        'response_time': {
            'target_ms': 2000,
            'warning_ms': 5000,
            'error_ms': 10000
        },
        'accuracy_scores': {
            'excellent': 0.9,
            'good': 0.8,
            'acceptable': 0.7,
            'poor': 0.5
        },
        'conversation_quality': {
            'context_awareness': 0.8,
            'coherence': 0.85,
            'politeness': 0.95,
            'completeness': 0.8
        }
    }


@pytest.fixture
def test_report_config():
    """Configuration for test reporting."""
    return {
        'save_detailed_logs': True,
        'include_validation_details': True,
        'generate_performance_metrics': True,
        'export_formats': ['json', 'html'],
        'report_directory': Path(__file__).parent / 'reports'
    }


@pytest.fixture
def validator():
    """Create a RealisticScenarioValidator instance for testing."""
    # Import here to avoid circular import issues
    from tests.test_realistic_scenarios import RealisticScenarioValidator
    return RealisticScenarioValidator()


@pytest.fixture
def mock_services(mock_comprehensive_services):
    """Create comprehensive mock services for realistic scenario testing."""
    return mock_comprehensive_services


@pytest.fixture
def answer_validator():
    """Create an AnswerValidator instance for testing."""
    # Import here to avoid circular import issues  
    from tests.test_answer_validation import AnswerValidator
    return AnswerValidator()


# Create an alias for validator fixture for answer validation tests
@pytest.fixture
def answer_validation_validator():
    """Create an AnswerValidator instance for answer validation tests."""
    from tests.test_answer_validation import AnswerValidator
    return AnswerValidator()