# backend/app/graph/agent.py
import json
import yaml
import asyncio
from pathlib import Path
from typing import Dict, Optional, Sequence, Literal, Any, List, Union, cast, AsyncGenerator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, AIMessageChunk
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field as PydanticField

from .state import AgentState, ScenarioAgentOutput, PRODUCT_TYPES
from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME
from ..services.google_services import GOOGLE_SERVICES_AVAILABLE

# --- Pydantic 모델 정의 ---
class NextStageDecisionModel(BaseModel):
    chosen_next_stage_id: str = PydanticField(description="LLM이 결정한 다음 시나리오 단계 ID")
next_stage_decision_parser = PydanticOutputParser(pydantic_object=NextStageDecisionModel)

class ScenarioOutputModel(BaseModel):
    intent: str = PydanticField(description="사용자 발화의 주요 의도 (예: '정보제공_연소득', '확인_긍정')")
    entities: Dict[str, Any] = PydanticField(default_factory=dict, description="추출된 주요 개체 (예: {'annual_income': 5000})")
    is_scenario_related: bool = PydanticField(description="현재 시나리오와 관련된 발화인지 여부")
    user_sentiment: Optional[Literal['positive', 'negative', 'neutral']] = PydanticField(default='neutral', description="사용자 발화의 감정 (옵션)")
scenario_output_parser = PydanticOutputParser(pydantic_object=ScenarioOutputModel)

class InitialTaskDecisionModel(BaseModel):
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
    action: Literal[
        "select_product_type",
        "set_product_type_didimdol",
        "set_product_type_jeonse",
        "set_product_type_deposit_account",
        "invoke_scenario_agent",
        "invoke_qa_agent",
        "answer_directly_chit_chat",
        "process_next_scenario_step",
        "end_conversation",
        "unclear_input"
    ] = PydanticField(description="결정된 Action")
    extracted_value: Optional[str] = PydanticField(default=None, description="단순 응답 값 (process_next_scenario_step용)")
    direct_response: Optional[str] = PydanticField(default=None, description="직접 응답 텍스트")
main_router_decision_parser = PydanticOutputParser(pydantic_object=MainRouterDecisionModel)


# --- 경로 및 설정 ---
APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
CONFIG_DIR = APP_DIR / "config"

# 시나리오 및 지식베이스 파일 정의
SCENARIO_FILES: Dict[PRODUCT_TYPES, Path] = { # 타입 변경
    "didimdol": DATA_DIR / "didimdol_loan_scenario.json",
    "jeonse": DATA_DIR / "jeonse_loan_scenario.json",
    "deposit_account": DATA_DIR / "deposit_account_scenario.json", # 신규 추가
}
KNOWLEDGE_BASE_FILES: Dict[PRODUCT_TYPES, Path] = { # 타입 변경
    "didimdol": DATA_DIR / "didimdol.md",
    "jeonse": DATA_DIR / "jeonse.md",
    "deposit_account": DATA_DIR / "deposit_account.md",
    "debit_card": DATA_DIR / "debit_card.md",
    "internet_banking": DATA_DIR / "internet_banking.md",
}
# 일반 QA를 위한 기본 지식베이스 (선택 사항, 없으면 특정 상품 KB 우선 또는 에러)
# GENERAL_KNOWLEDGE_BASE_PATH = DATA_DIR / "general_faq.md" 

PROMPT_FILES = {
    'main_agent': CONFIG_DIR / "main_agent_prompts.yaml",
    'scenario_agent': CONFIG_DIR / "scenario_agent_prompts.yaml",
    'qa_agent': CONFIG_DIR / "qa_agent_prompts.yaml",
}

