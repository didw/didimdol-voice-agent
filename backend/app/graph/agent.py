import base64
import json
from pathlib import Path
# from typing import List, Dict, TypedDict, Optional, Sequence, Literal

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from typing import List, Dict, TypedDict, Optional, Sequence, Literal # 여기서 Literal 등 필요 타입만 남기거나 삭제
# from langchain_core.messages import BaseMessage # 이미 state.py에 정의됨

from .state import AgentState # AgentState를 state.py에서 임포트

# --- 프로젝트 경로 설정 ---
# 이 agent.py 파일의 위치를 기준으로 backend/app/data/loan_scenario.json 경로를 찾습니다.
# agent.py는 backend/app/graph/agent.py 에 위치합니다.
# 따라서 ../data/loan_scenario.json 이 됩니다.
APP_DIR = Path(__file__).parent.parent # backend/app/
DATA_DIR = APP_DIR / "data"
SCENARIO_FILE_PATH = DATA_DIR / "loan_scenario.json"

# --- 서비스 및 설정 로드 ---
from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME
from ..services.google_services import transcribe_audio_bytes, synthesize_text_to_audio_bytes

# --- LLM 초기화 (LangChain 사용) ---
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

llm = ChatOpenAI(model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.7)

# --- 대출 시나리오 로드 함수 ---
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


# --- LangGraph 노드 함수 정의 ---

async def entry_point_node(state: AgentState) -> AgentState:
    """
    대화 시작점. 사용자 입력을 확인하고 초기 상태를 설정합니다.
    """
    print("--- 노드: entry_point_node ---")
    try:
        scenario_data = load_loan_scenario()
    except Exception as e:
        print(f"시나리오 로드 실패: {e}")
        return {
            **state,
            "error_message": f"시스템 설정 오류: 대출 시나리오 정보를 불러올 수 없습니다. ({e})",
            "next_node_override": "handle_error_node" # 에러 핸들링 노드로 바로 이동
        }

    updated_state = {
        **state,
        "loan_scenario_data": scenario_data,
        "current_scenario_stage_id": state.get("current_scenario_stage_id") or scenario_data.get("initial_stage_id", "greeting"), # 세션에서 이어받거나 초기 단계
        "collected_loan_info": state.get("collected_loan_info", {}),
        "messages": state.get("messages", [SystemMessage(content=scenario_data.get("system_prompt", "당신은 친절한 대출 상담원입니다."))]),
        "is_final_turn_response": False,
        "error_message": None,
        "next_node_override": None
    }

    if updated_state["user_input_audio_b64"]:
        print("입력 유형: 음성")
        updated_state["next_node_override"] = "stt_node"
    elif updated_state["user_input_text"]:
        print(f"입력 유형: 텍스트 ('{updated_state['user_input_text']}')")
        # 텍스트 입력은 바로 stt_result로 간주하고 HumanMessage 추가
        human_message_content = updated_state["user_input_text"]
        updated_state["stt_result"] = human_message_content
        updated_state["messages"] = list(updated_state["messages"]) + [HumanMessage(content=human_message_content)]
        updated_state["next_node_override"] = "intent_classification_node"
    else:
        print("오류: 사용자 입력 없음")
        updated_state["error_message"] = "사용자 입력(음성 또는 텍스트)이 없습니다."
        updated_state["next_node_override"] = "handle_error_node"

    return updated_state


async def stt_node(state: AgentState) -> AgentState:
    """
    음성 입력을 텍스트로 변환합니다 (Google STT 사용).
    """
    print("--- 노드: stt_node ---")
    audio_b64 = state.get("user_input_audio_b64")
    if not audio_b64:
        return {**state, "error_message": "STT 오류: 음성 데이터가 없습니다.", "next_node_override": "handle_error_node"}

    try:
        audio_bytes = base64.b64decode(audio_b64)
        # 실제 프론트엔드에서 전송하는 오디오의 sample_rate_hertz를 알아야 합니다.
        # 예시: 16000 Hz 또는 48000 Hz
        transcribed_text = await transcribe_audio_bytes(audio_bytes, sample_rate_hertz=16000) # TODO: 실제 샘플레이트 확인
        if not transcribed_text:
            print("STT 결과: 변환된 텍스트 없음 (음성 인식 실패 가능성)")
            # 빈 텍스트도 다음 노드로 넘겨서 LLM이 "잘 못들었습니다" 등으로 처리하도록 유도 가능
            transcribed_text = "" # 또는 특정 메시지 "음성을 인식하지 못했습니다."

        print(f"STT 결과: '{transcribed_text}'")
        return {
            **state,
            "stt_result": transcribed_text,
            "messages": state["messages"] + [HumanMessage(content=transcribed_text)],
            "next_node_override": "intent_classification_node"
        }
    except Exception as e:
        print(f"STT 처리 중 오류: {e}")
        return {**state, "error_message": f"음성 인식 중 오류가 발생했습니다: {e}", "next_node_override": "handle_error_node"}


