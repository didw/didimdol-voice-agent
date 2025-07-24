# backend/app/graph/nodes/workers/scenario_helpers.py
"""
시나리오 처리를 위한 헬퍼 함수들
정보 수집 및 그룹별 질문 생성 관련 유틸리티
"""
from typing import Dict, List, Any, Optional, cast
from ...state import AgentState


def check_required_info_completion(collected_info: Dict, required_fields: List[Dict]) -> tuple[bool, List[str]]:
    """필수 정보 수집 완료 여부 확인"""
    missing_fields = []
    
    for field in required_fields:
        # show_when 조건 확인
        if "show_when" in field:
            show_when = field["show_when"]
            # 간단한 조건 평가 (예: "use_internet_banking == true")
            if "==" in show_when:
                key, value = show_when.split(" == ")
                key = key.strip()
                value = value.strip().strip("'\"")
                
                # 부모 필드 값 확인
                parent_value = collected_info.get(key)
                if value == "true" and parent_value != True:
                    continue
                elif value == "false" and parent_value != False:
                    continue
                elif value != "true" and value != "false" and str(parent_value) != value:
                    continue
        
        # 필수 필드이고 수집되지 않은 경우
        if field["required"] and field["key"] not in collected_info:
            missing_fields.append(field["display_name"])
    
    is_complete = len(missing_fields) == 0
    return is_complete, missing_fields


def generate_missing_info_prompt(missing_fields: List[str], collected_info: Dict) -> str:
    """부족한 정보에 대한 자연스러운 요청 메시지 생성"""
    if len(missing_fields) == 1:
        return f"{missing_fields[0]}에 대해서 알려주시겠어요?"
    elif len(missing_fields) == 2:
        return f"{missing_fields[0]}과(와) {missing_fields[1]}에 대해서 알려주시겠어요?"
    else:
        field_list = ", ".join(missing_fields[:-1])
        return f"{field_list}, 그리고 {missing_fields[-1]}에 대해서 알려주시겠어요?"


def get_next_missing_info_group_stage(collected_info: Dict, required_fields: List[Dict]) -> str:
    """수집된 정보를 바탕으로 다음에 물어볼 그룹 스테이지 결정"""
    # 그룹별 정보 확인
    group1_fields = ["loan_purpose_confirmed", "marital_status"]
    group2_fields = ["has_home", "annual_income"] 
    group3_fields = ["target_home_price"]
    
    # 각 그룹에서 누락된 정보가 있는지 확인
    group1_missing = any(field not in collected_info for field in group1_fields)
    group2_missing = any(field not in collected_info for field in group2_fields)
    group3_missing = any(field not in collected_info for field in group3_fields)
    
    if group1_missing:
        return "ask_missing_info_group1"
    elif group2_missing:
        return "ask_missing_info_group2"
    elif group3_missing:
        return "ask_missing_info_group3"
    else:
        return "eligibility_assessment"


