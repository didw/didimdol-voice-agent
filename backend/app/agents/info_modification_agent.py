# backend/app/agents/info_modification_agent.py
"""
정보 수정/변경 Agent - 고객의 자연스러운 수정 요청을 지능적으로 파악하고 처리
"""

import re
from typing import Dict, Any, Optional, List, Tuple
from ..graph.chains import generative_llm


def convert_korean_to_digits(text: str) -> str:
    """한국어 숫자 표현을 아라비아 숫자로 변환"""
    korean_numbers = {
        '영': '0', '공': '0',
        '일': '1', '하나': '1',
        '이': '2', '둘': '2',
        '삼': '3', '셋': '3',
        '사': '4', '넷': '4',
        '오': '5', '다섯': '5',
        '육': '6', '여섯': '6',
        '칠': '7', '일곱': '7',
        '팔': '8', '여덟': '8',
        '구': '9', '아홉': '9'
    }
    
    # 한국어 숫자를 아라비아 숫자로 변환
    result = text
    for korean, digit in korean_numbers.items():
        result = result.replace(korean, digit)
    
    return result


class InfoModificationAgent:
    """
    고객의 자연스러운 수정 요청을 파악하고 적절한 필드를 수정하는 Agent
    
    기능:
    1. 자연어로 표현된 수정 요청 분석
    2. 컨텍스트 기반 필드 매칭
    3. 기존 정보와 비교하여 수정 대상 추론
    4. 데이터 검증 및 형식 변환
    """
    
    def __init__(self):
        self.field_patterns = {
            # 전화번호 관련 패턴
            "customer_phone": [
                r"뒷번호\s*(\d{4})",
                r"뒤\s*(\d{4})",
                r"마지막\s*(\d{4})",
                r"끝번호\s*(\d{4})",
                r"010[-\s]*(\d{3,4})[-\s]*(\d{4})",
                r"(\d{3})[-\s]*(\d{4})[-\s]*(\d{4})",
                r"전화번호\s*(010[-\s]*\d{3,4}[-\s]*\d{4})",
                r"휴대폰\s*(010[-\s]*\d{3,4}[-\s]*\d{4})",
                r"연락처\s*(010[-\s]*\d{3,4}[-\s]*\d{4})"
            ],
            
            # 이름 관련 패턴
            "customer_name": [
                r"이름\s*([가-힣]{2,4})",
                r"성함\s*([가-힣]{2,4})",
                r"이름은\s*([가-힣]{2,4})",
                r"([가-힣]{2,4})\s*입니다",
                r"([가-힣]{2,4})\s*이에요",
                r"([가-힣]{2,4})\s*예요",
                r"([가-힣]{2,4})\s*라고\s*해주세요"
            ]
        }
        
        self.context_keywords = {
            "customer_phone": ["전화", "연락처", "휴대폰", "번호", "뒷번호", "뒤", "마지막", "끝번호"],
            "customer_name": ["이름", "성함", "명의", "고객명"],
            "confirm_personal_info": ["확인", "동의", "맞다", "틀리다", "다르다"],
            "use_lifelong_account": ["평생계좌", "평생", "계좌번호"],
            "use_internet_banking": ["인터넷뱅킹", "인뱅", "온라인뱅킹"],
            "use_check_card": ["체크카드", "카드", "체크"]
        }
    
    async def analyze_modification_request(
        self, 
        user_input: str, 
        current_info: Dict[str, Any],
        required_fields: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        사용자의 수정 요청을 분석하고 적절한 필드 수정을 수행
        
        Args:
            user_input: 사용자의 자연어 입력
            current_info: 현재 수집된 정보
            required_fields: 필드 정의 정보
            
        Returns:
            {
                "modified_fields": {"field_key": "new_value"},
                "confidence": float,
                "reasoning": str,
                "suggestions": List[str]
            }
        """
        print(f"[InfoModAgent] Analyzing: '{user_input}'")
        print(f"[InfoModAgent] Converted: '{convert_korean_to_digits(user_input)}'")
        print(f"[InfoModAgent] Current info: {current_info}")
        
        # 1. 패턴 기반 매칭
        pattern_matches = self._extract_using_patterns(user_input, current_info)
        print(f"[InfoModAgent] Pattern matches: {pattern_matches}")
        
        # 2. 컨텍스트 기반 추론
        context_matches = self._infer_from_context(user_input, current_info)
        print(f"[InfoModAgent] Context matches: {context_matches}")
        
        # 3. LLM 기반 지능적 분석
        llm_analysis = await self._analyze_with_llm(user_input, current_info, required_fields)
        print(f"[InfoModAgent] LLM analysis: {llm_analysis}")
        
        # 4. 결과 통합 및 검증
        final_result = self._merge_and_validate_results(
            pattern_matches, context_matches, llm_analysis, current_info
        )
        
        print(f"[InfoModAgent] Final result: {final_result}")
        return final_result
    
    def _extract_using_patterns(self, user_input: str, current_info: Dict[str, Any] = None) -> Dict[str, Any]:
        """패턴 기반 정보 추출"""
        matches = {}
        if current_info is None:
            current_info = {}
        
        # 한국어 숫자를 아라비아 숫자로 변환한 버전도 생성
        converted_input = convert_korean_to_digits(user_input)
        
        # 대조 표현 패턴 처리 (예: "오육칠팔이 아니라 이이오구야")
        contrast_patterns = [
            r"([\d가-힣]+)\s*(이|가)?\s*아니라\s*([\d가-힣]+)",  # "5678이 아니라 2259"
            r"([\d가-힣]+)\s*(이|가)?\s*아니고\s*([\d가-힣]+)",  # "5678이 아니고 2259"
            r"([\d가-힣]+)\s*말고\s*([\d가-힣]+)",  # "5678 말고 2259"
        ]
        
        # 대조 표현 확인
        for pattern in contrast_patterns:
            # 먼저 원본 입력에서 확인
            for test_input in [user_input, converted_input]:
                match = re.search(pattern, test_input, re.IGNORECASE)
                if match:
                    # 대조 표현이 있으면 뒤의 값만 추출
                    old_value = match.group(1)
                    new_value = match.group(len(match.groups()))  # 마지막 그룹
                    
                    # 한국어 숫자를 아라비아 숫자로 변환
                    old_value_digits = convert_korean_to_digits(old_value)
                    new_value_digits = convert_korean_to_digits(new_value)
                    
                    # 숫자만 추출 (끝의 조사 제거)
                    old_digits_match = re.search(r'(\d+)', old_value_digits)
                    new_digits_match = re.search(r'(\d+)', new_value_digits)
                    
                    if old_digits_match and new_digits_match:
                        old_digits = old_digits_match.group(1)
                        new_digits = new_digits_match.group(1)
                        
                        print(f"[InfoModAgent] Contrast pattern detected: '{old_value}' ({old_digits}) → '{new_value}' ({new_digits})")
                        
                        # 4자리 숫자인 경우 전화번호 뒷자리로 간주
                        if re.match(r'^\d{4}$', new_digits):
                            # 기존 전화번호에서 뒷자리만 변경
                            current_phone = current_info.get("customer_phone", "010-1234-5678")
                            phone_parts = current_phone.split("-")
                            if len(phone_parts) == 3:
                                new_phone = f"{phone_parts[0]}-{phone_parts[1]}-{new_digits}"
                            else:
                                new_phone = f"010-xxxx-{new_digits}"
                            matches["customer_phone"] = new_phone
                            print(f"[InfoModAgent] Phone number tail change: {current_phone} → {new_phone}")
                        
                        # 대조 표현을 찾았으면 결과 반환
                        if matches:
                            return {"extracted": matches, "method": "contrast_pattern"}
                    break
        
        # 원본과 변환된 버전 모두에서 패턴 매칭 시도
        for test_input in [user_input, converted_input]:
            for field_key, patterns in self.field_patterns.items():
                for pattern in patterns:
                    match = re.search(pattern, test_input, re.IGNORECASE)
                    if match:
                        if field_key == "customer_phone":
                            # 전화번호 특별 처리
                            phone_value = self._process_phone_match(match, test_input)
                            if phone_value:
                                matches[field_key] = phone_value
                        elif field_key == "customer_name":
                            # 이름 추출
                            name_value = match.group(1).strip()
                            if len(name_value) >= 2:
                                matches[field_key] = name_value
                        break
        
        return {"extracted": matches, "method": "pattern"}
    
    def _process_phone_match(self, match: re.Match, user_input: str) -> Optional[str]:
        """전화번호 매칭 특별 처리"""
        groups = match.groups()
        
        # 뒷번호 4자리인 경우
        if len(groups) == 1 and len(groups[0]) == 4:
            if "뒷번호" in user_input or "뒤" in user_input or "마지막" in user_input:
                # 010-xxxx-{4자리}로 가정
                return f"010-xxxx-{groups[0]}"
        
        # 전체 번호인 경우
        elif len(groups) >= 2:
            # 010-xxxx-xxxx 형태로 조합
            if len(groups) == 2:
                return f"010-{groups[0]}-{groups[1]}"
            elif len(groups) == 3:
                return f"{groups[0]}-{groups[1]}-{groups[2]}"
        
        return None
    
    def _infer_from_context(self, user_input: str, current_info: Dict[str, Any]) -> Dict[str, Any]:
        """컨텍스트 기반 필드 추론"""
        scores = {}
        
        for field_key, keywords in self.context_keywords.items():
            score = 0
            for keyword in keywords:
                if keyword in user_input:
                    score += 1
            
            if score > 0:
                scores[field_key] = score / len(keywords)
        
        # 가장 높은 점수의 필드 선택
        if scores:
            best_field = max(scores.keys(), key=lambda k: scores[k])
            return {"inferred_field": best_field, "confidence": scores[best_field], "method": "context"}
        
        return {"method": "context"}
    
    async def _analyze_with_llm(
        self, 
        user_input: str, 
        current_info: Dict[str, Any], 
        required_fields: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """LLM을 사용한 지능적 분석"""
        
        if not generative_llm:
            return {"method": "llm", "error": "LLM not available"}
        
        # 필드 정보 요약
        field_descriptions = []
        for field in required_fields:
            field_descriptions.append(f"- {field['key']} ({field.get('display_name', field['key'])}): {field.get('description', 'N/A')}")
        
        prompt = f"""
고객의 정보 수정 요청을 분석해주세요.

현재 고객 정보:
{self._format_current_info(current_info)}

가능한 필드들:
{chr(10).join(field_descriptions)}

고객 발화: "{user_input}"

중요: 한국어 숫자 표현을 정확히 인식해주세요:
- 영/공 → 0, 일 → 1, 이 → 2, 삼 → 3, 사 → 4, 오 → 5, 육 → 6, 칠 → 7, 팔 → 8, 구 → 9
- 예: "이이칠구" → "2279", "오육칠팔" → "5678"

특히 주의할 점:
- "~가 아니라 ~야" 형태는 대조/수정을 의미합니다
- "오육칠팔이 아니라 이이오구야" → 기존 5678을 2259로 수정
- 현재 정보와 다른 부분만 수정하면 됩니다

분석해야 할 사항:
1. 고객이 어떤 정보를 수정하려고 하는지
2. 새로운 값이 무엇인지 (한국어 숫자는 아라비아 숫자로 변환)
3. 추론의 근거

답변 형식 (JSON):
{{
    "target_field": "수정하려는 필드 키",
    "new_value": "새로운 값",
    "confidence": 0.0~1.0,
    "reasoning": "추론 근거"
}}

예시:
- "뒷번호 0987이야" → {{"target_field": "customer_phone", "new_value": "010-xxxx-0987", "confidence": 0.9, "reasoning": "뒷번호 4자리는 전화번호의 마지막 부분"}}
- "이름은 김철수야" → {{"target_field": "customer_name", "new_value": "김철수", "confidence": 0.95, "reasoning": "명시적으로 이름을 제공"}}
- "오육칠팔이 아니라 이이오구야" → {{"target_field": "customer_phone", "new_value": "010-xxxx-2259", "confidence": 0.95, "reasoning": "기존 뒷번호 5678을 2259로 수정 요청"}}
"""

        try:
            from langchain_core.messages import HumanMessage
            response = await generative_llm.ainvoke([HumanMessage(content=prompt)])
            
            # JSON 응답 파싱
            content = response.content.strip()
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "").strip()
            
            import json
            result = json.loads(content)
            result["method"] = "llm"
            return result
            
        except Exception as e:
            print(f"[InfoModAgent] LLM analysis error: {e}")
            return {"method": "llm", "error": str(e)}
    
    def _format_current_info(self, current_info: Dict[str, Any]) -> str:
        """현재 정보를 읽기 쉽게 포맷"""
        formatted = []
        for key, value in current_info.items():
            formatted.append(f"- {key}: {value}")
        return "\n".join(formatted) if formatted else "- (정보 없음)"
    
    def _merge_and_validate_results(
        self, 
        pattern_matches: Dict[str, Any], 
        context_matches: Dict[str, Any], 
        llm_analysis: Dict[str, Any],
        current_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """결과 통합 및 검증"""
        
        modified_fields = {}
        confidence = 0.0
        reasoning_parts = []
        
        # 1. 패턴 매칭 결과 우선 적용
        if "extracted" in pattern_matches and pattern_matches["extracted"]:
            for field, value in pattern_matches["extracted"].items():
                modified_fields[field] = value
                confidence = max(confidence, 0.8)
                reasoning_parts.append(f"패턴 매칭: {field} = {value}")
        
        # 2. LLM 분석 결과 적용 (패턴 매칭이 없거나, LLM이 더 정확한 경우만)
        if "target_field" in llm_analysis and "new_value" in llm_analysis:
            field = llm_analysis["target_field"]
            value = llm_analysis["new_value"]
            
            # 패턴 매칭 결과가 이미 있으면 패턴 매칭 우선 (특히 전화번호의 경우)
            if field in modified_fields and (field == "customer_phone" or llm_analysis.get("confidence", 0.5) < 0.95):
                reasoning_parts.append(f"LLM 분석 (패턴 매칭 우선): {llm_analysis.get('reasoning', 'N/A')}")
            else:
                # 전화번호 특별 처리 - 기존 정보와 조합
                if field == "customer_phone" and value.startswith("010-xxxx-"):
                    existing_phone = current_info.get("customer_phone", "")
                    if existing_phone and existing_phone.startswith("010-"):
                        # 기존 번호의 중간 부분 유지
                        parts = existing_phone.split("-")
                        if len(parts) == 3:
                            new_last_4 = value.split("-")[-1]
                            value = f"{parts[0]}-{parts[1]}-{new_last_4}"
                
                modified_fields[field] = value
                confidence = max(confidence, llm_analysis.get("confidence", 0.5))
                reasoning_parts.append(f"LLM 분석: {llm_analysis.get('reasoning', 'N/A')}")
        
        # 3. 컨텍스트 추론 보조 활용
        if "inferred_field" in context_matches and not modified_fields:
            # 다른 방법으로 값을 찾지 못한 경우에만 컨텍스트 사용
            reasoning_parts.append(f"컨텍스트 추론: {context_matches['inferred_field']} 가능성 높음")
        
        return {
            "modified_fields": modified_fields,
            "confidence": confidence,
            "reasoning": " | ".join(reasoning_parts) if reasoning_parts else "수정할 정보를 찾지 못함",
            "suggestions": self._generate_suggestions(modified_fields, current_info)
        }
    
    def _generate_suggestions(self, modified_fields: Dict[str, Any], current_info: Dict[str, Any]) -> List[str]:
        """수정 제안사항 생성"""
        suggestions = []
        
        for field, new_value in modified_fields.items():
            old_value = current_info.get(field, "없음")
            
            if field == "customer_phone":
                suggestions.append(f"연락처를 {old_value}에서 {new_value}(으)로 변경하시겠어요?")
            elif field == "customer_name":
                suggestions.append(f"성함을 {old_value}에서 {new_value}(으)로 변경하시겠어요?")
            else:
                display_name = self._get_field_display_name(field)
                suggestions.append(f"{display_name}을(를) '{old_value}'에서 '{new_value}'로 변경하시겠어요?")
        
        return suggestions
    
    def _get_field_display_name(self, field_key: str) -> str:
        """필드 키를 한국어 표시명으로 변환"""
        display_names = {
            "customer_name": "고객명",
            "customer_phone": "연락처",
            "confirm_personal_info": "개인정보 확인",
            "use_lifelong_account": "평생계좌 등록",
            "use_internet_banking": "인터넷뱅킹 가입",
            "use_check_card": "체크카드 신청"
        }
        return display_names.get(field_key, field_key)


# 전역 인스턴스
info_modification_agent = InfoModificationAgent()