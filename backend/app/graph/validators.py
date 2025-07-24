# backend/app/graph/validators.py
"""
필드별 유효성 검증 규칙
"""
from typing import Any, Tuple, Optional
import re


class TransferLimitValidator:
    """이체한도 검증"""
    
    def __init__(self, max_limit: int, field_type: str):
        self.max_limit = max_limit
        self.field_type = field_type
    
    def validate(self, value: Any) -> Tuple[bool, Optional[str]]:
        try:
            amount = int(value)
            if amount <= 0:
                return False, f"{self.field_type}는 0보다 커야 합니다."
            if amount > self.max_limit:
                return False, f"{self.field_type}는 최대 {self.max_limit:,}만원까지 가능합니다. {self.max_limit:,}만원 이하로 다시 말씀해주세요."
            return True, None
        except (ValueError, TypeError):
            return False, f"올바른 숫자 형식으로 말씀해주세요."


class PhoneNumberValidator:
    """전화번호 검증"""
    
    def validate(self, value: str) -> Tuple[bool, Optional[str]]:
        # 숫자만 추출
        numbers_only = re.sub(r'\D', '', value)
        
        # 한국 휴대폰 번호 패턴 (010, 011, 016, 017, 018, 019)
        pattern = r'^01[016789]\d{7,8}$'
        
        if re.match(pattern, numbers_only):
            return True, None
        return False, "올바른 휴대폰 번호 형식으로 다시 말씀해주세요. 예: 010-1234-5678"


class AddressValidator:
    """주소 검증"""
    
    def validate(self, value: str) -> Tuple[bool, Optional[str]]:
        # 최소 길이 체크
        if len(value.strip()) < 5:
            return False, "주소가 너무 짧습니다. 도로명 주소나 지번 주소를 입력해주세요."
        
        # 기본 주소 패턴 체크 (시/도, 구/군, 동/읍/면 등)
        address_patterns = ['시', '도', '구', '군', '동', '읍', '면', '로', '길']
        if not any(pattern in value for pattern in address_patterns):
            return False, "올바른 주소 형식으로 입력해주세요. 예: 서울시 강남구 테헤란로 123"
        
        return True, None


class NameValidator:
    """이름 검증"""
    
    def validate(self, value: str) -> Tuple[bool, Optional[str]]:
        # 한글 이름 패턴 (2-4자)
        pattern = r'^[가-힣]{2,4}$'
        
        if re.match(pattern, value.strip()):
            return True, None
        return False, "올바른 한글 이름을 입력해주세요. (2-4자)"


class BooleanValidator:
    """불린 값 검증"""
    
    def validate(self, value: Any) -> Tuple[bool, Optional[str]]:
        if isinstance(value, bool):
            return True, None
        if isinstance(value, str) and value.lower() in ['true', 'false']:
            return True, None
        return False, "예/아니오로 대답해주세요."


class ChoiceValidator:
    """선택지 검증"""
    
    def __init__(self, choices: list):
        self.choices = choices
    
    def validate(self, value: str) -> Tuple[bool, Optional[str]]:
        if value in self.choices:
            return True, None
        return False, f"다음 중에서 선택해주세요: {', '.join(self.choices)}"


# 필드별 검증기 매핑
FIELD_VALIDATORS = {
    "transfer_limit_per_time": TransferLimitValidator(5000, "1회 이체한도"),
    "transfer_limit_per_day": TransferLimitValidator(10000, "1일 이체한도"),
    "phone_number": PhoneNumberValidator(),
    "customer_phone": PhoneNumberValidator(),
    "address": AddressValidator(),
    "customer_name": NameValidator(),
    "limit_account_agreement": BooleanValidator(),
    "confirm_personal_info": BooleanValidator(),
    "use_lifelong_account": BooleanValidator(),
    "use_internet_banking": BooleanValidator(),
    "use_check_card": BooleanValidator(),
    "postpaid_transport": BooleanValidator(),
    "important_transaction_alert": BooleanValidator(),
    "withdrawal_alert": BooleanValidator(),
    "overseas_ip_restriction": BooleanValidator(),
}


def get_validator_for_field(field_key: str, field_info: dict = None) -> Optional[Any]:
    """필드에 맞는 검증기 반환"""
    
    # 매핑된 검증기가 있으면 반환
    if field_key in FIELD_VALIDATORS:
        return FIELD_VALIDATORS[field_key]
    
    # field_info가 있고 choices가 정의된 경우 ChoiceValidator 사용
    if field_info and field_info.get('choices'):
        return ChoiceValidator(field_info['choices'])
    
    # field_info가 있고 type이 boolean인 경우 BooleanValidator 사용
    if field_info and field_info.get('type') == 'boolean':
        return BooleanValidator()
    
    return None