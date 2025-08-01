"""
필드 추출 및 처리 관련 함수들
"""
import json
import re
from typing import Dict, Any, Optional, List, Tuple
from langchain_core.messages import HumanMessage
from ...chains import json_llm
from ...validators import get_validator_for_field


async def process_partial_response(
    stage_id: str,
    user_input: str,
    required_fields: List[Dict[str, Any]],
    collected_info: Dict[str, Any],
    field_validators: Dict[str, Any] = None
) -> Dict[str, Any]:
    """부분 응답 처리 및 유효성 검증"""
    
    if field_validators is None:
        from ...validators import FIELD_VALIDATORS
        field_validators = FIELD_VALIDATORS
    
    # 1. Entity Agent를 통한 개별 필드 추출
    extracted_entities = {}
    if user_input:
        try:
            from ....agents.entity_agent import entity_agent
            extraction_result = await entity_agent.extract_entities(user_input, required_fields)
            extracted_entities = extraction_result.get("extracted_entities", {})
        except Exception as e:
            print(f"[ERROR] Entity extraction error in partial response: {e}")
    
    # 2. 유효성 검증
    validation_results = {}
    for field in required_fields:
        field_key = field['key']
        value = extracted_entities.get(field_key) or collected_info.get(field_key)
        
        if value is not None:
            validator = get_validator_for_field(field_key, field_validators)
            is_valid = True
            error_msg = ""
            
            if validator:
                try:
                    validator(value)
                except ValueError as e:
                    is_valid = False
                    error_msg = str(e)
            
            validation_results[field_key] = {
                "value": value,
                "is_valid": is_valid,
                "error": error_msg
            }
    
    # 3. 유효한 필드만 collected_info에 업데이트
    valid_fields = []
    invalid_fields = []
    
    for field_key, result in validation_results.items():
        if result["is_valid"]:
            collected_info[field_key] = result["value"]
            valid_fields.append(field_key)
        else:
            invalid_fields.append({
                "field": field_key,
                "error": result["error"],
                "value": result["value"]
            })
    
    # 4. 미수집 필드 확인
    missing_fields = [
        field for field in required_fields 
        if field['key'] not in collected_info
    ]
    
    # 5. 재질문 생성
    response_text = None
    if invalid_fields or missing_fields:
        from .response_generation import generate_re_prompt
        response_text = generate_re_prompt(
            valid_fields, 
            invalid_fields, 
            missing_fields,
            required_fields
        )
    
    return {
        "collected_info": collected_info,
        "valid_fields": valid_fields,
        "invalid_fields": invalid_fields,
        "missing_fields": missing_fields,
        "response_text": response_text,
        "is_complete": not (invalid_fields or missing_fields)
    }


async def extract_field_value_with_llm(
    user_input: str,
    field_key: str,
    field_info: Dict[str, Any],
    collected_info: Dict[str, Any],
    current_stage: str
) -> Optional[Any]:
    """LLM을 사용하여 특정 필드 값 추출"""
    
    field_type = field_info.get("type", "text")
    field_name = field_info.get("display_name", field_key)
    
    # 필드 타입별 프롬프트 구성
    type_instructions = {
        "number": "숫자로 추출하세요. 예: 1000000",
        "boolean": "true 또는 false로 추출하세요.",
        "choice": f"다음 중 하나를 선택하세요: {field_info.get('choices', [])}",
        "text": "텍스트로 추출하세요."
    }
    
    prompt = f"""사용자의 입력에서 {field_name} 정보를 추출하세요.

사용자 입력: "{user_input}"
현재 대화 맥락: {current_stage} 단계에서 {field_name} 정보 수집 중

추출 규칙:
1. {type_instructions.get(field_type, '값을 추출하세요.')}
2. 명확하게 추출할 수 없으면 null을 반환하세요.
3. 사용자가 부정하거나 거부하는 경우도 null을 반환하세요.

{f"선택 가능한 값: {field_info.get('choices', [])}" if field_type == 'choice' else ""}

JSON 응답 형식:
{{
    "extracted_value": 추출된 값 또는 null,
    "confidence": 0.0-1.0,
    "reasoning": "추출 이유"
}}"""

    try:
        response = await json_llm.ainvoke([HumanMessage(content=prompt)])
        result = json.loads(response.content.strip())
        
        if result.get("extracted_value") is not None and result.get("confidence", 0) > 0.6:
            print(f"✅ [LLM_FIELD_EXTRACT] Extracted {field_key}: {result['extracted_value']}")
            return result["extracted_value"]
            
    except Exception as e:
        print(f"❌ [LLM_FIELD_EXTRACT] Error extracting {field_key}: {e}")
    
    return None


