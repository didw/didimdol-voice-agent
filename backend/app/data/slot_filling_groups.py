"""
Slot Filling 그룹 정의
"""

# 입출금통장 신규 시나리오의 그룹 정의
DEPOSIT_ACCOUNT_GROUPS = {
    "기본정보": {
        "id": "basic_info",
        "name": "기본정보",
        "stages": ["confirm_personal_info"],
        "fields": [
            "name",
            "english_name", 
            "ssn",
            "phone_number",
            "email",
            "address",
            "work_address"
        ]
    },
    "전자금융": {
        "id": "electronic_banking",
        "name": "전자금융",
        "stages": ["security_medium_registration", "additional_services"],
        "fields": [
            # security_medium_registration
            "security_medium",
            "transfer_limit_once",
            "transfer_limit_daily",
            # additional_services
            "important_transaction_alert",
            "withdrawal_alert",
            "overseas_ip_restriction"
        ]
    },
    "체크카드": {
        "id": "check_card",
        "name": "체크카드",
        "stages": [
            "card_selection",
            "statement_delivery",
            "card_usage_alert",
            "card_password_setting"
        ],
        "fields": [
            # card_selection
            "card_receipt_method",
            "card_selection",
            "transit_function",
            # statement_delivery
            "statement_delivery_method",
            "statement_delivery_date",
            # card_usage_alert
            "card_usage_alert",
            # card_password_setting
            "card_password_same_as_account"
        ]
    }
}

def get_groups_for_product(product_type: str):
    """상품 타입에 따른 그룹 정의 반환"""
    if product_type == "deposit_account":
        return list(DEPOSIT_ACCOUNT_GROUPS.values())
    # 다른 상품 타입 추가 가능
    return []

def get_group_for_stage(product_type: str, stage_id: str):
    """특정 스테이지가 속한 그룹 반환"""
    groups = get_groups_for_product(product_type)
    for group in groups:
        if stage_id in group.get("stages", []):
            return group
    return None

def get_group_id_for_stage(product_type: str, stage_id: str):
    """특정 스테이지가 속한 그룹 ID 반환"""
    group = get_group_for_stage(product_type, stage_id)
    return group["id"] if group else None

def get_groups_for_fields(product_type: str, field_keys: list):
    """특정 필드들이 속한 그룹들 반환"""
    groups = get_groups_for_product(product_type)
    relevant_groups = []
    
    for group in groups:
        group_fields = group.get("fields", [])
        if any(field in group_fields for field in field_keys):
            relevant_groups.append(group)
    
    return relevant_groups