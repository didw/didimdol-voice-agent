# Testing Guide for 디딤돌 Voice Agent

This document provides comprehensive testing instructions for the 디딤돌 Voice Consultation Agent project.

## 📋 Overview

The project includes two levels of testing:

1. **Backend Unit Tests** (`backend/tests/`) - Test individual components and modules
2. **Integration Tests** (`tests/`) - Test complete workflows and system interactions

## 🚀 Quick Start

### Install Test Dependencies

```bash
# Install test dependencies for the entire project
pip install -r requirements-test.txt

# Or install backend-specific test dependencies
pip install -r backend/requirements-test.txt
```

### Run Tests

```bash
# Run all tests
python test_runner.py all

# Run quick tests
python test_runner.py quick

# Run specific test types
python test_runner.py unit           # Backend unit tests
python test_runner.py integration   # Integration tests
python test_runner.py e2e           # End-to-end tests
```

## 🧪 Test Categories

### Backend Unit Tests

Located in `backend/tests/`, these tests focus on individual components:

- **Agent Routing Tests** (`test_agent_routing.py`) - LangGraph agent node functions
- **RAG Pipeline Tests** (`test_rag_pipeline.py`) - Vector store and RAG functionality  
- **Services Tests** (`test_services.py`) - RAG and web search services
- **QA Scenarios Tests** (`test_qa_scenarios.py`) - Question answering and scenarios
- **Realistic Scenarios Tests** (`test_realistic_scenarios.py`) - Real Korean conversation patterns
- **Edge Cases Tests** (`test_edge_cases.py`) - Error handling and boundary conditions
- **Answer Validation Tests** (`test_answer_validation.py`) - Response quality assessment

```bash
# Run backend unit tests
cd backend
python test_runner.py unit

# Run specific test files
python -m pytest tests/test_agent_routing.py -v

# Run realistic conversation scenarios
python -m pytest tests/test_realistic_scenarios.py -v

# Run edge case tests
python -m pytest tests/test_edge_cases.py -v

# Run answer validation tests
python -m pytest tests/test_answer_validation.py -v

# Run comprehensive test suite with validation
python tests/comprehensive_test_runner.py --verbose
```

### Integration Tests

Located in `tests/`, these tests cover complete system workflows:

- **Agent Flow Tests** (`test_integration_agent_flows.py`) - Complete conversation flows
- **API Endpoint Tests** (`test_integration_api_endpoints.py`) - FastAPI and WebSocket testing
- **End-to-End Tests** (`test_integration_end_to_end.py`) - Full system scenarios

```bash
# Run integration tests
python test_runner.py integration

# Run end-to-end tests
python test_runner.py e2e

# Run API tests
python test_runner.py api
```

## 🔧 Test Configuration

### Backend Tests (`backend/pytest.ini`)

```ini
[tool:pytest]
testpaths = tests
asyncio_mode = auto
addopts = --cov=app --cov-fail-under=80
markers =
    unit: Unit tests
    integration: Integration tests
    slow: Slow running tests
```

### Integration Tests (`pytest.ini`)

```ini
[tool:pytest]
testpaths = tests
asyncio_mode = auto
addopts = --cov=backend/app --cov-fail-under=70
markers =
    integration: Integration tests
    e2e: End-to-end tests
    performance: Performance tests
```

## 📊 Coverage Reports

### Generate Coverage Reports

```bash
# Full coverage report
python test_runner.py coverage

# Backend coverage only
cd backend
python test_runner.py coverage
```

Coverage reports are generated in:
- `backend/htmlcov/` - Backend unit test coverage
- `htmlcov/` - Integration test coverage

### Coverage Targets

- **Backend Unit Tests**: 80% minimum coverage
- **Integration Tests**: 70% minimum coverage

## 🎯 Test Markers

Use pytest markers to run specific test categories:

```bash
# Backend markers
python -m pytest -m unit          # Unit tests only
python -m pytest -m "not slow"    # Skip slow tests
python -m pytest -m agent         # Agent-related tests

# Integration markers  
python -m pytest -m integration   # Integration tests
python -m pytest -m e2e          # End-to-end tests
python -m pytest -m performance  # Performance tests
```

## 🏃‍♂️ Running Tests

### Command Line Options

```bash
# Parallel execution
python test_runner.py unit --parallel

# Verbose output
python test_runner.py integration --verbose

# Stop on first failure
python test_runner.py all --failfast

# Concurrent backend and integration tests
python test_runner.py quick --concurrent
```

### Direct pytest Usage

```bash
# Backend unit tests
cd backend
python -m pytest tests/ -v

# Integration tests
python -m pytest tests/ -v

# Specific test file
python -m pytest tests/test_agent_routing.py::TestEntryPointNode::test_basic_functionality -v
```

## 🧹 Code Quality

