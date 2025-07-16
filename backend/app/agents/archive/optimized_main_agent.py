"""
최적화된 Main Agent - 통합 지식베이스 + 병렬 처리
"""

import asyncio
import json
from typing import Dict, Any, Optional, List, Tuple
from langchain_core.messages import HumanMessage
from ..graph.chains import json_llm, generative_llm
from ..graph.simple_scenario_engine import simple_scenario_engine
from ..services.rag_service import rag_service


class OptimizedMainAgent:
    """최적화된 메인 에이전트 - 빠른 응답과 병렬 처리"""
    
    def __init__(self):
        self.unified_knowledge = self._load_unified_knowledge()
        self.unified_prompt = self._get_unified_prompt()
    
    def _load_unified_knowledge(self) -> Dict[str, Any]:
        """시나리오와 매뉴얼 통합 로드"""
        # scenario.json의 manual
        scenario_manual = simple_scenario_engine.manual
        
        # deposit_account.md의 주요 내용 (실제로는 파일에서 로드)
        detailed_knowledge = {
            "한도제한계좌": {
                "정의": "금융거래 목적 확인 전까지 1일 출금 및 이체 한도가 제한되는 계좌",
                "제한내용": "ATM 인출/이체 각 30만원~100만원 이하",
                "해제조건": "급여소득자는 재직증명서, 사업자는 사업자등록증명원 제출"
            },
            "평생계좌": {
                "정의": "고객이 기억하기 쉬운 자신만의 번호를 계좌에 부여하는 서비스",
                "신청방법": "영업점 방문 또는 인터넷/모바일뱅킹에서 신청",
                "주의사항": "휴대폰 번호 변경 시 평생계좌번호도 변경 필요"
            }
        }
        
        return {
            "quick_answers": {**scenario_manual.get("common_questions", {}), **detailed_knowledge},
            "process_info": scenario_manual.get("process_steps", ""),
            "service_overview": scenario_manual.get("service_overview", "")
        }
    
    def _get_unified_prompt(self) -> str:
        """통합 프롬프트"""
        return """당신은 신한은행 입출금통장 개설 상담 AI입니다.

## 즉시 답변 가능한 정보
{quick_knowledge}

## 현재 상황
- 시나리오 단계: {current_stage} ({stage_type})
- 수집된 정보: {collected_info}
- 필요한 정보: {required_fields}

## 처리 방침
1. **즉시 답변**: 사용자 질문이 '즉시 답변 가능한 정보'에 있다면 해당 내용으로 바로 답변
2. **정보 수집**: 현재 단계에서 필요한 정보가 포함되어 있다면 추출하여 저장
3. **시나리오 진행**: yes/no 질문에 대한 답변이면 다음 단계로 진행
4. **상세 검색**: 즉시 답변이 어려운 복잡한 질문은 RAG 결과 활용
5. **재질의**: 불명확한 경우 구체적으로 재질의

## 사용자 입력
"{user_input}"

## 병렬 처리 결과
- 추출된 정보: {extracted_entities}
- 의도 분류: {classified_intent}
- RAG 검색: {rag_results}

## 응답 형식
{{
  "response_type": "direct_answer|slot_filling|stage_progression|rag_answer|clarification",
  "message": "사용자에게 전달할 메시지",
  "collected_info": {{}},  // 새로 수집된 정보
  "next_stage": "다음 단계 ID (해당시)",
  "confidence": 0.0-1.0
}}"""
    
    def check_quick_answer(self, user_input: str) -> Optional[str]:
        """즉시 답변 가능한지 체크 (동기 처리)"""
        user_input_lower = user_input.lower()
        
        # 키워드 매칭으로 빠른 답변 체크
        for keyword, answer in self.unified_knowledge["quick_answers"].items():
            if keyword in user_input_lower:
                return answer
        
        return None
    
    async def extract_entities(self, user_input: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """엔티티 추출 (비동기)"""
        current_stage = context.get("current_stage", "")
        required_fields = simple_scenario_engine.get_required_fields_for_stage(current_stage)
        
        if not required_fields:
            return {}
        
        # 간단한 패턴 매칭 (실제로는 EntityAgent 사용)
        extracted = {}
        
        # 이름 추출
        name_pattern = r"([가-힣]{2,4})(?:입니다|이에요|예요)"
        if "customer_name" in [f["key"] for f in required_fields]:
            import re
            match = re.search(name_pattern, user_input)
            if match:
                extracted["customer_name"] = match.group(1)
        
        # 전화번호 추출
        phone_pattern = r"(010[-\s]?\d{4}[-\s]?\d{4})"
        if "phone_number" in [f["key"] for f in required_fields]:
            import re
            match = re.search(phone_pattern, user_input)
            if match:
                extracted["phone_number"] = match.group(1).replace(" ", "").replace("-", "")
        
        return extracted
    
    async def classify_intent(self, user_input: str, context: Dict[str, Any]) -> str:
        """의도 분류 (비동기)"""
        user_input_lower = user_input.lower().strip()
        
        # 간단한 규칙 기반 분류
        if user_input_lower in ["네", "예", "좋아요", "할게요"]:
            return "긍정"
        elif user_input_lower in ["아니요", "아니에요", "안해요"]:
            return "부정"
        elif any(q in user_input_lower for q in ["뭐", "무엇", "어떻게", "얼마"]):
            return "질문"
        else:
            return "정보제공"
    
    async def search_rag(self, user_input: str) -> Optional[Dict[str, Any]]:
        """RAG 검색 (비동기)"""
        try:
            # 실제로는 rag_service 사용
            # result = await rag_service.answer_question(user_input)
            # 여기서는 시뮬레이션
            return {
                "answer": "RAG 검색 결과입니다.",
                "confidence": 0.8
            }
        except Exception as e:
            print(f"RAG search error: {e}")
            return None
    
    async def generate_final_response(
        self,
        user_input: str,
        quick_answer: Optional[str],
        entities: Dict[str, Any],
        intent: str,
        rag_result: Optional[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """최종 응답 생성"""
        
        current_stage = context.get("current_stage", "")
        stage_info = simple_scenario_engine.get_current_stage_info(current_stage)
        stage_type = stage_info.get("type", "")
        
        # 1. 즉시 답변 가능한 경우
        if quick_answer:
            return {
                "response_type": "direct_answer",
                "message": quick_answer,
                "collected_info": {},
                "continue_stage": current_stage,
                "confidence": 1.0
            }
        
        # 2. Slot filling 단계에서 정보 추출된 경우
        if stage_type == "slot_filling" and entities:
            required_fields = simple_scenario_engine.get_required_fields_for_stage(current_stage)
            missing_fields = [f for f in required_fields 
                            if f["required"] and f["key"] not in {**context.get("collected_info", {}), **entities}]
            
            if not missing_fields:
                # 모든 정보 수집 완료
                next_stage = simple_scenario_engine.get_next_stage(current_stage)
                return {
                    "response_type": "slot_filling",
                    "message": "네, 확인했습니다. " + simple_scenario_engine.get_stage_message(next_stage),
                    "collected_info": entities,
                    "next_stage": next_stage,
                    "confidence": 0.9
                }
            else:
                # 추가 정보 필요
                missing_names = [f["display_name"] for f in missing_fields]
                return {
                    "response_type": "slot_filling",
                    "message": f"네, 확인했습니다. 추가로 {', '.join(missing_names)}을(를) 알려주세요.",
                    "collected_info": entities,
                    "continue_stage": current_stage,
                    "confidence": 0.9
                }
        
        # 3. Yes/No 질문에 대한 답변
        if stage_type == "yes_no_question" and intent in ["긍정", "부정"]:
            next_stage = simple_scenario_engine.get_next_stage(current_stage, user_input)
            return {
                "response_type": "stage_progression",
                "message": simple_scenario_engine.get_stage_message(next_stage),
                "collected_info": {},
                "next_stage": next_stage,
                "confidence": 0.95
            }
        
        # 4. RAG 결과가 있는 경우
        if rag_result and rag_result.get("confidence", 0) > 0.7:
            return {
                "response_type": "rag_answer",
                "message": rag_result["answer"],
                "collected_info": {},
                "continue_stage": current_stage,
                "confidence": rag_result["confidence"]
            }
        
        # 5. 불명확한 경우
        return {
            "response_type": "clarification",
            "message": "죄송합니다. 다시 한 번 말씀해주시겠어요?",
            "collected_info": {},
            "continue_stage": current_stage,
            "confidence": 0.3
        }
    
    async def process_user_input(
        self,
        user_input: str,
        current_stage: str,
        collected_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """최적화된 사용자 입력 처리 - 메인 엔트리포인트"""
        
        context = {
            "current_stage": current_stage,
            "collected_info": collected_info
        }
        
        # 1. 즉시 답변 체크 (동기)
        quick_answer = self.check_quick_answer(user_input)
        
        # 2. 병렬 도구 호출 준비
        tasks = []
        
        # 항상 실행되는 도구들
        tasks.append(self.extract_entities(user_input, context))
        tasks.append(self.classify_intent(user_input, context))
        
        # 조건부 실행 (quick_answer가 없을 때만)
        if not quick_answer:
            tasks.append(self.search_rag(user_input))
        
        # 3. 비동기 병렬 실행
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 4. 결과 언패킹
        entities = results[0] if not isinstance(results[0], Exception) else {}
        intent = results[1] if not isinstance(results[1], Exception) else "unknown"
        rag_result = results[2] if len(results) > 2 and not isinstance(results[2], Exception) else None
        
        # 5. 최종 응답 생성
        return await self.generate_final_response(
            user_input=user_input,
            quick_answer=quick_answer,
            entities=entities,
            intent=intent,
            rag_result=rag_result,
            context=context
        )


# 전역 인스턴스
optimized_main_agent = OptimizedMainAgent()