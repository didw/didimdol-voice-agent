# backend/app/agents/internet_banking_agent.py
"""
인터넷뱅킹 전용 개체 추출 Agent - 복잡한 인터넷뱅킹 정보를 정확하게 파악하고 처리
"""

import re
from typing import Dict, Any, Optional, List, Tuple
from ..graph.chains import generative_llm


class InternetBankingAgent:
    """
    인터넷뱅킹 관련 정보를 지능적으로 추출하고 분석하는 전용 Agent
    
    기능:
    1. 자연어로 표현된 이체한도, 보안매체, 알림설정 등 정확한 매칭
    2. 숫자 표현 정규화 (삼백만원 → 300, 하루 1억 → 10000)
    3. 불완전한 답변에 대한 적절한 안내 문구 생성
    4. 여러 항목을 한번에 말하는 경우 각각 분리하여 추출
    """
    
    def __init__(self):
        # 금액 표현 패턴 (만원 단위로 변환)
        self.amount_patterns = [
            # 명시적 금액 표현
            (r"(\d+)\s*억\s*(\d+)?\s*천?\s*만?\s*원?", self._parse_억_천만),
            (r"(\d+)\s*억\s*원?", lambda m: int(m.group(1)) * 10000),
            (r"(\d+)\s*천\s*(\d+)?\s*백?\s*만?\s*원?", self._parse_천만),
            (r"(\d+)\s*천\s*만?\s*원?", lambda m: int(m.group(1)) * 1000),
            (r"(\d+)\s*백\s*만?\s*원?", lambda m: int(m.group(1)) * 100),
            (r"(\d+)\s*만\s*원?", lambda m: int(m.group(1))),
            
            # 한글 숫자 표현
            (r"일억", lambda m: 10000),
            (r"오천만원?", lambda m: 5000),
            (r"삼천만원?", lambda m: 3000),
            (r"이천만원?", lambda m: 2000),
            (r"천만원?", lambda m: 1000),
            (r"오백만원?", lambda m: 500),
            (r"삼백만원?", lambda m: 300),
            (r"이백만원?", lambda m: 200),
            (r"백만원?", lambda m: 100),
            (r"구십만원?", lambda m: 90),
            (r"팔십만원?", lambda m: 80),
            (r"칠십만원?", lambda m: 70),
            (r"육십만원?", lambda m: 60),
            (r"오십만원?", lambda m: 50),
        ]
        
        # 이체한도 관련 키워드
        self.transfer_limit_keywords = {
            "per_time": ["1회", "회당", "한번에", "한 번에", "건당", "회차당", "번에"],
            "per_day": ["1일", "하루", "일일", "하루에", "하루당", "날마다", "매일", "데일리"]
        }
        
        # 보안매체 매칭
        self.security_medium_map = {
            "보안카드": ["보안카드", "카드"],
            "신한 OTP": ["신한OTP", "신한 OTP", "OTP", "오티피", "원타임패스워드"],
            "타행 OTP": ["타행OTP", "타행 OTP", "다른은행OTP", "타은행OTP", "기존OTP"]
        }
        
        # 알림 설정 매칭
        self.alert_map = {
            "중요거래통보": ["중요거래", "중요", "큰거래", "고액", "고액거래"],
            "출금내역통보": ["출금내역", "출금", "인출", "빠져나가는", "지출"],
            "해외IP이체 제한": ["해외IP", "해외", "IP제한", "해외접속", "외국", "해외차단"]
        }
    
    def _parse_억_천만(self, match):
        """억, 천만 단위 파싱"""
        억 = int(match.group(1))
        천만 = int(match.group(2)) if match.group(2) else 0
        return 억 * 10000 + 천만 * 1000
    
    def _parse_천만(self, match):
        """천만 단위 파싱"""
        천 = int(match.group(1))
        백만 = int(match.group(2)) if match.group(2) else 0
        return 천 * 1000 + 백만 * 100
    
    async def analyze_internet_banking_info(
        self, 
        user_input: str, 
        current_info: Dict[str, Any],
        required_fields: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        인터넷뱅킹 관련 사용자 입력을 분석하고 적절한 정보 추출
        
        Args:
            user_input: 사용자의 자연어 입력
            current_info: 현재 수집된 정보
            required_fields: 필드 정의 정보
            
        Returns:
            {
                "extracted_info": {"field_key": "value"},
                "missing_info": ["field_key"],
                "confidence": float,
                "guidance_message": str,
                "reasoning": str
            }
        """
        print(f"[IBAgent] Analyzing: '{user_input}'")
        print(f"[IBAgent] Current info: {current_info}")
        
        # 1. 이체한도 추출
        transfer_limits = self._extract_transfer_limits(user_input)
        
        # 2. 보안매체 추출
        security_medium = self._extract_security_medium(user_input)
        
        # 3. 알림 설정 추출
        alert_setting = self._extract_alert_setting(user_input)
        
        # 4. 출금계좌 추가 여부 추출
        additional_account = self._extract_additional_account(user_input)
        
        # 5. LLM 기반 종합 분석
        llm_analysis = await self._analyze_with_llm(user_input, current_info, required_fields)
        
        # 6. 결과 통합
        extracted_info = {}
        if transfer_limits:
            extracted_info.update(transfer_limits)
        if security_medium:
            extracted_info["security_medium"] = security_medium
        if alert_setting:
            extracted_info["alert"] = alert_setting
        if additional_account is not None:
            extracted_info["additional_withdrawal_account"] = additional_account
        
        # LLM 분석 결과 보완
        if llm_analysis.get("extracted_fields"):
            for field, value in llm_analysis["extracted_fields"].items():
                if field not in extracted_info and value is not None:
                    extracted_info[field] = value
        
        # 7. 누락된 정보 파악
        missing_info = self._identify_missing_info(extracted_info, current_info, required_fields)
        
        # 8. 안내 메시지 생성
        guidance_message = self._generate_guidance_message(extracted_info, missing_info, user_input)
        
        # 9. 신뢰도 계산
        confidence = self._calculate_confidence(extracted_info, user_input)
        
        result = {
            "extracted_info": extracted_info,
            "missing_info": missing_info,
            "confidence": confidence,
            "guidance_message": guidance_message,
            "reasoning": f"추출됨: {list(extracted_info.keys())}, 누락: {missing_info}"
        }
        
        print(f"[IBAgent] Result: {result}")
        return result
    
    def _extract_transfer_limits(self, user_input: str) -> Dict[str, int]:
        """이체한도 추출"""
        limits = {}
        
        # 각 금액 패턴으로 시도
        for pattern, parser in self.amount_patterns:
            matches = list(re.finditer(pattern, user_input, re.IGNORECASE))
            
            for match in matches:
                try:
                    amount = parser(match) if callable(parser) else parser(match)
                    
                    # 앞뒤 문맥으로 1회/1일 구분
                    context_before = user_input[:match.start()].lower()
                    context_after = user_input[match.end():].lower()
                    full_context = context_before + " " + context_after
                    
                    # 1회 이체한도 키워드 체크
                    if any(keyword in full_context for keyword in self.transfer_limit_keywords["per_time"]):
                        if amount <= 5000:  # 1회 최대 5천만원
                            limits["transfer_limit_per_time"] = amount
                    
                    # 1일 이체한도 키워드 체크
                    elif any(keyword in full_context for keyword in self.transfer_limit_keywords["per_day"]):
                        if amount <= 10000:  # 1일 최대 1억원
                            limits["transfer_limit_per_day"] = amount
                    
                    # 키워드가 없는 경우 금액 크기로 추론
                    else:
                        if amount <= 5000 and "transfer_limit_per_time" not in limits:
                            limits["transfer_limit_per_time"] = amount
                        elif amount > 5000 and amount <= 10000 and "transfer_limit_per_day" not in limits:
                            limits["transfer_limit_per_day"] = amount
                            
                except (ValueError, AttributeError):
                    continue
        
        return limits
    
    def _extract_security_medium(self, user_input: str) -> Optional[str]:
        """보안매체 추출"""
        user_lower = user_input.lower()
        
        for medium, keywords in self.security_medium_map.items():
            if any(keyword.lower() in user_lower for keyword in keywords):
                return medium
        
        return None
    
    def _extract_alert_setting(self, user_input: str) -> Optional[str]:
        """알림 설정 추출"""
        user_lower = user_input.lower()
        
        for alert_type, keywords in self.alert_map.items():
            if any(keyword in user_lower for keyword in keywords):
                return alert_type
        
        return None
    
    def _extract_additional_account(self, user_input: str) -> Optional[bool]:
        """출금계좌 추가 여부 추출"""
        user_lower = user_input.lower()
        
        # 긍정적 표현
        positive_keywords = ["추가", "더", "계좌 하나 더", "여러 계좌", "다른 계좌", "계좌 늘리기"]
        if any(keyword in user_lower for keyword in positive_keywords):
            return True
        
        # 부정적 표현
        negative_keywords = ["추가 안", "안 추가", "하나만", "기본만", "필요없", "안할게"]
        if any(keyword in user_lower for keyword in negative_keywords):
            return False
        
        return None
    
    async def _analyze_with_llm(
        self, 
        user_input: str, 
        current_info: Dict[str, Any], 
        required_fields: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """LLM을 사용한 종합 분석"""
        
        if not generative_llm:
            return {"error": "LLM not available"}
        
        # 인터넷뱅킹 관련 필드만 필터링
        ib_fields = [f for f in required_fields if f.get("parent_field") == "use_internet_banking" or f["key"] == "use_internet_banking"]
        
        field_descriptions = []
        for field in ib_fields:
            desc = f"- {field['key']} ({field.get('display_name', field['key'])}): {field.get('description', 'N/A')}"
            if field.get("choices"):
                desc += f" [선택지: {', '.join(field['choices'])}]"
            field_descriptions.append(desc)
        
        prompt = f"""
인터넷뱅킹 관련 고객 답변을 분석해주세요.

인터넷뱅킹 관련 필드들:
{chr(10).join(field_descriptions)}

고객 발화: "{user_input}"

분석 규칙:
1. 금액 표현 (만원 단위로 변환):
   - "삼백만원", "300만원" → 300
   - "하루 최대 일억", "1일 1억" → 10000 (1일 이체한도)
   - "1회 5천", "한번에 오천만원" → 5000 (1회 이체한도)

2. 보안매체:
   - "보안카드", "카드" → "보안카드"
   - "OTP", "신한OTP" → "신한 OTP"  
   - "타행OTP", "기존OTP" → "타행 OTP"

3. 알림 설정:
   - "중요거래", "고액거래" → "중요거래통보"
   - "출금내역", "빠져나가는거" → "출금내역통보"
   - "해외IP", "해외차단" → "해외IP이체 제한"

4. 출금계좌 추가:
   - "추가", "더", "여러 계좌" → true
   - "추가 안", "하나만" → false

답변 형식 (JSON):
{{
    "extracted_fields": {{
        "field_key": "value"
    }},
    "confidence": 0.0~1.0,
    "reasoning": "분석 근거"
}}
"""

        try:
            from langchain_core.messages import HumanMessage
            response = await generative_llm.ainvoke([HumanMessage(content=prompt)])
            
            content = response.content.strip()
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "").strip()
            
            import json
            result = json.loads(content)
            return result
            
        except Exception as e:
            print(f"[IBAgent] LLM analysis error: {e}")
            return {"error": str(e)}
    
    def _identify_missing_info(
        self, 
        extracted_info: Dict[str, Any], 
        current_info: Dict[str, Any],
        required_fields: List[Dict[str, Any]]
    ) -> List[str]:
        """누락된 필수 정보 파악"""
        missing = []
        
        # 인터넷뱅킹 가입이 true인 경우에만 관련 정보 요구
        if current_info.get("use_internet_banking") == True:
            required_ib_fields = [
                "security_medium",
                "transfer_limit_per_time", 
                "transfer_limit_per_day",
                "alert",
                "additional_withdrawal_account"
            ]
            
            for field_key in required_ib_fields:
                if field_key not in extracted_info and field_key not in current_info:
                    missing.append(field_key)
        
        return missing
    
    def _generate_guidance_message(
        self, 
        extracted_info: Dict[str, Any], 
        missing_info: List[str],
        user_input: str
    ) -> str:
        """적절한 안내 메시지 생성"""
        
        if not extracted_info and not missing_info:
            return "인터넷뱅킹 설정에 필요한 정보를 말씀해주세요. 보안매체, 이체한도, 알림설정 등을 알려주시면 됩니다."
        
        messages = []
        
        # 성공적으로 추출된 정보 확인
        if extracted_info:
            confirmations = []
            for field, value in extracted_info.items():
                if field == "security_medium":
                    confirmations.append(f"보안매체: {value}")
                elif field == "transfer_limit_per_time":
                    confirmations.append(f"1회 이체한도: {value}만원")
                elif field == "transfer_limit_per_day":
                    confirmations.append(f"1일 이체한도: {value}만원")
                elif field == "alert":
                    confirmations.append(f"알림설정: {value}")
                elif field == "additional_withdrawal_account":
                    confirmations.append(f"출금계좌 추가: {'예' if value else '아니오'}")
            
            if confirmations:
                messages.append(f"네, {', '.join(confirmations)}로 설정하겠습니다.")
        
        # 누락된 정보 요청
        if missing_info:
            missing_requests = []
            for field in missing_info:
                if field == "security_medium":
                    missing_requests.append("보안매체 선택 (보안카드/신한 OTP/타행 OTP)")
                elif field == "transfer_limit_per_time":
                    missing_requests.append("1회 이체한도 (최대 5천만원)")
                elif field == "transfer_limit_per_day":
                    missing_requests.append("1일 이체한도 (최대 1억원)")
                elif field == "alert":
                    missing_requests.append("알림 설정 (중요거래통보/출금내역통보/해외IP이체 제한)")
                elif field == "additional_withdrawal_account":
                    missing_requests.append("출금계좌 추가 여부")
            
            if missing_requests:
                if len(missing_requests) == 1:
                    messages.append(f"추가로 {missing_requests[0]}를 알려주세요.")
                else:
                    messages.append(f"추가로 다음 정보들을 알려주세요: {', '.join(missing_requests)}")
        
        return " ".join(messages) if messages else "추가 정보가 필요합니다."
    
    def _calculate_confidence(self, extracted_info: Dict[str, Any], user_input: str) -> float:
        """신뢰도 계산"""
        if not extracted_info:
            return 0.1
        
        confidence = 0.0
        total_weight = 0.0
        
        # 각 필드별 신뢰도 가중치
        field_weights = {
            "security_medium": 0.3,
            "transfer_limit_per_time": 0.25,
            "transfer_limit_per_day": 0.25,
            "alert": 0.15,
            "additional_withdrawal_account": 0.05
        }
        
        for field, value in extracted_info.items():
            weight = field_weights.get(field, 0.1)
            total_weight += weight
            
            # 필드별 신뢰도 계산
            if field.startswith("transfer_limit_"):
                # 숫자 추출의 경우 패턴 매칭 정확도 높음
                confidence += weight * 0.9
            elif field == "security_medium" and value in ["보안카드", "신한 OTP", "타행 OTP"]:
                # 정확한 선택지 매칭
                confidence += weight * 0.95
            elif field == "alert" and value in ["중요거래통보", "출금내역통보", "해외IP이체 제한"]:
                # 정확한 알림 설정 매칭
                confidence += weight * 0.85
            else:
                confidence += weight * 0.7
        
        return min(confidence / total_weight if total_weight > 0 else 0.1, 1.0)


# 전역 인스턴스
internet_banking_agent = InternetBankingAgent()