"""
사용자 의도 매핑 관련 함수들
"""
import json
from typing import Dict, Any, Optional, List
from langchain_core.messages import HumanMessage
from ...chains import json_llm


async def map_user_intent_to_choice(
    user_input: str,
    choices: List[Any],
    field_key: str,
    keyword_mapping: Optional[Dict[str, List[str]]] = None,
    current_stage_info: Dict[str, Any] = None,
    collected_info: Dict[str, Any] = None
) -> Optional[str]:
    """
    사용자 입력을 선택지에 매핑하는 통합 함수
    - 키워드 기반 매핑 우선
    - LLM 기반 의미 매핑 사용
    - 특수 케이스 처리 (card_selection, additional_services 등)
    """
    
    # 특수 케이스 처리
    if field_key == "card_selection" and current_stage_info and collected_info:
        return handle_card_selection_mapping(user_input, choices, current_stage_info, collected_info)
    
    # 먼저 키워드 기반 매칭 시도
    if keyword_mapping:
        user_input_lower = user_input.lower()
        for choice_value, keywords in keyword_mapping.items():
            for keyword in keywords:
                if keyword in user_input_lower:
                    print(f"🎯 [KEYWORD_MATCH] Found '{keyword}' in '{user_input}' -> '{choice_value}'")
                    # additional_services 특수 처리
                    if field_key == "additional_services":
                        return handle_additional_services_mapping(choice_value, field_key)
                    return choice_value
    
    # LLM 기반 의미 매칭
    try:
        # 선택지 정보 준비
        choice_info = []
        choice_values = []
        for choice in choices:
            if isinstance(choice, dict):
                choice_info.append({
                    "value": choice.get("value"),
                    "display": choice.get("display"),
                    "keywords": choice.get("keywords", [])
                })
                choice_values.append(choice.get("value", ""))
            else:
                choice_info.append({"value": choice, "display": choice})
                choice_values.append(str(choice))
        
        prompt = f"""사용자의 입력을 주어진 선택지 중 하나에 매핑해주세요.

사용자 입력: "{user_input}"

선택지:
{json.dumps(choice_info, ensure_ascii=False, indent=2)}

사용자의 의도를 파악하여 가장 적절한 선택지의 value를 반환하세요.
명확한 매칭이 없으면 null을 반환하세요.

JSON 응답 형식:
{{"matched_value": "선택된 value" 또는 null}}

주의: 반드시 제공된 선택지의 value 중 하나를 선택하거나 null을 반환하세요.
"""

        response = await json_llm.ainvoke([HumanMessage(content=prompt)])
        result = json.loads(response.content.strip())
        matched_value = result.get("matched_value")
        
        if matched_value and matched_value in choice_values:
            print(f"🎯 [LLM_CHOICE_MAPPING] Mapped '{user_input}' to '{matched_value}'")
            # additional_services 특수 처리
            if field_key == "additional_services":
                return handle_additional_services_mapping(matched_value, field_key)
            return matched_value
            
    except Exception as e:
        print(f"❌ [LLM_CHOICE_MAPPING] Error: {e}")
    
    return None


async def map_user_intent_to_choice_enhanced(
    user_input: str,
    choices: List[Any],
    field_key: str,
    keyword_mapping: Optional[Dict[str, List[str]]] = None,
    stage_info: Dict[str, Any] = None,
    collected_info: Dict[str, Any] = None
) -> Optional[str]:
    """향상된 사용자 의도 매핑 함수 - 더 정교한 매칭 로직"""
    
    # 1. 먼저 키워드 기반 매칭 시도
    if keyword_mapping:
        matched = fallback_keyword_matching(user_input, keyword_mapping)
        if matched:
            print(f"🎯 [KEYWORD_MATCH_ENHANCED] Found match: '{user_input}' -> '{matched}'")
            return matched
    
    # 2. 완화된 매칭 로직
    user_lower = user_input.lower().strip()
    
    # 선택지 정보 준비
    choice_map = {}
    for choice in choices:
        if isinstance(choice, dict):
            value = choice.get("value", "")
            display = choice.get("display", "")
            keywords = choice.get("keywords", [])
            
            # 모든 가능한 표현을 소문자로 저장
            choice_map[value] = {
                'display': display.lower(),
                'keywords': [k.lower() for k in keywords],
                'original': choice
            }
    
    # 3. 완화된 키워드 매칭
    for value, info in choice_map.items():
        # display 텍스트와 부분 매칭
        if info['display'] and info['display'] in user_lower:
            print(f"🎯 [DISPLAY_MATCH] Found '{info['display']}' in user input -> '{value}'")
            return value
        
        # keywords와 부분 매칭
        for keyword in info['keywords']:
            if keyword and keyword in user_lower:
                print(f"🎯 [KEYWORD_PARTIAL_MATCH] Found '{keyword}' in user input -> '{value}'")
                return value
    
    # 4. LLM 기반 매칭 (기존 로직 유지)
    return await map_user_intent_to_choice(
        user_input, choices, field_key, 
        keyword_mapping, stage_info, collected_info
    )


