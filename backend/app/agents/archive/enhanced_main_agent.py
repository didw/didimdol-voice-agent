"""
Enhanced Main Agent - 중앙 오케스트레이터 + QA 처리
"""

import json
from typing import Dict, Any, Optional, Tuple
from langchain_core.messages import HumanMessage
from ..graph.chains import json_llm
from ..graph.simple_scenario_engine import simple_scenario_engine
from ..agents.entity_agent import entity_agent
from ..services.rag_service import rag_service


class EnhancedMainAgent:
    """개선된 메인 에이전트 - 시나리오 관리 + QA 처리 + Slot Filling 오케스트레이션"""
    
    def __init__(self):
        self.decision_prompt = self._get_decision_prompt()
    
    def _get_decision_prompt(self) -> str:
        """입력 분류 및 의사결정 프롬프트"""
        return """당신은 은행 입출금통장 개설 상담의 중앙 관리자입니다.

**현재 상황:**
- 진행 단계: {current_stage} ({stage_description})
- 고객 입력: "{user_input}"
- 수집된 정보: {collected_info}
- 시나리오 매뉴얼: {manual_info}

**현재 단계에서 할 일:**
{stage_instructions}

**고객 입력 분류 및 처리 방법:**

1. **DIRECT_QA** - 매뉴얼로 바로 답변 가능한 간단한 질문
   - 수수료, 소요시간, 필요서류 등 기본 정보
   - 즉시 답변 후 원래 단계 계속 진행

2. **COMPLEX_QA** - 복잡한 금융 상품 질문 (RAG 검색 필요)
   - 금리, 이자, 투자, 대출 조건 등 상세 정보
   - QA Tool을 통한 검색 후 답변

3. **SLOT_FILLING** - 현재 단계에서 필요한 정보 제공
   - 이름, 연락처, 선택사항 등 수집해야 할 정보
   - Entity Agent를 통한 정보 추출 및 저장

4. **STAGE_PROGRESSION** - 단계 진행 관련 응답
   - "네", "아니요", "다음" 등 진행 의사 표현
   - 다음 단계로 이동 처리

5. **CLARIFICATION** - 불명확하거나 예상치 못한 입력
   - 재질의 또는 안내 필요

**의사결정 규칙:**
- 현재 단계가 slot_filling이고 필요한 정보가 포함되어 있으면 → SLOT_FILLING
- 간단한 QA 키워드(수수료, 시간, 서류)가 포함되어 있으면 → DIRECT_QA  
- 복잡한 금융 키워드(금리, 투자, 대출)가 포함되어 있으면 → COMPLEX_QA
- yes/no 질문에 대한 명확한 답변이면 → STAGE_PROGRESSION
- 그 외는 → CLARIFICATION

**출력 형식:**
{{
  "action": "DIRECT_QA|COMPLEX_QA|SLOT_FILLING|STAGE_PROGRESSION|CLARIFICATION",
  "reasoning": "선택 이유",
  "direct_answer": "DIRECT_QA인 경우 답변 내용",
  "next_stage": "STAGE_PROGRESSION인 경우 다음 단계",
  "clarification_message": "CLARIFICATION인 경우 재질의 내용"
}}"""

    async def process_user_input(
        self, 
        user_input: str, 
        current_stage: str, 
        collected_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """사용자 입력 종합 처리"""
        
        print(f"[EnhancedMainAgent] Processing: '{user_input}' at stage '{current_stage}'")
        
        # 1단계: 입력 분류 및 의사결정
        decision = await self._classify_input(user_input, current_stage, collected_info)
        action = decision.get("action", "CLARIFICATION")
        
        print(f"[EnhancedMainAgent] Decision: {action}")
        
        # 2단계: 액션별 처리
        if action == "DIRECT_QA":
            return await self._handle_direct_qa(user_input, decision, current_stage)
        
        elif action == "COMPLEX_QA":
            return await self._handle_complex_qa(user_input, current_stage)
        
        elif action == "SLOT_FILLING":
            return await self._handle_slot_filling(user_input, current_stage, collected_info)
        
        elif action == "STAGE_PROGRESSION":
            return await self._handle_stage_progression(user_input, current_stage, decision)
        
        else:  # CLARIFICATION
            return await self._handle_clarification(user_input, decision, current_stage)
    
    async def _classify_input(
        self, 
        user_input: str, 
        current_stage: str, 
        collected_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """입력 분류 및 의사결정"""
        
        stage_info = simple_scenario_engine.get_current_stage_info(current_stage)
        stage_type = stage_info.get("type", "")
        
        # 단계별 지시사항 생성
        if stage_type == "slot_filling":
            required_fields = simple_scenario_engine.get_required_fields_for_stage(current_stage)
            field_names = [f['display_name'] for f in required_fields]
            stage_instructions = f"현재 수집해야 할 정보: {', '.join(field_names)}"
        elif stage_type == "yes_no_question":
            stage_instructions = f"예/아니요 질문에 대한 고객의 답변을 기다리는 중입니다: {stage_info.get('message', '')}"
        else:
            stage_instructions = "일반적인 상담 진행 중입니다."
        
        prompt = self.decision_prompt.format(
            current_stage=current_stage,
            stage_description=stage_type,
            user_input=user_input,
            collected_info=json.dumps(collected_info, ensure_ascii=False),
            manual_info=json.dumps(simple_scenario_engine.manual, ensure_ascii=False),
            stage_instructions=stage_instructions
        )
        
        try:
            response = await json_llm.ainvoke([HumanMessage(content=prompt)])
            result = json.loads(response.content)
            return result
        except Exception as e:
            print(f"[EnhancedMainAgent] Classification error: {e}")
            return {
                "action": "CLARIFICATION",
                "reasoning": f"분류 오류: {str(e)}",
                "clarification_message": "죄송합니다. 다시 한 번 말씀해주시겠어요?"
            }
    
    async def _handle_direct_qa(
        self, 
        user_input: str, 
        decision: Dict[str, Any], 
        current_stage: str
    ) -> Dict[str, Any]:
        """간단한 QA 직접 처리"""
        
        # 매뉴얼 기반 답변 시도
        simple_answer = simple_scenario_engine.answer_simple_question(user_input)
        
        if simple_answer:
            answer = simple_answer
        else:
            answer = decision.get("direct_answer", "관련 정보를 찾을 수 없습니다.")
        
        # 답변 후 원래 단계 계속 진행을 위한 안내 추가
        stage_info = simple_scenario_engine.get_current_stage_info(current_stage)
        if stage_info.get("type") == "slot_filling":
            stage_message = simple_scenario_engine.get_stage_message(current_stage)
            answer += f"\n\n{stage_message}"
        
        return {
            "type": "direct_qa_response",
            "message": answer,
            "continue_stage": current_stage,
            "collected_info": {}  # 정보 변경 없음
        }
    
    async def _handle_complex_qa(self, user_input: str, current_stage: str) -> Dict[str, Any]:
        """복잡한 QA - RAG 시스템 사용"""
        
        try:
            # RAG 서비스를 통한 검색 및 답변
            rag_result = await rag_service.search_and_answer(
                query=user_input,
                context="입출금통장 개설 상담"
            )
            
            answer = rag_result.get("answer", "관련 정보를 찾을 수 없습니다.")
            
            # 답변 후 원래 단계 계속 진행 안내
            stage_info = simple_scenario_engine.get_current_stage_info(current_stage)
            if stage_info.get("type") == "slot_filling":
                stage_message = simple_scenario_engine.get_stage_message(current_stage)
                answer += f"\n\n{stage_message}"
            
            return {
                "type": "complex_qa_response",
                "message": answer,
                "continue_stage": current_stage,
                "collected_info": {},
                "rag_sources": rag_result.get("sources", [])
            }
            
        except Exception as e:
            print(f"[EnhancedMainAgent] RAG error: {e}")
            return {
                "type": "qa_error",
                "message": "죄송합니다. 정보 검색 중 오류가 발생했습니다. 다시 질문해주시겠어요?",
                "continue_stage": current_stage,
                "collected_info": {}
            }
    
    async def _handle_slot_filling(
        self, 
        user_input: str, 
        current_stage: str, 
        collected_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Slot Filling 처리"""
        
        required_fields = simple_scenario_engine.get_required_fields_for_stage(current_stage)
        
        if not required_fields:
            return {
                "type": "slot_filling_error",
                "message": "현재 단계에서 수집할 정보가 없습니다.",
                "continue_stage": current_stage,
                "collected_info": collected_info
            }
        
        # Entity Agent를 통한 정보 추출
        slot_result = await entity_agent.process_slot_filling(
            user_input=user_input,
            required_fields=required_fields,
            collected_info=collected_info
        )
        
        new_collected_info = slot_result["collected_info"]
        missing_fields = slot_result["missing_fields"]
        is_complete = slot_result["is_complete"]
        
        if is_complete:
            # 단계 완료 - 다음 단계로 진행
            next_stage = simple_scenario_engine.get_next_stage(current_stage)
            completion_message = simple_scenario_engine.get_current_stage_info(current_stage).get("completion_message", "")
            next_stage_message = simple_scenario_engine.get_stage_message(next_stage, new_collected_info)
            
            message = completion_message
            if next_stage_message:
                message += f"\n\n{next_stage_message}"
            
            return {
                "type": "slot_filling_complete",
                "message": message,
                "next_stage": next_stage,
                "collected_info": new_collected_info,
                "completed_fields": slot_result["valid_entities"]
            }
        
        else:
            # 정보 부족 - 재질의
            prompt_message = entity_agent.generate_missing_info_prompt(missing_fields)
            
            # 유효하게 수집된 정보가 있으면 확인 메시지 추가
            if slot_result["valid_entities"]:
                confirmed_fields = []
                for key, value in slot_result["valid_entities"].items():
                    field_info = simple_scenario_engine.get_field_display_info(key)
                    display_name = field_info.get("display_name", key)
                    confirmed_fields.append(f"{display_name}: {value}")
                
                message = f"다음 정보를 확인했습니다: {', '.join(confirmed_fields)}.\n\n{prompt_message}"
            else:
                message = prompt_message
            
            return {
                "type": "slot_filling_incomplete",
                "message": message,
                "continue_stage": current_stage,
                "collected_info": new_collected_info,
                "missing_fields": [f["key"] for f in missing_fields]
            }
    
    async def _handle_stage_progression(
        self, 
        user_input: str, 
        current_stage: str, 
        decision: Dict[str, Any]
    ) -> Dict[str, Any]:
        """단계 진행 처리"""
        
        next_stage = simple_scenario_engine.get_next_stage(current_stage, user_input)
        
        if next_stage == current_stage:
            # 단계 변경 없음 - 명확하지 않은 답변
            return {
                "type": "stage_clarification",
                "message": "예 또는 아니요로 명확히 답변해주시겠어요?",
                "continue_stage": current_stage,
                "collected_info": {}
            }
        
        # 다음 단계로 진행
        next_stage_message = simple_scenario_engine.get_stage_message(next_stage)
        
        return {
            "type": "stage_progression",
            "message": next_stage_message,
            "next_stage": next_stage,
            "collected_info": {}
        }
    
    async def _handle_clarification(
        self, 
        user_input: str, 
        decision: Dict[str, Any], 
        current_stage: str
    ) -> Dict[str, Any]:
        """불명확한 입력 처리"""
        
        clarification_message = decision.get(
            "clarification_message", 
            "죄송합니다. 이해하지 못했습니다. 다시 말씀해주시겠어요?"
        )
        
        # 현재 단계의 가이드 메시지 추가
        stage_info = simple_scenario_engine.get_current_stage_info(current_stage)
        if stage_info.get("type") == "slot_filling":
            stage_message = simple_scenario_engine.get_stage_message(current_stage)
            clarification_message += f"\n\n{stage_message}"
        
        return {
            "type": "clarification",
            "message": clarification_message,
            "continue_stage": current_stage,
            "collected_info": {}
        }


# 전역 인스턴스
enhanced_main_agent = EnhancedMainAgent()