### Linting and Formatting

```bash
# Run all code quality checks
python test_runner.py lint

# Individual tools
python -m black backend/app/ tests/
python -m isort backend/app/ tests/
python -m flake8 backend/app/ tests/
python -m mypy backend/app/
```

### Pre-commit Hooks

```bash
# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Run on all files
pre-commit run --all-files
```

## 🚀 Performance Testing

### Basic Performance Tests

```bash
# Run performance tests
python test_runner.py performance

# Benchmark specific functions
python -m pytest tests/ -m performance --benchmark-only
```

### Load Testing

The integration tests include concurrent session testing:

```python
# Example from test_integration_end_to_end.py
@pytest.mark.asyncio
async def test_concurrent_user_sessions():
    # Tests 5 concurrent user sessions
    # Verifies system handles multiple users
```

## 🐛 Debugging Tests

### Verbose Output

```bash
# Maximum verbosity
python -m pytest tests/ -vvv

# Show local variables on failure
python -m pytest tests/ -l

# Drop into debugger on failure
python -m pytest tests/ --pdb
```

### Test Data

Test fixtures provide comprehensive mock data:

- `sample_agent_state` - Mock conversation state
- `complete_scenario_data` - Full scenario definitions
- `mock_knowledge_base_data` - RAG test data
- `mock_web_search_results` - Web search responses

## 📝 Writing New Tests

### Backend Unit Test Example

```python
# backend/tests/test_my_feature.py
import pytest
from unittest.mock import Mock, AsyncMock

class TestMyFeature:
    @pytest.mark.asyncio
    async def test_my_async_function(self, sample_agent_state):
        # Test implementation
        result = await my_async_function(sample_agent_state)
        assert result is not None
```

### Integration Test Example

```python
# tests/test_my_integration.py
import pytest
from backend.app.graph.agent import run_agent_streaming

class TestMyIntegration:
    @pytest.mark.asyncio
    async def test_complete_flow(self, full_system_mocks):
        responses = []
        async for response in run_agent_streaming(
            user_input_text="test input",
            session_id="test_session"
        ):
            responses.append(response)
        
        assert len(responses) > 0
```

## 🔍 Test Organization

```
didimdol-voice-agent/
├── backend/tests/           # Backend unit tests
│   ├── conftest.py         # Backend test fixtures
│   ├── test_agent_routing.py
│   ├── test_rag_pipeline.py
│   ├── test_services.py
│   └── test_qa_scenarios.py
├── tests/                  # Integration tests
│   ├── conftest.py         # Integration test fixtures
│   ├── test_integration_agent_flows.py
│   ├── test_integration_api_endpoints.py
│   └── test_integration_end_to_end.py
├── pytest.ini             # Root test configuration
├── backend/pytest.ini     # Backend test configuration
└── test_runner.py         # Main test runner
```

## 🎭 Advanced Testing Features

### Realistic Korean Conversation Testing

Our comprehensive test suite includes realistic Korean conversation scenarios:

#### 디딤돌 대출 (Didimdol Loan) Scenarios
```python
# Example realistic scenario test
@pytest.mark.asyncio
async def test_didimdol_basic_info_inquiry(self, validator, mock_services):
    user_input = "디딤돌 대출이 뭔가요? 처음 들어보는데 자세히 알려주세요."
    
    # Test agent response
    result = await factual_answer_node(state)
    response = result["factual_response"]
    
    # Validate response quality
    validation = validator.validate_response(response, 'didimdol_basic_info')
    assert validation['valid']
    assert validator.validate_politeness(response)
```

#### Test Categories
- **Basic Information**: Product overview and fundamental details
- **Interest Rates**: Rate inquiries with numerical validation
- **Eligibility**: Personal qualification assessments
- **Documents**: Required paperwork information
- **Multi-turn Conversations**: Context-aware dialogue testing

### Answer Validation System

Advanced response quality assessment:

```python
# Validation criteria example
validation_result = validator.validate_response(
    response="디딤돌 대출은 만39세 이하 청년층을 위한 생애최초 주택담보대출입니다.",
    validation_key='didimdol_basic_info'
)

# Results include:
# - Overall quality score (0.0-1.0)
# - Keyword coverage analysis
# - Korean politeness markers
# - Content completeness
# - Context awareness
```

#### Validation Dimensions
1. **Content Accuracy**: Required keywords and information
2. **Korean Language Quality**: Politeness and formal tone
3. **Completeness**: Comprehensive answers
4. **Context Awareness**: Multi-turn conversation coherence
5. **Numerical Accuracy**: Rates, amounts, and limits

### Edge Case Testing

Comprehensive error handling and boundary condition testing:

