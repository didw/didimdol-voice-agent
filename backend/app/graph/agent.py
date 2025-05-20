# backend/app/graph/agent.py

import base64
import json
import yaml
import asyncio
from pathlib import Path
from typing import Dict, Optional, Sequence, Literal, Any, List, Union, cast, AsyncGenerator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, AIMessageChunk
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END # END 임포트 확인
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field as PydanticField

from .state import AgentState, ScenarioAgentOutput, QAAgentOutput
from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME
# transcribe_audio_bytes만 가져오고, 스트리밍 서비스는 chat.py에서 사용
from ..services.google_services import transcribe_audio_bytes, GOOGLE_SERVICES_AVAILABLE # GOOGLE_SERVICES_AVAILABLE 임포트

# --- Pydantic 모델 및 파서 ---
class NextStageDecisionModel(BaseModel):
    chosen_next_stage_id: str = PydanticField(description="LLM이 결정한 다음 시나리오 단계 ID")
next_stage_decision_parser = PydanticOutputParser(pydantic_object=NextStageDecisionModel)

class ScenarioOutputModel(BaseModel):
    intent: str = PydanticField(description="사용자 발화의 주요 의도 (예: '정보제공_연소득', '확인_긍정', '질문_대출한도')")
    entities: Dict[str, Any] = PydanticField(default_factory=dict, description="추출된 주요 개체 (예: {'income_amount': 6000, 'loan_type': '디딤돌'})")
    is_scenario_related: bool = PydanticField(description="현재 진행 중인 대출 시나리오와 관련된 발화인지 여부")
    user_sentiment: Optional[Literal['positive', 'negative', 'neutral']] = PydanticField(default='neutral', description="사용자 발화의 감정")
scenario_output_parser = PydanticOutputParser(pydantic_object=ScenarioOutputModel)


# --- 경로 및 설정 ---
APP_DIR = Path(__file__).parent.parent
DATA_DIR = APP_DIR / "data"
CONFIG_DIR = APP_DIR / "config"
SCENARIO_FILE_PATH = DATA_DIR / "loan_scenario.json"
QA_KNOWLEDGE_BASE_PATH = DATA_DIR / "didimdol.md"

PROMPT_FILES = {
    'main_agent': CONFIG_DIR / "main_agent_prompts.yaml",
    'scenario_agent': CONFIG_DIR / "scenario_agent_prompts.yaml",
    'qa_agent': CONFIG_DIR / "qa_agent_prompts.yaml",
}

# --- LLM 초기화 ---
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

main_llm = ChatOpenAI( # JSON 출력 및 라우팅 결정용
    model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.1,
    model_kwargs={"response_format": {"type": "json_object"}}
)
streaming_llm = ChatOpenAI( # 텍스트 스트리밍용 (QA 등)
    model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.3, streaming=True
)

def load_all_prompts() -> Dict[str, Dict[str, str]]:
    loaded_prompts = {}
    try:
        for agent_name, file_path in PROMPT_FILES.items():
            with open(file_path, 'r', encoding='utf-8') as f:
                prompts_for_agent = yaml.safe_load(f)
            if not prompts_for_agent:
                raise ValueError(f"{agent_name} 프롬프트 파일이 비어있거나 로드에 실패했습니다: {file_path}")
            loaded_prompts[agent_name] = prompts_for_agent
        print("--- 모든 에이전트 프롬프트 로드 완료 ---")
        return loaded_prompts
    except FileNotFoundError as e:
        raise FileNotFoundError(f"프롬프트 파일을 찾을 수 없습니다: {e.filename}")
    except yaml.YAMLError as e:
        raise ValueError(f"프롬프트 파일의 YAML 형식이 올바르지 않습니다: {e}")
    except Exception as e:
        raise Exception(f"프롬프트 파일 로드 중 오류 발생: {e}")

# --- 프롬프트 및 시나리오 로드 함수 (기존과 동일) ---
ALL_PROMPTS = load_all_prompts() # 함수 호출 위치 변경 없음

def load_loan_scenario() -> Dict:
    try:
        with open(SCENARIO_FILE_PATH, 'r', encoding='utf-8') as f:
            scenario = json.load(f)
        if not scenario: raise ValueError("시나리오 파일이 비어있습니다.")
        return scenario
    except FileNotFoundError: raise FileNotFoundError(f"시나리오 파일을 찾을 수 없습니다: {SCENARIO_FILE_PATH}")
    except json.JSONDecodeError: raise ValueError(f"시나리오 파일의 JSON 형식이 올바르지 않습니다: {SCENARIO_FILE_PATH}")
    except Exception as e: raise Exception(f"시나리오 파일 로드 중 오류 발생: {e}")

def format_transitions_for_prompt(transitions: List[Dict[str, Any]], default_next_stage_id: Optional[str]) -> str:
    if not transitions and not default_next_stage_id: return "현재 단계에서 정의된 다음 단계(Transition)가 없습니다."
    formatted_list = []
    if transitions:
        for i, transition in enumerate(transitions):
            keywords_str = ", ".join(transition.get("keywords", []))
            condition_desc = f"사용자 답변에 '{keywords_str}' 키워드 포함 시" if keywords_str else "항상"
            formatted_list.append(f"{i+1}. 다음 단계 ID: '{transition['next_stage_id']}', 조건 설명: {condition_desc}")
    result = "\n".join(formatted_list)
    return result if result else "명시된 Transition 조건 없음."

def format_messages_for_prompt(messages: Sequence[BaseMessage], max_history: int = 3) -> str:
    history_str = []
    relevant_messages = [m for m in messages if not isinstance(m, SystemMessage)][-max_history:]
    for msg in relevant_messages:
        role = "사용자" if isinstance(msg, HumanMessage) else "상담원"
        history_str.append(f"{role}: {msg.content}")
    return "\n".join(history_str) if history_str else "이전 대화 없음."

