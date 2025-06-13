# backend/app/graph/prompts.py
import json
import yaml
from pathlib import Path
from typing import Dict, Optional, Sequence, Literal, Any, List, cast, AsyncGenerator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, AIMessageChunk
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME
from .state import AgentState, PRODUCT_TYPES

# --- 경로 및 설정 ---
APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
CONFIG_DIR = APP_DIR / "config"

# --- LLM 초기화 ---
if not OPENAI_API_KEY:
    print("CRITICAL: OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
json_llm = ChatOpenAI(
    model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.1,
    model_kwargs={"response_format": {"type": "json_object"}}
) if OPENAI_API_KEY else None

generative_llm = ChatOpenAI(
    model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.3, streaming=True
) if OPENAI_API_KEY else None

# --- 데이터 로딩 및 관리 ---
ALL_PROMPTS: Dict[str, Dict[str, str]] = {}
ALL_SCENARIOS_DATA: Dict[PRODUCT_TYPES, Dict] = {}
ALL_KNOWLEDGE_BASES: Dict[PRODUCT_TYPES, Optional[str]] = {}

def load_all_prompts_sync() -> None:
    global ALL_PROMPTS
    loaded_prompts = {}
    PROMPT_FILES = {
        'main_agent': CONFIG_DIR / "main_agent_prompts.yaml",
        'scenario_agent': CONFIG_DIR / "scenario_agent_prompts.yaml",
        'qa_agent': CONFIG_DIR / "qa_agent_prompts.yaml",
    }
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

def load_all_scenarios_sync() -> None:
    global ALL_SCENARIOS_DATA
    SCENARIO_FILES: Dict[PRODUCT_TYPES, Path] = {
        "didimdol": DATA_DIR / "didimdol_loan_scenario.json",
        "jeonse": DATA_DIR / "jeonse_loan_scenario.json",
        "deposit_account": DATA_DIR / "deposit_account_scenario.json",
    }
    loaded_scenarios = {}
    try:
        for loan_type, file_path in SCENARIO_FILES.items():
            with open(file_path, 'r', encoding='utf-8') as f:
                scenario = json.load(f)
            if not scenario: raise ValueError(f"{loan_type} 시나리오 파일이 비어있습니다: {file_path}")
            loaded_scenarios[loan_type] = scenario
        ALL_SCENARIOS_DATA = cast(Dict[PRODUCT_TYPES, Dict], loaded_scenarios)
        print("--- 모든 상품 시나리오 데이터 로드 완료 ---")
    except Exception as e:
        print(f"시나리오 파일 로드 중 치명적 오류 발생: {e}")
        raise

async def load_knowledge_base_content_async(loan_type: PRODUCT_TYPES) -> Optional[str]:
    global ALL_KNOWLEDGE_BASES
    KNOWLEDGE_BASE_FILES: Dict[PRODUCT_TYPES, Path] = {
        "didimdol": DATA_DIR / "didimdol.md",
        "jeonse": DATA_DIR / "jeonse.md",
        "deposit_account": DATA_DIR / "deposit_account.md",
        # "debit_card": DATA_DIR / "debit_card.md", # These can be loaded on demand if needed
        # "internet_banking": DATA_DIR / "internet_banking.md",
    }
    
    if loan_type not in KNOWLEDGE_BASE_FILES:
        print(f"경고: '{loan_type}'에 대한 지식베이스 파일이 정의되지 않았습니다.")
        ALL_KNOWLEDGE_BASES[loan_type] = "NOT_AVAILABLE"
        return None

    if ALL_KNOWLEDGE_BASES.get(loan_type) is None:
        file_path = KNOWLEDGE_BASE_FILES[loan_type]
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            ALL_KNOWLEDGE_BASES[loan_type] = content
            print(f"--- QA Agent: '{loan_type}' 지식베이스 로딩 완료 ---")
        except Exception as e:
            print(f"'{loan_type}' QA 지식베이스 로딩 실패: {e}")
            ALL_KNOWLEDGE_BASES[loan_type] = "ERROR_LOADING_FAILED"
            return None
            
    return ALL_KNOWLEDGE_BASES[loan_type]

def initialize_all_data():
    load_all_prompts_sync()
    load_all_scenarios_sync()

# --- Utility Functions ---
def format_messages_for_prompt(messages: Sequence[BaseMessage], max_history: int = 5) -> str:
    history_str = []
    relevant_messages = [m for m in messages if isinstance(m, (HumanMessage, AIMessage, SystemMessage))][-(max_history * 2):]
    for msg in relevant_messages:
        role = "사용자" if isinstance(msg, HumanMessage) else "상담원" if isinstance(msg, AIMessage) else "시스템"
        history_str.append(f"{role}: {msg.content}")
    return "\n".join(history_str) if history_str else "이전 대화 없음."

def format_transitions_for_prompt(transitions: List[Dict[str, Any]], current_stage_prompt: str) -> str:
    if not transitions:
        return "현재 단계에서 다음으로 넘어갈 수 있는 조건(Transition)이 정의되지 않았습니다."
    
    formatted_list = [f"현재 단계의 사용자 안내/질문: \"{current_stage_prompt}\""]
    for i, transition in enumerate(transitions):
        condition_desc = transition.get("condition_description", "조건 설명 없음")
        example_phrases = transition.get("example_phrases", [])
        if example_phrases:
            condition_desc += f" (예시: {', '.join(f'{p}' for p in example_phrases)})"
        formatted_list.append(f"{i+1}. 다음 단계 ID: '{transition['next_stage_id']}', 조건: {condition_desc}")
    
    return "\n".join(formatted_list)