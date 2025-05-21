# backend/app/api/v1/chat.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
from typing import Dict, Optional

from ...graph.agent import run_agent_streaming, AgentState
from ...services.google_services import StreamSTTService, StreamTTSService, GOOGLE_SERVICES_AVAILABLE
from ...core.config import LLM_MODEL_NAME # LLM 모델명 등 설정 가져오기

router = APIRouter()

# 세션 상태 저장소 (인메모리 방식, 프로덕션에서는 Redis 등 외부 저장소 권장)
SESSION_STATES: Dict[str, AgentState] = {}

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
            await self.active_connections[session_id].send_json(data)

manager = ConnectionManager()

@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect(websocket, session_id)

    stt_service: Optional[StreamSTTService] = None
    tts_service: Optional[StreamTTSService] = None

    if session_id not in SESSION_STATES:
        SESSION_STATES[session_id] = {}
        print(f"New session initialized for {session_id}")
        await manager.send_json_to_client(session_id, {
            "type": "session_initialized",
            "message": "안녕하세요! 디딤돌 대출 음성 상담 서비스입니다. 무엇을 도와드릴까요? (채팅으로 입력하시거나 마이크 버튼을 눌러 말씀해주세요)"
        })
    else:
        print(f"Existing session loaded for {session_id}")
        # TODO: 이전 대화 이력 요약 등 클라이언트에 전달 가능

    if GOOGLE_SERVICES_AVAILABLE:
        async def _on_tts_audio_chunk(audio_chunk_b64: str):
            await manager.send_json_to_client(session_id, {"type": "tts_audio_chunk", "audio_chunk_base64": audio_chunk_b64})

        async def _on_tts_stream_complete():
            await manager.send_json_to_client(session_id, {"type": "tts_stream_end"})

        async def _on_tts_error(error_msg: str):
            await manager.send_json_to_client(session_id, {"type": "error", "message": f"TTS Error: {error_msg}"})

        tts_service = StreamTTSService(
            session_id=session_id,
            on_audio_chunk=_on_tts_audio_chunk,
            on_stream_complete=_on_tts_stream_complete,
            on_error=_on_tts_error
        )

        async def _on_stt_interim_result(transcript: str):
            await manager.send_json_to_client(session_id, {"type": "stt_interim_result", "transcript": transcript})
        
        async def handle_stt_final_result_with_tts_wrapper(transcript: str): # Wrapper to include tts_service
            await manager.send_json_to_client(session_id, {"type": "stt_final_result", "transcript": transcript})
            if GOOGLE_SERVICES_AVAILABLE and tts_service: # Ensure tts_service is available
                # For voice input, always use TTS
                await handle_text_input(session_id, transcript, tts_service, input_mode="voice")
            else:
                # Fallback if TTS is not available but STT worked
                await handle_text_input_without_tts(session_id, transcript, input_mode="voice")


        async def _on_stt_error(error_msg: str):
            await manager.send_json_to_client(session_id, {"type": "error", "message": f"STT Error: {error_msg}"})

        async def _on_epd_detected():
            # This EPD is from Google STT, signaling end of user's single utterance.
            # Useful for barge-in if client needs to stop its recording or for UI feedback.
            print(f"EPD detected by Google STT for session {session_id}")
            await manager.send_json_to_client(session_id, {"type": "epd_detected"})


        stt_service = StreamSTTService(
            session_id=session_id,
            on_interim_result=_on_stt_interim_result,
            on_final_result=handle_stt_final_result_with_tts_wrapper, # Use the new wrapper
            on_error=_on_stt_error,
            on_epd_detected=_on_epd_detected
        )
        # Do NOT start STT stream automatically here. Wait for client message.
        # await stt_service.start_stream() 
    else:
        print(f"[{session_id}] Google STT/TTS 서비스가 비활성화되어 음성 관련 기능이 제한됩니다.")
        await manager.send_json_to_client(session_id, {
            "type": "warning",
            "message": "음성 인식 및 합성이 현재 지원되지 않습니다. 텍스트로 입력해주세요."
        })

    try:
        while True:
            data = await websocket.receive()
            message_type = None
            payload_dict = None # To hold parsed JSON payload
            raw_payload = None # To hold bytes payload

            if "text" in data:
                try:
                    message_data = json.loads(data["text"])
                    message_type = message_data.get("type")
                    payload_dict = message_data # Keep the parsed dict
                    print(f"WebSocket text received from {session_id}: {message_type} - {payload_dict}")
                except json.JSONDecodeError:
                    print(f"Invalid JSON received from {session_id}: {data['text']}")
                    await manager.send_json_to_client(session_id, {"type": "error", "message": "Invalid JSON format."})
                    continue
            elif "bytes" in data: # This will be audio chunks
                message_type = "audio_chunk"
                raw_payload = data["bytes"]
                # print(f"WebSocket audio chunk received from {session_id}, size: {len(raw_payload)}")

            if message_type == "process_text":
                user_text = payload_dict.get("text")
                input_mode = payload_dict.get("input_mode", "text") # Default to "text" if not specified

                if user_text:
                    if input_mode == "text": # Text input from chatbox
                        print(f"[{session_id}] Processing text input (mode: text, no TTS for AI response)")
                        await handle_text_input_without_tts(session_id, user_text, input_mode="text")
                    else: # Should ideally not happen if "process_text" is only for chatbox. Voice goes via STT.
                          # However, if client sends text with input_mode="voice", handle with TTS.
                        print(f"[{session_id}] Processing text input (mode: {input_mode}, with TTS for AI response)")
                        if tts_service and GOOGLE_SERVICES_AVAILABLE:
                             await handle_text_input(session_id, user_text, tts_service, input_mode="voice")
                        else:
                             await handle_text_input_without_tts(session_id, user_text, input_mode="voice")
                else:
                    await manager.send_json_to_client(session_id, {"type": "error", "message": "No text provided."})

            elif message_type == "audio_chunk":
                if stt_service and GOOGLE_SERVICES_AVAILABLE:
                    await stt_service.process_audio_chunk(raw_payload)
                else:
                    # 음성 서비스 비활성화 또는 STT 서비스 미초기화 상태
                    # print(f"[{session_id}] Audio chunk received but STT service is not active/available.")
                    pass
            
            elif message_type == "activate_voice":
                if stt_service and GOOGLE_SERVICES_AVAILABLE:
                    print(f"[{session_id}] Client requested to activate voice. Starting STT stream.")
                    await stt_service.start_stream()
                    await manager.send_json_to_client(session_id, {"type": "voice_activated"})
                else:
                    await manager.send_json_to_client(session_id, {"type": "error", "message": "음성 인식 서비스를 시작할 수 없습니다."})

            elif message_type == "deactivate_voice":
                if stt_service and GOOGLE_SERVICES_AVAILABLE:
                    print(f"[{session_id}] Client requested to deactivate voice. Stopping STT stream.")
                    await stt_service.stop_stream()
                    await manager.send_json_to_client(session_id, {"type": "voice_deactivated"})
                else:
                    # This case might not be an error if voice was never activated
                    print(f"[{session_id}] Voice deactivation requested, STT service might not be active.")
                    await manager.send_json_to_client(session_id, {"type": "voice_deactivated", "message": "음성 인식이 이미 비활성화 상태일 수 있습니다."})


            elif message_type == "stop_tts": # Client requests to stop TTS playback
                if tts_service and GOOGLE_SERVICES_AVAILABLE:
                    print(f"[{session_id}] Client requested to stop TTS stream.")
                    await tts_service.stop_tts_stream() # Stops backend generation
                    # Client should also stop its own playback
                else:
                     print(f"[{session_id}] TTS 중지 요청 수신, TTS 서비스 비활성 상태")
            
            # EPD, Barge-in related client control messages (legacy, keep for reference or specific client needs)
            # The new activate_voice/deactivate_voice are more explicit for STT control
            elif message_type == "start_recording": # Potentially for client-side VAD start
                if stt_service and GOOGLE_SERVICES_AVAILABLE:
                    # This assumes backend STT stream is already started by "activate_voice"
                    print(f"[{session_id}] Client signaled start_recording (STT stream should be active).")
                else:
                    await manager.send_json_to_client(session_id, {"type": "error", "message": "음성 인식 서비스가 준비되지 않았습니다."})

            elif message_type == "stop_recording": # Potentially for client-side VAD stop
                 if stt_service:
                    print(f"[{session_id}] Client signaled stop_recording.")
                    # Backend STT stream stopping is now handled by "deactivate_voice" or EPD from Google STT.

    except WebSocketDisconnect:
        print(f"WebSocket disconnected by client: {session_id}")
    except Exception as e:
        print(f"WebSocket Error for session {session_id}: {e}")
        import traceback
        traceback.print_exc()
        await manager.send_json_to_client(session_id, {"type": "error", "message": f"Server error: {str(e)}"})
    finally:
        if stt_service: 
            await stt_service.stop_stream()
        if tts_service: 
            await tts_service.stop_tts_stream() # Ensure TTS generation stops
        manager.disconnect(session_id)
        if session_id in SESSION_STATES:
            del SESSION_STATES[session_id]
            print(f"Session state for {session_id} cleared.")


