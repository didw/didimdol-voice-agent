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
            "phone_number": [
                r"뒷번호\s*(\d{4})",
                r"뒷자리\s*(\d{4})",
                r"뒤\s*(\d{4})",
                r"마지막\s*(\d{4})",
                r"끝번호\s*(\d{4})",
                r"가운데가?\s*(\d{3,4})",
                r"중간이?\s*(\d{3,4})",
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
            ],
            
            # 이메일 관련 패턴
            "email": [
                r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
                r"이메일\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
                r"메일\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"
            ],
            # 주소 관련 패턴
            "address": [
                r"집\s*주소.+?([가-힣]+(?:동|로|길)\s*\d+)",   # 집주소는 ~ (주소 형태만)
                r"집이?\s+([가-힣]+(?:동|로|길)\s*\d+)",     # 집은/집이 ~ (주소 형태만)
            ],
            "work_address": [
                r"직장\s*주소.+?([가-힣]+(?:동|로|길)\s*\d+)",   # 직장주소는 ~ (주소 형태만)
                r"회사\s*주소.+?([가-힣]+(?:동|로|길)\s*\d+)",   # 회사주소는 ~ (주소 형태만)
                r"직장이?\s+([가-힣]+(?:동|로|길)\s*\d+)",       # 직장은/직장이 ~ (주소 형태만)
                r"회사가?\s+([가-힣]+(?:동|로|길)\s*\d+)",       # 회사가 ~ (주소 형태만)
            ],
            # 명시적 필드 언급이 없는 일반 주소 패턴은 별도로 처리
            "_generic_address": [
                r"([가-힣]+동\s*\d+)",  # 동 + 번지 (한글만)
                r"([가-힣]+로\s*\d+)",  # 로 + 번지 (한글만)
                r"([가-힣]+길\s*\d+)",  # 길 + 번지 (한글만)
            ]
        }
        
        self.context_keywords = {
            "phone_number": ["전화", "연락처", "휴대폰", "번호", "뒷번호", "뒷자리", "뒤", "마지막", "끝번호"],
            "customer_name": ["이름", "성함", "명의", "고객명"],
            "email": ["이메일", "메일", "전자메일", "@"],
            "address": ["주소", "집", "사는곳", "거주지", "집주소"],
            "work_address": ["직장", "회사", "근무지", "직장주소"],
            "confirm_personal_info": ["확인", "동의", "맞다", "틀리다", "다르다"],
            "use_lifelong_account": ["평생계좌", "평생", "계좌번호"],
            "use_internet_banking": ["인터넷뱅킹", "인뱅", "온라인뱅킹"],
            "use_check_card": ["체크카드", "카드", "체크"]
        }
    
    async def analyze_modification_request(
        self, 
        user_input: str, 
        current_info: Dict[str, Any],
        required_fields: List[Dict[str, Any]],
        modification_context: Optional[str] = None,
        correction_mode: bool = False
    ) -> Dict[str, Any]:
        """
        사용자의 수정 요청을 분석하고 적절한 필드 수정을 수행
        
        Args:
            user_input: 사용자의 자연어 입력
            current_info: 현재 수집된 정보
            required_fields: 필드 정의 정보
            modification_context: 현재 수정 컨텍스트 (이전에 수정하려던 필드)
            correction_mode: 수정 모드 활성화 여부 (대화 흐름 추론에 활용)
            
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
        print(f"[InfoModAgent] Modification context: {modification_context}")
        print(f"[InfoModAgent] Correction mode: {correction_mode}")
        
        # 1. 패턴 기반 매칭
        pattern_matches = self._extract_using_patterns(user_input, current_info, modification_context)
        print(f"[InfoModAgent] Pattern matches: {pattern_matches}")
        
        # 2. 컨텍스트 기반 추론
        context_matches = self._infer_from_context(user_input, current_info)
        print(f"[InfoModAgent] Context matches: {context_matches}")
        
        # 3. LLM 기반 지능적 분석
        llm_analysis = await self._analyze_with_llm(user_input, current_info, required_fields, modification_context, correction_mode)
        print(f"[InfoModAgent] LLM analysis: {llm_analysis}")
        
        # 4. 결과 통합 및 검증
        final_result = self._merge_and_validate_results(
            pattern_matches, context_matches, llm_analysis, current_info, modification_context, user_input
        )
        
        print(f"[InfoModAgent] Final result: {final_result}")
        return final_result
    
    def _extract_using_patterns(self, user_input: str, current_info: Dict[str, Any] = None, modification_context: Optional[str] = None) -> Dict[str, Any]:
        """패턴 기반 정보 추출"""
        matches = {}
        if current_info is None:
            current_info = {}
        
        # 한국어 숫자를 아라비아 숫자로 변환한 버전도 생성
        converted_input = convert_korean_to_digits(user_input)
        
        # 대조 표현 패턴 처리 (예: "오육칠팔이 아니라 이이오구야", "숭인동에서 수이동으로")
        contrast_patterns = [
            r"([\d가-힣]+)\s*(이|가)?\s*아니라\s*([\d가-힣]+)",  # "5678이 아니라 2259"
            r"([\d가-힣]+)\s*(이|가)?\s*아니고\s*([\d가-힣]+)",  # "5678이 아니고 2259"
            r"([\d가-힣]+)\s*말고\s*([\d가-힣]+)",  # "5678 말고 2259"
            r"([가-힣]+(?:동|로|길))[에서|을|를]\s*([가-힣]+(?:동|로|길))(?:으로|로)",  # "숭인동에서 수이동으로"
            r"([가-힣]+)에서\s*([가-힣]+)(?:으로|로)",  # "김철수에서 이영희로"
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
                    
                    print(f"[InfoModAgent] Contrast pattern detected: '{old_value}' → '{new_value}'")
                    
                    # 주소 관련 대조 표현 처리
                    if "동" in new_value or "로" in new_value or "길" in new_value:
                        # 주소 대조 표현
                        if modification_context in ["address", "work_address"]:
                            # 컨텍스트가 있으면 해당 필드 사용
                            target_field = modification_context
                        else:
                            # 컨텍스트가 없으면 기본적으로 address 사용 (LLM이 더 정확히 판단할 것)
                            target_field = "address"
                        
                        # 기존 주소에서 시/구 정보 추출하여 결합
                        current_address = current_info.get(target_field, "")
                        if current_address and "서울" in current_address:
                            parts = current_address.split()
                            if len(parts) >= 2:
                                prefix = " ".join(parts[:2])
                                matches[target_field] = f"{prefix} {new_value}"
                            else:
                                matches[target_field] = new_value
                        else:
                            # 기본 시/구 정보 추가
                            if target_field == "work_address":
                                matches[target_field] = f"서울특별시 중구 {new_value}"
                            else:
                                matches[target_field] = f"서울특별시 종로구 {new_value}"
                        
                        print(f"[InfoModAgent] Address contrast change: {target_field} = {matches[target_field]}")
                        return {"extracted": matches, "method": "contrast_pattern"}
                    
                    # 기존 숫자 대조 표현 처리
                    else:
                        # 한국어 숫자를 아라비아 숫자로 변환
                        old_value_digits = convert_korean_to_digits(old_value)
                        new_value_digits = convert_korean_to_digits(new_value)
                        
                        # 숫자만 추출 (끝의 조사 제거)
                        old_digits_match = re.search(r'(\d+)', old_value_digits)
                        new_digits_match = re.search(r'(\d+)', new_value_digits)
                        
                        if old_digits_match and new_digits_match:
                            old_digits = old_digits_match.group(1)
                            new_digits = new_digits_match.group(1)
                            
                            print(f"[InfoModAgent] Number contrast pattern: '{old_value}' ({old_digits}) → '{new_value}' ({new_digits})")
                            
                            # 4자리 숫자인 경우 전화번호 뒷자리로 간주
                            if re.match(r'^\d{4}$', new_digits):
                                # 기존 전화번호에서 뒷자리만 변경
                                current_phone = current_info.get("phone_number", "010-1234-5678")
                                phone_parts = current_phone.split("-")
                                if len(phone_parts) == 3:
                                    new_phone = f"{phone_parts[0]}-{phone_parts[1]}-{new_digits}"
                                else:
                                    new_phone = f"010-xxxx-{new_digits}"
                                matches["phone_number"] = new_phone
                                print(f"[InfoModAgent] Phone number tail change: {current_phone} → {new_phone}")
                            
                            # 대조 표현을 찾았으면 결과 반환
                            if matches:
                                return {"extracted": matches, "method": "contrast_pattern"}
                    break
        
        # 원본과 변환된 버전 모두에서 패턴 매칭 시도
        for test_input in [user_input, converted_input]:
            # 먼저 명시적 필드 패턴 확인 (address, work_address)
            for field_key, patterns in self.field_patterns.items():
                if field_key == "_generic_address":
                    continue  # 일반 주소 패턴은 나중에 처리
                
                for pattern in patterns:
                    match = re.search(pattern, test_input, re.IGNORECASE)
                    if match:
                        if field_key == "phone_number":
                            # 전화번호 특별 처리
                            phone_value = self._process_phone_match(match, test_input)
                            if phone_value:
                                matches[field_key] = phone_value
                        elif field_key == "customer_name":
                            # 이름 추출
                            name_value = match.group(1).strip()
                            if len(name_value) >= 2:
                                matches[field_key] = name_value
                        elif field_key == "email":
                            # 이메일 추출
                            email_value = match.group(1).strip()
                            if "@" in email_value and "." in email_value:
                                matches[field_key] = email_value
                        elif field_key in ["address", "work_address"]:
                            # 주소 추출 - 기존 주소와 병합 처리
                            new_address_part = match.group(1).strip()
                            
                            # modification_context가 있고 주소 필드인 경우, context의 필드를 우선 사용
                            if modification_context in ["address", "work_address"]:
                                target_field = modification_context
                                current_address = current_info.get(target_field, "")
                            else:
                                # context가 없으면 기본 필드 사용
                                target_field = field_key
                                current_address = current_info.get(field_key, "")
                            
                            # 부분 주소인 경우 (동/로/길 + 번지만 있는 경우)
                            if ("동" in new_address_part or "로" in new_address_part or "길" in new_address_part) and len(new_address_part) < 20:
                                if current_address and "서울" in current_address:
                                    # 기존 주소에서 시/구 정보 추출하여 결합
                                    parts = current_address.split()
                                    if len(parts) >= 2:
                                        # 서울특별시 종로구 같은 부분 유지
                                        prefix = " ".join(parts[:2])
                                        matches[target_field] = f"{prefix} {new_address_part}"
                                    else:
                                        matches[target_field] = new_address_part
                                else:
                                    # 기본 시/구 정보 추가
                                    if target_field == "work_address":
                                        # 직장주소는 기존 직장주소의 시/구를 사용하거나 기본값 사용
                                        work_address = current_info.get("work_address", "")
                                        if work_address and "서울" in work_address:
                                            parts = work_address.split()
                                            if len(parts) >= 2:
                                                prefix = " ".join(parts[:2])
                                                matches[target_field] = f"{prefix} {new_address_part}"
                                            else:
                                                matches[target_field] = f"서울특별시 중구 {new_address_part}"
                                        else:
                                            matches[target_field] = f"서울특별시 중구 {new_address_part}"
                                    else:
                                        matches[target_field] = f"서울특별시 종로구 {new_address_part}"
                            else:
                                # 완전한 새 주소인 경우
                                matches[target_field] = new_address_part
                        break
        
        # 명시적 필드 패턴에서 매치가 없었고, 일반 주소 패턴이 있는 경우
        if not matches and "_generic_address" in self.field_patterns:
            for test_input in [user_input, converted_input]:
                for pattern in self.field_patterns["_generic_address"]:
                    match = re.search(pattern, test_input, re.IGNORECASE)
                    if match:
                        new_address_part = match.group(1).strip()
                        
                        # modification_context가 있으면 그것을 사용
                        if modification_context in ["address", "work_address"]:
                            target_field = modification_context
                        else:
                            # context가 없으면 기본적으로 address로 설정 (하지만 LLM이 더 정확히 판단할 것)
                            target_field = "address"
                        
                        current_address = current_info.get(target_field, "")
                        
                        # 부분 주소인 경우
                        if ("동" in new_address_part or "로" in new_address_part or "길" in new_address_part) and len(new_address_part) < 20:
                            if current_address and "서울" in current_address:
                                parts = current_address.split()
                                if len(parts) >= 2:
                                    prefix = " ".join(parts[:2])
                                    matches[target_field] = f"{prefix} {new_address_part}"
                                else:
                                    matches[target_field] = new_address_part
                            else:
                                # 기본 시/구 정보 추가
                                if target_field == "work_address":
                                    work_address = current_info.get("work_address", "")
                                    if work_address and "서울" in work_address:
                                        parts = work_address.split()
                                        if len(parts) >= 2:
                                            prefix = " ".join(parts[:2])
                                            matches[target_field] = f"{prefix} {new_address_part}"
                                        else:
                                            matches[target_field] = f"서울특별시 중구 {new_address_part}"
                                    else:
                                        matches[target_field] = f"서울특별시 중구 {new_address_part}"
                                else:
                                    matches[target_field] = f"서울특별시 종로구 {new_address_part}"
                        else:
                            matches[target_field] = new_address_part
                        break
        
        return {"extracted": matches, "method": "pattern"}
    
    def _process_phone_match(self, match: re.Match, user_input: str) -> Optional[str]:
        """전화번호 매칭 특별 처리"""
        groups = match.groups()
        
        # 가운데 번호 4자리인 경우
        if len(groups) == 1 and len(groups[0]) in [3, 4]:
            if "가운데" in user_input or "중간" in user_input:
                # 010-{3-4자리}-xxxx로 가정
                return f"010-{groups[0]}-xxxx"
            elif "뒷번호" in user_input or "뒷자리" in user_input or "뒤" in user_input or "마지막" in user_input or "끝번호" in user_input:
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
        required_fields: List[Dict[str, Any]],
        modification_context: Optional[str] = None,
        correction_mode: bool = False
    ) -> Dict[str, Any]:
        """LLM을 사용한 지능적 분석"""
        
        if not generative_llm:
            return {"method": "llm", "error": "LLM not available"}
        
        # 필드 정보 요약
        field_descriptions = []
        for field in required_fields:
            field_descriptions.append(f"- {field['key']} ({field.get('display_name', field['key'])}): {field.get('description', 'N/A')}")
        
        # 컨텍스트 추론을 위한 정보 분석
        context_analysis = self._analyze_context_clues(user_input, current_info, modification_context, correction_mode)
        
        prompt = f"""
