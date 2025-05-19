# backend/app/graph/agent.py

import base64
import json
import yaml # PyYAML 임포트
from pathlib import Path
from typing import Dict, Optional, Sequence, Literal, Any, List, Union # Union 추가

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field as PydanticField # Field 이름 충돌 방지

from .state import AgentState, ScenarioAgentOutput, QAAgentOutput
from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME
from ..services.google_services import transcribe_audio_bytes, synthesize_text_to_audio_bytes

# --- 경로 및 설정 ---
APP_DIR = Path(__file__).parent.parent
DATA_DIR = APP_DIR / "data"
CONFIG_DIR = APP_DIR / "config"
SCENARIO_FILE_PATH = DATA_DIR / "loan_scenario.json"

PROMPT_FILES = {
    'main_agent': CONFIG_DIR / "main_agent_prompts.yaml",
    'scenario_agent': CONFIG_DIR / "scenario_agent_prompts.yaml",
    'qa_agent': CONFIG_DIR / "qa_agent_prompts.yaml",
}

# --- LLM 초기화 ---
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
# Main Agent는 판단과 라우팅이 중요하므로 온도를 낮게, Specialist Agent는 창의성/요약 필요시 약간 높게 설정 가능
main_llm = ChatOpenAI(model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.1) # Main Agent용
specialist_llm = ChatOpenAI(model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.3) # Scenario/QA Agent용

# --- 프롬프트 로드 함수 ---
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

ALL_PROMPTS = load_all_prompts()

# --- 시나리오 로드 함수 (기존과 동일) ---
# ... (load_loan_scenario 함수 코드는 이전 답변과 동일하게 유지) ...
def load_loan_scenario() -> Dict:
    try:
        with open(SCENARIO_FILE_PATH, 'r', encoding='utf-8') as f:
            scenario = json.load(f)
        if not scenario:
            raise ValueError("시나리오 파일이 비어있습니다.")
        return scenario
    except FileNotFoundError:
        raise FileNotFoundError(f"시나리오 파일을 찾을 수 없습니다: {SCENARIO_FILE_PATH}")
    except json.JSONDecodeError:
        raise ValueError(f"시나리오 파일의 JSON 형식이 올바르지 않습니다: {SCENARIO_FILE_PATH}")
    except Exception as e:
        raise Exception(f"시나리오 파일 로드 중 오류 발생: {e}")


# --- Specialist Agent 로직 ---

class ScenarioOutputModel(BaseModel): # Pydantic 모델 이름 변경 (AgentState 내 필드명과 구분)
    intent: str = PydanticField(description="사용자 발화의 주요 의도 (예: '정보제공_연소득', '확인_긍정', '질문_대출한도')")
    entities: Dict[str, Any] = PydanticField(default_factory=dict, description="추출된 주요 개체 (예: {'income_amount': 6000, 'loan_type': '디딤돌'})")
    is_scenario_related: bool = PydanticField(description="현재 진행 중인 대출 시나리오와 관련된 발화인지 여부")
    user_sentiment: Optional[Literal['positive', 'negative', 'neutral']] = PydanticField(default='neutral', description="사용자 발화의 감정")

scenario_output_parser = PydanticOutputParser(pydantic_object=ScenarioOutputModel)

def format_messages_for_prompt(messages: Sequence[BaseMessage], max_history: int = 3) -> str:
    history_str = []
    # 최근 메시지부터 (System 메시지는 제외하고 AI-Human 순서로)
    relevant_messages = [m for m in messages if not isinstance(m, SystemMessage)][-max_history:]
    for msg in relevant_messages:
        role = "사용자" if isinstance(msg, HumanMessage) else "상담원"
        history_str.append(f"{role}: {msg.content}")
    return "\n".join(history_str) if history_str else "이전 대화 없음."

async def invoke_scenario_agent_logic(user_input: str, current_stage_prompt: str, expected_info_key: Optional[str], messages_history: Sequence[BaseMessage]) -> ScenarioAgentOutput:
    print(f"--- Scenario Agent 호출 (입력: '{user_input}') ---")
    prompt_template = ALL_PROMPTS.get('scenario_agent', {}).get('nlu_extraction', '')
    if not prompt_template:
        raise ValueError("Scenario Agent의 NLU 프롬프트를 찾을 수 없습니다.")

    formatted_history = format_messages_for_prompt(messages_history)
    formatted_prompt = prompt_template.format(
        current_stage_prompt=current_stage_prompt,
        expected_info_key=expected_info_key or "특정 정보 없음",
        formatted_messages_history=formatted_history,
        user_input=user_input,
        format_instructions=scenario_output_parser.get_format_instructions()
    )
    try:
        response = await specialist_llm.ainvoke([HumanMessage(content=formatted_prompt)])
        parsed_output_dict = scenario_output_parser.parse(response.content).model_dump()
        print(f"Scenario Agent 결과: {parsed_output_dict}")
        return parsed_output_dict # ScenarioAgentOutput 타입에 맞게 반환
    except Exception as e:
        print(f"Scenario Agent 처리 오류: {e}. LLM 응답: {getattr(e, 'llm_output', getattr(response, 'content', 'N/A'))}")
        # ScenarioAgentOutput 타입에 맞춰 오류 반환
        return {"intent": "error_parsing_scenario_output", "entities": {}, "is_scenario_related": False, "user_sentiment": "neutral"}


