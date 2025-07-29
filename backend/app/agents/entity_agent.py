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
        self.similarity_prompt = self._get_similarity_matching_prompt()
        # entity_extraction_prompts.yaml 파일 로드
        config_dir = Path(__file__).parent.parent / "config"
        self.entity_prompts = load_yaml_file(str(config_dir / "entity_extraction_prompts.yaml"))
        
        # 유사도 임계값 설정
        self.similarity_threshold = 0.7  # 70% 이상의 유사도만 매칭으로 인정
        self.retry_threshold = 0.3      # 30% 미만은 재질문 필요
    
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
    
    def _get_similarity_matching_prompt(self) -> str:
        """의미 기반 유사도 매칭 프롬프트"""
        return """당신은 사용자의 입력과 선택지 간의 의미적 유사성을 판단하는 전문가입니다.

**작업:**
사용자 입력: "{user_input}"
필드 정보: {field_info}
선택 가능한 값들: {choices}

**분석 규칙:**
1. 사용자 입력의 의도와 의미를 정확히 파악하세요
2. 각 선택지와의 의미적 유사성을 분석하세요
3. 문맥을 고려하여 가장 적절한 매칭을 찾으세요
4. 동의어, 유사 표현, 축약어 등을 고려하세요

**유사도 점수 기준:**
- 1.0: 완전히 동일하거나 명확히 같은 의미
- 0.8-0.9: 매우 유사하며 같은 의도로 볼 수 있음
- 0.6-0.7: 유사하나 약간의 차이가 있음
- 0.4-0.5: 관련은 있으나 차이가 큼
- 0.0-0.3: 거의 관련 없음

**출력 형식:**
{{
  "best_match": "가장 유사한 선택지",
  "similarity_score": 0.0-1.0,
  "reasoning": "매칭 이유 설명",
  "alternative_matches": [
    {{"value": "대안 선택지", "score": 0.0-1.0}}
  ]
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
3. boolean 타입: 명시적 언급만
   - 긍정: 네/예/응/어/그래/좋아/알겠/등록/추가/신청/할게/해줘/해주세요/맞아/확인 → true
   - 부정: 아니/아니요/안/싫/필요없/안할/안해 → false
   - withdrawal_account_registration의 경우 "등록해줘", "추가해줘" 등도 true로 처리
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
                    if field_def['type'] == 'number':
                        # 숫자 타입 처리
                        if isinstance(value, (int, float)):
                            # 이미 숫자인 경우 그대로 사용
                            processed_entities[field_key] = int(value)
                            print(f"[EntityAgent] {field_key}: already number = {value}")
                        elif isinstance(value, str):
                            # 문자열인 경우 변환 시도
                            converted = convert_korean_number(value)
                            if converted is not None:
                                processed_entities[field_key] = converted
                                print(f"[EntityAgent] {field_key}: converted '{value}' → {converted}")
                            else:
                                try:
                                    processed_entities[field_key] = int(value)
                                    print(f"[EntityAgent] {field_key}: parsed '{value}' → {int(value)}")
                                except:
                                    print(f"[EntityAgent] {field_key}: failed to convert '{value}'")
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
    
    async def extract_entities_with_similarity(
        self, 
        user_input: str, 
        required_fields: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """사용자 입력에서 엔티티 추출 - 유사도 매칭 포함"""
        print(f"[EntityAgent] extract_entities_with_similarity called with {len(required_fields)} fields: {[f['key'] for f in required_fields]}")
        
        # 1. 먼저 기존 방식으로 추출 시도
        extraction_result = await self.extract_entities(user_input, required_fields)
        extracted_entities = extraction_result.get("extracted_entities", {})
        
        # 2. choice 타입 필드 중 추출되지 않은 것들에 대해 유사도 매칭 시도
        similarity_messages = []
        for field in required_fields:
            field_key = field['key']
            
            # 이미 추출된 필드는 스킵
            if field_key in extracted_entities:
                continue
                
            # choice 타입 필드에 대해서만 유사도 매칭
            if field.get('type') == 'choice' and field.get('choices'):
                similarity_result = await self.match_with_similarity(user_input, field)
                
                if similarity_result['matched']:
                    # 유사도 매칭 성공
                    extracted_entities[field_key] = similarity_result['value']
                    print(f"[EntityAgent] Similarity matched {field_key}: {similarity_result['value']} (score: {similarity_result['score']})")
                elif similarity_result.get('need_retry') and similarity_result.get('message'):
                    # 재질문 필요
                    similarity_messages.append(similarity_result['message'])
        
        # 3. 결과 반환
        result = {
            "extracted_entities": extracted_entities,
            "confidence": extraction_result.get("confidence", 0.8),
            "unclear_fields": [f['key'] for f in required_fields if f['key'] not in extracted_entities],
            "reasoning": extraction_result.get("reasoning", ""),
            "similarity_messages": similarity_messages
        }
        
        # 유사도 메시지가 있으면 confidence 조정
        if similarity_messages:
            result["confidence"] = min(result["confidence"], 0.6)
            result["need_clarification"] = True
        
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
            "transfer_limit_per_time": [
                r"일회\s*([가-힣]+)만원",  # "일회 사백만원"
                r"1회\s*([가-힣]+)만원",   # "1회 사백만원"
                r"일회\s*(\d+)(?:만원)?",  # "일회 400만원"
                r"1회\s*이체\s*한도\s*(\d+)(?:만원)?",
                r"1회\s*한도\s*(\d+)(?:만원)?",
                r"회당\s*(\d+)(?:만원)?",
                r"1회\s*(\d+)(?:만원)?",
                r"한번에\s*(\d+)(?:만원)?"
            ],
            "transfer_limit_per_day": [
                r"일일\s*([가-힣]+)만원",  # "일일 천만원"
                r"1일\s*([가-힣]+)만원",   # "1일 천만원"
                r"일일\s*(\d+)(?:만원)?",  # "일일 1000만원"
                r"1일\s*이체\s*한도\s*(\d+)(?:만원)?",
                r"일일\s*한도\s*(\d+)(?:만원)?",
                r"하루\s*(\d+)(?:만원)?",
                r"1일\s*(\d+)(?:만원)?",
                r"일당\s*(\d+)(?:만원)?"
            ],
            "ib_daily_limit": [
                r"(\d+)만원?",
                r"(\d+)천만원?",
                r"한도\s*(\d+)",
                r"(\d+)원?"
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
        positive_patterns = ["네", "예", "응", "맞아", "맞습니다", "확인", "동의", "ok", "okay", "ㅇㅇ", "ㅇㅋ", 
                           "어", "그래", "좋아", "알겠", "등록", "추가", "신청", "할게", "해줘", "해주세요"]
        negative_patterns = ["아니", "아뇨", "아니요", "아니에요", "안", "싫", "no", "ㄴㄴ", "필요없", "안할"]
        
        # Boolean 타입 필드 처리
        if field_key in ["confirm_personal_info", "use_lifelong_account", "use_internet_banking", 
                         "additional_withdrawal_account", "use_check_card", "postpaid_transport",
                         "same_password_as_account", "card_usage_alert", "withdrawal_account_registration",
                         "important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction",
                         "card_password_same_as_account", "limit_account_agreement"]:
            user_lower = user_input.lower().strip()
            
            # 부정 패턴을 먼저 확인 (더 구체적인 패턴)
            for pattern in negative_patterns:
                if pattern in user_lower:
                    # "할게"가 포함되어 있어도 "안할게"면 false
                    if pattern == "안할" and "안할" in user_lower:
                        return "false"
                    # "필요없"이 포함되어 있으면 false
                    elif pattern == "필요없" and "필요없" in user_lower:
                        return "false"
                    elif pattern in user_lower and pattern not in ["안할", "필요없"]:
                        return "false"
            
            # 긍정 패턴 확인
            for pattern in positive_patterns:
                if pattern in user_lower:
                    return "true"
        
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
                
                # 이체한도의 경우 한국어 숫자를 변환
                if field_key in ["transfer_limit_per_time", "transfer_limit_per_day"]:
                    # convert_korean_number 함수 사용
                    converted = convert_korean_number(value)
                    if converted is not None:
                        return str(converted)
                    
                    # 일반 숫자 추출 시도
                    num_match = re.search(r'(\d+)', value)
                    if num_match:
                        return num_match.group(1)
                    
                return value
        
        return None
    
    async def match_with_similarity(
        self,
        user_input: str,
        field: Dict[str, Any]
    ) -> Dict[str, Any]:
        """LLM을 사용한 의미 기반 유사도 매칭"""
        
        # choice 타입이 아니거나 choices가 없으면 스킵
        if field.get('type') != 'choice' or not field.get('choices'):
            return {
                "matched": False,
                "value": None,
                "score": 0.0,
                "need_retry": False
            }
        
        field_info = {
            "key": field['key'],
            "display_name": field.get('display_name', field['key']),
            "description": field.get('description', '')
        }
        
        prompt = self.similarity_prompt.format(
            user_input=user_input,
            field_info=json.dumps(field_info, ensure_ascii=False),
            choices=json.dumps(field['choices'], ensure_ascii=False)
        )
        
        # JSON 응답을 위한 추가 지시
        prompt += "\n\n반드시 위의 JSON 형식으로 응답해주세요."
        
        try:
            response = await json_llm.ainvoke([HumanMessage(content=prompt)])
            
            # JSON 파싱
            content = response.content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            
            result = json.loads(content.strip())
            
            best_match = result.get("best_match")
            similarity_score = result.get("similarity_score", 0.0)
            reasoning = result.get("reasoning", "")
            
            print(f"[EntityAgent] Similarity matching for '{user_input}': {best_match} (score: {similarity_score})")
            print(f"[EntityAgent] Reasoning: {reasoning}")
            
            # 유사도 기반 판단
            if similarity_score >= self.similarity_threshold:
                # 매칭 성공
                return {
                    "matched": True,
                    "value": best_match,
                    "score": similarity_score,
                    "need_retry": False,
                    "reasoning": reasoning
                }
            elif similarity_score < self.retry_threshold:
                # 유사도가 너무 낮음 - 재질문 필요
                return {
                    "matched": False,
                    "value": None,
                    "score": similarity_score,
                    "need_retry": True,
                    "reasoning": reasoning,
                    "message": f"입력하신 '{user_input}'는 선택 가능한 옵션과 일치하지 않습니다. {', '.join(field['choices'])} 중에서 선택해주세요."
                }
            else:
                # 애매한 경우 - 추가 확인 필요
                alternatives = result.get("alternative_matches", [])
                if alternatives:
                    alt_text = ", ".join([f"{alt['value']}({alt['score']:.1f})" for alt in alternatives[:2]])
                    message = f"'{user_input}'를 '{best_match}'로 이해했습니다. 맞으신가요? 혹시 {alt_text} 중 하나를 말씀하신 건가요?"
                else:
                    message = f"'{user_input}'를 '{best_match}'로 이해했습니다. 맞으신가요?"
                
                return {
                    "matched": False,
                    "value": best_match,
                    "score": similarity_score,
                    "need_retry": True,
                    "reasoning": reasoning,
                    "message": message
                }
                
        except Exception as e:
            print(f"[EntityAgent] Similarity matching error: {e}")
            return {
                "matched": False,
                "value": None,
                "score": 0.0,
                "need_retry": True,
                "message": f"{field.get('display_name', field['key'])}을(를) 다시 말씀해주세요. 선택 가능한 옵션: {', '.join(field['choices'])}"
            }
    
    async def process_slot_filling(
        self, 
        user_input: str, 
        required_fields: List[Dict[str, Any]], 
        collected_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """종합적인 Slot Filling 처리 - 유사도 매칭 포함"""
        print(f"[EntityAgent] process_slot_filling called with {len(required_fields)} fields: {[f['key'] for f in required_fields]}")
        
        # 1단계: LLM 기반 엔티티 추출 (유사도 매칭 포함)
        extraction_result = await self.extract_entities_with_similarity(user_input, required_fields)
        extracted_entities = extraction_result.get("extracted_entities", {})
        similarity_messages = extraction_result.get("similarity_messages", [])
        
        # 2단계: 패턴 기반 보완 (LLM과 유사도 매칭이 놓친 정보)
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
        
        result = {
            "collected_info": new_collected_info,
            "extracted_entities": extracted_entities,
            "valid_entities": valid_entities,
            "invalid_entities": invalid_entities,
            "missing_fields": missing_fields,
            "extraction_confidence": extraction_result.get("confidence", 0.0),
            "is_complete": len(missing_fields) == 0,
            "similarity_messages": similarity_messages
        }
        
        # 유사도 매칭 메시지가 있으면 need_clarification 추가
        if similarity_messages:
            result["need_clarification"] = True
            result["clarification_message"] = "\n".join(similarity_messages)
        
        return result
    
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
            "사백만원": 400, "사백만": 400,
            "삼백만원": 300, "삼백만": 300,
            "이백만원": 200, "이백만": 200,
            "백만원": 100, "백만": 100,
            "오천만원": 5000, "오천만": 5000,
            "사천만원": 4000, "사천만": 4000,
            "삼천만원": 3000, "삼천만": 3000,
            "이천만원": 2000, "이천만": 2000,
            "천만원": 1000, "천만": 1000,
            "구백만원": 900, "구백만": 900,
            "팔백만원": 800, "팔백만": 800,
            "칠백만원": 700, "칠백만": 700,
            "육백만원": 600, "육백만": 600,
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