고객의 정보 수정 요청을 분석해주세요.

현재 고객 정보:
{self._format_current_info(current_info)}

가능한 필드들:
{chr(10).join(field_descriptions)}

고객 발화: "{user_input}"

수정 컨텍스트: {f"이전에 '{modification_context}' 필드 수정을 요청했습니다." if modification_context else "없음"}

컨텍스트 분석: {context_analysis}

**매우 중요한 추가 지침**:
- 사용자가 주소 값(동/로/길 + 번지)만 제공하고 명시적으로 "집주소" 또는 "직장주소"를 언급하지 않은 경우:
  1. 수정 컨텍스트가 있으면 반드시 그 필드를 선택하세요
  2. 패턴 매칭이 'address'로 되어있어도, 대화 흐름상 직장주소 수정이 진행 중이었다면 'work_address'로 수정하세요
  3. correction_mode가 True이고 새로운 동명인 경우, 직장주소 수정 가능성을 우선 고려하세요

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

특별 지침:
- "틀렸다", "다르다", "잘못됐다", "아니다" 등의 표현은 수정 요청이지 새로운 값이 아닙니다
- 이런 경우 new_value는 null로 설정하고, 해당 필드를 수정하려는 의도만 파악하세요
- "바꿔줘", "바꿀래", "수정해줘" 등의 표현만 있고 구체적인 새 값이 없으면 new_value를 null로 두세요
- 구체적인 새 값이 제공되지 않으면 new_value를 null로 두세요
- 단, 구체적인 주소 정보(동명 + 번지, 로, 길 등)가 포함된 경우에는 해당 값을 추출하세요
- **중요**: 현재 값과 동일한 값을 new_value로 설정하지 마세요. 그런 경우 new_value는 null이어야 합니다

