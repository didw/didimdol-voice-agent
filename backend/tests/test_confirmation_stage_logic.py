"""
확인 단계 로직 테스트
PRD 요구사항에 따른 그룹별 확인 및 수정 처리 테스트
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch

from app.graph.state import AgentState
from app.graph.nodes.workers.scenario_logic import process_scenario_logic_node
from app.graph.nodes.workers.scenario_helpers import check_required_info_completion


class TestConfirmationStageLogic:
    """확인 단계 처리 로직 테스트"""
    
    @pytest.fixture
    def sample_scenario_data(self):
        """테스트용 시나리오 데이터"""
        return {
            "scenario_name": "입출금통장 신규",
            "required_info_fields": [
                {
                    "key": "customer_name",
                    "display_name": "고객명",
                    "required": True,
                    "type": "text",
                    "default": "홍길동"
                },
                {
                    "key": "customer_phone",
                    "display_name": "연락처",
                    "required": True,
                    "type": "text",
                    "default": "010-1234-5678"
                },
                {
                    "key": "use_lifelong_account",
                    "display_name": "평생계좌 등록",
                    "required": True,
                    "type": "boolean"
                }
            ],
            "stages": {
                "greeting": {
                    "id": "greeting",
                    "prompt": "안녕하세요. 입출금통장 개설을 도와드리겠습니다.",
                    "is_question": True,
                    "default_next_stage_id": "ask_lifelong_account"
                },
                "ask_lifelong_account": {
                    "id": "ask_lifelong_account",
                    "prompt": "평생계좌번호로 등록하시겠어요?",
                    "is_question": True,
                    "expected_info_key": "use_lifelong_account",
                    "default_next_stage_id": "ask_internet_banking"
                }
            }
        }
    
    @pytest.mark.asyncio
    async def test_check_required_info_completion(self, sample_scenario_data):
        """필수 정보 완료 체크 테스트"""
        required_fields = sample_scenario_data["required_info_fields"]
        
        # Case 1: 모든 정보가 없는 경우
        collected_info = {}
        is_complete, missing_fields = check_required_info_completion(collected_info, required_fields)
        assert not is_complete
        assert len(missing_fields) == 3
        assert "customer_name" in missing_fields
        assert "customer_phone" in missing_fields
        assert "use_lifelong_account" in missing_fields
        
        # Case 2: 일부 정보만 있는 경우
        collected_info = {
            "customer_name": "홍길동",
            "customer_phone": "010-1234-5678"
        }
        is_complete, missing_fields = check_required_info_completion(collected_info, required_fields)
        assert not is_complete
        assert len(missing_fields) == 1
        assert "use_lifelong_account" in missing_fields
        
        # Case 3: 모든 정보가 있는 경우
        collected_info = {
            "customer_name": "홍길동",
            "customer_phone": "010-1234-5678",
            "use_lifelong_account": True
        }
        is_complete, missing_fields = check_required_info_completion(collected_info, required_fields)
        assert is_complete
        assert len(missing_fields) == 0
        
        print("✅ 필수 정보 완료 체크 테스트 통과")
    
    @pytest.mark.asyncio
    async def test_confirmation_intent_processing(self):
        """확인 의도 처리 테스트"""
        # 긍정 응답 케이스
        positive_responses = ["네", "맞아요", "예", "맞습니다", "확인했습니다"]
        for response in positive_responses:
            intent = self._classify_confirmation_intent(response)
            assert intent == "confirmed", f"'{response}'가 confirmed로 분류되지 않음"
        
        # 부정 응답 케이스
        negative_responses = ["아니요", "틀려요", "다시 알려드릴게요", "수정할게요"]
        for response in negative_responses:
            intent = self._classify_confirmation_intent(response)
            assert intent == "needs_correction", f"'{response}'가 needs_correction으로 분류되지 않음"
        
        # 특정 수정 요청 케이스
        specific_corrections = [
            "이름이 틀렸어요",
            "번호가 틀렸습니다",
            "연락처를 수정하고 싶어요"
        ]
        for response in specific_corrections:
            intent = self._classify_confirmation_intent(response)
            assert intent == "specific_correction", f"'{response}'가 specific_correction으로 분류되지 않음"
        
        print("✅ 확인 의도 처리 테스트 통과")
    
    @pytest.mark.asyncio
    async def test_stage_transition_with_default_values(self):
        """기본값이 적용된 상태에서의 단계 전환 테스트"""
        # 초기 상태 생성
        state = AgentState(
            session_id="test_defaults",
            current_product_type="deposit_account",
            current_scenario_stage_id="greeting",
            collected_product_info={},  # 비어있지만 기본값이 적용될 예정
            active_scenario_name="입출금통장 신규",
            messages=[]
        )
        
        # 시나리오 데이터 모킹
        scenario_data = {
            "required_info_fields": [
                {
                    "key": "customer_name",
                    "default": "홍길동",
                    "required": True
                },
                {
                    "key": "customer_phone", 
                    "default": "010-1234-5678",
                    "required": True
                }
            ],
            "stages": {
                "greeting": {
                    "id": "greeting",
                    "prompt": "기본 정보를 확인하겠습니다.",
                    "apply_defaults": True,
                    "default_next_stage_id": "next_stage"
                }
            }
        }
        
        with patch('app.graph.utils.get_active_scenario_data', return_value=scenario_data):
            # greeting 단계에서 기본값이 적용되어야 함
            result = await process_scenario_logic_node(state)
            
            # 기본값이 적용되었는지 확인
            collected_info = result.collected_product_info
            assert collected_info.get("customer_name") == "홍길동"
            assert collected_info.get("customer_phone") == "010-1234-5678"
            
            print("✅ 기본값 적용 테스트 통과")
    
    @pytest.mark.asyncio
    async def test_grouped_info_collection_strategy(self):
        """그룹별 정보 수집 전략 테스트"""
        # 정보 그룹 정의
        info_groups = {
            "basic_info": {
                "fields": ["customer_name", "customer_phone"],
                "priority": 1,
                "max_items": 2
            },
            "account_settings": {
                "fields": ["use_lifelong_account"],
                "priority": 2,
                "max_items": 1
            },
            "internet_banking": {
                "fields": ["security_medium", "transfer_limit_per_time", "transfer_limit_per_day"],
                "priority": 3,
                "max_items": 2,
                "depends_on": {"use_internet_banking": True}
            }
        }
        
        # Case 1: 아무 정보도 없을 때 - 첫 번째 그룹 선택
        collected_info = {}
        next_group = self._get_next_info_group(collected_info, info_groups)
        assert next_group == "basic_info"
        
        # Case 2: 기본 정보 수집 후 - 다음 우선순위 그룹 선택
        collected_info = {
            "customer_name": "홍길동",
            "customer_phone": "010-1234-5678"
        }
        next_group = self._get_next_info_group(collected_info, info_groups)
        assert next_group == "account_settings"
        
        # Case 3: 의존성이 있는 그룹 - 조건 미충족 시 건너뛰기
        collected_info = {
            "customer_name": "홍길동",
            "customer_phone": "010-1234-5678",
            "use_lifelong_account": True,
            "use_internet_banking": False  # 인터넷뱅킹 미사용
        }
        next_group = self._get_next_info_group(collected_info, info_groups)
        assert next_group is None  # 인터넷뱅킹 미사용으로 관련 그룹 건너뛰기
        
        print("✅ 그룹별 정보 수집 전략 테스트 통과")
    
    @pytest.mark.asyncio 
    async def test_correction_request_extraction(self):
        """수정 요청 추출 테스트"""
        test_cases = [
            {
                "input": "이름은 김철수입니다",
                "expected_field": "customer_name",
                "expected_value": "김철수"
            },
            {
                "input": "번호는 010-9876-5432로 변경해주세요",
                "expected_field": "customer_phone",
                "expected_value": "010-9876-5432"
            },
            {
                "input": "김민수로 수정하고 싶어요",
                "expected_field": "customer_name",
                "expected_value": "김민수"
            }
        ]
        
        for test_case in test_cases:
            field, value = self._extract_correction_request(test_case["input"])
            assert field == test_case["expected_field"]
            assert value == test_case["expected_value"]
        
        print("✅ 수정 요청 추출 테스트 통과")
    
    def _classify_confirmation_intent(self, user_input: str) -> str:
        """확인 의도 분류 (간단한 구현)"""
        positive_keywords = ["네", "맞아요", "예", "맞습니다", "확인"]
        negative_keywords = ["아니요", "틀려요", "수정", "변경", "다시"]
        specific_keywords = ["이름이", "번호가", "연락처", "주소가"]
        
        # 특정 필드 언급 확인
        for keyword in specific_keywords:
            if keyword in user_input:
                return "specific_correction"
        
        # 긍정/부정 확인
        for keyword in positive_keywords:
            if keyword in user_input:
                return "confirmed"
        
        for keyword in negative_keywords:
            if keyword in user_input:
                return "needs_correction"
        
        return "unclear"
    
    def _get_next_info_group(self, collected_info: dict, info_groups: dict) -> str:
        """다음 수집할 정보 그룹 결정"""
        sorted_groups = sorted(info_groups.items(), key=lambda x: x[1]["priority"])
        
        for group_name, group_info in sorted_groups:
            # 의존성 체크
            if "depends_on" in group_info:
                dependency_met = all(
                    collected_info.get(field) == value
                    for field, value in group_info["depends_on"].items()
                )
                if not dependency_met:
                    continue
            
            # 아직 수집되지 않은 필드 확인
            missing_fields = [
                field for field in group_info["fields"]
                if field not in collected_info
            ]
            
            if missing_fields:
                return group_name
        
        return None
    
    def _extract_correction_request(self, user_input: str) -> tuple:
        """수정 요청에서 필드와 값 추출"""
        import re
        
        patterns = {
            "customer_name": [
                r"(?:이름은|성함은)?\s*([가-힣]{2,4})(?:입니다|이에요|예요)?",
                r"([가-힣]{2,4})(?:으로|로)\s*(?:수정|변경)"
            ],
            "customer_phone": [
                r"(?:번호는|연락처는)?\s*(010[-\s]?\d{4}[-\s]?\d{4})",
                r"(010[-\s]?\d{4}[-\s]?\d{4})(?:으로|로)\s*(?:수정|변경)"
            ]
        }
        
        for field, field_patterns in patterns.items():
            for pattern in field_patterns:
                match = re.search(pattern, user_input)
                if match:
                    return field, match.group(1).strip()
        
        return None, None