# QA Agent 관련 (기존과 유사, 프롬프트 로드 방식 변경)
QA_KNOWLEDGE_BASE_PATH = DATA_DIR / "didimdol.md" # didimdol.md 파일이 이 경로에 있어야 함
vector_store_cache = None

async def load_or_get_vector_store_async():
    global vector_store_cache
    if vector_store_cache is None:
        print("--- QA Agent: 지식베이스 로딩 중... ---")
        try:
            from langchain_community.document_loaders import UnstructuredMarkdownLoader # Markdown용 로더
            from langchain_text_splitters import RecursiveCharacterTextSplitter
            from langchain_openai import OpenAIEmbeddings
            from langchain_community.vectorstores import FAISS

            loader = UnstructuredMarkdownLoader(str(QA_KNOWLEDGE_BASE_PATH), mode="single")
            documents = await loader.aload()
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200) # overlap 증가
            texts = text_splitter.split_documents(documents)
            if not texts:
                raise ValueError("지식베이스에서 텍스트를 추출하지 못했습니다. 파일 내용을 확인하세요.")
            embeddings = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY)
            vector_store_cache = await FAISS.afrom_documents(texts, embeddings)
            print("--- QA Agent: 지식베이스 로딩 완료 ---")
        except Exception as e:
            print(f"QA 지식베이스 로딩 실패: {e}")
            vector_store_cache = "ERROR"
            # raise # 여기서 에러를 다시 raise하면 서버 시작이 안될 수 있으므로, 호출부에서 None 체크
    if vector_store_cache == "ERROR": # 로딩 실패 시 호출부에서 처리하도록 None 반환
        return None
    return vector_store_cache


async def invoke_qa_agent_logic(user_question: str) -> QAAgentOutput:
    print(f"--- QA Agent 호출 (질문: '{user_question}') ---")
    try:
        db = await load_or_get_vector_store_async()
        if db is None:
            return {"answer": "죄송합니다. 현재 대출 관련 정보를 조회할 수 없습니다. (지식베이스 오류)"}

        retriever = db.as_retriever(search_kwargs={"k": 3}) # 상위 3개 문서 검색
        retrieved_docs = await retriever.ainvoke(user_question)
        
        context_for_llm = "\n\n".join([f"문서 {i+1}:\n{doc.page_content}" for i, doc in enumerate(retrieved_docs)])
        if not retrieved_docs:
            context_for_llm = "참고할 만한 문서를 찾지 못했습니다."
            
        prompt_template = ALL_PROMPTS.get('qa_agent', {}).get('rag_answer_generation', '')
        if not prompt_template:
             raise ValueError("QA Agent의 RAG 프롬프트를 찾을 수 없습니다.")

        formatted_prompt = prompt_template.format(
            context_for_llm=context_for_llm,
            user_question=user_question
        )
        
        response = await specialist_llm.ainvoke([HumanMessage(content=formatted_prompt)])
        answer = response.content
        source_docs_summary = "; ".join([doc.page_content[:50]+"..." for doc in retrieved_docs]) if retrieved_docs else "없음"

        print(f"QA Agent 답변: {answer}, 참고 요약: {source_docs_summary}")
        return {"answer": answer, "retrieved_context_summary": source_docs_summary}
    except Exception as e:
        print(f"QA Agent 처리 오류: {e}")
        return {"answer": f"질문 답변 중 시스템 오류가 발생했습니다. 잠시 후 다시 시도해주세요."}


# --- LangGraph 노드 함수 정의 (Main Agent 역할) ---

