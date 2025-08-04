"""
스테이지 응답 생성 관련 함수들
"""
from typing import Dict, Any, List
from .scenario_utils import get_default_choice_display, format_korean_currency, format_field_value
from .response_generation import generate_final_confirmation_prompt
from .scenario_helpers import replace_template_variables


def generate_confirmation_summary(collected_info: Dict[str, Any]) -> str:
    """최종 확인용 요약 정보 생성"""
    summary_parts = []
    
    # 서비스 선택
    services = collected_info.get("services_selected")
    if services == "all":
        summary_parts.append("- 서비스: 입출금계좌 + 체크카드 + 모바일뱅킹")
    elif services == "mobile_only":
        summary_parts.append("- 서비스: 입출금계좌 + 모바일뱅킹")
    elif services == "card_only":
        summary_parts.append("- 서비스: 입출금계좌 + 체크카드")
    elif services == "account_only":
        summary_parts.append("- 서비스: 입출금계좌만")
    
    # 개인정보
    if collected_info.get("name"):
        summary_parts.append(f"- 고객명: {collected_info['name']}")
    if collected_info.get("phone_number"):
        summary_parts.append(f"- 연락처: {collected_info['phone_number']}")
    if collected_info.get("email"):
        summary_parts.append(f"- 이메일: {collected_info['email']}")
    
    # 보안매체 및 이체한도 (모바일 뱅킹)
    security_medium = collected_info.get("security_medium")
    if security_medium:
        if security_medium == "futuretech_19284019384":
            summary_parts.append("- 보안매체: 미래테크 19284019384")
        elif security_medium == "comas_rsa_12930295":
            summary_parts.append("- 보안매체: 코마스(RSA) 12930295")
        elif security_medium == "security_card":
            summary_parts.append("- 보안매체: 보안카드")
        elif security_medium == "shinhan_otp":
            summary_parts.append("- 보안매체: 신한OTP (10,000원)")
        else:
            summary_parts.append(f"- 보안매체: {security_medium}")
    
    # 이체한도
    transfer_once = collected_info.get("transfer_limit_once")
    transfer_daily = collected_info.get("transfer_limit_daily")
    if transfer_once and transfer_daily:
        # 금액 포맷팅 (50000000 -> 5,000만원)
        try:
            # 문자열일 수 있으므로 int로 변환
            once_amount = int(transfer_once) if isinstance(transfer_once, str) else transfer_once
            daily_amount = int(transfer_daily) if isinstance(transfer_daily, str) else transfer_daily
            once_formatted = format_korean_currency(once_amount)
            daily_formatted = format_korean_currency(daily_amount)
            summary_parts.append(f"- 이체한도: 1회 {once_formatted}, 1일 {daily_formatted}")
        except (ValueError, TypeError):
            # 변환 실패 시 원본 값 사용
            summary_parts.append(f"- 이체한도: 1회 {transfer_once}, 1일 {transfer_daily}")
    
    # 추가 서비스 (알림 및 제한)
    alerts = []
    if collected_info.get("important_transaction_alert"):
        alerts.append("중요거래 알림")
    if collected_info.get("withdrawal_alert"):
        alerts.append("출금 알림")
    if collected_info.get("overseas_ip_restriction"):
        alerts.append("해외 IP 제한")
    if alerts:
        summary_parts.append(f"- 추가 서비스: {', '.join(alerts)}")
    
    # 체크카드 정보
    card_selection = collected_info.get("card_selection")
    transit_function = collected_info.get("transit_function", False)
    
    if card_selection == "sline_transit":
        summary_parts.append("- 체크카드: S-Line 체크카드 (후불교통)")
    elif card_selection == "sline_regular":
        summary_parts.append("- 체크카드: S-Line 체크카드 (일반)")
    elif card_selection == "deepdream_transit":
        summary_parts.append("- 체크카드: 신한 Deep Dream 체크카드 (후불교통)")
    elif card_selection == "deepdream_regular":
        summary_parts.append("- 체크카드: 신한 Deep Dream 체크카드 (일반)")
    elif card_selection == "heyyoung_regular":
        summary_parts.append("- 체크카드: Hey Young 체크카드")
    elif card_selection:
        # 매핑되지 않은 값들에 대한 폴백 (자연어 표현 처리)
        # "배송되는 카드" 같은 경우 transit_function을 확인
        if "배송" in card_selection and "카드" in card_selection:
            # 배송되는 카드 중 기본 선택 또는 transit_function에 따라 결정
            if transit_function:
                summary_parts.append("- 체크카드: 신한 Deep Dream 체크카드 (후불교통)")
            else:
                summary_parts.append("- 체크카드: 신한 Deep Dream 체크카드 (일반)")
        elif "헤이영" in card_selection or "hey young" in card_selection.lower():
            summary_parts.append("- 체크카드: Hey Young 체크카드")
        elif "딥드림" in card_selection or "deep dream" in card_selection.lower():
            if "후불교통" in card_selection or "교통" in card_selection or transit_function:
                summary_parts.append("- 체크카드: 신한 Deep Dream 체크카드 (후불교통)")
            else:
                summary_parts.append("- 체크카드: 신한 Deep Dream 체크카드 (일반)")
        elif "s-line" in card_selection.lower() or "에스라인" in card_selection:
            if "후불교통" in card_selection or "교통" in card_selection or transit_function:
                summary_parts.append("- 체크카드: S-Line 체크카드 (후불교통)")
            else:
                summary_parts.append("- 체크카드: S-Line 체크카드 (일반)")
        else:
            # 기타 알 수 없는 값
            if transit_function:
                summary_parts.append(f"- 체크카드: {card_selection} (후불교통)")
            else:
                summary_parts.append(f"- 체크카드: {card_selection}")
    
    # 카드 수령 방법
    card_receipt_method = collected_info.get("card_receipt_method")
    if card_receipt_method == "즉시발급":
        summary_parts.append("- 카드 수령: 즉시발급")
    elif card_receipt_method == "배송":
        summary_parts.append("- 카드 수령: 배송")
    
    # 명세서 수령 정보
    delivery_method = collected_info.get("statement_delivery_method")
    delivery_date = collected_info.get("statement_delivery_date")
    if delivery_method and delivery_date:
        method_text = "이메일" if delivery_method == "email" else "휴대폰" if delivery_method == "mobile" else "홈페이지"
        summary_parts.append(f"- 명세서: 매월 {delivery_date}일 {method_text} 수령")
    
    # 카드 사용 알림
    card_alert = collected_info.get("card_usage_alert")
    if card_alert == "over_50000_free":
        summary_parts.append("- 카드 사용 알림: 5만원 이상 결제 시 발송 (무료)")
    elif card_alert == "over_30000_free":
        summary_parts.append("- 카드 사용 알림: 3만원 이상 결제 시 발송 (무료)")
    elif card_alert == "all_transactions_200won":
        summary_parts.append("- 카드 사용 알림: 모든 내역 발송 (200원, 포인트 우선 차감)")
    elif card_alert == "no_alert":
        summary_parts.append("- 카드 사용 알림: 문자 받지 않음")
    
    # 카드 비밀번호
    same_password = collected_info.get("card_password_same_as_account")
    if same_password:
        summary_parts.append("- 카드 비밀번호: 계좌 비밀번호와 동일")
    elif same_password is False:
        summary_parts.append("- 카드 비밀번호: 별도 설정")
    
    return "\n".join(summary_parts) if summary_parts else "신청하신 서비스 정보"