def handle_additional_services_mapping(choice_value: str, field_key: str) -> str:
    """additional_services 필드의 특수 매핑 처리"""
    # "all"이 "both"로 매핑되어야 함
    if choice_value == "all":
        return "both"
    return choice_value


def handle_card_selection_mapping(
    user_input: str, 
    choices: List[Any], 
    current_stage_info: Dict[str, Any], 
    collected_info: Dict[str, Any]
) -> Optional[str]:
    """card_selection 단계의 특수 매핑 처리"""
    
    # 현재 DEFAULT_SELECTION이 설정되어 있는지 확인
    if current_stage_info.get("DEFAULT_SELECTION"):
        # DEFAULT_SELECTION이 있는 경우에만 적용
        
        # 사용자가 명시적으로 다른 카드를 선택한 경우 확인
        user_lower = user_input.lower().strip()
        
        # 각 카드 타입별 키워드
        card_keywords = {
            "체크카드": ["체크", "체크카드"],
            "신용카드": ["신용", "신용카드"],
            "하이브리드": ["하이브리드", "하이브리드카드", "둘 다", "두 개", "모두"]
        }
        
        # 명시적 선택 확인
        for card_type, keywords in card_keywords.items():
            for keyword in keywords:
                if keyword in user_lower:
                    print(f"🎯 [CARD_SELECTION] Explicit choice detected: '{keyword}' -> '{card_type}'")
                    return card_type
        
        # 명시적 선택이 없고 긍정 응답인 경우
        positive_keywords = ["응", "어", "네", "예", "좋아", "그래", "맞아", "할게", "할래"]
        if any(keyword in user_lower for keyword in positive_keywords):
            default_value = current_stage_info.get("DEFAULT_SELECTION")
            print(f"🎯 [CARD_SELECTION] Positive response, using DEFAULT_SELECTION: '{default_value}'")
            return default_value
    
    # DEFAULT_SELECTION이 없거나 적용되지 않는 경우 None 반환
    return None


def apply_additional_services_values(choice_value: str, collected_info: Dict[str, Any]) -> Dict[str, Any]:
    """additional_services 선택에 따른 추가 필드 값 설정"""
    
    updates = {}
    
    # additional_services 값에 따른 추가 필드 설정
    if choice_value == "internet_banking":
        updates["use_internet_banking"] = True
        updates["use_check_card"] = False
    elif choice_value == "check_card":
        updates["use_internet_banking"] = False
        updates["use_check_card"] = True
    elif choice_value in ["both", "all"]:
        updates["use_internet_banking"] = True
        updates["use_check_card"] = True
    elif choice_value == "none":
        updates["use_internet_banking"] = False
        updates["use_check_card"] = False
    
    return updates


def handle_additional_services_fallback(user_input: str, collected_info: Dict[str, Any]) -> bool:
    """additional_services 단계에서 사용자 입력 해석이 어려운 경우 처리"""
    
    user_lower = user_input.lower().strip()
    
    # 부정적 응답 키워드
    negative_keywords = ["아니", "안", "없", "괜찮", "됐", "필요없", "싫"]
    
    # 긍정적 응답 키워드 (명시적 서비스 언급 없이)
    positive_keywords = ["응", "어", "네", "예", "좋아", "그래"]
    
    # 부정적 응답 확인
    if any(keyword in user_lower for keyword in negative_keywords):
        print("🎯 [ADDITIONAL_SERVICES] Negative response detected -> 'none'")
        collected_info["additional_services"] = "none"
        collected_info.update(apply_additional_services_values("none", collected_info))
        return True
    
    # 긍정적 응답만 있는 경우 - 기본값(both) 적용
    if any(keyword in user_lower for keyword in positive_keywords):
        # 명시적 서비스 언급이 없는지 확인
        service_keywords = ["인터넷", "뱅킹", "체크", "카드", "모바일"]
        if not any(keyword in user_lower for keyword in service_keywords):
            print("🎯 [ADDITIONAL_SERVICES] Simple positive response -> default 'both'")
            collected_info["additional_services"] = "both"
            collected_info.update(apply_additional_services_values("both", collected_info))
            return True
    
    return False