async def entry_point_node(state: AgentState) -> AgentState:
    print("--- 노드: Entry Point ---")
    # run_agent에서 초기 상태를 잘 구성하여 전달한다고 가정
    # loan_scenario_data는 run_agent에서 주입됨
    scenario_data = state.get("loan_scenario_data", {})
    if not scenario_data: # 혹시 모를 경우 대비
        try:
            scenario_data = load_loan_scenario()
        except Exception as e:
            print(f"비상: 시나리오 로드 실패 (entry_point_node): {e}")
            return {
                **state, # 입력으로 들어온 user_input_text, user_input_audio_b64 등 유지
                "error_message": "시스템 설정 오류로 상담을 시작할 수 없습니다.",
                "final_response_text_for_tts": "시스템 설정 오류로 상담을 시작할 수 없습니다.",
                "is_final_turn_response": True
            }

    # 매 턴마다 초기화해야 할 상태 필드들 (user_input 관련 필드는 run_agent에서 설정)
    # 수정된 타입 힌트: Dict[str, Any] 또는 더 구체적인 타입
    turn_specific_defaults: Dict[str, Optional[Union[str, bool, dict, list]]] = {
        "stt_result": None,
        "main_agent_routing_decision": None,
        "main_agent_direct_response": None,
        "scenario_agent_output": None,
        "qa_agent_output": None,
        "final_response_text_for_tts": None,
        "tts_audio_b64": None,
        "is_final_turn_response": False,
        "error_message": None, # 이전 턴의 에러는 지움
    }
    # AgentState의 필드와 일치시키기 위해 Dict[str, Any] 대신 더 구체적으로 명시하거나,
    # 혹은 AgentState의 부분집합을 나타내는 별도 TypedDict(total=False)를 정의할 수도 있습니다.
    # 여기서는 해당 딕셔너리 리터럴의 값 타입을 반영하도록 수정했습니다.

    updated_state = {**state, **turn_specific_defaults} # 기존 상태에 덮어쓰기

    current_messages = list(updated_state.get("messages", []))

    # user_input_text, user_input_audio_b64는 run_agent에서 initial_input_for_turn에 이미 설정됨
    # 그리고 state를 통해 updated_state로 전달됨
    if updated_state.get("user_input_audio_b64"):
        print("입력 유형: 음성")
        # 다음 노드는 route_from_entry에서 stt_node로 결정
    elif updated_state.get("user_input_text"):
        print(f"입력 유형: 텍스트 ('{updated_state['user_input_text']}')")
        human_message_content = updated_state["user_input_text"]
        # 텍스트 입력 시 stt_result 설정 및 HumanMessage 추가
        # (stt_node를 거치지 않으므로 여기서 처리)
        updated_state["stt_result"] = human_message_content
        if not current_messages or not (isinstance(current_messages[-1], HumanMessage) and current_messages[-1].content == human_message_content):
             current_messages.append(HumanMessage(content=human_message_content))
        # 다음 노드는 route_from_entry에서 main_agent_router_node로 결정
    else:
        print("오류: 사용자 입력 없음 (entry_point_node)")
        updated_state["error_message"] = "사용자 입력(음성 또는 텍스트)이 없습니다."
        updated_state["final_response_text_for_tts"] = "사용자 입력이 없습니다."
        updated_state["is_final_turn_response"] = True # 바로 TTS로

    updated_state["messages"] = current_messages # 업데이트된 메시지 반영
    return updated_state


async def stt_node(state: AgentState) -> AgentState:
    print("--- 노드: STT ---")
    audio_b64 = state.get("user_input_audio_b64")
    if not audio_b64:
        # 이 경우는 entry_point에서 이미 걸러졌어야 하지만, 방어적으로 처리
        return {**state, "error_message": "STT 오류: 음성 데이터가 없습니다.", 
                "final_response_text_for_tts": "음성 데이터가 제공되지 않았습니다.", 
                "is_final_turn_response": True}
    try:
        audio_bytes = base64.b64decode(audio_b64)
        transcribed_text = await transcribe_audio_bytes(audio_bytes, sample_rate_hertz=16000) # TODO: 샘플레이트 설정
        
        if not transcribed_text and transcribed_text != "": # STT 실패 또는 빈 음성
            print("STT 결과: 변환된 텍스트 없음 (음성 인식 실패 가능성)")
            transcribed_text = "" # 빈 문자열로 다음 노드에서 처리
        
        print(f"STT 결과: '{transcribed_text}'")
        # messages는 Sequence[BaseMessage]이므로 list로 변환 후 HumanMessage 추가
        updated_messages = list(state.get("messages", [])) + [HumanMessage(content=transcribed_text)]
        return {**state, "stt_result": transcribed_text, "messages": updated_messages}
    except Exception as e:
        print(f"STT 처리 중 오류: {e}")
        return {**state, "error_message": f"음성 인식 중 오류가 발생했습니다: {e}", 
                "final_response_text_for_tts": "음성을 인식하는 중 문제가 발생했습니다.", 
                "is_final_turn_response": True}