def check_internet_banking_completion(collected_info: Dict, required_fields: List[Dict]) -> tuple[bool, List[str]]:
    """인터넷뱅킹 필수 정보 완료 여부 확인 - 엄격한 검증"""
    print(f"[DEBUG] check_internet_banking_completion - collected_info keys: {list(collected_info.keys())}")
    print(f"[DEBUG] check_internet_banking_completion - collected_info: {collected_info}")
    
    # 인터넷뱅킹을 사용하지 않는 경우
    if not collected_info.get("use_internet_banking"):
        print(f"[DEBUG] check_internet_banking_completion - use_internet_banking is False or missing")
        return True, []
    
    # 인터넷뱅킹 필수 필드 목록 (하드코딩으로 명확히)
    required_ib_fields = [
        "security_medium",           # 보안매체
        "transfer_limit_per_time",   # 1회 이체한도
        "transfer_limit_per_day",    # 1일 이체한도
        "alert",                     # 알림 설정
        "additional_withdrawal_account"  # 출금계좌 추가
    ]
    
    missing_fields = []
    field_map = {}
    
    # 필드 맵 생성
    for field in required_fields:
        field_map[field["key"]] = field
    
    # 필수 필드 검증
    for field_key in required_ib_fields:
        if field_key not in collected_info:
            if field_key in field_map:
                missing_fields.append(field_map[field_key]["display_name"])
                print(f"[DEBUG] Missing required IB field: {field_key} ({field_map[field_key]['display_name']})")
        else:
            value = collected_info[field_key]
            print(f"[DEBUG] Found IB field: {field_key} = {value}")
            
            # 값 유효성 검증
            if field_key == "transfer_limit_per_time":
                if not isinstance(value, (int, float)) or value <= 0:
                    missing_fields.append("1회 이체한도 (유효한 금액)")
                    print(f"[DEBUG] Invalid transfer_limit_per_time: {value}")
                elif value > 5000:  # 1회 최대 5천만원
                    missing_fields.append("1회 이체한도 (최대 5천만원)")
                    print(f"[DEBUG] transfer_limit_per_time exceeds maximum: {value}")
                    
            elif field_key == "transfer_limit_per_day":
                if not isinstance(value, (int, float)) or value <= 0:
                    missing_fields.append("1일 이체한도 (유효한 금액)")
                    print(f"[DEBUG] Invalid transfer_limit_per_day: {value}")
                elif value > 10000:  # 1일 최대 1억원
                    missing_fields.append("1일 이체한도 (최대 1억원)")
                    print(f"[DEBUG] transfer_limit_per_day exceeds maximum: {value}")
                    
            elif field_key == "security_medium":
                valid_options = ["보안카드", "신한 OTP", "타행 OTP"]
                if value not in valid_options:
                    missing_fields.append(f"보안매체 (선택: {', '.join(valid_options)})")
                    print(f"[DEBUG] Invalid security_medium: {value}")
                    
            elif field_key == "alert":
                valid_alerts = ["중요거래통보", "출금내역통보", "해외IP이체 제한"]
                if value not in valid_alerts:
                    missing_fields.append(f"알림 설정 (선택: {', '.join(valid_alerts)})")
                    print(f"[DEBUG] Invalid alert: {value}")
    
    # 1회 한도와 1일 한도 논리적 검증
    per_time = collected_info.get("transfer_limit_per_time", 0)
    per_day = collected_info.get("transfer_limit_per_day", 0)
    if per_time > 0 and per_day > 0 and per_time > per_day:
        missing_fields.append("이체한도 재확인 (1회 한도가 1일 한도보다 클 수 없음)")
        print(f"[DEBUG] Logical error: per_time ({per_time}) > per_day ({per_day})")
    
    # 타행 OTP 선택 시 추가 필드 확인
    if collected_info.get("security_medium") == "타행 OTP":
        otp_fields = ["other_otp_manufacturer", "other_otp_serial"]
        for otp_field in otp_fields:
            if otp_field not in collected_info:
                if otp_field in field_map:
                    missing_fields.append(field_map[otp_field]["display_name"])
                    print(f"[DEBUG] Missing OTP field: {otp_field}")
    
    # 중복 제거
    missing_fields = list(dict.fromkeys(missing_fields))
    
    is_complete = len(missing_fields) == 0
    print(f"[DEBUG] check_internet_banking_completion - is_complete: {is_complete}, missing_fields: {missing_fields}")
    
    return is_complete, missing_fields


def generate_internet_banking_prompt(missing_fields: List[str]) -> str:
    """인터넷뱅킹 부족한 정보 요청 메시지 생성 - 개선된 안내"""
    print(f"[DEBUG] generate_internet_banking_prompt - missing_fields: {missing_fields}")
    
    if not missing_fields:
        return ""
    
    # 특정 필드에 대한 구체적인 안내 메시지
    specific_prompts = {
        "보안매체": "보안매체는 보안카드, 신한 OTP, 타행 OTP 중에서 선택해주세요",
        "1회 이체한도": "1회 이체한도는 최대 5천만원까지 설정 가능합니다",
        "1일 이체한도": "1일 이체한도는 최대 1억원까지 설정 가능합니다",
        "알림 설정": "알림 설정은 중요거래통보, 출금내역통보, 해외IP이체 제한 중에서 선택해주세요",
        "출금계좌 추가": "다른 출금계좌를 추가로 등록하시겠어요?",
        "이체한도 재확인": "1회 한도는 1일 한도보다 작거나 같아야 합니다. 다시 말씀해주세요"
    }
    
    # 카테고리별로 그룹화
    security_fields = []
    limit_fields = []
    alert_fields = []
    other_fields = []
    
    for field in missing_fields:
        if "보안매체" in field or "OTP" in field:
            security_fields.append(field)
        elif "한도" in field:
            limit_fields.append(field)
        elif "알림" in field or "통보" in field or "제한" in field:
            alert_fields.append(field)
        else:
            other_fields.append(field)
    
    # 구체적인 안내 메시지 생성
    detailed_prompts = []
    
    # 이체한도 관련
    if any("1회 이체한도" in f for f in limit_fields) and any("1일 이체한도" in f for f in limit_fields):
        detailed_prompts.append("• 이체한도: 1회 한도와 1일 한도를 각각 말씀해주세요 (예: 1회 500만원, 1일 2천만원)")
    elif any("1회 이체한도" in f for f in limit_fields):
        detailed_prompts.append("• 1회 이체한도: 한 번에 보낼 수 있는 최대 금액 (최대 5천만원)")
    elif any("1일 이체한도" in f for f in limit_fields):
        detailed_prompts.append("• 1일 이체한도: 하루 동안 보낼 수 있는 총 금액 (최대 1억원)")
    
    # 보안매체
    if security_fields:
        detailed_prompts.append("• 보안매체: 보안카드, 신한 OTP, 타행 OTP 중 선택")
    
    # 알림 설정
    if alert_fields:
        detailed_prompts.append("• 알림 설정: 중요거래통보, 출금내역통보, 해외IP이체 제한 중 선택")
    
    # 출금계좌 추가
    if any("출금계좌" in f for f in other_fields):
        detailed_prompts.append("• 출금계좌 추가 여부: 다른 계좌도 출금계좌로 등록하시겠어요? (예/아니요)")
    
    # 기타 필드
    for field in other_fields:
        if "출금계좌" not in field:
            detailed_prompts.append(f"• {field}")
    
    if len(detailed_prompts) == 1:
        return f"인터넷뱅킹 설정을 위해 {detailed_prompts[0][2:]}를 알려주세요."  # "• " 제거
    else:
        return f"인터넷뱅킹 설정을 위해 다음 정보가 필요합니다:\n\n{chr(10).join(detailed_prompts)}\n\n편하신 순서대로 말씀해 주세요."