# --- Specialist Agent 로직 ---
async def invoke_scenario_agent_logic(user_input: str, current_stage_prompt: str, expected_info_key: Optional[str], messages_history: Sequence[BaseMessage], scenario_name: str) -> ScenarioAgentOutput:
    print(f"--- Scenario Agent 호출 (입력: '{user_input}') ---")
    prompt_template = ALL_PROMPTS.get('scenario_agent', {}).get('nlu_extraction', '')
    if not prompt_template:
        return cast(ScenarioAgentOutput, {"intent": "error_prompt_not_found", "entities": {}, "is_scenario_related": False, "user_sentiment": "neutral"})

    formatted_history = format_messages_for_prompt(messages_history)
    try:
        formatted_prompt = prompt_template.format(
            scenario_name=scenario_name, current_stage_prompt=current_stage_prompt,
            expected_info_key=expected_info_key or "특정 정보 없음",
            formatted_messages_history=formatted_history, user_input=user_input,
            format_instructions=scenario_output_parser.get_format_instructions()
        )
        response = await main_llm.ainvoke([HumanMessage(content=formatted_prompt)]) # JSON 출력이므로 main_llm 사용
        raw_content = response.content.strip()
        if raw_content.startswith("```json"): raw_content = raw_content.replace("```json", "").replace("```", "").strip()
        parsed_output_dict = scenario_output_parser.parse(raw_content).model_dump()
        print(f"Scenario Agent 결과: {parsed_output_dict}")
        return cast(ScenarioAgentOutput, parsed_output_dict)
    except Exception as e:
        print(f"Scenario Agent 처리 오류: {e}. LLM 응답: {getattr(e, 'llm_output', getattr(response if 'response' in locals() else None, 'content', 'N/A'))}")
        return cast(ScenarioAgentOutput, {"intent": "error_parsing_scenario_output", "entities": {}, "is_scenario_related": False, "user_sentiment": "neutral"})

knowledge_base_content_cache: Optional[str] = None
async def load_knowledge_base_content_async() -> Optional[str]:
    global knowledge_base_content_cache
    if knowledge_base_content_cache is None:
        print("--- QA Agent: 지식베이스 (didimdol.md) 로딩 중... ---")
        try:
            if not QA_KNOWLEDGE_BASE_PATH.exists():
                print(f"경고: 지식베이스 파일을 찾을 수 없습니다: {QA_KNOWLEDGE_BASE_PATH}"); knowledge_base_content_cache = "ERROR_FILE_NOT_FOUND"; return None
            with open(QA_KNOWLEDGE_BASE_PATH, 'r', encoding='utf-8') as f: content = f.read()
            if not content.strip():
                print(f"경고: 지식베이스 파일이 비어있습니다: {QA_KNOWLEDGE_BASE_PATH}"); knowledge_base_content_cache = "EMPTY_CONTENT"; return None
            knowledge_base_content_cache = content
            print(f"--- QA Agent: 지식베이스 (didimdol.md) 로딩 완료 ({len(content)} 자) ---")
        except Exception as e: print(f"QA 지식베이스 로딩 실패: {e}"); knowledge_base_content_cache = "ERROR_LOADING_FAILED"; return None
    if knowledge_base_content_cache in ["ERROR_FILE_NOT_FOUND", "EMPTY_CONTENT", "ERROR_LOADING_FAILED"]: return None
    return knowledge_base_content_cache

async def invoke_qa_agent_streaming_logic(user_question: str, scenario_name: str) -> AsyncGenerator[str, None]:
    print(f"--- QA Agent 스트리밍 호출 (질문: '{user_question}') ---")
    try:
        knowledge_base_text = await load_knowledge_base_content_async()
        if knowledge_base_text is None:
            error_message_map = {
                "ERROR_FILE_NOT_FOUND": f"죄송합니다. 상담에 필요한 정보 파일({QA_KNOWLEDGE_BASE_PATH.name})을 찾을 수 없습니다.",
                "EMPTY_CONTENT": f"죄송합니다. 상담에 필요한 정보 파일({QA_KNOWLEDGE_BASE_PATH.name})의 내용이 비어있습니다.",
                "ERROR_LOADING_FAILED": "죄송합니다. 현재 대출 관련 정보를 조회할 수 없습니다 (지식베이스 문제)."
            }
            yield error_message_map.get(knowledge_base_content_cache, "지식베이스 접근 중 알 수 없는 오류 발생.")
            return

        prompt_template = ALL_PROMPTS.get('qa_agent', {}).get('rag_answer_generation', '')
        if not prompt_template:
            yield "죄송합니다, 답변 생성에 필요한 설정(프롬프트)을 찾을 수 없습니다."
            return

        formatted_prompt = prompt_template.format(
            scenario_name=scenario_name, context_for_llm=knowledge_base_text, user_question=user_question
        )
        print(f"\n=== QA Agent 스트리밍 프롬프트 (일부 컨텍스트) ===\n{formatted_prompt[:500]}...\n=============================\n")
        
        async for chunk in streaming_llm.astream([HumanMessage(content=formatted_prompt)]):
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                yield str(chunk.content)
            elif isinstance(chunk, str) and chunk: # 이전 버전 호환
                yield chunk
    except Exception as e:
        print(f"QA Agent 스트리밍 처리 오류: {e}")
        yield f"질문 답변 중 시스템 오류가 발생했습니다: {e}"

