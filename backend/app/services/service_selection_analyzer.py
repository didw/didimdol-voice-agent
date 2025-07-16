"""
LLM 기반 부가서비스 선택 분석기
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from langchain_core.messages import HumanMessage
from ..core.config import LLM_MODEL_NAME
from ..graph.chains import json_llm


class ServiceSelectionAnalyzer:
    """부가서비스 선택을 LLM으로 분석하는 클래스"""
    
    def __init__(self):
        self.prompts = self._get_hardcoded_prompts()
    
    def _get_hardcoded_prompts(self) -> Dict[str, str]:
        """하드코딩된 프롬프트 (yaml 의존성 회피)"""
        return {
            "analyze_additional_services_choice": """당신은 은행 고객의 부가서비스 선택 의도를 정확히 분석하는 전문가입니다.

**상황:** 
고객이 입출금통장 개설 시 체크카드와 인터넷뱅킹 서비스 신청 여부를 묻는 질문에 답변했습니다.

**원래 질문:**
"혹시 체크카드나 인터넷뱅킹도 함께 신청하시겠어요? (예: 둘 다 신청, 체크카드만, 인터넷뱅킹만, 아니요)"

**고객 답변:**
"{user_input}"

**분석 과제:**
고객의 답변을 분석하여 다음 중 정확히 어느 의도에 해당하는지 판단하세요:

1. **BOTH** - 체크카드와 인터넷뱅킹을 모두 신청하고 싶음
   - 예시: "둘다", "둘 다요", "모두 신청해주세요", "체크카드랑 인터넷뱅킹 다 해주세요", "네, 둘 다 필요해요"

2. **CARD_ONLY** - 체크카드만 신청하고 싶음
   - 예시: "체크카드만", "카드만 있으면 돼요", "체크카드는 필요해요", "카드 하나만"

3. **BANKING_ONLY** - 인터넷뱅킹만 신청하고 싶음
   - 예시: "인터넷뱅킹만", "온라인 뱅킹만", "인뱅만", "모바일뱅킹만 해주세요"

4. **NONE** - 부가서비스를 신청하지 않음
   - 예시: "아니요", "필요없어요", "괜찮아요", "나중에 할게요", "기본 통장만"

5. **UNCLEAR** - 의도가 불분명하거나 다른 질문을 하는 경우
   - 예시: "뭐가 좋을까요?", "차이점이 뭔가요?", "수수료는 얼마인가요?"

**중요 지침:**
- 고객의 **진짜 의도**를 파악하세요. 단순 키워드 매칭이 아닌 문맥상 의미를 이해하세요.
- 애매한 표현("네", "좋아요")의 경우 UNCLEAR로 분류하세요.
- 질문이나 추가 정보 요청은 UNCLEAR로 분류하세요.
- 확실하지 않으면 UNCLEAR를 선택하세요.

**출력 형식:**
반드시 다음 JSON 형식으로만 응답하세요:

{{
  "choice": "BOTH|CARD_ONLY|BANKING_ONLY|NONE|UNCLEAR",
  "confidence": 0.0-1.0,
  "reasoning": "판단 근거를 한 문장으로 설명"
}}""",

            "normalize_additional_services_value": """사용자의 부가서비스 선택을 표준화된 값으로 변환하세요.

**입력:**
- 분석 결과: {analysis_result}
- 원본 사용자 입력: "{user_input}"

**변환 규칙:**
- BOTH → "둘 다 신청"
- CARD_ONLY → "체크카드만"  
- BANKING_ONLY → "인터넷뱅킹만"
- NONE → "아니요"
- UNCLEAR → null (값을 설정하지 않음)

**출력 형식:**
{{
  "normalized_value": "표준화된 값 또는 null",
  "should_clarify": true/false,
  "clarification_needed": "명확화가 필요한 경우 이유"
}}""",

            "determine_next_stage_smart": """입출금통장 상담에서 부가서비스 선택에 따른 다음 단계를 지능적으로 결정하세요.

**현재 상황:**
- 고객이 부가서비스 선택을 완료했습니다.
- 수집된 정보: {collected_info}
- 부가서비스 선택: "{additional_services_choice}"

**가능한 다음 단계:**
1. **ask_cc_issuance_method** - 체크카드 관련 설정 질문
   - 조건: 체크카드 신청이 포함된 경우
   
2. **ask_ib_notification** - 인터넷뱅킹 관련 설정 질문
   - 조건: 인터넷뱅킹만 신청한 경우
   
3. **final_summary_deposit** - 최종 요약 및 확인
   - 조건: 부가서비스를 신청하지 않은 경우
   
4. **clarify_services** - 서비스 선택 재확인
   - 조건: 선택이 불분명한 경우

**결정 로직:**
- "둘 다 신청" 또는 "체크카드만" → ask_cc_issuance_method (체크카드부터 설정)
- "인터넷뱅킹만" → ask_ib_notification
- "아니요" → final_summary_deposit
- null 또는 불분명 → clarify_services

