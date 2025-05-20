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

    # STT 서비스 인스턴스 (세션별 또는 공유)
    stt_service = StreamSTTService(
        session_id=session_id,
        on_interim_result=lambda transcript: manager.send_json_to_client(session_id, {"type": "stt_interim_result", "transcript": transcript}),
        on_final_result=lambda transcript: handle_stt_final_result(session_id, transcript),
        on_error=lambda error_msg: manager.send_json_to_client(session_id, {"type": "error", "message": f"STT Error: {error_msg}"}),
        on_epd_detected=lambda: manager.send_json_to_client(session_id, {"type": "epd_detected"})
    )

    # TTS 서비스 인스턴스
    tts_service = StreamTTSService(
        session_id=session_id,
        on_audio_chunk=lambda audio_chunk_b64: manager.send_json_to_client(session_id, {"type": "tts_audio_chunk", "audio_chunk_base64": audio_chunk_b64}),
        on_error=lambda error_msg: manager.send_json_to_client(session_id, {"type": "error", "message": f"TTS Error: {error_msg}"}),
        # 만약 스트리밍 URL 방식을 쓴다면 on_stream_url 콜백도 가능
        # on_stream_url=lambda url: manager.send_json_to_client(session_id, {"type": "tts_stream_url", "url": url})
    )

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
        await stt_service.finalize_stream() # STT 리소스 정리
        await tts_service.stop_tts_stream() # TTS 리소스 정리
        manager.disconnect(session_id)
        if session_id in SESSION_STATES: # 세션 상태 정리 (정책에 따라)
            # del SESSION_STATES[session_id]
            pass


async def handle_stt_final_result(session_id: str, transcript: str):
    """STT 최종 결과가 나오면 호출되는 함수. LLM 처리를 시작."""
    await manager.send_json_to_client(session_id, {"type": "stt_final_result", "transcript": transcript})
    # TTS 서비스 인스턴스를 가져오거나 새로 생성 (위 websocket_endpoint의 tts_service를 어떻게 전달할지 고려)
    # 여기서는 간단히 전역 manager를 통해 websocket 객체를 가져와 tts_service를 다시 찾는다고 가정하거나,
    # websocket_endpoint 내에서 이 함수를 호출하며 tts_service를 넘겨줘야 함.
    # 아래는 임시로 new tts_service를 만듦. 실제로는 websocket_endpoint의 tts_service 사용
    temp_tts_service = StreamTTSService(
        session_id=session_id,
        on_audio_chunk=lambda audio_chunk_b64: manager.send_json_to_client(session_id, {"type": "tts_audio_chunk", "audio_chunk_base64": audio_chunk_b64}),
        on_error=lambda error_msg: manager.send_json_to_client(session_id, {"type": "error", "message": f"TTS Error: {error_msg}"})
    )
    await handle_text_input(session_id, transcript, temp_tts_service)


async def handle_text_input(session_id: str, user_text: str, tts_service: StreamTTSService):
    """사용자 텍스트 입력(STT 결과 포함)을 받아 LLM을 호출하고 결과를 스트리밍하는 함수."""
    if not user_text:
        return

    previous_state_dict = SESSION_STATES.get(session_id)
    full_ai_response_text = ""

    try:
        # run_agent_streaming은 텍스트 청크를 비동기적으로 yield해야 함
        async for llm_chunk in run_agent_streaming(
            user_input_text=user_text,
            session_id=session_id,
            current_state_dict=previous_state_dict
        ):
            if isinstance(llm_chunk, str): # 텍스트 청크인 경우
                await manager.send_json_to_client(session_id, {"type": "llm_response_chunk", "chunk": llm_chunk})
                full_ai_response_text += llm_chunk
            elif isinstance(llm_chunk, dict) and llm_chunk.get("type") == "final_state_update":
                # LLM 처리 중 Agent의 최종 상태가 업데이트되면 저장
                SESSION_STATES[session_id] = llm_chunk.get("state", {}) # 혹은 필요한 부분만 업데이트

        await manager.send_json_to_client(session_id, {"type": "llm_response_end"})

        # LLM 응답 완료 후 TTS 시작
        if full_ai_response_text:
            # 여기서 SESSION_STATES[session_id]를 업데이트 할 수도 있음 (예: final_response_text)
            # SESSION_STATES[session_id]["final_response_text_for_tts"] = full_ai_response_text
            # SESSION_STATES[session_id]["collected_loan_info"] = ... (run_agent_streaming에서 반환된 정보)

            # 만약 TTS 서비스가 전체 텍스트를 받아 스트리밍한다면:
            await tts_service.start_tts_stream(full_ai_response_text)
            # 또는 tts_service가 문장 단위로 스트리밍을 지원하고,
            # run_agent_streaming이 문장 단위로 yield 한다면, 그 때마다 tts_service.speak_sentence(sentence) 호출 가능

    except Exception as e:
        error_msg = f"LLM 또는 Agent 처리 중 오류: {e}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        await manager.send_json_to_client(session_id, {"type": "error", "message": error_msg})
        # 오류 발생 시에도 빈 LLM 응답 종료 메시지 전송 (클라이언트가 대기 상태 풀도록)
        await manager.send_json_to_client(session_id, {"type": "llm_response_end"})