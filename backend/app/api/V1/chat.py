# backend/app/api/v1/chat.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException, status
import json
from typing import Dict, Optional, cast

from ...graph.agent import run_agent_streaming, AgentState # AgentState 임포트
from ...services.google_services import StreamSTTService, StreamTTSService, GOOGLE_SERVICES_AVAILABLE
from ...core.config import LLM_MODEL_NAME

router = APIRouter()
# SESSION_STATES는 이제 AgentState 전체를 저장하거나, 필요한 주요 필드(current_loan_type, current_scenario_stage_id, messages, collected_loan_info)를 저장
SESSION_STATES: Dict[str, AgentState] = {} # AgentState 타입으로 변경


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

@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect(websocket, session_id)

    stt_service: Optional[StreamSTTService] = None
    tts_service: Optional[StreamTTSService] = None

    if session_id not in SESSION_STATES:
        # 초기 AgentState 설정 (필수 필드 위주로)
        SESSION_STATES[session_id] = {
            "session_id": session_id,
            "user_input_text": None,
            "user_input_audio_b64": None,
            "stt_result": None,
            "current_loan_type": None, # 초기에는 대출 유형 미정
            "available_loan_types": ["didimdol", "jeonse"],
            "main_agent_routing_decision": None,
            "main_agent_direct_response": None,
            "scenario_agent_output": None,
            "messages": [], # 초기 메시지는 비우거나, run_agent_streaming에서 시스템 프롬프트 추가
            "current_scenario_stage_id": None, # 대출 유형 선택 후 설정됨
            "collected_loan_info": {},
            "active_scenario_data": None,
            "active_knowledge_base_content": None,
            "active_scenario_name": "미정",
            "final_response_text_for_tts": None,
            "error_message": None,
            "is_final_turn_response": False
        }
        print(f"New session initialized for {session_id}")
        # 초기 안내 메시지는 첫 번째 run_agent_streaming 호출 시 Main Agent가 생성하도록 유도
        # 또는 여기서 더 일반적인 메시지 전송
        initial_greeting_message = "안녕하세요! 신한은행 AI 금융 상담 서비스입니다. 어떤 도움이 필요하신가요? (예: 디딤돌 대출, 전세자금 대출 문의)"
        await manager.send_json_to_client(session_id, {
            "type": "session_initialized",
            "message": initial_greeting_message
            # "message": "안녕하세요! 신한은행 AI 금융 상담 서비스입니다. 어떤 대출 상품에 대해 알아보고 싶으신가요? (예: 디딤돌 대출, 전세자금 대출)"
        })
        # 첫 번째 사용자 입력 후 run_agent_streaming이 호출되면, current_loan_type이 없으므로
        # main_agent_router_node에서 initial_task_selection_prompt를 사용하여 대출 유형을 결정하게 됨.
    
    # STT/TTS 서비스 콜백 및 초기화 (기존과 유사)
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
            # STT 최종 결과를 받으면 LangGraph 에이전트 실행
            await process_input_through_agent(session_id, transcript, tts_service, input_mode="voice")

        async def _on_stt_error(error_msg: str):
            await manager.send_json_to_client(session_id, {"type": "error", "message": f"STT Error: {error_msg}"})
        async def _on_epd_detected():
            print(f"EPD detected by Google STT for session {session_id}")
            await manager.send_json_to_client(session_id, {"type": "epd_detected"})
        stt_service = StreamSTTService(session_id=session_id, on_interim_result=_on_stt_interim_result, on_final_result=handle_stt_final_result_with_tts_wrapper, on_error=_on_stt_error, on_epd_detected=_on_epd_detected)
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
                    # 텍스트 입력 시 input_mode="text"로 LangGraph 에이전트 실행
                    await process_input_through_agent(session_id, user_text, tts_service, input_mode="text")
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
                # else: await manager.send_json_to_client(session_id, {"type": "voice_deactivated", "message": "음성 인식이 이미 비활성화 상태일 수 있습니다."}) # 클라이언트 상태와 다를 수 있으므로 메시지 제거
            
            elif message_type == "stop_tts": 
                if tts_service and GOOGLE_SERVICES_AVAILABLE:
                    print(f"[{session_id}] Client requested server to stop TTS stream generation.")
                    await tts_service.stop_tts_stream() 
                else: print(f"[{session_id}] TTS stop_tts, TTS service N/A.")
            
    except WebSocketDisconnect: print(f"WebSocket disconnected by client: {session_id}")
    except Exception as e:
        print(f"WebSocket Error for session {session_id}: {e}")
        import traceback; traceback.print_exc()
        try: # 연결이 아직 유효하다면 클라이언트에게 에러 메시지 전송 시도
            await manager.send_json_to_client(session_id, {"type": "error", "message": f"Server error: {str(e)}"})
        except Exception: pass # 전송 실패 시 무시
    finally:
        if stt_service: await stt_service.stop_stream()
        if tts_service: await tts_service.stop_tts_stream() # TTS도 확실히 중지
        manager.disconnect(session_id)
        if session_id in SESSION_STATES: del SESSION_STATES[session_id]; print(f"Session state for {session_id} cleared.")


