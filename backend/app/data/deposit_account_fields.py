"""
입출금통장 시나리오의 필수 필드 정의
"""

DEPOSIT_ACCOUNT_REQUIRED_FIELDS = [
    # 기본정보 그룹
    {
        "key": "name",
        "display_name": "이름",
        "type": "text",
        "required": True,
        "group": "basic_info",
        "stage": "confirm_personal_info"
    },
    {
        "key": "english_name",
        "display_name": "영문이름",
        "type": "text",
        "required": True,
        "group": "basic_info",
        "stage": "confirm_personal_info"
    },
    {
        "key": "ssn",
        "display_name": "주민등록번호",
        "type": "text",
        "required": True,
        "group": "basic_info",
        "stage": "confirm_personal_info"
    },
    {
        "key": "phone_number",
        "display_name": "휴대폰번호",
        "type": "text",
        "required": True,
        "group": "basic_info",
        "stage": "confirm_personal_info"
    },
    {
        "key": "email",
        "display_name": "이메일",
        "type": "text",
        "required": True,
        "group": "basic_info",
        "stage": "confirm_personal_info"
    },
    {
        "key": "address",
        "display_name": "집주소",
        "type": "text",
        "required": True,
        "group": "basic_info",
        "stage": "confirm_personal_info"
    },
    {
        "key": "work_address",
        "display_name": "직장주소",
        "type": "text",
        "required": True,
        "group": "basic_info",
        "stage": "confirm_personal_info"
    },
    
    # 전자금융 그룹 - security_medium_registration
    {
        "key": "security_medium",
        "display_name": "보안매체",
        "type": "choice",
        "required": True,
        "group": "electronic_banking",
        "stage": "security_medium_registration",
        "choices": ["futuretech_19284019384", "comas_rsa_12930295", "security_card", "shinhan_otp"]
    },
    {
        "key": "transfer_limit_once",
        "display_name": "1회 이체한도",
        "type": "number",
        "required": True,
        "group": "electronic_banking",
        "stage": "security_medium_registration",
        "unit": "만원"
    },
    {
        "key": "transfer_limit_daily",
        "display_name": "1일 이체한도",
        "type": "number",
        "required": True,
        "group": "electronic_banking",
        "stage": "security_medium_registration",
        "unit": "만원"
    },
    
    # 전자금융 그룹 - additional_services
    {
        "key": "important_transaction_alert",
        "display_name": "중요거래 알림",
        "type": "boolean",
        "required": True,
        "group": "electronic_banking",
        "stage": "additional_services"
    },
    {
        "key": "withdrawal_alert",
        "display_name": "출금 알림",
        "type": "boolean",
        "required": True,
        "group": "electronic_banking",
        "stage": "additional_services"
    },
    {
        "key": "overseas_ip_restriction",
        "display_name": "해외IP 제한",
        "type": "boolean",
        "required": True,
        "group": "electronic_banking",
        "stage": "additional_services"
    },
    
    # 체크카드 그룹 - card_selection
    {
        "key": "card_selection",
        "display_name": "체크카드 선택",
        "type": "choice",
        "required": True,
        "group": "check_card",
        "stage": "card_selection",
        "choices": ["sline_transit", "sline_regular", "deepdream_transit", "deepdream_regular", "heyyoung_regular"]
    },
    {
        "key": "card_receipt_method",
        "display_name": "카드 수령 방법",
        "type": "text",
        "required": True,
        "group": "check_card",
        "stage": "card_selection"
    },
    {
        "key": "transit_function",
        "display_name": "후불교통 기능",
        "type": "boolean",
        "required": True,
        "group": "check_card",
        "stage": "card_selection"
    },
    
    # 체크카드 그룹 - statement_delivery
    {
        "key": "statement_delivery_method",
        "display_name": "명세서 수령 방법",
        "type": "choice",
        "required": True,
        "group": "check_card",
        "stage": "statement_delivery",
        "choices": ["mobile", "email", "website"]
    },
    {
        "key": "statement_delivery_date",
        "display_name": "명세서 발송일",
        "type": "text",
        "required": True,
        "group": "check_card",
        "stage": "statement_delivery"
    },
    
    # 체크카드 그룹 - card_usage_alert
    {
        "key": "card_usage_alert",
        "display_name": "카드 사용 알림",
        "type": "choice",
        "required": True,
        "group": "check_card",
        "stage": "card_usage_alert",
        "choices": ["over_50000_free", "all_transactions_200won", "no_alert"]
    },
    
    # 체크카드 그룹 - card_password_setting
    {
        "key": "card_password_same_as_account",
        "display_name": "카드 비밀번호 계좌와 동일",
        "type": "boolean",
        "required": True,
        "group": "check_card",
        "stage": "card_password_setting"
    }
]

