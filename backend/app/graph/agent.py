import json
import yaml
import asyncio
from pathlib import Path
from typing import Dict, Optional, Sequence, Literal, Any, List, Union, cast, AsyncGenerator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END, MessageGraph
from langgraph.prebuilt import ToolNode, tools_condition

from .state import AgentState, PRODUCT_TYPES
from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME

# --- 경로 및 설정 ---
APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
CONFIG_DIR = APP_DIR / "config"

# 파일 경로 정의 (유지)
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
    'qa_agent': CONFIG_DIR / "qa_agent_prompts.yaml",
}

# --- LLM, 프롬프트, 데이터 로드 ---
if not OPENAI_API_KEY:
    raise ValueError("CRITICAL: OPENAI_API_KEY is not set.")

# JSON 출력을 위한 LLM (초기 라우터용)
json_llm = ChatOpenAI(
    model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.0,
    model_kwargs={"response_format": {"type": "json_object"}}
)

# 메인 에이전트용 LLM (도구 호출 기능 포함)
main_agent_llm = ChatOpenAI(
    model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.2, streaming=True
)

ALL_PROMPTS: Dict[str, Dict[str, str]] = {}
ALL_SCENARIOS_DATA: Dict[str, Dict] = {}
ALL_KNOWLEDGE_BASES: Dict[str, str] = {}

def load_all_data_sync():
    global ALL_PROMPTS, ALL_SCENARIOS_DATA, ALL_KNOWLEDGE_BASES
    try:
        # 프롬프트 로드
        for agent_name, file_path in PROMPT_FILES.items():
            with open(file_path, 'r', encoding='utf-8') as f:
                ALL_PROMPTS[agent_name] = yaml.safe_load(f)
        
        # 시나리오 데이터 로드
        for product_type, file_path in SCENARIO_FILES.items():
            with open(file_path, 'r', encoding='utf-8') as f:
                ALL_SCENARIOS_DATA[product_type] = json.load(f)
        
        # 지식베이스 로드
        for product_type, file_path in KNOWLEDGE_BASE_FILES.items():
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    ALL_KNOWLEDGE_BASES[product_type] = f.read()
            else:
                ALL_KNOWLEDGE_BASES[product_type] = f"'{product_type}' 상품에 대한 문서를 찾을 수 없습니다."
        
        print("--- All prompts, scenarios, and knowledge bases loaded successfully. ---")
    except Exception as e:
        print(f"CRITICAL: Failed to load initial data: {e}")
        raise

load_all_data_sync()

# --- 도우미 함수 ---
def get_current_stage_info(state: AgentState) -> dict:
    product_type = state.get("current_product_type")
    if not product_type: return {}
    scenario_data = ALL_SCENARIOS_DATA.get(product_type, {})
    stage_id = state.get("current_scenario_stage_id", scenario_data.get("initial_stage_id"))
    return scenario_data.get("stages", {}).get(stage_id, {})

# --- 도구(Tool) 정의 ---
@tool
def answer_question_from_knowledge_base(query: str, product_context: Optional[PRODUCT_TYPES] = None) -> str:
    """사용자가 상품 조건, 용어, 절차 등에 대해 구체적인 질문을 할 때 사용합니다. 현재 대화의 상품 맥락(product_context)을 함께 제공하여 가장 정확한 지식 베이스를 참조하게 하세요."""
    print(f"--- Tool: QA (Query: '{query}', Context: '{product_context}') ---")
    kb_to_use = ALL_KNOWLEDGE_BASES.get(product_context, "일반 금융 지식") if product_context else "일반 금융 지식"
    scenario_name = ALL_SCENARIOS_DATA.get(product_context, {}).get("scenario_name", "일반 문의") if product_context else "일반 문의"
    
    prompt = ChatPromptTemplate.from_template(ALL_PROMPTS['qa_agent']['rag_answer_generation'])
    chain = prompt | json_llm # Use a non-streaming LLM for internal tool logic
    
    response = chain.invoke({"scenario_name": scenario_name, "context_for_llm": kb_to_use, "user_question": query})
    return response.content