# --- LangGraph 노드 함수 정의 ---
async def entry_point_node(state: AgentState) -> AgentState:
    print("--- 노드: Entry Point ---")
    scenario_data = state.get("loan_scenario_data")
    if not scenario_data:
        try: scenario_data = load_loan_scenario(); state["loan_scenario_data"] = scenario_data
        except Exception as e:
            print(f"CRITICAL: 시나리오 로드 실패 (entry_point_node): {e}")
            return {**state, "error_message": "상담 서비스 초기화 실패.", "final_response_text_for_tts": "상담 서비스 초기화에 실패했습니다.", "is_final_turn_response": True}

    turn_specific_defaults: Dict[str, Any] = {
        "stt_result": None, "main_agent_routing_decision": None, "main_agent_direct_response": None,
        "scenario_agent_output": None, "qa_agent_output": None, # QAAgentOutput은 스트리밍 결과를 담지 않음
        "final_response_text_for_tts": None, "is_final_turn_response": False, "error_message": None,
    }
    updated_state = {**state, **turn_specific_defaults}
    current_messages = list(updated_state.get("messages", []))

    if updated_state.get("user_input_audio_b64"):
        print("입력 유형: 음성 -> STT 노드로 이동")
    elif updated_state.get("user_input_text"):
        print(f"입력 유형: 텍스트 ('{updated_state['user_input_text']}') -> Main Router로 이동")
        human_message_content = updated_state["user_input_text"]
        updated_state["stt_result"] = human_message_content
        if not current_messages or not (isinstance(current_messages[-1], HumanMessage) and current_messages[-1].content == human_message_content):
            current_messages.append(HumanMessage(content=human_message_content))
    else: # 사용자 입력 없음
        updated_state.update({"error_message": "사용자 입력이 없습니다.", "final_response_text_for_tts": "사용자 입력이 없습니다.", "is_final_turn_response": True})

    updated_state["messages"] = current_messages
    return cast(AgentState, updated_state)

async def stt_node(state: AgentState) -> AgentState:
    print("--- 노드: STT ---")
    audio_b64 = state.get("user_input_audio_b64")
    if not audio_b64:
        return {**state, "error_message": "STT 오류: 음성 데이터 없음.", "final_response_text_for_tts": "음성 데이터가 제공되지 않았습니다.", "is_final_turn_response": True}
    
    if not GOOGLE_SERVICES_AVAILABLE: # STT 서비스 사용 불가 시 처리
        print("STT 노드: Google 서비스 사용 불가. STT를 건너뛰고 빈 텍스트로 처리합니다.")
        transcribed_text = "" # 또는 적절한 오류 메시지
        # 사용자에게 안내 메시지 추가 고려
        state["error_message"] = "음성 인식 서비스를 현재 사용할 수 없습니다. 텍스트로 입력해주세요." # 사용자에게 보여줄 메시지
        # final_response_text_for_tts는 이 메시지로 설정하거나, 다음 단계에서 처리
    else:
        try:
            audio_bytes = base64.b64decode(audio_b64)
            # 클라이언트가 WebM/Opus, 48kHz로 전송한다고 가정
            transcribed_text = await transcribe_audio_bytes(audio_bytes, sample_rate_hertz=48000, encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS)
            if not transcribed_text and transcribed_text != "": transcribed_text = "" # STT 결과가 없을 수 있음
        except Exception as e:
            print(f"STT 처리 중 오류: {e}")
            return {**state, "error_message": f"음성 인식 오류: {e}", "final_response_text_for_tts": "음성 인식 중 문제가 발생했습니다.", "is_final_turn_response": True}

    print(f"STT 결과: '{transcribed_text}'")
    updated_messages = list(state.get("messages", []))
    if not updated_messages or not (isinstance(updated_messages[-1], HumanMessage) and updated_messages[-1].content == transcribed_text):
         updated_messages.append(HumanMessage(content=transcribed_text))
    return {**state, "stt_result": transcribed_text, "messages": updated_messages}

async def main_agent_router_node(state: AgentState) -> AgentState:
    print("--- 노드: Main Agent Router ---")
    user_input = state.get("stt_result", "") # STT 결과가 비어있을 수 있음 (음성 인식 실패 등)
    messages_history = state.get("messages", [])
    
    # STT 결과가 없거나 빈 문자열일 경우 (STT 실패 또는 무음성)
    if user_input == "" and state.get("user_input_audio_b64"): # 음성 입력이었는데 STT 결과가 빈 경우
        print("Main Agent Router: STT 결과가 비어있습니다. 'unclear_input'으로 처리합니다.")
        return {**state, "main_agent_routing_decision": "unclear_input", "error_message": "음성을 인식하지 못했어요. 다시 말씀해주시겠어요?", "final_response_text_for_tts": "음성을 인식하지 못했어요. 다시 말씀해주시겠어요?"}
    elif not user_input and not state.get("user_input_audio_b64"): # 텍스트 입력도 비어있는 경우
        print("Main Agent Router: 사용자 입력이 없습니다. 'unclear_input'으로 처리합니다.")
        return {**state, "main_agent_routing_decision": "unclear_input", "error_message": "입력 내용이 없습니다.", "final_response_text_for_tts": "입력 내용이 없습니다."}


    if not messages_history or not isinstance(messages_history[-1], HumanMessage):
        messages_history = list(messages_history) + [HumanMessage(content=user_input)] # 방어 코드

    current_stage_id = state.get("current_scenario_stage_id", "greeting")
    loan_scenario = state.get("loan_scenario_data", {})
    current_stage_info = loan_scenario.get("stages", {}).get(current_stage_id, {})
    prompt_template = ALL_PROMPTS.get('main_agent', {}).get('router_prompt', '')

    if not prompt_template:
         return {**state, "error_message": "라우터 프롬프트 로드 실패", "final_response_text_for_tts": "시스템 설정 오류입니다.", "main_agent_routing_decision": "unclear_input"}

    formatted_history = format_messages_for_prompt(messages_history[:-1]) 
    qa_keywords_list = loan_scenario.get("qa_keywords", ["궁금"])
    qa_keywords_example_str = qa_keywords_list[0] if qa_keywords_list else "질문"

    try:
        main_agent_prompt_filled = prompt_template.format(
            user_input=user_input, formatted_messages_history=formatted_history,
            current_scenario_stage_id=current_stage_id, current_stage_prompt=current_stage_info.get("prompt", "정보 없음"),
            collected_loan_info=str(state.get("collected_loan_info", {})), scenario_name=loan_scenario.get("scenario_name", "대출 상담"),
            expected_info_key=current_stage_info.get("expected_info_key", "정보 없음"), qa_keywords_example=qa_keywords_example_str
        )
        response = await main_llm.ainvoke([HumanMessage(content=main_agent_prompt_filled)])
        raw_response_content = response.content.strip()
        if raw_response_content.startswith("```json"): raw_response_content = raw_response_content.replace("```json", "").replace("```", "").strip()
        decision_data = json.loads(raw_response_content)
        routing_decision = decision_data.get("action")
        direct_response = decision_data.get("direct_response")
        extracted_value = decision_data.get("extracted_value")
        print(f"Main Agent 결정: {routing_decision}, 직접 답변: {direct_response}, 추출값: {extracted_value}")
        
        scenario_output_for_direct_processing = None
        if routing_decision == "process_next_scenario_step" and extracted_value is not None:
            key_to_collect = current_stage_info.get("expected_info_key")
            entities_direct = {key_to_collect: extracted_value} if key_to_collect else {}
            scenario_output_for_direct_processing = cast(ScenarioAgentOutput, {"intent": f"direct_confirm_{str(extracted_value).lower()}", "entities": entities_direct, "is_scenario_related": True, "user_sentiment": "neutral"})
        return {**state, "main_agent_routing_decision": routing_decision, "main_agent_direct_response": direct_response, "scenario_agent_output": scenario_agent_output_for_direct_processing}
    except json.JSONDecodeError as je:
        err_msg = "요청 이해 중 내부 오류 발생 (JSON 파싱). 다시 시도해주세요."
        print(f"Main Agent Router JSON 파싱 오류: {je}. LLM 응답: {getattr(response if 'response' in locals() else None, 'content', 'N/A')}")
        return {**state, "error_message": err_msg, "final_response_text_for_tts":err_msg, "main_agent_routing_decision": "unclear_input"}
    except Exception as e:
        err_msg = "요청 처리 중 시스템 오류 발생. 잠시 후 다시 시도해주세요."
        print(f"Main Agent Router 시스템 오류: {e}"); import traceback; traceback.print_exc()
        return {**state, "error_message": err_msg, "final_response_text_for_tts": err_msg, "main_agent_routing_decision": "unclear_input"}