async def handle_text_input_common(session_id: str, user_text: str, input_mode: str) -> Dict:
    """LLM 호출 및 상태 업데이트 공통 로직. input_mode를 AgentState에 추가 가능성 고려."""
    if not user_text:
        return {}

    previous_state_dict = SESSION_STATES.get(session_id, {})
    # Include input_mode in the agent state if your LangGraph agent needs to know
    # For now, it's mainly for differentiating TTS on/off at this API layer
    # previous_state_dict['input_mode'] = input_mode 

    full_ai_response_text = ""
    final_agent_state_data = None

    try:
        # run_agent_streaming now also needs to know about input_mode if agent logic differs
        # For simplicity, we assume run_agent_streaming doesn't need input_mode directly,
        # as TTS decision is made after it.
        async for agent_output_chunk in run_agent_streaming(
            user_input_text=user_text,
            session_id=session_id,
            current_state_dict=previous_state_dict
            # Pass input_mode here if Agent needs it:
            # custom_input_params={"input_mode": input_mode}
        ):
            if isinstance(agent_output_chunk, str):  # LLM 텍스트 청크
                await manager.send_json_to_client(session_id, {"type": "llm_response_chunk", "chunk": agent_output_chunk})
                full_ai_response_text += agent_output_chunk
            elif isinstance(agent_output_chunk, dict):
                if agent_output_chunk.get("type") == "stream_start":
                    await manager.send_json_to_client(session_id, agent_output_chunk)
                elif agent_output_chunk.get("type") == "stream_end":
                    await manager.send_json_to_client(session_id, {"type": "llm_response_end", "full_text": full_ai_response_text})
                elif agent_output_chunk.get("type") == "final_state":
                    final_agent_state_data = agent_output_chunk.get("data")
                    if final_agent_state_data:
                        SESSION_STATES[session_id] = final_agent_state_data
                        full_ai_response_text = final_agent_state_data.get("final_response_text_for_tts", full_ai_response_text)
                        print(f"Session state for {session_id} updated. Final AI response: '{full_ai_response_text[:50]}...'")
        
        return {"full_ai_response_text": full_ai_response_text, "final_agent_state": final_agent_state_data}

    except Exception as e:
        error_msg = f"LLM 또는 Agent 처리 중 오류: {e}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        await manager.send_json_to_client(session_id, {"type": "error", "message": error_msg})
        await manager.send_json_to_client(session_id, {"type": "llm_response_end", "full_text": ""})
        return {"full_ai_response_text": "", "error": error_msg}

