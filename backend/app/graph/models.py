# backend/app/graph/models.py

from pydantic import BaseModel, Field
from typing import Dict, Optional, Literal, Any, List
from langchain_core.output_parsers import PydanticOutputParser

class NextStageDecisionModel(BaseModel):
    """A model to hold the decision for the next scenario stage."""
    chosen_next_stage_id: str = Field(description="The ID of the next scenario stage determined by the LLM.")

next_stage_decision_parser = PydanticOutputParser(pydantic_object=NextStageDecisionModel)

class ScenarioOutputModel(BaseModel):
    """Defines the structured output from the Scenario Agent."""
    intent: str = Field(description="The main intent of the user's utterance (e.g., 'provide_info_annual_income', 'confirm_positive').")
    entities: Dict[str, Any] = Field(default_factory=dict, description="Key entities extracted from the user's utterance (e.g., {'annual_income': 5000}).")
    is_scenario_related: bool = Field(description="Whether the utterance is directly related to the current scenario.")
    user_sentiment: Optional[Literal['positive', 'negative', 'neutral']] = Field(default='neutral', description="The sentiment of the user's utterance (optional).")

scenario_output_parser = PydanticOutputParser(pydantic_object=ScenarioOutputModel)

# Simplified model for initial user intent
class InitialTaskDecisionModel(BaseModel):
    """Defines the possible initial actions the main agent can decide on."""
    # 'action'을 'actions' 리스트로 변경합니다.
    actions: List[Literal[
        "proceed_with_product_type_didimdol",
        "proceed_with_product_type_jeonse",
        "proceed_with_product_type_deposit_account",
        "invoke_qa_agent_general",
        "answer_directly_chit_chat",
        "clarify_product_type"
    ]] = Field(description="The determined list of actions to take based on initial user input.")
    direct_response: Optional[str] = Field(default=None, description="A direct text response for clarification or chit-chat.")

initial_task_decision_parser = PydanticOutputParser(pydantic_object=InitialTaskDecisionModel)


class MainRouterDecisionModel(BaseModel):
    """Defines the routing decisions for the main agent during a conversation."""
    actions: List[Literal[
        "select_product_type",
        "set_product_type_didimdol",
        "set_product_type_jeonse",
        "set_product_type_deposit_account",
        "invoke_scenario_agent",
        "invoke_qa_agent",
        "answer_directly_chit_chat",
        "end_conversation",
        "unclear_input"
    ]] = Field(description="The determined list of actions to execute in sequence for this turn.")
    direct_response: Optional[str] = Field(default=None, description="A direct text response for simple actions like chit-chat, clarification, or unclear input.")

main_router_decision_parser = PydanticOutputParser(pydantic_object=MainRouterDecisionModel)