def get_deposit_account_fields():
    """입출금통장 필수 필드 반환"""
    return DEPOSIT_ACCOUNT_REQUIRED_FIELDS

def get_fields_for_stage(stage_id: str):
    """특정 스테이지의 필드만 반환"""
    return [field for field in DEPOSIT_ACCOUNT_REQUIRED_FIELDS if field.get("stage") == stage_id]

def get_fields_for_group(group_id: str):
    """특정 그룹의 필드만 반환"""
    return [field for field in DEPOSIT_ACCOUNT_REQUIRED_FIELDS if field.get("group") == group_id]

# 한글 키와 영문 키 매핑
KOREAN_TO_ENGLISH_KEY_MAPPING = {
    "이름": "name",
    "영문이름": "english_name",
    "주민번호": "ssn",
    "휴대폰번호": "phone_number",
    "이메일": "email",
    "집주소": "address",  # 집주소도 address로 매핑
    "직장주소": "work_address",
    "명세서발송일": "statement_delivery_date",
    "명세서 발송일": "statement_delivery_date"
}

def convert_korean_keys_to_english(collected_info: dict) -> dict:
    """한글 키를 영문 키로 변환"""
    converted_info = {}
    for korean_key, value in collected_info.items():
        english_key = KOREAN_TO_ENGLISH_KEY_MAPPING.get(korean_key, korean_key)
        converted_info[english_key] = value
    return converted_info

# Choice 필드의 값을 한글로 표시하기 위한 매핑
CHOICE_VALUE_DISPLAY_MAPPING = {
    # 보안매체
    "futuretech_19284019384": "퓨처테크 OTP",
    "comas_rsa_12930295": "코마스 RSA",
    "security_card": "보안카드",
    "shinhan_otp": "신한 OTP",
    
    # 체크카드 선택
    "sline_transit": "S-line 교통카드",
    "sline_regular": "S-line 일반카드",
    "deepdream_transit": "Deep Dream 교통카드",
    "deepdream_regular": "Deep Dream 일반카드",
    "heyyoung_regular": "Hey Young 일반카드",
    
    # 명세서 수령 방법
    "mobile": "모바일",
    "email": "이메일",
    "website": "홈페이지",
    
    # 카드 사용 알림
    "over_50000_free": "5만원 이상 결제시 발송 (무료)",
    "all_transactions_200won": "모든 내역 발송 (200원)",
    "no_alert": "문자 받지 않음",
    
    # Boolean 값
    True: "예",
    False: "아니오",
    "true": "예",
    "false": "아니오"
}

def format_korean_currency(amount: int) -> str:
    """숫자를 한국어 통화 단위로 변환 (만원/억원 단위)"""
    if amount >= 100000000:  # 1억 이상
        if amount % 100000000 == 0:
            return f"{amount // 100000000}억원"
        else:
            awk = amount // 100000000
            remainder = amount % 100000000
            if remainder % 10000 == 0:
                man = remainder // 10000
                return f"{awk}억{man}만원"
            else:
                return f"{amount:,}원"  # 복잡한 경우 기존 방식
    elif amount >= 10000:  # 1만원 이상
        if amount % 10000 == 0:
            return f"{amount // 10000}만원"
        else:
            man = amount // 10000
            remainder = amount % 10000
            return f"{man}만{remainder:,}원" if remainder > 0 else f"{man}만원"
    else:  # 1만원 미만
        return f"{amount:,}원"


def get_display_value(field_key: str, value: any) -> str:
    """필드 값을 한글 표시용으로 변환"""
    if value in CHOICE_VALUE_DISPLAY_MAPPING:
        return CHOICE_VALUE_DISPLAY_MAPPING[value]
    
    # 이체한도 필드 특별 처리
    if field_key in ["transfer_limit_once", "transfer_limit_daily"]:
        try:
            # 문자열이면 숫자로 변환
            if isinstance(value, str):
                numeric_value = int(value) if value.isdigit() else float(value)
            else:
                numeric_value = value
            return format_korean_currency(int(numeric_value))
        except (ValueError, TypeError):
            return str(value) if value is not None else ""
    
    # 특별한 필드 처리
    if field_key == "statement_delivery_date":
        # 날짜 형식 처리 (예: "3" -> "매월 3일")
        if isinstance(value, (str, int)) and value.isdigit() if isinstance(value, str) else True:
            return f"매월 {value}일"
    
    # 기본값은 그대로 반환
    return str(value) if value is not None else ""