async def call_scenario_agent_node(state: AgentState) -> AgentState:
    print("--- 노드: Scenario Agent 호출 ---")
    # (기존 로직과 거의 동일, invoke_scenario_agent_logic 사용)
    user_input = state.get("stt_result", "")
    # STT 결과가 없는 경우에 대한 방어 코드 추가
    if not user_input and user_input != "": # user_input이 None일 수 있음
        # 이 경우는 main_agent_router_node에서 이미 처리되었어야 함.
        # 그럼에도 불구하고 여기까지 왔다면, unclear_input으로 처리.
        print("Scenario Agent 호출 노드: 사용자 입력 없음. 폴백 처리 필요.")
        # 이 상태를 다음 노드로 전달하여 처리하도록 하거나, 여기서 직접 에러 상태 설정.
        # 여기서는 다음 노드(main_agent_scenario_processing_node)가 is_scenario_related를 보고 처리하도록 둠.
        # 또는, 여기서 main_agent_routing_decision을 'unclear_input' 등으로 변경하여 폴백 유도 가능.
        # 일단은 ScenarioAgentOutput을 비어있는 형태로라도 반환.
        return {**state, "scenario_agent_output": cast(ScenarioAgentOutput, {"intent": "no_input", "entities": {}, "is_scenario_related": False, "user_sentiment": "neutral"})}

    current_stage_id = state.get("current_scenario_stage_id", "greeting")
    loan_scenario = state.get("loan_scenario_data", {})
    current_stage_info = loan_scenario.get("stages", {}).get(current_stage_id, {})
    current_stage_prompt = current_stage_info.get("prompt", "")
    expected_info_key = current_stage_info.get("expected_info_key")
    messages_history = state.get("messages", []) 
    scenario_name = loan_scenario.get("scenario_name", "대출 상담")
    
    output = await invoke_scenario_agent_logic(user_input, current_stage_prompt, expected_info_key, messages_history, scenario_name)
    return {**state, "scenario_agent_output": output}


async def call_qa_agent_node(state: AgentState) -> AgentState:
    print("--- 노드: QA Agent 호출 준비 (스트리밍은 run_agent_streaming에서 처리) ---")
    # 이 노드는 QA 스트리밍을 시작해야 함을 나타내는 '신호' 역할을 함.
    # 실제 QA 로직(스트리밍)은 run_agent_streaming 함수가 이 노드의 라우팅 결과를 보고 처리.
    # 상태에 'qa_requested' 같은 플래그를 설정하거나, 다음 라우팅 조건에서 사용될 수 있음.
    # 여기서는 특별한 상태 변경 없이 그대로 반환. main_agent_routing_decision이 이미 'invoke_qa_agent'.
    return state

