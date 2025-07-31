"""
간소화된 시나리오 엔진 - 8단계 선형 프로세스
"""

import json
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path


class SimpleScenarioEngine:
    """간소화된 시나리오 처리 엔진"""
    
    def __init__(self, scenario_data: Dict[str, Any] = None):
        if scenario_data:
            self.scenario_data = scenario_data
        else:
            self.scenario_data = self._load_scenario()
        self.manual = self.scenario_data.get("manual", {})
    
    def _load_scenario(self) -> Dict[str, Any]:
        """간소화된 시나리오 JSON 로드"""
        scenario_path = Path(__file__).parent.parent / "data" / "scenarios" / "deposit_account_scenario_v3.json"
        
        try:
            with open(scenario_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading simple scenario: {e}")
            return {}
    
    def get_current_stage_info(self, stage_id: str) -> Dict[str, Any]:
        """현재 단계 정보 조회"""
        return self.scenario_data.get("stages", {}).get(stage_id, {})
    
    def get_required_fields_for_stage(self, stage_id: str) -> List[Dict[str, Any]]:
        """특정 단계의 필수 필드 조회"""
        all_fields = self.scenario_data.get("slot_fields", [])
        return [field for field in all_fields if field.get("stage") == stage_id]
    
    def check_stage_completion(self, stage_id: str, collected_info: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """단계 완료 여부 확인"""
        # final_confirmation 단계는 특별 처리
        if stage_id == "final_confirmation":
            # final_confirmation 필드가 True로 설정되어 있으면 완료
            final_confirmation = collected_info.get("final_confirmation")
            if final_confirmation is True:
                return True, []
            else:
                return False, ["final_confirmation"]
        
        required_fields = self.get_required_fields_for_stage(stage_id)
        missing_fields = []
        
        for field in required_fields:
            field_key = field["key"]
            
            # 의존성 체크
            if "depends_on" in field:
                depends_on = field["depends_on"]
                dependent_field = depends_on["field"]
                required_value = depends_on["value"]
                
                if collected_info.get(dependent_field) != required_value:
                    continue  # 의존성 조건에 맞지 않으면 필수가 아님
            
            # 필수 필드 체크
            if field.get("required", False) and field_key not in collected_info:
                missing_fields.append(field_key)
        
        is_complete = len(missing_fields) == 0
        return is_complete, missing_fields
    
    def get_next_stage(self, current_stage_id: str, user_response: Optional[str] = None) -> str:
        """다음 단계 결정"""
        current_stage = self.get_current_stage_info(current_stage_id)
        stage_type = current_stage.get("type", "")
        
        if stage_type == "yes_no_question":
            if user_response and self._is_positive_response(user_response):
                return current_stage.get("yes_stage", "complete")
            else:
                return current_stage.get("no_stage", "complete")
        
        elif stage_type in ["info", "slot_filling", "confirmation", "completion"]:
            return current_stage.get("next_stage", "complete")
        
        else:
            return current_stage.get("next_stage", "complete")
    
    def _is_positive_response(self, response: str) -> bool:
        """긍정적 응답 판단"""
        positive_keywords = ["네", "예", "좋아요", "그래요", "맞아요", "신청", "원해요", "할게요", "하겠어요"]
        negative_keywords = ["아니요", "아니에요", "안", "필요없", "괜찮", "나중에", "안할"]
        
        response_lower = response.lower().strip()
        
        # 부정 키워드 우선 체크
        if any(keyword in response_lower for keyword in negative_keywords):
            return False
        
        # 긍정 키워드 체크
        if any(keyword in response_lower for keyword in positive_keywords):
            return True
        
        # 애매한 경우 False (재질의 유도)
        return False
    
    def get_stage_message(self, stage_id: str, collected_info: Dict[str, Any] = None) -> str:
        """단계별 메시지 생성"""
        stage_info = self.get_current_stage_info(stage_id)
        base_message = stage_info.get("message", "")
        
        if stage_id == "confirm_all" and collected_info:
            # 확인 단계에서는 수집된 정보를 포함한 메시지 생성
            return self._generate_confirmation_message(collected_info)
        
        return base_message
    
    def _generate_confirmation_message(self, collected_info: Dict[str, Any]) -> str:
        """확인 단계 메시지 생성"""
        message = "지금까지 입력해주신 정보를 확인해드리겠습니다.\n\n"
        
        # 기본 정보
        if "customer_name" in collected_info:
            message += f"• 고객명: {collected_info['customer_name']}\n"
        if "phone_number" in collected_info:
            message += f"• 연락처: {collected_info['phone_number']}\n"
        if "use_lifelong_account" in collected_info:
            lifelong = "사용" if collected_info['use_lifelong_account'] else "사용안함"
            message += f"• 평생계좌: {lifelong}\n"
        
        # 인터넷뱅킹 정보
        if "ib_service_type" in collected_info:
            message += f"\n[인터넷뱅킹]\n"
            message += f"• 서비스: {collected_info['ib_service_type']}\n"
            if "ib_daily_limit" in collected_info:
                message += f"• 일일한도: {collected_info['ib_daily_limit']}만원\n"
            if "ib_security_method" in collected_info:
                message += f"• 보안방법: {collected_info['ib_security_method']}\n"
        
        # 체크카드 정보
        if "cc_type" in collected_info:
            message += f"\n[체크카드]\n"
            message += f"• 카드종류: {collected_info['cc_type']}\n"
            if "cc_delivery_method" in collected_info:
                message += f"• 수령방법: {collected_info['cc_delivery_method']}\n"
            if "cc_delivery_address" in collected_info:
                message += f"• 배송주소: {collected_info['cc_delivery_address']}\n"
        
        message += "\n위 정보가 맞으신가요? 틀린 부분이 있으시면 알려주세요."
        return message
    
    def handle_correction_request(self, intent: str) -> str:
        """정보 수정 요청 처리"""
        if intent == "REQUEST_MODIFY":
            return "네, 알겠습니다. 고객 정보 수정 단계로 이동하겠습니다. 어떤 정보를 수정하시겠어요?"
        return None
    
    def answer_simple_question(self, question: str) -> Optional[str]:
        """매뉴얼 기반 간단한 질문 답변"""
        question_lower = question.lower()
        common_qa = self.manual.get("common_questions", {})
        
        # 키워드 매칭으로 간단 답변
        for topic, answer in common_qa.items():
            if topic in question_lower:
                return answer
        
        # 서비스 개요 질문
        if any(keyword in question_lower for keyword in ["뭐", "무엇", "어떤", "설명", "알려"]):
            return self.manual.get("service_overview", "")
        
        # 절차 관련 질문
        if any(keyword in question_lower for keyword in ["순서", "절차", "과정", "단계"]):
            return self.manual.get("process_steps", "")
        
        return None
    
    def should_use_qa_tool(self, question: str) -> bool:
        """복잡한 질문으로 QA Tool 사용 여부 판단"""
        # 간단한 답변이 가능한 경우 False
        if self.answer_simple_question(question) is not None:
            return False
        
        # 복잡한 금융 상품 질문 키워드
        complex_keywords = [
            "금리", "이자", "수익", "투자", "적금", "예금", "대출", "신용", 
            "한도", "심사", "조건", "자격", "혜택", "특약", "약관"
        ]
        
        question_lower = question.lower()
        return any(keyword in question_lower for keyword in complex_keywords)
    
    def get_field_display_info(self, field_key: str) -> Dict[str, Any]:
        """필드의 표시 정보 조회"""
        # Try both possible field names
        all_fields = self.scenario_data.get("required_info_fields", []) or self.scenario_data.get("slot_fields", [])
        for field in all_fields:
            if field["key"] == field_key:
                return field
        return {}
    
    def get_all_collected_fields(self) -> List[Dict[str, Any]]:
        """모든 수집 가능한 필드 정보 반환"""
        return self.scenario_data.get("required_info_fields", []) or self.scenario_data.get("slot_fields", [])
    
    def validate_field_value(self, field_key: str, value: Any) -> Tuple[bool, str]:
        """필드 값 유효성 검증"""
        field_info = self.get_field_display_info(field_key)
        
        
        if not field_info:
            return False, "알 수 없는 필드입니다."
        
        field_type = field_info.get("type", "text")
        
        if field_type == "choice":
            choices = field_info.get("choices", [])
            if value not in choices:
                return False, f"다음 중에서 선택해주세요: {', '.join(choices)}"
        
        elif field_type == "number":
            try:
                float(value)
            except (ValueError, TypeError):
                return False, "숫자로 입력해주세요."
        
        elif field_type == "boolean":
            # Boolean 타입은 다양한 한국어 표현과 boolean 값을 모두 허용
            valid_true_values = [True, "true", "True", 1, "1", "네", "예", "신청", "좋아요", "동의", "확인"]
            valid_false_values = [False, "false", "False", 0, "0", "아니요", "아니", "미신청", "싫어요", "거부"]
            valid_values = valid_true_values + valid_false_values
            
            if value not in valid_values:
                return False, "신청/미신청 또는 예/아니요로 답변해주세요."
        
        return True, ""


# 전역 인스턴스
simple_scenario_engine = SimpleScenarioEngine()