# backend/app/api/v1/chat.py

# ... (기존 import 및 ConnectionManager, SESSION_STATES는 동일) ...
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException, status # WebSocketException 추가
import json
from typing import Dict, Optional

from ...graph.agent import run_agent_streaming, AgentState
from ...services.google_services import StreamSTTService, StreamTTSService, GOOGLE_SERVICES_AVAILABLE
from ...core.config import LLM_MODEL_NAME

router = APIRouter()
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
            try:
                await self.active_connections[session_id].send_json(data)
            except WebSocketException as e: # Handle cases where client might have abruptly closed
                print(f"Error sending to client {session_id} (possibly closed): {e}")
                self.disconnect(session_id) # Clean up
            except RuntimeError as e: # Handle "WebSocket is closed" runtime error
                 print(f"RuntimeError sending to client {session_id} (WebSocket is closed): {e}")
                 self.disconnect(session_id)


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
            "message": "안녕하세요! 디딤돌 대출 음성 상담 서비스입니다. 채팅으로 입력하시거나 마이크 버튼을 눌러 말씀해주세요."
        })
    # ... (tts_service, stt_service 콜백 및 초기화는 이전과 동일하게 유지) ...
    if GOOGLE_SERVICES_AVAILABLE:
        async def _on_tts_audio_chunk(audio_chunk_b64: str):
            await manager.send_json_to_client(session_id, {"type": "tts_audio_chunk", "audio_chunk_base64": audio_chunk_b64})
        async def _on_tts_stream_complete():
            await manager.send_json_to_client(session_id, {"type": "tts_stream_end"})
        async def _on_tts_error(error_msg: str):
            await manager.send_json_to_client(session_id, {"type": "error", "message": f"TTS Error: {error_msg}"})
        tts_service = StreamTTSService(session_id=session_id, on_audio_chunk=_on_tts_audio_chunk, on_stream_complete=_on_tts_stream_complete, on_error=_on_tts_error)

        async def _on_stt_interim_result(transcript: str):
            await manager.send_json_to_client(session_id, {"type": "stt_interim_result", "transcript": transcript})
        
        async def handle_stt_final_result_with_tts_wrapper(transcript: str):
            await manager.send_json_to_client(session_id, {"type": "stt_final_result", "transcript": transcript})
            if GOOGLE_SERVICES_AVAILABLE and tts_service:
                await handle_text_input(session_id, transcript, tts_service, input_mode="voice") # 명시적으로 input_mode 전달
            else:
                await handle_text_input_without_tts(session_id, transcript, input_mode="voice") # 명시적으로 input_mode 전달
        async def _on_stt_error(error_msg: str):
            await manager.send_json_to_client(session_id, {"type": "error", "message": f"STT Error: {error_msg}"})
        async def _on_epd_detected():
            print(f"EPD detected by Google STT for session {session_id}")
            await manager.send_json_to_client(session_id, {"type": "epd_detected"})
        stt_service = StreamSTTService(session_id=session_id, on_interim_result=_on_stt_interim_result, on_final_result=handle_stt_final_result_with_tts_wrapper, on_error=_on_stt_error, on_epd_detected=_on_epd_detected)
    else: # GOOGLE_SERVICES_AVAILABLE is False
        print(f"[{session_id}] Google STT/TTS 서비스가 비활성화되어 음성 관련 기능이 제한됩니다.")
        await manager.send_json_to_client(session_id, { "type": "warning", "message": "음성 인식 및 합성이 현재 지원되지 않습니다. 텍스트로 입력해주세요."})

    try:
        while True:
            data = await websocket.receive()
            # ... (메시지 파싱 로직은 이전과 동일하게 유지) ...
            message_type = None; payload_dict = None; raw_payload = None
            if "text" in data:
                try:
                    message_data = json.loads(data["text"]); message_type = message_data.get("type"); payload_dict = message_data
                    # print(f"WS text from {session_id}: {message_type} - {payload_dict}") # 상세 로깅
                except json.JSONDecodeError:
                    print(f"Invalid JSON from {session_id}: {data['text']}")
                    await manager.send_json_to_client(session_id, {"type": "error", "message": "Invalid JSON format."}); continue
            elif "bytes" in data:
                message_type = "audio_chunk"; raw_payload = data["bytes"]
                # print(f"WS audio chunk from {session_id}, size: {len(raw_payload)}") # 상세 로깅

            if message_type == "process_text":
                user_text = payload_dict.get("text")
                input_mode = payload_dict.get("input_mode", "text") 
                if user_text:
                    if input_mode == "text":
                        await handle_text_input_without_tts(session_id, user_text, input_mode="text")
                    else: # "voice" 또는 명시되지 않은 경우, STT 경로를 타는 것이 정상
                        print(f"Warning: 'process_text' received with input_mode='{input_mode}'. Treating as voice for TTS.")
                        if tts_service and GOOGLE_SERVICES_AVAILABLE:
                             await handle_text_input(session_id, user_text, tts_service, input_mode="voice")
                        else:
                             await handle_text_input_without_tts(session_id, user_text, input_mode="voice")
                else: await manager.send_json_to_client(session_id, {"type": "error", "message": "No text provided."})

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
                else: await manager.send_json_to_client(session_id, {"type": "voice_deactivated", "message": "음성 인식이 이미 비활성화 상태일 수 있습니다."})

            elif message_type == "stop_tts": 
                if tts_service and GOOGLE_SERVICES_AVAILABLE:
                    print(f"[{session_id}] Client requested server to stop TTS stream generation.")
                    await tts_service.stop_tts_stream() 
                else: print(f"[{session_id}] TTS stop_tts, TTS service N/A.")
            
    except WebSocketDisconnect: print(f"WebSocket disconnected by client: {session_id}")
    except Exception as e:
        print(f"WebSocket Error for session {session_id}: {e}")
        import traceback; traceback.print_exc()
        await manager.send_json_to_client(session_id, {"type": "error", "message": f"Server error: {str(e)}"})
    finally:
        # ... (finally 블록은 이전과 동일하게 유지, stt/tts 서비스 중지 및 세션 정리) ...
        if stt_service: await stt_service.stop_stream()
        if tts_service: await tts_service.stop_tts_stream()
        manager.disconnect(session_id)
        if session_id in SESSION_STATES: del SESSION_STATES[session_id]; print(f"Session state for {session_id} cleared.")