전화번호 수정 시 중요 지침:
- 4자리 숫자만 제공된 경우: 가운데 부분과 마지막 부분 중에 어느 부분을 바꿔드릴까요?라고 재질의
  예: "9347로 바꿔줘" → needs_clarification: true, new_value: null
- "뒷번호", "뒷자리", "뒤", "마지막", "끝번호" 키워드와 함께 4자리: 확실히 뒷자리만 변경
- "가운데", "중간" 키워드와 함께 4자리: 가운데 자리만 변경 (010-XXXX-YYYY에서 XXXX 부분)
  예: "가운데가 5555야" → 010-1234-5678을 010-5555-5678로 변경
- 현재 전화번호가 있으면 명확한 지시가 있을 때만 해당 부분 변경

매우 중요한 주소 필드 선택 규칙:
- 패턴 매칭에서 이미 address나 work_address를 추출한 경우, 해당 필드를 우선적으로 고려하세요
- correction_mode가 True이고 새로운 동명이라고 해서 무조건 work_address로 판단하지 마세요
- 대화 맥락과 패턴 매칭 결과를 종합적으로 고려하세요

수정 컨텍스트 활용 지침:
- 수정 컨텍스트가 있으면, 해당 필드를 최우선적으로 고려하세요
- 예: 수정 컨텍스트가 "work_address"이고 사용자가 "종로동 471로"라고 하면 work_address를 수정
- 단, 사용자가 명시적으로 다른 필드를 언급하면 그것을 우선하세요
- **매우 중요**: 수정 컨텍스트가 주소 필드(address 또는 work_address)이고 사용자가 주소 값만 제공한 경우, 반드시 수정 컨텍스트의 필드를 선택하세요

