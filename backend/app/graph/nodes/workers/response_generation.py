"""
응답 생성 관련 함수들
"""
import json
from typing import Dict, Any, Optional, List
from pathlib import Path
import yaml
from langchain_core.messages import HumanMessage
from ...chains import json_llm
from .scenario_utils import find_scenario_guidance, format_korean_currency, format_field_value


async def generate_natural_response(
    user_input: str,
    current_stage: str,
    stage_info: Dict[str, Any],
    collected_info: Dict[str, Any],
    extraction_result: Dict[str, Any],
    next_stage_info: Dict[str, Any] = None,
    scenario_deviation: bool = False,
    deviation_topic: Optional[str] = None
) -> str:
    """
    LLM을 사용하여 자연스러운 응답 생성 - 통합 버전
    - 오타나 이상한 표현도 자연스럽게 처리
    - 시나리오 이탈 시 자연스럽게 유도
    """
    
    print(f"\n🌐 [LLM_NATURAL_RESPONSE] 자연스러운 응답 생성 시작")
    print(f"   📝 사용자 입력: \"{user_input}\"")
    print(f"   📍 현재 단계: {current_stage}")
    print(f"   📋 추출된 정보: {extraction_result.get('extracted_entities', {})}")
    
    # 시나리오 프롬프트
    stage_prompt = stage_info.get("prompt", "") if stage_info else ""
    stage_name = stage_info.get("stage_name", current_stage)
    
    # 다음 단계 프롬프트
    next_prompt = ""
    if next_stage_info:
        next_prompt = next_stage_info.get("prompt", "")
    
    # 오타 수정 정보
    typo_corrections = extraction_result.get("typo_corrections", {})
    
    # 사용자 의도 분석 결과
    intent_analysis = extraction_result.get("intent_analysis", {})
    user_intent = intent_analysis.get("intent", "")
    
    # 시나리오 유도 필요 여부 판단
    needs_scenario_guidance = (
        scenario_deviation or
        user_intent in ["질문", "혼란", "기타"] or 
        extraction_result.get("confidence", 1.0) < 0.5 or 
        not extraction_result.get("extracted_entities")
    )
    
    # 미리 정의된 시나리오 유도 응답 찾기
    predefined_guidance = find_scenario_guidance(user_input, current_stage) if needs_scenario_guidance else None
    
    if predefined_guidance:
        print(f"✅ [PREDEFINED_GUIDANCE] Using predefined response")
        return predefined_guidance
    
    # 오타나 무관한 발화인 경우 간단한 유도 응답
    if scenario_deviation and not deviation_topic:
        prompt = f"""사용자가 이해하기 어려운 말을 했습니다. 친절하게 다시 질문을 유도하세요.

사용자 입력: "{user_input}"
현재 질문: {stage_prompt or "질문을 계속 진행해주세요"}

친절하고 자연스럽게 응답하되, 현재 질문으로 다시 유도하세요.
응답은 2-3문장으로 작성하세요."""
    else:
        # 일반적인 응답 생성
        prompt = f"""한국 은행 상담원으로서 사용자의 응답을 처리하고 자연스럽게 대화를 이어가세요.

[상황 정보]
- 현재 단계: {stage_name} ({current_stage})
- 현재 질문/안내: {stage_prompt}
- 사용자 응답: "{user_input}"

[처리 결과]
- 추출된 정보: {json.dumps(extraction_result.get('extracted_entities', {}), ensure_ascii=False)}
- 사용자 의도: {user_intent}
- 신뢰도: {extraction_result.get('confidence', 1.0)}

[오타 수정]
{json.dumps(typo_corrections, ensure_ascii=False) if typo_corrections else "없음"}

[다음 단계]
{f"다음 질문/안내: {next_prompt}" if next_prompt else "현재 단계 계속 진행"}

[응답 작성 지침]
1. 추출된 정보가 있으면 간단히 확인 (예: "네, 확인했습니다")
2. 오타가 있었다면 자연스럽게 수정된 내용으로 확인
3. 시나리오 이탈이나 무관한 질문이면 친절하게 답변 후 현재 질문으로 유도
4. 다음 단계로 진행할 때는 자연스럽게 연결
5. 응답은 간결하고 친근하게 (2-3문장)

[응답 예시]
- 정보 수집 성공: "네, (확인내용). 다음 질문입니다..."
- 오타 처리: "아, (수정된 내용) 말씀이시군요. 확인했습니다..."
- 시나리오 이탈: "(간단한 답변). 먼저 현재 진행 중인 (업무)를 계속할게요..."

응답:"""

    try:
        response = await json_llm.ainvoke([HumanMessage(content=prompt)])
        response_text = response.content.strip()
        
        print(f"✅ [LLM_NATURAL_RESPONSE] Generated response")
        return response_text
        
    except Exception as e:
        print(f"❌ [LLM_NATURAL_RESPONSE] Error: {e}")
        
        # 폴백 응답
        if extraction_result.get("extracted_entities"):
            return f"네, 확인했습니다. {next_prompt if next_prompt else '계속 진행하겠습니다.'}"
        else:
            return f"죄송합니다. 다시 한 번 말씀해주시겠어요? {stage_prompt}"


