# backend/app/graph/agent.py
import json
import yaml
import asyncio
from pathlib import Path
from typing import Dict, Optional, Sequence, Literal, Any, List, Union, cast, AsyncGenerator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, AIMessageChunk
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langchain_core.output_parsers import PydanticOutputParser # PydanticOutputParser 직접 사용
from pydantic import BaseModel, Field as PydanticField

from .state import AgentState, ScenarioAgentOutput # QAAgentOutput은 스트리밍으로 대체
from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME
from ..services.google_services import GOOGLE_SERVICES_AVAILABLE # STT/TTS 서비스 사용 가능 여부 확인용
# STT/TTS 직접 호출은 service 모듈로 완전 위임

# --- Pydantic 모델 정의 (기존 파일 참고) ---
class NextStageDecisionModel(BaseModel):
    chosen_next_stage_id: str = PydanticField(description="LLM이 결정한 다음 시나리오 단계 ID")
next_stage_decision_parser = PydanticOutputParser(pydantic_object=NextStageDecisionModel)

class ScenarioOutputModel(BaseModel):
    intent: str = PydanticField(description="사용자 발화의 주요 의도 (예: '정보제공_연소득', '확인_긍정')")
    entities: Dict[str, Any] = PydanticField(default_factory=dict, description="추출된 주요 개체 (예: {'annual_income': 5000})")
    is_scenario_related: bool = PydanticField(description="현재 시나리오와 관련된 발화인지 여부")
    user_sentiment: Optional[Literal['positive', 'negative', 'neutral']] = PydanticField(default='neutral', description="사용자 발화의 감정 (옵션)")
scenario_output_parser = PydanticOutputParser(pydantic_object=ScenarioOutputModel)


# --- 경로 및 설정 (기존 파일 참고) ---
APP_DIR = Path(__file__).resolve().parent.parent # 경로 수정
DATA_DIR = APP_DIR / "data"
CONFIG_DIR = APP_DIR / "config"
SCENARIO_FILE_PATH = DATA_DIR / "loan_scenario.json"
QA_KNOWLEDGE_BASE_PATH = DATA_DIR / "didimdol.md"

PROMPT_FILES = {
    'main_agent': CONFIG_DIR / "main_agent_prompts.yaml",
    'scenario_agent': CONFIG_DIR / "scenario_agent_prompts.yaml",
    'qa_agent': CONFIG_DIR / "qa_agent_prompts.yaml",
}

# --- LLM 초기화 (기존 파일 참고) ---
if not OPENAI_API_KEY:
    print("CRITICAL: OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
    # 애플리케이션 실행 중단 또는 기본 동작을 정의할 수 있으나, 여기서는 경고만 출력
    # raise ValueError("OPENAI_API_KEY is not set.")

main_llm = ChatOpenAI(
    model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.1,
    model_kwargs={"response_format": {"type": "json_object"}}
) if OPENAI_API_KEY else None

streaming_llm = ChatOpenAI(
    model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.3, streaming=True
) if OPENAI_API_KEY else None


# --- 프롬프트 및 시나리오 로드 함수 (기존과 동일) ---
ALL_PROMPTS: Dict[str, Dict[str, str]] = {}
LOAN_SCENARIO_DATA: Dict = {}
QA_KNOWLEDGE_BASE_CONTENT: Optional[str] = None

def load_all_prompts_sync() -> Dict[str, Dict[str, str]]:
    # (기존 load_all_prompts 로직)
    # 제공된 코드의 load_all_prompts() 함수 내용 사용
    # ... (생략, 기존 파일 내용 복사)
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
        return loaded_prompts
    except FileNotFoundError as e:
        raise FileNotFoundError(f"프롬프트 파일을 찾을 수 없습니다: {e.filename}")
    except yaml.YAMLError as e:
        raise ValueError(f"프롬프트 파일의 YAML 형식이 올바르지 않습니다: {e}")
    except Exception as e:
        raise Exception(f"프롬프트 파일 로드 중 오류 발생: {e}")


def load_loan_scenario_sync() -> Dict:
    # (기존 load_loan_scenario 로직)
    # 제공된 코드의 load_loan_scenario() 함수 내용 사용
    # ... (생략, 기존 파일 내용 복사)
    global LOAN_SCENARIO_DATA
    try:
        with open(SCENARIO_FILE_PATH, 'r', encoding='utf-8') as f:
            scenario = json.load(f)
        if not scenario: raise ValueError("시나리오 파일이 비어있습니다.")
        LOAN_SCENARIO_DATA = scenario
        print("--- 대출 시나리오 데이터 로드 완료 ---")
        return scenario
    except FileNotFoundError: raise FileNotFoundError(f"시나리오 파일을 찾을 수 없습니다: {SCENARIO_FILE_PATH}")
    except json.JSONDecodeError: raise ValueError(f"시나리오 파일의 JSON 형식이 올바르지 않습니다: {SCENARIO_FILE_PATH}")
    except Exception as e: raise Exception(f"시나리오 파일 로드 중 오류 발생: {e}")

async def load_knowledge_base_content_async() -> Optional[str]:
    # (기존 load_knowledge_base_content_async 로직)
    # 제공된 코드의 load_knowledge_base_content_async() 함수 내용 사용
    # ... (생략, 기존 파일 내용 복사)
    global QA_KNOWLEDGE_BASE_CONTENT
    if QA_KNOWLEDGE_BASE_CONTENT is None:
        print("--- QA Agent: 지식베이스 (didimdol.md) 로딩 중... ---")
        try:
            if not QA_KNOWLEDGE_BASE_PATH.exists():
                print(f"경고: 지식베이스 파일을 찾을 수 없습니다: {QA_KNOWLEDGE_BASE_PATH}"); QA_KNOWLEDGE_BASE_CONTENT = "ERROR_FILE_NOT_FOUND"; return None
            with open(QA_KNOWLEDGE_BASE_PATH, 'r', encoding='utf-8') as f: content = f.read()
            if not content.strip():
                print(f"경고: 지식베이스 파일이 비어있습니다: {QA_KNOWLEDGE_BASE_PATH}"); QA_KNOWLEDGE_BASE_CONTENT = "EMPTY_CONTENT"; return None
            QA_KNOWLEDGE_BASE_CONTENT = content
            print(f"--- QA Agent: 지식베이스 (didimdol.md) 로딩 완료 ({len(content)} 자) ---")
        except Exception as e: print(f"QA 지식베이스 로딩 실패: {e}"); QA_KNOWLEDGE_BASE_CONTENT = "ERROR_LOADING_FAILED"; return None
    if QA_KNOWLEDGE_BASE_CONTENT in ["ERROR_FILE_NOT_FOUND", "EMPTY_CONTENT", "ERROR_LOADING_FAILED"]: return None
    return QA_KNOWLEDGE_BASE_CONTENT


# 애플리케이션 시작 시 동기적으로 로드
load_all_prompts_sync()
load_loan_scenario_sync()
# QA 지식베이스는 첫 호출 시 비동기적으로 로드되도록 유지 (load_knowledge_base_content_async)


def format_messages_for_prompt(messages: Sequence[BaseMessage], max_history: int = 3) -> str:
    # (기존 함수와 동일)
    history_str = []
    # 시스템 메시지를 제외하고 최근 max_history 개의 메시지만 사용 (Human, AI 순서 유지)
    # 현재 사용자 입력은 제외하고 이전 턴까지만 포함하도록 수정 필요 (main_agent_router_node에서 호출 시 주의)
    relevant_messages = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))][-(max_history * 2):] # 대화턴 기준
    
    for msg in relevant_messages:
        role = "사용자" if isinstance(msg, HumanMessage) else "상담원"
        history_str.append(f"{role}: {msg.content}")
    return "\n".join(history_str) if history_str else "이전 대화 없음."