**출력 형식:**
{{
  "next_stage_id": "선택된 다음 단계 ID",
  "reasoning": "선택 근거"
}}"""
        }
    
    async def analyze_additional_services_choice(self, user_input: str) -> Dict[str, Any]:
        """
        사용자 입력을 분석하여 부가서비스 선택 의도를 파악
        
        Args:
            user_input: 사용자의 원본 입력
            
        Returns:
            분석 결과 딕셔너리 {choice, confidence, reasoning}
        """
        prompt_template = self.prompts.get("analyze_additional_services_choice", "")
        if not prompt_template:
            return {"choice": "UNCLEAR", "confidence": 0.0, "reasoning": "프롬프트 로드 실패"}
        
        prompt = prompt_template.format(user_input=user_input)
        
        try:
            response = await json_llm.ainvoke([HumanMessage(content=prompt)])
            result = json.loads(response.content)
            
            # 결과 검증
            valid_choices = ["BOTH", "CARD_ONLY", "BANKING_ONLY", "NONE", "UNCLEAR"]
            if result.get("choice") not in valid_choices:
                result["choice"] = "UNCLEAR"
                
            if not isinstance(result.get("confidence"), (int, float)):
                result["confidence"] = 0.5
                
            return result
            
        except Exception as e:
            print(f"Error analyzing service choice: {e}")
            return {"choice": "UNCLEAR", "confidence": 0.0, "reasoning": f"분석 오류: {str(e)}"}
    
    async def normalize_additional_services_value(
        self, 
        analysis_result: Dict[str, Any], 
        user_input: str
    ) -> Dict[str, Any]:
        """
        분석 결과를 표준화된 값으로 변환
        
        Args:
            analysis_result: analyze_additional_services_choice 결과
            user_input: 원본 사용자 입력
            
        Returns:
            정규화 결과 {normalized_value, should_clarify, clarification_needed}
        """
        prompt_template = self.prompts.get("normalize_additional_services_value", "")
        if not prompt_template:
            return {"normalized_value": None, "should_clarify": True, "clarification_needed": "프롬프트 로드 실패"}
        
        prompt = prompt_template.format(
            analysis_result=json.dumps(analysis_result, ensure_ascii=False),
            user_input=user_input
        )
        
        try:
            response = await json_llm.ainvoke([HumanMessage(content=prompt)])
            result = json.loads(response.content)
            
            return result
            
        except Exception as e:
            print(f"Error normalizing service value: {e}")
            return {"normalized_value": None, "should_clarify": True, "clarification_needed": f"정규화 오류: {str(e)}"}
    
    async def determine_next_stage_smart(
        self, 
        additional_services_choice: str, 
        collected_info: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        부가서비스 선택에 따른 다음 단계를 지능적으로 결정
        
        Args:
            additional_services_choice: 표준화된 부가서비스 선택 값
            collected_info: 현재까지 수집된 정보
            
        Returns:
            다음 단계 결정 {next_stage_id, reasoning}
        """
        prompt_template = self.prompts.get("determine_next_stage_smart", "")
        if not prompt_template:
            return {"next_stage_id": "final_summary_deposit", "reasoning": "프롬프트 로드 실패"}
        
        prompt = prompt_template.format(
            additional_services_choice=additional_services_choice,
            collected_info=json.dumps(collected_info, ensure_ascii=False)
        )
        
        try:
            response = await json_llm.ainvoke([HumanMessage(content=prompt)])
            result = json.loads(response.content)
            
            # 유효한 단계 ID 확인
            valid_stages = [
                "ask_cc_issuance_method", 
                "ask_ib_notification", 
                "final_summary_deposit", 
                "clarify_services"
            ]
            
            if result.get("next_stage_id") not in valid_stages:
                result["next_stage_id"] = "final_summary_deposit"
                result["reasoning"] = "유효하지 않은 단계 ID로 인한 기본값 설정"
            
            return result
            
        except Exception as e:
            print(f"Error determining next stage: {e}")
            return {"next_stage_id": "final_summary_deposit", "reasoning": f"단계 결정 오류: {str(e)}"}
    
    async def process_additional_services_input(
        self, 
        user_input: str, 
        collected_info: Dict[str, Any]
    ) -> Tuple[Optional[str], str, Dict[str, Any]]:
        """
        부가서비스 입력을 종합적으로 처리
        
        Args:
            user_input: 사용자 입력
            collected_info: 현재까지 수집된 정보
            
        Returns:
            (normalized_value, next_stage_id, processing_info)
        """
        print(f"[ServiceSelectionAnalyzer] Processing input: '{user_input}'")
        
        # 1단계: 의도 분석
        analysis_result = await self.analyze_additional_services_choice(user_input)
        print(f"[ServiceSelectionAnalyzer] Analysis: {analysis_result}")
        
        # 2단계: 값 정규화
        normalization_result = await self.normalize_additional_services_value(analysis_result, user_input)
        print(f"[ServiceSelectionAnalyzer] Normalization: {normalization_result}")
        
        normalized_value = normalization_result.get("normalized_value")
        
        # 3단계: 다음 단계 결정
        if normalized_value:
            stage_result = await self.determine_next_stage_smart(normalized_value, collected_info)
            next_stage_id = stage_result.get("next_stage_id")
        else:
            # 명확화가 필요한 경우
            next_stage_id = "clarify_services"
            stage_result = {"reasoning": "사용자 선택이 불분명하여 재확인 필요"}
        
        print(f"[ServiceSelectionAnalyzer] Next stage: {next_stage_id}")
        
        # 처리 정보 통합
        processing_info = {
            "analysis": analysis_result,
            "normalization": normalization_result,
            "stage_decision": stage_result,
            "confidence": analysis_result.get("confidence", 0.0)
        }
        
        return normalized_value, next_stage_id, processing_info


# 전역 인스턴스
service_selection_analyzer = ServiceSelectionAnalyzer()