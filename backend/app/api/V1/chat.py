# backend/app/api/v1/chat.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
from typing import Dict

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

    if session_id not in SESSION_STATES:
        SESSION_STATES[session_id] = {} # 초기 AgentState (빈 dict 또는 TypedDict 구조체)
        print(f"New session initialized for {session_id}")
        await manager.send_json_to_client(session_id, {
            "type": "session_initialized",
            "message": "안녕하세요! 디딤돌 대출 음성 상담 서비스입니다. 무엇을 도와드릴까요?"
        })
    else:
        print(f"Existing session loaded for {session_id}")
        # TODO: 이전 대화 이력 요약 등을 클라이언트에 전달하여 대화 이어가기 기능 구현 가능

    stt_service = None
    tts_service = None

    if GOOGLE_SERVICES_AVAILABLE:
        tts_service = StreamTTSService(
            session_id=session_id,
            on_audio_chunk=lambda audio_chunk_b64: manager.send_json_to_client(session_id, {"type": "tts_audio_chunk", "audio_chunk_base64": audio_chunk_b64}),
            on_stream_complete=lambda: manager.send_json_to_client(session_id, {"type": "tts_stream_end"}),
            on_error=lambda error_msg: manager.send_json_to_client(session_id, {"type": "error", "message": f"TTS Error: {error_msg}"})
        )

        async def handle_stt_final_result_with_tts(transcript: str):
            await manager.send_json_to_client(session_id, {"type": "stt_final_result", "transcript": transcript})
            if tts_service: # tts_service가 초기화 되었는지 확인
                await handle_text_input(session_id, transcript, tts_service)
            else: # tts_service가 없는 경우 (Google 서비스 비활성화 등)
                await handle_text_input_without_tts(session_id, transcript)


        stt_service = StreamSTTService(
            session_id=session_id,
            on_interim_result=lambda transcript: manager.send_json_to_client(session_id, {"type": "stt_interim_result", "transcript": transcript}),
            on_final_result=handle_stt_final_result_with_tts,
            on_error=lambda error_msg: manager.send_json_to_client(session_id, {"type": "error", "message": f"STT Error: {error_msg}"}),
            on_epd_detected=lambda: manager.send_json_to_client(session_id, {"type": "epd_detected"})
        )
        await stt_service.start_stream()
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
            payload = None

            if "text" in data:
                try:
                    message_data = json.loads(data["text"])
                    message_type = message_data.get("type")
                    payload = message_data
                    print(f"WebSocket text received from {session_id}: {message_type} - {payload}")
                except json.JSONDecodeError:
                    print(f"Invalid JSON received from {session_id}: {data['text']}")
                    await manager.send_json_to_client(session_id, {"type": "error", "message": "Invalid JSON format."})
                    continue
            elif "bytes" in data:
                message_type = "audio_chunk"
                payload = data["bytes"]
                # print(f"WebSocket audio chunk received from {session_id}, size: {len(payload)}")


            if message_type == "process_text":
                user_text = payload.get("text")
                if user_text:
                    if tts_service:
                        await handle_text_input(session_id, user_text, tts_service)
                    else:
                        await handle_text_input_without_tts(session_id, user_text)


            elif message_type == "audio_chunk":
                if stt_service:
                    await stt_service.process_audio_chunk(payload)
                else:
                    # 음성 서비스 비활성화 시 무시 또는 오류 안내
                    pass
            
            elif message_type == "stop_tts":
                if tts_service:
                    await tts_service.stop_tts_stream()
                else:
                     print(f"[{session_id}] TTS 중지 요청 수신, TTS 서비스 비활성 상태")


            # EPD, Barge-in 관련 클라이언트 제어 메시지 (예: 녹음 시작/중지)
            elif message_type == "start_recording":
                if stt_service:
                    # await stt_service.start_stream() # 이미 연결시 자동 시작되도록 설계, 필요시 명시적 재시작
                    print(f"[{session_id}] Client requested to start recording (STT stream should be active).")
                else:
                    await manager.send_json_to_client(session_id, {"type": "error", "message": "음성 인식 서비스가 준비되지 않았습니다."})

            elif message_type == "stop_recording":
                 if stt_service:
                    # await stt_service.stop_stream() # EPD로 자동 중지되도록 설계, 필요시 명시적 중지
                    print(f"[{session_id}] Client requested to stop recording.")


    except WebSocketDisconnect:
        print(f"WebSocket disconnected by client: {session_id}")
    except Exception as e:
        print(f"WebSocket Error for session {session_id}: {e}")
        import traceback
        traceback.print_exc()
        await manager.send_json_to_client(session_id, {"type": "error", "message": f"Server error: {str(e)}"})
    finally:
        if stt_service: await stt_service.stop_stream()
        if tts_service: await tts_service.stop_tts_stream()
        manager.disconnect(session_id)
        if session_id in SESSION_STATES:
            del SESSION_STATES[session_id] # 세션 정리
            print(f"Session state for {session_id} cleared.")