async def main_agent_router_node(state: AgentState) -> AgentState:
    print("--- 노드: Main Agent Router ---")
    user_input = state.get("stt_result", "") # STT 결과 또는 텍스트 직접 입력 사용
    
    # 텍스트 입력이 stt_node를 거치지 않은 경우, messages에 HumanMessage가 누락될 수 있음.
    # entry_point_node 또는 run_agent에서 모든 사용자 입력을 HumanMessage로 messages에 추가하도록 일관성 유지 필요.
    # 여기서는 messages에 이미 최신 사용자 발화가 HumanMessage로 포함되어 있다고 가정.
    messages_history = state.get("messages", [])
    if not messages_history or not isinstance(messages_history[-1], HumanMessage):
        # 가장 최근 메시지가 HumanMessage가 아니면 (예: STT 결과가 비었거나 시스템 오류)
        # user_input을 기준으로 임시 HumanMessage를 만들어 프롬프트에 사용하거나, 에러 처리
        if user_input: # user_input이라도 있으면 사용
             messages_history = list(messages_history) + [HumanMessage(content=user_input)]
        else: # stt_result도 비어있으면 판단 불가
            print("Main Agent Router: 판단할 사용자 입력이 없습니다.")
            return {**state, "main_agent_routing_decision": "unclear_input", "error_message": "사용자 입력 분석 불가"}


    current_stage_id = state.get("current_scenario_stage_id", "greeting")
    loan_scenario = state.get("loan_scenario_data", {})
    current_stage_info = loan_scenario.get("stages", {}).get(current_stage_id, {})
    
    prompt_template = ALL_PROMPTS.get('main_agent', {}).get('router_prompt', '')
    if not prompt_template:
        raise ValueError("Main Agent의 router 프롬프트를 찾을 수 없습니다.")

    formatted_history = format_messages_for_prompt(messages_history)
    
    # QA 키워드 예시를 동적으로 채우기
    qa_keywords_list = loan_scenario.get("qa_keywords", ["궁금"])
    qa_keywords_example_str = qa_keywords_list[0] if qa_keywords_list else "질문"


    try:
        main_agent_prompt_filled = prompt_template.format(
            user_input=user_input,
            formatted_messages_history=formatted_history,
            current_scenario_stage_id=current_stage_id,
            current_stage_prompt=current_stage_info.get("prompt", "정보 없음"),
            collected_loan_info=str(state.get("collected_loan_info", {})), # dict를 문자열로
            scenario_name=loan_scenario.get("scenario_name", "대출 상담"),
            expected_info_key=current_stage_info.get("expected_info_key", "정보 없음"),
            qa_keywords_example=qa_keywords_example_str
        )
        
        response = await main_llm.ainvoke([HumanMessage(content=main_agent_prompt_filled)])
        
        # LLM 응답이 JSON 문자열이라고 가정. 실제로는 더 견고한 파싱 필요.
        # 예: ```json\n{...}\n``` 와 같은 마크다운 코드 블록 제거 등
        raw_response_content = response.content.strip()
        if raw_response_content.startswith("```json"):
            raw_response_content = raw_response_content.replace("```json", "").replace("```", "").strip()
        
        decision_data = json.loads(raw_response_content)
        routing_decision = decision_data.get("action")
        direct_response = decision_data.get("direct_response")
        extracted_value = decision_data.get("extracted_value") # for process_scenario_info_directly

        print(f"Main Agent 결정: {routing_decision}, 직접 답변: {direct_response}, 추출값: {extracted_value}")
        
        # "process_scenario_info_directly"의 경우, ScenarioAgentOutput과 유사한 구조로 상태 업데이트
        scenario_agent_output_direct = None
        if routing_decision == "process_scenario_info_directly" and extracted_value is not None:
            # expected_info_key를 찾아 해당 키로 저장
            key_to_collect = current_stage_info.get("expected_info_key")
            entities_direct = {key_to_collect: extracted_value} if key_to_collect else {}
            scenario_agent_output_direct = {
                "intent": f"direct_confirm_{extracted_value.lower()}", # 예시 인텐트
                "entities": entities_direct,
                "is_scenario_related": True,
                "user_sentiment": "neutral" # 단순화
            }

        return {
            **state,
            "main_agent_routing_decision": routing_decision,
            "main_agent_direct_response": direct_response,
            # "process_scenario_info_directly" 시에는 scenario_agent_output을 채워 다음 로직 재활용
            "scenario_agent_output": scenario_agent_output_direct if scenario_agent_output_direct else state.get("scenario_agent_output")
        }
    except json.JSONDecodeError as je:
        raw_content = getattr(response, 'content', 'N/A (응답 객체 없음)')
        print(f"Main Agent Router JSON 파싱 오류: {je}. LLM 응답: {raw_content}")
        return {**state, "error_message": "메인 에이전트 판단 결과 파싱 오류입니다. 다시 시도해주세요.", "main_agent_routing_decision": "unclear_input"}
    except Exception as e:
        print(f"Main Agent Router 시스템 오류: {e}")
        import traceback
        traceback.print_exc()
        return {**state, "error_message": "메인 에이전트 판단 중 시스템 오류가 발생했습니다.", "main_agent_routing_decision": "unclear_input"}