def generate_group_specific_prompt(stage_id: str, collected_info: Dict) -> str:
    """그룹별로 이미 수집된 정보를 제외하고 맞춤형 질문 생성"""
    
    if stage_id == "ask_missing_info_group1":
        missing = []
        has_loan_purpose = collected_info.get("loan_purpose_confirmed", False)
        has_marital_status = "marital_status" in collected_info
        
        if not has_loan_purpose:
            missing.append("대출 목적(주택 구입용인지)")
        if not has_marital_status:
            missing.append("혼인 상태")
        
        if len(missing) == 2:
            return "몇 가지 더 확인해볼게요. 대출 목적과 혼인 상태는 어떻게 되시나요?"
        elif "대출 목적(주택 구입용인지)" in missing:
            return "대출 목적을 확인해볼게요. 주택 구입 목적이 맞으신가요?"
        elif "혼인 상태" in missing:
            return "혼인 상태는 어떻게 되시나요? (미혼/기혼/예비부부)"
        else:
            # Group1의 모든 정보가 수집된 경우 Group2로 넘어가야 함
            return "추가 정보를 알려주시겠어요?"
            
    elif stage_id == "ask_missing_info_group2":
        missing = []
        if "has_home" not in collected_info:
            missing.append("주택 소유 여부")
        if "annual_income" not in collected_info:
            missing.append("연소득")
            
        if len(missing) == 2:
            return "현재 주택 소유 여부와 연소득은 어느 정도 되시나요?"
        elif "주택 소유 여부" in missing:
            return "현재 소유하고 계신 주택이 있으신가요?"
        else:
            return "연소득은 어느 정도 되시나요? (세전 기준)"
            
    elif stage_id == "ask_missing_info_group3":
        return "구매 예정이신 주택 가격은 어느 정도로 생각하고 계신가요?"
    
    return "추가 정보를 알려주시겠어요?"


def check_check_card_completion(collected_info: Dict, required_fields: List[Dict]) -> tuple[bool, List[str]]:
    """체크카드 필수 정보 완료 여부 확인"""
    print(f"[DEBUG] check_check_card_completion - collected_info: {collected_info}")
    
    # 체크카드를 신청하지 않는 경우
    if not collected_info.get("use_check_card"):
        print(f"[DEBUG] check_check_card_completion - use_check_card is False or missing")
        return True, []
    
    # 체크카드 관련 필드만 필터링
    cc_fields = []
    for field in required_fields:
        if field.get("parent_field") == "use_check_card" and field["required"]:
            cc_fields.append(field)
            print(f"[DEBUG] Found check card required field: {field['key']} ({field['display_name']})")
    
    missing_fields = []
    
    for field in cc_fields:
        key = field["key"]
        if key not in collected_info:
            missing_fields.append(field["display_name"])
            print(f"[DEBUG] check_check_card_completion - Missing field: {key} ({field['display_name']})")
        else:
            print(f"[DEBUG] check_check_card_completion - Found field: {key} = {collected_info[key]}")
    
    # 배송 선택 시 추가 필드 확인
    if collected_info.get("card_receive_method") == "배송":
        print(f"[DEBUG] Card receive method is '배송', checking for delivery location field")
        for field in required_fields:
            if field.get("parent_field") == "card_receive_method" and field["required"]:
                if field["key"] not in collected_info:
                    missing_fields.append(field["display_name"])
                    print(f"[DEBUG] Missing delivery field: {field['key']} ({field['display_name']})")
                else:
                    print(f"[DEBUG] Found delivery field: {field['key']} = {collected_info[field['key']]}")
    else:
        print(f"[DEBUG] Card receive method is '{collected_info.get('card_receive_method')}', not '배송'")
    
    is_complete = len(missing_fields) == 0
    print(f"[DEBUG] check_check_card_completion - is_complete: {is_complete}, missing_fields: {missing_fields}")
    
    return is_complete, missing_fields


