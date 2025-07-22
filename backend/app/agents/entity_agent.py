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
        """사용자 입력에서 엔티티 추출 - YAML 프롬프트 우선 사용"""
        
        # 각 필드별로 개별 추출 수행
        all_extracted_entities = {}
        extraction_details = []
        
        for field in required_fields:
            field_key = field['key']
            
            # YAML에서 해당 필드의 프롬프트 가져오기
            if field_key in self.entity_prompts:
                entity_config = self.entity_prompts[field_key]
                prompt_template = entity_config.get('prompt', '')
                
                # 프롬프트에 user_input 삽입
                specific_prompt = prompt_template.format(user_input=user_input)
                
                # 예시 추가 (있는 경우)
                if 'examples' in entity_config:
                    specific_prompt += "\n\n예시:"
                    for example in entity_config['examples']:
                        specific_prompt += f"\n입력: {example['input']} → 출력: {example['output']}"
                
                print(f"[EntityAgent] Using YAML prompt for {field_key}")
            else:
                # YAML에 없으면 scenario JSON의 extraction_prompt 사용
                if field.get('extraction_prompt'):
                    specific_prompt = f"사용자 발화: \"{user_input}\"\n\n{field['extraction_prompt']}"
                    print(f"[EntityAgent] Using scenario extraction_prompt for {field_key}")
                else:
                    # 둘 다 없으면 기본 프롬프트 사용
                    specific_prompt = f"""사용자 발화에서 {field['display_name']}을(를) 추출하세요.
필드 타입: {field['type']}
{"선택지: " + ", ".join(field['choices']) if field.get('choices') else ""}

사용자 발화: "{user_input}"

추출된 값 (없으면 null):"""
                    print(f"[EntityAgent] Using fallback prompt for {field_key}")
            
            try:
                # 개별 필드 추출 수행 (일반 LLM 사용)
                response = await generative_llm.ainvoke([HumanMessage(content=specific_prompt)])
                content = response.content.strip()
                
                # JSON이 아닌 단순 텍스트 응답 처리
                if content and content != "null" and content != "None":
                    # 따옴표 제거
                    if content.startswith('"') and content.endswith('"'):
                        content = content[1:-1]
                    
                    # 타입별 변환
                    if field['type'] == 'boolean':
                        if content.lower() in ['true', '네', '예', '맞습니다', '동의합니다']:
                            all_extracted_entities[field_key] = True
                        elif content.lower() in ['false', '아니요', '아니에요', '동의하지 않습니다']:
                            all_extracted_entities[field_key] = False
                    elif field['type'] == 'number':
                        try:
                            # 숫자 변환 시도
                            if isinstance(content, str):
                                converted = convert_korean_number(content)
                                if converted is not None:
                                    all_extracted_entities[field_key] = converted
                                else:
                                    all_extracted_entities[field_key] = int(content)
                            else:
                                all_extracted_entities[field_key] = int(content)
                        except:
                            pass
                    elif field['type'] == 'choice':
                        # 선택지 확인
                        if content in field.get('choices', []):
                            all_extracted_entities[field_key] = content
                    else:
                        # text 타입
                        all_extracted_entities[field_key] = content
                    
                    extraction_details.append(f"{field_key}: {content} (YAML prompt used)")
                
            except Exception as e:
                print(f"[EntityAgent] Error extracting {field_key}: {e}")
                extraction_details.append(f"{field_key}: extraction failed - {str(e)}")
        
        # 전체 결과 구성
        result = {
            "extracted_entities": all_extracted_entities,
            "confidence": 0.8 if all_extracted_entities else 0.0,
            "unclear_fields": [f['key'] for f in required_fields if f['key'] not in all_extracted_entities],
            "reasoning": "YAML 프롬프트 기반 개별 필드 추출\n" + "\n".join(extraction_details)
        }
        
        print(f"[EntityAgent] Extraction result: {result}")
        return result
    
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
            ]
        }
        
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
        
        # 만원 단위 제거
        text = text.replace("만원", "").replace("만", "")
        
        # 억, 천만, 백만 등 처리
        if "억" in text:
            parts = text.split("억")
            result = int(parts[0]) * 10000
            if len(parts) > 1 and parts[1]:
                result += int(parts[1])
            return result
        elif "천" in text:
            # "5천", "3천5백" 등 처리
            parts = text.split("천")
            result = int(parts[0]) * 1000
            if len(parts) > 1 and parts[1]:
                if "백" in parts[1]:
                    hundred_parts = parts[1].split("백")
                    result += int(hundred_parts[0]) * 100
                    if len(hundred_parts) > 1 and hundred_parts[1]:
                        result += int(hundred_parts[1])
                else:
                    result += int(parts[1])
            return result
        elif "백" in text:
            parts = text.split("백")
            result = int(parts[0]) * 100
            if len(parts) > 1 and parts[1]:
                result += int(parts[1])
            return result
        else:
            # 일반 숫자
            return int(text)
    except:
        return None


# 전역 인스턴스
entity_agent = EntityRecognitionAgent()