# call_scenario_agent_node, call_qa_agent_node는 Specialist Agent 호출 로직 (이전과 유사, 프롬프트 포맷팅 주의)
async def call_scenario_agent_node(state: AgentState) -> AgentState:
    print("--- 노드: Scenario Agent 호출 ---")
    user_input = state.get("stt_result", "")
    current_stage_id = state.get("current_scenario_stage_id", "greeting")
    current_stage_info = state.get("loan_scenario_data", {}).get("stages", {}).get(current_stage_id, {})
    current_stage_prompt = current_stage_info.get("prompt", "")
    expected_info_key = current_stage_info.get("expected_info_key")
    messages_history = state.get("messages", [])
    
    output = await invoke_scenario_agent_logic(user_input, current_stage_prompt, expected_info_key, messages_history)
    return {**state, "scenario_agent_output": output}

async def call_qa_agent_node(state: AgentState) -> AgentState:
    print("--- 노드: QA Agent 호출 ---")
    user_question = state.get("stt_result", "")
    output = await invoke_qa_agent_logic(user_question)
    return {**state, "qa_agent_output": output}


# Main Agent가 Scenario Agent 결과 또는 직접 판단한 정보를 바탕으로 시나리오 진행
async def main_agent_scenario_processing_node(state: AgentState) -> AgentState:
    print("--- 노드: Main Agent 시나리오 처리 ---")
    scenario_output = state.get("scenario_agent_output") # invoke_scenario_agent 또는 main_router에서 직접 설정 가능
    user_answer_for_transition = state.get("stt_result","") # 또는 scenario_output의 특정 필드 사용

    current_stage_id = state.get("current_scenario_stage_id", "greeting")
    loan_scenario = state.get("loan_scenario_data", {})
    stages = loan_scenario.get("stages", {})
    current_stage_info = stages.get(current_stage_id, {})
    collected_info = state.get("collected_loan_info", {}).copy()

    final_response_text = loan_scenario.get("fallback_message")
    next_stage_id_for_user = current_stage_id # 기본값: 현재 스테이지 유지

    if scenario_output and scenario_output.get("is_scenario_related"):
        extracted_entities = scenario_output.get("entities", {})
        
        # Scenario Agent가 추출한 정보 업데이트
        # expected_info_key가 있다면 해당 정보 우선 적용
        key_to_collect = current_stage_info.get("expected_info_key")
        if key_to_collect and key_to_collect in extracted_entities and extracted_entities[key_to_collect] is not None:
            collected_info[key_to_collect] = extracted_entities[key_to_collect]
            print(f"정보 업데이트 (Scenario Agent - expected): {key_to_collect} = {extracted_entities[key_to_collect]}")
        # 그 외 entities도 업데이트 (예: 사용자가 한 번에 여러 정보 제공 시)
        for key, value in extracted_entities.items():
            if key != key_to_collect and value is not None: # 중복 방지 및 유효값
                 collected_info[key] = value
                 print(f"추가 정보 업데이트 (Scenario Agent): {key} = {value}")
        
        # 다음 단계 결정 (loan_scenario.json의 transitions 활용)
        # TODO: Scenario Agent의 'intent'를 사용하여 keyword 매칭보다 정교하게 개선
        found_transition = False
        user_response_for_keyword_match = user_answer_for_transition.lower() # 키워드 매칭용
        # 또는 scenario_output.get("intent")에서 키워드를 추출하거나, 직접적인 의도를 사용할 수 있음

        if "transitions" in current_stage_info:
            for transition in current_stage_info["transitions"]:
                if any(keyword.lower() in user_response_for_keyword_match for keyword in transition.get("keywords", [])):
                    next_stage_id_for_user = transition["next_stage_id"]
                    found_transition = True
                    break
            if not found_transition and current_stage_info.get("default_next_stage_id"): # 매칭 실패 시 기본
                next_stage_id_for_user = current_stage_info["default_next_stage_id"]
        elif current_stage_info.get("default_next_stage_id"): # transitions 없고 default만 있는 경우
             next_stage_id_for_user = current_stage_info["default_next_stage_id"]
        else: # 다음 단계 정의가 없는 경우 (시나리오 오류 또는 마지막 단계)
            if current_stage_id != "END_SCENARIO_COMPLETE" and current_stage_id != "END_SCENARIO_ABORT":
                 print(f"경고: 현재 단계({current_stage_id})에서 다음 단계 정의를 찾을 수 없습니다. 시나리오 종료로 간주합니다.")
                 next_stage_id_for_user = "END_SCENARIO_COMPLETE" # 또는 에러 처리

    else: # is_scenario_related가 false이거나 scenario_output이 없는 경우
        # 이 경우는 Main Agent Router에서 이미 다른 경로(unclear, chit_chat 등)로 처리했어야 함.
        # 만약 이 노드로 잘못 라우팅 되었다면, fallback 또는 에러 처리.
        print(f"경고: 시나리오 처리 노드에 부적절한 상태로 진입 (is_scenario_related: {scenario_output.get('is_scenario_related') if scenario_output else 'N/A'}). 폴백 메시지를 사용합니다.")
        # next_stage_id_for_user는 현재 스테이지 유지 또는 fallback stage로 이동
    
    # 다음 사용자에게 보여줄 프롬프트 생성
    target_stage_info = stages.get(next_stage_id_for_user, {})
    if next_stage_id_for_user == "END_SCENARIO_COMPLETE":
        final_response_text = loan_scenario.get("end_scenario_message", "상담이 완료되었습니다.")
    elif next_stage_id_for_user == "END_SCENARIO_ABORT":
        final_response_text = target_stage_info.get("prompt", "상담이 중단되었습니다.") # farewell_early의 prompt
    else:
        final_response_text = target_stage_info.get("prompt", loan_scenario.get("fallback_message"))

    # 프롬프트 내 플레이스홀더 치환
    if "%{" in final_response_text: # %{key}% 형식만 치환
        import re
        # collected_info에 있는 값으로 치환, 없으면 플레이스홀더 그대로 남김 (LLM이 처리하거나, UI에서 빈칸으로 보일 수 있음)
        def replace_placeholder(match):
            key = match.group(1)
            return str(collected_info.get(key, f"%{{{key}}}%")) # 키가 없으면 플레이스홀더 유지
        final_response_text = re.sub(r'%\{([^}]+)\}%', replace_placeholder, final_response_text)


    print(f"Main Agent 시나리오 처리 결과: 다음 사용자 안내는 '{final_response_text[:50]}...', 다음 단계 ID는 '{next_stage_id_for_user}'")
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=final_response_text)]
    return {
        **state,
        "collected_loan_info": collected_info,
        "current_scenario_stage_id": next_stage_id_for_user,
        "final_response_text_for_tts": final_response_text,
        "messages": updated_messages
    }


