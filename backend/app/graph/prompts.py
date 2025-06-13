# prompts.py

import yaml
from pathlib import Path
from typing import Dict, Optional, Literal, Any

from pydantic import BaseModel, Field as PydanticField
from langchain_core.output_parsers import PydanticOutputParser

# --- 경로 설정 ---
# 이 파일이 프로젝트의 특정 디렉토리 내에 있다고 가정합니다. (예: /your_project/agents/)
# 필요에 따라 경로를 수정하세요.
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

# --- 프롬프트 파일 정의 ---
PROMPT_FILES = {
    'main_agent': CONFIG_DIR / "main_agent_prompts.yaml",
    'scenario_agent': CONFIG_DIR / "scenario_agent_prompts.yaml",
    'qa_agent': CONFIG_DIR / "qa_agent_prompts.yaml",
}

# --- Pydantic 모델 및 파서 정의 ---
# 이 모델들은 LLM이 특정 작업을 수행할 때 반환해야 하는 JSON 구조를 정의합니다.

class NextStageDecisionModel(BaseModel):
    """다음 시나리오 단계를 결정하기 위한 모델"""
    chosen_next_stage_id: str = PydanticField(description="LLM이 결정한 다음 시나리오 단계 ID")

next_stage_decision_parser = PydanticOutputParser(pydantic_object=NextStageDecisionModel)

class ScenarioOutputModel(BaseModel):
    """시나리오 에이전트가 사용자 발화에서 정보를 추출하기 위한 모델"""
    intent: str = PydanticField(description="사용자 발화의 주요 의도 (예: '정보제공_연소득', '확인_긍정')")
    entities: Dict[str, Any] = PydanticField(default_factory=dict, description="추출된 주요 개체 (예: {'annual_income': 5000})")
    is_scenario_related: bool = PydanticField(description="현재 시나리오와 관련된 발화인지 여부")
    user_sentiment: Optional[Literal['positive', 'negative', 'neutral']] = PydanticField(default='neutral', description="사용자 발화의 감정 (옵션)")

scenario_output_parser = PydanticOutputParser(pydantic_object=ScenarioOutputModel)

class InitialTaskDecisionModel(BaseModel):
    """대화 초기 단계에서 사용자의 의도를 파악하고 작업을 결정하기 위한 모델"""
    action: Literal[
        "proceed_with_product_type_didimdol",
        "proceed_with_product_type_jeonse",
        "proceed_with_product_type_deposit_account",
        "invoke_qa_agent_general",
        "answer_directly_chit_chat",
        "clarify_product_type"
    ] = PydanticField(description="결정된 Action")
    direct_response: Optional[str] = PydanticField(default=None, description="AI의 직접 응답 텍스트 (필요시)")

initial_task_decision_parser = PydanticOutputParser(pydantic_object=InitialTaskDecisionModel)

class MainRouterDecisionModel(BaseModel):
    """메인 라우터가 사용자의 발화를 바탕으로 다음 행동을 결정하기 위한 모델"""
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
    ] = PydanticField(description="결정된 Action")
    extracted_value: Optional[str] = PydanticField(default=None, description="단순 응답 값 (현재는 거의 사용되지 않음)")
    direct_response: Optional[str] = PydanticField(default=None, description="직접 응답 텍스트")

main_router_decision_parser = PydanticOutputParser(pydantic_object=MainRouterDecisionModel)


# --- 프롬프트 로딩 ---
ALL_PROMPTS: Dict[str, Dict[str, str]] = {}

def load_all_prompts_sync() -> None:
    """
    YAML 파일에서 모든 에이전트의 프롬프트를 로드하여 전역 변수 ALL_PROMPTS에 저장합니다.
    """
    global ALL_PROMPTS
    loaded_prompts = {}
    try:
        for agent_name, file_path in PROMPT_FILES.items():
            with open(file_path, 'r', encoding='utf-8') as f:
                prompts_for_agent = yaml.safe_load(f)
            if not prompts_for_agent:
                raise ValueError(f"{agent_name} 프롬프트 파일이 비어있거나 로드에 실패했습니다: {file_path}")
            loaded_prompts[agent_name] = prompts_for_agent
        ALL_PROMPTS = loaded_prompts
        print("--- 모든 에이전트 프롬프트 로드 완료 ---")
    except Exception as e:
        print(f"프롬프트 파일 로드 중 치명적 오류 발생: {e}")
        raise