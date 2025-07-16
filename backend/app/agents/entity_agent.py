"""
Entity Recognition Agent - Slot Filling 전용 처리기
"""

import json
import re
from typing import Dict, Any, List, Optional, Tuple
from langchain_core.messages import HumanMessage
from ..graph.chains import json_llm


class EntityRecognitionAgent:
    """Slot Filling을 위한 엔티티 인식 및 추출 전용 에이전트"""
    
    def __init__(self):
        self.extraction_prompt = self._get_extraction_prompt()
        self.validation_prompt = self._get_validation_prompt()
    
    def _get_extraction_prompt(self) -> str:
        """엔티티 추출 프롬프트"""
        return """당신은 은행 상담에서 고객의 발화로부터 정확한 정보를 추출하는 전문가입니다.

**현재 상황:**
- 수집해야 할 정보: {required_fields}
- 고객 발화: "{user_input}"

**추출 규칙:**
1. 고객이 명시적으로 언급한 정보만 추출하세요.
2. 추측하거나 암시적인 정보는 추출하지 마세요.
3. 필드 타입에 맞는 형식으로 추출하세요.

**필드 타입별 추출 방법:**
- text: 고객이 말한 그대로 텍스트로 추출
- choice: 제공된 선택지 중에서만 선택 (정확히 일치해야 함)
- number: 숫자만 추출 (단위 제거)
- boolean: true/false로 변환

**출력 형식:**
{{
  "extracted_entities": {{
    "field_key": "extracted_value",
    ...
  }},
  "confidence": 0.0-1.0,
  "unclear_fields": ["field_key1", "field_key2"],
  "reasoning": "추출 과정 설명"
}}

**예시:**
고객: "김철수이고 연락처는 010-1234-5678입니다"
필드: [customer_name(text), phone_number(text)]
출력: {{
  "extracted_entities": {{
    "customer_name": "김철수",
    "phone_number": "010-1234-5678"
  }},
  "confidence": 0.95,
  "unclear_fields": [],
  "reasoning": "고객이 명확히 성함과 연락처를 제공했습니다"
}}"""

    def _get_validation_prompt(self) -> str:
        """추출된 정보 검증 프롬프트"""
        return """추출된 정보의 유효성을 검증하세요.

**추출된 정보:** {extracted_entities}
**필드 정의:** {field_definitions}

**검증 규칙:**
1. choice 타입: 제공된 선택지에 포함되는지 확인
2. number 타입: 숫자 형식이 올바른지 확인  
3. text 타입: 기본적인 형식 검증 (이름, 전화번호 등)
4. boolean 타입: true/false 값인지 확인

**출력 형식:**
{{
  "valid_entities": {{
    "field_key": "validated_value",
    ...
  }},
  "invalid_entities": {{
    "field_key": "error_reason",
    ...
  }},
  "need_clarification": ["field_key1", "field_key2"]
}}"""

    async def extract_entities(
        self, 
        user_input: str, 
        required_fields: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """사용자 입력에서 엔티티 추출"""
        
        # 필드 정보를 프롬프트에 포함할 형태로 변환
        field_descriptions = []
        for field in required_fields:
            desc = f"- {field['key']} ({field['type']}): {field['display_name']}"
            if field.get('choices'):
                desc += f" [선택지: {', '.join(field['choices'])}]"
            field_descriptions.append(desc)
        
        prompt = self.extraction_prompt.format(
            required_fields='\n'.join(field_descriptions),
            user_input=user_input
        )
        
        try:
            response = await json_llm.ainvoke([HumanMessage(content=prompt)])
            result = json.loads(response.content)
            
            print(f"[EntityAgent] Extraction result: {result}")
            return result
            
        except Exception as e:
            print(f"[EntityAgent] Extraction error: {e}")
            return {
                "extracted_entities": {},
                "confidence": 0.0,
                "unclear_fields": [field['key'] for field in required_fields],
                "reasoning": f"추출 오류: {str(e)}"
            }
    
    async def validate_entities(
        self, 
        extracted_entities: Dict[str, Any], 
        field_definitions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """추출된 엔티티 검증"""
        
        prompt = self.validation_prompt.format(
            extracted_entities=json.dumps(extracted_entities, ensure_ascii=False),
            field_definitions=json.dumps(field_definitions, ensure_ascii=False)
        )
        
        try:
            response = await json_llm.ainvoke([HumanMessage(content=prompt)])
            result = json.loads(response.content)
            
            print(f"[EntityAgent] Validation result: {result}")
            return result
            
        except Exception as e:
            print(f"[EntityAgent] Validation error: {e}")
            return {
                "valid_entities": {},
                "invalid_entities": {k: f"검증 오류: {str(e)}" for k in extracted_entities.keys()},
                "need_clarification": list(extracted_entities.keys())
            }
    
    def extract_with_patterns(self, user_input: str, field_key: str) -> Optional[str]:
        """패턴 기반 정보 추출 (fallback 방식)"""
        patterns = {
            "phone_number": [
                r"010[-\s]?\d{4}[-\s]?\d{4}",
                r"011[-\s]?\d{3,4}[-\s]?\d{4}",
                r"\d{3}[-\s]?\d{4}[-\s]?\d{4}"
            ],
            "customer_name": [
                r"([김이박최정강조윤장임한신오서권황안송류전고문양손배백허남심노정하곽성차주우구신임나전민유진지마진원봉][\w]{1,3})",
                r"([\w가-힣]{2,4})(?:입니다|이에요|예요|이고|입니다)"
            ],
            "ib_daily_limit": [
                r"(\d+)만원?",
                r"(\d+)천만원?",
                r"한도\s*(\d+)",
                r"(\d+)원?"
            ],
            "cc_delivery_address": [
                r"([\w가-힣\s\-\.]+(?:구|시|동|로|길)[\w가-힣\s\-\.]*)"
            ]
        }
        
        if field_key not in patterns:
            return None
        
        for pattern in patterns[field_key]:
            match = re.search(pattern, user_input)
            if match:
                return match.group(1).strip()
        
        return None
    
    async def process_slot_filling(
        self, 
        user_input: str, 
        required_fields: List[Dict[str, Any]], 
        collected_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """종합적인 Slot Filling 처리"""
        
        print(f"[EntityAgent] Processing slot filling for input: '{user_input}'")
        print(f"[EntityAgent] Required fields: {[f['key'] for f in required_fields]}")
        
        # 1단계: LLM 기반 엔티티 추출
        extraction_result = await self.extract_entities(user_input, required_fields)
        extracted_entities = extraction_result.get("extracted_entities", {})
        
        # 2단계: 패턴 기반 보완 (LLM이 놓친 정보)
        for field in required_fields:
            field_key = field['key']
            if field_key not in extracted_entities:
                pattern_result = self.extract_with_patterns(user_input, field_key)
                if pattern_result:
                    extracted_entities[field_key] = pattern_result
                    print(f"[EntityAgent] Pattern extraction: {field_key} = {pattern_result}")
        
        # 3단계: 검증
        if extracted_entities:
            validation_result = await self.validate_entities(extracted_entities, required_fields)
            valid_entities = validation_result.get("valid_entities", {})
            invalid_entities = validation_result.get("invalid_entities", {})
        else:
            valid_entities = {}
            invalid_entities = {}
        
        # 4단계: 결과 정리
        new_collected_info = collected_info.copy()
        new_collected_info.update(valid_entities)
        
        # 여전히 부족한 필드 확인
        missing_fields = []
        for field in required_fields:
            field_key = field['key']
            if field.get('required', False) and field_key not in new_collected_info:
                missing_fields.append(field)
        
        return {
            "collected_info": new_collected_info,
            "extracted_entities": extracted_entities,
            "valid_entities": valid_entities,
            "invalid_entities": invalid_entities,
            "missing_fields": missing_fields,
            "extraction_confidence": extraction_result.get("confidence", 0.0),
            "is_complete": len(missing_fields) == 0
        }
    
    def generate_missing_info_prompt(self, missing_fields: List[Dict[str, Any]]) -> str:
        """부족한 정보 재질의 메시지 생성"""
        if not missing_fields:
            return ""
        
        if len(missing_fields) == 1:
            field = missing_fields[0]
            message = f"{field['display_name']}을(를) 알려주세요."
            
            if field.get('choices'):
                choices_text = ', '.join(field['choices'])
                message += f" ({choices_text} 중에서 선택해주세요)"
            
            return message
        
        else:
            field_names = [f['display_name'] for f in missing_fields]
            return f"다음 정보를 알려주세요: {', '.join(field_names)}"


# 전역 인스턴스
entity_agent = EntityRecognitionAgent()