def generate_check_card_prompt(missing_fields: List[str]) -> str:
    """체크카드 부족한 정보 요청 메시지 생성"""
    print(f"[DEBUG] generate_check_card_prompt - missing_fields: {missing_fields}")
    
    if not missing_fields:
        return ""
    
    # 카테고리별로 그룹화
    card_basic_fields = []
    transport_fields = []
    payment_fields = []
    other_fields = []
    
    for field in missing_fields:
        if "카드 수령" in field or "배송" in field or "카드 종류" in field:
            card_basic_fields.append(field)
        elif "교통" in field:
            transport_fields.append(field)
        elif "결제일" in field or "명세서" in field or "비밀번호" in field or "알림" in field:
            payment_fields.append(field)
        else:
            other_fields.append(field)
    
    prompt_parts = []
    
    if card_basic_fields:
        prompt_parts.append(f"카드 정보({', '.join(card_basic_fields)})")
    if transport_fields:
        prompt_parts.append(f"교통기능({', '.join(transport_fields)})")
    if payment_fields:
        prompt_parts.append(f"결제/알림 설정({', '.join(payment_fields)})")
    if other_fields:
        prompt_parts.append(', '.join(other_fields))
    
    if len(prompt_parts) == 1:
        return f"체크카드 설정을 위해 {prompt_parts[0]}를 알려주세요."
    else:
        return f"체크카드 설정을 위해 다음 정보가 필요합니다:\\n\\n{chr(10).join(f'• {part}' for part in prompt_parts)}\\n\\n편하신 순서대로 말씀해 주세요."


def replace_template_variables(template: str, collected_info: Dict) -> str:
    """템플릿 문자열의 변수를 수집된 정보로 치환"""
    import re
    
    # 수집된 정보의 복사본 생성 (원본 수정 방지)
    info_copy = collected_info.copy()
    
    # 하위 정보가 있으면 상위 boolean 값을 추론
    # 체크카드 관련 정보가 있으면 use_check_card = True로 추론
    check_card_fields = ["card_type", "card_receive_method", "postpaid_transport", "card_usage_alert", "statement_method"]
    if any(field in info_copy for field in check_card_fields) and "use_check_card" not in info_copy:
        info_copy["use_check_card"] = True
        print(f"[DEBUG] Inferred use_check_card = True from existing card fields: {[f for f in check_card_fields if f in info_copy]}")
    
    # 인터넷뱅킹 관련 정보가 있으면 use_internet_banking = True로 추론
    ib_fields = ["security_medium", "transfer_limit_per_time", "transfer_limit_per_day", 
                 "important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
    if any(field in info_copy for field in ib_fields) and "use_internet_banking" not in info_copy:
        info_copy["use_internet_banking"] = True
        print(f"[DEBUG] Inferred use_internet_banking = True from existing IB fields: {[f for f in ib_fields if f in info_copy]}")
    
    result = template
    
    # 수집된 정보로 변수 치환
    for key, value in info_copy.items():
        placeholder = f"%{{{key}}}%"
        if placeholder in result:
            # boolean 값 한글로 변환
            if isinstance(value, bool):
                display_value = "예" if value else "아니요"
            # None 값 처리
            elif value is None:
                display_value = "미설정"
            else:
                display_value = str(value)
            result = result.replace(placeholder, display_value)
    
    # 특별한 경우 처리 - 체크카드 신청 안 함
    if collected_info.get("use_check_card") == False:
        # 체크카드 관련 항목들 제거
        check_card_fields = ["card_type", "card_receive_method", "postpaid_transport", "card_usage_alert"]
        for field in check_card_fields:
            placeholder = f"%{{{field}}}%"
            result = result.replace(placeholder, "해당없음")
    
    # 인터넷뱅킹 신청 안 함
    if collected_info.get("use_internet_banking") == False:
        # 인터넷뱅킹 관련 항목들 제거
        ib_fields = ["security_medium", "transfer_limit_per_time", "transfer_limit_per_day", "alert", "additional_withdrawal_account"]
        for field in ib_fields:
            placeholder = f"%{{{field}}}%"
            result = result.replace(placeholder, "해당없음")
    
    # 남은 플레이스홀더 처리 - 기본값으로 대체
    remaining_placeholders = re.findall(r'%\{([^}]+)\}%', result)
    for placeholder_key in remaining_placeholders:
        placeholder = f"%{{{placeholder_key}}}%"
        result = result.replace(placeholder, "미입력")
    
    # 빈 줄 정리
    result = re.sub(r'\n\s*\n\s*\n', '\n\n', result)
    
    return result