- **Service Failures**: RAG/LLM/Web search unavailability
- **Input Variations**: Empty, very long, special characters
- **Performance Limits**: Concurrent requests, memory pressure
- **Security**: Input sanitization and injection attempts
- **Korean Language**: Mixed languages, number formats

### Configuration-Driven Testing

Tests are configured via `test_scenarios_config.yaml`:

```yaml
realistic_scenarios:
  didimdol_scenarios:
    basic_info_inquiries:
      - question: "디딤돌 대출이 뭔가요?"
        expected_keywords: ["디딤돌", "청년", "생애최초"]
        validation_type: "didimdol_basic_info"
        context: "first_time_inquiry"
```

### Comprehensive Test Runner

Execute all tests with detailed reporting:

```bash
# Run comprehensive test suite
python tests/comprehensive_test_runner.py

# Options
python tests/comprehensive_test_runner.py --verbose    # Detailed output
python tests/comprehensive_test_runner.py --quick     # Fast subset
python tests/comprehensive_test_runner.py --no-save   # Skip reports
```

### Test Reports and Analytics

Automated generation of detailed test reports:

- **Overall Statistics**: Pass/fail rates, coverage metrics
- **Validation Scores**: Response quality assessments
- **Performance Metrics**: Response times and throughput
- **Recommendations**: Specific improvement suggestions

Reports saved to `backend/tests/reports/` with timestamps.

## 🎯 Best Practices

1. **Use Fixtures**: Leverage conftest.py fixtures for consistent test data
2. **Mock External Services**: Use mocks for OpenAI, Google Cloud, etc.
3. **Test Edge Cases**: Include error handling and boundary conditions
4. **Maintain Coverage**: Keep coverage above minimum thresholds
5. **Descriptive Names**: Use clear, descriptive test function names
6. **Async Testing**: Use `pytest.mark.asyncio` for async functions
7. **Parallel Execution**: Use `--parallel` for faster test runs
8. **Korean Language Testing**: Include various formality levels and expressions
9. **Conversation Context**: Test multi-turn dialogue management
10. **Response Validation**: Verify answer quality and appropriateness

## 🚨 Troubleshooting

### Common Issues

1. **Import Errors**: Ensure Python path includes backend directory
2. **Async Issues**: Use `asyncio_mode = auto` in pytest.ini
3. **Missing Dependencies**: Install requirements-test.txt
4. **Environment Variables**: Mock OPENAI_API_KEY and other secrets

### Debug Commands

```bash
# Show available fixtures
python -m pytest --fixtures

# Show test collection without running
python -m pytest --collect-only

# Run with maximum output
python -m pytest -vvv --tb=long
```

## 📈 Continuous Integration

Tests are designed to run in CI/CD environments:

```bash
# CI-friendly command
python test_runner.py all --parallel --failfast

# Generate XML reports for CI
python -m pytest --junitxml=test-results.xml
```

## 🎉 Success Criteria

### Core Testing Requirements
- ✅ All unit tests pass
- ✅ All integration tests pass  
- ✅ Coverage above minimum thresholds (80% backend, 70% integration)
- ✅ No linting errors
- ✅ Performance tests within acceptable limits
- ✅ End-to-end scenarios complete successfully

### Advanced Quality Standards
- ✅ **Response Accuracy**: ≥90% for factual information
- ✅ **Korean Politeness**: ≥95% proper honorific usage
- ✅ **Answer Completeness**: ≥85% comprehensive responses
- ✅ **Context Awareness**: ≥80% multi-turn conversation coherence
- ✅ **Error Handling**: Graceful degradation in all failure scenarios
- ✅ **Performance**: <2s response time target, <5s warning threshold

### Realistic Scenario Validation
- ✅ All 디딤돌 대출 conversation scenarios pass
- ✅ All 전세자금대출 conversation scenarios pass
- ✅ All 입출금통장 conversation scenarios pass
- ✅ Edge cases handled appropriately
- ✅ Multi-turn conversations maintain context
- ✅ Korean language patterns properly recognized

### Comprehensive Test Report
- ✅ Overall test score ≥85%
- ✅ No critical validation failures
- ✅ Performance benchmarks met
- ✅ Detailed recommendations for improvements available

## 📊 Quality Metrics

### Response Quality Scores
- **Excellent**: 0.9+ (90%+)
- **Good**: 0.8-0.89 (80-89%)
- **Acceptable**: 0.7-0.79 (70-79%)
- **Needs Improvement**: <0.7 (<70%)

### Performance Benchmarks
- **Target Response Time**: <2 seconds
- **Warning Threshold**: <5 seconds
- **Error Threshold**: >10 seconds
- **Concurrent Users**: Support 10+ simultaneous conversations

### Korean Language Quality
- **Formality**: Appropriate banking consultation tone
- **Politeness**: Consistent honorific usage
- **Accuracy**: Correct financial terminology
- **Clarity**: Easy to understand explanations