# Modified to accept input_mode
async def handle_text_input(session_id: str, user_text: str, tts_service: StreamTTSService, input_mode: str):
    """사용자 텍스트 입력(STT 결과 포함)을 받아 LLM을 호출하고 결과를 스트리밍하며, input_mode에 따라 TTS도 수행."""
    result = await handle_text_input_common(session_id, user_text, input_mode)
    full_ai_response_text = result.get("full_ai_response_text")

    if full_ai_response_text and not result.get("error"):
        # TTS is only for "voice" input mode, handled here as per original logic for STT path
        # For "text" mode, handle_text_input_without_tts is called directly.
        # This function (handle_text_input) is assumed to be called for voice inputs
        # or when TTS is explicitly desired.
        print(f"[{session_id}] Starting TTS for (mode: {input_mode}): {full_ai_response_text[:50]}...")
        await tts_service.start_tts_stream(full_ai_response_text)
    elif result.get("error"):
        print(f"[{session_id}] Error occurred during text input handling (mode: {input_mode}), TTS skipped.")
    else:
        print(f"[{session_id}] No text to synthesize for TTS (mode: {input_mode}).")

# Modified to accept input_mode (primarily for logging consistency)
async def handle_text_input_without_tts(session_id: str, user_text: str, input_mode: str):
    """TTS 서비스 없이 LLM 결과만 처리하는 함수 (Google 서비스 비활성화 또는 input_mode='text' 시)."""
    result = await handle_text_input_common(session_id, user_text, input_mode)
    full_ai_response_text = result.get("full_ai_response_text")

    if result.get("error"):
        print(f"[{session_id}] Error occurred during text input handling (mode: {input_mode}, no TTS).")
    elif not full_ai_response_text:
        print(f"[{session_id}] No text response from LLM (mode: {input_mode}, no TTS).")
    else:
        print(f"[{session_id}] LLM response generated (mode: {input_mode}), TTS skipped: {full_ai_response_text[:50]}...")