# backend/app/agents/info_modification_agent.py
"""
정보 수정/변경 Agent - 고객의 자연스러운 수정 요청을 지능적으로 파악하고 처리
"""

import re
from typing import Dict, Any, Optional, List, Tuple
from ..graph.chains import generative_llm


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
        print(f"[InfoModAgent] Current info: {current_info}")
        
        # 1. 패턴 기반 매칭
        pattern_matches = self._extract_using_patterns(user_input)
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
    
    def _extract_using_patterns(self, user_input: str) -> Dict[str, Any]:
        """패턴 기반 정보 추출"""
        matches = {}
        
        for field_key, patterns in self.field_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, user_input, re.IGNORECASE)
                if match:
                    if field_key == "customer_phone":
                        # 전화번호 특별 처리
                        phone_value = self._process_phone_match(match, user_input)
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

분석해야 할 사항:
1. 고객이 어떤 정보를 수정하려고 하는지
2. 새로운 값이 무엇인지
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
        
        # 2. LLM 분석 결과 적용
        if "target_field" in llm_analysis and "new_value" in llm_analysis:
            field = llm_analysis["target_field"]
            value = llm_analysis["new_value"]
            
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
                suggestions.append(f"연락처를 '{old_value}'에서 '{new_value}'로 변경하시겠어요?")
            elif field == "customer_name":
                suggestions.append(f"성함을 '{old_value}'에서 '{new_value}'로 변경하시겠어요?")
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