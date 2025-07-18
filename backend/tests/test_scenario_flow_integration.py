import pytest
from unittest.mock import Mock, AsyncMock, patch
import json

from app.graph.agent import run_agent_streaming
from app.graph.state import AgentState
from langchain_core.messages import HumanMessage, AIMessage


class TestScenarioFlowIntegration:
    """통장 신규 시나리오 플로우 통합 테스트"""
    
    @pytest.mark.asyncio
    async def test_deposit_account_scenario_flow(self):
        """
        입출금통장 시나리오 플로우 테스트:
        1. '통장만들려고요' 발화 -> 제품 선택 및 개인정보 확인 단계
        2. '네' 발화 -> 다음 단계(평생계좌 문의)로 이동
        
        PRD 요구사항 검증:
        - 기본값 자동 적용 (고객명, 연락처)
        - 단계별 정보 수집
        - 상태 전환 추적
        """
        
        # Mock 설정
        mock_rag_service = Mock()
        mock_rag_service.is_ready.return_value = True
        
        mock_web_search_service = Mock()
        mock_web_search_service.asearch = AsyncMock(return_value=[{"content": "검색결과"}])
        
        # 첫 번째 단계: "통장만들려고요" 발화
        session_id = "test_session_001"
        
        with patch('app.graph.agent.rag_service', mock_rag_service), \
             patch('app.graph.agent.web_search_service', mock_web_search_service), \
             patch('app.graph.nodes.workers.rag_worker.rag_service', mock_rag_service), \
             patch('app.graph.nodes.workers.web_worker.web_search_service', mock_web_search_service):
            
            # 1단계: 통장 신규 의도 인식
            result_stream = []
            async for item in run_agent_streaming(
                user_input_text="통장만들려고요",
                session_id=session_id
            ):
                result_stream.append(item)
            
            # 최종 상태 추출
            final_state = None
            for item in result_stream:
                if isinstance(item, dict) and item.get("type") == "final_state":
                    final_state = item["data"]
                    break
            
            assert final_state is not None
            assert final_state["current_product_type"] == "deposit_account"
            assert final_state["active_scenario_name"] == "신한은행 입출금통장 신규 상담"
            assert final_state["current_scenario_stage_id"] == "greeting"
            
            # 개인정보 확인 프롬프트가 포함되어야 함
            response_text = final_state.get("final_response_text_for_tts", "")
            assert "현재 등록된 고객님 정보는 다음과 같습니다" in response_text
            assert "이 정보가 맞으신가요?" in response_text
            
            print(f"✅ 1단계 완료: {final_state['current_scenario_stage_id']}")
            print(f"응답: {response_text[:100]}...")
            
            # 2단계: "네" 발화로 다음 단계 진행
            result_stream_2 = []
            async for item in run_agent_streaming(
                user_input_text="네",
                session_id=session_id,
                current_state_dict=final_state
            ):
                result_stream_2.append(item)
            
            # 최종 상태 추출
            final_state_2 = None
            for item in result_stream_2:
                if isinstance(item, dict) and item.get("type") == "final_state":
                    final_state_2 = item["data"]
                    break
            
            assert final_state_2 is not None
            assert final_state_2["current_scenario_stage_id"] == "ask_lifelong_account"
            
            # 평생계좌 문의 프롬프트가 포함되어야 함
            response_text_2 = final_state_2.get("final_response_text_for_tts", "")
            assert "평생계좌번호로 등록하시겠어요?" in response_text_2
            
            # 개인정보 확인이 수집되어야 함
            collected_info = final_state_2.get("collected_product_info", {})
            assert collected_info.get("confirm_personal_info") is True
            
            # PRD 요구사항: 기본값이 유지되어야 함
            assert collected_info.get("customer_name") == "홍길동"
            assert collected_info.get("customer_phone") == "010-1234-5678"
            
            print(f"✅ 2단계 완료: {final_state_2['current_scenario_stage_id']}")
            print(f"응답: {response_text_2[:100]}...")
            print(f"수집된 정보: {collected_info}")
            
    @pytest.mark.asyncio
    async def test_deposit_account_scenario_flow_with_mocked_llm(self):
        """
        LLM 응답을 모킹한 시나리오 플로우 테스트
        """
        
        # Mock LLM 응답 설정
        mock_llm = AsyncMock()
        
        # 첫 번째 호출: 제품 선택 (통장 -> deposit_account)
        mock_product_response = Mock()
        mock_product_response.content = json.dumps({
            "actions": [{"tool": "set_product_type", "tool_input": {"product_id": "deposit_account"}}]
        })
        
        # 두 번째 호출: 시나리오 NLU (개인정보 확인)
        mock_scenario_response = Mock()
        mock_scenario_response.content = json.dumps({
            "intent": "confirm_personal_info",
            "is_scenario_related": True,
            "entities": {"confirm_personal_info": True}
        })
        
        # 세 번째 호출: 다음 스테이지 결정
        mock_stage_response = Mock()
        mock_stage_response.content = json.dumps({
            "chosen_next_stage_id": "ask_lifelong_account"
        })
        
        mock_llm.ainvoke = AsyncMock(side_effect=[
            mock_product_response,
            mock_scenario_response,
            mock_stage_response
        ])
        
        with patch('app.graph.agent.json_llm', mock_llm), \
             patch('app.graph.nodes.orchestrator.main_router.json_llm', mock_llm), \
             patch('app.graph.chains.json_llm', mock_llm):
            
            # 테스트 실행
            result_stream = []
            async for item in run_agent_streaming(
                user_input_text="통장만들려고요",
                session_id="test_mock_session"
            ):
                result_stream.append(item)
            
            # 결과 검증
            final_state = None
            for item in result_stream:
                if isinstance(item, dict) and item.get("type") == "final_state":
                    final_state = item["data"]
                    break
            
            assert final_state is not None
            assert final_state["current_product_type"] == "deposit_account"
            
            print(f"✅ 모킹 테스트 완료: {final_state.get('current_scenario_stage_id', 'N/A')}")
            
    @pytest.mark.asyncio 
    async def test_scenario_stage_progression_with_entity_extraction(self):
        """
        Entity Agent를 통한 정보 추출 및 스테이지 진행 테스트
        """
        
        # Entity Agent 모킹
        mock_entity_agent = Mock()
        mock_entity_agent.process_slot_filling = AsyncMock(return_value={
            "extracted_entities": {"confirm_personal_info": True},
            "collected_info": {"confirm_personal_info": True}
        })
        
        # 초기 상태 설정 (이미 deposit_account 선택된 상태)
        initial_state = {
            "session_id": "test_entity_session",
            "current_product_type": "deposit_account",
            "active_scenario_name": "신한은행 입출금통장 신규 상담",
            "current_scenario_stage_id": "greeting",
            "collected_product_info": {},
            "messages": [
                {"type": "HumanMessage", "content": "통장만들려고요"},
                {"type": "AIMessage", "content": "현재 등록된 고객님 정보는 다음과 같습니다..."}
            ]
        }
        
        with patch('app.agents.entity_agent.entity_agent', mock_entity_agent):
            
            # "네" 발화로 다음 단계 진행
            result_stream = []
            async for item in run_agent_streaming(
                user_input_text="네",
                session_id="test_entity_session",
                current_state_dict=initial_state
            ):
                result_stream.append(item)
            
            # 결과 검증
            final_state = None
            for item in result_stream:
                if isinstance(item, dict) and item.get("type") == "final_state":
                    final_state = item["data"]
                    break
            
            assert final_state is not None
            
            # Entity Agent가 호출되었는지 확인
            mock_entity_agent.process_slot_filling.assert_called_once()
            
            # 정보가 수집되었는지 확인
            collected_info = final_state.get("collected_product_info", {})
            assert "confirm_personal_info" in collected_info
            
            print(f"✅ Entity 추출 테스트 완료: {collected_info}")

    @pytest.mark.asyncio
    async def test_scenario_error_handling(self):
        """
        시나리오 에러 처리 테스트
        """
        
        # LLM 에러 시뮬레이션
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM Error"))
        
        with patch('app.graph.agent.json_llm', mock_llm):
            
            result_stream = []
            async for item in run_agent_streaming(
                user_input_text="통장만들려고요",
                session_id="test_error_session"
            ):
                result_stream.append(item)
            
            # 에러 처리 확인
            final_state = None
            for item in result_stream:
                if isinstance(item, dict) and item.get("type") == "final_state":
                    final_state = item["data"]
                    break
            
            assert final_state is not None
            assert "error_message" in final_state
            
            print(f"✅ 에러 처리 테스트 완료: {final_state.get('error_message', 'N/A')}")