async def main_agent_scenario_processing_node(state: AgentState) -> AgentState:
    print("--- 노드: Main Agent 시나리오 처리 ---")
    # (기존 로직과 거의 동일, final_response_text_for_tts 설정)
    # 이 노드에서 생성된 final_response_text_for_tts는 run_agent_streaming에서 "가짜" 스트리밍됨.
    user_input = state.get("stt_result", "")
    scenario_output = state.get("scenario_agent_output") 
    current_stage_id = state.get("current_scenario_stage_id", "greeting")
    loan_scenario = state.get("loan_scenario_data", {})
    stages = loan_scenario.get("stages", {})
    current_stage_info = stages.get(current_stage_id, {})
    collected_info = state.get("collected_loan_info", {}).copy()

    final_response_text_for_user: str = loan_scenario.get("fallback_message", "죄송합니다, 처리 중 오류가 발생했습니다.")
    determined_next_stage_id: str = current_stage_id 

    is_related_to_scenario = False
    # Scenario Agent가 호출되었고 (scenario_output 존재), 시나리오 관련 발화로 판단한 경우
    if scenario_output and scenario_output.get("is_scenario_related"):
        is_related_to_scenario = True
        extracted_entities = scenario_output.get("entities", {})
        key_to_collect = current_stage_info.get("expected_info_key")
        # 예상 정보 수집
        if key_to_collect and key_to_collect in extracted_entities and extracted_entities[key_to_collect] is not None:
            collected_info[key_to_collect] = extracted_entities[key_to_collect]
            print(f"정보 업데이트 (Scenario Agent - expected): {key_to_collect} = {extracted_entities[key_to_collect]}")
        # 그 외 추출된 정보도 일단 수집 (선택적)
        for key, value in extracted_entities.items(): 
            if key != key_to_collect and value is not None: # 중복 방지 및 None 값 제외
                 collected_info[key] = value
                 print(f"추가 정보 업데이트 (Scenario Agent): {key} = {value}")
    # Main Agent Router가 직접 다음 단계로 처리하도록 결정한 경우 (extracted_value 존재)
    elif state.get("main_agent_routing_decision") == "process_next_scenario_step" and scenario_output and scenario_output.get("entities"): # scenario_output이 direct processing 용으로 채워짐
        is_related_to_scenario = True # 이 경로도 시나리오 관련으로 간주
        extracted_entities_direct = scenario_output.get("entities", {})
        for key, value in extracted_entities_direct.items():
            if value is not None:
                collected_info[key] = value
                print(f"정보 업데이트 (Main Agent 직접 처리): {key} = {value}")
    
    if not is_related_to_scenario:
        print(f"시나리오 처리 노드: is_scenario_related가 False. 현재 단계({current_stage_id}) 유지 또는 폴백 메시지 사용.")
        # final_response_text_for_user는 loan_scenario.get("fallback_message")로 유지되거나,
        # 또는 "다시 한번 말씀해주시겠어요?" 와 같은 재질문 프롬프트 사용 가능.
        # 여기서는 다음 단계 결정을 시도하지 않고, 현재 상태의 fallback_message 사용.
        # determined_next_stage_id는 현재 ID 유지 또는 특정 '재질문' 스테이지로. 여기서는 현재 ID 유지.
        # 이미 fallback_message로 초기화 되어 있으므로 추가 작업 불필요.
        # 만약 이 상황에서 특정 안내를 원한다면 여기서 final_response_text_for_user 수정.
    else: # 시나리오 관련 발화일 경우 다음 단계 결정
        prompt_template = ALL_PROMPTS.get('main_agent', {}).get('determine_next_scenario_stage', '')
        if not prompt_template:
            print("오류: 다음 단계 결정 프롬프트를 찾을 수 없습니다. 기본 다음 단계로 진행합니다.")
            determined_next_stage_id = current_stage_info.get("default_next_stage_id", current_stage_id)
        else:
            scenario_agent_intent = scenario_output.get("intent", "정보 없음") if scenario_output else "정보 없음"
            scenario_agent_entities_str = str(scenario_output.get("entities", {})) if scenario_output else "{}"
            transitions_list = current_stage_info.get("transitions", [])
            formatted_transitions = format_transitions_for_prompt(transitions_list, current_stage_info.get("default_next_stage_id"))

            llm_prompt_for_next_stage = prompt_template.format(
                scenario_name=loan_scenario.get("scenario_name", "대출 상담"), current_stage_id=current_stage_id,
                current_stage_prompt=current_stage_info.get("prompt", "정보 없음"), user_input=user_input,
                scenario_agent_intent=scenario_agent_intent, scenario_agent_entities=scenario_agent_entities_str,
                collected_loan_info=str(collected_info), formatted_transitions=formatted_transitions,
                default_next_stage_id=current_stage_info.get("default_next_stage_id", "None")
            )
            print(f"\n=== 다음 단계 결정 LLM 프롬프트 ===\n{llm_prompt_for_next_stage}\n=============================\n")
            try:
                response = await main_llm.ainvoke([HumanMessage(content=llm_prompt_for_next_stage)]) # JSON 출력 main_llm
                raw_content = response.content.strip()
                if raw_content.startswith("```json"): raw_content = raw_content.replace("```json", "").replace("```", "").strip()
                decision_data = next_stage_decision_parser.parse(raw_content) 
                determined_next_stage_id = decision_data.chosen_next_stage_id
                print(f"LLM 결정 다음 단계 ID: '{determined_next_stage_id}'")

                if determined_next_stage_id not in stages and \
                   determined_next_stage_id not in ["END_SCENARIO_COMPLETE", "END_SCENARIO_ABORT", "qa_listen"]: # qa_listen도 유효한 다음 단계
                    print(f"경고: LLM이 반환한 다음 단계 ID ('{determined_next_stage_id}')가 유효하지 않습니다. 기본 다음 단계를 사용합니다.")
                    determined_next_stage_id = current_stage_info.get("default_next_stage_id", current_stage_id)
            except Exception as e:
                print(f"다음 단계 결정 LLM 오류: {e}. LLM Raw: {getattr(response if 'response' in locals() else None, 'content', 'N/A')}. 기본 다음 단계 사용.")
                determined_next_stage_id = current_stage_info.get("default_next_stage_id", current_stage_id)
                if not determined_next_stage_id and current_stage_id not in ["END_SCENARIO_COMPLETE", "END_SCENARIO_ABORT", "qa_listen"]:
                     determined_next_stage_id = "END_SCENARIO_COMPLETE" if current_stage_id != "qa_listen" else current_stage_id
        
        # 결정된 다음 단계의 프롬프트를 가져와 final_response_text_for_user로 설정
        target_stage_info = stages.get(determined_next_stage_id, {})
        if determined_next_stage_id == "END_SCENARIO_COMPLETE":
            final_response_text_for_user = loan_scenario.get("end_scenario_message", "상담이 완료되었습니다. 감사합니다.")
        elif determined_next_stage_id == "END_SCENARIO_ABORT":
            final_response_text_for_user = target_stage_info.get("prompt", "상담이 중단되었습니다.")
        elif determined_next_stage_id == "qa_listen": # QA 리슨 상태로 가면, 특정 안내 메시지 후 사용자 질문 대기
            final_response_text_for_user = target_stage_info.get("prompt", "다른 궁금한 점이 있으시면 언제든지 말씀해주세요.")
        else: 
            final_response_text_for_user = target_stage_info.get("prompt", loan_scenario.get("fallback_message"))

        # Placeholder 치환
        if "%{" in final_response_text_for_user:
            import re
            def replace_placeholder(match): key = match.group(1); return str(collected_info.get(key, f"%{{{key}}}%")) 
            final_response_text_for_user = re.sub(r'%\{([^}]+)\}%', replace_placeholder, final_response_text_for_user)

    print(f"Main Agent 시나리오 처리 결과: 다음 사용자 안내 '{final_response_text_for_user[:50]}...', 다음 단계 ID '{determined_next_stage_id}'")
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=final_response_text_for_user)]
    
    return {
        **state, "collected_loan_info": collected_info, "current_scenario_stage_id": determined_next_stage_id,
        "final_response_text_for_tts": final_response_text_for_user, "messages": updated_messages,
        "is_final_turn_response": True # 이 노드가 응답을 결정하면 턴 종료 (스트리밍 시작 전)
    }