def format_transitions_for_prompt(transitions: List[Dict[str, Any]], current_stage_prompt: str) -> str:
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

# --- Specialist Agent 로직 (기존 파일 참고, 에러 처리 강화) ---
async def invoke_scenario_agent_logic(user_input: str, current_stage_prompt: str, expected_info_key: Optional[str], messages_history: Sequence[BaseMessage], scenario_name: str) -> ScenarioAgentOutput:
    # ... (제공된 invoke_scenario_agent_logic 함수 내용, main_llm null 체크 추가)
    if not main_llm:
        return cast(ScenarioAgentOutput, {"intent": "error_llm_not_initialized", "entities": {}, "is_scenario_related": False})
    # (이하 기존 코드)
    print(f"--- Scenario Agent 호출 (입력: '{user_input}') ---")
    prompt_template = ALL_PROMPTS.get('scenario_agent', {}).get('nlu_extraction', '')
    if not prompt_template:
        return cast(ScenarioAgentOutput, {"intent": "error_prompt_not_found", "entities": {}, "is_scenario_related": False, "user_sentiment": "neutral"})

    formatted_history = format_messages_for_prompt(messages_history) # 이전 대화만 전달
    try:
        format_instructions = scenario_output_parser.get_format_instructions()
        formatted_prompt = prompt_template.format(
            scenario_name=scenario_name, current_stage_prompt=current_stage_prompt,
            expected_info_key=expected_info_key or "특정 정보 없음",
            formatted_messages_history=formatted_history, user_input=user_input,
            format_instructions=format_instructions
        )
        # print(f"Scenario Agent 프롬프트:\n{formatted_prompt}") # 디버깅용
        response = await main_llm.ainvoke([HumanMessage(content=formatted_prompt)])
        raw_content = response.content.strip()
        # print(f"Scenario Agent 원본 LLM 응답:\n{raw_content}") # 디버깅용
        if raw_content.startswith("```json"): raw_content = raw_content.replace("```json", "").replace("```", "").strip()
        
        parsed_output_dict = scenario_output_parser.parse(raw_content).model_dump()
        print(f"Scenario Agent 결과: {parsed_output_dict}")
        return cast(ScenarioAgentOutput, parsed_output_dict)
    except Exception as e:
        print(f"Scenario Agent 처리 오류: {e}. LLM 응답: {getattr(e, 'llm_output', getattr(response if 'response' in locals() else None, 'content', 'N/A'))}")
        # import traceback; traceback.print_exc() # 상세 디버깅
        return cast(ScenarioAgentOutput, {"intent": "error_parsing_scenario_output", "entities": {}, "is_scenario_related": False, "user_sentiment": "neutral"})


async def invoke_qa_agent_streaming_logic(user_question: str, scenario_name: str) -> AsyncGenerator[str, None]:
    # ... (제공된 invoke_qa_agent_streaming_logic 함수 내용, streaming_llm null 체크 추가)
    if not streaming_llm:
        yield "죄송합니다, 답변 생성 서비스가 현재 사용할 수 없습니다. (LLM 초기화 오류)"
        return
    # (이하 기존 코드)
    print(f"--- QA Agent 스트리밍 호출 (질문: '{user_question}') ---")
    try:
        knowledge_base_text = await load_knowledge_base_content_async()
        if knowledge_base_text is None or "ERROR" in QA_KNOWLEDGE_BASE_CONTENT : # type: ignore
            error_map = {
                "ERROR_FILE_NOT_FOUND": f"죄송합니다. 상담에 필요한 정보 파일({QA_KNOWLEDGE_BASE_PATH.name})을 찾을 수 없습니다.",
                "EMPTY_CONTENT": f"죄송합니다. 상담에 필요한 정보 파일({QA_KNOWLEDGE_BASE_PATH.name})의 내용이 비어있습니다.",
                "ERROR_LOADING_FAILED": "죄송합니다. 현재 대출 관련 정보를 조회할 수 없습니다 (지식베이스 문제)."
            }
            yield error_map.get(QA_KNOWLEDGE_BASE_CONTENT, "지식베이스 접근 중 알 수 없는 오류 발생.") # type: ignore
            return

        prompt_template = ALL_PROMPTS.get('qa_agent', {}).get('rag_answer_generation', '')
        if not prompt_template:
            yield "죄송합니다, 답변 생성에 필요한 설정(프롬프트)을 찾을 수 없습니다."
            return

        formatted_prompt = prompt_template.format(
            scenario_name=scenario_name, context_for_llm=knowledge_base_text, user_question=user_question
        )
        # print(f"\n=== QA Agent 스트리밍 프롬프트 (일부 컨텍스트) ===\n{formatted_prompt[:500]}...\n=============================\n") # 디버깅용
        
        async for chunk in streaming_llm.astream([HumanMessage(content=formatted_prompt)]):
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                yield str(chunk.content)
            elif isinstance(chunk, str) and chunk: # 이전 버전 호환
                yield chunk
    except Exception as e:
        print(f"QA Agent 스트리밍 처리 오류: {e}")
        yield f"질문 답변 중 시스템 오류가 발생했습니다: {e}"


