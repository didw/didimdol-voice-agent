# utils.py

import json
from pathlib import Path
from typing import Dict, Optional, Sequence, Literal, Any, List, TypedDict, Union, cast

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

# --- 상태 및 타입 정의 ---
# 원래 state.py 파일에 있었을 것으로 추정되는 내용
PRODUCT_TYPES = Literal["didimdol", "jeonse", "deposit_account"]

class ScenarioAgentOutput(TypedDict):
    intent: str
    entities: Dict[str, Any]
    is_scenario_related: bool
    user_sentiment: Optional[Literal['positive', 'negative', 'neutral']]

class AgentState(TypedDict):
    session_id: str
    user_input_text: Optional[str]
    user_input_audio_b64: Optional[str]
    stt_result: Optional[str]
    messages: Sequence[BaseMessage]
    
    current_product_type: Optional[PRODUCT_TYPES]
    current_scenario_stage_id: Optional[str]
    collected_product_info: Dict[str, Any]
    
    # Turn-specific state
    main_agent_routing_decision: Optional[str]
    main_agent_direct_response: Optional[str]
    scenario_agent_output: Optional[ScenarioAgentOutput]
    final_response_text_for_tts: Optional[str]
    is_final_turn_response: bool
    error_message: Optional[str]
    
    active_scenario_data: Optional[Dict]
    active_knowledge_base_content: Optional[str]
    active_scenario_name: Optional[str]
    
    available_product_types: List[PRODUCT_TYPES]
    loan_selection_is_fresh: bool
    factual_response: Optional[str]

# --- 경로 및 데이터 파일 정의 ---
APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"

SCENARIO_FILES: Dict[PRODUCT_TYPES, Path] = {
    "didimdol": DATA_DIR / "didimdol_loan_scenario.json",
    "jeonse": DATA_DIR / "jeonse_loan_scenario.json",
    "deposit_account": DATA_DIR / "deposit_account_scenario.json",
}
KNOWLEDGE_BASE_FILES: Dict[Union[PRODUCT_TYPES, str], Path] = {
    "didimdol": DATA_DIR / "didimdol.md",
    "jeonse": DATA_DIR / "jeonse.md",
    "deposit_account": DATA_DIR / "deposit_account.md",
    "debit_card": DATA_DIR / "debit_card.md",
    "internet_banking": DATA_DIR / "internet_banking.md",
}

# --- 인메모리 데이터 저장소 ---
ALL_SCENARIOS_DATA: Dict[PRODUCT_TYPES, Dict] = {}
ALL_KNOWLEDGE_BASES: Dict[str, Optional[str]] = {pt: None for pt in KNOWLEDGE_BASE_FILES.keys()}


# --- 데이터 로딩 함수 ---
def load_all_scenarios_sync() -> None:
    """모든 시나리오 JSON 파일을 로드합니다."""
    global ALL_SCENARIOS_DATA
    loaded_scenarios = {}
    try:
        for product_type, file_path in SCENARIO_FILES.items():
            with open(file_path, 'r', encoding='utf-8') as f:
                scenario = json.load(f)
            if not scenario:
                raise ValueError(f"{product_type} 시나리오 파일이 비어있습니다: {file_path}")
            loaded_scenarios[product_type] = scenario
        ALL_SCENARIOS_DATA = cast(Dict[PRODUCT_TYPES, Dict], loaded_scenarios)
        print("--- 모든 상품 시나리오 데이터 로드 완료 ---")
    except Exception as e:
        print(f"시나리오 파일 로드 중 치명적 오류 발생: {e}")
        raise