@tool
def process_scenario_information(user_response: str, current_product_info: dict, current_stage_info: dict) -> dict:
    """사용자가 시나리오 기반 대화(대출/계좌 신청)의 질문에 답변했을 때, 제공된 정보를 처리하고 다음 단계로 진행하기 위해 사용합니다."""
    print(f"--- Tool: Scenario Processor (Response: '{user_response}') ---")
    
    updated_info = current_product_info.copy()
    expected_key = current_stage_info.get("expected_info_key")
    if expected_key:
        # In a real scenario, an LLM call would be used here to extract the value robustly.
        # For now, we'll do a simplified direct assignment.
        updated_info[expected_key] = user_response
    
    # Simplified next stage logic, can be enhanced with LLM call as in original code
    next_stage_id = current_stage_info.get("default_next_stage_id", "END_SCENARIO_COMPLETE")
    
    return {
        "collected_info": updated_info,
        "next_stage_id": next_stage_id
    }

tools = [answer_question_from_knowledge_base, process_scenario_information]
main_agent_llm_with_tools = main_agent_llm.bind_tools(tools)

# --- LangGraph 노드 정의 ---

def initial_router_node(state: AgentState) -> dict:
    """대화 시작 시 사용자의 첫 의도를 파악하여 시나리오를 시작하거나, QA/잡담으로 분기합니다."""
    print("--- Node: Initial Router ---")
    user_input = state['messages'][-1].content
    prompt = ChatPromptTemplate.from_template(ALL_PROMPTS['main_agent']['initial_task_selection_prompt'])
    chain = prompt | json_llm
    
    response = chain.invoke({"user_input": user_input})
    decision = json.loads(response.content)
    
    # 결정에 따라 상태를 업데이트하여 다음 노드로 전달
    return {"initial_routing_decision": decision}

def call_tool_based_agent(state: AgentState) -> dict:
    """도구 사용이 가능한 메인 에이전트를 호출하여 다음 행동을 결정합니다."""
    print("--- Node: Tool-based Agent ---")
    
    stage_info = get_current_stage_info(state)
    chat_history = "\n".join([f"{type(m).__name__}: {m.content}" for m in state['messages']])
    
    system_prompt = ALL_PROMPTS['main_agent']['main_agent_prompt'].format(
        active_scenario_name=state.get("active_scenario_name", "미정"),
        current_stage_prompt=stage_info.get("prompt", "N/A"),
        collected_product_info=json.dumps(state.get("collected_product_info", {}), ensure_ascii=False),
        chat_history=chat_history
    )
    
    agent_messages = [SystemMessage(content=system_prompt)] + state['messages']
    
    response = main_agent_llm_with_tools.invoke(agent_messages)
    return {"messages": state['messages'] + [response]}

def handle_initial_decision(state: AgentState) -> AgentState:
    """초기 라우터의 결정을 처리하여 상태를 설정하고 사용자에게 첫 응답을 생성합니다."""
    print("--- Node: Handle Initial Decision ---")
    decision = state.pop("initial_routing_decision")
    action = decision.get("action")
    
    product_map = {
        "start_scenario_didimdol": "didimdol",
        "start_scenario_jeonse": "jeonse",
        "start_scenario_deposit_account": "deposit_account",
    }
    
    if action in product_map:
        product_type = product_map[action]
        scenario_data = ALL_SCENARIOS_DATA[product_type]
        initial_stage_id = scenario_data.get("initial_stage_id")
        initial_prompt = scenario_data.get("stages", {}).get(initial_stage_id, {}).get("prompt", "상담을 시작하겠습니다.")
        
        state['current_product_type'] = product_type
        state['active_scenario_name'] = scenario_data.get("scenario_name")
        state['current_scenario_stage_id'] = initial_stage_id
        state['collected_product_info'] = {}
        # 사용자에게 시나리오 시작을 알리는 메시지를 추가
        ai_response = f"네, {state['active_scenario_name']} 상담을 시작하겠습니다. {initial_prompt}"
        state['messages'].append(AIMessage(content=ai_response))

    elif action == "invoke_general_qa":
        # QA는 Tool-based agent가 처리하도록 유도
        # 특별한 상태 변경 없이 바로 메인 에이전트로 넘어감
        pass
    else: # 잡담 또는 불명확한 경우
        state['messages'].append(AIMessage(content=decision.get("direct_response", "죄송하지만 잘 이해하지 못했습니다.")))
        
    return state


