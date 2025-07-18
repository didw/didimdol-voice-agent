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
    """인터넷뱅킹 필수 정보 완료 여부 확인"""
    print(f"[DEBUG] check_internet_banking_completion - collected_info keys: {list(collected_info.keys())}")
    print(f"[DEBUG] check_internet_banking_completion - collected_info: {collected_info}")
    
    # 인터넷뱅킹을 사용하지 않는 경우
    if not collected_info.get("use_internet_banking"):
        print(f"[DEBUG] check_internet_banking_completion - use_internet_banking is False or missing")
        return True, []
    
    # 인터넷뱅킹 관련 필드만 필터링
    ib_fields = []
    for field in required_fields:
        if field.get("parent_field") == "use_internet_banking" and field["required"]:
            ib_fields.append(field)
            print(f"[DEBUG] Found IB required field: {field['key']} ({field['display_name']})")
    
    missing_fields = []
    
    for field in ib_fields:
        key = field["key"]
        if key not in collected_info:
            missing_fields.append(field["display_name"])
            print(f"[DEBUG] check_internet_banking_completion - Missing field: {key} ({field['display_name']})")
        else:
            print(f"[DEBUG] check_internet_banking_completion - Found field: {key} = {collected_info[key]}")
    
    # 타행 OTP 선택 시 추가 필드 확인
    if collected_info.get("security_medium") == "타행 OTP":
        for field in required_fields:
            if field.get("parent_field") == "security_medium" and field["required"]:
                if field["key"] not in collected_info:
                    missing_fields.append(field["display_name"])
                    print(f"[DEBUG] Missing OTP field: {field['key']}")
    
    is_complete = len(missing_fields) == 0
    print(f"[DEBUG] check_internet_banking_completion - is_complete: {is_complete}, missing_fields: {missing_fields}")
    
    return is_complete, missing_fields


def generate_internet_banking_prompt(missing_fields: List[str]) -> str:
    """인터넷뱅킹 부족한 정보 요청 메시지 생성"""
    print(f"[DEBUG] generate_internet_banking_prompt - missing_fields: {missing_fields}")
    
    if not missing_fields:
        return ""
    
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
    
    prompt_parts = []
    
    if security_fields:
        prompt_parts.append(f"보안매체 정보({', '.join(security_fields)})")
    if limit_fields:
        prompt_parts.append(f"이체한도({', '.join(limit_fields)})")
    if alert_fields:
        prompt_parts.append(f"알림 설정({', '.join(alert_fields)})")
    if other_fields:
        prompt_parts.append(', '.join(other_fields))
    
    if len(prompt_parts) == 1:
        return f"인터넷뱅킹 설정을 위해 {prompt_parts[0]}를 알려주세요."
    else:
        return f"인터넷뱅킹 설정을 위해 다음 정보가 필요합니다:\\n\\n{chr(10).join(f'• {part}' for part in prompt_parts)}\\n\\n편하신 순서대로 말씀해 주세요."


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
    
    result = template
    
    # 수집된 정보로 변수 치환
    for key, value in collected_info.items():
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
    
    # 남은 플레이스홀더 처리
    # 조건부 필드 제거 (전체 줄 제거)
    lines = result.split('\n')
    filtered_lines = []
    for line in lines:
        if '%{' in line and '}%' in line:
            # 플레이스홀더가 있는 줄은 제외
            continue
        filtered_lines.append(line)
    
    result = '\n'.join(filtered_lines)
    
    # 빈 줄 정리
    result = re.sub(r'\n\s*\n\s*\n', '\n\n', result)
    
    return result