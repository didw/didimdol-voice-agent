import json
import yaml
import asyncio
from pathlib import Path
from typing import Dict, Optional, Sequence, Literal, Any, List, Union, cast, AsyncGenerator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, AIMessageChunk, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from .state import AgentState, ScenarioAgentOutput, PRODUCT_TYPES
from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME

# --- Pydantic Models for Parsing (Simplified - LLM will generate JSON for tools) ---
# Pydantic models for explicit output parsing are less critical here as we use function calling,
# but can be kept for validation if desired. For this refactor, we'll rely on the LLM's
# ability to generate correct tool inputs.

# --- 경로 및 설정 ---
APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
CONFIG_DIR = APP_DIR / "config"

# 시나리오 및 지식베이스 파일 정의
SCENARIO_FILES: Dict[PRODUCT_TYPES, Path] = {
    "didimdol": DATA_DIR / "didimdol_loan_scenario.json",
    "jeonse": DATA_DIR / "jeonse_loan_scenario.json",
    "deposit_account": DATA_DIR / "deposit_account_scenario.json",
}
KNOWLEDGE_BASE_FILES: Dict[PRODUCT_TYPES, Path] = {
    "didimdol": DATA_DIR / "didimdol.md",
    "jeonse": DATA_DIR / "jeonse.md",
    "deposit_account": DATA_DIR / "deposit_account.md",
    "debit_card": DATA_DIR / "debit_card.md",
    "internet_banking": DATA_DIR / "internet_banking.md",
}

PROMPT_FILES = {
    'main_agent': CONFIG_DIR / "main_agent_prompts.yaml",
    'qa_agent': CONFIG_DIR / "qa_agent_prompts.yaml", # Kept for QA tool's internal prompt
}

# --- LLM 초기화 ---
if not OPENAI_API_KEY:
    raise ValueError("CRITICAL: OPENAI_API_KEY is not set. Please check your .env file.")

# Main agent LLM with tool-calling capabilities
main_agent_llm = ChatOpenAI(
    model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.2, streaming=True
)

# LLM for specific tool internal logic (can be the same model)
internal_llm = ChatOpenAI(
    model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.1
)


# --- 프롬프트 및 데이터 로드 (유지) ---
ALL_PROMPTS: Dict[str, Dict[str, str]] = {}
ALL_SCENARIOS_DATA: Dict[PRODUCT_TYPES, Dict] = {}
ALL_KNOWLEDGE_BASES: Dict[PRODUCT_TYPES, Optional[str]] = {}

def load_all_data_sync():
    global ALL_PROMPTS, ALL_SCENARIOS_DATA
    try:
        for agent_name, file_path in PROMPT_FILES.items():
            with open(file_path, 'r', encoding='utf-8') as f:
                ALL_PROMPTS[agent_name] = yaml.safe_load(f)
        
        for product_type, file_path in SCENARIO_FILES.items():
            with open(file_path, 'r', encoding='utf-8') as f:
                ALL_SCENARIOS_DATA[product_type] = json.load(f)
        
        for product_type, file_path in KNOWLEDGE_BASE_FILES.items():
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    ALL_KNOWLEDGE_BASES[product_type] = f.read()
            else:
                ALL_KNOWLEDGE_BASES[product_type] = "Knowledge base not available."
        
        print("--- All prompts, scenarios, and knowledge bases loaded successfully. ---")
    except Exception as e:
        print(f"CRITICAL: Failed to load initial data: {e}")
        raise

load_all_data_sync()

# --- Helper Functions ---
def format_messages_for_prompt(messages: Sequence[BaseMessage]) -> str:
    history_str = []
    for msg in messages:
        role = "Unknown"
        if isinstance(msg, HumanMessage): role = "User"
        elif isinstance(msg, AIMessage): role = "AI"
        elif isinstance(msg, SystemMessage): role = "System"
        elif isinstance(msg, ToolMessage): role = f"Tool ({msg.name})"
        
        content_summary = (
            str(msg.content)[:150] + '...'
            if isinstance(msg.content, str) and len(msg.content) > 150
            else str(msg.content)
        )
        history_str.append(f"{role}: {content_summary}")
    return "\n".join(history_str) if history_str else "No previous conversation."

def get_current_stage_info(state: AgentState) -> dict:
    product_type = state.get("current_product_type")
    if not product_type: return {}
    
    scenario_data = ALL_SCENARIOS_DATA.get(product_type, {})
    stage_id = state.get("current_scenario_stage_id")
    if not stage_id: stage_id = scenario_data.get("initial_stage_id")

    return scenario_data.get("stages", {}).get(stage_id, {})

# --- Tool Definitions ---

