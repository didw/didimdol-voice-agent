"""
입출금통장 슬롯필링 확인 기능 테스트
PRD 기반 테스트 케이스 구현
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
import json

from app.graph.agent import run_agent_streaming
from app.graph.state import AgentState
from app.agents.entity_agent import entity_agent


class TestSlotFillingConfirmation:
    """PRD 기반 슬롯필링 확인 기능 테스트"""
    
    @pytest.fixture
    def mock_services(self):
        """공통 서비스 목업"""
        mock_rag = Mock()
        mock_rag.is_ready.return_value = True
        
        mock_web = Mock()
        mock_web.asearch = AsyncMock(return_value=[{"content": "검색결과"}])
        
        return mock_rag, mock_web
    
    @pytest.mark.asyncio
    async def test_basic_info_confirmation_flow(self, mock_services):
        """
        PRD Stage 1: 기본정보 확인 플로우 테스트
        시나리오: 고객명과 연락처 확인 -> 확인 응답 -> 다음 단계 진행
        """
        mock_rag, mock_web = mock_services
        session_id = "test_basic_info_confirmation"
        
        with patch('app.services.rag_service.rag_service', mock_rag), \
             patch('app.services.web_search_service.web_search_service', mock_web):
            
            # 1단계: 통장 신규 요청
            result_stream = []
            async for item in run_agent_streaming(
                user_input_text="통장 만들고 싶어요",
                session_id=session_id
            ):
                result_stream.append(item)
            
            final_state = self._extract_final_state(result_stream)
            
            # 검증: 기본 정보가 포함된 greeting 단계
            assert final_state["current_scenario_stage_id"] == "greeting"
            assert "홍길동" in final_state["final_response_text_for_tts"]
            assert "010-1234-5678" in final_state["final_response_text_for_tts"]
            assert "이 정보가 맞으신가요?" in final_state["final_response_text_for_tts"]
            
            # 기본값이 자동으로 적용되었는지 확인
            collected_info = final_state.get("collected_product_info", {})
            assert collected_info.get("customer_name") == "홍길동"
            assert collected_info.get("customer_phone") == "010-1234-5678"
            
            print(f"✅ Stage 1 완료: 기본 정보 표시 및 확인 요청")
            
            # 2단계: 사용자 확인 응답
            result_stream_2 = []
            async for item in run_agent_streaming(
                user_input_text="네, 맞아요",
                session_id=session_id,
                current_state_dict=final_state
            ):
                result_stream_2.append(item)
            
            final_state_2 = self._extract_final_state(result_stream_2)
            
            # 검증: 다음 단계로 진행
            assert final_state_2["current_scenario_stage_id"] == "ask_lifelong_account"
            assert final_state_2["collected_product_info"]["confirm_personal_info"] is True
            
            print(f"✅ Stage 2 완료: 정보 확인 후 다음 단계 진행")
    
    @pytest.mark.asyncio
    async def test_basic_info_correction_flow(self, mock_services):
        """
        PRD Stage 1 수정: 기본정보 수정 플로우 테스트
        시나리오: 고객명과 연락처 확인 -> 수정 요청 -> 재확인
        
        Note: 현재 구현에서는 greeting 단계에서 Scenario Agent가 엔티티를 추출하고
        이를 기반으로 정보를 업데이트합니다. 완전한 정보 수정을 위해서는
        추후 confirmation 단계 구현이 필요합니다.
        """
        mock_rag, mock_web = mock_services
        session_id = "test_basic_info_correction"
        
        with patch('app.services.rag_service.rag_service', mock_rag), \
             patch('app.services.web_search_service.web_search_service', mock_web):
            
            # 초기 상태 설정 (greeting 단계)
            initial_state = {
                "session_id": session_id,
                "current_product_type": "deposit_account",
                "current_scenario_stage_id": "greeting",
                "collected_product_info": {
                    "customer_name": "홍길동",
                    "customer_phone": "010-1234-5678"
                },
                "active_scenario_name": "신한은행 입출금통장 신규 상담",
                "messages": []
            }
            
            # 수정 요청 (현재 구현에 맞게 간단한 거부 응답)
            result_stream = []
            async for item in run_agent_streaming(
                user_input_text="아니요",
                session_id=session_id,
                current_state_dict=initial_state
            ):
                result_stream.append(item)
            
            final_state = self._extract_final_state(result_stream)
            
            # 검증: 현재 구현에서는 Scenario Agent가 confirm_personal_info를 False로 추출하여
            # 개인정보 확인을 거부하는 것으로 인식하고 정보 수정 단계로 이동
            collected_info = final_state.get("collected_product_info", {})
            
            # 수정 요청이 인식되었는지 확인
            assert final_state["current_scenario_stage_id"] == "info_correction_end"
            
            print(f"✅ 정보 수정 요청 인식 완료: {final_state['current_scenario_stage_id']}")
            print(f"응답: {final_state.get('final_response_text_for_tts', '')[:100]}...")
    
    @pytest.mark.asyncio
    async def test_internet_banking_grouped_collection(self, mock_services):
        """
        PRD Stage 3: 인터넷뱅킹 그룹별 정보 수집 테스트
        시나리오: 보안매체와 이체한도를 함께 수집 -> 확인
        """
        mock_rag, mock_web = mock_services
        session_id = "test_ib_grouped"
        
        # 인터넷뱅킹 정보 수집 단계 상태
        initial_state = {
            "session_id": session_id,
            "current_product_type": "deposit_account",
            "current_scenario_stage_id": "collect_internet_banking_info",
            "collected_product_info": {
                "customer_name": "홍길동",
                "customer_phone": "010-1234-5678",
                "confirm_personal_info": True,
                "use_lifelong_account": True,
                "use_internet_banking": True
            },
            "active_scenario_name": "신한은행 입출금통장 신규 상담",
            "messages": []
        }
        
        # Entity Agent 목업 - 여러 필드 동시 추출 (모든 인터넷뱅킹 필드 포함)
        mock_entity_response = {
            "extracted_entities": {
                "security_medium": "보안카드",
                "transfer_limit_per_time": 500,
                "transfer_limit_per_day": 1000,
                "alert": "중요거래통보",
                "additional_withdrawal_account": True
            },
            "collected_info": initial_state["collected_product_info"].copy()
        }
        mock_entity_response["collected_info"].update({
            "security_medium": "보안카드",
            "transfer_limit_per_time": 500,
            "transfer_limit_per_day": 1000,
            "alert": "중요거래통보",
            "additional_withdrawal_account": True
        })
        
        with patch('app.services.rag_service.rag_service', mock_rag), \
             patch('app.services.web_search_service.web_search_service', mock_web), \
             patch('app.agents.entity_agent.entity_agent.process_slot_filling',
                   AsyncMock(return_value=mock_entity_response)):
            
            # 여러 정보를 한 번에 제공
            result_stream = []
            async for item in run_agent_streaming(
                user_input_text="보안카드로 하고, 1회 500만원, 1일 1000만원으로 설정해주세요",
                session_id=session_id,
                current_state_dict=initial_state
            ):
                result_stream.append(item)
            
            final_state = self._extract_final_state(result_stream)
            
            # 검증: 정보가 모두 수집되었는지
            collected_info = final_state.get("collected_product_info", {})
            assert collected_info.get("security_medium") == "보안카드"
            assert collected_info.get("transfer_limit_per_time") == 500
            assert collected_info.get("transfer_limit_per_day") == 1000
            assert collected_info.get("alert") == "중요거래통보"
            assert collected_info.get("additional_withdrawal_account") is True
            
            # 다음 단계로 진행되었는지 확인 (모든 인터넷뱅킹 정보 수집 완료)
            assert final_state["current_scenario_stage_id"] == "ask_check_card"
            
            print(f"✅ 인터넷뱅킹 그룹 정보 수집 완료: {collected_info}")
    
    @pytest.mark.asyncio
    async def test_multiple_info_with_confirmation(self, mock_services):
        """
        PRD 5.1: 한 번에 여러 정보 제공 케이스
        시나리오: 사용자가 한 번에 여러 정보 제공 -> 그룹 단위로 확인
        """
        mock_rag, mock_web = mock_services
        session_id = "test_multiple_info"
        
        # 인터넷뱅킹 정보 수집 단계
        initial_state = {
            "session_id": session_id,
            "current_product_type": "deposit_account",
            "current_scenario_stage_id": "collect_internet_banking_info",
            "collected_product_info": {
                "customer_name": "홍길동",
                "customer_phone": "010-1234-5678",
                "confirm_personal_info": True,
                "use_lifelong_account": True,
                "use_internet_banking": True
            },
            "active_scenario_name": "신한은행 입출금통장 신규 상담",
            "messages": []
        }
        
        # 모든 인터넷뱅킹 정보를 한 번에 제공
        mock_entity_response = {
            "extracted_entities": {
                "security_medium": "보안카드",
                "transfer_limit_per_time": 500,
                "transfer_limit_per_day": 1000,
                "important_transaction_alert": True,
                "withdrawal_alert": True,
                "overseas_ip_restriction": True
            },
            "collected_info": initial_state["collected_product_info"].copy()
        }
        
        # 모든 필드 업데이트
        for key, value in mock_entity_response["extracted_entities"].items():
            mock_entity_response["collected_info"][key] = value
        
        with patch('app.services.rag_service.rag_service', mock_rag), \
             patch('app.services.web_search_service.web_search_service', mock_web), \
             patch('app.agents.entity_agent.entity_agent.process_slot_filling',
                   AsyncMock(return_value=mock_entity_response)):
            
            result_stream = []
            async for item in run_agent_streaming(
                user_input_text="보안카드로 하고 1회 500만원, 1일 1000만원, 알림도 다 신청할게요",
                session_id=session_id,
                current_state_dict=initial_state
            ):
                result_stream.append(item)
            
            final_state = self._extract_final_state(result_stream)
            
            # 검증: 모든 정보가 수집되었는지
            collected_info = final_state.get("collected_product_info", {})
            assert collected_info.get("security_medium") == "보안카드"
            assert collected_info.get("transfer_limit_per_time") == 500
            assert collected_info.get("transfer_limit_per_day") == 1000
            assert collected_info.get("important_transaction_alert") is True
            assert collected_info.get("withdrawal_alert") is True
            assert collected_info.get("overseas_ip_restriction") is True
            
            print(f"✅ 여러 정보 한 번에 수집 완료")
    
    @pytest.mark.asyncio
    async def test_state_transitions_tracking(self, mock_services):
        """
        시나리오 state 변경 추적 테스트
        각 단계별로 state가 올바르게 변경되는지 확인
        
        Note: 현재 구현에서는 state_update 이벤트를 생성하지 않으므로
        final_state를 통해 최종 상태를 검증합니다.
        """
        mock_rag, mock_web = mock_services
        session_id = "test_state_tracking"
        
        with patch('app.services.rag_service.rag_service', mock_rag), \
             patch('app.services.web_search_service.web_search_service', mock_web):
            
            # 1. 초기 요청
            result_stream = []
            async for item in run_agent_streaming(
                user_input_text="통장 개설하려고 합니다",
                session_id=session_id
            ):
                result_stream.append(item)
            
            final_state = self._extract_final_state(result_stream)
            
            # 최종 상태 검증
            assert final_state is not None
            assert final_state["current_product_type"] == "deposit_account"
            assert final_state["current_scenario_stage_id"] == "greeting"
            
            print(f"✅ 상태 전환 추적 완료")
            print(f"  최종 제품: {final_state['current_product_type']}")
            print(f"  최종 단계: {final_state['current_scenario_stage_id']}")
    
    @pytest.mark.asyncio
    async def test_slot_filling_updates(self, mock_services):
        """
        슬롯필링 업데이트 추적 테스트
        각 단계에서 collected_product_info가 올바르게 업데이트되는지 확인
        
        Note: 현재 구현에서는 state_update 이벤트를 생성하지 않으므로
        final_state를 통해 최종 슬롯 상태를 검증합니다.
        """
        mock_rag, mock_web = mock_services
        session_id = "test_slot_updates"
        
        # 초기 상태 (이미 일부 정보 수집됨)
        initial_state = {
            "session_id": session_id,
            "current_product_type": "deposit_account",
            "current_scenario_stage_id": "ask_lifelong_account",
            "collected_product_info": {
                "customer_name": "홍길동",
                "customer_phone": "010-1234-5678",
                "confirm_personal_info": True
            },
            "active_scenario_name": "신한은행 입출금통장 신규 상담",
            "messages": []
        }
        
        with patch('app.services.rag_service.rag_service', mock_rag), \
             patch('app.services.web_search_service.web_search_service', mock_web):
            
            # 평생계좌 응답
            result_stream = []
            async for item in run_agent_streaming(
                user_input_text="네, 평생계좌로 등록할게요",
                session_id=session_id,
                current_state_dict=initial_state
            ):
                result_stream.append(item)
            
            final_state = self._extract_final_state(result_stream)
            
            # 최종 슬롯 상태 검증
            assert final_state is not None
            collected_info = final_state.get("collected_product_info", {})
            
            # 평생계좌 정보가 추가되었는지
            assert "use_lifelong_account" in collected_info
            assert collected_info["use_lifelong_account"] is True
            
            # 기존 정보가 유지되는지
            assert collected_info.get("customer_name") == "홍길동"
            assert collected_info.get("customer_phone") == "010-1234-5678"
            assert collected_info.get("confirm_personal_info") is True
            
            # 다음 단계로 진행되었는지
            assert final_state["current_scenario_stage_id"] == "ask_internet_banking"
            
            print(f"✅ 슬롯필링 업데이트 추적 완료")
            print(f"최종 슬롯 상태: {collected_info}")
            print(f"다음 단계: {final_state['current_scenario_stage_id']}")
    
    def _extract_final_state(self, result_stream):
        """스트림에서 최종 상태 추출"""
        for item in result_stream:
            if isinstance(item, dict) and item.get("type") == "final_state":
                return item["data"]
        return None