async def prepare_direct_response_node(state: AgentState) -> AgentState:
    print("--- 노드: 직접 응답 준비 (칫챗 등) ---")
    response_text = state.get("main_agent_direct_response") or state.get("loan_scenario_data", {}).get("fallback_message", "네, 말씀하세요.")
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=response_text)]
    return {**state, "final_response_text_for_tts": response_text, "messages": updated_messages, "is_final_turn_response": True}

async def prepare_fallback_response_node(state: AgentState) -> AgentState:
    print("--- 노드: 폴백 응답 준비 ---")
    response_text = state.get("error_message") or state.get("loan_scenario_data", {}).get("fallback_message", "죄송합니다, 잘 이해하지 못했습니다.")
    # error_message가 final_response_text_for_tts로 이미 설정되었을 수 있음 (라우터 등에서)
    # 이 노드에서는 명시적으로 한번 더 설정하여 일관성 유지
    updated_messages = list(state.get("messages", []))
    # 중복 메시지 방지
    if not updated_messages or not (isinstance(updated_messages[-1], AIMessage) and updated_messages[-1].content == response_text):
        updated_messages.append(AIMessage(content=response_text))
    return {**state, "final_response_text_for_tts": response_text, "messages": updated_messages, "is_final_turn_response": True}

async def prepare_end_conversation_node(state: AgentState) -> AgentState:
    print("--- 노드: 대화 종료 메시지 준비 ---")
    response_text = state.get("loan_scenario_data", {}).get("end_conversation_message", "상담을 종료합니다. 이용해주셔서 감사합니다.")
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=response_text)]
    return {**state, "final_response_text_for_tts": response_text, "messages": updated_messages, "is_final_turn_response": True}

async def handle_error_node(state: AgentState) -> AgentState:
    print("--- 노드: 에러 핸들링 ---")
    error_msg_for_user = state.get("error_message", "알 수 없는 오류가 발생했습니다. 죄송합니다.")
    updated_messages = list(state.get("messages", []))
    if not updated_messages or not (isinstance(updated_messages[-1], AIMessage) and updated_messages[-1].content == error_msg_for_user):
        updated_messages.append(AIMessage(content=error_msg_for_user))
    return {**state, "final_response_text_for_tts": error_msg_for_user, "is_final_turn_response": True, "messages": updated_messages}

# --- 조건부 엣지 로직 (TTS 노드 관련 부분 제거) ---
def route_from_entry(state: AgentState) -> str:
    if state.get("is_final_turn_response"): return END # is_final_turn_response가 설정되면 바로 종료
    if state.get("user_input_audio_b64"): return "stt_node"
    return "main_agent_router_node" 

def route_from_stt(state: AgentState) -> str:
    if state.get("is_final_turn_response"): return END # STT 에러 시
    return "main_agent_router_node"

def route_from_main_agent_router(state: AgentState) -> str:
    decision = state.get("main_agent_routing_decision")
    print(f"Main Agent 라우팅 결정: {decision}")
    if state.get("is_final_turn_response"): return END # 라우터에서 이미 턴 종료 결정 시 (예: 입력 오류)
    if decision == "invoke_scenario_agent": return "call_scenario_agent_node"
    if decision == "process_next_scenario_step": return "main_agent_scenario_processing_node"
    if decision == "invoke_qa_agent": return "call_qa_agent_node" # QA 스트리밍 시작 지점
    if decision == "answer_directly_chit_chat": return "prepare_direct_response_node"
    if decision == "end_conversation": return "prepare_end_conversation_node"
    # unclear_input 또는 알 수 없는 결정 -> fallback
    return "prepare_fallback_response_node"

def route_from_scenario_agent_call(state: AgentState) -> str:
    scenario_output = state.get("scenario_agent_output")
    if scenario_output and (scenario_output.get("intent") == "error_prompt_not_found" or \
                           scenario_output.get("intent") == "error_parsing_scenario_output" or \
                           scenario_output.get("intent") == "no_input"):
        err_msg = "답변 분석 중 내부 오류가 발생했습니다." if scenario_output.get("intent") != "no_input" else "분석할 사용자 입력이 없습니다."
        if "error_message" not in state or not state["error_message"]:
             state["error_message"] = err_msg
             state["final_response_text_for_tts"] = err_msg # 에러 메시지 설정
        return "handle_error_node"
    return "main_agent_scenario_processing_node"

