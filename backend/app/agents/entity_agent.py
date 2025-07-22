"""
Entity Recognition Agent - Slot Filling 전용 처리기
"""

import json
import re
from typing import Dict, Any, List, Optional, Tuple
from langchain_core.messages import HumanMessage
from ..graph.chains import json_llm, generative_llm
from ..config.prompt_loader import load_yaml_file
from pathlib import Path


class EntityRecognitionAgent:
    """Slot Filling을 위한 엔티티 인식 및 추출 전용 에이전트"""
    
    def __init__(self):
        self.extraction_prompt = self._get_extraction_prompt()
        self.validation_prompt = self._get_validation_prompt()
        # entity_extraction_prompts.yaml 파일 로드
        config_dir = Path(__file__).parent.parent / "config"
        self.entity_prompts = load_yaml_file(str(config_dir / "entity_extraction_prompts.yaml"))
        
        # 필드 키 매핑은 더 이상 필요없음 (YAML 파일에서 customer_phone 직접 사용)
    
    def _get_extraction_prompt(self) -> str:
        """엔티티 추출 프롬프트"""
        return """당신은 은행 상담에서 고객의 발화로부터 정확한 정보를 추출하는 전문가입니다.

**현재 상황:**
- 수집해야 할 정보: {required_fields}
- 고객 발화: "{user_input}"
- 추가 추출 가이드: {extraction_prompts}

**추출 규칙:**
1. 고객이 명시적으로 언급한 정보만 추출하세요.
2. 추측하거나 암시적인 정보는 추출하지 마세요.
3. 필드 타입에 맞는 형식으로 추출하세요.
4. 추가 추출 가이드가 제공된 경우 이를 참고하세요.

**필드 타입별 추출 방법:**
- text: 고객이 말한 그대로 텍스트로 추출
- choice: 제공된 선택지 중에서만 선택 (정확히 일치해야 함)
- number: 숫자만 추출 (단위 제거, 예: "5천만원" → 5000, "1억" → 10000)
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
        """사용자 입력에서 엔티티 추출 - 최적화된 단일 LLM 호출"""
        
        # 짧은 입력이나 간단한 응답인 경우 패턴 매칭만 수행
        if len(user_input.strip()) < 10:
            pattern_results = {}
            for field in required_fields:
                field_key = field['key']
                pattern_result = self.extract_with_patterns(user_input, field_key)
                if pattern_result:
                    pattern_results[field_key] = pattern_result
            
            if pattern_results:
                print(f"[EntityAgent] Quick pattern match for short input: {pattern_results}")
                return {
                    "extracted_entities": pattern_results,
                    "confidence": 0.9,
                    "unclear_fields": [],
                    "reasoning": "패턴 매칭으로 빠른 추출"
                }
        
        # 복잡한 입력인 경우 단일 LLM 호출로 모든 필드 추출
        # 필드 정보를 구조화
        field_descriptions = []
        for field in required_fields:
            desc = {
                "key": field['key'],
                "display_name": field.get('display_name', field['key']),
                "type": field['type'],
                "required": field.get('required', False)
            }
            if field.get('choices'):
                desc['choices'] = field['choices']
            field_descriptions.append(desc)
        
        # 통합 추출 프롬프트
        unified_prompt = f"""사용자 발화에서 명시적으로 언급된 정보만 추출하세요. 절대 추론하거나 기본값을 넣지 마세요.

사용자 발화: "{user_input}"

추출 가능한 필드들:
{json.dumps(field_descriptions, ensure_ascii=False, indent=2)}

추출 규칙:
1. 사용자가 직접 말한 내용만 추출 (추론 금지)
2. 언급하지 않은 필드는 절대 추출하지 말 것
3. boolean 타입: 명시적 언급만 (네/예 → true, 아니요 → false)
4. number 타입: 한국어 숫자 정확히 변환
   - "오백만원" → 500 (만원 단위)
   - "일일" 또는 "1일" → 1일 이체한도
   - "일회" 또는 "1회" → 1회 이체한도
5. choice 타입: 제공된 선택지 중에서만 선택

중요: 
- 1회/1일 이체한도는 반드시 구분할 것
- 사용자가 말하지 않은 정보는 빈 값으로 둘 것
- "일일 오백만원"이라고 하면 transfer_limit_per_day: 500만 추출