def generate_stage_response(stage_info: Dict[str, Any], collected_info: Dict[str, Any], scenario_data: Dict = None) -> Dict[str, Any]:
    """단계별 응답 유형에 맞는 데이터 생성"""
    response_type = stage_info.get("response_type", "narrative")
    stage_id = stage_info.get("stage_id", "unknown")
    
    
    # final_confirmation 단계의 동적 프롬프트 생성
    if stage_id == "final_confirmation":
        summary = generate_confirmation_summary(collected_info)
        prompt = f"지금까지 신청하신 내용을 확인해드리겠습니다.\n\n{summary}\n\n위 내용이 맞으신가요? 수정하실 부분이 있으면 말씀해주세요."
        print(f"🎯 [FINAL_CONFIRMATION] Generated dynamic prompt with summary: {prompt[:100]}...")
    # dynamic_prompt 처리 우선 (V3 시나리오)
    elif stage_info.get("dynamic_prompt"):
        prompt = stage_info["dynamic_prompt"]
        
        # {default_choice} 치환
        if "{default_choice}" in prompt:
            default_choice = get_default_choice_display(stage_info)
            prompt = prompt.replace("{default_choice}", default_choice)
            print(f"🎯 [DYNAMIC_PROMPT] Used dynamic_prompt with default_choice: '{default_choice}'")
        
        # {summary} 치환 (final_confirmation 단계용)
        if "{summary}" in prompt:
            summary = generate_confirmation_summary(collected_info)
            prompt = prompt.replace("{summary}", summary)
            print(f"🎯 [DYNAMIC_PROMPT] Generated summary for final_confirmation")
    else:
        prompt = stage_info.get("prompt", "")
    
    
    
    # display_fields가 있는 경우 처리 (bullet 타입)
    if stage_info.get("display_fields"):
        # V3 시나리오: display_fields가 dict인 경우 (실제 값이 포함됨)
        if isinstance(stage_info["display_fields"], dict):
            # V3 시나리오의 display_fields는 이미 포맷된 데이터이므로 바로 사용
            display_values = stage_info["display_fields"]
            field_display = []
            for field_name, value in display_values.items():
                field_display.append(f"- {field_name}: {value}")
            
            # 프롬프트에 개인정보 추가
            if field_display:
                prompt = prompt + "\n\n" + "\n".join(field_display)
                print(f"🎯 [V3_DISPLAY_FIELDS] Added {len(field_display)} fields to prompt")
        else:
            # 기존 방식: display_fields가 list인 경우
            prompt = format_prompt_with_fields(prompt, collected_info, stage_info["display_fields"], scenario_data)
    
    # 템플릿 변수 치환
    prompt = replace_template_variables(prompt, collected_info)
    
    response_data = {
        "stage_id": stage_info.get("stage_id"),
        "stageId": stage_info.get("stage_id"),  # camelCase for frontend compatibility
        "response_type": response_type,
        "responseType": response_type,  # camelCase for frontend compatibility  
        "prompt": prompt,
        "skippable": stage_info.get("skippable", False)
    }
    
    # additional_questions가 있는 경우 추가
    if stage_info.get("additional_questions"):
        questions = stage_info.get("additional_questions", [])
        response_data["additional_questions"] = questions
        response_data["additionalQuestions"] = questions  # camelCase for frontend compatibility
    
    # 선택지가 있는 경우
    if response_type in ["bullet", "boolean"]:
        response_data["choices"] = stage_info.get("choices", [])
        # choice_groups가 있는 경우 추가 (frontend 형식으로 변환)
        if stage_info.get("choice_groups"):
            print(f"🎯 [CHOICE_GROUPS] Found choice_groups in stage_info: {stage_info.get('choice_groups')}")
            choice_groups = []
            for group in stage_info.get("choice_groups", []):
                # choices도 frontend 형식으로 변환
                transformed_choices = []
                for choice in group.get("choices", []):
                    transformed_choice = {
                        "value": choice.get("value", ""),
                        "label": choice.get("display", choice.get("label", "")),
                        "display": choice.get("display", choice.get("label", "")),
                        "default": choice.get("default", False)
                    }
                    # metadata가 있으면 포함
                    if choice.get("metadata"):
                        transformed_choice["metadata"] = choice.get("metadata")
                    transformed_choices.append(transformed_choice)
                    print(f"🎯 [CHOICE_GROUPS] Transformed choice: {transformed_choice}")
                
                transformed_group = {
                    "title": group.get("group_name", ""),
                    "items": transformed_choices
                }
                choice_groups.append(transformed_group)
                print(f"🎯 [CHOICE_GROUPS] Transformed group: {transformed_group}")
            
            response_data["choice_groups"] = choice_groups
            response_data["choiceGroups"] = choice_groups  # camelCase for frontend compatibility
            
            # choice_groups에서 default choice 찾아서 top-level에 설정
            default_choice_value = None
            for group in choice_groups:
                for item in group.get("items", []):
                    if item.get("default"):
                        default_choice_value = item.get("value")
                        break
                if default_choice_value:
                    break
            
            if default_choice_value:
                response_data["default_choice"] = default_choice_value
                response_data["defaultChoice"] = default_choice_value  # camelCase for frontend compatibility
                print(f"🎯 [CHOICE_GROUPS] Set default choice from choice_groups: {default_choice_value}")
            
            print(f"🎯 [CHOICE_GROUPS] Final choice_groups in response_data: {response_data['choice_groups']}")
            print(f"🎯 [CHOICE_GROUPS] Added choiceGroups (camelCase) for frontend compatibility")
            print(f"🎯 [CHOICE_GROUPS] Transformed {len(choice_groups)} groups with {sum(len(g['items']) for g in choice_groups)} total choices for frontend")
        # choices에서 default choice 찾기 (choice_groups가 없는 경우)
        if not stage_info.get("choice_groups") and stage_info.get("choices"):
            default_choice_value = None
            for choice in stage_info.get("choices", []):
                if isinstance(choice, dict) and choice.get("default"):
                    default_choice_value = choice.get("value")
                    break
            
            if default_choice_value:
                response_data["default_choice"] = default_choice_value
                response_data["defaultChoice"] = default_choice_value  # camelCase for frontend compatibility  
                print(f"🎯 [CHOICES] Set default choice from choices: {default_choice_value}")
        
        # default_choice가 있는 경우 추가
        if stage_info.get("default_choice"):
            response_data["default_choice"] = stage_info.get("default_choice")
            response_data["defaultChoice"] = stage_info.get("default_choice")  # camelCase for frontend compatibility
        
    
    # 수정 가능한 필드 정보
    if stage_info.get("modifiable_fields"):
        response_data["modifiable_fields"] = stage_info["modifiable_fields"]
        response_data["modifiableFields"] = stage_info["modifiable_fields"]  # camelCase for frontend compatibility
    
    # display_fields 정보 추가 (V3 시나리오)
    if stage_info.get("display_fields"):
        if isinstance(stage_info["display_fields"], dict):
            # V3: display_fields가 실제 값을 포함하는 경우
            display_values = stage_info["display_fields"]
            merged_values = {**display_values, **collected_info}  # collected_info가 우선
            response_data["display_fields"] = merged_values
        else:
            # 기존: display_fields가 필드명 리스트인 경우
            response_data["display_fields"] = stage_info["display_fields"]
    
    return response_data