async def load_knowledge_base_content_async(product_type: str) -> Optional[str]:
    """특정 상품의 지식베이스 Markdown 파일을 비동기적으로 로드합니다."""
    global ALL_KNOWLEDGE_BASES
    if product_type not in KNOWLEDGE_BASE_FILES:
        print(f"경고: '{product_type}'에 대한 지식베이스 파일이 정의되지 않았습니다.")
        ALL_KNOWLEDGE_BASES[product_type] = "NOT_AVAILABLE"
        return None
        
    if ALL_KNOWLEDGE_BASES.get(product_type) is None or "ERROR" in str(ALL_KNOWLEDGE_BASES.get(product_type)):
        file_path = KNOWLEDGE_BASE_FILES[product_type]
        print(f"--- QA Agent: '{product_type}' 지식베이스 ({file_path.name}) 로딩 중... ---")
        try:
            if not file_path.exists():
                error_msg = f"경고: '{product_type}' 지식베이스 파일을 찾을 수 없습니다: {file_path}"
                print(error_msg)
                ALL_KNOWLEDGE_BASES[product_type] = "ERROR_FILE_NOT_FOUND"
                return None
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if not content.strip():
                error_msg = f"경고: '{product_type}' 지식베이스 파일이 비어있습니다: {file_path}"
                print(error_msg)
                ALL_KNOWLEDGE_BASES[product_type] = "EMPTY_CONTENT"
                return None
            ALL_KNOWLEDGE_BASES[product_type] = content
            print(f"--- QA Agent: '{product_type}' 지식베이스 로딩 완료 ({len(content)} 자) ---")
        except Exception as e:
            error_msg = f"'{product_type}' QA 지식베이스 로딩 실패: {e}"
            print(error_msg)
            ALL_KNOWLEDGE_BASES[product_type] = "ERROR_LOADING_FAILED"
            return None
    
    if str(ALL_KNOWLEDGE_BASES.get(product_type)).startswith(("ERROR_", "NOT_AVAILABLE")):
        return None
    return ALL_KNOWLEDGE_BASES[product_type]

def get_active_scenario_data(state: AgentState) -> Optional[Dict]:
    """현재 상태(State)에서 활성화된 상품의 시나리오 데이터를 반환합니다."""
    product_type = state.get("current_product_type")
    if product_type:
        return ALL_SCENARIOS_DATA.get(product_type)
    return None

async def get_active_knowledge_base(state: AgentState) -> Optional[str]:
    """현재 상태(State)에서 활성화된 상품의 지식베이스 내용을 반환합니다."""
    product_type = state.get("current_product_type")
    if product_type:
        return await load_knowledge_base_content_async(product_type)
    return None

# --- 프롬프트 포맷팅 유틸리티 ---
def format_messages_for_prompt(messages: Sequence[BaseMessage], max_history: int = 5) -> str:
    """대화 기록을 LLM 프롬프트에 넣기 좋은 문자열 형태로 변환합니다."""
    history_str = []
    relevant_messages = [m for m in messages if isinstance(m, (HumanMessage, AIMessage, SystemMessage))][-(max_history * 2):]
    for msg in relevant_messages:
        if isinstance(msg, HumanMessage):
            role = "사용자"
        elif isinstance(msg, AIMessage):
            role = "상담원"
        else:
            role = "시스템"
        history_str.append(f"{role}: {msg.content}")
    return "\n".join(history_str) if history_str else "이전 대화 없음."

def format_transitions_for_prompt(transitions: List[Dict[str, Any]], current_stage_prompt: str) -> str:
    """시나리오의 Transition 정보를 LLM이 이해하기 쉬운 문자열로 변환합니다."""
    if not transitions:
        return "현재 단계에서 다음으로 넘어갈 수 있는 조건(Transition)이 정의되지 않았습니다."
    
    formatted_list = [f"현재 단계의 사용자 안내/질문: \"{current_stage_prompt}\""]
    for i, transition in enumerate(transitions):
        condition_desc = transition.get("condition_description", "조건 설명 없음")
        example_phrases_str = ", ".join(f"'{p}'" for p in transition.get("example_phrases", []))
        if example_phrases_str:
            condition_desc += f" (예시: {example_phrases_str})"
        formatted_list.append(f"{i+1}. 다음 단계 ID: '{transition['next_stage_id']}', 조건: {condition_desc}")
    
    return "\n".join(formatted_list)