async def extract_any_field_value_with_llm(
    user_input: str,
    stage_fields: List[Dict[str, Any]],
    collected_info: Dict[str, Any],
    current_stage: str
) -> Dict[str, Any]:
    """여러 필드 중 어떤 것이든 추출 시도"""
    
    # 필드 정보 준비
    fields_info = []
    for field in stage_fields:
        field_desc = {
            "key": field["key"],
            "name": field.get("display_name", field["key"]),
            "type": field.get("type", "text"),
            "description": field.get("description", "")
        }
        if field.get("type") == "choice":
            field_desc["choices"] = field.get("choices", [])
        fields_info.append(field_desc)
    
    prompt = f"""사용자의 입력에서 다음 필드들 중 해당하는 정보를 모두 추출하세요.

사용자 입력: "{user_input}"
현재 단계: {current_stage}

추출 가능한 필드들:
{json.dumps(fields_info, ensure_ascii=False, indent=2)}

추출 규칙:
1. 각 필드의 타입에 맞게 추출하세요.
2. 명확하게 추출할 수 없는 필드는 포함하지 마세요.
3. 여러 필드를 동시에 추출할 수 있습니다.
4. 한국어 표현을 적절히 해석하세요 (예: "둘 다" → both, "안 해" → false)

JSON 응답 형식:
{{
    "extracted_fields": {{
        "필드key": 추출된 값,
        ...
    }},
    "confidence": 0.0-1.0,
    "reasoning": "추출 이유"
}}"""

    try:
        response = await json_llm.ainvoke([HumanMessage(content=prompt)])
        result = json.loads(response.content.strip())
        
        extracted = result.get("extracted_fields", {})
        if extracted and result.get("confidence", 0) > 0.5:
            print(f"✅ [LLM_MULTI_EXTRACT] Extracted fields: {list(extracted.keys())}")
            return extracted
            
    except Exception as e:
        print(f"❌ [LLM_MULTI_EXTRACT] Error: {e}")
    
    return {}


def detect_newly_extracted_values(
    previous_collected: Dict[str, Any],
    current_collected: Dict[str, Any],
    extraction_result: Dict[str, Any]
) -> Dict[str, Any]:
    """새로 추출된 값들을 감지"""
    
    newly_extracted = {}
    
    # extraction_result의 extracted_entities 우선 확인
    if extraction_result and extraction_result.get('extracted_entities'):
        for field, value in extraction_result['extracted_entities'].items():
            if field not in previous_collected and field in current_collected:
                newly_extracted[field] = value
    
    # current_collected에서 새로 추가된 필드 확인
    for field, value in current_collected.items():
        if field not in previous_collected and field not in newly_extracted:
            newly_extracted[field] = value
    
    return newly_extracted