async def intent_classification_node(state: AgentState) -> AgentState:
    """
    사용자 발화(stt_result)의 의도를 파악합니다 (LLM 또는 규칙 기반).
    (시나리오 답변, Q&A, 칫챗, 종료 등)
    """
    print("--- 노드: intent_classification_node ---")
    user_text = state.get("stt_result", "")
    # messages_history = state.get("messages", [])
    current_stage_id = state.get("current_scenario_stage_id", "greeting")
    scenario_data = state.get("loan_scenario_data", {})
    stages = scenario_data.get("stages", {})
    current_stage_info = stages.get(current_stage_id, {})

    # TODO: 정교한 의도 분류 로직 구현 (LLM 사용 가능)
    # 예시: 키워드 기반 또는 간단한 LLM 프롬프트
    # For now, assume it's a scenario answer if there's an active question
    # or try to match keywords for QA/chit-chat
    intent: Literal["scenario_answer", "qa_question", "chit_chat", "end_conversation", "unclear"]

    if "종료" in user_text or "그만" in user_text:
        intent = "end_conversation"
    elif current_stage_info.get("is_question"): # 현재 단계가 질문을 던지는 단계라면, 사용자의 답변으로 간주
        intent = "scenario_answer"
    elif any(kw in user_text.lower() for kw in scenario_data.get("qa_keywords", ["궁금", "질문", "알려줘"])):
        intent = "qa_question"
    elif len(user_text.split()) < 4 and user_text: # 짧은 문장은 칫챗으로 간주 (매우 단순한 기준)
        intent = "chit_chat"
    elif not user_text and user_text != "": # STT 결과가 명시적으로 빈 문자열이 아니고 None 등인 경우
        intent = "unclear" # STT 실패 등으로 텍스트가 없는 경우
    else: # 기본적으로 시나리오 답변으로 처리 시도
        intent = "scenario_answer"


    print(f"분류된 의도: {intent} (사용자 발화: '{user_text}')")
    return {**state, "intent": intent}