# --- LangGraph 노드 함수 정의 (기존 파일 참고, TTS 로직 제거 및 에러 처리 강화) ---
async def entry_point_node(state: AgentState) -> AgentState:
    print("--- 노드: Entry Point ---")
    # loan_scenario_data는 전역에서 로드된 LOAN_SCENARIO_DATA 사용
    if not LOAN_SCENARIO_DATA:
        # 이 경우는 애플리케이션 시작 시 로드 실패. 심각한 오류로 처리.
        error_msg = "상담 서비스 초기화 실패 (시나리오 데이터 로드 불가)."
        print(f"CRITICAL: 시나리오 데이터가 로드되지 않았습니다 (entry_point_node).")
        return {**state, "error_message": error_msg, "final_response_text_for_tts": error_msg, "is_final_turn_response": True}
    state["loan_scenario_data"] = LOAN_SCENARIO_DATA

    # 턴 시작 시 초기화할 필드들
    turn_specific_defaults: Dict[str, Any] = {
        "stt_result": None, "main_agent_routing_decision": None, "main_agent_direct_response": None,
        "scenario_agent_output": None, # qa_agent_output은 스트리밍으로 처리되므로 상태에 직접 저장하지 않음
        "final_response_text_for_tts": None, "is_final_turn_response": False, "error_message": None,
    }
    # messages는 이전 상태에서 가져오되, 없으면 시스템 프롬프트로 초기화
    initial_messages: List[BaseMessage] = list(state.get("messages", []))
    if not initial_messages and LOAN_SCENARIO_DATA.get("system_prompt"):
        initial_messages.append(SystemMessage(content=LOAN_SCENARIO_DATA["system_prompt"]))
    
    updated_state = {**state, **turn_specific_defaults, "messages": initial_messages}

    if updated_state.get("user_input_audio_b64"):
        if not GOOGLE_SERVICES_AVAILABLE:
            print("STT 서비스 사용 불가. 텍스트 입력으로 처리합니다.")
            updated_state["user_input_text"] = "(음성 입력 시도 - STT 서비스 비활성)" # 또는 빈 문자열
            updated_state["user_input_audio_b64"] = None # 오디오 처리 안 함
            # 바로 main_agent_router_node로 가도록
        else:
            print("입력 유형: 음성 -> STT는 chat.py에서 이미 처리됨. stt_result 사용.")
            # chat.py에서 STT 최종 결과를 user_input_text로 전달해 줄 것으로 가정.
            # 또는, run_agent_streaming 호출 시 stt_result가 채워져 들어옴.
            # 여기서는 stt_result가 있으면 HumanMessage 추가 로직만 수행
            pass # STT 결과는 이미 state['stt_result']에 있을 것으로 가정

    # user_input_text가 있으면 messages에 추가 (stt_result 또는 직접 텍스트 입력)
    user_text_for_turn = updated_state.get("stt_result") or updated_state.get("user_input_text")
    
    if user_text_for_turn:
        current_messages = list(updated_state.get("messages", []))
        # 중복 메시지 추가 방지
        if not current_messages or not (isinstance(current_messages[-1], HumanMessage) and current_messages[-1].content == user_text_for_turn):
            current_messages.append(HumanMessage(content=user_text_for_turn))
        updated_state["messages"] = current_messages
        updated_state["stt_result"] = user_text_for_turn # 일관성을 위해 stt_result에도 최종 텍스트 입력
    elif not updated_state.get("user_input_audio_b64"): # 텍스트도, 오디오도 없는 경우
        err_msg = "사용자 입력이 없습니다."
        updated_state.update({"error_message": err_msg, "final_response_text_for_tts": err_msg, "is_final_turn_response": True})

    return cast(AgentState, updated_state)

