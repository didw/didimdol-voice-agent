"""
시나리오 처리를 위한 유틸리티 함수들
"""
from typing import Dict, Any, Optional, List
from pathlib import Path
import yaml


def create_update_dict_with_last_prompt(update_dict: Dict[str, Any], stage_response_data: Dict[str, Any] = None) -> Dict[str, Any]:
    """Update dict를 생성하면서 last_llm_prompt도 함께 저장"""
    # final_response_text_for_tts가 있으면 last_llm_prompt에도 저장
    if update_dict.get("final_response_text_for_tts"):
        update_dict["last_llm_prompt"] = update_dict["final_response_text_for_tts"]
        print(f"💾 [SAVE_LAST_PROMPT] Saved: '{update_dict['last_llm_prompt'][:100]}...'" if len(update_dict['last_llm_prompt']) > 100 else f"💾 [SAVE_LAST_PROMPT] Saved: '{update_dict['last_llm_prompt']}'")
    
    # stage_response_data에서 prompt 추출하여 저장
    elif stage_response_data and stage_response_data.get("prompt"):
        update_dict["last_llm_prompt"] = stage_response_data["prompt"]
        print(f"💾 [SAVE_LAST_PROMPT] From stage_response_data: '{update_dict['last_llm_prompt'][:100]}...'" if len(update_dict['last_llm_prompt']) > 100 else f"💾 [SAVE_LAST_PROMPT] From stage_response_data: '{update_dict['last_llm_prompt']}'")
    
    return update_dict


def find_scenario_guidance(user_input: str, current_stage: str) -> Optional[str]:
    """현재 단계의 미리 정의된 시나리오 유도 응답 찾기"""
    try:
        # 시나리오 유도 응답 로드
        scenario_guidance_path = Path(__file__).parent.parent.parent.parent / "config" / "scenario_guidance_responses.yaml"
        
        if not scenario_guidance_path.exists():
            return None
            
        with open(scenario_guidance_path, 'r', encoding='utf-8') as f:
            guidance_responses = yaml.safe_load(f)
        
        # 현재 단계의 응답들
        stage_responses = guidance_responses.get(current_stage, {})
        
        # 사용자 입력과 매칭되는 키워드 찾기
        user_input_lower = user_input.lower().strip()
        
        for keywords, response in stage_responses.items():
            if isinstance(keywords, str):
                keyword_list = [keywords]
            else:
                keyword_list = keywords.split(",") if isinstance(keywords, str) else keywords
                
            for keyword in keyword_list:
                if keyword.strip().lower() in user_input_lower:
                    return response
        
        return None
    except Exception as e:
        print(f"❌ [SCENARIO_GUIDANCE] Error loading guidance responses: {e}")
        return None


def format_korean_currency(amount: int) -> str:
    """한국 원화 금액을 포맷팅하는 유틸리티 함수"""
    try:
        amount_int = int(amount)
        if amount_int >= 10000:
            man = amount_int // 10000
            remainder = amount_int % 10000
            if remainder == 0:
                return f"{man:,}만원"
            else:
                return f"{man:,}만 {remainder:,}원"
        else:
            return f"{amount_int:,}원"
    except:
        return str(amount)


def format_field_value(field_key: str, value: Any, field_type: str) -> str:
    """필드 값을 표시용으로 포맷팅"""
    if value is None:
        return "미입력"
    
    # Boolean 타입
    if field_type == "boolean":
        if isinstance(value, bool):
            return "신청" if value else "미신청"
        return str(value)
    
    # 금액 관련 필드
    if field_key in ["transfer_limit_per_time", "transfer_limit_per_day", "transfer_daily_limit"]:
        try:
            amount = int(value)
            return format_korean_currency(amount)
        except:
            return str(value)
    
    # 선택형 필드 - 한글 표시
    choice_display_map = {
        "sms": "SMS",
        "push": "PUSH 알림",
        "모바일브랜치": "모바일",
        "우편수령": "우편"
    }
    
    if str(value) in choice_display_map:
        return choice_display_map[str(value)]
    
    return str(value)


def get_default_choice_display(stage_info: Dict[str, Any]) -> str:
    """기본 선택지의 표시 텍스트 가져오기"""
    if stage_info.get("response_type") == "bullet":
        choices = stage_info.get("choices", [])
        for choice in choices:
            if isinstance(choice, dict) and choice.get("default"):
                return choice.get("display", choice.get("value", ""))
    return ""


def get_expected_field_keys(stage_info: Dict[str, Any]) -> List[str]:
    """스테이지에서 기대되는 필드 키 목록 반환"""
    field_keys = []
    
    # expected_info_key가 있는 경우
    if stage_info.get("expected_info_key"):
        field_keys.append(stage_info["expected_info_key"])
    
    # response_type이 bullet이고 choices가 있는 경우
    if stage_info.get("response_type") == "bullet" and stage_info.get("choices"):
        # 각 choice가 설정하는 필드들 확인
        for choice in stage_info.get("choices", []):
            if isinstance(choice, dict) and choice.get("sets_fields"):
                field_keys.extend(choice["sets_fields"].keys())
    
    # 중복 제거
    return list(set(field_keys))


def get_stage_relevant_fields(current_stage_info: Dict, required_fields: List[Dict], current_stage_id: str) -> List[Dict]:
    """현재 스테이지와 관련된 필드들만 필터링"""
    # 특정 스테이지와 필드 매핑
    stage_field_mapping = {
        "ask_notification_settings": [
            "transfer_limit_per_time", "transfer_limit_per_day",
            "important_transaction_alert", "withdrawal_alert", 
            "overseas_ip_restriction", "limit_account_agreement"
        ],
        "ask_transfer_limit": [
            "transfer_limit_per_time", "transfer_limit_per_day"
        ],
        # 다른 스테이지들도 필요 시 추가
    }
    
    # 현재 스테이지에 해당하는 필드 목록
    relevant_field_keys = stage_field_mapping.get(current_stage_id, [])
    
    # 해당하는 필드들만 필터링
    if relevant_field_keys:
        return [field for field in required_fields if field.get("key") in relevant_field_keys]
    
    # 매핑이 없으면 모든 필드 반환
    return required_fields