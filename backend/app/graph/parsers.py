# backend/app/graph/parsers.py
from typing import Dict, Optional, Literal, Any
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

class NextStageDecisionModel(BaseModel):
    chosen_next_stage_id: str = Field(description="LLM이 결정한 다음 시나리오 단계 ID")

class ScenarioOutputModel(BaseModel):
    intent: str = Field(description="사용자 발화의 주요 의도 (예: '정보제공_연소득', '확인_긍정')")
    entities: Dict[str, Any] = Field(default_factory=dict, description="추출된 주요 개체 (예: {'annual_income': 5000})")
    is_scenario_related: bool = Field(description="현재 시나리오와 관련된 발화인지 여부")
    user_sentiment: Optional[Literal['positive', 'negative', 'neutral']] = Field(default='neutral', description="사용자 발화의 감정 (옵션)")

class InitialTaskDecisionModel(BaseModel):
    action: Literal[
        "proceed_with_product_type_didimdol",
        "proceed_with_product_type_jeonse",
        "proceed_with_product_type_deposit_account",
        "invoke_qa_agent_general",
        "answer_directly_chit_chat",
        "clarify_product_type"
    ] = Field(description="결정된 Action")
    direct_response: Optional[str] = Field(default=None, description="AI의 직접 응답 텍스트 (필요시)")

class MainRouterDecisionModel(BaseModel):
    action: Literal[
        "select_product_type",
        "set_product_type_didimdol",
        "set_product_type_jeonse",
        "set_product_type_deposit_account",
        "invoke_scenario_agent",
        "invoke_qa_agent",
        "answer_directly_chit_chat",
        "end_conversation",
        "unclear_input"
    ] = Field(description="결정된 Action")
    extracted_value: Optional[str] = Field(default=None, description="단순 응답 값 (현재는 거의 사용되지 않음)")
    direct_response: Optional[str] = Field(default=None, description="직접 응답 텍스트")

# Parsers
next_stage_decision_parser = PydanticOutputParser(pydantic_object=NextStageDecisionModel)
scenario_output_parser = PydanticOutputParser(pydantic_object=ScenarioOutputModel)
initial_task_decision_parser = PydanticOutputParser(pydantic_object=InitialTaskDecisionModel)
main_router_decision_parser = PydanticOutputParser(pydantic_object=MainRouterDecisionModel)