대화 흐름 기반 컨텍스트 추론:
- 수정 컨텍스트가 없더라도, 사용자 입력에서 주소 정보만 제공되고 구체적인 필드 언급이 없다면:
- "동명 + 번지" 형태의 입력이고 기존 address와 work_address 둘 다 같은 동을 포함하고 있다면 더 자세히 분석 필요
- 특별히 이전에 직장주소 관련 질문이 있었을 가능성을 고려하세요
- **중요**: correction_mode가 활성화된 상황에서 주소 정보가 제공될 때:
  - 먼저 사용자가 명시적으로 언급한 필드가 있는지 확인 (예: "집주소", "직장주소")
  - 명시적 언급이 없고 수정 컨텍스트도 없는 경우에만 다음 규칙 적용:
    - 새로운 동명인 경우 직장주소 수정 가능성이 높음
    - 기존 동을 포함한 경우는 해당 주소 유형을 우선 고려
  - **주의**: 사용자가 단순히 주소 값만 제공한 경우, 최근 대화 맥락을 신중히 고려해야 함
- **컨텍스트 불확실성 처리**:
  - 컨텍스트 분석에 "수정 컨텍스트가 없어서 대화 맥락 추론이 어렵습니다"라는 단서가 있으면 매우 주의하세요
  - "불확실한 상황에서는 직장주소보다는 더 명확한 근거가 필요합니다"라는 단서가 있으면 확신도를 0.6 이하로 낮추세요
  - 명확한 근거가 없는 경우 needs_clarification을 true로 설정하는 것을 고려하세요