# prepare_qa_response_node, prepare_direct_response_node 등은 이전과 유사 (AIMessage 추가 로직 일관성 있게)
async def prepare_qa_response_node(state: AgentState) -> AgentState:
    print("--- 노드: QA 응답 준비 ---")
    qa_output = state.get("qa_agent_output")
    response_text = qa_output.get("answer") if qa_output else "죄송합니다, 질문에 대한 답변을 찾지 못했습니다."
    return {**state, "final_response_text_for_tts": response_text, "messages": state["messages"] + [AIMessage(content=response_text)]}

async def prepare_direct_response_node(state: AgentState) -> AgentState:
    print("--- 노드: 직접 응답 준비 (칫챗 등) ---")
    response_text = state.get("main_agent_direct_response") or \
                    state.get("loan_scenario_data", {}).get("fallback_message", "네, 말씀하세요.")
    return {**state, "final_response_text_for_tts": response_text, "messages": state["messages"] + [AIMessage(content=response_text)]}

async def prepare_fallback_response_node(state: AgentState) -> AgentState:
    print("--- 노드: 폴백 응답 준비 ---")
    response_text = state.get("error_message") or \
                    state.get("loan_scenario_data", {}).get("fallback_message", "죄송합니다, 잘 이해하지 못했습니다.")
    return {**state, "final_response_text_for_tts": response_text, "messages": state["messages"] + [AIMessage(content=response_text)]}

async def prepare_end_conversation_node(state: AgentState) -> AgentState:
    print("--- 노드: 대화 종료 메시지 준비 ---")
    response_text = state.get("loan_scenario_data", {}).get("end_conversation_message", "상담을 종료합니다.")
    return {**state, "final_response_text_for_tts": response_text, "messages": state["messages"] + [AIMessage(content=response_text)]}

# tts_node, handle_error_node는 이전과 유사 (AIMessage 추가 로직 일관성 있게)
async def tts_node(state: AgentState) -> AgentState:
    print("--- 노드: TTS ---")
    text_to_speak = state.get("final_response_text_for_tts")
    
    if not text_to_speak:
        print("경고: TTS 노드에 전달된 텍스트가 없습니다. 폴백 메시지를 사용합니다.")
        text_to_speak = state.get("loan_scenario_data", {}).get("fallback_message", "음성 답변을 준비하지 못했습니다.")
        # messages는 이전 노드에서 이미 AIMessage가 추가되었을 것으로 기대

    try:
        audio_bytes = await synthesize_text_to_audio_bytes(text_to_speak)
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        print(f"TTS 변환 완료 (텍스트: '{text_to_speak[:30]}...')")
        return {**state, "tts_audio_b64": audio_b64, "is_final_turn_response": True}
    except Exception as e:
        print(f"TTS 변환 중 오류: {e}")
        return {**state, "error_message": f"음성 변환 중 오류: {e}. 텍스트로 답변합니다.", 
                "final_response_text_for_tts": text_to_speak, # TTS 실패해도 텍스트는 유지
                "is_final_turn_response": True}