async def generate_choice_clarification_response(
    user_input: str,
    choices: List[Any],
    stage_info: Dict[str, Any],
    field_key: str
) -> str:
    """선택지를 명확히 하는 자연스러운 응답 생성"""
    
    # 선택지 정보 준비
    choice_descriptions = []
    for choice in choices:
        if isinstance(choice, dict):
            display = choice.get("display", choice.get("value", ""))
            description = choice.get("description", "")
            if description:
                choice_descriptions.append(f"- {display}: {description}")
            else:
                choice_descriptions.append(f"- {display}")
        else:
            choice_descriptions.append(f"- {choice}")
    
    choice_text = "\n".join(choice_descriptions)
    
    # 단계별 맞춤 설명
    stage_specific_guidance = {
        "additional_services": "인터넷뱅킹은 온라인으로 계좌 조회와 이체를 할 수 있는 서비스이고, 체크카드는 계좌 잔액 내에서 결제할 수 있는 카드입니다.",
        "card_selection": "체크카드는 계좌 잔액 내에서만 사용 가능하고, 신용카드는 신용한도 내에서 사용 후 결제일에 대금을 납부합니다.",
        "statement_delivery": "이메일은 전자우편으로, 우편은 실물 우편으로 받으시는 방법입니다."
    }
    
    additional_guidance = stage_specific_guidance.get(stage_info.get("id", ""), "")
    
    prompt = f"""사용자가 선택을 망설이고 있습니다. 선택지를 친절하게 설명하고 결정을 도와주세요.

현재 질문: {stage_info.get('prompt', '')}
사용자 입력: "{user_input}"

선택 가능한 옵션:
{choice_text}

{additional_guidance}

친절하고 도움이 되는 톤으로 2-3문장으로 응답하세요.
각 옵션의 장단점이나 특징을 간단히 설명해주세요."""

    try:
        response = await json_llm.ainvoke([HumanMessage(content=prompt)])
        return response.content.strip()
    except Exception as e:
        print(f"❌ [CHOICE_CLARIFICATION] Error: {e}")
        return f"어떤 것을 선택하실지 고민이시군요. {choice_text}\n\n원하시는 것을 선택해주세요."