async def main_agent_router_node(state: AgentState) -> AgentState:
    print("--- 노드: Main Agent Router ---")
    # (기존 main_agent_router_node 로직, main_llm null 체크 및 프롬프트 로드 확인 추가)
    if not main_llm:
        return {**state, "error_message": "라우터 서비스 사용 불가 (LLM 미초기화)", "final_response_text_for_tts": "시스템 설정 오류입니다.", "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True}

    user_input = state.get("stt_result", "") # stt_result에 최종 사용자 발화가 있다고 가정
    messages_history = state.get("messages", [])
    
    if not user_input and user_input != "": # 입력이 None이거나 빈 문자열인 경우
        # entry_point_node에서 이 경우 is_final_turn_response=True로 설정되어 여기까지 오지 않아야 함.
        # 만약을 위한 방어 코드
        print("Main Agent Router: 사용자 입력 없음. 폴백 처리.")
        return {**state, "error_message": "입력 내용이 없어 처리할 수 없습니다.", "final_response_text_for_tts": "다시 말씀해주시겠어요?", "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True}

    # messages_history에는 현재 사용자 입력이 이미 포함되어 있음. 라우터 프롬프트에는 이전 대화만 전달.
    # HumanMessage가 마지막에 두 번 들어가지 않도록 주의.
    # format_messages_for_prompt는 마지막 HumanMessage를 제외하고 전달해야 함.
    
    # messages_history가 비어있거나, 마지막이 HumanMessage가 아니면 비정상.
    if not messages_history or not isinstance(messages_history[-1], HumanMessage):
        print(f"경고: Main Agent Router - messages_history의 마지막이 HumanMessage가 아님: {messages_history[-1] if messages_history else '비어있음'}")
        # 비상시 현재 입력을 HumanMessage로 간주
        history_for_prompt = list(messages_history)
    else:
        history_for_prompt = list(messages_history[:-1]) # 마지막 사용자 입력 제외

    current_stage_id = state.get("current_scenario_stage_id", LOAN_SCENARIO_DATA.get("initial_stage_id", "greeting"))
    current_stage_info = LOAN_SCENARIO_DATA.get("stages", {}).get(current_stage_id, {})
    prompt_template = ALL_PROMPTS.get('main_agent', {}).get('router_prompt', '')

    if not prompt_template:
         return {**state, "error_message": "라우터 프롬프트 로드 실패", "final_response_text_for_tts": "시스템 설정 오류로 요청을 이해할 수 없습니다.", "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True}

    formatted_history_str = format_messages_for_prompt(history_for_prompt) 
    
    try:
        main_agent_prompt_filled = prompt_template.format(
            user_input=user_input, formatted_messages_history=formatted_history_str,
            current_scenario_stage_id=current_stage_id,
            current_stage_prompt=current_stage_info.get("prompt", "안내 없음"),
            collected_loan_info=str(state.get("collected_loan_info", {})),
            scenario_name=LOAN_SCENARIO_DATA.get("scenario_name", "대출 상담"),
            expected_info_key=current_stage_info.get("expected_info_key", "정보 없음"),
            # qa_keywords_example는 프롬프트에서 제거했으므로 주석 처리
        )
        # print(f"Main Agent Router 프롬프트:\n{main_agent_prompt_filled}") # 디버깅용
        response = await main_llm.ainvoke([HumanMessage(content=main_agent_prompt_filled)])
        raw_response_content = response.content.strip()
        # print(f"Main Agent Router 원본 LLM 응답:\n{raw_response_content}") # 디버깅용
        if raw_response_content.startswith("```json"): raw_response_content = raw_response_content.replace("```json", "").replace("```", "").strip()
        
        decision_data = json.loads(raw_response_content)
        routing_decision = decision_data.get("action")
        direct_response = decision_data.get("direct_response") # 칫챗용
        extracted_value_for_direct_processing = decision_data.get("extracted_value") # process_next_scenario_step용
        
        print(f"Main Agent 결정: {routing_decision}, 직접 답변: {direct_response}, 추출값: {extracted_value_for_direct_processing}")
        
        # 'process_next_scenario_step'일 경우, ScenarioAgentOutput과 유사한 구조로 만들어 다음 노드에서 일관되게 처리
        scenario_output_for_direct_step = None
        if routing_decision == "process_next_scenario_step" and extracted_value_for_direct_processing is not None:
            key_to_collect = current_stage_info.get("expected_info_key")
            entities_direct = {key_to_collect: extracted_value_for_direct_processing} if key_to_collect else {}
            scenario_output_for_direct_step = cast(ScenarioAgentOutput, {
                "intent": f"direct_input_{str(extracted_value_for_direct_processing)[:20].replace(' ','_').lower()}", 
                "entities": entities_direct, 
                "is_scenario_related": True
            })
            # 이 경우, scenario_agent_output을 채워 main_agent_scenario_processing_node가 처리하도록 함

        return {
            **state, 
            "main_agent_routing_decision": routing_decision, 
            "main_agent_direct_response": direct_response, # 칫챗 응답
            "scenario_agent_output": scenario_output_for_direct_step # process_next_scenario_step일 때만 채워짐
        }
    except json.JSONDecodeError as je:
        err_msg = "요청을 이해하는 중 내부 오류가 발생했습니다 (JSON 파싱). 다시 시도해주세요."
        print(f"Main Agent Router JSON 파싱 오류: {je}. LLM 응답: {getattr(response if 'response' in locals() else None, 'content', 'N/A')}")
        return {**state, "error_message": err_msg, "final_response_text_for_tts":err_msg, "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True}
    except Exception as e:
        err_msg = "요청 처리 중 시스템 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        print(f"Main Agent Router 시스템 오류: {e}"); import traceback; traceback.print_exc()
        return {**state, "error_message": err_msg, "final_response_text_for_tts": err_msg, "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True}

async def call_scenario_agent_node(state: AgentState) -> AgentState:
    print("--- 노드: Scenario Agent 호출 ---")
    user_input = state.get("stt_result", "")
    if not user_input and user_input != "":
        print("Scenario Agent 호출 노드: 사용자 입력 없음. 폴백 처리 필요.")
        return {**state, "scenario_agent_output": cast(ScenarioAgentOutput, {"intent": "no_input", "entities": {}, "is_scenario_related": False})}

    current_stage_id = state.get("current_scenario_stage_id", LOAN_SCENARIO_DATA.get("initial_stage_id", "greeting"))
    current_stage_info = LOAN_SCENARIO_DATA.get("stages", {}).get(current_stage_id, {})
    messages_history = state.get("messages", [])[:-1] # 현재 사용자 입력 제외
    
    output = await invoke_scenario_agent_logic(
        user_input=user_input,
        current_stage_prompt=current_stage_info.get("prompt", ""),
        expected_info_key=current_stage_info.get("expected_info_key"),
        messages_history=messages_history,
        scenario_name=LOAN_SCENARIO_DATA.get("scenario_name", "대출 상담")
    )
    return {**state, "scenario_agent_output": output}

async def call_qa_agent_node(state: AgentState) -> AgentState:
    print("--- 노드: QA Agent 호출 준비 (스트리밍은 run_agent_streaming에서 직접 처리) ---")
    # 이 노드는 실제 로직을 수행하지 않고, 라우팅 결정에 따라 run_agent_streaming에서
    # invoke_qa_agent_streaming_logic를 직접 호출하도록 하는 신호 역할.
    # state에 qa_agent_output을 채우지 않음.
    return state # 상태 변경 없음

async def main_agent_scenario_processing_node(state: AgentState) -> AgentState:
    print("--- 노드: Main Agent 시나리오 처리 (다음 단계 결정 및 응답 생성) ---")
    # (기존 main_agent_scenario_processing_node 로직, main_llm null 체크 추가)
    if not main_llm:
         return {**state, "error_message": "시나리오 처리 서비스 사용 불가 (LLM 미초기화)", "final_response_text_for_tts": "시스템 설정 오류로 다음 안내를 드릴 수 없습니다.", "is_final_turn_response": True}

    user_input = state.get("stt_result", "")
    scenario_output = state.get("scenario_agent_output") # invoke_scenario_agent 또는 process_next_scenario_step 에서 채워짐
    current_stage_id = state.get("current_scenario_stage_id", LOAN_SCENARIO_DATA.get("initial_stage_id", "greeting"))
    stages_data = LOAN_SCENARIO_DATA.get("stages", {})
    current_stage_info = stages_data.get(current_stage_id, {})
    collected_info = state.get("collected_loan_info", {}).copy()

    final_response_text_for_user: str = LOAN_SCENARIO_DATA.get("fallback_message", "죄송합니다, 처리 중 오류가 발생했습니다.")
    determined_next_stage_id: str = current_stage_id 

    # Scenario Agent 결과 또는 Main Agent 직접 처리 결과(scenario_output에 저장됨)를 바탕으로 정보 수집
    if scenario_output and scenario_output.get("is_scenario_related"):
        extracted_entities = scenario_output.get("entities", {})
        for key, value in extracted_entities.items():
            if value is not None: # None이 아닌 값만 수집
                collected_info[key] = value
                print(f"정보 업데이트: {key} = {value}")
        
        # 다음 단계 결정 로직
        prompt_template = ALL_PROMPTS.get('main_agent', {}).get('determine_next_scenario_stage', '')
        if not prompt_template:
            print("오류: 다음 단계 결정 프롬프트를 찾을 수 없습니다. 기본 다음 단계로 진행합니다.")
            determined_next_stage_id = current_stage_info.get("default_next_stage_id", current_stage_id)
            if not determined_next_stage_id and current_stage_id not in ["END_SCENARIO_COMPLETE", "END_SCENARIO_ABORT", "qa_listen"]:
                determined_next_stage_id = "END_SCENARIO_COMPLETE" # 정의된 다음 단계 없으면 완료로 간주
        else:
            # LLM에 다음 단계 결정을 요청
            scenario_agent_intent_str = scenario_output.get("intent", "정보 없음")
            scenario_agent_entities_str = str(scenario_output.get("entities", {}))
            
            current_transitions = current_stage_info.get("transitions", [])
            formatted_transitions_str = format_transitions_for_prompt(current_transitions, current_stage_info.get("prompt",""))

            llm_prompt_for_next_stage = prompt_template.format(
                scenario_name=LOAN_SCENARIO_DATA.get("scenario_name", "대출 상담"),
                current_stage_id=current_stage_id,
                current_stage_prompt=current_stage_info.get("prompt", "안내 없음"),
                user_input=user_input, # 현재 사용자 발화
                scenario_agent_intent=scenario_agent_intent_str,
                scenario_agent_entities=scenario_agent_entities_str,
                collected_loan_info=str(collected_info),
                formatted_transitions=formatted_transitions_str,
                default_next_stage_id=current_stage_info.get("default_next_stage_id", "None")
            )
            # print(f"\n=== 다음 단계 결정 LLM 프롬프트 ===\n{llm_prompt_for_next_stage}\n=============================\n") # 디버깅
            try:
                response = await main_llm.ainvoke([HumanMessage(content=llm_prompt_for_next_stage)])
                raw_content = response.content.strip()
                if raw_content.startswith("```json"): raw_content = raw_content.replace("```json", "").replace("```", "").strip()
                
                decision_data = next_stage_decision_parser.parse(raw_content) 
                determined_next_stage_id = decision_data.chosen_next_stage_id
                print(f"LLM 결정 다음 단계 ID: '{determined_next_stage_id}'")

                if determined_next_stage_id not in stages_data and \
                   determined_next_stage_id not in ["END_SCENARIO_COMPLETE", "END_SCENARIO_ABORT", "qa_listen"]:
                    print(f"경고: LLM이 반환한 다음 단계 ID ('{determined_next_stage_id}')가 유효하지 않습니다. 기본 다음 단계를 사용합니다.")
                    determined_next_stage_id = current_stage_info.get("default_next_stage_id", current_stage_id)
            except Exception as e:
                print(f"다음 단계 결정 LLM 오류: {e}. LLM Raw: {getattr(response if 'response' in locals() else None, 'content', 'N/A')}. 기본 다음 단계 사용.")
                determined_next_stage_id = current_stage_info.get("default_next_stage_id", current_stage_id)
                if not determined_next_stage_id and current_stage_id not in ["END_SCENARIO_COMPLETE", "END_SCENARIO_ABORT", "qa_listen"]:
                     determined_next_stage_id = "END_SCENARIO_COMPLETE"
    else: # 시나리오 관련 발화가 아님 (Scenario Agent가 그렇게 판단했거나, 호출되지 않음)
        print(f"시나리오 처리 노드: 시나리오 관련 발화 아님. 현재 단계({current_stage_id}) 유지 또는 fallback 메시지.")
        # 특별한 안내 없이 현재 상태의 fallback_message 또는 이전 라우터의 direct_response 사용됨.
        # 이 노드는 시나리오 '진행'을 담당하므로, 관련 없으면 다음 단계 결정 안 함.
        # main_agent_router_node에서 'answer_directly_chit_chat' 등으로 이미 분기되었어야 함.
        # 이 경로로 왔다는 것은 로직상 오류 가능성 -> fallback 처리
        determined_next_stage_id = current_stage_id # 현재 단계 유지
        final_response_text_for_user = state.get("main_agent_direct_response") or LOAN_SCENARIO_DATA.get("fallback_message")

    # 다음 단계의 프롬프트 설정
    target_stage_info = stages_data.get(determined_next_stage_id, {})
    if determined_next_stage_id == "END_SCENARIO_COMPLETE":
        final_response_text_for_user = LOAN_SCENARIO_DATA.get("end_scenario_message", "상담이 완료되었습니다.")
    elif determined_next_stage_id == "END_SCENARIO_ABORT":
        final_response_text_for_user = target_stage_info.get("prompt", LOAN_SCENARIO_DATA.get("end_conversation_message", "상담을 종료합니다."))
    elif determined_next_stage_id == "qa_listen": # QA 후 다시 질문을 듣는 상태
        final_response_text_for_user = target_stage_info.get("prompt") or ALL_PROMPTS.get('main_agent',{}).get('qa_follow_up_prompt', "다른 궁금한 점이 있으시면 말씀해주세요.")
    else: 
        final_response_text_for_user = target_stage_info.get("prompt", LOAN_SCENARIO_DATA.get("fallback_message"))
        # Placeholder 치환
        if "%{" in final_response_text_for_user:
            import re
            def replace_placeholder(match): key = match.group(1); return str(collected_info.get(key, f"%{{{key}}}%")) 
            final_response_text_for_user = re.sub(r'%\{([^}]+)\}%', replace_placeholder, final_response_text_for_user)


    print(f"Main Agent 시나리오 처리 결과: 다음 사용자 안내 '{final_response_text_for_user[:70]}...', 다음 단계 ID '{determined_next_stage_id}'")
    updated_messages = list(state.get("messages", []))
    # 중복 AIMessage 추가 방지
    if not updated_messages or not (isinstance(updated_messages[-1], AIMessage) and updated_messages[-1].content == final_response_text_for_user):
         updated_messages.append(AIMessage(content=final_response_text_for_user))
    
    return {
        **state, 
        "collected_loan_info": collected_info, 
        "current_scenario_stage_id": determined_next_stage_id,
        "final_response_text_for_tts": final_response_text_for_user, 
        "messages": updated_messages,
        "is_final_turn_response": True # 이 노드가 응답을 결정하면 턴 종료
    }

async def prepare_direct_response_node(state: AgentState) -> AgentState:
    print("--- 노드: 직접 응답 준비 (칫챗 등) ---")
    response_text = state.get("main_agent_direct_response") or LOAN_SCENARIO_DATA.get("fallback_message", "네, 말씀하세요.")
    updated_messages = list(state.get("messages", []))
    if not updated_messages or not (isinstance(updated_messages[-1], AIMessage) and updated_messages[-1].content == response_text):
        updated_messages.append(AIMessage(content=response_text))
    
    # 칫챗 후 다음 시나리오 단계는 현재 단계 유지 또는 qa_listen으로 설정
    next_stage_after_chitchat = state.get("current_scenario_stage_id", "qa_listen") # 또는 "greeting" 등 초기/대기 상태
    
    return {**state, "final_response_text_for_tts": response_text, "messages": updated_messages, "is_final_turn_response": True, "current_scenario_stage_id": next_stage_after_chitchat}

async def prepare_fallback_response_node(state: AgentState) -> AgentState:
    # (기존 prepare_fallback_response_node 로직)
    print("--- 노드: 폴백 응답 준비 ---")
    response_text = state.get("error_message") or LOAN_SCENARIO_DATA.get("fallback_message", "죄송합니다, 잘 이해하지 못했습니다.")
    updated_messages = list(state.get("messages", []))
    if not updated_messages or not (isinstance(updated_messages[-1], AIMessage) and updated_messages[-1].content == response_text):
        updated_messages.append(AIMessage(content=response_text))
    
    # 폴백 후 다음 시나리오 단계는 현재 단계 유지 또는 재질문 단계
    next_stage_after_fallback = state.get("current_scenario_stage_id") # 현재 단계 유지하며 재시도 유도
    # 또는 특정 reprompt stage ID: current_stage_info.get("reprompt_stage_id", state.get("current_scenario_stage_id"))

    return {**state, "final_response_text_for_tts": response_text, "messages": updated_messages, "is_final_turn_response": True, "current_scenario_stage_id": next_stage_after_fallback}

async def prepare_end_conversation_node(state: AgentState) -> AgentState:
    # (기존 prepare_end_conversation_node 로직)
    print("--- 노드: 대화 종료 메시지 준비 ---")
    response_text = LOAN_SCENARIO_DATA.get("end_conversation_message", "상담을 종료합니다. 이용해주셔서 감사합니다.")
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=response_text)]
    return {**state, "final_response_text_for_tts": response_text, "messages": updated_messages, "is_final_turn_response": True, "current_scenario_stage_id": "END_SCENARIO_ABORT"} # 명시적 종료 상태


async def handle_error_node(state: AgentState) -> AgentState: # 최종 에러 처리
    print("--- 노드: 에러 핸들링 (최종) ---")
    error_msg_for_user = state.get("error_message", "알 수 없는 오류가 발생했습니다. 죄송합니다.")
    updated_messages = list(state.get("messages", []))
    if not updated_messages or not (isinstance(updated_messages[-1], AIMessage) and updated_messages[-1].content == error_msg_for_user):
        updated_messages.append(AIMessage(content=error_msg_for_user))
    
    return {**state, "final_response_text_for_tts": error_msg_for_user, "is_final_turn_response": True, "messages": updated_messages, "current_scenario_stage_id": state.get("current_scenario_stage_id")} # 현재 단계 유지

# --- 조건부 엣지 로직 (STT 노드 제거 및 라우팅 수정) ---
def route_from_entry(state: AgentState) -> str:
    if state.get("is_final_turn_response"): return END # 입력 오류 등으로 바로 종료될 경우
    # STT는 chat.py에서 처리하고 결과를 stt_result에 담아오므로, STT 노드 불필요.
    return "main_agent_router_node" 

# main_agent_router_node의 라우팅 조건은 기존과 유사
def route_from_main_agent_router(state: AgentState) -> str:
    # (기존 route_from_main_agent_router 로직)
    decision = state.get("main_agent_routing_decision")
    print(f"Main Agent 라우팅 결정: {decision}")
    if state.get("is_final_turn_response"): return END 
    if decision == "invoke_scenario_agent": return "call_scenario_agent_node"
    if decision == "process_next_scenario_step": return "main_agent_scenario_processing_node" # scenario_agent_output이 채워져 있음
    if decision == "invoke_qa_agent": return "call_qa_agent_node" 
    if decision == "answer_directly_chit_chat": return "prepare_direct_response_node"
    if decision == "end_conversation": return "prepare_end_conversation_node"
    return "prepare_fallback_response_node" # unclear_input 등

# call_scenario_agent_node 다음은 main_agent_scenario_processing_node로 통일
def route_from_scenario_agent_call(state: AgentState) -> str:
    # (기존 route_from_scenario_agent_call 로직)
    scenario_output = state.get("scenario_agent_output")
    if scenario_output and scenario_output.get("intent", "").startswith("error_"):
        # 에러 메시지를 상태에 설정하고 handle_error_node로
        err_msg = f"답변 분석 중 오류: {scenario_output.get('intent')}"
        state["error_message"] = err_msg # final_response_text_for_tts도 설정해야 함
        state["final_response_text_for_tts"] = err_msg
        return "handle_error_node"
    return "main_agent_scenario_processing_node"

def route_from_qa_agent_call(state: AgentState) -> str:
    # QA 호출 후에는 run_agent_streaming에서 스트리밍 처리, 그래프는 종료
    return END

# --- 그래프 빌드 (STT 노드 제거) ---
workflow = StateGraph(AgentState)
nodes_to_add = [
    ("entry_point_node", entry_point_node),
    ("main_agent_router_node", main_agent_router_node),
    ("call_scenario_agent_node", call_scenario_agent_node),
    ("call_qa_agent_node", call_qa_agent_node), # QA 스트리밍 시작 신호
    ("main_agent_scenario_processing_node", main_agent_scenario_processing_node),
    ("prepare_direct_response_node", prepare_direct_response_node),
    ("prepare_fallback_response_node", prepare_fallback_response_node),
    ("prepare_end_conversation_node", prepare_end_conversation_node),
    ("handle_error_node", handle_error_node)
]
for name, node_func in nodes_to_add: workflow.add_node(name, node_func)

workflow.set_entry_point("entry_point_node")

workflow.add_conditional_edges("entry_point_node", route_from_entry)
# STT 노드가 없으므로 stt_node 관련 엣지 제거

workflow.add_conditional_edges("main_agent_router_node", route_from_main_agent_router)
workflow.add_conditional_edges("call_scenario_agent_node", route_from_scenario_agent_call)
workflow.add_conditional_edges("call_qa_agent_node", route_from_qa_agent_call) # END로 연결

# 응답 준비 노드들은 모두 END로 연결 (각 노드에서 is_final_turn_response=True 설정)
workflow.add_edge("main_agent_scenario_processing_node", END)
workflow.add_edge("prepare_direct_response_node", END)
workflow.add_edge("prepare_fallback_response_node", END)
workflow.add_edge("prepare_end_conversation_node", END)
workflow.add_edge("handle_error_node", END)

app_graph = workflow.compile()
print("--- LangGraph 컴파일 완료 ---")


# --- run_agent_streaming 함수 (기존 파일 참고, TTS 로직 제거) ---
async def run_agent_streaming(
    user_input_text: Optional[str] = None, # STT 결과를 직접 받거나 텍스트 입력
    user_input_audio_b64: Optional[str] = None, # chat.py에서 STT 처리 후 user_input_text로 변환하여 전달 권장
    session_id: Optional[str] = "default_session",
    current_state_dict: Optional[Dict[str, Any]] = None
) -> AsyncGenerator[Union[Dict[str, Any], str], None]:
    
    if not OPENAI_API_KEY or not main_llm or not streaming_llm:
        error_msg = "LLM 서비스가 초기화되지 않았습니다. API 키 설정을 확인하세요."
        print(f"CRITICAL ({session_id}): {error_msg}")
        yield {"type": "error", "session_id": session_id, "message": error_msg}
        yield {"type": "final_state", "session_id": session_id, "data": {"error_message": error_msg, "is_final_turn_response": True, "messages": [AIMessage(content=error_msg)]}}
        return

    # 1. 초기 상태 설정
    if not LOAN_SCENARIO_DATA: # 시나리오 데이터 로드 확인
        try: load_loan_scenario_sync()
        except Exception as e:
            yield {"type": "error", "session_id": session_id, "message": f"상담 서비스 초기화 실패 (시나리오 로드): {e}"}
            return
    
    initial_messages: List[BaseMessage] = ([SystemMessage(content=LOAN_SCENARIO_DATA.get("system_prompt", ""))] 
                                         if not (current_state_dict and current_state_dict.get("messages")) 
                                         else list(current_state_dict["messages"]))

    initial_input_for_graph: AgentState = cast(AgentState, {
        "session_id": session_id or "default_session",
        "user_input_text": user_input_text, # STT 결과 또는 텍스트 입력
        "user_input_audio_b64": user_input_audio_b64, # 참고용으로 전달, 실제 STT는 chat.py에서
        "stt_result": user_input_text, # stt_result에 사용자 발화 텍스트를 넣어줌
        "messages": initial_messages,
        "current_scenario_stage_id": (current_state_dict.get("current_scenario_stage_id", LOAN_SCENARIO_DATA.get("initial_stage_id", "greeting")) 
                                      if current_state_dict else LOAN_SCENARIO_DATA.get("initial_stage_id", "greeting")),
        "collected_loan_info": current_state_dict.get("collected_loan_info", {}) if current_state_dict else {},
        "loan_scenario_data": LOAN_SCENARIO_DATA, # 전역에서 로드된 데이터 사용
        # 턴 시작 시 초기화 필드
        "main_agent_routing_decision": None, "main_agent_direct_response": None,
        "scenario_agent_output": None, 
        "final_response_text_for_tts": None, "is_final_turn_response": False, "error_message": None,
    })
    
    print(f"\n--- [{session_id}] Agent Turn 시작 ---")
    print(f"초기 입력 상태 (요약): stage='{initial_input_for_graph['current_scenario_stage_id']}', text='{user_input_text}'")

    final_graph_output_state: Optional[AgentState] = None # 최종 상태 저장용
    full_response_text_streamed = ""

    try:
        graph_output_state: AgentState = await app_graph.ainvoke(initial_input_for_graph)
        final_graph_output_state = graph_output_state # 중간 결과 저장

        print(f"LangGraph 실행 완료. 라우팅: '{graph_output_state.get('main_agent_routing_decision')}', 다음 단계 ID: '{graph_output_state.get('current_scenario_stage_id')}'")

        # 3. 스트리밍 결정 및 실행
        if graph_output_state.get("main_agent_routing_decision") == "invoke_qa_agent":
            user_question_for_qa = graph_output_state.get("stt_result", "") # 최종 사용자 발화
            if user_question_for_qa:
                scenario_name_for_qa = graph_output_state.get("loan_scenario_data", {}).get("scenario_name", "디딤돌 대출")
                print(f"QA 스트리밍 시작 (세션: {session_id}, 질문: '{user_question_for_qa[:50]}...')")
                
                yield {"type": "stream_start", "stream_type": "qa_answer"}
                async for chunk in invoke_qa_agent_streaming_logic(user_question_for_qa, scenario_name_for_qa):
                    yield chunk 
                    full_response_text_streamed += chunk
                
                # QA 후 최종 상태 업데이트
                updated_messages_after_qa = list(graph_output_state.get("messages", []))
                # QA 질문은 이미 HumanMessage로 들어가 있음, QA 답변을 AIMessage로 추가
                if not updated_messages_after_qa or not (isinstance(updated_messages_after_qa[-1], AIMessage) and updated_messages_after_qa[-1].content == full_response_text_streamed):
                    updated_messages_after_qa.append(AIMessage(content=full_response_text_streamed))
                
                final_graph_output_state = {
                    **graph_output_state, 
                    "final_response_text_for_tts": full_response_text_streamed,
                    "messages": updated_messages_after_qa, 
                    "is_final_turn_response": True,
                    "current_scenario_stage_id": LOAN_SCENARIO_DATA.get("stages",{}).get(graph_output_state.get("current_scenario_stage_id","qa_listen"),{}).get("default_next_stage_id", "qa_listen") # QA 후 다음 단계
                }
            else: 
                err_msg_qa = graph_output_state.get("error_message") or "질문을 인식하지 못했습니다. 다시 질문해주시겠어요?"
                yield {"type": "stream_start", "stream_type": "error_message"}
                for char_chunk in err_msg_qa: yield char_chunk; await asyncio.sleep(0.01) # 가짜 스트리밍
                full_response_text_streamed = err_msg_qa
                final_graph_output_state = {**graph_output_state, "final_response_text_for_tts": full_response_text_streamed, "error_message": err_msg_qa, "is_final_turn_response": True}

        elif graph_output_state.get("final_response_text_for_tts"): # 시나리오, 칫챗, 폴백 등
            text_to_stream = graph_output_state["final_response_text_for_tts"]
            yield {"type": "stream_start", "stream_type": "general_response"}
            chunk_size = 20 
            for i in range(0, len(text_to_stream), chunk_size):
                chunk = text_to_stream[i:i+chunk_size]
                yield chunk
                await asyncio.sleep(0.02) 
                full_response_text_streamed += chunk
            # final_graph_output_state는 이미 graph_output_state로 설정됨

        else: # 응답 텍스트가 없는 예외적 경우
            error_message_fallback = graph_output_state.get("error_message", "응답을 생성하지 못했습니다.")
            yield {"type": "stream_start", "stream_type": "critical_error"}
            for char_chunk in error_message_fallback: yield char_chunk; await asyncio.sleep(0.01)
            full_response_text_streamed = error_message_fallback
            final_graph_output_state = {**graph_output_state, "final_response_text_for_tts": full_response_text_streamed, "error_message": error_message_fallback, "is_final_turn_response": True}

        yield {"type": "stream_end", "full_text": full_response_text_streamed}

    except Exception as e:
        print(f"CRITICAL error in run_agent_streaming for session {session_id}: {e}")
        import traceback; traceback.print_exc()
        error_response = f"죄송합니다, 에이전트 처리 중 심각한 시스템 오류가 발생했습니다."
        yield {"type": "stream_start", "stream_type": "critical_error"}
        for char_chunk in error_response: yield char_chunk; await asyncio.sleep(0.01)
        yield {"type": "stream_end", "full_text": error_response}
        
        # 오류 발생 시 최종 상태 구성 (최대한 안전하게)
        final_graph_output_state = initial_input_for_graph.copy() # type: ignore
        final_graph_output_state["error_message"] = error_response # type: ignore
        final_graph_output_state["final_response_text_for_tts"] = error_response # type: ignore
        final_graph_output_state["is_final_turn_response"] = True # type: ignore
        current_messages_on_error = list(initial_input_for_graph.get("messages", [])) # type: ignore
        if not current_messages_on_error or not (isinstance(current_messages_on_error[-1], AIMessage) and current_messages_on_error[-1].content == error_response):
            current_messages_on_error.append(AIMessage(content=error_response))
        final_graph_output_state["messages"] = current_messages_on_error # type: ignore


    finally:
        # 최종 상태를 한번 더 yield (세션 저장용)
        if final_graph_output_state:
            # messages 필드가 Langchain 객체이므로 필요시 직렬화 (여기서는 그대로 전달)
            # final_graph_output_state["messages"] = [msg.dict() for msg in final_graph_output_state.get("messages", [])]
            
            # TTS 관련 필드는 AgentState에 없음.
            yield {"type": "final_state", "session_id": session_id, "data": final_graph_output_state}
        else: # 예외로 인해 final_graph_output_state가 설정되지 않은 경우
             yield {"type": "final_state", "session_id": session_id, "data": {"error_message": "Agent 실행 중 심각한 오류로 최종 상태 기록 불가", "is_final_turn_response": True}}

        print(f"--- [{session_id}] Agent Turn 종료 (최종 AI 응답 텍스트 길이: {len(full_response_text_streamed)}) ---")