async def process_input_through_agent(session_id: str, user_text: str, tts_service: Optional[StreamTTSService], input_mode: str):
    """사용자 입력(텍스트 또는 STT 최종 결과)을 받아 LangGraph 에이전트를 실행하고 응답을 처리하는 함수"""
    print(f"process_input_through_agent called for session {session_id}, mode: {input_mode}, text: '{user_text[:30]}...'")
    
    current_session_state = SESSION_STATES.get(session_id)
    if not current_session_state:
        # 이 경우는 발생해서는 안되지만, 방어적으로 처리
        print(f"Error: Session state for {session_id} not found during agent processing.")
        await manager.send_json_to_client(session_id, {"type": "error", "message": "세션 정보를 찾을 수 없습니다. 다시 시도해주세요."})
        return

    full_ai_response_text = ""
    try:
        # run_agent_streaming 호출
        async for agent_output_chunk in run_agent_streaming(
            user_input_text=user_text, # 텍스트 입력 또는 STT 결과
            session_id=session_id,
            current_state_dict=current_session_state # 현재 세션 상태 전달
        ):
            if isinstance(agent_output_chunk, str):  # LLM 응답 스트리밍 청크
                await manager.send_json_to_client(session_id, {"type": "llm_response_chunk", "chunk": agent_output_chunk})
                full_ai_response_text += agent_output_chunk
            elif isinstance(agent_output_chunk, dict):
                if agent_output_chunk.get("type") == "stream_start":
                    await manager.send_json_to_client(session_id, agent_output_chunk)
                elif agent_output_chunk.get("type") == "stream_end":
                    await manager.send_json_to_client(session_id, {"type": "llm_response_end", "full_text": full_ai_response_text})
                    # TTS는 voice 모드에서만, 그리고 에러가 없을 때
                    if input_mode == "voice" and tts_service and GOOGLE_SERVICES_AVAILABLE and full_ai_response_text and not current_session_state.get("error_message"):
                        print(f"[{session_id}] Starting TTS for (mode: {input_mode}): {full_ai_response_text[:50]}...")
                        await tts_service.start_tts_stream(full_ai_response_text)
                    elif input_mode != "voice":
                         print(f"[{session_id}] Text input mode (mode: {input_mode}), TTS skipped.")
                    elif not full_ai_response_text:
                         print(f"[{session_id}] No text from LLM, TTS skipped.")


                elif agent_output_chunk.get("type") == "final_state":
                    final_agent_state_data = agent_output_chunk.get("data")
                    if final_agent_state_data:
                        # AgentState 전체를 업데이트
                        SESSION_STATES[session_id] = cast(AgentState, final_agent_state_data)
                        # final_response_text_for_tts는 AgentState 내부에 이미 설정되어 있을 것
                        tts_candidate_text = final_agent_state_data.get("final_response_text_for_tts", full_ai_response_text)
                        if not full_ai_response_text and tts_candidate_text : # 스트리밍 없이 바로 final_state로 온 경우
                            full_ai_response_text = tts_candidate_text
                            # 이 경우 LLM 응답을 클라이언트에 한 번에 보내줘야 함
                            await manager.send_json_to_client(session_id, {"type": "llm_response_chunk", "chunk": full_ai_response_text}) # stream_start 없이 바로 chunk
                            await manager.send_json_to_client(session_id, {"type": "llm_response_end", "full_text": full_ai_response_text})

                            if input_mode == "voice" and tts_service and GOOGLE_SERVICES_AVAILABLE and full_ai_response_text and not final_agent_state_data.get("error_message"):
                                print(f"[{session_id}] Starting TTS for final_state (mode: {input_mode}): {full_ai_response_text[:50]}...")
                                await tts_service.start_tts_stream(full_ai_response_text)


                        print(f"Session state for {session_id} updated via final_state.")
                elif agent_output_chunk.get("type") == "error": # run_agent_streaming 내부에서 발생한 에러
                    await manager.send_json_to_client(session_id, agent_output_chunk)
                    await manager.send_json_to_client(session_id, {"type": "llm_response_end", "full_text": ""}) # 에러 시 빈 텍스트로 종료
                    # SESSION_STATES의 error_message도 업데이트 필요 (final_state에서 처리됨)

    except Exception as e:
        error_msg = f"Agent 처리 중 예외 발생: {e}"
        print(f"[{session_id}] {error_msg}")
        import traceback; traceback.print_exc()
        await manager.send_json_to_client(session_id, {"type": "error", "message": error_msg})
        await manager.send_json_to_client(session_id, {"type": "llm_response_end", "full_text": ""}) # 에러 시 빈 텍스트로 종료
        # 세션 상태 업데이트
        if session_id in SESSION_STATES:
            SESSION_STATES[session_id]["error_message"] = error_msg
            SESSION_STATES[session_id]["is_final_turn_response"] = True