def generate_choice_confirmation_response(
    choice_value: str,
    choice_display: str,
    field_key: str,
    stage_info: Dict[str, Any]
) -> str:
    """선택 확인 응답 생성 - 각 필드별 맞춤 응답"""
    
    # 필드별 확인 메시지 템플릿
    confirmation_templates = {
        "services_selected": {
            "all": "네, 입출금 계좌와 체크카드, 모바일 뱅킹을 모두 신청해드리겠습니다.",
            "mobile_only": "네, 입출금 계좌와 모바일 뱅킹만 신청해드리겠습니다.",
            "card_only": "네, 입출금 계좌와 체크카드만 신청해드리겠습니다.",
            "account_only": "알겠습니다. 입출금 계좌만 개설해드리겠습니다."
        },
        "additional_services": {
            "internet_banking": "네, 인터넷뱅킹만 신청해드리겠습니다.",
            "check_card": "네, 체크카드만 신청해드리겠습니다.",
            "both": "네, 인터넷뱅킹과 체크카드 모두 신청해드리겠습니다.",
            "none": "네, 추가 서비스는 신청하지 않으시는 것으로 확인했습니다."
        },
        "card_selection": {
            "체크카드": "네, 체크카드로 발급해드리겠습니다.",
            "신용카드": "네, 신용카드로 발급해드리겠습니다.",
            "하이브리드": "네, 하이브리드 카드로 발급해드리겠습니다."
        },
        "statement_delivery": {
            "email": "네, 거래명세서를 이메일로 받으시는 것으로 확인했습니다.",
            "mail": "네, 거래명세서를 우편으로 받으시는 것으로 확인했습니다."
        },
        "card_usage_alert": {
            "sms": "네, 카드 사용 알림을 SMS로 받으시겠습니다.",
            "push": "네, 카드 사용 알림을 모바일 앱 푸시로 받으시겠습니다."
        },
        "security_medium": {
            "otp": "네, OTP를 보안매체로 선택하셨습니다.",
            "보안카드": "네, 보안카드를 선택하셨습니다."
        }
    }
    
    # 해당 필드의 템플릿 확인
    field_templates = confirmation_templates.get(field_key, {})
    
    # 템플릿에서 응답 찾기
    if choice_value in field_templates:
        return field_templates[choice_value]
    
    # 기본 응답
    return f"네, {choice_display}(으)로 확인했습니다."


def generate_confirmation_message(
    newly_extracted: Dict[str, Any],
    collected_info: Dict[str, Any],
    scenario_data: Dict[str, Any]
) -> str:
    """새로 추출된 정보에 대한 확인 메시지 생성"""
    
    confirmation_parts = []
    
    # 필드별 확인 메시지
    field_confirmations = {
        'customer_name': lambda v: f"성함은 {v}님",
        'phone_number': lambda v: f"연락처는 {v}",
        'customer_phone': lambda v: f"연락처는 {v}",
        'address': lambda v: f"주소는 {v}",
        'email': lambda v: f"이메일은 {v}",
        'transfer_limit_per_time': lambda v: f"1회 이체한도는 {format_korean_currency(v)}",
        'transfer_limit_per_day': lambda v: f"1일 이체한도는 {format_korean_currency(v)}",
        'use_internet_banking': lambda v: "인터넷뱅킹 신청" if v else "인터넷뱅킹 미신청",
        'use_check_card': lambda v: "체크카드 신청" if v else "체크카드 미신청",
        'additional_services': lambda v: {
            'internet_banking': '인터넷뱅킹만 신청',
            'check_card': '체크카드만 신청',
            'both': '인터넷뱅킹과 체크카드 모두 신청',
            'none': '추가 서비스 미신청'
        }.get(v, v)
    }
    
    # 각 필드에 대한 확인 메시지 생성
    for field, value in newly_extracted.items():
        if field in field_confirmations:
            if callable(field_confirmations[field]):
                msg = field_confirmations[field](value)
            else:
                msg = field_confirmations[field]
            
            if msg:
                confirmation_parts.append(msg)
        else:
            # 기본 처리
            field_info = next((f for f in scenario_data.get('required_info_fields', []) 
                             if f['key'] == field), None)
            if field_info:
                display_name = field_info.get('display_name', field)
                formatted_value = format_field_value(field, value, field_info.get('type', 'text'))
                confirmation_parts.append(f"{display_name}은(는) {formatted_value}")
    
    if confirmation_parts:
        # 여러 정보가 있을 때
        if len(confirmation_parts) > 1:
            return "네, " + ", ".join(confirmation_parts[:-1]) + f" 그리고 {confirmation_parts[-1]}(으)로 확인했습니다."
        else:
            return f"네, {confirmation_parts[0]}(으)로 확인했습니다."
    
    return "네, 확인했습니다."