- 컨텍스트 분석에서 "correction_mode가 활성화된 상황에서는 직장주소 관련 대화가 진행 중일 가능성이 높습니다"라는 단서가 있으면 work_address를 우선 고려하세요
- correction_mode에서 구체적인 주소 정보가 제공된 경우, 해당 값을 추출하여 new_value에 설정하세요

주소 수정 시 특별 지침:
- 주소의 일부만 변경하는 경우(예: "숭인동 99로"), 기존 주소에서 해당 부분만 수정
- 예: 기존 "서울특별시 종로구 숭인동 123" → 사용자 "숭인동 99로" → 결과 "서울특별시 종로구 숭인동 99로"
- 완전히 새로운 주소가 아닌 경우 기존 주소의 구조를 유지하면서 변경된 부분만 반영
- "직장주소"라는 키워드가 있으면 work_address 필드만 수정하세요
- "삼각동 724야"처럼 동 이름이 기존 work_address에 있으면 work_address를 수정하세요
- 동시에 여러 주소를 수정하지 말고, 사용자가 의도한 하나의 주소만 수정하세요

답변 형식 (JSON):
{{
    "target_field": "수정하려는 필드 키",
    "new_value": "새로운 값 또는 null",
    "confidence": 0.0~1.0,
    "reasoning": "추론 근거",
    "needs_clarification": true/false
}}

수정 컨텍스트 최종 점검:
- 수정 컨텍스트가 "work_address"이고 사용자가 주소 값(동/로/길)만 제공했다면 → target_field는 반드시 "work_address"
- 수정 컨텍스트가 "address"이고 사용자가 주소 값(동/로/길)만 제공했다면 → target_field는 반드시 "address"
- 이는 패턴 매칭 결과보다 우선합니다