async def scenario_logic_node(state: AgentState) -> AgentState:
    """
    분류된 의도가 'scenario_answer'일 때, 시나리오 정의에 따라 사용자 답변을 처리하고
    다음 단계를 결정하거나 정보를 수집합니다. LLM 프롬프트를 준비합니다.
    """
    print("--- 노드: scenario_logic_node ---")
    user_answer = state.get("stt_result", "")
    current_stage_id = state.get("current_scenario_stage_id")
    scenario_data = state.get("loan_scenario_data")
    stages = scenario_data.get("stages", {})
    current_stage_info = stages.get(current_stage_id, {})
    collected_info = state.get("collected_loan_info", {}).copy()

    next_stage_id = current_stage_id # 기본적으로 현재 단계 유지
    llm_prompt = ""

    if current_stage_info.get("expected_info_key"): # 현재 단계에서 정보 수집이 필요한 경우
        collected_info[current_stage_info["expected_info_key"]] = user_answer
        print(f"정보 수집: {current_stage_info['expected_info_key']} = '{user_answer}'")

    # 다음 단계 결정 로직 (시나리오 JSON의 transitions 활용)
    # TODO: 더 정교한 transition 로직 (LLM 사용하여 사용자 답변과 keyword 매칭 등)
    found_transition = False
    if "transitions" in current_stage_info:
        for transition in current_stage_info["transitions"]:
            if any(keyword.lower() in user_answer.lower() for keyword in transition.get("keywords", [])):
                next_stage_id = transition["next_stage_id"]
                found_transition = True
                break
        if not found_transition and current_stage_info.get("default_next_stage_id"): # 키워드 매칭 실패 시 기본 다음 단계
            next_stage_id = current_stage_info["default_next_stage_id"]

    elif current_stage_info.get("default_next_stage_id"): # transition 정의 없이 다음 단계로 바로 넘어가는 경우
         next_stage_id = current_stage_info["default_next_stage_id"]


    if next_stage_id == "END_SCENARIO": # 시나리오 종료 조건
        llm_prompt = scenario_data.get("end_scenario_message", "상담이 완료되었습니다. 감사합니다.")
        print(f"시나리오 종료. 최종 메시지: {llm_prompt}")
    else:
        next_stage_info = stages.get(next_stage_id, {})
        llm_prompt = next_stage_info.get("prompt", scenario_data.get("fallback_message", "다음 질문을 준비 중입니다."))
        if next_stage_info.get("is_question") and "%" in llm_prompt: # 프롬프트에 변수 치환
            try:
                # 예시: "안녕하세요, %{user_name}%님. %{loan_purpose}% 관련하여 질문드리겠습니다."
                # collected_info에서 필요한 값을 찾아 치환합니다. 안전하게 처리 필요.
                # 여기서는 간단히 % 형식만 처리. f-string 방식 등으로 고도화 가능.
                # 실제 구현 시에는 정규식이나 더 안전한 템플릿 엔진 사용 고려.
                # for key, value in collected_info.items():
                #    llm_prompt = llm_prompt.replace(f"%{{{key}}}%", str(value))
                pass # 치환 로직 추가
            except Exception as e:
                print(f"프롬프트 변수 치환 중 오류: {e}")


    print(f"다음 시나리오 단계: {next_stage_id}, 생성된 프롬프트: '{llm_prompt}'")
    # LLM 노드에서 이 프롬프트를 사용하여 사용자에게 전달할 최종 메시지를 다듬습니다.
    # 여기서는 LLM이 이 프롬프트를 그대로 또는 약간 변형하여 사용자에게 전달한다고 가정합니다.
    return {
        **state,
        "current_scenario_stage_id": next_stage_id,
        "collected_loan_info": collected_info,
        "llm_response_text": llm_prompt, # LLM이 이 내용을 바탕으로 최종 응답 생성
        "next_node_override": "tts_node" # 시나리오 로직 후 바로 TTS (LLM이 이 프롬프트를 직접 사용)
                                         # 또는 "llm_response_node"로 보내서 LLM이 한번 더 가공
    }

async def qa_retrieval_node(state: AgentState) -> AgentState:
    """
    의도가 'qa_question'일 때, 관련된 정보를 검색합니다 (RAG).
    검색된 정보를 바탕으로 LLM 프롬프트를 준비합니다.
    """
    print("--- 노드: qa_retrieval_node ---")
    user_question = state.get("stt_result", "")
    # TODO: RAG 로직 구현 (Vector DB 검색 등)
    # retrieved_context = await search_knowledge_base(user_question)
    retrieved_context = "현재 디딤돌 대출은 주택 구입 자금 마련을 위한 정부 지원 대출 상품입니다. (예시 RAG 결과)" # Placeholder

    # LLM에게 전달할 프롬프트 구성
    system_prompt = "당신은 신한은행 디딤돌 대출 전문가입니다. 다음 정보를 바탕으로 사용자의 질문에 답변해주세요."
    prompt = f"""
    [참고 정보]
    {retrieved_context}

    [사용자 질문]
    {user_question}

    [답변]
    """
    # 이 프롬프트를 messages에 추가하거나 llm_prompt_for_response에 저장
    # 여기서는 messages에 시스템 프롬프트와 사용자 질문(컨텍스트 포함)을 넣어 LLM에 전달하도록 함
    updated_messages = state["messages"][:-1] # 마지막 HumanMessage(단순 질문) 제거
    updated_messages = list(updated_messages) + [
        SystemMessage(content=system_prompt),
        HumanMessage(content=prompt) # 컨텍스트가 포함된 프롬프트를 HumanMessage로 전달
    ]

    print(f"Q&A 프롬프트 준비 완료 (사용자 질문: '{user_question}')")
    return {**state, "messages": updated_messages, "next_node_override": "llm_response_node"}