def fallback_keyword_matching(
    user_input: str,
    keyword_mapping: Dict[str, List[str]]
) -> Optional[str]:
    """키워드 매칭의 폴백 로직 - 더 유연한 매칭"""
    
    user_lower = user_input.lower().strip()
    
    # 특수 문자 제거 및 정규화
    import re
    user_normalized = re.sub(r'[^가-힣a-zA-Z0-9\s]', '', user_lower)
    
    # 1. 정확한 매칭
    for choice_value, keywords in keyword_mapping.items():
        for keyword in keywords:
            if keyword.lower() == user_normalized:
                return choice_value
    
    # 2. 부분 매칭
    for choice_value, keywords in keyword_mapping.items():
        for keyword in keywords:
            keyword_lower = keyword.lower()
            # 키워드가 사용자 입력에 포함되거나
            if keyword_lower in user_normalized:
                return choice_value
            # 사용자 입력이 키워드에 포함되는 경우
            if user_normalized in keyword_lower and len(user_normalized) >= 2:
                return choice_value
    
    # 3. 단어 단위 매칭
    user_words = user_normalized.split()
    for choice_value, keywords in keyword_mapping.items():
        for keyword in keywords:
            keyword_words = keyword.lower().split()
            # 모든 키워드 단어가 사용자 입력에 있는지 확인
            if all(kw in user_words for kw in keyword_words):
                return choice_value
    
    return None


def _is_info_modification_request(user_input: str, collected_info: Dict[str, Any]) -> bool:
    """자연스러운 정보 수정 요청인지 감지하는 헬퍼 함수"""
    if not user_input:
        return False
    
    # 간단한 패턴 기반 수정 요청 감지
    # 1. 직접적인 수정 요청
    modification_words = ["틀려", "틀렸", "다르", "다릅", "수정", "변경", "바꿔", "바꾸", "바꿀", "잘못"]
    if any(word in user_input for word in modification_words):
        return True
    
    # 2. "아니야" + 구체적인 정보 패턴
    if "아니" in user_input:
        # 전화번호 패턴
        import re
        if re.search(r'\d{3,4}', user_input):  # 3-4자리 숫자
            return True
        # 이름 변경 패턴
        if any(word in user_input for word in ["이름", "성함"]):
            return True
    
    # 3. 대조 표현 패턴 (X가 아니라 Y)
    contrast_patterns = [
        r'(.+)이?\s*아니(?:라|고|야)',  # X가 아니라/아니고/아니야
        r'(.+)이?\s*말고',  # X 말고
        r'(.+)에서\s*(.+)으로',  # X에서 Y로
    ]
    
    for pattern in contrast_patterns:
        if re.search(pattern, user_input):
            return True
    
    # 4. 기존 정보와 다른 값을 제시하는 경우
    # 전화번호
    if collected_info.get("customer_phone"):
        phone_match = re.search(r'(\d{4})', user_input)
        if phone_match:
            new_number = phone_match.group(1)
            existing_phone = collected_info["customer_phone"]
            if new_number not in existing_phone:
                return True
    
    # 이름
    if collected_info.get("customer_name"):
        # 2-4글자 한글 이름 패턴
        name_match = re.search(r'([가-힣]{2,4})(?:이야|입니다|이에요|예요)?$', user_input)
        if name_match:
            name = name_match.group(1)
            # 기존 이름과 다르고, 일반 단어가 아닌 경우
            if (len(name) >= 2 and 
                name != collected_info["customer_name"] and 
                name not in ["이름", "성함", "번호", "전화", "연락처", "정보", "수정", "변경"]):
                return True
    
    return False