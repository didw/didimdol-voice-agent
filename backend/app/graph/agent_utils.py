"""
Agent 유틸리티 함수들
- 정보 추출, 필드 검증, 프롬프트 생성 등
"""

import re
import json
from typing import Dict, Any, List, Optional, Tuple
from langchain_core.messages import HumanMessage
from ..core.config import get_llm_model
from ..data.scenario_loader import ALL_SCENARIOS_DATA

# json_llm 초기화
json_llm = get_llm_model(response_format={"type": "json_object"})


def format_transitions_for_prompt(transitions: List[Dict], current_prompt: str) -> str:
    """프롬프트용 전환 조건 포맷팅"""
    if not transitions:
        return "전환 조건이 정의되지 않음"
    
    formatted = []
    for transition in transitions:
        condition = transition.get("condition", "")
        next_stage = transition.get("next_stage_id", "")
        formatted.append(f"  - 조건: {condition} -> 다음: {next_stage}")
    
    return "\n".join(formatted)


def get_active_scenario_data(state: Dict) -> Optional[Dict]:
    """현재 활성화된 시나리오 데이터 가져오기"""
    current_product = state.get("current_product_type")
    if current_product and current_product in ALL_SCENARIOS_DATA:
        return ALL_SCENARIOS_DATA[current_product]
    return None


async def extract_multiple_info_from_text(text: str, required_fields: List[Dict]) -> Dict[str, Any]:
    """LLM을 사용하여 텍스트에서 여러 정보를 한번에 추출"""
    print(f"🤖 [LLM-based Extraction] Processing text: '{text[:100]}...'")
    
    # 필드 정보를 LLM 프롬프트로 변환
    fields_description = []
    for field in required_fields:
        field_desc = f"- {field['key']} ({field.get('display_name', field['key'])}): "
        field_desc += f"타입={field.get('type', 'text')}"
        if field.get('description'):
            field_desc += f", 설명={field['description']}"
        fields_description.append(field_desc)
    
    extraction_prompt = f"""
다음 사용자 입력에서 요청된 정보를 추출해주세요:

사용자 입력: "{text}"

추출해야 할 필드들:
{chr(10).join(fields_description)}

추출 규칙:
1. 사용자가 명시적으로 언급한 정보만 추출하세요.
2. 추측하거나 가정하지 마세요.
3. 숫자는 적절한 형식으로 변환하세요 (예: "3억" → 30000, "500만원" → 500).
4. boolean 타입은 true/false로 표현하세요.

특별 처리:
- loan_purpose_confirmed: "주택 구입", "집 사기", "구매" 등이 있으면 true
- marital_status: "미혼", "기혼", "예비부부" 중 하나
- has_home: "무주택", "집 없다" 등이 있으면 false
- annual_income, target_home_price: 만원 단위로 변환

JSON 형식으로만 응답하세요:
{{
    "extracted_fields": {{
        "field_key": value,
        ...
    }}
}}
"""
    
    try:
        response = await json_llm.ainvoke([HumanMessage(content=extraction_prompt)])
        result = json.loads(response.content.strip().replace("```json", "").replace("```", ""))
        
        extracted_fields = result.get("extracted_fields", {})
        
        print(f"🤖 [LLM Extraction] Extracted fields: {extracted_fields}")
        return extracted_fields
        
    except Exception as e:
        print(f"🤖 [LLM Extraction] Error: {e}")
        return {}


def check_required_info_completion(collected_info: Dict, required_fields: List[Dict]) -> tuple[bool, List[str]]:
    """필수 정보 수집 완료 여부 확인"""
    missing_fields = []
    
    for field in required_fields:
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
    
    print(f"현재 수집된 정보: {collected_info}")
    
    # 각 그룹에서 누락된 정보가 있는지 확인
    group1_missing = any(field not in collected_info for field in group1_fields)
    group2_missing = any(field not in collected_info for field in group2_fields)
    group3_missing = any(field not in collected_info for field in group3_fields)
    
    print(f"그룹별 누락 상태 - Group1: {group1_missing}, Group2: {group2_missing}, Group3: {group3_missing}")
    
    if group1_missing:
        return "ask_missing_info_group1"
    elif group2_missing:
        return "ask_missing_info_group2"
    elif group3_missing:
        return "ask_missing_info_group3"
    else:
        return "eligibility_assessment"


def generate_group_specific_prompt(stage_id: str, collected_info: Dict) -> str:
    """그룹별로 이미 수집된 정보를 제외하고 맞춤형 질문 생성"""
    print(f"질문 생성 - stage_id: {stage_id}, collected_info: {collected_info}")
    
    if stage_id == "ask_missing_info_group1":
        missing = []
        has_loan_purpose = collected_info.get("loan_purpose_confirmed", False)
        has_marital_status = "marital_status" in collected_info
        
        if not has_loan_purpose:
            missing.append("대출 목적(주택 구입용인지)")
        if not has_marital_status:
            missing.append("혼인 상태")
        
        print(f"Group1 누락 정보: {missing}")
        
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