async def chit_chat_node(state: AgentState) -> AgentState:
    """
    의도가 'chit_chat'일 때, 간단한 일상 대화용 LLM 프롬프트를 준비합니다.
    """
    print("--- 노드: chit_chat_node ---")
    # user_utterance = state.get("stt_result", "")
    # messages에 이미 HumanMessage가 추가되어 있으므로, 특별한 프롬프트 수정 없이 바로 LLM 호출
    # 필요시 chit-chat용 시스템 프롬프트 추가 가능
    # system_prompt = SystemMessage(content="당신은 사용자와 가볍게 대화하는 친근한 AI입니다.")
    # updated_messages = [system_prompt] + list(state["messages"])
    # return {**state, "messages": updated_messages, "next_node_override": "llm_response_node"}
    return {**state, "next_node_override": "llm_response_node"} # 현재 메시지 그대로 LLM으로 전달


async def llm_response_node(state: AgentState) -> AgentState:
    """
    준비된 프롬프트/메시지를 바탕으로 LLM을 호출하여 최종 응답 텍스트를 생성합니다.
    (주로 Q&A, 칫챗 또는 복잡한 시나리오 응답 생성 시 사용)
    """
    print("--- 노드: llm_response_node ---")
    current_messages = state.get("messages", [])
    if not current_messages or not isinstance(current_messages[-1], HumanMessage):
        # 이 경우는 보통 intent_classification에서 HumanMessage가 아닌 다른 메시지로 끝났을 때 발생 가능
        # 또는 이전 노드에서 messages를 잘못 구성한 경우
        print("LLM 호출 오류: 마지막 메시지가 HumanMessage가 아님")
        return {**state, "llm_response_text": "요청을 이해하지 못했습니다. 다시 말씀해주시겠어요?", "next_node_override": "tts_node"}

    try:
        print(f"LLM 호출 메시지: {current_messages}")
        ai_response = await llm.ainvoke(current_messages)
        response_content = ai_response.content
        print(f"LLM 응답: '{response_content}'")
        return {
            **state,
            "llm_response_text": response_content,
            "messages": state["messages"] + [AIMessage(content=response_content)],
            "next_node_override": "tts_node"
        }
    except Exception as e:
        print(f"LLM 호출 중 오류: {e}")
        return {**state, "error_message": f"AI 응답 생성 중 오류: {e}", "next_node_override": "handle_error_node"}


async def tts_node(state: AgentState) -> AgentState:
    """
    LLM 응답 텍스트를 음성으로 변환합니다 (Google TTS 사용).
    """
    print("--- 노드: tts_node ---")
    text_to_speak = state.get("llm_response_text")
    if not text_to_speak: # llm_response_text가 없는 경우 (예: 시나리오 노드에서 직접 설정 안하고 넘어온 경우)
        # 또는 오류 상황에서 fallback 메시지 사용
        text_to_speak = state.get("error_message") or state.get("loan_scenario_data", {}).get("fallback_message", "음성 답변을 준비하지 못했습니다.")

    try:
        audio_bytes = await synthesize_text_to_audio_bytes(text_to_speak)
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        print(f"TTS 변환 완료 (텍스트: '{text_to_speak[:30]}...')")
        return {**state, "tts_audio_b64": audio_b64, "is_final_turn_response": True} # 최종 응답 준비 완료
    except Exception as e:
        print(f"TTS 변환 중 오류: {e}")
        # TTS 실패 시 텍스트 응답이라도 유지, 오류 메시지 추가
        return {**state, "error_message": f"음성 변환 중 오류: {e}. 텍스트로 답변합니다.", "is_final_turn_response": True}


async def handle_error_node(state: AgentState) -> AgentState:
    """
    처리 중 발생한 오류를 사용자에게 알릴 메시지를 준비하고 TTS 노드로 전달합니다.
    """
    print("--- 노드: handle_error_node ---")
    error_msg_for_user = state.get("error_message", "알 수 없는 오류가 발생했습니다. 죄송합니다.")
    # 이미 기록된 error_message를 llm_response_text로 설정하여 TTS에서 사용하도록 함
    return {**state, "llm_response_text": error_msg_for_user, "next_node_override": "tts_node"}


# --- 조건부 엣지 로직 ---
def route_after_entry(state: AgentState) -> str:
    return state.get("next_node_override", "intent_classification_node") # 기본값은 의도분류

