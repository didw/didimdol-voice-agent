# backend/app/agents/check_card_agent.py
"""
체크카드 전용 개체 추출 Agent - 복잡한 체크카드 정보를 정확하게 파악하고 처리
"""

import re
from typing import Dict, Any, Optional, List, Tuple
from ..graph.chains import generative_llm


class CheckCardAgent:
    """
    체크카드 관련 정보를 지능적으로 추출하고 분석하는 전용 Agent
    
    기능:
    1. 자연어로 표현된 카드수령방법, 배송지, 카드종류 등 정확한 매칭
    2. 결제일 숫자 표현 정규화 (1일~30일)
    3. 불완전한 답변에 대한 적절한 안내 문구 생성
    4. 여러 항목을 한번에 말하는 경우 각각 분리하여 추출
    """
    
    def __init__(self):
        # 카드 수령 방법 매칭
        self.card_receive_method_map = {
            "즉시발급": ["즉시발급", "즉시", "바로발급", "바로", "당일발급", "당일", "지금", "지금발급", 
                        "현장발급", "현장", "즉석", "즉석발급", "바로받기", "지금받기"],
            "배송": ["배송", "택배", "집으로", "우편", "우편배송", "택배배송", "배달", "집배송", 
                    "회사로", "직장으로", "나중에", "나중에받기", "며칠후"]
        }
        
        # 카드 배송지 매칭
        self.card_delivery_location_map = {
            "자택": ["자택", "집", "우리집", "본인집", "주소지", "등록주소", "집주소", "거주지", 
                    "사는곳", "살고있는곳", "내집", "홈"],
            "직장": ["직장", "회사", "사무실", "근무지", "일하는곳", "오피스", "직장주소", "회사주소", 
                    "근무하는곳", "출근하는곳", "업무지"],
            "지점": ["지점", "은행", "영업점", "매장", "신한은행", "은행지점", "가까운지점", "근처지점",
                    "이곳", "여기", "지금여기"]
        }
        
        # 카드 종류 매칭
        self.card_type_map = {
            "S-line": ["S라인", "S-line", "에스라인", "s라인", "s-line", "sline", "에스line", "s line"],
            "딥드림": ["딥드림", "딥드림체크", "deep dream", "deepdream", "딥 드림", "dip dream"]
        }
        
        # 후불교통 매칭 (boolean)
        self.postpaid_transport_keywords = {
            "positive": ["후불교통", "후불", "교통카드", "대중교통", "버스", "지하철", "교통", 
                        "후불교통기능", "교통기능", "탑승", "교통비"],
            "negative": ["안해", "안할", "필요없", "없어도", "안써", "사용안함", "쓰지않", "노후불"]
        }
        
        # 결제일 패턴 (1-30)
        self.payment_date_patterns = [
            (r"(\d{1,2})일", lambda m: int(m.group(1)) if 1 <= int(m.group(1)) <= 30 else None),
            (r"매월\s*(\d{1,2})", lambda m: int(m.group(1)) if 1 <= int(m.group(1)) <= 30 else None),
            (r"(\d{1,2})일날", lambda m: int(m.group(1)) if 1 <= int(m.group(1)) <= 30 else None),
            (r"월\s*(\d{1,2})", lambda m: int(m.group(1)) if 1 <= int(m.group(1)) <= 30 else None),
        ]
        
        # 명세서 수령 방법 매칭
        self.statement_method_map = {
            "이메일": ["이메일", "email", "메일", "전자메일", "e-mail", "이멜", "전자우편"],
            "문자": ["문자", "SMS", "sms", "문자메시지", "문자메세지", "핸드폰", "휴대폰", "카톡", "카카오톡"],
            "우편": ["우편", "우편물", "편지", "실물", "종이", "오프라인", "집으로"],
            "미수령": ["안받", "필요없", "받지않", "미수령", "수령안함", "안해", "노", "없어도"]
        }
        
        # 계좌비밀번호 동일 사용 (boolean)
        self.same_password_keywords = {
            "positive": ["동일", "같게", "똑같이", "같은", "동일하게", "통일", "같이", "일치", "그대로"],
            "negative": ["다르게", "다른", "별도", "새로", "따로", "별개", "다른걸로", "변경"]
        }
        
        # 카드사용알림 (boolean)
        self.card_alert_keywords = {
            "positive": ["알림", "알려", "통보", "알람", "푸시", "push", "문자", "받을게", "받고싶", "설정"],
            "negative": ["안받", "필요없", "알림안", "거절", "싫어", "안해", "받지않", "설정안함"]
        }
    
    async def analyze_check_card_info(
        self, 
        user_input: str, 
        current_info: Dict[str, Any],
        required_fields: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        체크카드 관련 사용자 입력을 분석하고 적절한 정보 추출
        
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
        print(f"[CCAgent] Analyzing: '{user_input}'")
        print(f"[CCAgent] Current info: {current_info}")
        
        # 1. 카드 수령 방법 추출
        card_receive_method = self._extract_card_receive_method(user_input)
        
        # 2. 카드 배송지 추출
        card_delivery_location = self._extract_card_delivery_location(user_input)
        
        # 3. 카드 종류 추출
        card_type = self._extract_card_type(user_input)
        
        # 4. 후불교통 기능 추출
        postpaid_transport = self._extract_postpaid_transport(user_input)
        
        # 5. 결제일 추출
        payment_date = self._extract_payment_date(user_input)
        
        # 6. 명세서 수령 방법 추출
        statement_method = self._extract_statement_method(user_input)
        
        # 7. 계좌비밀번호 동일 사용 추출
        same_password = self._extract_same_password(user_input)
        
        # 8. 카드사용알림 추출
        card_usage_alert = self._extract_card_usage_alert(user_input)
        
        # 9. LLM 기반 종합 분석
        llm_analysis = await self._analyze_with_llm(user_input, current_info, required_fields)
        
        # 10. 결과 통합
        extracted_info = {}
        if card_receive_method:
            extracted_info["card_receive_method"] = card_receive_method
        if card_delivery_location:
            extracted_info["card_delivery_location"] = card_delivery_location
        if card_type:
            extracted_info["card_type"] = card_type
        if postpaid_transport is not None:
            extracted_info["postpaid_transport"] = postpaid_transport
        if payment_date:
            extracted_info["payment_date"] = payment_date
        if statement_method:
            extracted_info["statement_method"] = statement_method
        if same_password is not None:
            extracted_info["same_password_as_account"] = same_password
        if card_usage_alert is not None:
            extracted_info["card_usage_alert"] = card_usage_alert
        
        # LLM 분석 결과 보완
        if llm_analysis.get("extracted_fields"):
            for field, value in llm_analysis["extracted_fields"].items():
                if field not in extracted_info and value is not None:
                    extracted_info[field] = value
        
        # 11. 누락된 정보 파악
        missing_info = self._identify_missing_info(extracted_info, current_info, required_fields)
        
        # 12. 안내 메시지 생성
        guidance_message = self._generate_guidance_message(extracted_info, missing_info, user_input)
        
        # 13. 신뢰도 계산
        confidence = self._calculate_confidence(extracted_info, user_input)
        
        result = {
            "extracted_info": extracted_info,
            "missing_info": missing_info,
            "confidence": confidence,
            "guidance_message": guidance_message,
            "reasoning": f"추출됨: {list(extracted_info.keys())}, 누락: {missing_info}"
        }
        
        print(f"[CCAgent] Result: {result}")
        return result
    
    def _extract_card_receive_method(self, user_input: str) -> Optional[str]:
        """카드 수령 방법 추출"""
        user_lower = user_input.lower()
        
        for method, keywords in self.card_receive_method_map.items():
            if any(keyword in user_lower for keyword in keywords):
                return method
        
        return None
    
    def _extract_card_delivery_location(self, user_input: str) -> Optional[str]:
        """카드 배송지 추출"""
        user_lower = user_input.lower()
        
        for location, keywords in self.card_delivery_location_map.items():
            if any(keyword in user_lower for keyword in keywords):
                return location
        
        return None
    
    def _extract_card_type(self, user_input: str) -> Optional[str]:
        """카드 종류 추출"""
        user_lower = user_input.lower()
        
        for card_type, keywords in self.card_type_map.items():
            if any(keyword.lower() in user_lower for keyword in keywords):
                return card_type
        
        return None
    
    def _extract_postpaid_transport(self, user_input: str) -> Optional[bool]:
        """후불교통 기능 사용 여부 추출"""
        user_lower = user_input.lower()
        
        # 긍정적 표현 확인
        if any(keyword in user_lower for keyword in self.postpaid_transport_keywords["positive"]):
            # 부정적 표현이 함께 있는지 확인
            if any(keyword in user_lower for keyword in self.postpaid_transport_keywords["negative"]):
                return False
            return True
        
        # 부정적 표현만 있는 경우
        if any(keyword in user_lower for keyword in self.postpaid_transport_keywords["negative"]):
            return False
        
        return None
    
    def _extract_payment_date(self, user_input: str) -> Optional[int]:
        """결제일 추출 (1-30)"""
        for pattern, parser in self.payment_date_patterns:
            match = re.search(pattern, user_input)
            if match:
                try:
                    date = parser(match)
                    if date and 1 <= date <= 30:
                        print(f"[CCAgent] Found payment date: {date}")
                        return date
                except Exception as e:
                    print(f"[CCAgent] Error parsing payment date: {e}")
                    continue
        
        return None
    
    def _extract_statement_method(self, user_input: str) -> Optional[str]:
        """명세서 수령 방법 추출"""
        user_lower = user_input.lower()
        
        for method, keywords in self.statement_method_map.items():
            if any(keyword in user_lower for keyword in keywords):
                return method
        
        return None
    
    def _extract_same_password(self, user_input: str) -> Optional[bool]:
        """계좌비밀번호 동일 사용 여부 추출"""
        user_lower = user_input.lower()
        
        # 긍정적 표현 확인
        if any(keyword in user_lower for keyword in self.same_password_keywords["positive"]):
            return True
        
        # 부정적 표현 확인
        if any(keyword in user_lower for keyword in self.same_password_keywords["negative"]):
            return False
        
        return None
    
    def _extract_card_usage_alert(self, user_input: str) -> Optional[bool]:
        """카드사용알림 설정 여부 추출"""
        user_lower = user_input.lower()
        
        # 긍정적 표현 확인
        if any(keyword in user_lower for keyword in self.card_alert_keywords["positive"]):
            # 부정적 표현이 함께 있는지 확인
            if any(keyword in user_lower for keyword in self.card_alert_keywords["negative"]):
                return False
            return True
        
        # 부정적 표현만 있는 경우
        if any(keyword in user_lower for keyword in self.card_alert_keywords["negative"]):
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
        
        # 체크카드 관련 필드만 필터링
        cc_fields = [f for f in required_fields if f.get("parent_field") == "use_check_card" or f["key"] == "use_check_card"]
        
        field_descriptions = []
        for field in cc_fields:
            desc = f"- {field['key']} ({field.get('display_name', field['key'])}): {field.get('description', 'N/A')}"
            if field.get("choices"):
                desc += f" [선택지: {', '.join(field['choices'])}]"
            field_descriptions.append(desc)
        
        prompt = f"""
체크카드 관련 고객 답변을 분석해주세요.

체크카드 관련 필드들:
{chr(10).join(field_descriptions)}

고객 발화: "{user_input}"

분석 규칙:
1. 카드 수령 방법:
   - "즉시", "바로", "당일", "지금" → "즉시발급"
   - "배송", "택배", "집으로", "나중에" → "배송"

2. 카드 배송지:
   - "집", "자택", "주소지" → "자택"
   - "회사", "직장", "사무실" → "직장"
   - "지점", "은행", "여기" → "지점"

3. 카드 종류:
   - "S라인", "S-line", "에스라인" → "S-line"
   - "딥드림", "deep dream" → "딥드림"

4. 후불교통 (true/false):
   - "후불교통", "교통카드", "버스", "지하철" → true
   - "안해", "필요없" → false

5. 결제일 (1-30 숫자):
   - "15일", "매월 15" → 15
   - "월말", "말일" → 30

6. 명세서 수령:
   - "이메일", "메일" → "이메일"
   - "문자", "SMS" → "문자"
   - "우편", "종이" → "우편"
   - "안받", "필요없" → "미수령"

7. 계좌비밀번호 동일 (true/false):
   - "동일", "같게", "똑같이" → true
   - "다르게", "별도", "새로" → false

8. 카드사용알림 (true/false):
   - "알림", "받을게", "설정" → true
   - "안받", "필요없" → false

중요 원칙:
- 사용자가 말하지 않은 정보는 절대 추출하지 말 것
- 기본값이나 추론값을 넣지 말 것
- 명시적으로 언급된 정보만 추출

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
            print(f"[CCAgent] LLM analysis error: {e}")
            return {"error": str(e)}
    
    def _identify_missing_info(
        self, 
        extracted_info: Dict[str, Any], 
        current_info: Dict[str, Any],
        required_fields: List[Dict[str, Any]]
    ) -> List[str]:
        """누락된 필수 정보 파악"""
        missing = []
        
        # 체크카드 가입이 true인 경우에만 관련 정보 요구
        if current_info.get("use_check_card") == True:
            required_cc_fields = [
                "card_receive_method",
                "card_type"
            ]
            
            # 배송인 경우에만 배송지 필요
            if extracted_info.get("card_receive_method") == "배송" or current_info.get("card_receive_method") == "배송":
                required_cc_fields.append("card_delivery_location")
            
            # 선택적 필드들도 체크 (사용자가 언급하지 않으면 누락으로 표시하지 않음)
            optional_fields = [
                "postpaid_transport",
                "payment_date", 
                "statement_method",
                "same_password_as_account",
                "card_usage_alert"
            ]
            
            for field_key in required_cc_fields:
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
            return "체크카드 설정에 필요한 정보를 말씀해주세요. 카드 수령 방법, 카드 종류, 후불교통 기능 등을 알려주시면 됩니다."
        
        messages = []
        
        # 성공적으로 추출된 정보 확인
        if extracted_info:
            confirmations = []
            for field, value in extracted_info.items():
                if field == "card_receive_method":
                    confirmations.append(f"카드 수령: {value}")
                elif field == "card_delivery_location":
                    confirmations.append(f"배송지: {value}")
                elif field == "card_type":
                    confirmations.append(f"카드 종류: {value}")
                elif field == "postpaid_transport":
                    confirmations.append(f"후불교통: {'사용' if value else '미사용'}")
                elif field == "payment_date":
                    confirmations.append(f"결제일: 매월 {value}일")
                elif field == "statement_method":
                    confirmations.append(f"명세서: {value}로 수령")
                elif field == "same_password_as_account":
                    confirmations.append(f"계좌 비밀번호: {'동일' if value else '별도'}")
                elif field == "card_usage_alert":
                    confirmations.append(f"카드사용알림: {'설정' if value else '미설정'}")
            
            if confirmations:
                messages.append(f"네, {', '.join(confirmations)}로 확인했습니다.")
        
        # 누락된 정보 요청
        if missing_info:
            missing_requests = []
            for field in missing_info:
                if field == "card_receive_method":
                    missing_requests.append("카드 수령 방법 (즉시발급/배송)")
                elif field == "card_delivery_location":
                    missing_requests.append("카드 배송지 (자택/직장/지점)")
                elif field == "card_type":
                    missing_requests.append("카드 종류 (S-line/딥드림)")
                elif field == "postpaid_transport":
                    missing_requests.append("후불교통 기능 사용 여부")
                elif field == "payment_date":
                    missing_requests.append("결제일 (1일~30일)")
                elif field == "statement_method":
                    missing_requests.append("명세서 수령 방법 (이메일/문자/우편/미수령)")
                elif field == "same_password_as_account":
                    missing_requests.append("계좌 비밀번호와 동일하게 사용 여부")
                elif field == "card_usage_alert":
                    missing_requests.append("카드사용알림 설정 여부")
            
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
            "card_receive_method": 0.25,
            "card_delivery_location": 0.15,
            "card_type": 0.25,
            "postpaid_transport": 0.1,
            "payment_date": 0.1,
            "statement_method": 0.05,
            "same_password_as_account": 0.05,
            "card_usage_alert": 0.05
        }
        
        for field, value in extracted_info.items():
            weight = field_weights.get(field, 0.1)
            total_weight += weight
            
            # 필드별 신뢰도 계산
            if field in ["card_receive_method", "card_delivery_location", "card_type", "statement_method"]:
                # 정확한 선택지 매칭
                confidence += weight * 0.95
            elif field == "payment_date" and isinstance(value, int) and 1 <= value <= 30:
                # 유효한 날짜 범위
                confidence += weight * 0.9
            elif field in ["postpaid_transport", "same_password_as_account", "card_usage_alert"]:
                # Boolean 값
                confidence += weight * 0.85
            else:
                confidence += weight * 0.7
        
        return min(confidence / total_weight if total_weight > 0 else 0.1, 1.0)


# 전역 인스턴스
check_card_agent = CheckCardAgent()