def generate_re_prompt(
    valid_fields: List[str],
    invalid_fields: List[Dict[str, str]],
    missing_fields: List[Dict[str, Any]],
    all_fields: List[Dict[str, Any]]
) -> str:
    """재질문 프롬프트 생성"""
    
    response_parts = []
    
    # 필드 정보를 딕셔너리로 변환
    field_info_map = {field['key']: field for field in all_fields}
    
    # 수집된 필드 확인
    if valid_fields:
        # 여러 필드를 한 번에 확인
        if len(valid_fields) > 3:
            response_parts.append("입력하신 정보들을 확인했습니다.")
        else:
            field_names = []
            for field_key in valid_fields:
                field_info = field_info_map.get(field_key, {})
                display_name = field_info.get('display_name', field_key)
                field_names.append(display_name)
            
            response_parts.append(f"{', '.join(field_names)}은(는) 확인했습니다.")
    
    # 유효하지 않은 필드에 대한 재질문
    if invalid_fields:
        for field_info in invalid_fields:
            response_parts.append(field_info["error"])
    
    # 누락된 필드에 대한 질문
    if missing_fields:
        field_names = []
        for field in missing_fields:
            display_name = field.get('display_name', field.get('key', ''))
            field_names.append(display_name)
        
        if len(field_names) == 1:
            response_parts.append(f"{field_names[0]}을(를) 알려주세요.")
        else:
            response_parts.append(f"{', '.join(field_names[:-1])}와(과) {field_names[-1]}을(를) 알려주세요.")
    
    return " ".join(response_parts)


def generate_final_confirmation_prompt(collected_info: Dict[str, Any]) -> str:
    """최종 확인 단계의 프롬프트 생성"""
    
    sections = []
    
    # 1. 기본 정보
    basic_info = []
    if collected_info.get("customer_name"):
        basic_info.append(f"• 성함: {collected_info['customer_name']}")
    if collected_info.get("phone_number") or collected_info.get("customer_phone"):
        phone = collected_info.get("phone_number") or collected_info.get("customer_phone")
        basic_info.append(f"• 연락처: {phone}")
    if collected_info.get("email"):
        basic_info.append(f"• 이메일: {collected_info['email']}")
    
    if basic_info:
        sections.append("📋 기본 정보\n" + "\n".join(basic_info))
    
    # 2. 계좌 설정
    account_info = []
    if collected_info.get("use_lifelong_account") is not None:
        lifelong = "등록" if collected_info.get("use_lifelong_account") else "미등록"
        account_info.append(f"• 평생계좌번호: {lifelong}")
    
    if account_info:
        sections.append("🏦 계좌 설정\n" + "\n".join(account_info))
    
    # 3. 인터넷뱅킹
    if collected_info.get("use_internet_banking"):
        ib_info = ["• 신청: ✓"]
        
        if collected_info.get("security_medium"):
            ib_info.append(f"• 보안매체: {collected_info['security_medium']}")
        
        if collected_info.get("transfer_limit_per_time"):
            ib_info.append(f"• 1회 이체한도: {format_korean_currency(collected_info['transfer_limit_per_time'])}")
        if collected_info.get("transfer_limit_per_day"):
            ib_info.append(f"• 1일 이체한도: {format_korean_currency(collected_info['transfer_limit_per_day'])}")
        
        # 알림 설정
        alerts = []
        if collected_info.get("important_transaction_alert"):
            alerts.append("중요거래")
        if collected_info.get("withdrawal_alert"):
            alerts.append("출금")
        if alerts:
            ib_info.append(f"• 알림: {', '.join(alerts)}")
        
        sections.append("💻 인터넷뱅킹\n" + "\n".join(ib_info))
    
    # 4. 체크카드
    if collected_info.get("use_check_card"):
        card_info = ["• 신청: ✓"]
        
        if collected_info.get("card_selection"):
            card_info.append(f"• 카드종류: {collected_info['card_selection']}")
        
        if collected_info.get("card_design"):
            card_info.append(f"• 디자인: {collected_info['card_design']}")
        
        if collected_info.get("card_usage_alert"):
            alert_type = "SMS" if collected_info['card_usage_alert'] == "sms" else "PUSH 알림"
            card_info.append(f"• 사용알림: {alert_type}")
        
        sections.append("💳 체크카드\n" + "\n".join(card_info))
    
    # 5. 거래명세서
    if collected_info.get("statement_delivery"):
        delivery = "이메일" if collected_info['statement_delivery'] == "email" else "우편"
        sections.append(f"📮 거래명세서: {delivery} 수령")
    
    # 최종 조합
    prompt = "지금까지 신청하신 내용을 확인해드리겠습니다.\n\n"
    prompt += "\n\n".join(sections)
    prompt += "\n\n위 내용이 맞으신가요? 수정하실 부분이 있으면 말씀해주세요."
    
    return prompt