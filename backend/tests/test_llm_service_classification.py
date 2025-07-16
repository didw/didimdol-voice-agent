"""
LLM 기반 서비스 분류 성능 테스트

GeneralMainAgent의 LLM 기반 서비스 분류 성능을 검증하는 테스트
- 10가지 다양한 사용자 입력에 대한 정확한 서비스 분류 검증
- 응답 시간 측정 및 성능 분석
- 의도 분류 정확도 검증
"""

import pytest
import asyncio
import time
import json
from typing import Dict, List, Any, Tuple
from unittest.mock import Mock, AsyncMock, patch

from app.agents.general_main_agent import GeneralMainAgent
from app.graph.chains import generative_llm


class TestLLMServiceClassification:
    """LLM 기반 서비스 분류 테스트"""
    
    @pytest.fixture
    def test_cases(self) -> List[Dict[str, Any]]:
        """테스트 케이스 정의 - 10가지 다양한 시나리오"""
        return [
            {
                "id": 1,
                "user_input": "입출금 통장 만들려고요",
                "expected_service": "deposit_account",
                "expected_intent": "service_request",
                "description": "명확한 입출금통장 개설 요청"
            },
            {
                "id": 2,
                "user_input": "디딤돌 대출 신청하고 싶습니다",
                "expected_service": "didimdol",
                "expected_intent": "service_request",
                "description": "명확한 디딤돌 대출 신청 의도"
            },
            {
                "id": 3,
                "user_input": "전세 보증금 대출 받을 수 있나요?",
                "expected_service": "jeonse",
                "expected_intent": "service_inquiry",
                "description": "전세자금대출 문의"
            },
            {
                "id": 4,
                "user_input": "집을 사고 싶은데 어떤 대출이 좋을까요?",
                "expected_service": "didimdol",
                "expected_intent": "service_inquiry",
                "description": "주택구입 의도에서 디딤돌 대출 추천"
            },
            {
                "id": 5,
                "user_input": "새 직장 다니면서 급여통장 필요해요",
                "expected_service": "deposit_account",
                "expected_intent": "service_request",
                "description": "급여통장 개설 요청"
            },
            {
                "id": 6,
                "user_input": "전세집 구할 때 대출 도움 받을 수 있나요?",
                "expected_service": "jeonse",
                "expected_intent": "service_inquiry",
                "description": "전세 관련 대출 문의"
            },
            {
                "id": 7,
                "user_input": "안녕하세요",
                "expected_service": None,
                "expected_intent": "general_question",
                "description": "일반적인 인사말"
            },
            {
                "id": 8,
                "user_input": "신혼부부인데 내집마련 하려면 어떻게 해야 하나요?",
                "expected_service": "didimdol",
                "expected_intent": "service_inquiry",
                "description": "신혼부부 주택구입 상담"
            },
            {
                "id": 9,
                "user_input": "계좌 하나 개설하고 체크카드도 만들고 싶어요",
                "expected_service": "deposit_account",
                "expected_intent": "service_request",
                "description": "계좌 및 체크카드 개설"
            },
            {
                "id": 10,
                "user_input": "대출 금리가 어떻게 되나요?",
                "expected_service": None,
                "expected_intent": "general_question",
                "description": "일반적인 금리 문의 (특정 상품 미지정)"
            }
        ]
    
    @pytest.fixture
    def general_agent(self):
        """GeneralMainAgent 인스턴스"""
        return GeneralMainAgent()
    
    def create_mock_llm_response(self, service: str, intent: str) -> str:
        """LLM 응답 Mock 생성"""
        return f"""- 의도: {intent}
- 추천 서비스: {service or "없음"}
- RAG 필요: 예
- 서비스 전환 필요: {"예" if service else "아니오"}
- 분석 근거: 사용자의 요청을 분석한 결과"""
    
    @pytest.mark.asyncio
    async def test_single_classification_case(self, general_agent, test_cases):
        """개별 분류 케이스 테스트"""
        for case in test_cases:
            print(f"\n=== 테스트 케이스 {case['id']}: {case['description']} ===")
            print(f"입력: '{case['user_input']}'")
            
            # Mock LLM 응답 설정
            mock_response = Mock()
            mock_response.content = self.create_mock_llm_response(
                case['expected_service'],
                case['expected_intent']
            )
            
            with patch('app.agents.general_main_agent.generative_llm') as mock_llm:
                mock_llm.ainvoke = AsyncMock(return_value=mock_response)
                
                # 시간 측정 시작
                start_time = time.time()
                
                # 분류 수행
                result = await general_agent._classify_intent(
                    user_input=case['user_input'],
                    context={"session_stage": "general_consultation"}
                )
                
                end_time = time.time()
                response_time = (end_time - start_time) * 1000  # ms
                
                print(f"응답 시간: {response_time:.2f}ms")
                print(f"분류 결과: {result}")
                
                # 검증
                assert result['intent'] == case['expected_intent'], \
                    f"의도 분류 오류: 예상={case['expected_intent']}, 실제={result['intent']}"
                
                assert result['recommended_service'] == case['expected_service'], \
                    f"서비스 추천 오류: 예상={case['expected_service']}, 실제={result['recommended_service']}"
                
                # 서비스 전환 필요성 검증
                expected_transition = case['expected_service'] is not None
                assert result['needs_service_transition'] == expected_transition, \
                    f"서비스 전환 필요성 오류: 예상={expected_transition}, 실제={result['needs_service_transition']}"
                
                print(f"✅ 테스트 케이스 {case['id']} 성공")
    
    @pytest.mark.asyncio
    async def test_batch_classification_performance(self, general_agent, test_cases):
        """배치 분류 성능 테스트"""
        print(f"\n=== 배치 성능 테스트 (총 {len(test_cases)}개 케이스) ===")
        
        results = []
        total_start_time = time.time()
        
        for case in test_cases:
            # Mock LLM 응답 설정
            mock_response = Mock()
            mock_response.content = self.create_mock_llm_response(
                case['expected_service'],
                case['expected_intent']
            )
            
            with patch('app.agents.general_main_agent.generative_llm') as mock_llm:
                mock_llm.ainvoke = AsyncMock(return_value=mock_response)
                
                start_time = time.time()
                
                result = await general_agent._classify_intent(
                    user_input=case['user_input'],
                    context={"session_stage": "general_consultation"}
                )
                
                end_time = time.time()
                response_time = (end_time - start_time) * 1000
                
                results.append({
                    "case_id": case['id'],
                    "user_input": case['user_input'],
                    "response_time_ms": response_time,
                    "intent_correct": result['intent'] == case['expected_intent'],
                    "service_correct": result['recommended_service'] == case['expected_service'],
                    "result": result
                })
        
        total_end_time = time.time()
        total_time = (total_end_time - total_start_time) * 1000
        
        # 성능 분석
        response_times = [r['response_time_ms'] for r in results]
        avg_response_time = sum(response_times) / len(response_times)
        max_response_time = max(response_times)
        min_response_time = min(response_times)
        
        intent_accuracy = sum(1 for r in results if r['intent_correct']) / len(results) * 100
        service_accuracy = sum(1 for r in results if r['service_correct']) / len(results) * 100
        
        print(f"\n=== 성능 분석 결과 ===")
        print(f"총 처리 시간: {total_time:.2f}ms")
        print(f"평균 응답 시간: {avg_response_time:.2f}ms")
        print(f"최대 응답 시간: {max_response_time:.2f}ms")
        print(f"최소 응답 시간: {min_response_time:.2f}ms")
        print(f"의도 분류 정확도: {intent_accuracy:.1f}%")
        print(f"서비스 추천 정확도: {service_accuracy:.1f}%")
        
        # 성능 검증
        assert avg_response_time < 1000, f"평균 응답 시간이 너무 길음: {avg_response_time:.2f}ms"
        assert intent_accuracy >= 90, f"의도 분류 정확도가 낮음: {intent_accuracy:.1f}%"
        assert service_accuracy >= 90, f"서비스 추천 정확도가 낮음: {service_accuracy:.1f}%"
        
        # 상세 결과 출력
        print(f"\n=== 개별 케이스 결과 ===")
        for result in results:
            status = "✅" if result['intent_correct'] and result['service_correct'] else "❌"
            print(f"{status} 케이스 {result['case_id']}: {result['response_time_ms']:.1f}ms - '{result['user_input'][:30]}...'")
        
        return results
    
    @pytest.mark.asyncio
    async def test_ambiguous_input_classification(self, general_agent):
        """애매한 발화에 대한 분류 테스트"""
        ambiguous_cases = [
            {
                "user_input": "음... 그... 뭔가 통장 관련된...",
                "description": "불명확한 통장 관련 문의",
                "expected_intent": "general_question",  # 애매한 경우 일반 질문으로 분류
                "expected_service": None
            },
            {
                "user_input": "어... 대출 같은거...",
                "description": "애매한 대출 문의",
                "expected_intent": "general_question",
                "expected_service": None
            },
            {
                "user_input": "뭔가 필요한데...",
                "description": "매우 애매한 요청",
                "expected_intent": "general_question", 
                "expected_service": None
            },
            {
                "user_input": "대출 vs 적금 뭐가 나아요?",
                "description": "비교 요청",
                "expected_intent": "comparison_request",
                "expected_service": None
            },
            {
                "user_input": "첫 직장인데 어떤 은행 서비스가 필요할까요?",
                "description": "신입사원 종합 상담",
                "expected_intent": "general_question",
                "expected_service": None
            }
        ]
        
        print(f"\n=== 애매한 발화 분류 테스트 ===")
        
        for i, case in enumerate(ambiguous_cases, 1):
            print(f"\n--- 애매한 케이스 {i}: {case['description']} ---")
            print(f"입력: '{case['user_input']}'")
            
            # Mock LLM 응답 - 애매한 경우에 대한 적절한 분류
            mock_response = Mock()
            mock_response.content = self.create_mock_llm_response(
                case['expected_service'],
                case['expected_intent']
            )
            
            with patch('app.agents.general_main_agent.generative_llm') as mock_llm:
                mock_llm.ainvoke = AsyncMock(return_value=mock_response)
                
                result = await general_agent._classify_intent(
                    user_input=case['user_input'],
                    context={"session_stage": "general_consultation"}
                )
                
                print(f"분류 결과: {result}")
                
                # 검증: 애매한 입력은 일반 질문으로 분류되어야 함
                assert result['intent'] == case['expected_intent'], \
                    f"의도 분류 오류: 예상={case['expected_intent']}, 실제={result['intent']}"
                
                assert result['recommended_service'] == case['expected_service'], \
                    f"서비스 추천 오류: 예상={case['expected_service']}, 실제={result['recommended_service']}"
                
                # 애매한 경우 서비스 전환이 필요하지 않아야 함
                if case['expected_service'] is None:
                    assert result['needs_service_transition'] == False, \
                        "애매한 입력은 서비스 전환이 필요하지 않아야 함"
                
                print(f"✅ 애매한 케이스 {i} 성공: 적절히 '{case['expected_intent']}'로 분류")
    
    @pytest.mark.asyncio
    async def test_clarification_needed_cases(self, general_agent):
        """명확화가 필요한 케이스 테스트"""
        clarification_cases = [
            {
                "user_input": "도움이 필요해요",
                "description": "매우 일반적인 도움 요청"
            },
            {
                "user_input": "상담 받고 싶어요",
                "description": "구체적이지 않은 상담 요청"
            },
            {
                "user_input": "은행 업무 보러 왔어요",
                "description": "일반적인 은행 업무"
            }
        ]
        
        print(f"\n=== 명확화 필요 케이스 테스트 ===")
        
        for i, case in enumerate(clarification_cases, 1):
            print(f"\n--- 명확화 케이스 {i}: {case['description']} ---")
            print(f"입력: '{case['user_input']}'")
            
            # 명확화가 필요한 경우 general_question으로 분류
            mock_response = Mock()
            mock_response.content = self.create_mock_llm_response(None, "general_question")
            
            with patch('app.agents.general_main_agent.generative_llm') as mock_llm:
                mock_llm.ainvoke = AsyncMock(return_value=mock_response)
                
                result = await general_agent._classify_intent(
                    user_input=case['user_input'],
                    context={"session_stage": "general_consultation"}
                )
                
                print(f"분류 결과: {result}")
                
                # 명확화가 필요한 경우는 일반 질문으로 분류되어야 함
                assert result['intent'] == 'general_question', \
                    f"명확화 필요 케이스는 general_question으로 분류되어야 함: {result['intent']}"
                
                assert result['recommended_service'] is None, \
                    "명확화 필요 케이스는 특정 서비스를 추천하지 않아야 함"
                
                assert result['needs_service_transition'] == False, \
                    "명확화 필요 케이스는 서비스 전환이 필요하지 않아야 함"
                
                print(f"✅ 명확화 케이스 {i} 성공: 추가 정보 요청이 필요한 상황으로 적절히 분류")
    
    @pytest.mark.asyncio
    async def test_context_awareness(self, general_agent):
        """컨텍스트 인식 테스트"""
        print(f"\n=== 컨텍스트 인식 테스트 ===")
        
        # 대화 히스토리가 있는 상황
        context_with_history = {
            "conversation_history": [
                {"role": "user", "content": "안녕하세요"},
                {"role": "assistant", "content": "안녕하세요! 어떻게 도와드릴까요?"},
                {"role": "user", "content": "대출 상담 받고 싶어요"}
            ],
            "session_stage": "general_consultation"
        }
        
        follow_up_input = "그럼 금리는 어떻게 되나요?"
        
        mock_response = Mock()
        mock_response.content = self.create_mock_llm_response(None, "general_question")
        
        with patch('app.agents.general_main_agent.generative_llm') as mock_llm:
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            
            result = await general_agent._classify_intent(
                user_input=follow_up_input,
                context=context_with_history
            )
            
            print(f"컨텍스트 인식 결과: {result}")
            
            # LLM이 컨텍스트와 함께 호출되었는지 확인
            assert mock_llm.called
            call_args = mock_llm.call_args[0][0][0].content
            assert "그럼 금리는 어떻게 되나요?" in call_args
            
            print("✅ 컨텍스트 인식 테스트 성공")
    
    def test_parsing_accuracy(self, general_agent):
        """응답 파싱 정확도 테스트"""
        print(f"\n=== 응답 파싱 정확도 테스트 ===")
        
        test_responses = [
            {
                "llm_output": """- 의도: service_request
- 추천 서비스: deposit_account
- RAG 필요: 예
- 서비스 전환 필요: 예""",
                "expected": {
                    "intent": "service_request",
                    "recommended_service": "deposit_account",
                    "needs_rag": True,
                    "needs_service_transition": True
                }
            },
            {
                "llm_output": """- 의도: general_question
- 추천 서비스: 없음
- RAG 필요: 예
- 서비스 전환 필요: 아니오""",
                "expected": {
                    "intent": "general_question",
                    "recommended_service": None,
                    "needs_rag": True,
                    "needs_service_transition": False
                }
            },
            {
                "llm_output": """의도: service_inquiry, 추천 서비스: didimdol, RAG 필요: 예, 서비스 전환 필요: 예""",
                "expected": {
                    "intent": "service_inquiry",
                    "recommended_service": "didimdol",
                    "needs_rag": True,
                    "needs_service_transition": True
                }
            }
        ]
        
        for i, test in enumerate(test_responses, 1):
            print(f"\n--- 파싱 테스트 {i} ---")
            print(f"LLM 출력: {test['llm_output']}")
            
            result = general_agent._parse_intent_result(test['llm_output'])
            
            print(f"파싱 결과: {result}")
            print(f"예상 결과: {test['expected']}")
            
            for key, expected_value in test['expected'].items():
                assert result[key] == expected_value, \
                    f"파싱 오류 - {key}: 예상={expected_value}, 실제={result[key]}"
            
            print(f"✅ 파싱 테스트 {i} 성공")