async def handle_text_input_common(session_id: str, user_text: str, input_mode: str) -> Dict:
    """LLM 호출 및 상태 업데이트 공통 로직. input_mode를 AgentState에 추가 가능성 고려."""
    if not user_text: return {}
    previous_state_dict = SESSION_STATES.get(session_id, {})
    
    # AgentState에 input_mode를 포함시켜 LangGraph 내부에서 활용 가능하도록 할 수 있습니다.
    # 예: initial_input_for_graph['input_mode'] = input_mode
    # 여기서는 로깅 및 TTS 결정에만 사용합니다.
    print(f"handle_text_input_common called for session {session_id}, mode: {input_mode}, text: '{user_text[:30]}...'")


    full_ai_response_text = ""
    final_agent_state_data = None
    try:
        async for agent_output_chunk in run_agent_streaming(
            user_input_text=user_text,
            session_id=session_id,
            current_state_dict=previous_state_dict
            # 만약 agent.py의 run_agent_streaming이 input_mode를 필요로 한다면 여기서 전달합니다.
            # custom_params={"input_mode": input_mode} 
        ):
            if isinstance(agent_output_chunk, str):  
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
                        print(f"Session state for {session_id} updated via final_state. Final AI response: '{full_ai_response_text[:50]}...'")
        
        # 최종적으로 LLM 응답이 있었는지 확인 (final_state 이후 full_ai_response_text가 채워졌을 수 있음)
        if not full_ai_response_text and final_agent_state_data:
            full_ai_response_text = final_agent_state_data.get("final_response_text_for_tts", "")

        return {"full_ai_response_text": full_ai_response_text, "final_agent_state": final_agent_state_data}

    except Exception as e: # ... (오류 처리 로직은 이전과 동일) ...
        error_msg = f"LLM 또는 Agent 처리 중 오류: {e}"; print(error_msg)
        import traceback; traceback.print_exc()
        await manager.send_json_to_client(session_id, {"type": "error", "message": error_msg})
        await manager.send_json_to_client(session_id, {"type": "llm_response_end", "full_text": ""})
        return {"full_ai_response_text": "", "error": error_msg}


async def handle_text_input(session_id: str, user_text: str, tts_service: StreamTTSService, input_mode: str):
    """input_mode가 "voice"일 때 TTS를 포함하여 처리합니다."""
    result = await handle_text_input_common(session_id, user_text, input_mode)
    full_ai_response_text = result.get("full_ai_response_text")

    if full_ai_response_text and not result.get("error") and input_mode == "voice": # TTS는 voice 모드에서만
        print(f"[{session_id}] Starting TTS for (mode: {input_mode}): {full_ai_response_text[:50]}...")
        await tts_service.start_tts_stream(full_ai_response_text)
    elif result.get("error"):
        print(f"[{session_id}] Error during text input handling (mode: {input_mode}), TTS skipped.")
    elif input_mode != "voice":
        print(f"[{session_id}] Text input mode (mode: {input_mode}), TTS skipped as per logic.")
    else: # No text or other conditions
        print(f"[{session_id}] No text to synthesize or other condition met, TTS skipped (mode: {input_mode}).")


async def handle_text_input_without_tts(session_id: str, user_text: str, input_mode: str):
    """input_mode가 "text"이거나 TTS 서비스가 없을 때 호출됩니다."""
    result = await handle_text_input_common(session_id, user_text, input_mode)
    full_ai_response_text = result.get("full_ai_response_text")

    if result.get("error"):
        print(f"[{session_id}] Error during text input handling (mode: {input_mode}, no TTS).")
    elif not full_ai_response_text:
        print(f"[{session_id}] No text response from LLM (mode: {input_mode}, no TTS).")
    else:
        print(f"[{session_id}] LLM response generated (mode: {input_mode}), TTS explicitly skipped: {full_ai_response_text[:50]}...")