# call_qa_agent_node 다음은 END. 스트리밍은 run_agent_streaming에서 이 라우팅 결정을 보고 처리.
def route_from_qa_agent_call(state: AgentState) -> str:
    print("QA Agent 호출 결정됨. 스트리밍은 외부(run_agent_streaming)에서 시작될 것임.")
    # 이 노드는 QA 스트리밍을 시작하라는 신호. 그래프 자체는 여기서 종료.
    # run_agent_streaming 함수가 이 상태를 보고 QA 스트리밍을 시작.
    return END


# --- 그래프 빌드 (TTS 노드 제거 및 엣지 수정) ---
workflow = StateGraph(AgentState)
nodes = [
    ("entry_point_node", entry_point_node), ("stt_node", stt_node),
    ("main_agent_router_node", main_agent_router_node),
    ("call_scenario_agent_node", call_scenario_agent_node),
    ("call_qa_agent_node", call_qa_agent_node), # QA 스트리밍 시작 신호용
    ("main_agent_scenario_processing_node", main_agent_scenario_processing_node),
    ("prepare_direct_response_node", prepare_direct_response_node),
    ("prepare_fallback_response_node", prepare_fallback_response_node),
    ("prepare_end_conversation_node", prepare_end_conversation_node),
    ("handle_error_node", handle_error_node)
]
for name, node_func in nodes: workflow.add_node(name, node_func)

workflow.set_entry_point("entry_point_node")

workflow.add_conditional_edges("entry_point_node", route_from_entry)
workflow.add_conditional_edges("stt_node", route_from_stt)
workflow.add_conditional_edges("main_agent_router_node", route_from_main_agent_router)
workflow.add_conditional_edges("call_scenario_agent_node", route_from_scenario_agent_call)
workflow.add_conditional_edges("call_qa_agent_node", route_from_qa_agent_call) # END로 연결

# 응답 준비 노드들은 모두 END로 연결 (is_final_turn_response=True 설정됨)
workflow.add_edge("main_agent_scenario_processing_node", END)
workflow.add_edge("prepare_direct_response_node", END)
workflow.add_edge("prepare_fallback_response_node", END)
workflow.add_edge("prepare_end_conversation_node", END)
workflow.add_edge("handle_error_node", END)

app_graph = workflow.compile()

