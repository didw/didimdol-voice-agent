# backend/app/graph/utils.py
import json
import yaml
from pathlib import Path
from typing import Dict, Optional, Sequence, Literal, Any, List, cast

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from .state import AgentState, PRODUCT_TYPES

# --- Paths and Settings ---
APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
CONFIG_DIR = APP_DIR / "config"

# Scenario and KnowledgeBase file definitions
SCENARIO_FILES: Dict[PRODUCT_TYPES, Path] = {
    "didimdol": DATA_DIR / "scenarios" / "didimdol_loan_scenario.json",
    "jeonse": DATA_DIR / "scenarios" / "jeonse_loan_scenario.json",
    "deposit_account": DATA_DIR / "scenarios" / "deposit_account_scenario_v3.json",
}
KNOWLEDGE_BASE_FILES: Dict[str, Path] = {
    "didimdol": DATA_DIR / "docs" / "didimdol.md",
    "jeonse": DATA_DIR / "docs" / "jeonse.md",
    "deposit_account": DATA_DIR / "docs" / "deposit_account.md",
    "debit_card": DATA_DIR / "docs" / "debit_card.md",
    "internet_banking": DATA_DIR / "docs" / "internet_banking.md",
}
PROMPT_FILES = {
    'main_agent': CONFIG_DIR / "main_agent_prompts.yaml",
    'scenario_agent': CONFIG_DIR / "scenario_agent_prompts.yaml",
    'qa_agent': CONFIG_DIR / "qa_agent_prompts.yaml",
}

# --- Data Caching ---
ALL_PROMPTS: Dict[str, Dict[str, str]] = {}
ALL_SCENARIOS_DATA: Dict[PRODUCT_TYPES, Dict] = {}
ALL_KNOWLEDGE_BASES: Dict[str, Optional[str]] = {}

# --- Loading Functions ---
def load_all_prompts_sync() -> None:
    """Loads all agent prompts from YAML files into memory."""
    global ALL_PROMPTS
    try:
        for agent_name, file_path in PROMPT_FILES.items():
            with open(file_path, 'r', encoding='utf-8') as f:
                ALL_PROMPTS[agent_name] = yaml.safe_load(f)
        print("--- All agent prompts loaded successfully. ---")
    except Exception as e:
        print(f"CRITICAL ERROR loading prompt files: {e}")
        raise

def load_all_scenarios_sync() -> None:
    """Loads all scenario JSON files into memory."""
    global ALL_SCENARIOS_DATA
    try:
        for product_type, file_path in SCENARIO_FILES.items():
            with open(file_path, 'r', encoding='utf-8') as f:
                ALL_SCENARIOS_DATA[product_type] = json.load(f)
        print("--- All product scenarios loaded successfully. ---")
    except Exception as e:
        print(f"CRITICAL ERROR loading scenario files: {e}")
        raise

async def load_knowledge_base_content_async(product_type: str) -> Optional[str]:
    """Loads a specific knowledge base file into memory if not already loaded."""
    global ALL_KNOWLEDGE_BASES
    if product_type not in KNOWLEDGE_BASE_FILES:
        print(f"Warning: No knowledge base file defined for '{product_type}'.")
        return None
    
    if ALL_KNOWLEDGE_BASES.get(product_type) is None:
        file_path = KNOWLEDGE_BASE_FILES[product_type]
        print(f"--- Loading KB for '{product_type}' from {file_path.name}... ---")
        try:
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                ALL_KNOWLEDGE_BASES[product_type] = content
                print(f"--- KB for '{product_type}' loaded ({len(content)} chars). ---")
            else:
                print(f"Warning: KB file not found for '{product_type}': {file_path}")
                ALL_KNOWLEDGE_BASES[product_type] = "ERROR_FILE_NOT_FOUND"
        except Exception as e:
            print(f"Failed to load KB for '{product_type}': {e}")
            ALL_KNOWLEDGE_BASES[product_type] = "ERROR_LOADING_FAILED"

    content = ALL_KNOWLEDGE_BASES.get(product_type)
    return content if content and not content.startswith("ERROR_") else None

# --- Formatting and Utility Functions ---
def format_messages_for_prompt(messages: Sequence[BaseMessage], max_history: int = 5) -> str:
    """Formats a sequence of messages for inclusion in a prompt."""
    history_str = []
    relevant_messages = [m for m in messages if isinstance(m, (HumanMessage, AIMessage, SystemMessage))][-(max_history * 2):]
    for msg in relevant_messages:
        role = "System"
        if isinstance(msg, HumanMessage): role = "User"
        elif isinstance(msg, AIMessage): role = "AI"
        history_str.append(f"{role}: {msg.content}")
    return "\n".join(history_str) if history_str else "No previous conversation."

def format_transitions_for_prompt(transitions: List[Dict[str, Any]], current_stage_prompt: str) -> str:
    """Formats transition rules for inclusion in a prompt."""
    if not transitions:
        return "No transitions are defined for the current stage."
    
    formatted_list = [f"Current question/guidance to the user: \"{current_stage_prompt}\""]
    for i, transition in enumerate(transitions):
        desc = transition.get("condition_description", "No description")
        examples = ", ".join(f"'{p}'" for p in transition.get("example_phrases", []))
        desc += f" (e.g., {examples})" if examples else ""
        formatted_list.append(f"{i+1}. Next Stage ID: '{transition['next_stage_id']}', Condition: {desc}")
    
    return "\n".join(formatted_list)

def get_active_scenario_data(state: AgentState) -> Optional[Dict]:
    """Retrieves the active scenario data based on the current product type in the state."""
    product_type = state.get("current_product_type")
    return ALL_SCENARIOS_DATA.get(product_type) if product_type else None

async def get_active_knowledge_base(state: AgentState) -> Optional[str]:
    """Retrieves the active knowledge base content based on the current product type."""
    product_type = state.get("current_product_type")
    return await load_knowledge_base_content_async(product_type) if product_type else None

# --- Initial Load ---
load_all_prompts_sync()
load_all_scenarios_sync()