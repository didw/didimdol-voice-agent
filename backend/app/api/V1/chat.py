"""
리팩토링된 WebSocket 채팅 엔드포인트
"""

import json
import copy
from typing import Optional, Dict, cast, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage, AIMessage
from ...graph.state import AgentState
from ...services.google_services import StreamSTTService, StreamTTSService, GOOGLE_SERVICES_AVAILABLE
from .websocket_manager import manager
from .chat_handlers import (
    handle_agent_output_chunk,
    handle_slot_filling_update,
    process_tts_for_response,
    get_agent_generator
)
from .chat_utils import get_info_collection_stages, send_slot_filling_update

router = APIRouter()


# 전역 세션 상태
SESSION_STATES: Dict[str, AgentState] = {}
INFO_COLLECTION_STAGES = get_info_collection_stages()


async def websocket_chat_endpoint(websocket: WebSocket):
    """메인 WebSocket 엔드포인트"""
    session_id = await initialize_session(websocket)
    if not session_id:
        return
    
    # Google 서비스 초기화
    tts_service = await initialize_tts_service(session_id) if GOOGLE_SERVICES_AVAILABLE else None
    stt_service = await initialize_stt_service(session_id, tts_service, websocket) if GOOGLE_SERVICES_AVAILABLE else None
    
    try:
        await handle_websocket_messages(websocket, session_id, tts_service, stt_service)
    except WebSocketDisconnect:
        print(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        print(f"WebSocket error for {session_id}: {e}")
        # WebSocket이 이미 닫혔을 수 있으므로 에러 메시지 전송을 시도하지 않음
        try:
            if session_id in manager.active_connections:
                await manager.send_json_to_client(session_id, {
                    "type": "error", 
                    "message": f"Server error: {str(e)}"
                })
        except:
            pass  # 에러 메시지 전송 실패는 무시
    finally:
        await cleanup_session(session_id, stt_service, tts_service)


async def initialize_session(websocket: WebSocket) -> Optional[str]:
    """세션 초기화"""
    await manager.connect(websocket)
    session_id = manager.get_session_id(websocket)
    
    if not session_id:
        print("Failed to create session ID")
        await websocket.close()
        return None
    
    # 세션 상태 초기화
    SESSION_STATES[session_id] = {
        "messages": [],
        "current_product_type": None,
        "active_scenario_data": None,
        "collected_product_info": {},
        "current_scenario_stage_id": "",
        "active_scenario_name": "미정",
        "final_response_text_for_tts": None,
        "error_message": None,
        "is_final_turn_response": False,
        "tts_cancelled": False,
        "router_call_count": 0,
        "correction_mode": False,
        "pending_modifications": None,
    }
    
    print(f"New session initialized: {session_id}")
    
    # 초기 인사 메시지
    greeting = "안녕하세요. 신한은행 AI 금융 상담 서비스입니다. 통장을 새로 만드실꺼면 '통장 만들고싶어요' 와 같이 말씀해주세요"
    await manager.send_json_to_client(session_id, {
        "type": "session_initialized",
        "message": greeting
    })
    
    # 초기 슬롯 필링 상태 전송
    await send_slot_filling_update(websocket, SESSION_STATES[session_id], session_id)
    
    return session_id


async def initialize_tts_service(session_id: str) -> StreamTTSService:
    """TTS 서비스 초기화"""
    async def on_audio_chunk(audio_chunk_b64: str):
        await manager.send_json_to_client(session_id, {
            "type": "tts_audio_chunk", 
            "audio_chunk_base64": audio_chunk_b64
        })
    
    async def on_stream_complete():
        await manager.send_json_to_client(session_id, {
            "type": "tts_stream_end"
        })
    
    async def on_error(error_msg: str):
        await manager.send_json_to_client(session_id, {
            "type": "error", 
            "message": f"TTS Error: {error_msg}"
        })
    
    return StreamTTSService(
        session_id=session_id,
        on_audio_chunk=on_audio_chunk,
        on_stream_complete=on_stream_complete,
        on_error=on_error
    )


async def initialize_stt_service(
    session_id: str, 
    tts_service: StreamTTSService,
    websocket: WebSocket
) -> StreamSTTService:
    """STT 서비스 초기화"""
    async def on_interim_result(transcript: str):
        await manager.send_json_to_client(session_id, {
            "type": "stt_interim_result", 
            "transcript": transcript
        })
    
    async def on_final_result(transcript: str):
        trimmed = transcript.strip()
        await manager.send_json_to_client(session_id, {
            "type": "stt_final_result", 
            "transcript": trimmed
        })
        
        if trimmed:
            await process_input_through_agent(
                session_id, trimmed, tts_service, "voice", websocket
            )
        else:
            await handle_empty_stt_result(session_id, tts_service)
    
    async def on_error(error_msg: str):
        await manager.send_json_to_client(session_id, {
            "type": "error", 
            "message": f"STT Error: {error_msg}"
        })
    
    async def on_epd_detected():
        await manager.send_json_to_client(session_id, {
            "type": "epd_detected"
        })
    
    return StreamSTTService(
        session_id=session_id,
        on_interim_result=on_interim_result,
        on_final_result=on_final_result,
        on_error=on_error,
        on_epd_detected=on_epd_detected
    )


async def handle_websocket_messages(
    websocket: WebSocket,
    session_id: str,
    tts_service: Optional[StreamTTSService],
    stt_service: Optional[StreamSTTService]
) -> None:
    """WebSocket 메시지 처리 루프"""
    while True:
        data = await websocket.receive()
        
        # 메시지 타입 파싱
        message_type, payload = parse_websocket_message(data)
        
        # 메시지 타입별 처리
        if message_type == "process_text":
            await handle_text_input(session_id, payload, tts_service, websocket)
        elif message_type == "activate_voice":
            await handle_voice_activation(session_id, stt_service)
        elif message_type == "deactivate_voice":
            await handle_voice_deactivation(session_id, stt_service)
        elif message_type == "stop_tts":
            await handle_tts_stop(session_id, tts_service)
        elif message_type == "audio_chunk":
            await handle_audio_chunk(session_id, stt_service, payload)
        elif message_type == "user_choice_selection":
            await handle_user_choice_selection(session_id, payload, tts_service, websocket)
        elif message_type == "user_boolean_selection":
            await handle_user_boolean_selection(session_id, payload, tts_service, websocket)


def parse_websocket_message(data: dict) -> tuple[str, Any]:
    """WebSocket 메시지 파싱"""
    if "text" in data:
        try:
            message_data = json.loads(data["text"])
            return message_data.get("type"), message_data
        except json.JSONDecodeError:
            return None, None
    elif "bytes" in data:
        return "audio_chunk", data["bytes"]
    return None, None


async def handle_text_input(
    session_id: str,
    payload: dict,
    tts_service: Optional[StreamTTSService],
    websocket: WebSocket
) -> None:
    """텍스트 입력 처리"""
    user_text = payload.get("text")
    if user_text:
        await process_input_through_agent(
            session_id, user_text, tts_service, "text", websocket
        )
    else:
        await manager.send_json_to_client(session_id, {
            "type": "error", 
            "message": "No text provided."
        })


async def handle_voice_activation(
    session_id: str,
    stt_service: Optional[StreamSTTService]
) -> None:
    """음성 인식 활성화"""
    if stt_service and GOOGLE_SERVICES_AVAILABLE:
        print(f"[{session_id}] Activating voice")
        await stt_service.start_stream()
        await manager.send_json_to_client(session_id, {"type": "voice_activated"})
    else:
        await manager.send_json_to_client(session_id, {
            "type": "error", 
            "message": "음성 인식 서비스를 시작할 수 없습니다."
        })


async def handle_voice_deactivation(
    session_id: str,
    stt_service: Optional[StreamSTTService]
) -> None:
    """음성 인식 비활성화"""
    if stt_service and GOOGLE_SERVICES_AVAILABLE:
        print(f"[{session_id}] Deactivating voice")
        await stt_service.stop_stream()
        await manager.send_json_to_client(session_id, {"type": "voice_deactivated"})


async def handle_tts_stop(
    session_id: str,
    tts_service: Optional[StreamTTSService]
) -> None:
    """TTS 중지"""
    if tts_service and GOOGLE_SERVICES_AVAILABLE:
        print(f"[{session_id}] Stopping TTS")
        if session_id in SESSION_STATES:
            SESSION_STATES[session_id]['tts_cancelled'] = True
        await tts_service.stop_tts_stream()


async def handle_audio_chunk(
    session_id: str,
    stt_service: Optional[StreamSTTService],
    audio_data: bytes
) -> None:
    """오디오 청크 처리"""
    if stt_service and GOOGLE_SERVICES_AVAILABLE:
        await stt_service.process_audio_chunk(audio_data)


async def handle_user_choice_selection(
    session_id: str,
    payload: dict,
    tts_service: Optional[StreamTTSService],
    websocket: WebSocket
) -> None:
    """사용자 선택지 처리"""
    stage_id = payload.get("stageId")
    choice = payload.get("selectedChoice")  # 프론트엔드에서 보내는 키명에 맞춤
    
    if not stage_id or not choice:
        await manager.send_json_to_client(session_id, {
            "type": "error",
            "message": f"stageId와 selectedChoice가 필요합니다. 받은 데이터: {payload}"
        })
        return
    
    print(f"[{session_id}] User choice selection: {stage_id} -> {choice}")
    
    # 사용자 선택을 에이전트로 전달
    await process_input_through_agent(
        session_id, choice, tts_service, "choice", websocket
    )


async def handle_user_boolean_selection(
    session_id: str,
    payload: dict,
    tts_service: Optional[StreamTTSService],
    websocket: WebSocket
) -> None:
    """사용자 불린 선택 처리"""
    stage_id = payload.get("stageId")
    selections = payload.get("booleanSelections")  # 프론트엔드에서 보내는 키명에 맞춤
    
    if not stage_id or not selections:
        await manager.send_json_to_client(session_id, {
            "type": "error",
            "message": f"stageId와 booleanSelections가 필요합니다. 받은 데이터: {payload}"
        })
        return
    
    print(f"[{session_id}] User boolean selection: {stage_id} -> {selections}")
    
    # 불린 선택을 문자열로 변환하여 에이전트로 전달
    selection_text = ", ".join([
        f"{key}: {'신청' if value else '미신청'}" 
        for key, value in selections.items()
    ])
    
    # boolean 선택을 collected_product_info에 직접 저장
    current_state = SESSION_STATES.get(session_id)
    if current_state:
        collected_info = current_state.get("collected_product_info", {})
        # boolean 선택 항목들을 직접 저장
        for key, value in selections.items():
            collected_info[key] = value
            print(f"[{session_id}] Saving boolean field '{key}' = {value}")
        current_state["collected_product_info"] = collected_info
        SESSION_STATES[session_id] = current_state
        print(f"[{session_id}] Boolean selections directly saved to collected_product_info: {selections}")
        print(f"[{session_id}] Updated collected_product_info: {collected_info}")
    
    await process_input_through_agent(
        session_id, selection_text, tts_service, "boolean", websocket
    )


async def handle_empty_stt_result(
    session_id: str,
    tts_service: Optional[StreamTTSService]
) -> None:
    """빈 STT 결과 처리"""
    print(f"[{session_id}] Empty STT result")
    reprompt = "죄송합니다, 잘 이해하지 못했어요. 다시 한번 말씀해주시겠어요?"
    
    await manager.send_json_to_client(session_id, {
        "type": "llm_response_chunk", 
        "chunk": reprompt
    })
    await manager.send_json_to_client(session_id, {
        "type": "llm_response_end", 
        "full_text": reprompt
    })
    
    if session_id in SESSION_STATES:
        SESSION_STATES[session_id]["messages"].append(AIMessage(content=reprompt))
    
    if tts_service and GOOGLE_SERVICES_AVAILABLE:
        await tts_service.start_tts_stream(reprompt)


async def process_input_through_agent(
    session_id: str,
    user_text: str,
    tts_service: Optional[StreamTTSService],
    input_mode: str,
    websocket: WebSocket
) -> None:
    """에이전트를 통한 입력 처리"""
    print(f"\n{'='*60}")
    print(f"[{session_id}] 🚀 DEBUG LOG START - Processing user input")
    print(f"[{session_id}] User text: '{user_text[:50]}...'")
    print(f"{'='*60}\n")
    
    current_state = SESSION_STATES.get(session_id)
    if not current_state:
        print(f"[{session_id}] Session state not found")
        await manager.send_json_to_client(session_id, {
            "type": "error", 
            "message": "세션 정보를 찾을 수 없습니다."
        })
        return
    
    
    # TTS 취소 플래그 초기화
    SESSION_STATES[session_id]['tts_cancelled'] = False
    
    # 새로운 LLM 기반 에이전트 사용
    product_type = current_state.get("current_product_type", "")
    
    
    full_ai_response_text = ""
    # deep copy를 사용하여 previous_state 생성
    previous_state = {
        "collected_product_info": copy.deepcopy(current_state.get("collected_product_info", {})),
        "scenario_data": current_state.get("active_scenario_data"),
        "product_type": product_type,
        "current_scenario_stage_id": current_state.get("current_scenario_stage_id", "")
    }
    
    try:
        # 에이전트 출력 처리
        async for chunk in get_agent_generator(
            user_text, session_id, current_state, websocket
        ):
            full_ai_response_text, stream_ended, final_data = await handle_agent_output_chunk(
                chunk, session_id, websocket, SESSION_STATES, full_ai_response_text
            )
            
            if final_data:
                
                # final_data가 dict인지 확인하고 기존 SESSION_STATES 업데이트
                if session_id in SESSION_STATES:
                    # 기존 상태를 유지하면서 새로운 데이터로 업데이트
                    existing_state = SESSION_STATES[session_id]
                    if isinstance(existing_state, dict):
                        existing_state.update(final_data)
                        SESSION_STATES[session_id] = existing_state
                    else:
                        # AgentState 인스턴스인 경우
                        for key, value in final_data.items():
                            existing_state[key] = value
                        SESSION_STATES[session_id] = existing_state
                else:
                    SESSION_STATES[session_id] = cast(AgentState, final_data)
                
                current_state = SESSION_STATES[session_id]
                
                # 슬롯 필링 업데이트
                await handle_slot_filling_update(
                    session_id, websocket, current_state, 
                    previous_state, INFO_COLLECTION_STAGES
                )
            
            if stream_ended and chunk.get("type") == "error":
                break
        
        # 디버그 로그 종료 - collected_info 출력
        final_collected_info = current_state.get("collected_product_info", {}) if current_state else {}
        print(f"\n{'='*60}")
        print(f"[{session_id}] 🏁 DEBUG LOG END - Processing Complete")
        print(f"[{session_id}] Final collected_info:")
        if final_collected_info:
            for key, value in final_collected_info.items():
                print(f"[{session_id}]   - {key}: {value}")
        else:
            print(f"[{session_id}]   (No data collected)")
        print(f"{'='*60}\n")
        
        # TTS 처리
        await process_tts_for_response(
            session_id, full_ai_response_text, tts_service, 
            input_mode, current_state
        )
        
    except Exception as e:
        print(f"[{session_id}] Agent processing error: {e}")
        # 에러 상황에서도 collected_info 출력
        error_collected_info = current_state.get("collected_product_info", {}) if current_state else {}
        print(f"\n{'='*60}")
        print(f"[{session_id}] 🚫 DEBUG LOG END - Error Occurred")
        print(f"[{session_id}] Error: {str(e)}")
        print(f"[{session_id}] Final collected_info:")
        if error_collected_info:
            for key, value in error_collected_info.items():
                print(f"[{session_id}]   - {key}: {value}")
        else:
            print(f"[{session_id}]   (No data collected)")
        print(f"{'='*60}\n")
        # WebSocket이 이미 닫혔을 수 있으므로 에러 메시지 전송을 시도하지 않음
        try:
            if session_id in manager.active_connections:
                await manager.send_json_to_client(session_id, {
                    "type": "error", 
                    "message": f"처리 중 오류: {str(e)}"
                })
        except:
            pass  # 에러 메시지 전송 실패는 무시


async def cleanup_session(
    session_id: str,
    stt_service: Optional[StreamSTTService],
    tts_service: Optional[StreamTTSService]
) -> None:
    """세션 정리"""
    try:
        # Google 서비스 정리
        if stt_service:
            try:
                await stt_service.stop_stream()
            except Exception as e:
                print(f"Error stopping STT service for {session_id}: {e}")
        
        if tts_service:
            try:
                await tts_service.stop_tts_stream()
            except Exception as e:
                print(f"Error stopping TTS service for {session_id}: {e}")
        
        # WebSocket 연결 해제
        manager.disconnect(session_id)
        
        # 세션 상태 삭제
        if session_id in SESSION_STATES:
            del SESSION_STATES[session_id]
            print(f"Session cleaned up: {session_id}")
    except Exception as e:
        print(f"Error during cleanup for session {session_id}: {e}")


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket 엔드포인트 - 세션 ID 기반"""
    await websocket_chat_endpoint(websocket)