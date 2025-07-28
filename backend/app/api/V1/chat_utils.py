"""
채팅 관련 유틸리티 함수들
"""

import json
import re
from typing import Dict, Any, List, Optional
from datetime import datetime
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from ...graph.state import AgentState


# ===== 새로운 조건 평가 엔진 (심플 구조) =====

def normalize_bool_value(value):
    """다양한 타입의 값을 boolean으로 정규화"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        # True로 처리할 값들
        if value.lower() in ['true', '1', 'yes', 'y', '네', '예', '신청', '가입', '필요', '할게요']:
            return True
        # False로 처리할 값들
        elif value.lower() in ['false', '0', 'no', 'n', '아니요', '아니오', '미신청', '미가입', '안해요', '필요없어요']:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return False

def evaluate_show_when(show_when: str, collected_info: Dict[str, Any]) -> bool:
    """간단한 표현식으로 조건 평가
    
    지원하는 표현식:
    - field == value
    - field != null  
    - condition1 && condition2
    - condition1 || condition2
    """
    if not show_when or not show_when.strip():
        return True
    
    try:
        expression = show_when.strip()
        
        # && 및 || 연산자로 분리
        if '&&' in expression:
            conditions = [cond.strip() for cond in expression.split('&&')]
            return all(evaluate_single_condition(cond, collected_info) for cond in conditions)
        elif '||' in expression:
            conditions = [cond.strip() for cond in expression.split('||')]
            return any(evaluate_single_condition(cond, collected_info) for cond in conditions)
        else:
            return evaluate_single_condition(expression, collected_info)
    
    except Exception as e:
        print(f"Error evaluating show_when expression '{show_when}': {e}")
        return True  # 에러 시 기본적으로 표시


def evaluate_single_condition(condition: str, collected_info: Dict[str, Any]) -> bool:
    """단일 조건 평가"""
    condition = condition.strip()
    
    # field != null 패턴
    if ' != null' in condition:
        field_name = condition.replace(' != null', '').strip()
        value = collected_info.get(field_name)
        result = value is not None and value != '' and value != False
        return result
    
    # field == null 패턴  
    if ' == null' in condition:
        field_name = condition.replace(' == null', '').strip()
        value = collected_info.get(field_name)
        result = value is None or value == '' or value == False
        return result
    
    # field == value 패턴
    if ' == ' in condition:
        parts = condition.split(' == ', 1)
        if len(parts) == 2:
            field_name = parts[0].strip()
            expected_value = parts[1].strip().strip("'\"")
            current_value = collected_info.get(field_name)
            
            # boolean 값 처리 - 통합된 정규화 함수 사용
            if expected_value.lower() == 'true':
                result = normalize_bool_value(current_value) is True
            elif expected_value.lower() == 'false':
                result = normalize_bool_value(current_value) is False
            else:
                # 문자열 비교에서도 정규화된 비교 수행
                if isinstance(current_value, bool):
                    current_str = 'true' if current_value else 'false'
                else:
                    current_str = str(current_value) if current_value is not None else ''
                result = current_str == expected_value
            
            return result
    
    # field != value 패턴
    if ' != ' in condition:
        parts = condition.split(' != ', 1)
        if len(parts) == 2:
            field_name = parts[0].strip()
            expected_value = parts[1].strip().strip("'\"")
            current_value = collected_info.get(field_name)
            
            # boolean 값 처리 - 통합된 정규화 함수 사용
            if expected_value.lower() == 'true':
                result = normalize_bool_value(current_value) is not True
            elif expected_value.lower() == 'false':
                result = normalize_bool_value(current_value) is not False
            else:
                # 문자열 비교에서도 정규화된 비교 수행
                if isinstance(current_value, bool):
                    current_str = 'true' if current_value else 'false'
                else:
                    current_str = str(current_value) if current_value is not None else ''
                result = current_str != expected_value
            
            return result
    
    return True


def get_contextual_visible_fields(scenario_data: Dict, collected_info: Dict, current_stage: str) -> List[Dict]:
    """현재 대화 단계에 맞는 필드들만 점진적으로 표시"""
    if not scenario_data:
        return []
    
    required_fields = scenario_data.get("required_info_fields", [])
    visible_fields = []
    stages = scenario_data.get("stages", {})
    
    
    # 현재 단계에서 요구하는 필드 확인
    current_stage_info = stages.get(current_stage, {})
    expected_info_key = current_stage_info.get("expected_info_key")
    
    # 단계별 표시 정책 - 시나리오 데이터와 완전 일치
    stage_groups = {
        # 기본 정보 수집 단계
        "customer_info": ["customer_name", "phone_number", "address", "confirm_personal_info"],
        # 이체한도 설정 단계  
        "transfer_limit": ["transfer_limit_per_time", "transfer_limit_per_day"],
        # 알림설정 단계
        "notification": ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"],
        # 체크카드 관련 단계 (모든 하위 필드 포함)
        "check_card": ["use_check_card", "card_type", "card_receive_method", "card_delivery_location", 
                      "postpaid_transport", "card_usage_alert", "statement_method"],
        # 인터넷뱅킹 관련 단계 (모든 하위 필드 포함)
        "internet_banking": ["use_internet_banking", "security_medium", "initial_password", "other_otp_info",
                            "transfer_limit_per_time", "transfer_limit_per_day",
                            "important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
    }
    
    # 현재 단계에 따른 필드 그룹 결정
    allowed_fields = set()
    
    # 1. 단계별로 필요한 필드만 표시 (처음부터 모든 필드를 보여주지 않음)
    # limit_account_guide 단계에서는 아무것도 표시하지 않음
    if current_stage == "limit_account_guide":
        # 빈 리스트를 반환하여 아무것도 표시하지 않음
        return []
    elif current_stage == "limit_account_agreement":
        # 한도계좌 동의 단계
        allowed_fields.add("limit_account_agreement")
    elif current_stage == "customer_info_check":
        # 고객정보 확인 단계 - 모든 기본 개인정보 필드 표시 (confirm_personal_info 제외)
        allowed_fields.update([
            "limit_account_agreement", "customer_name", "english_name", "resident_number", 
            "phone_number", "email", "address", "work_address"
        ])
    
    # 기본 정보가 확인된 이후에는 기본 필드들 표시 (특정 단계가 아닌 경우)
    if (collected_info.get("confirm_personal_info") and 
        current_stage not in ["limit_account_guide", "limit_account_agreement", "customer_info_check"]):
        basic_fields = ["limit_account_agreement", "customer_name", "phone_number", "address", 
                       "confirm_personal_info"]
        allowed_fields.update(basic_fields)
    
    # 2. 현재 단계의 필드 추가
    if expected_info_key:
        allowed_fields.add(expected_info_key)
    
    # 평생계좌 사용 여부 단계
    if current_stage == "ask_lifelong_account":
        allowed_fields.add("use_lifelong_account")
        # 기본 정보도 함께 표시
        allowed_fields.update(["customer_name", "phone_number", "address"])
    
    # 2-1. 현재 단계가 인터넷뱅킹이나 체크카드면 해당 메인 필드도 추가
    
    if current_stage == "ask_internet_banking":
        # ask_internet_banking 단계에서는 use_internet_banking만 표시
        allowed_fields.add("use_internet_banking")
    elif current_stage == "internet_banking":
        allowed_fields.add("use_internet_banking")
    
    if current_stage == "ask_check_card":
        # ask_check_card 단계에서 체크카드 관련 필드들 모두 표시
        check_card_fields = ["use_check_card", "card_type", "card_receive_method", "card_delivery_location", 
                           "postpaid_transport", "card_usage_alert", "statement_method"]
        allowed_fields.update(check_card_fields)
    elif current_stage in ["check_card", "ask_check_card"]:
        allowed_fields.add("use_check_card")
    elif current_stage == "ask_notification_settings":
        # 알림 설정 단계에서 모든 알림 관련 필드 표시
        # 인터넷뱅킹 기본 필드도 포함
        notification_fields = ["use_internet_banking", "security_medium", "transfer_limit_per_time", 
                              "transfer_limit_per_day", "important_transaction_alert", 
                              "withdrawal_alert", "overseas_ip_restriction"]
        allowed_fields.update(notification_fields)
    
    # 3. 진행 상황에 따른 추가 필드 결정 (단계별 표시로 변경되어 대부분 불필요)
    # 특정 단계가 아닌 경우에만 점진적 공개 적용
    if current_stage not in ["limit_account_guide", "limit_account_agreement", "customer_info_check", 
                           "ask_lifelong_account", "ask_internet_banking", "ask_check_card", 
                           "ask_notification_settings"]:
        if collected_info.get("confirm_personal_info"):
            # 개인정보 확인 후 기본 필드 유지
            pass
    
    # 4. 출금계좌 등록 단계 처리
    if current_stage == "ask_withdrawal_account":
        allowed_fields.add("withdrawal_account_registration")
        # 기본 정보도 함께 표시 (이미 수집된 정보들)
        allowed_fields.update([
            "limit_account_agreement", "customer_name", "english_name", "resident_number", 
            "phone_number", "email", "address", "work_address", "confirm_personal_info"
        ])
    
    # 5. 추가 서비스 선택 후 하위 필드들 표시 (개인정보 단계와 동일한 방식)
    # 인터넷뱅킹 관련 모든 단계에서 필드 표시
    internet_banking_stages = ["ask_security_medium", "ask_other_otp_info", "ask_transfer_limit", 
                              "ask_notification_settings", "ask_internet_banking", "ask_withdrawal_account"]
    
    # use_internet_banking이 true이거나 인터넷뱅킹 관련 단계에서는 항상 모든 필드 표시
    # 또는 security_medium이 이미 수집되었으면 계속 표시
    if (current_stage in internet_banking_stages or 
        collected_info.get("use_internet_banking") == True or
        expected_info_key == "security_medium" or
        "security_medium" in collected_info):
        internet_banking_sub = ["use_internet_banking", "security_medium", "initial_password", "other_otp_info", 
                               "transfer_limit_per_time", "transfer_limit_per_day", 
                               "important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction", 
                               "withdrawal_account_registration"]
        allowed_fields.update(internet_banking_sub)
    
    # 체크카드 단계이거나 선택했을 때 모든 관련 하위 필드들을 표시
    # 체크카드 관련 모든 단계에서 하위 필드 표시
    check_card_stages = ["check_card", "ask_check_card", "ask_card_receive_method", "ask_card_delivery_location",
                        "ask_card_type", "ask_postpaid_transport", "ask_statement_method", "ask_card_usage_alert"]
    
    if current_stage in check_card_stages or collected_info.get("use_check_card") == True:
        # use_check_card 필드도 포함
        check_card_fields = ["use_check_card", "card_type", "card_receive_method", "card_delivery_location", 
                            "postpaid_transport", "card_usage_alert", "statement_method"]
        allowed_fields.update(check_card_fields)
        
    # final_summary 단계에서는 모든 그룹의 필드들을 표시 (시나리오 visible_groups 기준)
    if current_stage == "final_summary":
        # 시나리오에서 정의한 visible_groups 기준으로 모든 필드 허용
        stage_info = stages.get(current_stage, {})
        visible_groups = stage_info.get("visible_groups", [])
        field_groups = scenario_data.get("field_groups", [])
        
        for group in field_groups:
            if group.get("id") in visible_groups:
                group_fields = group.get("fields", [])
                allowed_fields.update(group_fields)
        
        
    # 5. 추가 조건부 필드들 (보험 등)
    # 여기에 더 많은 서비스별 하위 필드들을 추가할 수 있음
    
    # 이미 수집된 필드들도 항상 표시 (stage가 바뀌어도 유지)
    for field_key in collected_info:
        if field_key not in allowed_fields and collected_info[field_key] is not None:
            allowed_fields.add(field_key)
    
    
    # 조건 검사 및 계층 구조 적용
    for field in required_fields:
        field_key = field.get("key")
        
        # 1. 단계별 허용 필드 체크 (매우 관대한 정책 - 개인정보 단계와 동일)
        is_allowed = field_key in allowed_fields
        
        if not is_allowed:
            # show_when 조건이 있는 필드는 조건만 확인하면 표시 허용
            show_when = field.get("show_when")
            if show_when:
                # 조건부 필드는 조건 평가로 넘어감 (부모 필드 체크 생략)
                pass  # 조건 평가로 넘어감
            else:
                # 조건이 없는 필드만 제한
                continue
        else:
            pass
            
        show_when = field.get("show_when")
        
        
        # 2. show_when 조건 확인 (개인정보 단계와 동일 - 더 관대한 표시)
        if show_when and not is_allowed:  # allowed 필드는 조건 체크 없이 바로 표시
            is_visible = evaluate_show_when(show_when, collected_info)
            
            # 조건이 만족되지 않아도 부모 필드가 선택되었다면 미리 표시 (값은 "미입력"으로)
            parent_field = field.get("parent_field")
            if not is_visible and parent_field:
                parent_value = collected_info.get(parent_field)
                if parent_value == True:  # 부모가 선택되었다면 하위 필드들 미리 표시
                    # 미리 표시하되 조건 미충족 상태로 마킹
                    pass
                else:
                    continue
            elif not is_visible:
                continue
        
        # 3. 계층 정보 추가
        field_with_hierarchy = field.copy()
        field_with_hierarchy["depth"] = calculate_field_depth(field, required_fields)
        field_with_hierarchy["is_visible"] = True
        
        visible_fields.append(field_with_hierarchy)
    
    return visible_fields

def get_visible_fields_with_hierarchy(scenario_data: Dict, collected_info: Dict) -> List[Dict]:
    """계층적 구조로 표시 가능한 필드 반환 - 이전 버전 호환성 위해 유지"""
    # 기본 동작은 모든 필드 표시 (이전 동작과 동일)
    return get_contextual_visible_fields(scenario_data, collected_info, "")


def calculate_field_depth(field: Dict, all_fields: List[Dict]) -> int:
    """필드의 계층 깊이 계산"""
    parent_field = field.get("parent_field")
    if not parent_field:
        return 0
    
    # 부모 필드 찾기
    for parent in all_fields:
        if parent.get("key") == parent_field:
            return calculate_field_depth(parent, all_fields) + 1
    
    return 0


def apply_conditional_defaults(scenario_data: Dict, collected_info: Dict) -> Dict:
    """조건부 필드의 default 값을 동적으로 적용"""
    enhanced_info = collected_info.copy()
    
    if not scenario_data:
        return enhanced_info
    
    for field in scenario_data.get("required_info_fields", []):
        field_key = field["key"]
        
        # 이미 값이 있으면 skip
        if field_key in enhanced_info:
            continue
        
        # show_when 조건 확인
        show_when = field.get("show_when")
        if show_when:
            # 조건이 만족되어도 default 값 자동 설정 비활성화
            if evaluate_show_when(show_when, enhanced_info) and "default" in field:
                # enhanced_info[field_key] = field["default"]
                # print(f"Applied conditional default: {field_key} = {field['default']}")
                pass
        elif "default" in field:
            # 조건이 없는 필드의 default 값도 비활성화
            # enhanced_info[field_key] = field["default"]
            # print(f"Applied default: {field_key} = {field['default']}")
            pass
    
    return enhanced_info


def update_slot_filling_with_hierarchy(scenario_data: Dict, collected_info: Dict, current_stage: str) -> Dict:
    """실시간으로 계층적 슬롯 필링 상태 계산"""
    
    if not scenario_data:
        return {}
    
    # 현재 단계에 맞는 필드들만 가져오기 - 점진적 공개
    visible_fields = get_contextual_visible_fields(scenario_data, collected_info, current_stage)
    
    # Default 값 자동 추가 비활성화 - 고객 응답을 기다림
    # customer_info_check 단계 전에는 기본값을 수집하지 않음
    enhanced_collected_info = collected_info.copy()
    
    # customer_info_check 단계 이후에만 기본값 적용
    stages_allowing_defaults = ["customer_info_check", "info_correction", "ask_lifelong_account", 
                                "ask_internet_banking", "ask_security_medium", "ask_transfer_limit",
                                "ask_notification_settings", "ask_check_card"]
    
    # for field in visible_fields:
    #     field_key = field["key"]
    #     if (field_key not in enhanced_collected_info and 
    #         "default" in field and 
    #         field["default"] is not None and
    #         current_stage in stages_allowing_defaults):
    #         enhanced_collected_info[field_key] = field["default"]
    #         print(f"Auto-collected default value: {field_key} = {field['default']}")
    
    # 필드 그룹 정보
    field_groups = scenario_data.get("field_groups", [])
    
    # 완료 상태 계산 (모든 필드, 표시되지 않는 필드도 포함)
    all_fields = scenario_data.get("required_info_fields", [])
    
    # 🔥 Boolean 필드 문자열 변환 + 누락된 boolean 값 추론
    boolean_field_keys = [f["key"] for f in all_fields if f.get("type") == "boolean"]
    
    # 🚨 CRITICAL FIX: 누락된 boolean 필드 값 추론
    # use_check_card가 없는데 체크카드 관련 필드가 있으면 true로 추론
    if ("use_check_card" not in enhanced_collected_info and 
        any(key in enhanced_collected_info for key in ["card_receive_method", "card_type", "postpaid_transport", "statement_method", "card_usage_alert"])):
        enhanced_collected_info["use_check_card"] = True
    
    # use_internet_banking이 없는데 인터넷뱅킹 관련 필드가 있으면 true로 추론
    if ("use_internet_banking" not in enhanced_collected_info and 
        any(key in enhanced_collected_info for key in ["security_medium", "transfer_limit_per_time", "transfer_limit_per_day", "important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"])):
        enhanced_collected_info["use_internet_banking"] = True
    
    for field_key in boolean_field_keys:
        if field_key in enhanced_collected_info and isinstance(enhanced_collected_info[field_key], str):
            str_value = enhanced_collected_info[field_key].strip()
            
            if str_value in ["신청", "네", "예", "좋아요", "동의", "하겠습니다", "필요해요", "받을게요"]:
                enhanced_collected_info[field_key] = True
            elif str_value in ["미신청", "아니요", "아니", "싫어요", "거부", "안할게요", "필요없어요", "안받을게요"]:
                enhanced_collected_info[field_key] = False
            else:
                pass
        elif field_key in enhanced_collected_info:
            value = enhanced_collected_info[field_key]
    
    
    completion_status = {}
    
    def is_field_completed(field: Dict, collected_info: Dict) -> bool:
        """필드 완료 상태를 일관된 로직으로 판단"""
        field_key = field["key"]
        value = collected_info.get(field_key)
        
        # 값이 존재하지 않으면 미완료
        if value is None:
            return False
        
        field_type = field.get("type", "text")
        
        if field_type == "boolean":
            # Boolean 필드는 명시적인 boolean 값이거나 유효한 문자열 값이 있어야 완료
            if isinstance(value, bool):
                return True
            elif isinstance(value, str):
                # 한국어 boolean 문자열도 완료로 인식
                normalized_value = value.strip().lower()
                return normalized_value in ["신청", "미신청", "true", "false", "네", "아니요", "예", "아니", "좋아요", "싫어요", "동의", "거부"]
            return False
        elif field_type in ["text", "choice"]:
            # 텍스트/선택 필드는 비어있지 않은 문자열이어야 완료
            if isinstance(value, str):
                return value.strip() != ""
            return bool(value)
        elif field_type == "number":
            # 숫자 필드는 0이 아닌 숫자이거나 0이 유효한 값인 경우 완료
            if isinstance(value, (int, float)):
                return True  # 0도 유효한 값으로 간주
            if isinstance(value, str):
                try:
                    float(value)
                    return True
                except ValueError:
                    return False
        
        # 기타 타입: 값이 존재하고 False가 아니면 완료
        return value not in [None, "", False]
    
    for field in all_fields:
        field_key = field["key"]
        is_completed = is_field_completed(field, enhanced_collected_info)
        completion_status[field_key] = is_completed
        
    
    # 완료율 계산 - 실제로 표시되는 필드만 기준으로 계산
    # visible_fields 중 required=true인 필드만 계산
    
    # use_internet_banking, use_check_card 같은 boolean 필드는 제외 (선택 옵션이미로 필수 필드 아님)
    excluded_from_count = ["use_internet_banking", "use_check_card", "confirm_personal_info"]
    
    # 실제로 표시되는 필수 필드만 필터링
    countable_fields = [f for f in visible_fields 
                       if f.get("required", True) and f["key"] not in excluded_from_count]
    
    # 전체 필수 필드 개수
    total_required = len(countable_fields)
    
    # 완료된 필드 개수 계산
    completed_required = 0
    for field in countable_fields:
        field_key = field["key"]
        if completion_status.get(field_key, False):
            completed_required += 1
    
    # 완료율 계산
    completion_rate = (completed_required / total_required * 100) if total_required > 0 else 0
    
    
    # 조건부 필드 디버그
    if 'card_receive_method' in enhanced_collected_info:
        pass
    
    # 표시되는 필드 기준 완료율 (이미 위에서 계산됨)
    visible_total_required = total_required
    visible_completed_required = completed_required
    visible_completion_rate = completion_rate
    
    
    return {
        "visible_fields": visible_fields,
        "all_fields": all_fields,  # 전체 필드 목록 추가
        "completion_status": completion_status,
        "completion_rate": completion_rate,
        "visible_completion_rate": visible_completion_rate,  # 표시 필드 기준 완료율
        "total_required_count": total_required,  # 전체 필수 필드 개수
        "completed_required_count": completed_required,  # 완료된 필수 필드 개수
        "field_groups": field_groups,
        "current_stage": current_stage,
        "enhanced_collected_info": enhanced_collected_info  # 반환에 추가
    }


def should_send_slot_filling_update(
    info_changed: bool,
    scenario_changed: bool,
    product_type_changed: bool,
    stage_changed: bool,
    scenario_active: bool,
    is_info_collection_stage: bool
) -> bool:
    """슬롯 필링 업데이트를 전송해야 하는지 확인"""
    return (
        info_changed or 
        scenario_changed or 
        product_type_changed or
        stage_changed or
        (scenario_active and is_info_collection_stage)
    )


async def send_slot_filling_update(
    websocket: Any,
    state: AgentState,
    session_id: str
) -> None:
    """슬롯 필링 상태 업데이트를 WebSocket으로 전송"""
    
    
    # 시나리오 데이터 확인
    scenario_data = state.get("active_scenario_data")
    if not scenario_data:
        
        # deposit_account의 경우 기본 시나리오 데이터 생성
        if state.get("current_product_type") == "deposit_account":
            await _send_deposit_account_update(websocket, state, session_id)
        return
    
    try:
        # 필요한 정보 필드들 (시나리오 데이터 구조에 맞춤)
        required_fields = scenario_data.get("required_info_fields", [])
        if not required_fields:
            required_fields = scenario_data.get("slot_fields", [])
        field_groups = scenario_data.get("field_groups", [])
        collected_info = state.get("collected_product_info", {})
        current_stage = state.get("current_scenario_stage_id", "")
        
        # card_receive_method 변경 감지 및 로그
        if "card_receive_method" in collected_info:
            pass
        
        # 각 필드의 수집 상태 확인
        fields_status = []
        for field in required_fields:
            field_key = field.get("key", "")
            field_status = {
                "key": field_key,
                "display_name": field.get("display_name", field_key),
                "value": collected_info.get(field_key, ""),
                "is_collected": field_key in collected_info,
                "is_required": field.get("required", True)
            }
            fields_status.append(field_status)
        
        # 그룹별 진행률 계산
        groups_status = []
        for group in field_groups:
            group_fields = group.get("fields", [])
            collected_count = sum(1 for field in group_fields if field in collected_info)
            total_count = len(group_fields)
            
            groups_status.append({
                "id": group.get("id", ""),
                "name": group.get("name", ""),
                "progress": (collected_count / total_count * 100) if total_count > 0 else 0,
                "collected": collected_count,
                "total": total_count
            })
        
        # 전체 진행률
        total_required = len([f for f in required_fields if f.get("required", True)])
        total_collected = sum(1 for f in required_fields if f.get("key") in collected_info and f.get("required", True))
        overall_progress = (total_collected / total_required * 100) if total_required > 0 else 0
        
        # 현재 stage에서 표시할 그룹 정보 가져오기
        groups_info = get_stage_visible_groups(scenario_data, current_stage, collected_info)
        visible_groups = groups_info["visible_groups"]
        current_stage_groups = groups_info["current_stage_groups"]
        
        # 새로운 계층적 슬롯 필링 계산
        try:
            hierarchy_data = update_slot_filling_with_hierarchy(scenario_data, collected_info, current_stage)
            # enhanced_collected_info 사용
            if "enhanced_collected_info" in hierarchy_data:
                collected_info = hierarchy_data["enhanced_collected_info"]
            
            # 디버깅: card_delivery_location 필드 상태 확인
            visible_fields = hierarchy_data.get('visible_fields', [])
            card_delivery_field = next((f for f in visible_fields if f.get('key') == 'card_delivery_location'), None)
            if card_delivery_field:
                pass
            else:
                pass
        except Exception as e:
            hierarchy_data = {}
        
        # 계층 정보가 있는 필드들 준비
        enhanced_fields = []
        visible_fields = hierarchy_data.get("visible_fields", [])
        
        if visible_fields:
            # 계층 정보가 있는 경우 사용
            enhanced_fields = [{
                "key": f["key"],
                "displayName": f["display_name"],
                "type": f.get("type", "text"),
                "required": f.get("required", True),
                "choices": f.get("choices", []) if f.get("type") == "choice" else None,
                "unit": f.get("unit") if f.get("type") == "number" else None,
                "description": f.get("description", ""),
                "showWhen": f.get("show_when"),
                "parentField": f.get("parent_field"),
                "depth": f.get("depth", 0),
                "default": f.get("default")  # default 값 추가
            } for f in visible_fields]
        else:
            # fallback: 기존 방식
            enhanced_fields = [{
                "key": f["key"],
                "displayName": f["display_name"],
                "type": f.get("type", "text"),
                "required": f.get("required", True),
                "choices": f.get("choices", []) if f.get("type") == "choice" else None,
                "unit": f.get("unit") if f.get("type") == "number" else None,
                "description": f.get("description", ""),
                "showWhen": f.get("show_when"),
                "parentField": f.get("parent_field"),
                "depth": 0,  # 기본 depth
                "default": f.get("default")  # default 값 추가
            } for f in required_fields]
        
        # WebSocket 메시지 구성 (새로운 구조)
        slot_filling_data = {
            "type": "slot_filling_update",
            "productType": state.get("current_product_type", ""),
            "requiredFields": enhanced_fields,
            "collectedInfo": collected_info,
            "completionStatus": hierarchy_data.get("completion_status", {f["key"]: f["key"] in collected_info for f in required_fields}),
            "completionRate": hierarchy_data.get("completion_rate", overall_progress),
            "totalRequiredCount": hierarchy_data.get("total_required_count", total_required),  # 전체 필수 필드 수
            "completedRequiredCount": hierarchy_data.get("completed_required_count", total_collected),  # 완료된 필수 필드 수
            "fieldGroups": [{
                "id": group["id"],
                "name": group["name"],
                "fields": group["fields"]
            } for group in field_groups] if field_groups else [],
            "currentStage": {
                "stageId": current_stage,
                "visibleGroups": visible_groups,
                "currentStageGroups": current_stage_groups  # 현재 단계의 그룹만
            }
        }
        
        # 디버그 로그 추가
        
        
        try:
            await websocket.send_json(slot_filling_data)
            
            # 즉시 테스트 메시지 전송하여 WebSocket 연결 확인
            test_message = {
                "type": "test_websocket_connection",
                "message": "This is a test message to verify WebSocket is working",
                "timestamp": str(datetime.now()),
                "session_id": session_id
            }
            await websocket.send_json(test_message)
            
        except Exception as e:
            print(f"[{session_id}] ❌ WEBSOCKET SEND FAILED: {e}")
            print(f"[{session_id}] ❌ WebSocket state: {websocket.client_state if hasattr(websocket, 'client_state') else 'unknown'}")
            raise
        
        
        # 프론트엔드에서 수신 확인을 위한 디버그 메시지도 함께 전송
        debug_message = {
            "type": "debug_slot_filling",
            "timestamp": json.dumps({"timestamp": str(datetime.now())}),
            "data_hash": hash(json.dumps(slot_filling_data, sort_keys=True)),
            "summary": {
                "productType": slot_filling_data['productType'],
                "fieldsCount": len(slot_filling_data['requiredFields']),
                "collectedCount": len(slot_filling_data['collectedInfo']),
                "completionRate": slot_filling_data['completionRate']
            }
        }
        await websocket.send_json(debug_message)
        
    except Exception as e:
        print(f"[{session_id}] Error sending slot filling update: {e}")


def format_messages_for_display(messages: List[BaseMessage]) -> List[Dict[str, str]]:
    """메시지 리스트를 표시용 포맷으로 변환"""
    formatted = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            formatted.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            formatted.append({"role": "assistant", "content": msg.content})
        elif isinstance(msg, SystemMessage):
            formatted.append({"role": "system", "content": msg.content})
    return formatted


async def _send_deposit_account_update(
    websocket: Any,
    state: AgentState,
    session_id: str
) -> None:
    """입출금통장용 기본 슬롯 필링 업데이트"""
    try:
        collected_info = state.get("collected_product_info", {})
        current_stage = state.get("current_scenario_stage_id", "collect_basic")
        
        # 실제 시나리오 데이터에서 필드 가져오기
        scenario_data = state.get("active_scenario_data")
        
        if scenario_data and "required_info_fields" in scenario_data:
            default_fields = scenario_data["required_info_fields"]
        elif scenario_data and "slot_fields" in scenario_data:
            default_fields = scenario_data["slot_fields"]
        else:
            # 폴백 필드 정의
            default_fields = [
                {"key": "customer_name", "display_name": "성함", "required": True},
                {"key": "phone_number", "display_name": "연락처", "required": True},
                {"key": "use_lifelong_account", "display_name": "평생계좌 사용", "required": True},
                {"key": "ib_service_type", "display_name": "인터넷뱅킹 서비스", "required": False},
                {"key": "cc_type", "display_name": "체크카드 종류", "required": False}
            ]
        
        # 그룹 정의 (시나리오 데이터에서 가져오기)
        field_groups = scenario_data.get("field_groups", []) if scenario_data else []
        if not field_groups:
            # 폴백 그룹 정의
            field_groups = [
                {
                    "id": "basic_info",
                    "name": "기본 정보",
                    "fields": ["customer_name", "phone_number", "birth_date", "address"]
                },
                {
                    "id": "service_options", 
                    "name": "부가 서비스",
                    "fields": ["lifelong_account", "internet_banking", "check_card"]
                }
            ]
        
        # 그룹별 진행률 계산
        groups_status = []
        for group in field_groups:
            group_fields = group["fields"]
            collected_count = sum(1 for field in group_fields if field in collected_info)
            total_count = len(group_fields)
            
            groups_status.append({
                "id": group["id"],
                "name": group["name"],
                "progress": (collected_count / total_count * 100) if total_count > 0 else 0,
                "collected": collected_count,
                "total": total_count
            })
        
        # 전체 진행률 (필수 필드만)
        required_fields = [f for f in default_fields if f["required"]]
        total_required = len(required_fields)
        total_collected = sum(1 for f in required_fields if f["key"] in collected_info)
        overall_progress = (total_collected / total_required * 100) if total_required > 0 else 0
        
        # 필드 상태
        fields_status = []
        for field in default_fields:
            field_key = field["key"]
            fields_status.append({
                "key": field_key,
                "display_name": field["display_name"],
                "value": collected_info.get(field_key, ""),
                "is_collected": field_key in collected_info,
                "is_required": field["required"]
            })
        
        # 새로운 계층적 슬롯 필링 계산
        if scenario_data:
            hierarchy_data = update_slot_filling_with_hierarchy(scenario_data, collected_info, current_stage)
            # enhanced_collected_info 사용
            if "enhanced_collected_info" in hierarchy_data:
                collected_info = hierarchy_data["enhanced_collected_info"]
        else:
            hierarchy_data = {}
        
        # WebSocket 메시지 전송 (새로운 구조)
        slot_filling_data = {
            "type": "slot_filling_update",
            "productType": "deposit_account",
            "requiredFields": [{
                "key": f["key"],
                "displayName": f["display_name"],
                "type": f.get("type", "text"),
                "required": f["required"],
                "choices": f.get("choices", []) if f.get("type") == "choice" else None,
                "unit": f.get("unit") if f.get("type") == "number" else None,
                "description": f.get("description", ""),
                "showWhen": f.get("show_when"),
                "parentField": f.get("parent_field"),
                "depth": f.get("depth", 0)
            } for f in hierarchy_data.get("visible_fields", default_fields)],
            "collectedInfo": collected_info,
            "completionStatus": hierarchy_data.get("completion_status", {f["key"]: f["key"] in collected_info for f in default_fields}),
            "completionRate": hierarchy_data.get("completion_rate", overall_progress),
            "fieldGroups": [{
                "id": group["id"],
                "name": group["name"],
                "fields": group["fields"]
            } for group in field_groups] if field_groups else []
        }
        
        await websocket.send_json(slot_filling_data)
        print(f"[{session_id}] Deposit account slot filling update sent: {overall_progress:.1f}% complete")
        
    except Exception as e:
        print(f"[{session_id}] Error sending deposit account slot filling update: {e}")


def get_info_collection_stages() -> List[str]:
    """정보 수집 단계 목록 반환"""
    return [
        # 디딤돌 대출
        "ask_address_status", "ask_residence_type", "ask_acquisition_details",
        "ask_loan_details", "ask_marital_houseowner_status", 
        "ask_missing_info_group_personal", "ask_missing_info_group_property",
        "ask_missing_info_group_financial", "process_collected_info",
        
        # 전세자금 대출
        "ask_property_info", "ask_contract_info", "ask_tenant_info",
        "ask_existing_loans",
        
        # 입출금통장
        "greeting_deposit", "collect_customer_info",
        "clarify_services", "process_service_choices", 
        "collect_basic", "ask_internet_banking", "collect_ib_info",
        "ask_check_card", "collect_cc_info", "confirm_all"
    ]


def get_stage_visible_groups(scenario_data: Dict, stage_id: str, collected_info: Dict = None) -> Dict[str, List[str]]:
    """현재 stage에서 표시할 field_groups 반환 (현재 단계 그룹과 전체 표시 그룹 구분)"""
    
    if not scenario_data or not stage_id:
        return {"current_stage_groups": [], "visible_groups": []}
    
    # 시나리오 데이터에서 stage 정보 가져오기
    stages = scenario_data.get("stages", {})
    current_stage = stages.get(stage_id, {})
    
    # stage에 visible_groups가 정의되어 있으면 사용 (현재 단계 그룹)
    current_stage_groups = current_stage.get("visible_groups", [])
    
    # 전체 표시할 그룹 (현재 단계 + 이미 수집된 정보가 있는 그룹)
    visible_groups = current_stage_groups.copy()
    
    # 이미 수집된 정보가 있는 그룹도 추가
    if collected_info:
        field_groups = scenario_data.get("field_groups", [])
        for group in field_groups:
            # 그룹에 속한 필드 중 하나라도 수집되었으면 해당 그룹도 표시
            if any(field_key in collected_info and collected_info[field_key] not in [None, "", []] 
                   for field_key in group.get("fields", [])):
                if group["id"] not in visible_groups:
                    visible_groups.append(group["id"])
    
    return {
        "current_stage_groups": current_stage_groups,  # 현재 단계의 그룹만
        "visible_groups": visible_groups  # 표시할 모든 그룹
    }


def initialize_default_values(state: Dict[str, Any]) -> Dict[str, Any]:
    """시나리오 시작 시 default 값들을 collected_info에 설정 (조건부 필드 고려)"""
    from ...graph.utils import get_active_scenario_data
    
    scenario_data = get_active_scenario_data(state)
    collected_info = state.get("collected_product_info", {}).copy()
    
    if not scenario_data:
        return collected_info
    
    # 현재 단계 확인
    current_stage = state.get("current_scenario_stage_id", "")
    
    # customer_info_check 단계 이전에는 default 값을 설정하지 않음
    # (limit_account_guide 단계에서 정보가 노출되는 것을 방지)
    if current_stage in ["limit_account_guide", "limit_account_agreement", ""]:
        print(f"Skipping default value initialization for stage: {current_stage}")
        return collected_info
    
    # 기본정보(customer_name, phone_number, address)만 default 값 설정
    for field in scenario_data.get("required_info_fields", []):
        field_key = field["key"]
        
        # 기본정보 필드만 처리
        if field_key not in ["customer_name", "phone_number", "address"]:
            continue
        
        # 이미 값이 있으면 skip
        if field_key in collected_info:
            continue
            
        # default 값이 있으면 설정
        if "default" in field:
            collected_info[field_key] = field["default"]
            print(f"Initialized default value: {field_key} = {field['default']}")
    
    return collected_info