# --- LLM 초기화 ---
if not OPENAI_API_KEY:
    print("CRITICAL: OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
main_llm = ChatOpenAI(
    model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.1,
    model_kwargs={"response_format": {"type": "json_object"}}
) if OPENAI_API_KEY else None

streaming_llm = ChatOpenAI(
    model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.3, streaming=True
) if OPENAI_API_KEY else None


# --- 프롬프트 및 데이터 로드 함수 ---
ALL_PROMPTS: Dict[str, Dict[str, str]] = {}
ALL_SCENARIOS_DATA: Dict[PRODUCT_TYPES, Dict] = {} # 타입 변경
ALL_KNOWLEDGE_BASES: Dict[PRODUCT_TYPES, Optional[str]] = {"didimdol": None, "jeonse": None, "deposit_account": "NOT_AVAILABLE"}

def load_all_prompts_sync() -> None:
    global ALL_PROMPTS
    loaded_prompts = {}
    try:
        for agent_name, file_path in PROMPT_FILES.items():
            with open(file_path, 'r', encoding='utf-8') as f:
                prompts_for_agent = yaml.safe_load(f)
            if not prompts_for_agent:
                raise ValueError(f"{agent_name} 프롬프트 파일이 비어있거나 로드에 실패했습니다: {file_path}") #
            loaded_prompts[agent_name] = prompts_for_agent
        ALL_PROMPTS = loaded_prompts
        print("--- 모든 에이전트 프롬프트 로드 완료 ---") #
    except Exception as e:
        print(f"프롬프트 파일 로드 중 치명적 오류 발생: {e}")
        raise

def load_all_scenarios_sync() -> None:
    global ALL_SCENARIOS_DATA
    loaded_scenarios = {}
    try:
        for loan_type, file_path in SCENARIO_FILES.items():
            with open(file_path, 'r', encoding='utf-8') as f:
                scenario = json.load(f)
            if not scenario: raise ValueError(f"{loan_type} 시나리오 파일이 비어있습니다: {file_path}") #
            loaded_scenarios[loan_type] = scenario
        ALL_SCENARIOS_DATA = cast(Dict[Literal["didimdol", "jeonse"], Dict], loaded_scenarios)
        print("--- 모든 대출 시나리오 데이터 로드 완료 ---") #
    except Exception as e:
        print(f"시나리오 파일 로드 중 치명적 오류 발생: {e}")
        raise

async def load_knowledge_base_content_async(loan_type: Literal["didimdol", "jeonse"]) -> Optional[str]:
    global ALL_KNOWLEDGE_BASES
    if loan_type not in KNOWLEDGE_BASE_FILES: # 입출금 통장 등 KB 파일이 정의되지 않은 경우
        print(f"경고: '{loan_type}'에 대한 지식베이스 파일이 정의되지 않았습니다.")
        ALL_KNOWLEDGE_BASES[loan_type] = "NOT_AVAILABLE" # 명시적으로 KB 없음을 표시
        return None
    if ALL_KNOWLEDGE_BASES.get(loan_type) is None or "ERROR" in str(ALL_KNOWLEDGE_BASES.get(loan_type)):
        file_path = KNOWLEDGE_BASE_FILES[loan_type]
        print(f"--- QA Agent: '{loan_type}' 지식베이스 ({file_path.name}) 로딩 중... ---") #
        try:
            if not file_path.exists():
                print(f"경고: '{loan_type}' 지식베이스 파일을 찾을 수 없습니다: {file_path}") #
                ALL_KNOWLEDGE_BASES[loan_type] = "ERROR_FILE_NOT_FOUND" #
                return None
            with open(file_path, 'r', encoding='utf-8') as f: content = f.read()
            if not content.strip():
                print(f"경고: '{loan_type}' 지식베이스 파일이 비어있습니다: {file_path}") #
                ALL_KNOWLEDGE_BASES[loan_type] = "EMPTY_CONTENT" #
                return None
            ALL_KNOWLEDGE_BASES[loan_type] = content
            print(f"--- QA Agent: '{loan_type}' 지식베이스 로딩 완료 ({len(content)} 자) ---") #
        except Exception as e:
            print(f"'{loan_type}' QA 지식베이스 로딩 실패: {e}") #
            ALL_KNOWLEDGE_BASES[loan_type] = "ERROR_LOADING_FAILED" #
            return None
    
    if str(ALL_KNOWLEDGE_BASES.get(loan_type)).startswith("ERROR_") or ALL_KNOWLEDGE_BASES.get(loan_type) == "NOT_AVAILABLE":
        return None
    return ALL_KNOWLEDGE_BASES[loan_type]

# async def load_general_knowledge_base_async(): # 필요한 경우 일반 QA용
#     global GENERAL_KNOWLEDGE_BASE_CONTENT
#     # ... 로직 ...

# 애플리케이션 시작 시 동기적으로 로드
load_all_prompts_sync()
load_all_scenarios_sync()


def get_active_scenario_data(state: AgentState) -> Optional[Dict]:
    loan_type = state.get("current_product_type")
    if loan_type:
        return ALL_SCENARIOS_DATA.get(loan_type)
    return None

async def get_active_knowledge_base(state: AgentState) -> Optional[str]:
    loan_type = state.get("current_product_type")
    if loan_type:
        return await load_knowledge_base_content_async(loan_type)
    # else:
    #     # 일반 QA 시나리오에서는 특정 KB를 로드하지 않음 (invoke_qa_agent_streaming_logic에서 처리)
    #     print("일반 QA 요청: 특정 상품 지식베이스를 로드하지 않습니다.")
    return None


def format_messages_for_prompt(messages: Sequence[BaseMessage], max_history: int = 5) -> str: # max_history 증가 고려
    history_str = []
    # 이제 SystemMessage도 포함하여 최근 히스토리를 구성
    relevant_messages = [m for m in messages if isinstance(m, (HumanMessage, AIMessage, SystemMessage))][-(max_history * 2):]
    for msg in relevant_messages:
        if isinstance(msg, HumanMessage):
            role = "사용자"
        elif isinstance(msg, AIMessage):
            role = "상담원"
        else: # SystemMessage
            role = "시스템"
        history_str.append(f"{role}: {msg.content}")
    return "\n".join(history_str) if history_str else "이전 대화 없음."


def format_transitions_for_prompt(transitions: List[Dict[str, Any]], current_stage_prompt: str) -> str:
    if not transitions:
        return "현재 단계에서 다음으로 넘어갈 수 있는 조건(Transition)이 정의되지 않았습니다." #
    formatted_list = [f"현재 단계의 사용자 안내/질문: \"{current_stage_prompt}\""] #
    for i, transition in enumerate(transitions):
        condition_desc = transition.get("condition_description", "조건 설명 없음") #
        example_phrases_str = ", ".join(f"'{p}'" for p in transition.get("example_phrases", [])) #
        if example_phrases_str:
            condition_desc += f" (예시: {example_phrases_str})" #
        formatted_list.append(f"{i+1}. 다음 단계 ID: '{transition['next_stage_id']}', 조건: {condition_desc}") #
    
    return "\n".join(formatted_list)


async def invoke_scenario_agent_logic(
    user_input: str, current_stage_prompt: str, expected_info_key: Optional[str],
    messages_history: Sequence[BaseMessage], scenario_name: str
) -> ScenarioAgentOutput:
    if not main_llm:
        return cast(ScenarioAgentOutput, {"intent": "error_llm_not_initialized", "entities": {}, "is_scenario_related": False}) #
    
    print(f"--- Scenario Agent 호출 (시나리오: '{scenario_name}', 입력: '{user_input[:50]}...') ---")
    prompt_template = ALL_PROMPTS.get('scenario_agent', {}).get('nlu_extraction', '') #
    if not prompt_template:
        return cast(ScenarioAgentOutput, {"intent": "error_prompt_not_found", "entities": {}, "is_scenario_related": False}) #

    formatted_history = format_messages_for_prompt(messages_history) #
    try:
        format_instructions = scenario_output_parser.get_format_instructions() #
        formatted_prompt = prompt_template.format(
            scenario_name=scenario_name, current_stage_prompt=current_stage_prompt,
            expected_info_key=expected_info_key or "특정 정보 없음",
            formatted_messages_history=formatted_history, user_input=user_input,
            format_instructions=format_instructions
        )
        response = await main_llm.ainvoke([HumanMessage(content=formatted_prompt)]) #
        raw_response_content = response.content.strip() #
        print(f"LLM Raw Response: {raw_response_content}") #
        
        if raw_response_content.startswith("```json"): raw_response_content = raw_response_content.replace("```json", "").replace("```", "").strip() #
        
        parsed_output_dict = scenario_output_parser.parse(raw_response_content).model_dump() #
        print(f"Scenario Agent 결과: {parsed_output_dict}") #
        return cast(ScenarioAgentOutput, parsed_output_dict)
    except Exception as e:
        print(f"Scenario Agent 처리 오류: {e}. LLM 응답: {getattr(e, 'llm_output', getattr(response if 'response' in locals() else None, 'content', 'N/A'))}") #
        return cast(ScenarioAgentOutput, {"intent": "error_parsing_scenario_output", "entities": {}, "is_scenario_related": False}) #


async def invoke_qa_agent_streaming_logic(user_question: str, scenario_name: str, knowledge_base_text: Optional[str]) -> AsyncGenerator[str, None]:
    if not streaming_llm:
        yield "죄송합니다, 답변 생성 서비스가 현재 사용할 수 없습니다. (LLM 초기화 오류)" #
        return
    
    print(f"--- QA Agent 스트리밍 호출 (컨텍스트: '{scenario_name}', 질문: '{user_question[:50]}...') ---")
    if knowledge_base_text is None:
        # IMPROVEMENT: Handle general QA when no specific KB is loaded
        if scenario_name == "일반 금융 상담":
            # For general queries where no specific KB is expected,
            # we can directly use the LLM for a general answer or provide a specific message.
            # Here, we'll try to answer generally using the LLM without specific context.
            # Alternatively, provide a canned response.
            general_qa_prompt_template = ALL_PROMPTS.get('qa_agent', {}).get('rag_answer_generation', '') # Re-use or use a new one
            if not general_qa_prompt_template:
                yield "죄송합니다, 답변 생성에 필요한 설정(프롬프트)을 찾을 수 없습니다."
                return
            
            # Format prompt for general QA (no specific context)
            # The RAG prompt expects a context; for general QA, we might pass an empty string
            # or modify the prompt to handle cases with no context better.
            # For now, we'll pass a message indicating no specific context.
            general_context_info = "특정 상품 문서가 제공되지 않았습니다. 일반적인 금융 상식 또는 사용자의 질문 자체에만 기반하여 답변해주세요."
            formatted_prompt = general_qa_prompt_template.format(
                scenario_name=scenario_name, 
                context_for_llm=general_context_info, # Or an empty string
                user_question=user_question
            )
            try:
                print(f"QA Agent (일반): 프롬프트 전송 (특정 문서 없음)")
                async for chunk in streaming_llm.astream([HumanMessage(content=formatted_prompt)]):
                    if isinstance(chunk, AIMessageChunk) and chunk.content:
                        yield str(chunk.content)
            except Exception as e:
                print(f"일반 QA Agent 스트리밍 처리 오류: {e}")
                yield f"질문 답변 중 시스템 오류가 발생했습니다: {str(e)}"
            return # End execution for general QA here.

        # Original logic for when a specific KB was expected but not found
        error_message = f"죄송합니다. '{scenario_name}' 관련 정보를 현재 조회할 수 없습니다 (지식베이스 문제)."
        if scenario_name == "미정": # Should have been caught by general QA logic above ideally
            error_message = "죄송합니다. 현재 대출 관련 일반 정보를 조회할 수 없습니다 (지식베이스 문제)."
        yield error_message
        return

    prompt_template = ALL_PROMPTS.get('qa_agent', {}).get('rag_answer_generation', '') #
    if not prompt_template:
        yield "죄송합니다, 답변 생성에 필요한 설정(프롬프트)을 찾을 수 없습니다." #
        return

    formatted_prompt = prompt_template.format(
        scenario_name=scenario_name, context_for_llm=knowledge_base_text, user_question=user_question
    ) #
    try:
        async for chunk in streaming_llm.astream([HumanMessage(content=formatted_prompt)]): #
            if isinstance(chunk, AIMessageChunk) and chunk.content: #
                yield str(chunk.content)
    except Exception as e:
        print(f"QA Agent 스트리밍 처리 오류: {e}") #
        yield f"질문 답변 중 시스템 오류가 발생했습니다: {str(e)}" #


# --- LangGraph 노드 함수 정의 ---
async def entry_point_node(state: AgentState) -> AgentState:
    print("--- 노드: Entry Point ---") #
    if not ALL_SCENARIOS_DATA or not ALL_PROMPTS:
        error_msg = "상담 서비스 초기화 실패 (시나리오 또는 프롬프트 데이터 로드 불가)." #
        print(f"CRITICAL: 필수 데이터가 로드되지 않았습니다.")
        return {**state, "error_message": error_msg, "final_response_text_for_tts": error_msg, "is_final_turn_response": True} #

    turn_specific_defaults: Dict[str, Any] = {
        "stt_result": None, "main_agent_routing_decision": None, "main_agent_direct_response": None, #
        "scenario_agent_output": None, "final_response_text_for_tts": None, #
        "is_final_turn_response": False, "error_message": None, #
        "active_scenario_data": None, "active_knowledge_base_content": None, "active_scenario_name": None, #
        "available_product_types": ["didimdol", "jeonse", "deposit_account"], # 신규 추가
        "loan_selection_is_fresh": False, # Reset flag at the start of the turn
    }
    
    current_product_type = state.get("current_product_type") #
    updated_state = {**state, **turn_specific_defaults} #
    updated_state["current_product_type"] = current_product_type #

    if current_product_type:
        active_scenario = ALL_SCENARIOS_DATA.get(current_product_type) #
        if active_scenario:
            updated_state["active_scenario_data"] = active_scenario #
            updated_state["active_scenario_name"] = active_scenario.get("scenario_name", "알 수 없는 상품") #
            if not updated_state.get("current_scenario_stage_id"): #
                 updated_state["current_scenario_stage_id"] = active_scenario.get("initial_stage_id") #
        else:
            updated_state["error_message"] = f"선택하신 '{current_product_type}' 상품 정보를 불러올 수 없습니다." #
            updated_state["current_product_type"] = None #
    else:
        updated_state["active_scenario_name"] = "미정" #

    initial_messages: List[BaseMessage] = list(state.get("messages", [])) #
    updated_state["messages"] = initial_messages #

    user_text_for_turn = updated_state.get("stt_result") or updated_state.get("user_input_text") #
    
    if user_text_for_turn:
        current_messages = list(updated_state.get("messages", [])) #
        if not current_messages or not (isinstance(current_messages[-1], HumanMessage) and current_messages[-1].content == user_text_for_turn): #
            current_messages.append(HumanMessage(content=user_text_for_turn)) #
        updated_state["messages"] = current_messages #
        updated_state["stt_result"] = user_text_for_turn #
    elif not updated_state.get("user_input_audio_b64"): #
        if not initial_messages: #
             pass
    return cast(AgentState, updated_state)


async def main_agent_router_node(state: AgentState) -> AgentState:
    print("--- 노드: Main Agent Router ---") #
    if not main_llm:
        return {**state, "error_message": "라우터 서비스 사용 불가 (LLM 미초기화)", "final_response_text_for_tts": "시스템 설정 오류입니다.", "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True} #

    user_input = state.get("stt_result", "") #
    messages_history = state.get("messages", []) #
    current_product_type = state.get("current_product_type") #
    active_scenario_data = get_active_scenario_data(state) #
    session_id = state.get("session_id", "")
    
    prompt_template_key = ""
    if not current_product_type: # 상품 유형 미선택 (초기 또는 사용자가 명확히 안했을 때)
        # 사용자 입력이 없어도 (예: 초기 접속 시) initial_task_selection_prompt를 타도록 유도
        # 단, chat.py에서 초기 메시지를 보내고, 사용자 첫 입력부터 이 그래프가 처리하는 것이 더 자연스러움.
        # 현재 로직은 user_input이 있어야 이 노드에 의미있게 도달함.
        if not user_input and not state.get("messages"): # 첫 턴이고 입력 없음
             # 이 경우는 entry_point에서 처리되어 main_agent_router_node로 오지 않거나,
             # chat.py에서 초기 메시지를 보낸 후 사용자의 첫 발화를 기다리는 상태여야 함.
             # 만약 chat.py에서 초기 메시지를 보내지 않고 바로 여기로 온다면, 사용자에게 선택을 유도하는 응답 필요.
             print("Main Agent Router: 초기 상태, 사용자 입력 대기 중 (또는 chat.py에서 초기 안내 필요)")
             # 다음 턴에 사용자가 입력하면 initial_task_selection_prompt를 타도록 설정.
             # 여기서는 직접적인 응답 생성보다는, 다음 턴을 위한 상태 준비에 집중.
             # 또는, "select_product_type" 액션과 함께 안내 메시지를 direct_response에 설정.
             return {**state, "main_agent_routing_decision": "select_product_type", "main_agent_direct_response": "안녕하세요! 어떤 대출 상품에 대해 궁금하신가요? (디딤돌 대출, 전세자금 대출 등)"}

        prompt_template_key = 'initial_task_selection_prompt' #
        print(f"Main Agent Router: 상품 유형 미선택, 사용자 입력 ('{user_input[:30]}...')으로 초기 작업 선택.") #
    else: # 상품 유형 선택된 상태
        prompt_template_key = 'router_prompt' #
        print(f"Main Agent Router: 현재 상품 유형 '{current_product_type}', 라우터 프롬프트 사용.") #

    prompt_template = ALL_PROMPTS.get('main_agent', {}).get(prompt_template_key, '') #
    if not prompt_template:
         return {**state, "error_message": "라우터 프롬프트 로드 실패", "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True} #

    history_for_prompt = list(messages_history[:-1]) if messages_history and isinstance(messages_history[-1], HumanMessage) else list(messages_history) #
    formatted_history_str = format_messages_for_prompt(history_for_prompt) #
    
    current_stage_id_for_prompt = state.get("current_scenario_stage_id", "정보 없음") #
    current_stage_prompt_for_prompt = "정보 없음" #
    expected_info_key_for_prompt = "정보 없음" #
    active_scenario_name_for_prompt = state.get("active_scenario_name", "미정") #

    if active_scenario_data and current_product_type: #
        current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id_for_prompt), {}) #
        current_stage_prompt_for_prompt = current_stage_info.get("prompt", "안내 없음") #
        expected_info_key_for_prompt = current_stage_info.get("expected_info_key", "정보 없음") #
    
    available_product_types_display = ", ".join([ALL_SCENARIOS_DATA[lt]["scenario_name"] for lt in state.get("available_product_types", []) if lt in ALL_SCENARIOS_DATA])

    response_parser = None
    try:
        if prompt_template_key == 'initial_task_selection_prompt':
            response_parser = initial_task_decision_parser #
            format_instructions = response_parser.get_format_instructions()
            main_agent_prompt_filled = prompt_template.format(
                user_input=user_input,
                format_instructions=format_instructions # 주입
            )
        else: # router_prompt
            response_parser = main_router_decision_parser #
            format_instructions = response_parser.get_format_instructions()
            main_agent_prompt_filled = prompt_template.format(
                user_input=user_input, #
                active_scenario_name=active_scenario_name_for_prompt, #
                formatted_messages_history=formatted_history_str, #
                current_scenario_stage_id=current_stage_id_for_prompt, #
                current_stage_prompt=current_stage_prompt_for_prompt, #
                collected_product_info=str(state.get("collected_product_info", {})), #
                expected_info_key=expected_info_key_for_prompt, #
                available_product_types_display=available_product_types_display, #
                format_instructions=format_instructions # 주입
            )
        
        response = await main_llm.ainvoke([HumanMessage(content=main_agent_prompt_filled)]) #
        raw_response_content = response.content.strip() #
        print(f"[{session_id}] LLM Raw Response: {raw_response_content}") # 로깅 추가
        
        if raw_response_content.startswith("```json"): raw_response_content = raw_response_content.replace("```json", "").replace("```", "").strip() #
        


        parsed_decision = response_parser.parse(raw_response_content)
        
        # return {**state, **new_state_changes}

        
        new_state_changes: Dict[str, Any] = {"main_agent_routing_decision": parsed_decision.action} #
        if hasattr(parsed_decision, 'direct_response') and parsed_decision.direct_response: #
            new_state_changes["main_agent_direct_response"] = parsed_decision.direct_response #
        if hasattr(parsed_decision, 'extracted_value') and parsed_decision.extracted_value: #
            if active_scenario_data and current_product_type: #
                current_stage_info = active_scenario_data.get("stages", {}).get(str(state.get("current_scenario_stage_id")), {}) #
                key_to_collect = current_stage_info.get("expected_info_key") #
                entities_direct = {key_to_collect: parsed_decision.extracted_value} if key_to_collect else {} #
                new_state_changes["scenario_agent_output"] = cast(ScenarioAgentOutput, { #
                    "intent": f"direct_input_{str(parsed_decision.extracted_value)[:20].replace(' ','_').lower()}",  #
                    "entities": entities_direct,  #
                    "is_scenario_related": True #
                })
        
        # Action 결정 내용을 SystemMessage로 만들어 히스토리에 추가
        system_log_message = f"Main Agent 판단 결과: action='{parsed_decision.action}'"
        if hasattr(parsed_decision, 'direct_response') and parsed_decision.direct_response:
            system_log_message += f", direct_response='{parsed_decision.direct_response[:30]}...'"

        # 기존 메시지 목록에 시스템 메시지 추가
        updated_messages = list(state.get("messages", []))
        updated_messages.append(SystemMessage(content=system_log_message))
        new_state_changes["messages"] = updated_messages # 상태 업데이트에 포함

        print(f"Main Agent 최종 결정: {new_state_changes.get('main_agent_routing_decision')}")

        if prompt_template_key == 'initial_task_selection_prompt':
            initial_decision = cast(InitialTaskDecisionModel, parsed_decision) #
            if initial_decision.action == "proceed_with_product_type_didimdol":
                new_state_changes["current_product_type"] = "didimdol" #
                new_state_changes["main_agent_routing_decision"] = "set_product_type_didimdol" #
                new_state_changes["loan_selection_is_fresh"] = True # SET FLAG
            elif initial_decision.action == "proceed_with_product_type_jeonse":
                new_state_changes["current_product_type"] = "jeonse" #
                new_state_changes["main_agent_routing_decision"] = "set_product_type_jeonse" #
                new_state_changes["loan_selection_is_fresh"] = True # SET FLAG
            elif initial_decision.action == "proceed_with_product_type_deposit_account": # 신규 추가
                new_state_changes["current_product_type"] = "deposit_account"
                new_state_changes["main_agent_routing_decision"] = "set_product_type_deposit_account"
                new_state_changes["loan_selection_is_fresh"] = True
            elif initial_decision.action == "invoke_qa_agent_general":
                new_state_changes["main_agent_routing_decision"] = "invoke_qa_agent" #
                new_state_changes["active_scenario_name"] = "일반 금융 상담" #
            elif initial_decision.action == "clarify_product_type":
                new_state_changes["main_agent_routing_decision"] = "select_product_type" #
                new_state_changes["main_agent_direct_response"] = initial_decision.direct_response or \
                    f"어떤 상품에 대해 안내해 드릴까요? {available_product_types_display} 중에서 선택해주세요." #
            elif initial_decision.action == "answer_directly_chit_chat":
                 new_state_changes["main_agent_routing_decision"] = "answer_directly_chit_chat" #
                 new_state_changes["main_agent_direct_response"] = initial_decision.direct_response #
            else: 
                 new_state_changes["main_agent_routing_decision"] = "unclear_input" #

        print(f"Main Agent 최종 결정: {new_state_changes.get('main_agent_routing_decision')}, 직접 답변: {new_state_changes.get('main_agent_direct_response')}, 다음 상품 유형: {new_state_changes.get('current_product_type')}") #
        return {**state, **new_state_changes}

    except json.JSONDecodeError as je:
        err_msg = "요청을 이해하는 중 내부 오류가 발생했습니다 (JSON 파싱). 다시 시도해주세요." #
        print(f"Main Agent Router JSON 파싱 오류: {je}. LLM 응답: {getattr(response if 'response' in locals() else None, 'content', 'N/A')}") #
        return {**state, "error_message": err_msg, "final_response_text_for_tts":err_msg, "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True} #
    except Exception as e:
        err_msg = "요청 처리 중 시스템 오류가 발생했습니다. 잠시 후 다시 시도해주세요." #
        print(f"Main Agent Router 시스템 오류: {e}"); import traceback; traceback.print_exc() #
        return {**state, "error_message": err_msg, "final_response_text_for_tts": err_msg, "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True} #


async def call_scenario_agent_node(state: AgentState) -> AgentState:
    print("--- 노드: Scenario Agent 호출 ---") #
    user_input = state.get("stt_result", "") #
    current_product_type = state.get("current_product_type") #
    active_scenario_data = get_active_scenario_data(state) #

    if not current_product_type or not active_scenario_data: #
        return {**state, "error_message": "시나리오 에이전트 호출 실패: 현재 상품 유형 또는 시나리오 데이터가 없습니다.",  #
                "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True} #

    if not user_input and user_input != "": #
        return {**state, "scenario_agent_output": cast(ScenarioAgentOutput, {"intent": "no_input", "entities": {}, "is_scenario_related": False})} #

    current_stage_id = state.get("current_scenario_stage_id") #
    if not current_stage_id: #
        current_stage_id = active_scenario_data.get("initial_stage_id") #
        if not current_stage_id: #
             return {**state, "error_message": f"'{current_product_type}' 상품의 시작 단계를 찾을 수 없습니다.", "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True} #

    current_stage_info = active_scenario_data.get("stages", {}) #
    current_stage_id_for_state: str

    output = await invoke_scenario_agent_logic(
        user_input=user_input,
        current_stage_prompt=current_stage_info.get("prompt", ""),
        expected_info_key=current_stage_info.get("expected_info_key"),
        messages_history=state.get("messages", [])[:-1],
        scenario_name=active_scenario_data.get("scenario_name", "대출 상담")
    ) #
    return {**state, "scenario_agent_output": output} #

async def call_qa_agent_node(state: AgentState) -> AgentState:
    print("--- 노드: QA Agent 호출 준비 (스트리밍은 run_agent_streaming에서 직접 처리) ---") #
    current_product_type = state.get("current_product_type") #
    active_scenario_name = state.get("active_scenario_name", "일반 금융 상담") #

    # active_knowledge_base_content는 run_agent_streaming에서 kb_content_for_qa로 직접 로드하여
    # invoke_qa_agent_streaming_logic에 전달됩니다.
    # 따라서 이 노드에서 kb를 로드하거나 state에 저장할 필요는 없습니다.
    # 다만, kb 로드 실패 시의 처리를 위해 여기서 미리 체크해볼 수는 있습니다.
    if current_product_type:
        # 여기서 kb를 미리 로드해서 state.active_knowledge_base_content에 넣을 수도 있으나,
        # 스트리밍 함수에서 직접 로드하는 것이 비동기 흐름에 더 적합할 수 있음.
        # kb 로드 실패에 대한 처리는 invoke_qa_agent_streaming_logic 내부 또는
        # run_agent_streaming 함수에서 이루어지도록 함.
        pass
    
    # 만약 KB 로드 실패가 routing 결정에 영향을 줘야 한다면, 여기서 로드 시도하고
    # 실패 시 state에 에러 메시지를 설정하고 다른 노드로 라우팅할 수 있음.
    # 현재는 run_agent_streaming에서 QA 로직 실행 시 KB를 로드함.
    # 로그에서 "컨텍스트: '일반 금융 상담'"으로 나오는 것은 active_scenario_name이 그렇게 설정되었기 때문.
    # current_product_type이 None일 때 active_scenario_name이 "일반 금융 상담"으로 설정됨.
    # invoke_qa_agent_streaming_logic은 이 scenario_name과 None인 knowledge_base_text를 받음.
    # invoke_qa_agent_streaming_logic 내부에서 knowledge_base_text가 None이고 scenario_name이 "일반 금융 상담"일 때
    # 적절한 일반 응답을 생성하도록 수정 필요.

    return state #


async def main_agent_scenario_processing_node(state: AgentState) -> AgentState:
    print("--- 노드: Main Agent 시나리오 처리 (다음 단계 결정 및 응답 생성) ---") #
    if not main_llm:
         return {**state, "error_message": "시나리오 처리 서비스 사용 불가 (LLM 미초기화)", "final_response_text_for_tts": "시스템 설정 오류로 다음 안내를 드릴 수 없습니다.", "is_final_turn_response": True} #

    user_input = state.get("stt_result", "") #
    scenario_output = state.get("scenario_agent_output") #
    current_product_type = state.get("current_product_type") #
    active_scenario_data = get_active_scenario_data(state) #
    
    if not current_product_type or not active_scenario_data: #
        return {**state, "error_message": "시나리오 처리 실패: 현재 상품 유형 또는 시나리오 데이터가 없습니다.", "is_final_turn_response": True} #

    current_stage_id = state.get("current_scenario_stage_id") #
    if not current_stage_id: #
        current_stage_id = active_scenario_data.get("initial_stage_id") #
        if not current_stage_id : #
             return {**state, "error_message": f"'{current_product_type}' 상품의 시작 단계를 찾을 수 없습니다.", "is_final_turn_response": True} #

    stages_data = active_scenario_data.get("stages", {}) #
    current_stage_info = stages_data.get(str(current_stage_id), {}) #
    collected_info = state.get("collected_product_info", {}).copy() #

    final_response_text_for_user: str = active_scenario_data.get("fallback_message", "죄송합니다, 처리 중 오류가 발생했습니다.") #
    determined_next_stage_id: str = str(current_stage_id) #

    if scenario_output and scenario_output.get("is_scenario_related"): #
        extracted_entities = scenario_output.get("entities", {}) #
        for key, value in extracted_entities.items(): #
            if value is not None: #
                collected_info[key] = value; print(f"정보 업데이트 ({current_product_type}): {key} = {value}") #
        
        prompt_template = ALL_PROMPTS.get('main_agent', {}).get('determine_next_scenario_stage', '') #
        if not prompt_template: #
            print("오류: 다음 단계 결정 프롬프트를 찾을 수 없습니다.")
            determined_next_stage_id = current_stage_info.get("default_next_stage_id", current_stage_id) #
        else:
            scenario_agent_intent_str = scenario_output.get("intent", "정보 없음") #
            scenario_agent_entities_str = str(scenario_output.get("entities", {})) #
            current_transitions = current_stage_info.get("transitions", []) #
            formatted_transitions_str = format_transitions_for_prompt(current_transitions, current_stage_info.get("prompt","")) #

            llm_prompt_for_next_stage = prompt_template.format(
                active_scenario_name=active_scenario_data.get("scenario_name", "대출 상담"), #
                current_stage_id=str(current_stage_id), #
                current_stage_prompt=current_stage_info.get("prompt", "안내 없음"), #
                user_input=user_input, #
                scenario_agent_intent=scenario_agent_intent_str, #
                scenario_agent_entities=scenario_agent_entities_str, #
                collected_product_info=str(collected_info), #
                formatted_transitions=formatted_transitions_str, #
                default_next_stage_id=current_stage_info.get("default_next_stage_id", "None") #
            )
            try:
                response = await main_llm.ainvoke([HumanMessage(content=llm_prompt_for_next_stage)]) #
                raw_response_content = response.content.strip() #
                print(f"LLM Raw Response: {raw_response_content}") # 로깅 추가
                
                if raw_response_content.startswith("```json"): raw_response_content = raw_response_content.replace("```json", "").replace("```", "").strip() #
                decision_data = next_stage_decision_parser.parse(raw_response_content)  #
                determined_next_stage_id = decision_data.chosen_next_stage_id #
                print(f"LLM 결정 다음 단계 ID ('{current_product_type}' 시나리오): '{determined_next_stage_id}'") #
                if determined_next_stage_id not in stages_data and \
                   determined_next_stage_id not in ["END_SCENARIO_COMPLETE", "END_SCENARIO_ABORT", f"qa_listen_{current_product_type}"]: #
                    print(f"경고: LLM이 반환한 다음 단계 ID ('{determined_next_stage_id}')가 유효하지 않습니다. 기본 다음 단계를 사용합니다.") #
                    determined_next_stage_id = current_stage_info.get("default_next_stage_id", str(current_stage_id)) #
            except Exception as e:
                print(f"다음 단계 결정 LLM 오류: {e}. LLM Raw: {getattr(response if 'response' in locals() else None, 'content', 'N/A')}. 기본 다음 단계 사용.") #
                determined_next_stage_id = current_stage_info.get("default_next_stage_id", str(current_stage_id)) #
    
    if not determined_next_stage_id or determined_next_stage_id == "None": #
        if current_stage_id not in ["END_SCENARIO_COMPLETE", "END_SCENARIO_ABORT"] and not str(current_stage_id).startswith("qa_listen"): #
            print(f"'{current_product_type}' 시나리오: 명시적인 다음 단계 없음. 시나리오 완료로 간주.")
            determined_next_stage_id = "END_SCENARIO_COMPLETE" #
        elif not determined_next_stage_id : #
            determined_next_stage_id = str(current_stage_id) #

    target_stage_info = stages_data.get(determined_next_stage_id, {}) #
    if determined_next_stage_id == "END_SCENARIO_COMPLETE": #
        final_response_text_for_user = active_scenario_data.get("end_scenario_message", "상담이 완료되었습니다.") #
    elif determined_next_stage_id == "END_SCENARIO_ABORT": #
        final_response_text_for_user = target_stage_info.get("prompt") or active_scenario_data.get("end_conversation_message", "상담을 종료합니다.") #
    elif str(determined_next_stage_id).startswith("qa_listen"): #
        final_response_text_for_user = target_stage_info.get("prompt") or ALL_PROMPTS.get('main_agent',{}).get('qa_follow_up_prompt', "다른 궁금한 점이 있으시면 말씀해주세요.") #
    else: 
        final_response_text_for_user = target_stage_info.get("prompt", active_scenario_data.get("fallback_message")) #
        if "%{" in final_response_text_for_user: #
            import re #
            def replace_placeholder(match): key = match.group(1); return str(collected_info.get(key, f"%{{{key}}}%"))  #
            final_response_text_for_user = re.sub(r'%\{([^}]+)\}%', replace_placeholder, final_response_text_for_user) #

    print(f"Main Agent 시나리오 처리 결과 ({current_product_type}): 다음 사용자 안내 '{final_response_text_for_user[:70]}...', 다음 단계 ID '{determined_next_stage_id}'") #
    updated_messages = list(state.get("messages", [])) #
    if not updated_messages or not (isinstance(updated_messages[-1], AIMessage) and updated_messages[-1].content == final_response_text_for_user): #
         updated_messages.append(AIMessage(content=final_response_text_for_user)) #
    
    return {
        **state, 
        "collected_product_info": collected_info,  #
        "current_scenario_stage_id": determined_next_stage_id, #
        "final_response_text_for_tts": final_response_text_for_user,  #
        "messages": updated_messages, #
        "is_final_turn_response": True #
    }

async def prepare_direct_response_node(state: AgentState) -> AgentState:
    print("--- 노드: 직접 응답 준비 (칫챗, 상품 유형 선택 안내 등) ---") #
    response_text = state.get("main_agent_direct_response") #
    
    if not response_text: #
        active_scenario = get_active_scenario_data(state) #
        fallback_msg = active_scenario.get("fallback_message") if active_scenario else "죄송합니다, 잘 이해하지 못했습니다." #
        response_text = fallback_msg #
        print(f"경고: prepare_direct_response_node에 direct_response 없음. fallback 사용: {response_text}")

    updated_messages = list(state.get("messages", [])) #
    if not updated_messages or not (isinstance(updated_messages[-1], AIMessage) and updated_messages[-1].content == response_text): #
        updated_messages.append(AIMessage(content=response_text)) #
    
    next_stage_id = state.get("current_scenario_stage_id") #
    if state.get("main_agent_routing_decision") == "select_product_type": #
        pass 
    elif state.get("current_product_type"): #
        pass #
    else: 
        pass

    return {**state, "final_response_text_for_tts": response_text, "messages": updated_messages, "is_final_turn_response": True, "current_scenario_stage_id": next_stage_id} #


async def set_product_type_node(state: AgentState) -> AgentState: # AgentState 타입 변경 반영
    print(f"--- 노드: 상품 유형 설정 ---") # 명칭 변경
    routing_decision = state.get("main_agent_routing_decision")
    new_product_type: Optional[PRODUCT_TYPES] = None # 타입 변경

    if routing_decision == "set_product_type_didimdol":
        new_product_type = "didimdol"
    elif routing_decision == "set_product_type_jeonse":
        new_product_type = "jeonse"
    elif routing_decision == "set_product_type_deposit_account": # 신규 추가
        new_product_type = "deposit_account"
    
    if new_product_type and new_product_type in ALL_SCENARIOS_DATA:
        active_scenario = ALL_SCENARIOS_DATA[new_product_type]
        initial_stage_id_from_scenario = active_scenario.get("initial_stage_id")
        
        final_response_for_user: str
        current_stage_id_for_state: str

        user_just_selected = state.get("loan_selection_is_fresh", False)

        if user_just_selected:
            acknowledgement = f"네, {active_scenario.get('scenario_name', new_product_type + ' 상품')}에 대해 안내해 드리겠습니다. "
            
            first_question_stage_id: Optional[str] = None
            if new_product_type == "didimdol":
                first_question_stage_id = "ask_loan_purpose"
            elif new_product_type == "jeonse":
                first_question_stage_id = "ask_marital_status_jeonse" # 시나리오에 따라 조정
            elif new_product_type == "deposit_account": # 신규 추가
                first_question_stage_id = "ask_lifelong_account" # 입출금 통장 시나리오의 첫 질문으로 바로 이동 (greeting_deposit은 선택 유도 후 실제 정보수집 시작점)
                                                                  # greeting_deposit에서 부가서비스 선택에 따라 분기되므로, acknowledgemnet 이후 greeting_deposit의 prompt를 붙이는게 나을수도 있음.
                                                                  # 여기서는 일단 시나리오의 initial_stage_id를 따르도록 수정 (아래 로직과 통일)
                first_question_stage_id = initial_stage_id_from_scenario


            # 수정된 로직: user_just_selected 시 acknowledgemnt + initial_stage_id의 프롬프트 사용
            if first_question_stage_id and first_question_stage_id in active_scenario.get("stages", {}):
                prompt_of_first_stage = active_scenario["stages"][first_question_stage_id].get("prompt")
                if prompt_of_first_stage:
                    # 입출금통장의 greeting_deposit은 안내가 길고, 그 자체로 사용자의 선택을 유도하므로, acknowledgemnt와 합치기보다 그대로 사용하는게 나을 수 있음.
                    # 여기서는 상품 선택에 대한 확인 후, 해당 상품의 초기 프롬프트를 바로 출력하는 것으로 통일.
                    if new_product_type == "deposit_account": # 입출금 통장은 안내가 포함된 초기 프롬프트
                         final_response_for_user = prompt_of_first_stage
                    else: # 기존 대출 상품들은 간결한 안내 + 초기 프롬프트
                        final_response_for_user = acknowledgement + prompt_of_first_stage
                    current_stage_id_for_state = first_question_stage_id
                else: 
                    final_response_for_user = active_scenario.get("stages", {}).get(str(initial_stage_id_from_scenario), {}).get("prompt", "")
                    current_stage_id_for_state = str(initial_stage_id_from_scenario)
            else: 
                final_response_for_user = active_scenario.get("stages", {}).get(str(initial_stage_id_from_scenario), {}).get("prompt", "")
                current_stage_id_for_state = str(initial_stage_id_from_scenario)

        else: # 상품 전환 시
            final_response_for_user = active_scenario.get("stages", {}).get(str(initial_stage_id_from_scenario), {}).get("prompt", "")
            current_stage_id_for_state = str(initial_stage_id_from_scenario)

        if not final_response_for_user:
            final_response_for_user = f"{active_scenario.get('scenario_name', new_product_type + ' 상품')} 상담을 시작하겠습니다. 무엇을 도와드릴까요?"
            current_stage_id_for_state = str(initial_stage_id_from_scenario)
            
        print(f"상품 유형 '{new_product_type}'으로 설정됨. 시작 단계: '{current_stage_id_for_state}', 안내: '{final_response_for_user[:70]}...'")
        
        updated_messages = list(state.get("messages", []))
        if not updated_messages or not (isinstance(updated_messages[-1], AIMessage) and updated_messages[-1].content == final_response_for_user):
            updated_messages.append(AIMessage(content=final_response_for_user))

        return {
            **state,
            "current_product_type": new_product_type,
            "active_scenario_data": active_scenario,
            "active_scenario_name": active_scenario.get("scenario_name"),
            "current_scenario_stage_id": current_stage_id_for_state,
            "collected_product_info": {}, # 상품 유형 변경 시 정보 초기화
            "final_response_text_for_tts": final_response_for_user,
            "messages": updated_messages,
            "is_final_turn_response": True 
        }
    else:
        error_msg = f"요청하신 상품 유형('{new_product_type}')을 처리할 수 없습니다." #
        print(error_msg) #
        current_messages = list(state.get("messages", []))
        if not current_messages or not (isinstance(current_messages[-1], AIMessage) and current_messages[-1].content == error_msg):
            current_messages.append(AIMessage(content=error_msg))
        return {
            **state, 
            "error_message": error_msg,  #
            "final_response_text_for_tts": error_msg,  #
            "messages": current_messages, #
            "is_final_turn_response": True, #
            "current_product_type": state.get("current_product_type") # Revert to previous product type or None
        }


async def prepare_fallback_response_node(state: AgentState) -> AgentState:
    print("--- 노드: 폴백 응답 준비 ---") #
    active_scenario = get_active_scenario_data(state) #
    default_fallback = "죄송합니다, 잘 이해하지 못했습니다. 다시 말씀해주시겠어요?" #
    response_text = state.get("error_message") or (active_scenario.get("fallback_message") if active_scenario else default_fallback) #
    
    updated_messages = list(state.get("messages", [])) #
    if not updated_messages or not (isinstance(updated_messages[-1], AIMessage) and updated_messages[-1].content == response_text): #
        updated_messages.append(AIMessage(content=response_text)) #
    
    next_stage_after_fallback = state.get("current_scenario_stage_id") #
    return {**state, "final_response_text_for_tts": response_text, "messages": updated_messages, "is_final_turn_response": True, "current_scenario_stage_id": next_stage_after_fallback} #

async def prepare_end_conversation_node(state: AgentState) -> AgentState:
    print("--- 노드: 대화 종료 메시지 준비 ---") #
    active_scenario = get_active_scenario_data(state) #
    default_end_msg = "상담을 종료합니다. 이용해주셔서 감사합니다." #
    response_text = (active_scenario.get("end_conversation_message") if active_scenario else default_end_msg) or default_end_msg #
    
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=response_text)] #
    return {**state, "final_response_text_for_tts": response_text, "messages": updated_messages, "is_final_turn_response": True, "current_scenario_stage_id": "END_SCENARIO_ABORT"} #

async def handle_error_node(state: AgentState) -> AgentState:
    print("--- 노드: 에러 핸들링 (최종) ---") #
    error_msg_for_user = state.get("error_message", "알 수 없는 오류가 발생했습니다. 죄송합니다.") #
    updated_messages = list(state.get("messages", [])) #
    if not updated_messages or not (isinstance(updated_messages[-1], AIMessage) and updated_messages[-1].content == error_msg_for_user): #
        updated_messages.append(AIMessage(content=error_msg_for_user)) #
    
    return {**state, "final_response_text_for_tts": error_msg_for_user, "is_final_turn_response": True, "messages": updated_messages} #

# --- 조건부 엣지 로직 ---
def route_from_entry(state: AgentState) -> str:
    if state.get("is_final_turn_response"): return END #
    return "main_agent_router_node"  #

def route_from_main_agent_router(state: AgentState) -> str:
    decision = state.get("main_agent_routing_decision")
    print(f"Main Agent 라우팅 결정: {decision}")
    if state.get("is_final_turn_response"): return END

    if decision == "set_product_type_didimdol" or \
       decision == "set_product_type_jeonse" or \
       decision == "set_product_type_deposit_account": # 신규 추가
        return "set_product_type_node"
    if decision == "select_product_type" or decision == "answer_directly_chit_chat": #
        return "prepare_direct_response_node" #
    if decision == "invoke_scenario_agent": #
        # 상품 유형이 설정되어 있는지 확인
        if not state.get("current_product_type"):
            print("경고: invoke_scenario_agent 요청되었으나 current_product_type 미설정. select_product_type으로 재라우팅.")
            state["main_agent_direct_response"] = "먼저 어떤 상품에 대해 상담하고 싶으신지 알려주시겠어요? (디딤돌 대출, 전세자금 대출 등)"
            return "prepare_direct_response_node" # 사용자에게 다시 선택 요청
        return "call_scenario_agent_node" #
    if decision == "process_next_scenario_step": #
        if not state.get("current_product_type"):
            print("경고: process_next_scenario_step 요청되었으나 current_product_type 미설정. select_product_type으로 재라우팅.")
            state["main_agent_direct_response"] = "어떤 상품의 다음 단계로 진행할까요? 먼저 상품을 선택해주세요."
            return "prepare_direct_response_node"
        return "main_agent_scenario_processing_node" #
    if decision == "invoke_qa_agent": #
        return "call_qa_agent_node"  #
    if decision == "end_conversation": #
        return "prepare_end_conversation_node" #
    
    # qa_error_no_kb는 call_qa_agent_node에서 발생하지 않고, run_agent_streaming에서 처리됨.
    # 따라서 여기서 별도 라우팅 불필요. invoke_qa_agent 결과는 END로 감.
    return "prepare_fallback_response_node" #

def route_from_scenario_agent_call(state: AgentState) -> str:
    scenario_output = state.get("scenario_agent_output") #
    if scenario_output and scenario_output.get("intent", "").startswith("error_"): #
        err_msg = f"답변 분석 중 오류: {scenario_output.get('intent')}" #
        state["error_message"] = err_msg #
        state["final_response_text_for_tts"] = err_msg #
        return "handle_error_node" #
    return "main_agent_scenario_processing_node" #

def route_from_qa_agent_call(state: AgentState) -> str:
    # QA는 run_agent_streaming에서 직접 스트리밍 처리 후 그래프 종료
    return END #

# --- 그래프 빌드 ---
workflow = StateGraph(AgentState) #
nodes_to_add = [
    ("entry_point_node", entry_point_node), #
    ("main_agent_router_node", main_agent_router_node), #
    ("set_product_type_node", set_product_type_node), #
    ("call_scenario_agent_node", call_scenario_agent_node), #
    ("call_qa_agent_node", call_qa_agent_node),  #
    ("main_agent_scenario_processing_node", main_agent_scenario_processing_node), #
    ("prepare_direct_response_node", prepare_direct_response_node), #
    ("prepare_fallback_response_node", prepare_fallback_response_node), #
    ("prepare_end_conversation_node", prepare_end_conversation_node), #
    ("handle_error_node", handle_error_node) #
]
for name, node_func in nodes_to_add: workflow.add_node(name, node_func) #

workflow.set_entry_point("entry_point_node") #

workflow.add_conditional_edges("entry_point_node", route_from_entry) #
workflow.add_conditional_edges("main_agent_router_node", route_from_main_agent_router) #
workflow.add_conditional_edges("call_scenario_agent_node", route_from_scenario_agent_call) #
workflow.add_conditional_edges("call_qa_agent_node", route_from_qa_agent_call) #

workflow.add_edge("set_product_type_node", END) #
workflow.add_edge("main_agent_scenario_processing_node", END) #
workflow.add_edge("prepare_direct_response_node", END) #
workflow.add_edge("prepare_fallback_response_node", END) #
workflow.add_edge("prepare_end_conversation_node", END) #
workflow.add_edge("handle_error_node", END) #

app_graph = workflow.compile() #
print("--- LangGraph 컴파일 완료 (다중 업무 지원) ---") #


async def run_agent_streaming(
    user_input_text: Optional[str] = None,
    user_input_audio_b64: Optional[str] = None,
    session_id: Optional[str] = "default_session",
    current_state_dict: Optional[Dict[str, Any]] = None
) -> AsyncGenerator[Union[Dict[str, Any], str], None]:
    
    if not OPENAI_API_KEY or not main_llm or not streaming_llm: #
        error_msg = "LLM 서비스가 초기화되지 않았습니다. API 키 설정을 확인하세요." #
        yield {"type": "error", "session_id": session_id, "message": error_msg} #
        yield {"type": "final_state", "session_id": session_id, "data": {"error_message": error_msg, "is_final_turn_response": True, "messages": [AIMessage(content=error_msg)]}} #
        return

    if not ALL_SCENARIOS_DATA: #
        try: load_all_scenarios_sync() #
        except Exception as e: #
            yield {"type": "error", "session_id": session_id, "message": f"상담 서비스 초기화 실패 (시나리오 로드): {e}"} #
            return
    
    initial_messages: List[BaseMessage] = [] #
    current_product_type_from_session: Optional[Literal["didimdol", "jeonse"]] = None #
    current_stage_id_from_session: Optional[str] = None #
    collected_info_from_session: Dict[str, Any] = {} #

    if current_state_dict: #
        initial_messages = list(current_state_dict.get("messages", [])) #
        current_product_type_from_session = current_state_dict.get("current_product_type") #
        current_stage_id_from_session = current_state_dict.get("current_scenario_stage_id") #
        collected_info_from_session = current_state_dict.get("collected_product_info", {}) #

    initial_input_for_graph: AgentState = cast(AgentState, { #
        "session_id": session_id or "default_session", #
        "user_input_text": user_input_text, #
        "user_input_audio_b64": user_input_audio_b64, #
        "stt_result": user_input_text, #
        "messages": initial_messages, #
        
        "current_product_type": current_product_type_from_session, #
        "current_scenario_stage_id": current_stage_id_from_session, #
        "collected_product_info": collected_info_from_session, #
        "available_product_types": ["didimdol", "jeonse", "deposit_account"], # 


        "active_scenario_data": None, #
        "active_knowledge_base_content": None, #
        "active_scenario_name": None, #

        "main_agent_routing_decision": None, "main_agent_direct_response": None, #
        "scenario_agent_output": None,  #
        "final_response_text_for_tts": None, "is_final_turn_response": False, "error_message": None, #
    })
    
    print(f"\n--- [{session_id}] Agent Turn 시작 ---") #
    print(f"초기 입력 상태 (요약): product_type='{current_product_type_from_session}', stage='{current_stage_id_from_session}', text='{user_input_text}'") #

    final_graph_output_state: Optional[AgentState] = None #
    full_response_text_streamed = "" #

    try:
        graph_output_state: AgentState = await app_graph.ainvoke(initial_input_for_graph) #
        final_graph_output_state = graph_output_state #

        print(f"LangGraph 실행 완료. 라우팅: '{graph_output_state.get('main_agent_routing_decision')}', 다음 상품유형: '{graph_output_state.get('current_product_type')}', 다음 단계 ID: '{graph_output_state.get('current_scenario_stage_id')}'") #

        if graph_output_state.get("main_agent_routing_decision") == "invoke_qa_agent": #
            user_question_for_qa = graph_output_state.get("stt_result", "") #
            
            qa_context_product_type = graph_output_state.get("current_product_type") #
            qa_scenario_name = graph_output_state.get("active_scenario_name", "일반 금융 상담") #
            
            kb_content_for_qa: Optional[str] = None #
            if qa_context_product_type and qa_context_product_type in KNOWLEDGE_BASE_FILES: #
                kb_content_for_qa = await load_knowledge_base_content_async(qa_context_product_type) #

            if user_question_for_qa: #
                print(f"QA 스트리밍 시작 (세션: {session_id}, 컨텍스트: '{qa_scenario_name}', 질문: '{user_question_for_qa[:50]}...')") #
                yield {"type": "stream_start", "stream_type": "qa_answer"} #
                
                async for chunk in invoke_qa_agent_streaming_logic(user_question_for_qa, qa_scenario_name, kb_content_for_qa): #
                    yield chunk  #
                    full_response_text_streamed += chunk #
                
                updated_messages_after_qa = list(graph_output_state.get("messages", [])) #
                if not updated_messages_after_qa or not (isinstance(updated_messages_after_qa[-1], AIMessage) and updated_messages_after_qa[-1].content == full_response_text_streamed): #
                    updated_messages_after_qa.append(AIMessage(content=full_response_text_streamed)) #
                
                next_stage_after_qa = "qa_listen" #
                if qa_context_product_type: #
                    active_scenario = ALL_SCENARIOS_DATA.get(qa_context_product_type) #
                    if active_scenario: #
                        specific_qa_listen_stage = f"qa_listen_{qa_context_product_type}" #
                        if specific_qa_listen_stage in active_scenario.get("stages", {}): #
                            next_stage_after_qa = specific_qa_listen_stage #
                        else: 
                             current_stage_id = graph_output_state.get("current_scenario_stage_id") #
                             if current_stage_id and str(current_stage_id) in active_scenario.get("stages", {}): #
                                 next_stage_after_qa = active_scenario["stages"][str(current_stage_id)].get("default_next_stage_id", "qa_listen") #

                final_graph_output_state = {
                    **graph_output_state, 
                    "final_response_text_for_tts": full_response_text_streamed, #
                    "messages": updated_messages_after_qa,  #
                    "is_final_turn_response": True, #
                    "current_scenario_stage_id": next_stage_after_qa #
                }
            else: 
                pass

        elif graph_output_state.get("final_response_text_for_tts"): #
            text_to_stream = graph_output_state["final_response_text_for_tts"] #
            yield {"type": "stream_start", "stream_type": "general_response"} #
            chunk_size = 20  #
            for i in range(0, len(text_to_stream), chunk_size): #
                chunk = text_to_stream[i:i+chunk_size] #
                yield chunk #
                await asyncio.sleep(0.02)  #
                full_response_text_streamed += chunk #
        else:
            error_message_fallback = graph_output_state.get("error_message", "응답을 생성하지 못했습니다.") #
            yield {"type": "stream_start", "stream_type": "critical_error"} #
            for char_chunk in error_message_fallback: yield char_chunk; await asyncio.sleep(0.01) #
            full_response_text_streamed = error_message_fallback #
            final_graph_output_state = {**graph_output_state, "final_response_text_for_tts": full_response_text_streamed, "error_message": error_message_fallback, "is_final_turn_response": True} #

        yield {"type": "stream_end", "full_text": full_response_text_streamed} #

    except Exception as e:
        print(f"CRITICAL error in run_agent_streaming for session {session_id}: {e}") #
        import traceback; traceback.print_exc() #
        error_response = f"죄송합니다, 에이전트 처리 중 심각한 시스템 오류가 발생했습니다." #
        yield {"type": "stream_start", "stream_type": "critical_error"} #
        for char_chunk in error_response: yield char_chunk; await asyncio.sleep(0.01) #
        yield {"type": "stream_end", "full_text": error_response} #
        
        final_graph_output_state = cast(AgentState, initial_input_for_graph.copy()) #
        final_graph_output_state["error_message"] = error_response #
        final_graph_output_state["final_response_text_for_tts"] = error_response #
        final_graph_output_state["is_final_turn_response"] = True #
        current_messages_on_error = list(initial_input_for_graph.get("messages", [])) #
        if not current_messages_on_error or not (isinstance(current_messages_on_error[-1], AIMessage) and current_messages_on_error[-1].content == error_response): #
            current_messages_on_error.append(AIMessage(content=error_response)) #
        final_graph_output_state["messages"] = current_messages_on_error #

    finally:
        if final_graph_output_state: #
            yield {"type": "final_state", "session_id": session_id, "data": final_graph_output_state} #
        else: #
             yield {"type": "final_state", "session_id": session_id, "data": {"error_message": "Agent 실행 중 심각한 오류로 최종 상태 기록 불가", "is_final_turn_response": True}} #

        print(f"--- [{session_id}] Agent Turn 종료 (최종 AI 응답 텍스트 길이: {len(full_response_text_streamed)}) ---") #