def route_after_stt(state: AgentState) -> str:
    return state.get("next_node_override", "intent_classification_node")

def route_after_intent_classification(state: AgentState) -> str:
    intent = state.get("intent")
    user_text = state.get("stt_result", "")
    if state.get("error_message"): return "handle_error_node"

    if intent == "scenario_answer":
        return "scenario_logic_node"
    elif intent == "qa_question":
        return "qa_retrieval_node"
    elif intent == "chit_chat":
        return "chit_chat_node"
    elif intent == "end_conversation":
        # 종료 메시지를 llm_response_text에 설정하고 바로 tts로
        # (또는 별도의 'end_conversation_node'를 만들어 메시지 준비 후 tts)
        end_message = state.get("loan_scenario_data",{}).get("end_conversation_message", "상담을 종료합니다. 이용해주셔서 감사합니다.")
        state["llm_response_text"] = end_message
        return "tts_node" # 바로 TTS로 가서 종료 메시지 음성 출력
    else: # "unclear" 또는 기타
        # fallback 메시지를 llm_response_text에 설정
        fallback_message = state.get("loan_scenario_data",{}).get("fallback_message", "죄송합니다. 잘 이해하지 못했습니다. 다시 말씀해주시겠어요?")
        state["llm_response_text"] = fallback_message
        if not user_text and user_text != "": # STT 결과 자체가 없는 경우 (심각한 인식 실패)
            state["llm_response_text"] = "음성을 인식하지 못했습니다. 다시 한번 말씀해주시겠어요?"
        return "tts_node" # 바로 TTS로 가서 fallback 메시지 음성 출력

def route_after_logic_nodes(state: AgentState) -> str: # scenario_logic, qa_retrieval, chit_chat 이후
    if state.get("error_message"): return "handle_error_node"
    return state.get("next_node_override", "llm_response_node") # 기본적으로 LLM 응답 생성으로

def route_after_llm_or_error_handling(state: AgentState) -> str: # llm_response_node, handle_error_node 이후
    # 이 노드들은 항상 tts_node로 가도록 next_node_override를 설정해두었음
    # 따라서 여기서는 특별한 분기 없이 tts_node로 가거나, 만약의 경우를 대비해 에러 핸들링
    if state.get("error_message") and not state.get("llm_response_text"): # llm_response_text가 아직 설정 안된 심각한 오류
        return "handle_error_node" # 다시 에러 핸들러 (보통은 여기까지 안옴)
    return state.get("next_node_override", "tts_node")

# --- LangGraph 그래프 빌드 ---
workflow = StateGraph(AgentState)

workflow.add_node("entry_point_node", entry_point_node)
workflow.add_node("stt_node", stt_node)
workflow.add_node("intent_classification_node", intent_classification_node)
workflow.add_node("scenario_logic_node", scenario_logic_node)
workflow.add_node("qa_retrieval_node", qa_retrieval_node)
workflow.add_node("chit_chat_node", chit_chat_node)
workflow.add_node("llm_response_node", llm_response_node)
workflow.add_node("tts_node", tts_node)
workflow.add_node("handle_error_node", handle_error_node)

workflow.set_entry_point("entry_point_node")

workflow.add_conditional_edges("entry_point_node", route_after_entry, {
    "stt_node": "stt_node",
    "intent_classification_node": "intent_classification_node",
    "handle_error_node": "handle_error_node" # 시나리오 로드 실패 등 초기오류
})
workflow.add_conditional_edges("stt_node", route_after_stt, {
    "intent_classification_node": "intent_classification_node",
    "handle_error_node": "handle_error_node"
})
workflow.add_conditional_edges("intent_classification_node", route_after_intent_classification, {
    "scenario_logic_node": "scenario_logic_node",
    "qa_retrieval_node": "qa_retrieval_node",
    "chit_chat_node": "chit_chat_node",
    "tts_node": "tts_node", # 종료 또는 fallback 메시지 직접 설정 후 TTS로
    "handle_error_node": "handle_error_node"
})