def format_prompt_with_fields(prompt: str, collected_info: Dict[str, Any], display_fields: List[str], scenario_data: Dict = None) -> str:
    """프롬프트에 수집된 정보 동적 삽입 (기본값 포함)"""
    field_display = []
    
    field_names = {
        "customer_name": "이름",
        "english_name": "영문이름", 
        "resident_number": "주민등록번호",
        "phone_number": "휴대폰번호", 
        "customer_phone": "휴대폰번호",
        "email": "이메일",
        "address": "집주소",
        "work_address": "직장주소"
    }
    
    # 기본값 매핑
    default_values = {
        "customer_name": "홍길동",
        "phone_number": "010-1234-5678", 
        "address": "서울특별시 종로구 숭인동 123"
    }
    
    # 시나리오 데이터에서 기본값 가져오기
    if scenario_data:
        for field in scenario_data.get("required_info_fields", []):
            if field.get("key") in display_fields and field.get("default"):
                default_values[field["key"]] = field["default"]
    
    # 프롬프트에 이미 필드 정보가 포함되어 있는지 확인
    # "- 성함:" 같은 패턴이 이미 있으면 중복 추가하지 않음
    prompt_has_fields = False
    for field_key in display_fields:
        field_name = field_names.get(field_key, field_key)
        if f"- {field_name}:" in prompt:
            prompt_has_fields = True
            break
    
    # 프롬프트에 필드 정보가 없을 때만 추가
    if not prompt_has_fields:
        for field_key in display_fields:
            # 수집된 정보가 있으면 사용, 없으면 기본값 사용
            value = collected_info.get(field_key)
            if not value and field_key in default_values:
                value = default_values[field_key]
            if not value:
                value = "미입력"
                
            field_name = field_names.get(field_key, field_key)
            field_display.append(f"- {field_name}: {value}")
        
        if field_display:
            prompt += "\n" + "\n".join(field_display)
    
    return prompt