# --- run_agent_streaming 함수 ---
async def run_agent_streaming(
    user_input_text: Optional[str] = None,
    user_input_audio_b64: Optional[str] = None,
    session_id: Optional[str] = "default_session", # 디버깅 및 로깅용
    current_state_dict: Optional[Dict[str, Any]] = None
) -> AsyncGenerator[Union[Dict[str, Any], str], None]:
    
    # 1. 초기 상태 설정
    scenario: Dict[str, Any]
    if current_state_dict and current_state_dict.get("loan_scenario_data"):
        scenario = current_state_dict["loan_scenario_data"]
    else:
        try: scenario = load_loan_scenario()
        except Exception as e:
            print(f"CRITICAL: 시나리오 로드 실패 (run_agent_streaming): {e}")
            yield {"type": "error", "session_id": session_id, "message": "상담 서비스 초기화에 실패했습니다. 잠시 후 다시 시도해주세요."}
            return

    initial_messages: List[BaseMessage] = ([SystemMessage(content=scenario.get("system_prompt", "당신은 친절한 대출 상담원입니다."))] 
                                         if not (current_state_dict and current_state_dict.get("messages")) 
                                         else list(current_state_dict["messages"]))

    initial_input_for_turn: AgentState = cast(AgentState, {
        "user_input_text": user_input_text, "user_input_audio_b64": user_input_audio_b64,
        "messages": initial_messages,
        "current_scenario_stage_id": (current_state_dict.get("current_scenario_stage_id", scenario.get("initial_stage_id", "greeting")) 
                                      if current_state_dict else scenario.get("initial_stage_id", "greeting")),
        "collected_loan_info": current_state_dict.get("collected_loan_info", {}) if current_state_dict else {},
        "loan_scenario_data": scenario,
        # 턴 시작 시 초기화되는 필드들
        "stt_result": None, "main_agent_routing_decision": None, "main_agent_direct_response": None,
        "scenario_agent_output": None, "qa_agent_output": None,
        "final_response_text_for_tts": None, "is_final_turn_response": False, "error_message": None,
    })
    
    # 2. LangGraph 실행
    print(f"\n--- [{session_id}] Agent Turn 시작 ---")
    print(f"초기 입력 상태 (요약): stage='{initial_input_for_turn['current_scenario_stage_id']}', text='{user_input_text}', audio_present={bool(user_input_audio_b64)}")

    try: # 전체 로직을 try로 감싸서 최종 상태 반환 보장
        graph_output_state: AgentState = await app_graph.ainvoke(initial_input_for_turn)
        
        print(f"LangGraph 실행 완료. 최종 결정된 다음 단계: '{graph_output_state.get('current_scenario_stage_id')}', 라우팅: '{graph_output_state.get('main_agent_routing_decision')}'")

        # 3. 스트리밍 결정 및 실행
        full_response_text_streamed = ""
        final_state_to_yield: Optional[AgentState] = None

        # Main Agent가 QA를 호출하도록 결정한 경우
        if graph_output_state.get("main_agent_routing_decision") == "invoke_qa_agent":
            user_question = graph_output_state.get("stt_result", "")
            if user_question: # STT 결과가 있어야 QA 가능
                scenario_name = graph_output_state.get("loan_scenario_data", {}).get("scenario_name", "디딤돌 대출")
                print(f"QA 스트리밍 시작 (세션: {session_id}, 질문: '{user_question[:50]}...')")
                
                yield {"type": "stream_start", "stream_type": "qa_answer"}
                async for chunk in invoke_qa_agent_streaming_logic(user_question, scenario_name):
                    yield chunk # 텍스트 청크 yield
                    full_response_text_streamed += chunk
                
                updated_messages_qa = list(graph_output_state.get("messages", [])) + [AIMessage(content=full_response_text_streamed)]
                final_state_to_yield = {
                    **graph_output_state, "final_response_text_for_tts": full_response_text_streamed,
                    "messages": updated_messages_qa, "is_final_turn_response": True, # QA 후 턴 종료
                    # QA의 경우, 다음 시나리오 단계는 보통 'qa_listen' 또는 현재 단계 유지
                    "current_scenario_stage_id": graph_output_state.get("loan_scenario_data",{}).get("stages",{}).get(graph_output_state.get("current_scenario_stage_id"),{}).get("qa_next_stage_id", graph_output_state.get("current_scenario_stage_id","qa_listen"))
                }
            else: # QA를 하려 했으나 STT 결과가 없는 경우 (예: 음성인식 실패)
                err_msg_qa_no_stt = graph_output_state.get("error_message") or "질문을 인식하지 못했습니다. 다시 질문해주시겠어요?"
                print(f"QA 스트리밍 불가 (세션: {session_id}): STT 결과 없음. 오류 메시지 전송.")
                yield {"type": "stream_start", "stream_type": "error_message"}
                for char_chunk in err_msg_qa_no_stt: yield char_chunk; await asyncio.sleep(0.01)
                full_response_text_streamed = err_msg_qa_no_stt
                final_state_to_yield = {
                    **graph_output_state, "final_response_text_for_tts": full_response_text_streamed,
                    "error_message": err_msg_qa_no_stt, "is_final_turn_response": True,
                    "messages": list(graph_output_state.get("messages", [])) + [AIMessage(content=full_response_text_streamed)]
                }

        # 그 외, 그래프가 최종 응답 텍스트를 생성한 경우 (시나리오 진행, 직접 답변, 폴백 등)
        elif graph_output_state.get("final_response_text_for_tts"):
            text_to_stream = graph_output_state["final_response_text_for_tts"]
            print(f"일반 응답 스트리밍 시작 (세션: {session_id}, 내용: '{text_to_stream[:50]}...')")
            
            yield {"type": "stream_start", "stream_type": "general_response"}
            # "가짜" 스트리밍: 전체 텍스트를 작은 청크로 나누어 보냄
            # (실제 토큰 스트리밍을 위해서는 main_agent_scenario_processing_node 등에서 streaming_llm.astream 사용 필요)
            chunk_size = 20 # 예: 20 글자씩 (실제로는 더 유동적으로 조절 가능)
            for i in range(0, len(text_to_stream), chunk_size):
                chunk = text_to_stream[i:i+chunk_size]
                yield chunk
                await asyncio.sleep(0.02) # 너무 빠르지 않게 조절
                full_response_text_streamed += chunk
            final_state_to_yield = graph_output_state # 상태는 이미 그래프에서 최종 결정됨

        # 응답할 텍스트가 없는 예외적인 경우 (그래프 오류 등)
        else:
            error_message_to_yield = graph_output_state.get("error_message", "응답을 생성하지 못했습니다. 죄송합니다.")
            print(f"응답 스트리밍 불가 (세션: {session_id}): 생성된 응답 텍스트 없음. 오류 메시지 전송.")
            yield {"type": "stream_start", "stream_type": "error_message"}
            for char_chunk in error_message_to_yield: yield char_chunk; await asyncio.sleep(0.01)
            full_response_text_streamed = error_message_to_yield
            final_state_to_yield = {
                **graph_output_state, "final_response_text_for_tts": full_response_text_streamed,
                "error_message": error_message_to_yield, "is_final_turn_response": True,
                "messages": list(graph_output_state.get("messages", [])) + [AIMessage(content=full_response_text_streamed)]
            }

        # 4. 스트리밍 완료 후, 최종 AgentState를 Dict 형태로 한번 더 yield
        yield {"type": "stream_end", "full_text": full_response_text_streamed}
        
        # 최종 상태에서 messages 필드가 BaseMessage 객체 리스트이므로, 필요시 직렬화
        # 예: final_state_to_yield["messages"] = [msg.dict() for msg in final_state_to_yield.get("messages", [])]
        # 여기서는 AgentState 타입 그대로 반환 (chat.py에서 필요시 처리)
        
        # TTS 관련 필드는 AgentState에 포함하지 않음 (chat.py에서 별도 처리)
        if final_state_to_yield and "tts_audio_b64" in final_state_to_yield:
            del final_state_to_yield["tts_audio_b64"]

        yield {"type": "final_state", "session_id": session_id, "data": final_state_to_yield}
        print(f"--- [{session_id}] Agent Turn 종료 (최종 텍스트 길이: {len(full_response_text_streamed)}) ---")

    except Exception as e:
        print(f"CRITICAL error in run_agent_streaming for session {session_id}: {e}")
        import traceback
        traceback.print_exc()
        error_response = f"죄송합니다, 에이전트 처리 중 심각한 오류가 발생했습니다: {e}"
        yield {"type": "stream_start", "stream_type": "critical_error"}
        for char_chunk in error_response: yield char_chunk; await asyncio.sleep(0.01)
        yield {"type": "stream_end", "full_text": error_response}
        
        # 예외 발생 시 최종 상태를 구성하여 반환
        final_state_to_yield = initial_input_for_turn.copy() # 초기 상태 기반으로 오류 상태 구성
        final_state_to_yield["error_message"] = error_response
        final_state_to_yield["final_response_text_for_tts"] = error_response
        final_state_to_yield["is_final_turn_response"] = True
        final_state_to_yield["messages"] = list(initial_input_for_turn.get("messages", [])) + [AIMessage(content=error_response)]

    finally:
        # TTS 관련 필드는 AgentState에 포함하지 않음 (chat.py에서 별도 처리)
        if final_state_to_yield and "tts_audio_b64" in final_state_to_yield:
            del final_state_to_yield["tts_audio_b64"]
        yield {"type": "final_state", "session_id": session_id, "data": final_state_to_yield}
        print(f"--- [{session_id}] Agent Turn 종료 (최종 텍스트 길이: {len(full_response_text_streamed if 'full_response_text_streamed' in locals() else '')}) ---")
