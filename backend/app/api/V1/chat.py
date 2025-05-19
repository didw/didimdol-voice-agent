from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse
import base64
from typing import Dict, Optional # Optional, Dict 임포트 추가

# 상대 경로 수정: .... -> ...
from ...schemas.chat_schemas import UserMessage, AIMessage
from ...graph.agent import run_agent, AgentState # AgentState 타입 임포트 (type hinting용)
from ...services.google_services import synthesize_text_to_audio_bytes # 임포트 주석 해제 및 경로 수정

router = APIRouter()

# --- 세션 상태 저장소 (데모용 인메모리 딕셔너리) ---
# 프로덕션에서는 Redis, DB 등을 사용해야 합니다.
SESSION_STATES: Dict[str, AgentState] = {}


@router.post("/process_message", response_model=AIMessage)
async def process_user_message(message: UserMessage):
    print(f"수신 메시지: 세션 ID({message.session_id}), 텍스트({message.text is not None}), 오디오({message.audio_bytes_str is not None})")

    if not message.text and not message.audio_bytes_str:
        raise HTTPException(status_code=400, detail="텍스트 또는 오디오 입력이 필요합니다.")

    session_id = message.session_id or "default_session" # 세션 ID가 없으면 기본값 사용

    # 이전 대화 상태 로드 (데모용)
    # current_state_dict의 타입을 AgentState의 모든 필드가 Optional인 형태로 정의하거나,
    # run_agent 호출 시 필요한 최소한의 정보만 넘기고 나머지는 AgentState 내부에서 None으로 처리하도록 할 수 있습니다.
    # 여기서는 AgentState의 부분집합을 나타내는 Dict로 처리합니다.
    previous_state_dict: Optional[Dict] = SESSION_STATES.get(session_id)
    print(f"세션 [{session_id}] 이전 상태 로드: {bool(previous_state_dict)}")

    try:
        final_state: AgentState = await run_agent( # 반환 타입을 AgentState로 명시
            user_input_text=message.text,
            user_input_audio_b64=message.audio_bytes_str,
            session_id=session_id,
            current_state_dict=previous_state_dict # 이전 상태 전달
        )

        # 현재 턴의 최종 상태를 다음 턴을 위해 저장 (데모용)
        # final_state는 AgentState 타입의 딕셔너리입니다.
        # agent.py에서 반환되는 final_state가 AgentState 타입의 TypedDict이므로 바로 저장 가능
        SESSION_STATES[session_id] = final_state.copy() # 다음 사용을 위해 상태 저장 (복사본 저장)
        print(f"세션 [{session_id}] 현재 상태 저장 완료.")

        if final_state.get("error_message") and not final_state.get("is_final_turn_response"):
             return AIMessage(
                session_id=session_id,
                text=f"처리 중 오류: {final_state.get('error_message')}",
                tts_audio_base64=None, # 오류 시 오디오는 없음
                is_final=True,
                debug_info={
                    "current_stage": final_state.get("current_scenario_stage_id"),
                    "error_details": final_state.get("error_message")
                    # "full_graph_state": final_state # 필요시
                }
            )

        response_text = final_state.get("llm_response_text", "응답을 생성하지 못했습니다.")
        tts_audio_base64 = final_state.get("tts_audio_b64")

        return AIMessage(
            session_id=session_id,
            text=response_text,
            tts_audio_base64=tts_audio_base64,
            debug_info={
                "current_stage": final_state.get("current_scenario_stage_id"),
                "collected_info": final_state.get("collected_loan_info"),
            },
            is_final=True
        )

    except Exception as e:
        print(f"메시지 처리 중 심각한 API 레벨 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"서버 내부 오류: {str(e)}")


@router.post("/stream_tts")
async def stream_text_to_speech(message: UserMessage):
    if not message.text:
        raise HTTPException(status_code=400, detail="TTS로 변환할 텍스트가 없습니다.")

    async def tts_audio_streamer(text_to_speak: str):
        try:
            audio_bytes = await synthesize_text_to_audio_bytes(text_to_speak)
            yield audio_bytes
        except Exception as e:
            print(f"TTS 스트리밍 중 오류: {e}")
            error_message = f'{{"error": "TTS 생성 중 오류 발생: {str(e)}"}}'
            yield error_message.encode('utf-8')

    return StreamingResponse(tts_audio_streamer(message.text), media_type="audio/mpeg")


# --- WebSocket 엔드포인트 (고급 기능, 양방향 스트리밍) ---
# WebSocket을 사용하면 STT, LLM, TTS 전체를 스트리밍으로 주고받을 수 있어 반응성이 극대화됩니다.
# 구현 복잡도는 증가합니다.
# class ConnectionManager:
#     def __init__(self):
#         self.active_connections: list[WebSocket] = []
#
#     async def connect(self, websocket: WebSocket):
#         await websocket.accept()
#         self.active_connections.append(websocket)
#
#     def disconnect(self, websocket: WebSocket):
#         self.active_connections.remove(websocket)
#
#     async def broadcast_text(self, message: str, websocket: WebSocket):
#         await websocket.send_text(message)

# manager = ConnectionManager()

# @router.websocket("/ws/{session_id}")
# async def websocket_endpoint(websocket: WebSocket, session_id: str):
#     await manager.connect(websocket)
#     try:
#         while True:
#             data = await websocket.receive() # json, text, bytes 모두 가능
#             # data_type = data.get("type")
#             # if data_type == "audio_chunk":
#             #   # STT 스트리밍 처리
#             # elif data_type == "text_message":
#             #   # LLM 처리 -> TTS 스트리밍
#
#             # 예시: 받은 텍스트 에코
#             if "text" in data:
#                 await manager.broadcast_text(f"Session {session_id} says: {data['text']}", websocket)
#             elif "bytes" in data: # 음성 데이터 처리 (예시)
#                 # audio_bytes = data["bytes"]
#                 # stt_result = await transcribe_audio_bytes(audio_bytes)
#                 # await manager.broadcast_text(f"STT: {stt_result}", websocket)
#                 pass

#     except WebSocketDisconnect:
#         manager.disconnect(websocket)
#         print(f"WebSocket disconnected: {session_id}")
#     except Exception as e:
#         print(f"WebSocket Error for {session_id}: {e}")
#         await websocket.close(code=1011) # Internal server error