# --- 그래프 조건부 엣지 ---
def route_logic(state: AgentState) -> Literal["initial_router", "agent", "__end__"]:
    """대화 상태에 따라 어느 노드로 분기할지 결정합니다."""
    if not state.get("current_product_type"):
        return "initial_router"
    
    last_message = state['messages'][-1]
    if isinstance(last_message, AIMessage) and not last_message.tool_calls:
        return "__end__"
        
    return "agent"

# --- 그래프 구성 ---
workflow = StateGraph(AgentState)
workflow.add_node("initial_router", initial_router_node)
workflow.add_node("handle_decision", handle_initial_decision)
workflow.add_node("agent", call_tool_based_agent)
tool_node = ToolNode(tools)
workflow.add_node("tools", tool_node)

workflow.set_entry_point("handle_decision") # 초기 라우팅 결정을 처리하는 노드에서 시작

workflow.add_conditional_edges(
    "handle_decision",
    route_logic,
    {"initial_router": "initial_router", "agent": "agent", "__end__": END}
)
workflow.add_edge("initial_router", "handle_decision")

workflow.add_conditional_edges("agent", tools_condition)
workflow.add_edge("tools", "agent")

app_graph = workflow.compile()

# --- 비동기 실행 함수 ---
async def run_agent_streaming(
    user_input_text: Optional[str] = None,
    session_id: Optional[str] = "default_session",
    current_state_dict: Optional[Dict[str, Any]] = None
) -> AsyncGenerator[Union[Dict[str, Any], str], None]:

    if not current_state_dict:
        current_state_dict = {}

    initial_state: AgentState = {
        "session_id": session_id,
        "user_input_text": user_input_text,
        "messages": [HumanMessage(content=user_input_text)],
        "current_product_type": current_state_dict.get("current_product_type"),
        "active_scenario_name": current_state_dict.get("active_scenario_name"),
        "current_scenario_stage_id": current_state_dict.get("current_scenario_stage_id"),
        "collected_product_info": current_state_dict.get("collected_product_info", {}),
    }

    final_state = None
    try:
        async for output in app_graph.astream(initial_state):
            final_state = output
            # 마지막 메시지가 AI의 응답이고 도구 호출이 아닐 때 스트리밍
            if "messages" in output and output["messages"]:
                last_message = output["messages"][-1]
                if isinstance(last_message, AIMessage) and not last_message.tool_calls:
                    yield {"type": "stream_start", "stream_type": "final_response"}
                    full_text = ""
                    async for chunk in main_agent_llm.astream([SystemMessage(content="You are a helpful assistant.")] + output["messages"]):
                        if isinstance(chunk, AIMessageChunk) and chunk.content:
                            yield str(chunk.content)
                            full_text += chunk.content
                    yield {"type": "stream_end", "full_text": full_text}

        # 최종 상태 반환
        if final_state:
            yield {"type": "final_state", "session_id": session_id, "data": final_state}

    except Exception as e:
        print(f"Agent streaming error: {e}")
        error_msg = "처리 중 오류가 발생했습니다. 다시 시도해주세요."
        yield {"type": "error", "message": error_msg}
        yield {"type": "final_state", "data": {"error_message": str(e)}}