async def handle_text_input_common(session_id: str, user_text: str) -> Dict:
    """LLM 호출 및 상태 업데이트 공통 로직"""
    if not user_text:
        return {}

    previous_state_dict = SESSION_STATES.get(session_id, {})
    full_ai_response_text = ""
    final_agent_state_data = None

    try:
        async for agent_output_chunk in run_agent_streaming(
            user_input_text=user_text,
            session_id=session_id,
            current_state_dict=previous_state_dict
        ):
            if isinstance(agent_output_chunk, str):  # LLM 텍스트 청크
                await manager.send_json_to_client(session_id, {"type": "llm_response_chunk", "chunk": agent_output_chunk})
                full_ai_response_text += agent_output_chunk
            elif isinstance(agent_output_chunk, dict):
                if agent_output_chunk.get("type") == "stream_start":
                    await manager.send_json_to_client(session_id, agent_output_chunk)
                elif agent_output_chunk.get("type") == "stream_end":
                    await manager.send_json_to_client(session_id, {"type": "llm_response_end", "full_text": full_ai_response_text}) # full_text 명시적으로 전송
                elif agent_output_chunk.get("type") == "final_state":
                    final_agent_state_data = agent_output_chunk.get("data")
                    if final_agent_state_data:
                        SESSION_STATES[session_id] = final_agent_state_data
                        # final_response_text_for_tts는 final_state_data 안에 이미 포함되어 있어야 함
                        full_ai_response_text = final_agent_state_data.get("final_response_text_for_tts", full_ai_response_text)
                        print(f"Session state for {session_id} updated. Final AI response for TTS: '{full_ai_response_text[:50]}...'")

        return {"full_ai_response_text": full_ai_response_text, "final_agent_state": final_agent_state_data}

    except Exception as e:
        error_msg = f"LLM 또는 Agent 처리 중 오류: {e}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        await manager.send_json_to_client(session_id, {"type": "error", "message": error_msg})
        await manager.send_json_to_client(session_id, {"type": "llm_response_end", "full_text": ""}) # 빈 응답으로 종료
        return {"full_ai_response_text": "", "error": error_msg}


async def handle_text_input(session_id: str, user_text: str, tts_service: StreamTTSService):
    """사용자 텍스트 입력(STT 결과 포함)을 받아 LLM을 호출하고 결과를 스트리밍하며 TTS도 수행하는 함수."""
    result = await handle_text_input_common(session_id, user_text)
    full_ai_response_text = result.get("full_ai_response_text")

    if full_ai_response_text and not result.get("error"):
        print(f"[{session_id}] Starting TTS for: {full_ai_response_text[:50]}...")
        await tts_service.start_tts_stream(full_ai_response_text)
    elif result.get("error"):
        # 이미 에러 메시지는 handle_text_input_common에서 클라이언트로 전송됨
        print(f"[{session_id}] Error occurred during text input handling, TTS skipped.")
    else:
        print(f"[{session_id}] No text to synthesize for TTS.")

async def handle_text_input_without_tts(session_id: str, user_text: str):
    """TTS 서비스 없이 LLM 결과만 처리하는 함수 (Google 서비스 비활성화 시 등)"""
    result = await handle_text_input_common(session_id, user_text)
    full_ai_response_text = result.get("full_ai_response_text")

    if result.get("error"):
        print(f"[{session_id}] Error occurred during text input handling (no TTS).")
    elif not full_ai_response_text:
        print(f"[{session_id}] No text response from LLM (no TTS).")
    else:
        print(f"[{session_id}] LLM response generated, TTS skipped as service is unavailable: {full_ai_response_text[:50]}...")


# (참고) 기존의 HTTP 엔드포인트들은 WebSocket으로 기능이 통합되었으므로 제거 또는 주석 처리.
# @router.post("/process_message", ...)
# @router.post("/stream_tts", ...)