def _handle_field_name_mapping(collected_info: Dict[str, Any]) -> None:
    """필드명 매핑 처리 - 다양한 형태의 필드명을 표준화된 형태로 변환"""
    
    # "not specified" 객체 내의 값들을 상위 레벨로 이동
    if "not specified" in collected_info and isinstance(collected_info["not specified"], dict):
        not_specified_data = collected_info.pop("not specified")
        collected_info.update(not_specified_data)
    
    # 필드명 매핑 정의
    field_mappings = {
        # 고객 정보
        "customer_phone": "phone_number",
        "phone": "phone_number",
        "연락처": "phone_number",
        "전화번호": "phone_number",
        "핸드폰": "phone_number",
        "name": "customer_name",
        "고객명": "customer_name",
        "성함": "customer_name",
        "이름": "customer_name",
        
        # 인터넷뱅킹 관련
        "security_method": "security_medium",
        "보안매체": "security_medium",
        "보안방법": "security_medium",
        "ib_security_method": "security_medium",
        "transfer_daily_limit": "transfer_limit_per_day",
        "daily_transfer_limit": "transfer_limit_per_day",
        "일일이체한도": "transfer_limit_per_day",
        "per_transfer_limit": "transfer_limit_per_time",
        "건별이체한도": "transfer_limit_per_time",
        "이체한도": "transfer_limit_per_day",
        
        # 체크카드 관련
        "card_type": "card_selection",
        "카드종류": "card_selection",
        "check_card_type": "card_selection",
        "cc_type": "card_selection",
        "alert_method": "card_usage_alert",
        "알림방법": "card_usage_alert",
        "사용알림": "card_usage_alert",
        
        # 서비스 선택
        "services": "additional_services",
        "부가서비스": "additional_services",
        "추가서비스": "additional_services",
        
        # 배송 관련
        "delivery_method": "statement_delivery",
        "명세서수령": "statement_delivery",
        "거래명세서": "statement_delivery"
    }
    
    # 필드명 변환
    keys_to_update = []
    for old_key, new_key in field_mappings.items():
        if old_key in collected_info and new_key not in collected_info:
            keys_to_update.append((old_key, new_key))
    
    for old_key, new_key in keys_to_update:
        collected_info[new_key] = collected_info.pop(old_key)
        print(f"🔄 Mapped field: {old_key} → {new_key}")
    
    # 특수 케이스 처리
    # 1. 이체한도 관련
    if "transfer_limits" in collected_info and isinstance(collected_info["transfer_limits"], dict):
        limits = collected_info["transfer_limits"]
        if "per_time" in limits and "transfer_limit_per_time" not in collected_info:
            collected_info["transfer_limit_per_time"] = limits["per_time"]
        if "per_day" in limits and "transfer_limit_per_day" not in collected_info:
            collected_info["transfer_limit_per_day"] = limits["per_day"]
        collected_info.pop("transfer_limits", None)
    
    # 2. 한국어 boolean 값 변환
    boolean_fields = [
        "important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction",
        "limit_account_agreement", "confirm_personal_info", "use_lifelong_account", 
        "use_internet_banking", "use_check_card", "postpaid_transport"
    ]
    
    for field in boolean_fields:
        if field in collected_info:
            current_value = collected_info[field]
            
            if isinstance(current_value, str):
                if current_value.lower() in ["true", "yes", "네", "예", "신청", "사용", "동의", "확인"]:
                    collected_info[field] = True
                elif current_value.lower() in ["false", "no", "아니요", "아니오", "미신청", "미사용", "거부"]:
                    collected_info[field] = False
    
    # 3. 인터넷뱅킹 관련 정보가 있으면 use_internet_banking = True로 추론
    ib_fields = ["security_medium", "transfer_limit_per_time", "transfer_limit_per_day", 
                 "important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
    if any(field in collected_info for field in ib_fields) and "use_internet_banking" not in collected_info:
        collected_info["use_internet_banking"] = True


def _map_entity_to_valid_choice(field_key: str, entity_value: Any, stage_info: Dict[str, Any]) -> Optional[str]:
    """추출된 엔티티 값을 유효한 선택지로 매핑"""
    
    # stage_info에서 choices 찾기
    choices = []
    if stage_info.get("response_type") == "bullet":
        choices = stage_info.get("choices", [])
    elif stage_info.get("input_type") == "choice":
        choices = stage_info.get("choices", [])
    
    if not choices:
        return entity_value
    
    # 선택지 정보 추출
    valid_values = []
    choice_mapping = {}
    
    for choice in choices:
        if isinstance(choice, dict):
            value = choice.get("value")
            display = choice.get("display", value)
            keywords = choice.get("keywords", [])
            
            valid_values.append(value)
            
            # 키워드 매핑
            for keyword in keywords:
                choice_mapping[keyword.lower()] = value
            
            # display 텍스트도 매핑에 추가
            if display:
                choice_mapping[display.lower()] = value
                
        else:
            valid_values.append(str(choice))
            choice_mapping[str(choice).lower()] = str(choice)
    
    # 엔티티 값 매핑 시도
    entity_str = str(entity_value).lower().strip()
    
    # 1. 정확한 매칭
    if entity_str in choice_mapping:
        return choice_mapping[entity_str]
    
    # 2. 부분 매칭
    for key, value in choice_mapping.items():
        if key in entity_str or entity_str in key:
            return value
    
    # 3. 특수 케이스 처리
    if field_key == "additional_services":
        if "둘" in entity_str or "모두" in entity_str or "다" in entity_str:
            return "both"
        elif "인터넷" in entity_str:
            return "internet_banking"
        elif "체크" in entity_str or "카드" in entity_str:
            return "check_card"
        elif "없" in entity_str or "안" in entity_str:
            return "none"
    
    return None


def _get_default_value_for_field(field_key: str, stage_info: Dict[str, Any]) -> Optional[str]:
    """필드의 기본값 가져오기"""
    
    # DEFAULT_SELECTION이 있는 경우
    if stage_info.get("DEFAULT_SELECTION"):
        return stage_info["DEFAULT_SELECTION"]
    
    # choices에서 default가 True인 항목 찾기
    if stage_info.get("response_type") == "bullet":
        choices = stage_info.get("choices", [])
        for choice in choices:
            if isinstance(choice, dict) and choice.get("default"):
                return choice.get("value")
    
    return None