응답 형식 (JSON):
{{
  "extracted_fields": {{
    "field_key": "value"  // 실제로 언급된 것만
  }},
  "confidence": 0.0-1.0
}}"""

        try:
            print(f"[EntityAgent] Unified extraction for input: '{user_input}'")
            response = await json_llm.ainvoke([HumanMessage(content=unified_prompt)])
            
            # JSON 파싱
            content = response.content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            result = json.loads(content)
            extracted_fields = result.get("extracted_fields", {})
            
            # 타입별 후처리
            processed_entities = {}
            for field_key, value in extracted_fields.items():
                field_def = next((f for f in required_fields if f['key'] == field_key), None)
                if field_def:
                    if field_def['type'] == 'number' and isinstance(value, str):
                        converted = convert_korean_number(value)
                        if converted is not None:
                            processed_entities[field_key] = converted
                        else:
                            try:
                                processed_entities[field_key] = int(value)
                            except:
                                pass
                    else:
                        processed_entities[field_key] = value
            
            print(f"[EntityAgent] Unified extraction result: {processed_entities}")
            
            return {
                "extracted_entities": processed_entities,
                "confidence": result.get("confidence", 0.8),
                "unclear_fields": [],
                "reasoning": f"통합 LLM 추출 - {len(processed_entities)}개 필드 발견"
            }
            
        except Exception as e:
            print(f"[EntityAgent] Unified extraction error: {e}")
            # 폴백: 패턴 매칭 시도
            pattern_results = {}
            for field in required_fields:
                field_key = field['key']
                pattern_result = self.extract_with_patterns(user_input, field_key)
                if pattern_result:
                    pattern_results[field_key] = pattern_result
            
            return {
                "extracted_entities": pattern_results,
                "confidence": 0.5,
                "unclear_fields": [f['key'] for f in required_fields if f['key'] not in pattern_results],
                "reasoning": f"LLM 오류로 패턴 매칭 사용: {str(e)}"
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
            # JSON 형식 요청을 프롬프트에 명시적으로 추가
            prompt += "\n\n반드시 JSON 형식으로 응답해주세요."
            response = await json_llm.ainvoke([HumanMessage(content=prompt)])
            result = json.loads(response.content)
            
            print(f"[EntityAgent] Validation result: {result}")
            return result
            
        except Exception as e:
            return {
                "valid_entities": {},
                "invalid_entities": {k: f"검증 오류: {str(e)}" for k in extracted_entities.keys()},
                "need_clarification": list(extracted_entities.keys())
            }
    
    def extract_with_patterns(self, user_input: str, field_key: str) -> Optional[str]:
        """패턴 기반 정보 추출 (fallback 방식)"""
        patterns = {
            "customer_phone": [  # phone_number -> customer_phone으로 변경
                r"010[-\s]?\d{4}[-\s]?\d{4}",
                r"011[-\s]?\d{3,4}[-\s]?\d{4}",
                r"\d{3}[-\s]?\d{4}[-\s]?\d{4}"
            ],
            "phone_number": [  # 호환성을 위해 유지
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
            "transfer_limit_per_time": [
                r"1회\s*(\d+)만원?",
                r"회당\s*(\d+)만원?",
                r"한번에\s*(\d+)만원?"
            ],
            "transfer_limit_per_day": [
                r"1일\s*(\d+)만원?",
                r"하루\s*(\d+)만원?",
                r"일일\s*(\d+)만원?"
            ],
            "cc_delivery_address": [
                r"([\w가-힣\s\-\.]+(?:구|시|동|로|길)[\w가-힣\s\-\.]*)"
            ],
            "card_delivery_location": [
                r"([\w가-힣\s\-\.]+(?:구|시|동|로|길)[\w가-힣\s\-\.]*)"
            ],
            "payment_date": [
                r"(\d{1,2})일",
                r"매월\s*(\d{1,2})",
                r"(\d{1,2})일날",
                r"월\s*(\d{1,2})"
            ]
        }
        
        # Boolean 필드를 위한 간단한 패턴
        positive_patterns = ["네", "예", "응", "맞아", "맞습니다", "확인", "동의", "ok", "okay", "ㅇㅇ", "ㅇㅋ"]
        negative_patterns = ["아니", "아뇨", "아니요", "아니에요", "안", "싫", "no", "ㄴㄴ"]
        
        # Boolean 타입 필드 처리
        if field_key in ["confirm_personal_info", "use_lifelong_account", "use_internet_banking", 
                         "additional_withdrawal_account", "use_check_card", "postpaid_transport",
                         "same_password_as_account", "card_usage_alert"]:
            user_lower = user_input.lower().strip()
            for pattern in positive_patterns:
                if pattern in user_lower:
                    return "true"
            for pattern in negative_patterns:
                if pattern in user_lower:
                    return "false"
        
        if field_key not in patterns:
            return None
        
        for pattern in patterns[field_key]:
            match = re.search(pattern, user_input)
            if match:
                # group(0)는 전체 매치, group(1)은 첫 번째 캡처 그룹
                # 캡처 그룹이 있는지 확인
                if match.groups():
                    value = match.group(1).strip()
                else:
                    value = match.group(0).strip()
                
                # 전화번호의 경우 하이픈 형식으로 변환
                if field_key in ["customer_phone", "phone_number"]:
                    # 숫자만 추출
                    numbers_only = re.sub(r'\D', '', value)
                    if len(numbers_only) == 11 and numbers_only.startswith('010'):
                        return f"{numbers_only[:3]}-{numbers_only[3:7]}-{numbers_only[7:]}"
                    elif len(numbers_only) == 10:
                        return f"{numbers_only[:3]}-{numbers_only[3:6]}-{numbers_only[6:]}"
                return value
        
        return None
    
    async def process_slot_filling(
        self, 
        user_input: str, 
        required_fields: List[Dict[str, Any]], 
        collected_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """종합적인 Slot Filling 처리"""
        
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


def convert_korean_number(text: str) -> Optional[int]:
    """한국어 숫자 표현을 숫자로 변환 (만원 단위)"""
    try:
        # 기본 텍스트 정리
        text = text.strip().replace(",", "").replace(" ", "")
        
        # 한글 숫자를 아라비아 숫자로 변환
        korean_nums = {
            "일": "1", "이": "2", "삼": "3", "사": "4", "오": "5",
            "육": "6", "칠": "7", "팔": "8", "구": "9", "십": "10",
            "백": "100", "천": "1000", "만": "10000", "억": "100000000"
        }
        
        # 특수 케이스 처리 (일억, 일천만 등)
        text = text.replace("일억", "1억").replace("일천", "1천").replace("일백", "1백")
        
        # 단순 한글 숫자 케이스 (오백만원, 삼천만원 등)
        simple_patterns = {
            "오백만원": 500, "오백만": 500,
            "삼백만원": 300, "삼백만": 300,
            "이백만원": 200, "이백만": 200,
            "백만원": 100, "백만": 100,
            "오천만원": 5000, "오천만": 5000,
            "삼천만원": 3000, "삼천만": 3000,
            "이천만원": 2000, "이천만": 2000,
            "천만원": 1000, "천만": 1000,
            "구십만원": 90, "구십만": 90,
            "팔십만원": 80, "팔십만": 80,
            "칠십만원": 70, "칠십만": 70,
            "육십만원": 60, "육십만": 60,
            "오십만원": 50, "오십만": 50,
            "사십만원": 40, "사십만": 40,
            "삼십만원": 30, "삼십만": 30,
            "이십만원": 20, "이십만": 20,
            "십만원": 10, "십만": 10
        }
        
        # 정확한 매칭 우선
        for pattern, value in simple_patterns.items():
            if text == pattern:
                return value
        
        # 만원 단위 제거
        text = text.replace("만원", "").replace("만", "")
        
        # 복잡한 케이스 처리
        if "억" in text:
            parts = text.split("억")
            try:
                # 숫자로 변환 시도
                if parts[0].isdigit():
                    result = int(parts[0]) * 10000
                else:
                    # 한글 숫자인 경우
                    result = 10000  # 기본값 1억
            except:
                result = 10000
            
            if len(parts) > 1 and parts[1]:
                if parts[1].isdigit():
                    result += int(parts[1])
                elif "천" in parts[1]:
                    sub_parts = parts[1].split("천")
                    if sub_parts[0].isdigit():
                        result += int(sub_parts[0]) * 1000
                    else:
                        result += 1000
            return result
            
        elif "천" in text:
            parts = text.split("천")
            if parts[0].isdigit():
                result = int(parts[0]) * 1000
            else:
                # "오천" -> 5000
                num_map = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, 
                          "육": 6, "칠": 7, "팔": 8, "구": 9}
                result = num_map.get(parts[0], 1) * 1000
                
            if len(parts) > 1 and parts[1]:
                if "백" in parts[1]:
                    hundred_parts = parts[1].split("백")
                    if hundred_parts[0].isdigit():
                        result += int(hundred_parts[0]) * 100
                    else:
                        result += num_map.get(hundred_parts[0], 1) * 100
                elif parts[1].isdigit():
                    result += int(parts[1])
            return result
            
        elif "백" in text:
            parts = text.split("백")
            if parts[0].isdigit():
                result = int(parts[0]) * 100
            else:
                num_map = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, 
                          "육": 6, "칠": 7, "팔": 8, "구": 9}
                result = num_map.get(parts[0], 1) * 100
                
            if len(parts) > 1 and parts[1]:
                if parts[1].isdigit():
                    result += int(parts[1])
            return result
        else:
            # 일반 숫자
            if text.isdigit():
                return int(text)
            else:
                # 한글 숫자 단독 (오, 십 등)
                num_map = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, 
                          "육": 6, "칠": 7, "팔": 8, "구": 9, "십": 10}
                return num_map.get(text, None)
    except Exception as e:
        print(f"[convert_korean_number] Error converting '{text}': {e}")
        return None


# 전역 인스턴스
entity_agent = EntityRecognitionAgent()