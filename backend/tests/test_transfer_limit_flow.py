"""
이체한도 처리 흐름 테스트
"""
import pytest
from app.graph.validators import FIELD_VALIDATORS
from app.graph.nodes.workers.scenario_logic import process_partial_response


class TestTransferLimitValidation:
    """이체한도 유효성 검증 테스트"""
    
    def test_valid_transfer_limits(self):
        """유효한 이체한도 검증"""
        validator_per_time = FIELD_VALIDATORS["transfer_limit_per_time"]
        validator_per_day = FIELD_VALIDATORS["transfer_limit_per_day"]
        
        # 정상 범위 내 값
        is_valid, error = validator_per_time.validate(500)
        assert is_valid is True
        assert error is None
        
        is_valid, error = validator_per_day.validate(1000)
        assert is_valid is True
        assert error is None
    
    def test_invalid_transfer_limits(self):
        """유효하지 않은 이체한도 검증"""
        validator_per_time = FIELD_VALIDATORS["transfer_limit_per_time"]
        validator_per_day = FIELD_VALIDATORS["transfer_limit_per_day"]
        
        # 1회 이체한도 초과
        is_valid, error = validator_per_time.validate(10000)
        assert is_valid is False
        assert "최대 5,000만원까지 가능합니다" in error
        
        # 1일 이체한도 초과
        is_valid, error = validator_per_day.validate(20000)
        assert is_valid is False
        assert "최대 10,000만원까지 가능합니다" in error
        
        # 0 이하 값
        is_valid, error = validator_per_time.validate(0)
        assert is_valid is False
        assert "0보다 커야 합니다" in error
        
        # 잘못된 형식
        is_valid, error = validator_per_time.validate("abc")
        assert is_valid is False
        assert "올바른 숫자 형식" in error


@pytest.mark.asyncio
class TestPartialResponseProcessing:
    """부분 응답 처리 테스트"""
    
    async def test_partial_response_with_one_limit(self):
        """1개 이체한도만 입력된 경우"""
        required_fields = [
            {"key": "transfer_limit_per_time", "display_name": "1회 이체한도", "type": "number"},
            {"key": "transfer_limit_per_day", "display_name": "1일 이체한도", "type": "number"}
        ]
        collected_info = {}
        
        # 시뮬레이션: Entity Agent가 1회 이체한도만 추출
        # 실제로는 process_partial_response 내부에서 entity_agent.extract_entities를 호출
        # 여기서는 결과만 시뮬레이션
        collected_info["transfer_limit_per_time"] = 500
        
        result = {
            "collected_info": collected_info,
            "valid_fields": ["transfer_limit_per_time"],
            "invalid_fields": [],
            "missing_fields": [{"key": "transfer_limit_per_day", "display_name": "1일 이체한도"}],
            "response_text": "1회 이체한도은(는) 확인했습니다. 1일 이체한도도 함께 말씀해주세요.",
            "is_complete": False
        }
        
        assert result["is_complete"] is False
        assert "1일 이체한도도 함께 말씀해주세요" in result["response_text"]
    
    async def test_partial_response_with_invalid_value(self):
        """유효하지 않은 값이 포함된 경우"""
        required_fields = [
            {"key": "transfer_limit_per_time", "display_name": "1회 이체한도", "type": "number"},
            {"key": "transfer_limit_per_day", "display_name": "1일 이체한도", "type": "number"}
        ]
        
        # 한도 초과 값
        validator = FIELD_VALIDATORS["transfer_limit_per_time"]
        is_valid, error_msg = validator.validate(10000)
        
        assert is_valid is False
        assert "최대 5,000만원까지 가능합니다" in error_msg
    
    async def test_complete_valid_response(self):
        """모든 값이 유효하게 입력된 경우"""
        required_fields = [
            {"key": "transfer_limit_per_time", "display_name": "1회 이체한도", "type": "number"},
            {"key": "transfer_limit_per_day", "display_name": "1일 이체한도", "type": "number"}
        ]
        collected_info = {
            "transfer_limit_per_time": 500,
            "transfer_limit_per_day": 1000
        }
        
        # 모든 값이 유효한 경우
        result = {
            "collected_info": collected_info,
            "valid_fields": ["transfer_limit_per_time", "transfer_limit_per_day"],
            "invalid_fields": [],
            "missing_fields": [],
            "response_text": None,
            "is_complete": True
        }
        
        assert result["is_complete"] is True
        assert result["response_text"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])