@tool
def answer_question_from_knowledge_base(query: str, product_context: Optional[str]) -> str:
    """
    Answers a user's question based on the provided knowledge base for the specified financial product.
    Use this when the user asks for specific details, definitions, or conditions about a product.
    """
    print(f"--- Tool: answer_question_from_knowledge_base (Query: '{query}', Context: '{product_context}') ---")
    
    kb_to_use = ""
    scenario_name_for_prompt = "General Inquiry"
    
    # Determine which knowledge base to use
    if product_context and product_context in ALL_KNOWLEDGE_BASES:
        kb_to_use = ALL_KNOWLEDGE_BASES[product_context]
        scenario_name_for_prompt = ALL_SCENARIOS_DATA.get(product_context, {}).get("scenario_name", product_context)
    else:
        # Fallback for general questions: combine relevant KBs or use a default
        # For simplicity, we'll indicate no specific context.
        kb_to_use = "No specific product context provided. Answer based on general financial knowledge."

    rag_prompt_template = ALL_PROMPTS.get('qa_agent', {}).get('rag_answer_generation', '')
    if not rag_prompt_template:
        return "Error: RAG prompt not found."

    prompt = ChatPromptTemplate.from_template(rag_prompt_template)
    chain = prompt | internal_llm
    
    try:
        response = chain.invoke({
            "scenario_name": scenario_name_for_prompt,
            "context_for_llm": kb_to_use,
            "user_question": query
        })
        return response.content
    except Exception as e:
        print(f"Error in QA tool: {e}")
        return "Sorry, I encountered an error while looking up the information."


@tool
def process_scenario_information(user_response: str, current_state: AgentState) -> dict:
    """
    Processes the user's response within an ongoing loan or account application scenario.
    Use this to extract information, validate it, and determine the next step in the conversation flow.
    Returns a dictionary with the next prompt for the user and any information that was collected.
    """
    print(f"--- Tool: process_scenario_information (User Response: '{user_response}') ---")
    product_type = current_state.get("current_product_type")
    if not product_type:
        return {"next_prompt": "Please select a product first.", "collected_info": {}}

    scenario_data = ALL_SCENARIOS_DATA.get(product_type, {})
    stage_info = get_current_stage_info(current_state)
    collected_info = current_state.get("collected_product_info", {}).copy()

    # (This is a simplified logic. A real implementation might use an LLM call to extract entities)
    # For now, we'll assume the user's response directly provides the needed info.
    expected_key = stage_info.get("expected_info_key")
    if expected_key:
        collected_info[expected_key] = user_response # Simplified extraction
    
    # Determine next stage (simplified from original for clarity, can be expanded)
    next_stage_id = stage_info.get("default_next_stage_id")
    if stage_info.get("transitions"):
        # A more complex logic would evaluate transitions here
        pass

    if not next_stage_id or next_stage_id.startswith("END"):
         next_prompt = scenario_data.get("end_scenario_message", "The application is complete.")
    else:
        next_stage_info = scenario_data.get("stages", {}).get(next_stage_id, {})
        next_prompt = next_stage_info.get("prompt", "What is the next step?")

    return {
        "next_prompt": next_prompt,
        "collected_info": collected_info,
        "next_stage_id": next_stage_id
    }

tools = [answer_question_from_knowledge_base, process_scenario_information]
tool_node = ToolNode(tools)

main_agent_llm_with_tools = main_agent_llm.bind_tools(tools)

# --- LangGraph Nodes ---
def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
    """Determines whether to continue with tool calls or end the turn."""
    last_message = state['messages'][-1]
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return "__end__"
    return "tools"

def call_agent(state: AgentState) -> dict:
    """The main agent node. It decides what to do next - call tools or respond."""
    print("--- Node: Main Agent ---")
    messages = state['messages']
    
    # Build a system prompt with current context
    system_prompt_template = ALL_PROMPTS.get('main_agent', {}).get('main_system_prompt', '')
    stage_info = get_current_stage_info(state)
    
    system_prompt = system_prompt_template.format(
        active_scenario_name=state.get("active_scenario_name", "Not in a scenario"),
        current_stage_prompt=stage_info.get("prompt", "N/A"),
        collected_product_info=json.dumps(state.get("collected_product_info", {}), ensure_ascii=False),
        chat_history=format_messages_for_prompt(messages)
    )
    
    agent_messages = [SystemMessage(content=system_prompt)] + messages

    response = main_agent_llm_with_tools.invoke(agent_messages)
    return {"messages": [response]}

async def run_agent_streaming(
    user_input_text: Optional[str] = None,
    session_id: Optional[str] = "default_session",
    current_state_dict: Optional[Dict[str, Any]] = None
) -> AsyncGenerator[Union[Dict[str, Any], str], None]:
    
    # Initialize state
    initial_state: AgentState = {
        "session_id": session_id,
        "user_input_text": user_input_text,
        "messages": [HumanMessage(content=user_input_text)],
        **(current_state_dict or {}) # Load previous state
    }
    
    # Define the graph
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_agent)
    workflow.add_node("tools", tool_node)
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
    )
    workflow.add_edge("tools", "agent")
    app_graph = workflow.compile()
    
    # Stream the output
    final_state = None
    async for output in app_graph.astream(initial_state):
        final_state = output
        last_message = output['agent']['messages'][-1]
        if not last_message.tool_calls:
            # It's a final response from the LLM
            yield {"type": "stream_start", "stream_type": "final_response"}
            async for chunk in main_agent_llm.astream(output['agent']['messages']):
                if isinstance(chunk, AIMessageChunk) and chunk.content:
                    yield str(chunk.content)
            yield {"type": "stream_end"}

    # Yield the final state for the client to store
    if final_state:
        # We only want to yield the 'agent' part of the output, which is the AgentState
        yield {"type": "final_state", "session_id": session_id, "data": final_state.get('agent')}