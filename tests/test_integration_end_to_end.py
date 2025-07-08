import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path
import tempfile


class TestEndToEndIntegration:
    """End-to-end integration tests covering complete user scenarios."""

    @pytest.fixture
    def full_system_mocks(self, complete_scenario_data, mock_knowledge_base_data):
        """Set up comprehensive mocks for full system testing."""
        
        # Mock RAG service
        mock_rag_service = Mock()
        mock_rag_service.is_ready.return_value = True
        
        # Define responses for different types of questions
        rag_responses = {
            "기본정보": "디딤돌 대출은 청년층을 위한 정부 지원 대출 상품입니다. 연 2.5%의 저금리로 최대 2억원까지 대출 가능합니다.",
            "금리": "디딤돌 대출의 기본 금리는 연 2.5%이며, 소득 수준에 따라 우대금리 최대 0.5%가 적용됩니다.",
            "한도": "디딤돌 대출의 한도는 최대 2억원입니다. 개인의 소득과 신용도에 따라 실제 한도가 결정됩니다.",
            "신청": "디딤돌 대출 신청은 온라인, 영업점 방문, 전화 신청이 가능합니다. 필요 서류는 신분증, 소득증명서, 재직증명서 등입니다.",
            "우대조건": "소득 3천만원 이하 시 0.3%, 2천만원 이하 시 0.5% 우대금리가 적용되며, 신용등급에 따른 추가 우대도 있습니다."
        }
        
        def mock_rag_answer(queries, original_question):
            question = original_question.lower()
            if "기본" in question or "무엇" in question or "어떤" in question:
                return rag_responses["기본정보"]
            elif "금리" in question:
                return rag_responses["금리"]
            elif "한도" in question:
                return rag_responses["한도"]
            elif "신청" in question or "방법" in question:
                return rag_responses["신청"]
            elif "우대" in question or "할인" in question:
                return rag_responses["우대조건"]
            else:
                return "관련 정보를 찾을 수 없습니다. 다른 질문을 해주세요."
        
        mock_rag_service.answer_question = AsyncMock(side_effect=mock_rag_answer)
        
        # Mock web search service
        mock_web_search_service = Mock()
        mock_web_search_service.asearch = AsyncMock(return_value="최신 대출 정책 정보를 검색했습니다.")
        
        # Mock Google services (STT/TTS)
        mock_google_services = {
            "speech_to_text": AsyncMock(return_value="안녕하세요 디딤돌 대출에 대해 알려주세요"),
            "text_to_speech": AsyncMock(return_value=b"mock_audio_data")
        }
        
        # Mock LLMs
        mock_json_llm = AsyncMock()
        mock_generative_llm = AsyncMock()
        
        # Mock prompts
        mock_prompts = {
            "main_agent": {
                "initial_task_selection_prompt": """
사용자 입력: {user_input}
사용 가능한 상품 유형: {available_product_types_list}

다음 형식으로 응답하세요:
{format_instructions}
""",
                "router_prompt": """
사용자 입력: {user_input}
현재 활성 시나리오: {active_scenario_name}
현재 단계: {current_scenario_stage_id}
채팅 기록: {formatted_messages_history}

다음 형식으로 응답하세요:
{format_instructions}
""",
                "determine_next_scenario_stage": """
현재 시나리오: {active_scenario_name}
현재 단계: {current_stage_id}
사용자 입력: {user_input}
의도: {scenario_agent_intent}
수집된 정보: {collected_product_info}

다음 단계를 결정하세요:
{format_instructions}
"""
            },
            "qa_agent": {
                "rag_query_expansion_prompt": """
시나리오: {scenario_name}
채팅 기록: {chat_history}
사용자 질문: {user_question}

관련 질문들을 생성하세요.
""",
                "simple_chitchat_prompt": """
사용자 입력: {user_input}

친근하고 도움이 되는 응답을 생성하세요.
"""
            }
        }
        
        return {
            "rag_service": mock_rag_service,
            "web_search_service": mock_web_search_service,
            "google_services": mock_google_services,
            "json_llm": mock_json_llm,
            "generative_llm": mock_generative_llm,
            "prompts": mock_prompts,
            "scenarios": complete_scenario_data
        }

    @pytest.mark.asyncio
    async def test_complete_didimdol_consultation_flow(self, full_system_mocks, integration_test_scenarios):
        """Test complete consultation flow from greeting to completion."""
        
        from backend.app.graph.agent import run_agent_streaming
        from backend.app.graph.models import (
            InitialTaskDecisionModel, MainRouterDecisionModel, NextStageDecisionModel, 
            ActionModel, ScenarioOutputModel
        )
        
        # Setup comprehensive mocks
        mocks = full_system_mocks
        
        # Mock decision parsers and their responses
        def create_mock_parser_responses():
            # Initial task selection - choose didimdol
            initial_decision = InitialTaskDecision(
                actions=[ActionModel(tool="set_product_type", tool_input={"product_id": "didimdol"})]
            )
            
            # Router decisions for different stages
            qa_decision = MainRouterDecision(
                actions=[ActionModel(tool="invoke_qa_agent", tool_input={})]
            )
            
            scenario_decision = MainRouterDecision(
                actions=[ActionModel(tool="invoke_scenario_agent", tool_input={})]
            )
            
            # Stage transitions
            next_stage_decision = NextStageDecisionModel(chosen_next_stage_id="interest_rate_info")
            
            return {
                "initial": initial_decision,
                "qa": qa_decision, 
                "scenario": scenario_decision,
                "next_stage": next_stage_decision
            }
        
        decisions = create_mock_parser_responses()
        
        # Mock JSON LLM responses
        llm_responses = [
            json.dumps({"actions": [{"tool": "set_product_type", "tool_input": {"product_id": "didimdol"}}]}),
            json.dumps({"actions": [{"tool": "invoke_qa_agent", "tool_input": {}}]}),
            json.dumps({"chosen_next_stage_id": "interest_rate_info"}),
            json.dumps({"actions": [{"tool": "invoke_scenario_agent", "tool_input": {}}]}),
        ]
        
        def mock_llm_response(content):
            response = Mock()
            response.content = content
            return response
        
        mocks["json_llm"].ainvoke.side_effect = [mock_llm_response(resp) for resp in llm_responses]
        
        # Mock generative LLM for synthesis
        mocks["generative_llm"].ainvoke.return_value = mock_llm_response("종합적인 상담 응답입니다.")
        
        # Mock scenario agent logic
        mock_scenario_output = ScenarioOutputModel(
            intent="inquiry_interest_rate",
            is_scenario_related=True,
            entities={"inquiry_type": "금리 문의"}
        )
        
        # Test the complete flow
        conversation_steps = [
            ("안녕하세요", "greeting"),
            ("디딤돌 대출에 대해 알려주세요", "product_selection"),
            ("금리가 궁금해요", "qa_inquiry"),
            ("신청 방법을 알려주세요", "application_inquiry"),
        ]
        
        conversation_state = None
        
        with patch('backend.app.graph.agent.ALL_PROMPTS', mocks["prompts"]), \
             patch('backend.app.graph.agent.ALL_SCENARIOS_DATA', mocks["scenarios"]), \
             patch('backend.app.graph.agent.rag_service', mocks["rag_service"]), \
             patch('backend.app.graph.agent.web_search_service', mocks["web_search_service"]), \
             patch('backend.app.graph.agent.json_llm', mocks["json_llm"]), \
             patch('backend.app.graph.agent.generative_llm', mocks["generative_llm"]), \
             patch('backend.app.graph.agent.initial_task_decision_parser') as mock_initial_parser, \
             patch('backend.app.graph.agent.main_router_decision_parser') as mock_router_parser, \
             patch('backend.app.graph.agent.next_stage_decision_parser') as mock_stage_parser, \
             patch('backend.app.graph.agent.invoke_scenario_agent_logic', return_value=mock_scenario_output):
            
            # Setup parser mocks
            mock_initial_parser.parse.return_value = decisions["initial"]
            mock_initial_parser.get_format_instructions.return_value = "format instructions"
            
            mock_router_parser.parse.side_effect = [decisions["qa"], decisions["scenario"]]
            mock_router_parser.get_format_instructions.return_value = "format instructions"
            
            mock_stage_parser.parse.return_value = decisions["next_stage"]
            
            for i, (user_input, expected_type) in enumerate(conversation_steps):
                print(f"\n--- Step {i+1}: {user_input} ({expected_type}) ---")
                
                responses = []
                async for response in run_agent_streaming(
                    user_input_text=user_input,
                    session_id=f"e2e_test_step_{i}",
                    current_state_dict=conversation_state
                ):
                    responses.append(response)
                
                # Extract final state for next turn
                final_state = None
                for response in responses:
                    if isinstance(response, dict) and response.get("type") == "final_state":
                        final_state = response["data"]
                        break
                
                assert final_state is not None, f"No final state received for step {i+1}"
                
                # Verify conversation progression
                if i == 0:  # Greeting
                    assert final_state["is_final_turn_response"] is True
                elif i == 1:  # Product selection
                    assert final_state["current_product_type"] == "didimdol"
                elif i >= 2:  # QA and scenarios
                    assert len(final_state["messages"]) > i
                
                conversation_state = final_state
                
                # Collect text responses
                text_responses = [r for r in responses if isinstance(r, str)]
                full_response = "".join(text_responses)
                
                # Basic response validation
                assert len(full_response) > 0, f"Empty response for step {i+1}"
                
                print(f"Response: {full_response[:100]}...")

    @pytest.mark.asyncio
    async def test_multi_scenario_comparison_flow(self, full_system_mocks):
        """Test user comparing multiple loan products."""
        
        from backend.app.graph.agent import run_agent_streaming
        from backend.app.graph.models import MainRouterDecisionModel, ActionModel
        
        mocks = full_system_mocks
        
        # Enhanced RAG service for comparison questions
        def comparison_rag_answer(queries, original_question):
            question = original_question.lower()
            if "차이" in question or "비교" in question:
                return "디딤돌 대출은 청년층 대상이며 연 2.5%, 전세 대출은 일반인 대상이며 연 3.0%입니다."
            elif "적합" in question or "추천" in question:
                return "소득과 나이를 고려할 때 디딤돌 대출이 더 유리할 수 있습니다."
            else:
                return mocks["rag_service"].answer_question.side_effect(queries, original_question)
        
        mocks["rag_service"].answer_question = AsyncMock(side_effect=comparison_rag_answer)
        
        comparison_steps = [
            "디딤돌 대출과 전세 대출의 차이점이 뭔가요?",
            "저에게 더 적합한 상품은 뭔가요?",
            "디딤돌 대출로 상담을 진행하고 싶어요"
        ]
        
        conversation_state = None
        
        # Mock router to always use QA agent for comparison questions
        qa_decision = MainRouterDecision(
            actions=[ActionModel(tool="invoke_qa_agent", tool_input={})]
        )
        
        with patch('backend.app.graph.agent.ALL_PROMPTS', mocks["prompts"]), \
             patch('backend.app.graph.agent.ALL_SCENARIOS_DATA', mocks["scenarios"]), \
             patch('backend.app.graph.agent.rag_service', mocks["rag_service"]), \
             patch('backend.app.graph.agent.main_router_decision_parser') as mock_parser:
            
            mock_parser.parse.return_value = qa_decision
            mock_parser.get_format_instructions.return_value = "format instructions"
            
            for i, user_input in enumerate(comparison_steps):
                responses = []
                async for response in run_agent_streaming(
                    user_input_text=user_input,
                    session_id=f"comparison_test_{i}",
                    current_state_dict=conversation_state
                ):
                    responses.append(response)
                
                # Get text response
                text_responses = [r for r in responses if isinstance(r, str)]
                full_response = "".join(text_responses)
                
                # Verify relevant content
                if i == 0:  # Comparison question
                    assert "디딤돌" in full_response and "전세" in full_response
                elif i == 1:  # Recommendation question
                    assert "적합" in full_response or "유리" in full_response
                
                # Update state for next turn
                for response in responses:
                    if isinstance(response, dict) and response.get("type") == "final_state":
                        conversation_state = response["data"]
                        break

    @pytest.mark.asyncio
    async def test_error_recovery_and_fallback_flow(self, full_system_mocks):
        """Test system behavior under various error conditions."""
        
        from backend.app.graph.agent import run_agent_streaming
        
        mocks = full_system_mocks
        
        # Test scenarios with different types of failures
        error_scenarios = [
            {
                "name": "RAG service failure",
                "setup": lambda: setattr(mocks["rag_service"], "is_ready", Mock(return_value=False)),
                "input": "디딤돌 대출 정보를 알려주세요"
            },
            {
                "name": "LLM service failure", 
                "setup": lambda: mocks["json_llm"].ainvoke.side_effect(Exception("LLM Error")),
                "input": "금리가 궁금해요"
            },
            {
                "name": "Invalid user input",
                "setup": lambda: None,
                "input": ""  # Empty input
            }
        ]
        
        for scenario in error_scenarios:
            print(f"\n--- Testing {scenario['name']} ---")
            
            # Setup error condition
            if scenario["setup"]:
                scenario["setup"]()
            
            try:
                responses = []
                async for response in run_agent_streaming(
                    user_input_text=scenario["input"],
                    session_id=f"error_test_{scenario['name'].replace(' ', '_')}"
                ):
                    responses.append(response)
                
                # System should handle errors gracefully
                assert len(responses) > 0, f"No response for {scenario['name']}"
                
                # Check for error handling
                has_error_response = any(
                    isinstance(r, dict) and r.get("type") == "error" 
                    for r in responses
                )
                
                has_final_state = any(
                    isinstance(r, dict) and r.get("type") == "final_state"
                    for r in responses
                )
                
                # Should have either error response or graceful fallback
                assert has_error_response or has_final_state, f"No proper error handling for {scenario['name']}"
                
            except Exception as e:
                # Some errors are expected, but system shouldn't crash completely
                print(f"Expected error in {scenario['name']}: {e}")

    @pytest.mark.asyncio
    async def test_concurrent_user_sessions(self, full_system_mocks):
        """Test system handling multiple concurrent user sessions."""
        
        from backend.app.graph.agent import run_agent_streaming
        from backend.app.graph.models import InitialTaskDecisionModel, ActionModel
        
        mocks = full_system_mocks
        
        # Mock decision for product selection
        decision = InitialTaskDecisionModel(
            actions=[ActionModel(tool="set_product_type", tool_input={"product_id": "didimdol"})]
        )
        
        # Number of concurrent sessions to test
        num_sessions = 5
        
        async def simulate_user_session(session_id):
            """Simulate a single user session."""
            inputs = [
                "안녕하세요",
                "디딤돌 대출에 대해 알려주세요",
                "금리가 궁금해요"
            ]
            
            session_state = None
            session_results = []
            
            for user_input in inputs:
                responses = []
                async for response in run_agent_streaming(
                    user_input_text=user_input,
                    session_id=session_id,
                    current_state_dict=session_state
                ):
                    responses.append(response)
                
                # Update session state
                for response in responses:
                    if isinstance(response, dict) and response.get("type") == "final_state":
                        session_state = response["data"]
                        break
                
                session_results.append(len(responses))
            
            return session_results
        
        with patch('backend.app.graph.agent.ALL_PROMPTS', mocks["prompts"]), \
             patch('backend.app.graph.agent.ALL_SCENARIOS_DATA', mocks["scenarios"]), \
             patch('backend.app.graph.agent.rag_service', mocks["rag_service"]), \
             patch('backend.app.graph.agent.initial_task_decision_parser') as mock_parser:
            
            mock_parser.parse.return_value = decision
            mock_parser.get_format_instructions.return_value = "format instructions"
            
            # Run concurrent sessions
            tasks = [
                simulate_user_session(f"concurrent_user_{i}")
                for i in range(num_sessions)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Verify all sessions completed
            successful_sessions = [r for r in results if not isinstance(r, Exception)]
            assert len(successful_sessions) == num_sessions, f"Only {len(successful_sessions)}/{num_sessions} sessions succeeded"
            
            # Verify each session got responses
            for i, session_result in enumerate(successful_sessions):
                assert all(count > 0 for count in session_result), f"Session {i} had empty responses"

    @pytest.mark.asyncio
    async def test_performance_under_load(self, full_system_mocks, performance_test_data):
        """Test system performance under load conditions."""
        
        from backend.app.graph.agent import run_agent_streaming
        import time
        
        mocks = full_system_mocks
        test_data = performance_test_data
        
        # Performance metrics
        response_times = []
        successful_requests = 0
        failed_requests = 0
        
        async def timed_request(user_input, session_id):
            """Make a timed request and collect metrics."""
            start_time = time.time()
            try:
                responses = []
                async for response in run_agent_streaming(
                    user_input_text=user_input,
                    session_id=session_id
                ):
                    responses.append(response)
                
                end_time = time.time()
                response_time = end_time - start_time
                
                return {
                    "success": True,
                    "response_time": response_time,
                    "response_count": len(responses)
                }
            except Exception as e:
                end_time = time.time()
                return {
                    "success": False,
                    "response_time": end_time - start_time,
                    "error": str(e)
                }
        
        with patch('backend.app.graph.agent.ALL_PROMPTS', mocks["prompts"]), \
             patch('backend.app.graph.agent.ALL_SCENARIOS_DATA', mocks["scenarios"]), \
             patch('backend.app.graph.agent.rag_service', mocks["rag_service"]):
            
            # Generate load test requests
            tasks = []
            for i in range(test_data["concurrent_users"]):
                for j in range(test_data["requests_per_user"]):
                    user_input = test_data["sample_inputs"][j % len(test_data["sample_inputs"])]
                    session_id = f"load_test_user_{i}_req_{j}"
                    tasks.append(timed_request(user_input, session_id))
            
            # Execute load test
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Analyze results
            for result in results:
                if isinstance(result, Exception):
                    failed_requests += 1
                elif result["success"]:
                    successful_requests += 1
                    response_times.append(result["response_time"])
                else:
                    failed_requests += 1
            
            # Performance assertions
            total_requests = successful_requests + failed_requests
            success_rate = successful_requests / total_requests if total_requests > 0 else 0
            
            assert success_rate >= 0.9, f"Success rate too low: {success_rate:.2%}"
            
            if response_times:
                avg_response_time = sum(response_times) / len(response_times)
                max_response_time = max(response_times)
                
                assert avg_response_time < 5.0, f"Average response time too high: {avg_response_time:.2f}s"
                assert max_response_time < 10.0, f"Max response time too high: {max_response_time:.2f}s"
                
                print(f"Performance metrics:")
                print(f"  Success rate: {success_rate:.2%}")
                print(f"  Average response time: {avg_response_time:.2f}s")
                print(f"  Max response time: {max_response_time:.2f}s")
                print(f"  Total requests: {total_requests}")

    @pytest.mark.asyncio
    async def test_data_consistency_across_turns(self, full_system_mocks):
        """Test data consistency and state management across conversation turns."""
        
        from backend.app.graph.agent import run_agent_streaming
        
        mocks = full_system_mocks
        
        # Test conversation with state accumulation
        conversation_flow = [
            {"input": "디딤돌 대출을 선택해주세요", "expected_state": {"current_product_type": "didimdol"}},
            {"input": "금리 문의해요", "expected_state": {"current_product_type": "didimdol", "collected_info": {"inquiry_type": "금리 문의"}}},
            {"input": "우대 조건도 궁금해요", "expected_state": {"current_product_type": "didimdol"}},
        ]
        
        session_state = None
        
        with patch('backend.app.graph.agent.ALL_PROMPTS', mocks["prompts"]), \
             patch('backend.app.graph.agent.ALL_SCENARIOS_DATA', mocks["scenarios"]), \
             patch('backend.app.graph.agent.rag_service', mocks["rag_service"]):
            
            for i, step in enumerate(conversation_flow):
                responses = []
                async for response in run_agent_streaming(
                    user_input_text=step["input"],
                    session_id="consistency_test",
                    current_state_dict=session_state
                ):
                    responses.append(response)
                
                # Extract and verify final state
                final_state = None
                for response in responses:
                    if isinstance(response, dict) and response.get("type") == "final_state":
                        final_state = response["data"]
                        break
                
                assert final_state is not None, f"No final state for step {i+1}"
                
                # Verify expected state properties
                for key, expected_value in step["expected_state"].items():
                    if key == "collected_info":
                        # Check if collected info contains expected data
                        collected = final_state.get("collected_product_info", {})
                        assert any(k in collected for k in expected_value.keys()), f"Missing collected info in step {i+1}"
                    else:
                        assert final_state.get(key) == expected_value, f"State mismatch for {key} in step {i+1}"
                
                # Verify message history grows
                if session_state and "messages" in session_state:
                    assert len(final_state["messages"]) > len(session_state["messages"]), f"Message history not growing in step {i+1}"
                
                session_state = final_state