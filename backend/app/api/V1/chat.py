# backend/app/api/v1/chat.py
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import StreamingResponse # TTS 스트리밍 URL 방식 시 사용 가능
import base64
import json
from typing import Dict, Optional, Any

from ...schemas.chat_schemas import UserMessage, AIMessage # 기존 스키마 활용 가능
from ...graph.agent import run_agent_streaming, AgentState # 스트리밍 지원하는 agent 함수로 변경 가정
from ...services.google_services import (
    synthesize_text_to_audio_bytes, # 단건 TTS 용 (필요시)
    # stream_synthesize_text_to_audio, # TTS 스트리밍 생성 함수 (새로 만들어야 함)
    # stream_speech_to_text # STT 스트리밍 함수 (새로 만들어야 함)
)
from ...services.google_services import StreamSTTService, StreamTTSService # 예시: STT 스트리밍 서비스 클래스


router = APIRouter()

# --- 세션 상태 저장소 (프로덕션에서는 Redis 등 권장) ---
SESSION_STATES: Dict[str, AgentState] = {} # 기존 AgentState 또는 확장된 상태 관리

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {} # session_id: WebSocket

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

    async def broadcast_json(self, data: dict): # 모든 연결에 브로드캐스트 (필요시)
        for session_id in self.active_connections:
            await self.send_json_to_client(session_id, data)

manager = ConnectionManager()

# (주석처리) 기존 HTTP 엔드포인트 - WebSocket으로 기능 이전 또는 병행 운영 가능
# @router.post("/process_message", response_model=AIMessage) ...

# @router.post("/stream_tts") ... # WebSocket 내에서 TTS 스트리밍 처리 권장


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect(websocket, session_id)

    # 세션 상태 초기화 또는 로드
    if session_id not in SESSION_STATES:
        # 새로운 AgentState를 만들거나, 초기 상태를 정의합니다.
        # 예를 들어, AgentState가 TypedDict라면:
        # SESSION_STATES[session_id] = AgentState(history=[], collected_loan_info={}, ...)
        # 또는 이전처럼 None으로 시작하고 run_agent 내부에서 처리할 수도 있습니다.
        SESSION_STATES[session_id] = {} # 혹은 적절한 초기 AgentState
        print(f"New session initialized for {session_id}")
        await manager.send_json_to_client(session_id, {
            "type": "session_initialized",
            "message": "안녕하세요! 디딤돌 대출 상담을 시작합니다. 무엇을 도와드릴까요?"
        })
    else:
        print(f"Existing session loaded for {session_id}")
        # 필요시 이전 대화 요약 등을 클라이언트에게 전달 가능

    async def send_stt_interim_result(transcript: str):
        await manager.send_json_to_client(session_id, {"type": "stt_interim_result", "transcript": transcript})

    async def send_stt_error(error_msg: str):
        await manager.send_json_to_client(session_id, {"type": "error", "message": f"STT Error: {error_msg}"})

    async def send_epd_detected():
        await manager.send_json_to_client(session_id, {"type": "epd_detected"})

    # TTS 서비스 인스턴스 먼저 생성 (handle_stt_final_result에 전달하기 위함)
    tts_service = StreamTTSService(
        session_id=session_id,
        on_audio_chunk=lambda audio_chunk_b64: manager.send_json_to_client(session_id, {"type": "tts_audio_chunk", "audio_chunk_base64": audio_chunk_b64}),
        on_stream_complete=lambda: manager.send_json_to_client(session_id, {"type": "tts_stream_end"}), # TTS 스트림 종료 명시
        on_error=lambda error_msg: manager.send_json_to_client(session_id, {"type": "error", "message": f"TTS Error: {error_msg}"})
    )

    # STT 서비스 인스턴스, tts_service를 콜백에서 사용할 수 있도록 내부 함수 정의
    async def stt_final_result_handler_with_tts(transcript: str):
        await handle_stt_final_result(session_id, transcript, tts_service) # tts_service 전달

    stt_service = StreamSTTService(
        session_id=session_id,
        on_interim_result=send_stt_interim_result,
        on_final_result=stt_final_result_handler_with_tts, # 수정된 핸들러 사용
        on_error=send_stt_error,
        on_epd_detected=send_epd_detected
    )
    # STT 스트림 시작 (만약 자동 시작이 아니라면, 클라이언트 요청 시 시작)
    await stt_service.start_stream()


    try:
        while True:
            data = await websocket.receive()
            if "text" in data: # 텍스트 메시지 (JSON 형식 가정)
                message_data = json.loads(data["text"])
                print(f"WebSocket text received from {session_id}: {message_data}")

                if message_data.get("type") == "process_text":
                    user_text = message_data.get("text")
                    if user_text:
                        await handle_text_input(session_id, user_text, tts_service)

                elif message_data.get("type") == "stop_tts": # 클라이언트가 TTS 중단 요청
                    await tts_service.stop_tts_stream() # TTS 서비스에 중단 요청

                # 기타 제어 메시지 처리 ...

            elif "bytes" in data: # 오디오 청크 (Blob 직접 수신)
                audio_chunk = data["bytes"]
                # print(f"WebSocket audio chunk received from {session_id}, size: {len(audio_chunk)}")
                await stt_service.process_audio_chunk(audio_chunk)


    except WebSocketDisconnect:
        print(f"WebSocket disconnected by client: {session_id}")
    except Exception as e:
        print(f"WebSocket Error for session {session_id}: {e}")
        import traceback
        traceback.print_exc()
        await manager.send_json_to_client(session_id, {"type": "error", "message": f"Server error: {str(e)}"})
    finally:
        await stt_service.stop_stream() # 수정된 메소드명
        await tts_service.stop_tts_stream()
        manager.disconnect(session_id)