예시:
- "뒷번호 0987이야" → {{"target_field": "phone_number", "new_value": "010-xxxx-0987", "confidence": 0.9, "reasoning": "뒷번호 4자리는 전화번호의 마지막 부분", "needs_clarification": false}}
- "뒷자리 0987로" → {{"target_field": "phone_number", "new_value": "010-xxxx-0987", "confidence": 0.9, "reasoning": "뒷자리 4자리는 전화번호의 마지막 부분", "needs_clarification": false}}
- "가운데가 5555야" → {{"target_field": "phone_number", "new_value": "010-5555-xxxx", "confidence": 0.9, "reasoning": "가운데 4자리는 전화번호의 중간 부분", "needs_clarification": false}}
- "shinhan01@gmail.com이야" → {{"target_field": "email", "new_value": "shinhan01@gmail.com", "confidence": 0.95, "reasoning": "이메일 주소가 명시적으로 제공됨", "needs_clarification": false}}
- "이름은 김철수야" → {{"target_field": "customer_name", "new_value": "김철수", "confidence": 0.95, "reasoning": "명시적으로 이름을 제공", "needs_clarification": false}}
- "오육칠팔이 아니라 이이오구야" → {{"target_field": "phone_number", "new_value": "010-xxxx-2259", "confidence": 0.95, "reasoning": "기존 뒷번호 5678을 2259로 수정 요청", "needs_clarification": false}}
- "숭인동에서 수이동으로" → {{"target_field": "address", "new_value": "서울특별시 종로구 수이동", "confidence": 0.9, "reasoning": "주소를 숭인동에서 수이동으로 변경 요청", "needs_clarification": false}}
- "영문이름이 틀려" → {{"target_field": "english_name", "new_value": null, "confidence": 0.8, "reasoning": "영문이름이 틀렸다고 했지만 새로운 값을 제공하지 않음", "needs_clarification": true}}
- "주소가 다르다" → {{"target_field": "address", "new_value": null, "confidence": 0.8, "reasoning": "주소가 다르다고 했지만 새로운 주소를 제공하지 않음", "needs_clarification": true}}
- "구의동 57로" (correction_mode=true) → {{"target_field": "work_address", "new_value": "서울특별시 중구 구의동 57로", "confidence": 0.85, "reasoning": "correction_mode에서 새로운 동명의 주소 정보가 제공되어 직장주소 수정으로 판단", "needs_clarification": false}}
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
    
    def _analyze_context_clues(self, user_input: str, current_info: Dict[str, Any], modification_context: Optional[str], correction_mode: bool = False) -> str:
        """컨텍스트 추론을 위한 단서 분석"""
        clues = []
        
        # 1. 명시적 컨텍스트가 있는 경우
        if modification_context:
            clues.append(f"이전 대화에서 {modification_context} 수정을 요청했습니다.")
        
        # 2. 현재 사용자 입력에서 명시적 필드 언급 확인
        address_mentions = []
        if any(keyword in user_input for keyword in ["집주소", "집"]):
            address_mentions.append("집주소(address)")
        if any(keyword in user_input for keyword in ["직장주소", "회사주소", "직장", "회사"]):
            address_mentions.append("직장주소(work_address)")
        
        if address_mentions:
            clues.append(f"사용자가 {', '.join(address_mentions)}를 명시적으로 언급했습니다.")
        
        # 3. 사용자 입력이 단순한 주소 정보인 경우 (필드 명시 없음)
        elif not any(keyword in user_input for keyword in ["집주소", "직장주소", "회사주소", "집", "직장", "회사"]):
            # 동명만 있는 경우
            import re
            dong_match = re.search(r'([가-힣]+동)', user_input)
            if dong_match:
                dong_name = dong_match.group(1)
                
                # 현재 주소들에서 동 이름 확인
                address = current_info.get("address", "")
                work_address = current_info.get("work_address", "")
                
                address_has_dong = dong_name in address
                work_address_has_dong = dong_name in work_address
                
                if address_has_dong and work_address_has_dong:
                    clues.append(f"'{dong_name}'이 집주소와 직장주소 모두에 포함되어 있어 구분이 필요합니다.")
                elif work_address_has_dong and not address_has_dong:
                    clues.append(f"'{dong_name}'이 현재 직장주소({work_address})에만 포함되어 있습니다.")
                elif address_has_dong and not work_address_has_dong:
                    clues.append(f"'{dong_name}'이 현재 집주소({address})에만 포함되어 있습니다.")
                else:
                    clues.append(f"'{dong_name}'이 기존 주소에 없는 새로운 동명입니다.")
                    
                    # 새로운 동명인 경우 더 신중한 분석 필요
                    if correction_mode:
                        if not modification_context:
                            clues.append("수정 컨텍스트가 없어서 대화 맥락 추론이 어렵습니다.")
                            clues.append("correction_mode가 활성화되었지만 명시적 필드 지정이 없어 주의 필요합니다.")
                            # 기본적으로는 직장주소로 추정하지만 확신도를 낮춤
                            clues.append("불확실한 상황에서는 직장주소보다는 더 명확한 근거가 필요합니다.")
                        else:
                            clues.append("correction_mode가 활성화된 상황에서는 직장주소 관련 대화가 진행 중일 가능성이 높습니다.")
        
        # 4. 수정 의도 키워드 분석
        if "수정" in user_input or "변경" in user_input or "바꿔" in user_input:
            clues.append("명시적인 수정 요청입니다.")
        
        return " | ".join(clues) if clues else "특별한 컨텍스트 단서 없음"
    
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
        current_info: Dict[str, Any],
        modification_context: Optional[str] = None,
        user_input: str = ""
    ) -> Dict[str, Any]:
        """결과 통합 및 검증"""
        
        modified_fields = {}
        confidence = 0.0
        reasoning_parts = []
        
        # 1. 패턴 매칭 결과 우선 적용
        if "extracted" in pattern_matches and pattern_matches["extracted"]:
            # modification_context가 있고 주소 관련 필드인 경우 특별 처리
            if modification_context in ["address", "work_address"] and any(k in ["address", "work_address"] for k in pattern_matches["extracted"].keys()):
                # 패턴 매칭이 주소를 찾았지만 modification_context와 다른 필드인 경우
                pattern_address_fields = [(k, v) for k, v in pattern_matches["extracted"].items() if k in ["address", "work_address"]]
                
                if len(pattern_address_fields) == 1:
                    pattern_field, pattern_value = pattern_address_fields[0]
                    if pattern_field != modification_context:
                        # modification_context를 우선시
                        modified_fields[modification_context] = pattern_value
                        confidence = max(confidence, 0.85)
                        reasoning_parts.append(f"수정 컨텍스트 기반: {modification_context} = {pattern_value} (패턴은 {pattern_field}로 매칭됨)")
                    else:
                        # 패턴과 컨텍스트가 일치
                        modified_fields[pattern_field] = pattern_value
                        confidence = max(confidence, 0.9)
                        reasoning_parts.append(f"패턴 매칭 및 컨텍스트 일치: {pattern_field} = {pattern_value}")
                else:
                    # 일반적인 패턴 매칭 적용
                    for field, value in pattern_matches["extracted"].items():
                        modified_fields[field] = value
                        confidence = max(confidence, 0.8)
                        reasoning_parts.append(f"패턴 매칭: {field} = {value}")
            else:
                # 일반적인 패턴 매칭 적용
                for field, value in pattern_matches["extracted"].items():
                    modified_fields[field] = value
                    confidence = max(confidence, 0.8)
                    reasoning_parts.append(f"패턴 매칭: {field} = {value}")
        
        # 1.5. 사용자 입력에서 명시적 주소 타입 확인
        explicit_address_field = None
        if "집주소" in user_input or "집 주소" in user_input:
            explicit_address_field = "address"
            print(f"[InfoModAgent] User explicitly mentioned 집주소 - forcing address field")
        elif "직장주소" in user_input or "직장 주소" in user_input or "회사주소" in user_input or "회사 주소" in user_input:
            explicit_address_field = "work_address"
            print(f"[InfoModAgent] User explicitly mentioned 직장주소 - forcing work_address field")
        
        # modification_context가 없지만 이전에 명시적 언급이 있었던 경우 확인
        if not explicit_address_field and not modification_context:
            stored_context = current_info.get("_last_modification_context")
            if stored_context in ["address", "work_address"]:
                explicit_address_field = stored_context
                print(f"[InfoModAgent] Using stored modification context: {stored_context}")
                modification_context = stored_context  # 이후 로직에서 사용하기 위해
        
        # 명시적 언급이 있으면 패턴 매칭 결과를 해당 필드로 강제 변경
        if explicit_address_field and modified_fields:
            address_keys = [k for k in modified_fields.keys() if k in ["address", "work_address"]]
            if address_keys:
                # 기존 주소 필드 제거하고 명시적 필드로 변경
                address_value = None
                for key in address_keys:
                    address_value = modified_fields[key]
                    del modified_fields[key]
                if address_value:
                    modified_fields[explicit_address_field] = address_value
                    confidence = max(confidence, 0.95)  # 명시적 언급이므로 높은 신뢰도
                    reasoning_parts = [f"명시적 필드 지정: {explicit_address_field} = {address_value}"]
        
        # 명시적 언급이 없지만 modification_context가 있는 경우
        elif not explicit_address_field and modification_context in ["address", "work_address"] and modified_fields:
            address_keys = [k for k in modified_fields.keys() if k in ["address", "work_address"]]
            if address_keys:
                pattern_field = address_keys[0]
                if pattern_field != modification_context:
                    # 패턴 매칭 결과를 modification_context로 변경
                    address_value = modified_fields[pattern_field]
                    del modified_fields[pattern_field]
                    modified_fields[modification_context] = address_value
                    confidence = max(confidence, 0.9)  # 컨텍스트 기반이므로 높은 신뢰도
                    reasoning_parts = [f"수정 컨텍스트 적용: {modification_context} = {address_value} (패턴: {pattern_field})"]
                    print(f"[InfoModAgent] Applied modification context: {pattern_field} -> {modification_context}")
        
        # 2. LLM 분석 결과 적용
        if "target_field" in llm_analysis and "new_value" in llm_analysis:
            field = llm_analysis["target_field"]
            value = llm_analysis["new_value"]
            
            # 명시적 언급이 있으면 LLM 결과도 해당 필드로 강제 변경
            if explicit_address_field and field in ["address", "work_address"]:
                field = explicit_address_field
                print(f"[InfoModAgent] Overriding LLM field choice with explicit mention: {explicit_address_field}")
            # modification_context가 있고 LLM이 다른 주소 필드를 선택한 경우도 수정
            elif modification_context in ["address", "work_address"] and field in ["address", "work_address"] and field != modification_context:
                field = modification_context
                print(f"[InfoModAgent] Overriding LLM field choice with modification context: {modification_context}")
            
            # 패턴 매칭이 이미 동일한 필드에 대해 값을 찾았고, LLM이 null을 반환한 경우 패턴 매칭 우선
            if field in modified_fields and value is None and modified_fields[field] is not None:
                # 특히 전화번호의 경우 명확한 키워드가 있으면 패턴 매칭을 신뢰
                if field == "phone_number" and any(keyword in user_input for keyword in ["뒷자리", "뒷번호", "가운데", "중간"]):
                    print(f"[InfoModAgent] Pattern matching found confident phone match, ignoring LLM null: {modified_fields[field]}")
                    reasoning_parts.append(f"패턴 매칭 우선 (LLM null 무시): {field} = {modified_fields[field]}")
                    # 패턴 매칭 결과 유지
                    return {
                        "modified_fields": modified_fields,
                        "confidence": confidence,
                        "reasoning": " | ".join(reasoning_parts),
                        "suggestions": self._generate_suggestions(modified_fields, current_info)
                    }
                # 다른 필드도 패턴 매칭이 명확한 값을 찾았으면 우선
                elif modified_fields[field] and confidence >= 0.8:
                    print(f"[InfoModAgent] Pattern matching found confident match, ignoring LLM null: {field} = {modified_fields[field]}")
                    reasoning_parts.append(f"패턴 매칭 우선 (LLM null 무시): {field} = {modified_fields[field]}")
                    return {
                        "modified_fields": modified_fields,
                        "confidence": confidence,
                        "reasoning": " | ".join(reasoning_parts),
                        "suggestions": self._generate_suggestions(modified_fields, current_info)
                    }
            
            # LLM이 현재 값과 동일한 값을 새 값으로 설정한 경우 확인
            if value and field in current_info:
                current_value = current_info.get(field)
                if value == current_value:
                    # 현재 값과 동일하면 null로 설정하고 clarification 요청
                    value = None
                    llm_analysis["needs_clarification"] = True
                    print(f"[InfoModAgent] LLM returned same value as current, setting to null for clarification")
            
            # 주소 필드의 경우 특별 처리
            if field in ["address", "work_address"] and modified_fields:
                # 패턴 매칭이 이미 주소를 추출한 경우
                pattern_extracted_address = any(k in ["address", "work_address"] for k in modified_fields.keys())
                if pattern_extracted_address:
                    # 패턴 매칭 결과와 LLM 결과가 다른 경우
                    pattern_field = next(k for k in modified_fields.keys() if k in ["address", "work_address"])
                    if pattern_field != field:
                        # modification_context가 있으면 LLM 결과를 더 신뢰
                        if modification_context in ["address", "work_address"] or llm_analysis.get("confidence", 0.5) >= 0.7:
                            # LLM 결과 사용 (modification context가 있거나 LLM 신뢰도가 높은 경우)
                            pass  # 아래 코드에서 LLM 결과 적용
                        else:
                            reasoning_parts.append(f"LLM 분석 (패턴 매칭 우선): {llm_analysis.get('reasoning', 'N/A')}")
                            # 패턴 매칭 결과 유지
                            return {
                                "modified_fields": modified_fields,
                                "confidence": confidence,
                                "reasoning": " | ".join(reasoning_parts),
                                "suggestions": self._generate_suggestions(modified_fields, current_info)
                            }
            
            # LLM 분석 결과를 우선시 (높은 신뢰도의 경우)
            if llm_analysis.get("confidence", 0.5) >= 0.7:  # 신뢰도 기준 낮춤
                # 전화번호 특별 처리 - 기존 정보와 조합
                if field == "phone_number" and value and ("010-xxxx-" in value or "010-" in value and "-xxxx" in value):
                    existing_phone = current_info.get("phone_number", "")
                    if existing_phone and existing_phone.startswith("010-"):
                        # 기존 번호의 부분 조합
                        existing_parts = existing_phone.split("-")
                        if len(existing_parts) == 3:
                            if value.startswith("010-xxxx-"):
                                # 뒷번호 변경: 010-xxxx-1234
                                new_last_4 = value.split("-")[-1]
                                value = f"{existing_parts[0]}-{existing_parts[1]}-{new_last_4}"
                            elif "010-" in value and "-xxxx" in value:
                                # 가운데 번호 변경: 010-5555-xxxx
                                new_middle = value.split("-")[1]
                                value = f"{existing_parts[0]}-{new_middle}-{existing_parts[2]}"
                
                # 주소 필드 중복 처리 방지
                if field in ["address", "work_address"]:
                    # 패턴 매칭으로 잘못 추출된 다른 주소 필드 제거
                    if field == "work_address" and "address" in modified_fields:
                        # work_address가 타겟이면 address 제거
                        del modified_fields["address"]
                        reasoning_parts = [r for r in reasoning_parts if "address" not in r]
                    elif field == "address" and "work_address" in modified_fields:
                        # address가 타겟이면 work_address 제거
                        del modified_fields["work_address"]
                        reasoning_parts = [r for r in reasoning_parts if "work_address" not in r]
                
                modified_fields[field] = value
                confidence = max(confidence, llm_analysis.get("confidence", 0.5))
                reasoning_parts.append(f"LLM 분석: {llm_analysis.get('reasoning', 'N/A')}")
            else:
                # 신뢰도가 낮으면 패턴 매칭 우선
                if field not in modified_fields:
                    modified_fields[field] = value
                    confidence = max(confidence, llm_analysis.get("confidence", 0.5))
                    reasoning_parts.append(f"LLM 분석: {llm_analysis.get('reasoning', 'N/A')}")
                else:
                    reasoning_parts.append(f"LLM 분석 (패턴 매칭 우선): {llm_analysis.get('reasoning', 'N/A')}")
        
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
            
            if field == "phone_number":
                suggestions.append(f"전화번호를 {old_value}에서 {new_value}(으)로 변경하시겠어요?")
            elif field == "customer_name":
                suggestions.append(f"성함을 {old_value}에서 {new_value}(으)로 변경하시겠어요?")
            elif field == "address":
                if old_value != "없음" and old_value:
                    suggestions.append(f"집주소를 {new_value}(으)로 변경하시겠어요?")
                else:
                    suggestions.append(f"집주소를 {new_value}(으)로 설정하시겠어요?")
            elif field == "work_address":
                if old_value != "없음" and old_value:
                    suggestions.append(f"직장주소를 {new_value}(으)로 변경하시겠어요?")
                else:
                    suggestions.append(f"직장주소를 {new_value}(으)로 설정하시겠어요?")
            else:
                display_name = self._get_field_display_name(field)
                suggestions.append(f"{display_name}을(를) '{old_value}'에서 '{new_value}'(으)로 변경하시겠어요?")
        
        return suggestions
    
    def _get_field_display_name(self, field_key: str) -> str:
        """필드 키를 한국어 표시명으로 변환"""
        display_names = {
            "customer_name": "성함",
            "english_name": "영문이름",
            "resident_number": "주민등록번호",
            "phone_number": "전화번호",
            "email": "이메일",
            "address": "집주소",
            "work_address": "직장주소",
            "confirm_personal_info": "개인정보 확인",
            "use_lifelong_account": "평생계좌 등록",
            "use_internet_banking": "인터넷뱅킹 가입",
            "use_check_card": "체크카드 신청"
        }
        return display_names.get(field_key, field_key)


# 전역 인스턴스
info_modification_agent = InfoModificationAgent()