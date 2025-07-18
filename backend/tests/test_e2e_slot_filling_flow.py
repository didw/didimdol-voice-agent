"""
End-to-End 슬롯필링 플로우 테스트
전체 대화 흐름을 통한 슬롯필링 확인 기능 테스트
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
import json

from app.graph.agent import run_agent_streaming


class TestE2ESlotFillingFlow:
    """전체 대화 흐름을 통한 슬롯필링 테스트"""
    
    @pytest.fixture
    def mock_services(self):
        """공통 서비스 목업"""
        mock_rag = Mock()
        mock_rag.is_ready.return_value = True
        
        mock_web = Mock()
        mock_web.asearch = AsyncMock(return_value=[{"content": "검색결과"}])
        
        return mock_rag, mock_web
    
    @pytest.mark.asyncio
    async def test_complete_deposit_account_flow(self, mock_services):
        """
        입출금통장 개설 전체 플로우 테스트
        PRD 4.2 대화 흐름 설계에 따른 완전한 시나리오
        """
        mock_rag, mock_web = mock_services
        session_id = "test_complete_flow"
        
        with patch('app.graph.agent.rag_service', mock_rag), \
             patch('app.graph.agent.web_search_service', mock_web):
            
            # 대화 히스토리 추적
            conversation_history = []
            
            # Stage 1: 시작 및 기본정보 확인
            print("\n=== Stage 1: 시작 및 기본정보 확인 ===")
            state_1 = await self._run_conversation_turn(
                user_input="입출금통장 개설하고 싶어요",
                session_id=session_id,
                current_state=None
            )
            
            assert state_1["current_product_type"] == "deposit_account"
            assert state_1["current_scenario_stage_id"] == "greeting"
            assert "홍길동" in state_1["final_response_text_for_tts"]
            assert "010-1234-5678" in state_1["final_response_text_for_tts"]
            conversation_history.append({
                "user": "입출금통장 개설하고 싶어요",
                "ai": state_1["final_response_text_for_tts"][:100] + "..."
            })
            
            # Stage 2: 개인정보 확인 응답
            print("\n=== Stage 2: 개인정보 확인 ===")
            state_2 = await self._run_conversation_turn(
                user_input="네, 맞아요",
                session_id=session_id,
                current_state=state_1
            )
            
            assert state_2["current_scenario_stage_id"] == "ask_lifelong_account"
            assert state_2["collected_product_info"]["confirm_personal_info"] is True
            assert "평생계좌번호로 등록하시겠어요?" in state_2["final_response_text_for_tts"]
            conversation_history.append({
                "user": "네, 맞아요",
                "ai": state_2["final_response_text_for_tts"][:100] + "..."
            })
            
            # Stage 3: 평생계좌 설정
            print("\n=== Stage 3: 평생계좌 설정 ===")
            state_3 = await self._run_conversation_turn(
                user_input="네, 평생계좌로 등록할게요",
                session_id=session_id,
                current_state=state_2
            )
            
            assert state_3["current_scenario_stage_id"] == "ask_internet_banking"
            assert state_3["collected_product_info"]["use_lifelong_account"] is True
            conversation_history.append({
                "user": "네, 평생계좌로 등록할게요",
                "ai": state_3["final_response_text_for_tts"][:100] + "..."
            })
            
            # Stage 4: 인터넷뱅킹 가입 여부
            print("\n=== Stage 4: 인터넷뱅킹 가입 여부 ===")
            state_4 = await self._run_conversation_turn(
                user_input="네, 인터넷뱅킹도 가입할게요",
                session_id=session_id,
                current_state=state_3
            )
            
            assert state_4["current_scenario_stage_id"] == "collect_internet_banking_info"
            assert state_4["collected_product_info"]["use_internet_banking"] is True
            conversation_history.append({
                "user": "네, 인터넷뱅킹도 가입할게요",
                "ai": state_4["final_response_text_for_tts"][:100] + "..."
            })
            
            # Stage 5: 인터넷뱅킹 정보 수집 (그룹별)
            print("\n=== Stage 5: 인터넷뱅킹 정보 수집 ===")
            
            # Entity Agent 목업 설정
            mock_entity_response = {
                "extracted_entities": {
                    "security_medium": "보안카드",
                    "transfer_limit_per_time": 500,
                    "transfer_limit_per_day": 1000,
                    "important_transaction_alert": True,
                    "withdrawal_alert": True
                },
                "collected_info": state_4["collected_product_info"].copy()
            }
            mock_entity_response["collected_info"].update(mock_entity_response["extracted_entities"])
            
            with patch('app.agents.entity_agent.entity_agent.process_slot_filling',
                      AsyncMock(return_value=mock_entity_response)):
                
                state_5 = await self._run_conversation_turn(
                    user_input="보안카드로 하고, 1회 500만원, 1일 1000만원으로 하고, 알림은 다 신청할게요",
                    session_id=session_id,
                    current_state=state_4
                )
            
            # 인터넷뱅킹 정보가 모두 수집되었는지 확인
            ib_info = state_5["collected_product_info"]
            assert ib_info["security_medium"] == "보안카드"
            assert ib_info["transfer_limit_per_time"] == 500
            assert ib_info["transfer_limit_per_day"] == 1000
            assert ib_info["important_transaction_alert"] is True
            assert ib_info["withdrawal_alert"] is True
            
            # Stage 6: 체크카드 신청 여부
            print("\n=== Stage 6: 체크카드 신청 여부 ===")
            state_6 = await self._run_conversation_turn(
                user_input="아니요, 체크카드는 필요없어요",
                session_id=session_id,
                current_state=state_5
            )
            
            # 체크카드 미신청으로 최종 요약으로 이동
            assert state_6["collected_product_info"].get("use_check_card", False) is False
            
            # 최종 수집된 정보 검증
            final_info = state_6["collected_product_info"]
            print("\n=== 최종 수집된 정보 ===")
            print(f"고객명: {final_info.get('customer_name')}")
            print(f"연락처: {final_info.get('customer_phone')}")
            print(f"평생계좌: {final_info.get('use_lifelong_account')}")
            print(f"인터넷뱅킹: {final_info.get('use_internet_banking')}")
            print(f"보안매체: {final_info.get('security_medium')}")
            print(f"이체한도: 1회 {final_info.get('transfer_limit_per_time')}만원, 1일 {final_info.get('transfer_limit_per_day')}만원")
            print(f"체크카드: {final_info.get('use_check_card', False)}")
            
            # 필수 정보가 모두 수집되었는지 확인
            assert final_info.get("customer_name") == "홍길동"
            assert final_info.get("customer_phone") == "010-1234-5678"
            assert final_info.get("confirm_personal_info") is True
            assert final_info.get("use_lifelong_account") is True
            assert final_info.get("use_internet_banking") is True
            
            print("\n✅ 전체 플로우 테스트 완료")
            print(f"총 대화 턴 수: {len(conversation_history)}")
    
    @pytest.mark.asyncio
    async def test_flow_with_corrections(self, mock_services):
        """
        수정 요청이 포함된 플로우 테스트
        PRD 5.3 수정 요청 케이스
        """
        mock_rag, mock_web = mock_services
        session_id = "test_correction_flow"
        
        with patch('app.graph.agent.rag_service', mock_rag), \
             patch('app.graph.agent.web_search_service', mock_web):
            
            # Stage 1: 시작
            state_1 = await self._run_conversation_turn(
                user_input="통장 개설하려고 합니다",
                session_id=session_id,
                current_state=None
            )
            
            # Stage 2: 개인정보 수정 요청
            print("\n=== 개인정보 수정 요청 ===")
            
            # Entity Agent 목업 - 수정된 정보 추출
            mock_entity_response = {
                "extracted_entities": {
                    "customer_name": "김철수",
                    "customer_phone": "010-9876-5432"
                },
                "collected_info": {
                    "customer_name": "김철수",
                    "customer_phone": "010-9876-5432"
                }
            }
            
            with patch('app.agents.entity_agent.entity_agent.process_slot_filling',
                      AsyncMock(return_value=mock_entity_response)):
                
                state_2 = await self._run_conversation_turn(
                    user_input="아니요, 이름은 김철수이고 번호는 010-9876-5432예요",
                    session_id=session_id,
                    current_state=state_1
                )
            
            # 수정된 정보 확인
            assert state_2["collected_product_info"]["customer_name"] == "김철수"
            assert state_2["collected_product_info"]["customer_phone"] == "010-9876-5432"
            
            print(f"✅ 정보 수정 완료: {state_2['collected_product_info']}")
            
            # Stage 3: 수정된 정보 확인
            state_3 = await self._run_conversation_turn(
                user_input="네, 이제 맞아요",
                session_id=session_id,
                current_state=state_2
            )
            
            assert state_3["collected_product_info"]["confirm_personal_info"] is True
            print("✅ 수정된 정보 확인 완료")
    
    @pytest.mark.asyncio
    async def test_flow_with_skip_options(self, mock_services):
        """
        선택 항목을 건너뛰는 플로우 테스트
        인터넷뱅킹과 체크카드를 모두 신청하지 않는 경우
        """
        mock_rag, mock_web = mock_services
        session_id = "test_skip_flow"
        
        with patch('app.graph.agent.rag_service', mock_rag), \
             patch('app.graph.agent.web_search_service', mock_web):
            
            # 빠른 진행을 위해 초기 상태 설정
            initial_state = {
                "session_id": session_id,
                "current_product_type": "deposit_account",
                "current_scenario_stage_id": "ask_internet_banking",
                "collected_product_info": {
                    "customer_name": "홍길동",
                    "customer_phone": "010-1234-5678",
                    "confirm_personal_info": True,
                    "use_lifelong_account": True
                },
                "active_scenario_name": "신한은행 입출금통장 신규 상담",
                "messages": []
            }
            
            # 인터넷뱅킹 건너뛰기
            state_1 = await self._run_conversation_turn(
                user_input="아니요, 인터넷뱅킹은 나중에 할게요",
                session_id=session_id,
                current_state=initial_state
            )
            
            assert state_1["collected_product_info"]["use_internet_banking"] is False
            assert state_1["current_scenario_stage_id"] == "ask_check_card"
            
            # 체크카드도 건너뛰기
            state_2 = await self._run_conversation_turn(
                user_input="체크카드도 필요없어요",
                session_id=session_id,
                current_state=state_1
            )
            
            assert state_2["collected_product_info"].get("use_check_card", False) is False
            
            # 최종 수집된 정보 - 필수 항목만
            final_info = state_2["collected_product_info"]
            assert final_info["customer_name"] == "홍길동"
            assert final_info["customer_phone"] == "010-1234-5678"
            assert final_info["use_lifelong_account"] is True
            assert final_info["use_internet_banking"] is False
            assert final_info.get("use_check_card", False) is False
            
            # 선택 항목 관련 필드들이 없어야 함
            assert "security_medium" not in final_info
            assert "transfer_limit_per_time" not in final_info
            assert "card_type" not in final_info
            
            print("✅ 선택 항목 건너뛰기 플로우 테스트 완료")
    
    async def _run_conversation_turn(self, user_input: str, session_id: str, current_state: dict = None):
        """대화 턴 실행 헬퍼 함수"""
        result_stream = []
        async for item in run_agent_streaming(
            user_input_text=user_input,
            session_id=session_id,
            current_state_dict=current_state
        ):
            result_stream.append(item)
        
        # 최종 상태 추출
        for item in result_stream:
            if isinstance(item, dict) and item.get("type") == "final_state":
                return item["data"]
        
        return None