async def handle_stt_final_result(session_id: str, transcript: str, tts_service: StreamTTSService): # tts_service 인자 추가
    """STT 최종 결과가 나오면 호출되는 함수. LLM 처리를 시작."""
    await manager.send_json_to_client(session_id, {"type": "stt_final_result", "transcript": transcript})
    await handle_text_input(session_id, transcript, tts_service) # 전달받은 tts_service 사용


async def handle_text_input(session_id: str, user_text: str, tts_service: StreamTTSService):
    """사용자 텍스트 입력(STT 결과 포함)을 받아 LLM을 호출하고 결과를 스트리밍하는 함수."""
    if not user_text:
        return

    previous_state_dict = SESSION_STATES.get(session_id)
    full_ai_response_text = ""

    try:
        async for agent_output_chunk in run_agent_streaming( # 변수명 변경
            user_input_text=user_text,
            session_id=session_id,
            current_state_dict=previous_state_dict
        ):
            if isinstance(agent_output_chunk, str): # LLM 텍스트 청크
                await manager.send_json_to_client(session_id, {"type": "llm_response_chunk", "chunk": agent_output_chunk})
                full_ai_response_text += agent_output_chunk
            elif isinstance(agent_output_chunk, dict):
                if agent_output_chunk.get("type") == "stream_start":
                    await manager.send_json_to_client(session_id, agent_output_chunk)
                elif agent_output_chunk.get("type") == "stream_end":
                     # LLM 텍스트 스트리밍 종료, full_ai_response_text는 이미 누적됨
                    await manager.send_json_to_client(session_id, agent_output_chunk) # 여기에는 full_text 포함
                elif agent_output_chunk.get("type") == "final_state": # 최종 상태 업데이트
                    final_agent_state = agent_output_chunk.get("data")
                    if final_agent_state:
                        SESSION_STATES[session_id] = final_agent_state
                        print(f"Session state for {session_id} updated after agent run.")
                    # full_ai_response_text는 stream_end에서 이미 처리되거나 final_state에 포함될 수 있음.
                    # TTS는 final_state에 있는 final_response_text_for_tts를 사용하도록 agent.py에서 보장.
                    if final_agent_state and final_agent_state.get("final_response_text_for_tts"):
                        full_ai_response_text = final_agent_state.get("final_response_text_for_tts")

        # LLM 텍스트 스트리밍 및 최종 상태 처리 완료 후 TTS 시작
        if full_ai_response_text:
            print(f"[{session_id}] Starting TTS for: {full_ai_response_text[:50]}...")
            await tts_service.start_tts_stream(full_ai_response_text)
        else:
            print(f"[{session_id}] No text to synthesize for TTS.")

    except Exception as e:
        error_msg = f"LLM 또는 Agent 처리 중 오류: {e}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        await manager.send_json_to_client(session_id, {"type": "error", "message": error_msg})
        # 오류 발생 시에도 빈 LLM 응답 종료 메시지 전송 (클라이언트가 대기 상태 풀도록)
        await manager.send_json_to_client(session_id, {"type": "llm_response_end"})