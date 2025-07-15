# backend/app/api/v1/chat.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException, status, Header
import json
import re # For sentence splitting
from typing import Dict, Optional, cast, List, Any # Added List, Any
from langchain_core.messages import AIMessage

from ...graph.agent import run_agent_streaming, AgentState, PRODUCT_TYPES # PRODUCT_TYPES 임포트
from ...services.google_services import StreamSTTService, StreamTTSService, GOOGLE_SERVICES_AVAILABLE
from ...core.config import LLM_MODEL_NAME

router = APIRouter()
SESSION_STATES: Dict[str, AgentState] = {}

# 정보 수집 관련 스테이지 상수
INFO_COLLECTION_STAGES = {
    "info_collection_guidance", 
    "process_collected_info",
    "ask_missing_info_group1", 
    "ask_missing_info_group2", 
    "ask_missing_info_group3"
} 


# 허용할 출처 목록 (개발 환경)
# 프로덕션에서는 실제 서비스 도메인으로 변경해야 합니다.
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket
        print(f"WebSocket connected: {session_id}")

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]
            print(f"WebSocket disconnected: {session_id}")

    async def send_json_to_client(self, session_id: str, data: dict):
        if session_id in self.active_connections:
            try:
                await self.active_connections[session_id].send_json(data)
            except WebSocketException as e:
                print(f"Error sending to client {session_id} (possibly closed): {e}")
                self.disconnect(session_id)
            except RuntimeError as e:
                 print(f"RuntimeError sending to client {session_id} (WebSocket is closed): {e}")
                 self.disconnect(session_id)

manager = ConnectionManager()

def split_into_sentences(text: str) -> List[str]:
    """
    Splits text into sentences. This is a basic implementation.
    For more robust sentence tokenization, consider using a library like KSS (Korean Sentence Splitter)
    or NLTK if the project allows additional dependencies.
    """
    if not text:
        return []
    
    # Enhanced regex to better handle various sentence endings and keep them.
    # It looks for common Korean and English terminators.
    # It tries to keep the delimiter as part of the sentence.
    # This regex is still basic and might not cover all edge cases.
    parts = re.split(r'(?<=[.?!다죠요])\s+|(?<=[.?!])\s+(?=[A-Z"\'(])', text) # Slightly improved split
    
    processed_sentences = []
    for part in parts:
        if part and part.strip():
            # Further split if a part contains multiple simple sentences without clear delimiter separation
            # e.g. "안녕하세요 만나서 반갑습니다"
            # This part is tricky without a proper NLP tokenizer.
            # For now, we assume the primary split is mostly sufficient.
            # Simple check for run-on sentences without clear delimiters can be added later if needed.
            processed_sentences.append(part.strip())
            
    if not processed_sentences and text.strip(): # If split fails but text exists, return as single sentence
        return [text.strip()]
        
    return [s for s in processed_sentences if s]


def should_send_slot_filling_update(
    info_changed: bool, 
    scenario_changed: bool,
    product_type_changed: bool, 
    scenario_active: bool,
    is_info_collection_stage: bool
) -> bool:
    """Slot filling 업데이트 전송이 필요한지 판단"""
    return (
        info_changed or 
        scenario_changed or 
        product_type_changed or
        (scenario_active and is_info_collection_stage)
    )


# 성능 최적화를 위한 메시지 크기 제한 및 캐시
MAX_MESSAGE_SIZE = 512 * 1024  # 512KB
MAX_DESCRIPTION_LENGTH = 200  # 설명 최대 길이
_last_sent_message_hash = {}  # 세션별 마지막 전송 메시지 해시