# 시나리오, Q&A, 칫챗 로직 처리 후 LLM을 거치거나 바로 TTS로 갈 수 있음
# scenario_logic_node는 next_node_override를 통해 tts_node로 바로 갈 수 있음 (LLM 거치지 않고)
workflow.add_conditional_edges("scenario_logic_node", route_after_logic_nodes, {
    "llm_response_node": "llm_response_node",
    "tts_node": "tts_node", # scenario_logic_node에서 직접 llm_response_text 설정 후 tts로 가는 경우
    "handle_error_node": "handle_error_node"
})
workflow.add_conditional_edges("qa_retrieval_node", route_after_logic_nodes, {
    "llm_response_node": "llm_response_node", # Q&A는 보통 LLM을 거쳐 답변 생성
    "handle_error_node": "handle_error_node"
})
workflow.add_conditional_edges("chit_chat_node", route_after_logic_nodes, {
    "llm_response_node": "llm_response_node", # 칫챗은 보통 LLM을 거쳐 답변 생성
    "handle_error_node": "handle_error_node"
})

# LLM 응답 생성 후 또는 에러 핸들링 후
workflow.add_conditional_edges("llm_response_node", route_after_llm_or_error_handling, {
    "tts_node": "tts_node",
    "handle_error_node": "handle_error_node" # LLM 호출 실패 시 에러 핸들러에서 이미 처리했겠지만, 방어적 코딩
})
workflow.add_conditional_edges("handle_error_node", route_after_llm_or_error_handling, {
    "tts_node": "tts_node" # 에러 메시지를 TTS로
})

# TTS 노드는 항상 대화 턴의 마지막
workflow.add_edge("tts_node", END)


# 컴파일된 실행 가능한 LangGraph 에이전트
# checkpointer를 추가하면 대화 상태를 세션별로 지속시킬 수 있습니다. (예: MemorySaver)
# from langgraph.checkpoint.memory import MemorySaver
# memory = MemorySaver()
# app_graph = workflow.compile(checkpointer=memory)
app_graph = workflow.compile()


# --- 에이전트 실행 함수 ---
async def run_agent(
    user_input_text: Optional[str] = None,
    user_input_audio_b64: Optional[str] = None,
    session_id: Optional[str] = "default_session", # 세션 ID 추가
    current_state_dict: Optional[Dict] = None # 이전 상태를 받아 이어갈 경우
) -> AgentState:
    """
    LangGraph 에이전트를 실행하고 최종 상태를 반환합니다.
    """
    if current_state_dict:
        # 이전 상태에서 필요한 부분만 추출하여 AgentState 형식에 맞게 재구성
        # 특히 messages, current_scenario_stage_id, collected_loan_info 등을 이어받아야 함
        initial_input_for_turn: AgentState = {
            "messages": current_state_dict.get("messages", []),
            "user_input_text": user_input_text,
            "user_input_audio_b64": user_input_audio_b64,
            "current_scenario_stage_id": current_state_dict.get("current_scenario_stage_id"),
            "collected_loan_info": current_state_dict.get("collected_loan_info", {}),
            # 나머지 필드는 entry_point_node에서 초기화될 것임
            "stt_result": None, "intent": None, "loan_scenario_data": {},
            "llm_prompt_for_response": None, "llm_response_text": None,
            "tts_audio_b64": None, "error_message": None,
            "is_final_turn_response": False, "next_node_override": None
        }
    else: # 첫번째 턴이거나 상태 이어받기 안하는 경우
        initial_input_for_turn: AgentState = {
            "messages": [], # entry_point_node에서 시스템 프롬프트 추가됨
            "user_input_text": user_input_text,
            "user_input_audio_b64": user_input_audio_b64,
            "current_scenario_stage_id": None, # entry_point_node에서 초기값 설정
            "collected_loan_info": {},
            "stt_result": None, "intent": None, "loan_scenario_data": {},
            "llm_prompt_for_response": None, "llm_response_text": None,
            "tts_audio_b64": None, "error_message": None,
            "is_final_turn_response": False, "next_node_override": None
        }

    # LangGraph 실행 시 config (세션 ID 사용 예시 - checkpointer와 함께 사용)
    config = {"configurable": {"session_id": session_id}}

    # final_state = await app_graph.ainvoke(initial_input_for_turn, config=config) # checkpointer 사용시
    final_state = await app_graph.ainvoke(initial_input_for_turn) # checkpointer 미사용시

    # 사용 편의를 위해 AgentState 타입으로 명시적 반환 (실제로는 Dict 반환됨)
    return final_state