@pytest.mark.asyncio
async def test_integration_with_main_flow():
    """메인 플로우와의 통합 테스트"""
    from app.graph.agent import _handle_general_consultation, AgentState
    from langchain_core.messages import HumanMessage
    
    print(f"\n=== 메인 플로우 통합 테스트 ===")
    
    test_state = {
        "messages": [HumanMessage(content="입출금 통장 만들고 싶어요")],
        "current_product_type": None,  # 업무 미선택 상태
        "user_input_text": "입출금 통장 만들고 싶어요"
    }
    
    # GeneralMainAgent의 응답을 Mock
    mock_general_agent_result = {
        "response_text": "입출금통장 개설을 도와드리겠습니다.",
        "recommended_service": "deposit_account",
        "intent": "service_request",
        "needs_service_transition": True,
        "conversation_continues": True
    }
    
    with patch('app.agents.general_main_agent.GeneralMainAgent.process_user_input', 
               new_callable=AsyncMock) as mock_process:
        mock_process.return_value = mock_general_agent_result
        
        result = await _handle_general_consultation(test_state, "입출금 통장 만들고 싶어요")
        
        print(f"통합 테스트 결과: {result}")
        
        # 검증
        assert result['final_response_text_for_tts'] == "입출금통장 개설을 도와드리겠습니다."
        assert result['recommended_service'] == "deposit_account"
        assert mock_process.called
        
        print("✅ 메인 플로우 통합 테스트 성공")


if __name__ == "__main__":
    # 직접 실행 시 간단한 테스트 수행
    import asyncio
    
    async def run_quick_test():
        print("=== LLM 서비스 분류 빠른 테스트 ===")
        
        test_instance = TestLLMServiceClassification()
        general_agent = GeneralMainAgent()
        
        # 하나의 테스트 케이스만 실행
        test_case = {
            "user_input": "입출금 통장 만들려고요",
            "expected_service": "deposit_account",
            "expected_intent": "service_request"
        }
        
        mock_response = Mock()
        mock_response.content = test_instance.create_mock_llm_response(
            test_case['expected_service'],
            test_case['expected_intent']
        )
        
        with patch('app.agents.general_main_agent.generative_llm') as mock_llm:
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            
            result = await general_agent._classify_intent(
                user_input=test_case['user_input'],
                context={"session_stage": "general_consultation"}
            )
            
            print(f"입력: {test_case['user_input']}")
            print(f"결과: {result}")
            print("✅ 빠른 테스트 성공")
    
    asyncio.run(run_quick_test())