async def handle_error_node(state: AgentState) -> AgentState:
    print("--- 노드: 에러 핸들링 ---")
    error_msg_for_user = state.get("error_message", "알 수 없는 오류가 발생했습니다. 죄송합니다.")
    updated_messages = list(state.get("messages", []))
    if not updated_messages or not (isinstance(updated_messages[-1], AIMessage) and updated_messages[-1].content == error_msg_for_user):
        updated_messages.append(AIMessage(content=error_msg_for_user))
    
    return {**state, "final_response_text_for_tts": error_msg_for_user, 
            "is_final_turn_response": True, "messages": updated_messages}

# --- 조건부 엣지 로직 (Multi-Agent 구조에 맞게) ---
def route_from_entry(state: AgentState) -> str:
    if state.get("is_final_turn_response"): return "tts_node"
    if state.get("user_input_audio_b64"): return "stt_node"
    return "main_agent_router_node"

def route_from_stt(state: AgentState) -> str:
    if state.get("is_final_turn_response"): return "tts_node"
    # STT 결과가 비어있더라도 Main Agent Router가 판단하도록 넘김
    # if not state.get("stt_result", "").strip():
    #     state["main_agent_routing_decision"] = "unclear_input" # STT 결과 없으면 불분명 처리
    return "main_agent_router_node"

def route_from_main_agent_router(state: AgentState) -> str:
    decision = state.get("main_agent_routing_decision")
    print(f"Main Agent 라우팅 결정: {decision}")

    if state.get("error_message") and decision != "unclear_input": # 라우터 내부에서 명시적 에러가 아닌 일반 에러 발생 시
        return "handle_error_node"

    if decision == "invoke_scenario_agent": return "call_scenario_agent_node"
    if decision == "process_scenario_info_directly": return "main_agent_scenario_processing_node" # Scenario Agent Output이 이미 채워져 있음
    if decision == "invoke_qa_agent": return "call_qa_agent_node"
    if decision == "answer_directly_chit_chat": return "prepare_direct_response_node"
    if decision == "end_conversation": return "prepare_end_conversation_node"
    if decision == "unclear_input": return "prepare_fallback_response_node"
    
    print(f"경고: 알 수 없는 Main Agent 라우팅 결정값 '{decision}'. 폴백 처리합니다.")
    return "prepare_fallback_response_node" # 정의되지 않은 decision은 폴백으로

def route_from_scenario_agent_call(state: AgentState) -> str:
    scenario_output = state.get("scenario_agent_output", {})
    if scenario_output.get("intent") == "unknown_error" or scenario_output.get("intent") == "error_parsing_scenario_output":
        print("Scenario Agent 오류 감지, 에러 핸들링으로 라우팅")
        # state["error_message"] = scenario_output.get("error_message", "시나리오 분석 중 오류 발생") # 필요시 에러 메시지 설정
        return "handle_error_node" # 또는 "prepare_fallback_response_node"
    return "main_agent_scenario_processing_node"

def route_from_qa_agent_call(state: AgentState) -> str:
    qa_output = state.get("qa_agent_output",{})
    if "오류" in qa_output.get("answer","") or not qa_output.get("answer"): # QA Agent 답변 생성 실패
        print("QA Agent 오류 또는 답변 없음 감지, 폴백/에러 핸들링으로 라우팅")
        # state["error_message"] = qa_output.get("answer") # QA Agent가 반환한 에러 메시지 사용
        return "prepare_fallback_response_node" # QA 실패 시 간단한 폴백
    return "prepare_qa_response_node"

# --- 그래프 빌드 (동일) ---
# (이전 답변의 그래프 빌드 코드와 동일하게 유지)
workflow = StateGraph(AgentState)

workflow.add_node("entry_point_node", entry_point_node)
workflow.add_node("stt_node", stt_node)
workflow.add_node("main_agent_router_node", main_agent_router_node)
workflow.add_node("call_scenario_agent_node", call_scenario_agent_node)
workflow.add_node("call_qa_agent_node", call_qa_agent_node)
workflow.add_node("main_agent_scenario_processing_node", main_agent_scenario_processing_node)
workflow.add_node("prepare_qa_response_node", prepare_qa_response_node)
workflow.add_node("prepare_direct_response_node", prepare_direct_response_node)
workflow.add_node("prepare_fallback_response_node", prepare_fallback_response_node)
workflow.add_node("prepare_end_conversation_node", prepare_end_conversation_node)
workflow.add_node("tts_node", tts_node)
workflow.add_node("handle_error_node", handle_error_node)

workflow.set_entry_point("entry_point_node")

workflow.add_conditional_edges("entry_point_node", route_from_entry)
workflow.add_conditional_edges("stt_node", route_from_stt)
workflow.add_conditional_edges("main_agent_router_node", route_from_main_agent_router)
workflow.add_conditional_edges("call_scenario_agent_node", route_from_scenario_agent_call)
workflow.add_conditional_edges("call_qa_agent_node", route_from_qa_agent_call)