def _calculate_message_hash(message: dict) -> str:
    """메시지 해시 계산 (중복 전송 방지용)"""
    import hashlib
    import json
    
    # 메시지에서 변경되는 부분만 해시 계산에 포함
    hash_data = {
        "productType": message.get("productType"),
        "collectedInfo": message.get("collectedInfo"),
        "completionStatus": message.get("completionStatus"),
        "completionRate": message.get("completionRate")
    }
    
    message_str = json.dumps(hash_data, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(message_str.encode()).hexdigest()


def _optimize_fields_for_size(fields: List[Dict], max_size: int) -> List[Dict]:
    """필드 데이터 크기 최적화"""
    optimized_fields = []
    
    for field in fields:
        optimized_field = field.copy()
        
        # 설명이 너무 긴 경우 잘라내기
        if "description" in optimized_field and len(optimized_field["description"]) > MAX_DESCRIPTION_LENGTH:
            optimized_field["description"] = optimized_field["description"][:MAX_DESCRIPTION_LENGTH] + "..."
        
        # 불필요한 빈 값들 제거
        optimized_field = {k: v for k, v in optimized_field.items() if v is not None and v != ""}
        
        optimized_fields.append(optimized_field)
    
    return optimized_fields


async def send_slot_filling_update(websocket: WebSocket, state: AgentState, session_id: str = None):
    """Slot filling 상태 업데이트를 WebSocket으로 전송 (성능 최적화)"""
    try:
        scenario_data = state.get("active_scenario_data")
        if not scenario_data:
            print("[send_slot_filling_update] No active scenario data, skipping update")
            return
        
        required_fields = scenario_data.get("required_info_fields", [])
        collected_info = state.get("collected_product_info", {})
        
        # Frontend 인터페이스에 맞게 필드 변환
        frontend_fields = []
        for field in required_fields:
            frontend_field = {
                "key": field["key"],
                "displayName": field.get("display_name", field.get("name", "")),
                "type": field.get("type", "text"),
                "required": field.get("required", True),
            }
            
            # 선택형 필드의 choices 추가
            if field.get("type") == "choice" and "choices" in field:
                frontend_field["choices"] = field["choices"]
            
            # 숫자형 필드의 unit 추가
            if field.get("type") == "number" and "unit" in field:
                frontend_field["unit"] = field["unit"]
                
            # 설명 추가 (크기 최적화)
            if "description" in field:
                description = field["description"]
                if len(description) > MAX_DESCRIPTION_LENGTH:
                    description = description[:MAX_DESCRIPTION_LENGTH] + "..."
                frontend_field["description"] = description
                
            # 의존성 정보 추가
            if "depends_on" in field:
                frontend_field["dependsOn"] = field["depends_on"]
                
            frontend_fields.append(frontend_field)
        
        # completion_status 계산
        completion_status = {
            field["key"]: field["key"] in collected_info 
            for field in required_fields
        }
        
        # 수집률 계산 (required=true인 필드만 고려)
        required_fields_only = [f for f in required_fields if f.get("required", True)]
        total_required = len(required_fields_only)
        completed_required = sum(
            1 for f in required_fields_only 
            if f["key"] in collected_info
        )
        completion_rate = (completed_required / total_required * 100) if total_required > 0 else 0
        
        update_message = {
            "type": "slot_filling_update",
            "productType": state.get("current_product_type"),
            "requiredFields": frontend_fields,
            "collectedInfo": collected_info,
            "completionStatus": completion_status,
            "completionRate": completion_rate
        }
    
        # field_groups가 있으면 추가 (카멜케이스로 변환)
        if "field_groups" in scenario_data:
            update_message["fieldGroups"] = scenario_data["field_groups"]
        
        # 중복 메시지 전송 방지
        message_hash = _calculate_message_hash(update_message)
        if session_id:
            last_hash = _last_sent_message_hash.get(session_id)
            if last_hash == message_hash:
                print(f"[send_slot_filling_update] Skipping duplicate message for session {session_id}")
                return
            _last_sent_message_hash[session_id] = message_hash
        
        # 메시지 크기 확인 및 최적화
        import json
        message_size = len(json.dumps(update_message, ensure_ascii=False))
        
        if message_size > MAX_MESSAGE_SIZE:
            print(f"[send_slot_filling_update] Message too large ({message_size} bytes), optimizing...")
            
            # 필드 최적화
            update_message["requiredFields"] = _optimize_fields_for_size(
                update_message["requiredFields"], 
                MAX_MESSAGE_SIZE // 2
            )
            
            # 재계산
            message_size = len(json.dumps(update_message, ensure_ascii=False))
            print(f"[send_slot_filling_update] Optimized message size: {message_size} bytes")
        
        await websocket.send_json(update_message)
        print(f"[send_slot_filling_update] Sent update - Product: {state.get('current_product_type')}, Rate: {completion_rate:.1f}%, Fields: {len(required_fields)}, Size: {message_size} bytes")
        
    except WebSocketException as e:
        print(f"[send_slot_filling_update] WebSocket error: {e}")
    except Exception as e:
        print(f"[send_slot_filling_update] Unexpected error: {e}")


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect(websocket, session_id)

    if session_id not in manager.active_connections:
        return

    stt_service: Optional[StreamSTTService] = None
    tts_service: Optional[StreamTTSService] = None

    if session_id not in SESSION_STATES:
        SESSION_STATES[session_id] = {
            "session_id": session_id,
            "user_input_text": None,
            "user_input_audio_b64": None,
            "stt_result": None,
            "current_product_type": None,
            "available_product_types": ["didimdol", "jeonse", "deposit_account"], # 수정
            "main_agent_routing_decision": None,
            "main_agent_direct_response": None,
            "scenario_agent_output": None,
            "messages": [],
            "current_scenario_stage_id": None,
            "collected_product_info": {},
            "active_scenario_data": None,
            "active_knowledge_base_content": None,
            "active_scenario_name": "미정",
            "final_response_text_for_tts": None,
            "error_message": None,
            "is_final_turn_response": False,
            "tts_cancelled": False, # TTS 중단 플래그 추가
        }
        print(f"New session initialized for {session_id}")
        initial_greeting_message = "안녕하세요! 신한은행 AI 금융 상담 서비스입니다. 어떤 도움이 필요하신가요? (예: 디딤돌 대출, 전세자금 대출, 입출금통장 개설)" # 수정
        await manager.send_json_to_client(session_id, {
            "type": "session_initialized",
            "message": initial_greeting_message
        })
        
        # 초기 slot filling 상태 전송 (빈 상태)
        try:
            await send_slot_filling_update(websocket, SESSION_STATES[session_id], session_id)
            print(f"[{session_id}] Initial slot filling state sent")
        except Exception as e:
            print(f"[{session_id}] Failed to send initial slot filling state: {e}")

    if GOOGLE_SERVICES_AVAILABLE:
        async def _on_tts_audio_chunk(audio_chunk_b64: str):
            await manager.send_json_to_client(session_id, {"type": "tts_audio_chunk", "audio_chunk_base64": audio_chunk_b64})
        async def _on_tts_stream_complete(): # This now signals end of one sentence's audio
            await manager.send_json_to_client(session_id, {"type": "tts_stream_end"})
        async def _on_tts_error(error_msg: str):
            await manager.send_json_to_client(session_id, {"type": "error", "message": f"TTS Error: {error_msg}"})
        tts_service = StreamTTSService(session_id=session_id, on_audio_chunk=_on_tts_audio_chunk, on_stream_complete=_on_tts_stream_complete, on_error=_on_tts_error)

        async def _on_stt_interim_result(transcript: str):
            await manager.send_json_to_client(session_id, {"type": "stt_interim_result", "transcript": transcript})
        
        async def handle_stt_final_result_with_tts_wrapper(transcript: str):
            trimmed_transcript = transcript.strip()
            # STT 최종 결과를 클라이언트로 전송 (인터림 텍스트 지우기용)
            await manager.send_json_to_client(session_id, {"type": "stt_final_result", "transcript": trimmed_transcript})

            if trimmed_transcript:
                # 유효한 텍스트가 있으면 에이전트 처리
                await process_input_through_agent(session_id, trimmed_transcript, tts_service, input_mode="voice")
            else:
                # STT 결과가 비어있으면, 사용자에게 재요청
                print(f"[{session_id}] Empty STT result. Asking user to repeat.")
                reprompt_message = "죄송합니다, 잘 이해하지 못했어요. 다시 한번 말씀해주시겠어요?"
                
                # 재요청 메시지를 UI에 표시
                await manager.send_json_to_client(session_id, {"type": "llm_response_chunk", "chunk": reprompt_message})
                await manager.send_json_to_client(session_id, {"type": "llm_response_end", "full_text": reprompt_message})
                
                # 세션 상태의 메시지 기록에도 추가
                if session_id in SESSION_STATES:
                    current_messages = SESSION_STATES[session_id].get("messages", [])
                    current_messages.append(AIMessage(content=reprompt_message))
                    SESSION_STATES[session_id]["messages"] = current_messages

                # 음성 모드일 경우, 재요청 메시지를 TTS로 재생
                if tts_service and GOOGLE_SERVICES_AVAILABLE and SESSION_STATES.get(session_id, {}).get('isVoiceModeActive', True):
                    await tts_service.start_tts_stream(reprompt_message)

        async def _on_stt_error(error_msg: str):
            await manager.send_json_to_client(session_id, {"type": "error", "message": f"STT Error: {error_msg}"})
        async def _on_epd_detected():
            print(f"EPD detected by Google STT for session {session_id}")
            await manager.send_json_to_client(session_id, {"type": "epd_detected"})
        stt_service = StreamSTTService(
            session_id=session_id, 
            on_interim_result=_on_stt_interim_result, 
            on_final_result=handle_stt_final_result_with_tts_wrapper, 
            on_error=_on_stt_error, 
            on_epd_detected=_on_epd_detected
        )
    else:
        print(f"[{session_id}] Google STT/TTS 서비스가 비활성화되어 음성 관련 기능이 제한됩니다.")
        await manager.send_json_to_client(session_id, { "type": "warning", "message": "음성 인식 및 합성이 현재 지원되지 않습니다. 텍스트로 입력해주세요."})

    try:
        while True:
            data = await websocket.receive()
            message_type = None; payload_dict = None; raw_payload = None
            if "text" in data:
                try:
                    message_data = json.loads(data["text"]); message_type = message_data.get("type"); payload_dict = message_data
                except json.JSONDecodeError:
                    print(f"Invalid JSON from {session_id}: {data['text']}")
                    await manager.send_json_to_client(session_id, {"type": "error", "message": "Invalid JSON format."}); continue
            elif "bytes" in data:
                message_type = "audio_chunk"; raw_payload = data["bytes"]

            if message_type == "process_text":
                user_text = payload_dict.get("text")
                if user_text:
                    await process_input_through_agent(session_id, user_text, tts_service, input_mode="text")
                else: await manager.send_json_to_client(session_id, {"type": "error", "message": "No text provided."})
                
            elif message_type == "test_slot_filling":
                # 테스트용 더미 데이터로 slot filling 업데이트 전송
                test_state = SESSION_STATES.get(session_id, {}).copy()
                test_state["current_product_type"] = "didimdol"
                test_state["active_scenario_data"] = {
                    "required_info_fields": [
                        {
                            "key": "loan_purpose_confirmed",
                            "display_name": "대출 목적",
                            "type": "boolean",
                            "required": True,
                            "description": "주택 구입 목적인지 확인"
                        },
                        {
                            "key": "marital_status",
                            "display_name": "결혼 상태", 
                            "type": "choice",
                            "choices": ["미혼", "기혼", "예비부부"],
                            "required": True,
                            "description": "고객의 결혼 상태"
                        },
                        {
                            "key": "annual_income",
                            "display_name": "연소득",
                            "type": "number",
                            "unit": "만원",
                            "required": True,
                            "description": "연간 소득 금액"
                        }
                    ],
                    "field_groups": [
                        {
                            "id": "personal_info",
                            "name": "개인 정보",
                            "fields": ["marital_status"]
                        },
                        {
                            "id": "financial_info",
                            "name": "재무 정보", 
                            "fields": ["annual_income"]
                        }
                    ]
                }
                test_state["collected_product_info"] = {
                    "loan_purpose_confirmed": True,
                    "marital_status": "미혼"
                }
                
                await send_slot_filling_update(websocket, test_state, session_id)
                await manager.send_json_to_client(session_id, {
                    "type": "info",
                    "message": "테스트 slot filling 업데이트를 전송했습니다."
                })
            elif message_type == "audio_chunk":
                if stt_service and GOOGLE_SERVICES_AVAILABLE: await stt_service.process_audio_chunk(raw_payload)
            elif message_type == "activate_voice":
                if stt_service and GOOGLE_SERVICES_AVAILABLE:
                    print(f"[{session_id}] Activating voice. Starting STT stream.")
                    await stt_service.start_stream()
                    await manager.send_json_to_client(session_id, {"type": "voice_activated"})
                else: await manager.send_json_to_client(session_id, {"type": "error", "message": "음성 인식 서비스를 시작할 수 없습니다."})
            elif message_type == "deactivate_voice":
                if stt_service and GOOGLE_SERVICES_AVAILABLE:
                    print(f"[{session_id}] Deactivating voice. Stopping STT stream.")
                    await stt_service.stop_stream()
                    await manager.send_json_to_client(session_id, {"type": "voice_deactivated"})
            elif message_type == "stop_tts": 
                if tts_service and GOOGLE_SERVICES_AVAILABLE:
                    print(f"[{session_id}] Client requested server to stop TTS stream generation.")
                    if session_id in SESSION_STATES:
                        SESSION_STATES[session_id]['tts_cancelled'] = True
                    await tts_service.stop_tts_stream() 
                else: print(f"[{session_id}] TTS stop_tts, TTS service N/A.")
    except WebSocketDisconnect: print(f"WebSocket disconnected by client: {session_id}")
    except RuntimeError as e:
        # 클라이언트의 비정상 종료로 인한 특정 RuntimeError를 정상적인 연결 종료로 처리
        if 'Cannot call "receive" once a disconnect message has been received' in str(e):
            print(f"WebSocket closed abruptly, handled as a normal disconnect: {session_id}")
        else:
            # 그 외의 다른 RuntimeError는 실제 에러로 간주하고 로그를 남김
            print(f"An unexpected WebSocket RuntimeError occurred for session {session_id}: {e}")
            import traceback; traceback.print_exc()
            try: 
                await manager.send_json_to_client(session_id, {"type": "error", "message": f"Server runtime error: {str(e)}"})
            except Exception: pass 
    except Exception as e:
        print(f"WebSocket Error for session {session_id}: {e}")
        import traceback; traceback.print_exc()
        try: 
            await manager.send_json_to_client(session_id, {"type": "error", "message": f"Server error: {str(e)}"})
        except Exception: pass 
    finally:
        if stt_service: await stt_service.stop_stream()
        if tts_service: await tts_service.stop_tts_stream() 
        manager.disconnect(session_id)
        if session_id in SESSION_STATES: del SESSION_STATES[session_id]; print(f"Session state for {session_id} cleared.")


async def process_input_through_agent(session_id: str, user_text: str, tts_service: Optional[StreamTTSService], input_mode: str):
    print(f"process_input_through_agent called for session {session_id}, mode: {input_mode}, text: '{user_text[:30]}...'")
    current_session_state = SESSION_STATES.get(session_id)
    if not current_session_state:
        print(f"Error: Session state for {session_id} not found during agent processing.")
        await manager.send_json_to_client(session_id, {"type": "error", "message": "세션 정보를 찾을 수 없습니다. 다시 시도해주세요."})
        return

    # TTS 취소 플래그 초기화
    if session_id in SESSION_STATES:
        SESSION_STATES[session_id]['tts_cancelled'] = False

    full_ai_response_text = ""
    raw_llm_stream_ended = False # Flag to indicate LLM stream ended

    try:
        async for agent_output_chunk in run_agent_streaming(
            user_input_text=user_text,
            session_id=session_id,
            current_state_dict=current_session_state
        ):
            if isinstance(agent_output_chunk, str): 
                await manager.send_json_to_client(session_id, {"type": "llm_response_chunk", "chunk": agent_output_chunk})
                full_ai_response_text += agent_output_chunk
            elif isinstance(agent_output_chunk, dict):
                if agent_output_chunk.get("type") == "stream_start":
                    await manager.send_json_to_client(session_id, agent_output_chunk)
                elif agent_output_chunk.get("type") == "stream_end":
                    raw_llm_stream_ended = True # Mark LLM stream as ended
                    await manager.send_json_to_client(session_id, {"type": "llm_response_end", "full_text": full_ai_response_text})
                    # TTS for streamed LLM content will be handled after this loop, using the full_ai_response_text
                elif agent_output_chunk.get("type") == "final_state":
                    final_agent_state_data = agent_output_chunk.get("data")
                    if final_agent_state_data:
                        # 이전 상태 저장 (변경 감지용)
                        previous_collected_info = SESSION_STATES[session_id].get("collected_product_info", {}).copy()
                        previous_scenario_data = SESSION_STATES[session_id].get("active_scenario_data")
                        previous_product_type = SESSION_STATES[session_id].get("current_product_type")
                        
                        SESSION_STATES[session_id] = cast(AgentState, final_agent_state_data)
                        # If LLM didn't stream but final_state provides text, use it
                        if not full_ai_response_text and final_agent_state_data.get("final_response_text_for_tts"):
                            full_ai_response_text = final_agent_state_data["final_response_text_for_tts"]
                            # Send this full text as if it was streamed, for UI consistency
                            await manager.send_json_to_client(session_id, {"type": "llm_response_chunk", "chunk": full_ai_response_text})
                            await manager.send_json_to_client(session_id, {"type": "llm_response_end", "full_text": full_ai_response_text})
                        
                        # Update current_session_state for TTS logic below
                        current_session_state = SESSION_STATES[session_id]
                        print(f"Session state for {session_id} updated via final_state.")
                        
                        # Slot filling 업데이트 전송 (변경사항이 있거나 시나리오가 활성화된 경우)
                        current_collected_info = current_session_state.get("collected_product_info", {})
                        current_scenario_stage = current_session_state.get("current_scenario_stage_id", "")
                        
                        # 업데이트가 필요한 조건들
                        info_changed = previous_collected_info != current_collected_info
                        scenario_changed = previous_scenario_data != current_session_state.get("active_scenario_data")
                        product_type_changed = previous_product_type != current_session_state.get("current_product_type")
                        scenario_active = current_session_state.get("active_scenario_data") is not None
                        is_info_collection_stage = current_scenario_stage in INFO_COLLECTION_STAGES
                        
                        # 업데이트 전송 조건 확인
                        if should_send_slot_filling_update(
                            info_changed, scenario_changed, product_type_changed, 
                            scenario_active, is_info_collection_stage
                        ):
                            print(f"[{session_id}] Sending slot filling update - Info: {info_changed}, Scenario: {scenario_changed}, Product: {product_type_changed}, Stage: {current_scenario_stage}")
                            await send_slot_filling_update(websocket, current_session_state, session_id)
                elif agent_output_chunk.get("type") == "error": 
                    await manager.send_json_to_client(session_id, agent_output_chunk)
                    await manager.send_json_to_client(session_id, {"type": "llm_response_end", "full_text": ""}) 
                    if session_id in SESSION_STATES: # Update error in state
                        SESSION_STATES[session_id]["error_message"] = agent_output_chunk.get("message")
                        current_session_state = SESSION_STATES[session_id] # refresh
                        full_ai_response_text = "" # No TTS on error
                    break # Stop processing further chunks on error

        # TTS processing after LLM response is complete (either from stream_end or final_state)
        if input_mode == "voice" and tts_service and GOOGLE_SERVICES_AVAILABLE and full_ai_response_text and not (current_session_state and current_session_state.get("error_message")):
            print(f"[{session_id}] Splitting LLM response for sentence-by-sentence TTS. Full text: '{full_ai_response_text[:70]}...'")
            sentences = split_into_sentences(full_ai_response_text)
            if not sentences:
                print(f"[{session_id}] No sentences found in LLM response for TTS.")
            
            for i, sentence in enumerate(sentences):
                # 루프 시작 전, 매번 TTS 취소 플래그를 확인
                if current_session_state.get('tts_cancelled'):
                    print(f"[{session_id}] TTS loop interrupted by client request.")
                    break

                sentence_strip = sentence.strip()
                if sentence_strip:
                    print(f"[{session_id}] Starting TTS for sentence {i+1}/{len(sentences)}: '{sentence_strip[:50]}...'")
                    # The call to start_tts_stream will now await the completion of TTS for this sentence
                    await tts_service.start_tts_stream(sentence_strip) 
                    # A small delay might be useful if there are websocket send overlaps,
                    # but start_tts_stream being awaitable should handle sequencing.
                    # await asyncio.sleep(0.05) 
                else:
                    print(f"[{session_id}] Skipping empty sentence for TTS.")
        elif input_mode != "voice":
            print(f"[{session_id}] Text input mode (mode: {input_mode}), TTS skipped for: {full_ai_response_text[:30]}...")
        elif not full_ai_response_text:
            print(f"[{session_id}] No text from LLM, TTS skipped.")
        elif current_session_state and current_session_state.get("error_message"):
            print(f"[{session_id}] Error in session state, TTS skipped. Error: {current_session_state.get('error_message')}")


    except Exception as e:
        error_msg = f"Agent 처리 중 예외 발생: {e}"
        print(f"[{session_id}] {error_msg}")
        import traceback; traceback.print_exc()
        await manager.send_json_to_client(session_id, {"type": "error", "message": error_msg})
        await manager.send_json_to_client(session_id, {"type": "llm_response_end", "full_text": ""}) 
        if session_id in SESSION_STATES:
            SESSION_STATES[session_id]["error_message"] = error_msg
            SESSION_STATES[session_id]["is_final_turn_response"] = True