workflow.add_edge("main_agent_scenario_processing_node", "tts_node")
workflow.add_edge("prepare_qa_response_node", "tts_node")
workflow.add_edge("prepare_direct_response_node", "tts_node")
workflow.add_edge("prepare_fallback_response_node", "tts_node")
workflow.add_edge("prepare_end_conversation_node", "tts_node")
workflow.add_edge("handle_error_node", "tts_node")
workflow.add_edge("tts_node", END)

app_graph = workflow.compile()
# from langgraph.checkpoint.sqlite import SqliteSaver # 예시
# memory = SqliteSaver.from_conn_string(":memory:") # 인메모리 SQLite
# app_graph = workflow.compile(checkpointer=memory)


# --- run_agent 함수 (기존 Multi-Agent 버전에서 AgentState 초기화 부분 강화) ---
async def run_agent(
    user_input_text: Optional[str] = None,
    user_input_audio_b64: Optional[str] = None,
    session_id: Optional[str] = "default_session", # 세션 ID 추가
    current_state_dict: Optional[Dict] = None # 이전 AgentState 전체 또는 일부
) -> AgentState:
    
    # scenario_data는 한 번 로드 후 상태를 통해 계속 전달되거나, checkpointer 사용 시 자동으로 관리됨
    # 여기서는 current_state_dict에 없으면 새로 로드하는 방식 유지
    if current_state_dict and "loan_scenario_data" in current_state_dict and current_state_dict["loan_scenario_data"]:
        scenario = current_state_dict["loan_scenario_data"]
    else:
        scenario = load_loan_scenario() # 최초 또는 상태 없을 때 로드

    if current_state_dict:
        # 이전 상태에서 필요한 핵심 정보(messages, stage, collected_info)를 가져와서 이번 턴의 입력과 합침
        initial_input_for_turn: AgentState = {
            "messages": current_state_dict.get("messages", [SystemMessage(content=scenario.get("system_prompt", "당신은 친절한 대출 상담원입니다."))]),
            "current_scenario_stage_id": current_state_dict.get("current_scenario_stage_id", scenario.get("initial_stage_id", "greeting")),
            "collected_loan_info": current_state_dict.get("collected_loan_info", {}),
            "loan_scenario_data": scenario, # 로드된 시나리오 데이터
            
            "user_input_text": user_input_text, # 이번 턴의 사용자 입력
            "user_input_audio_b64": user_input_audio_b64, # 이번 턴의 사용자 입력

            # 매 턴 초기화되어야 하는 필드들
            "stt_result": None,
            "main_agent_routing_decision": None,
            "main_agent_direct_response": None,
            "scenario_agent_output": None,
            "qa_agent_output": None,
            "final_response_text_for_tts": None,
            "tts_audio_b64": None,
            "is_final_turn_response": False,
            "error_message": None,
        }
    else: # 첫 턴일 경우
        initial_input_for_turn: AgentState = {
            "user_input_text": user_input_text,
            "user_input_audio_b64": user_input_audio_b64,
            "messages": [SystemMessage(content=scenario.get("system_prompt", "당신은 친절한 대출 상담원입니다."))],
            "current_scenario_stage_id": scenario.get("initial_stage_id", "greeting"),
            "collected_loan_info": {},
            "loan_scenario_data": scenario,
            "stt_result": None, "main_agent_routing_decision": None, "main_agent_direct_response": None,
            "scenario_agent_output": None, "qa_agent_output": None,
            "final_response_text_for_tts": None, "tts_audio_b64": None,
            "is_final_turn_response": False, "error_message": None,
        }
    
    # 사용자 입력을 HumanMessage로 messages 리스트에 추가 (STT 노드에서 음성 입력을 처리하므로, 여기서는 텍스트 입력만 명시적으로 추가)
    # STT 노드에서도 HumanMessage를 추가하므로 중복될 수 있음. 일관성 있는 처리 필요.
    # -> entry_point_node에서 텍스트 입력 시 stt_result 설정, stt_node에서 음성 입력 STT 후 stt_result 설정.
    # -> main_agent_router_node가 stt_result를 보고 HumanMessage를 messages에 추가하는 것이 더 깔끔할 수 있음.
    # 또는, stt_node에서 HumanMessage를 추가하고, 텍스트 입력은 entry_point에서 stt_result와 messages에 HumanMessage를 추가. (현재 entry_point, stt_node 코드 반영)

    # config = {"configurable": {"session_id": session_id}} # checkpointer 사용 시
    # final_state = await app_graph.ainvoke(initial_input_for_turn, config=config)
    final_state = await app_graph.ainvoke(initial_input_for_turn) # type: ignore
    return final_state # type: ignore