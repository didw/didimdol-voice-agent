"""
WebSocket 채팅 핸들러 - 에이전트 처리 로직
"""

import json
from typing import Optional, Dict, Any, AsyncGenerator
from langchain_core.messages import HumanMessage, AIMessage
# from ...graph.unified_agent_integration import process_with_unified_agent
from ...graph.agent import run_agent_streaming
from ...services.google_services import StreamTTSService
from ...utils import split_into_sentences
from ...services.google_services import GOOGLE_SERVICES_AVAILABLE
from .websocket_manager import manager


async def handle_agent_output_chunk(
    agent_output_chunk: Any,
    session_id: str,
    websocket: Any,
    session_states: Dict[str, Dict],
    full_ai_response_text: str
) -> tuple[str, bool, Dict[str, Any]]:
    """
    에이전트 출력 청크 처리
    Returns: (updated_full_text, stream_ended, final_state_data)
    """
    if isinstance(agent_output_chunk, str):
        await manager.send_json_to_client(session_id, {
            "type": "llm_response_chunk", 
            "chunk": agent_output_chunk
        })
        return full_ai_response_text + agent_output_chunk, False, None
    
    elif isinstance(agent_output_chunk, dict):
        chunk_type = agent_output_chunk.get("type")
        
        if chunk_type == "stream_start":
            await manager.send_json_to_client(session_id, agent_output_chunk)
            return full_ai_response_text, False, None
            
        elif chunk_type == "stage_response":
            # Send stage response data to client
            stage_data = agent_output_chunk.get("data")
            if stage_data:
                websocket_data = {
                    "type": "stage_response",
                    "stageId": stage_data.get("stage_id"),
                    "responseType": stage_data.get("response_type"),
                    "prompt": stage_data.get("prompt"),
                    "choices": stage_data.get("choices"),
                    "skippable": stage_data.get("skippable", False),
                    "modifiableFields": stage_data.get("modifiable_fields")
                }
                # choice_groups가 있는 경우 추가
                if stage_data.get("choice_groups"):
                    websocket_data["choiceGroups"] = stage_data.get("choice_groups")
                # default_choice가 있는 경우 추가
                if stage_data.get("default_choice"):
                    websocket_data["defaultChoice"] = stage_data.get("default_choice")
                    
                await manager.send_json_to_client(session_id, websocket_data)
            return full_ai_response_text, False, None
            
        elif chunk_type == "stream_end":
            await manager.send_json_to_client(session_id, {
                "type": "llm_response_end", 
                "full_text": full_ai_response_text
            })
            return full_ai_response_text, True, None
            
        elif chunk_type == "final_state":
            final_data = agent_output_chunk.get("data")
            if final_data:
                # stage_response_data가 있으면 일반 텍스트 응답은 보내지 않음
                if final_data.get("stage_response_data"):
                    return full_ai_response_text, True, final_data
                
                # 텍스트가 없으면 final_state에서 가져오기
                if not full_ai_response_text and final_data.get("final_response_text_for_tts"):
                    text = final_data["final_response_text_for_tts"]
                    await manager.send_json_to_client(session_id, {
                        "type": "llm_response_chunk", 
                        "chunk": text
                    })
                    await manager.send_json_to_client(session_id, {
                        "type": "llm_response_end", 
                        "full_text": text
                    })
                    return text, True, final_data
            return full_ai_response_text, True, final_data
            
        elif chunk_type == "error":
            await manager.send_json_to_client(session_id, agent_output_chunk)
            await manager.send_json_to_client(session_id, {
                "type": "llm_response_end", 
                "full_text": ""
            })
            if session_id in session_states:
                session_states[session_id]["error_message"] = agent_output_chunk.get("message")
            return "", True, None
    
    return full_ai_response_text, False, None


async def handle_slot_filling_update(
    session_id: str,
    websocket: Any,
    current_state: Dict[str, Any],
    previous_state: Dict[str, Any],
    info_collection_stages: list
) -> None:
    """슬롯 필링 업데이트 처리"""
    from .chat_utils import should_send_slot_filling_update, send_slot_filling_update
    
    current_collected_info = current_state.get("collected_product_info", {})
    current_scenario_stage = current_state.get("current_scenario_stage_id", "")
    
    # 업데이트 필요 조건 확인
    info_changed = previous_state.get("collected_product_info", {}) != current_collected_info
    scenario_changed = previous_state.get("scenario_data") != current_state.get("active_scenario_data")
    product_type_changed = previous_state.get("product_type") != current_state.get("current_product_type")
    stage_changed = previous_state.get("current_scenario_stage_id") != current_scenario_stage
    scenario_active = current_state.get("active_scenario_data") is not None
    is_info_collection_stage = (current_scenario_stage in info_collection_stages or 
                               current_state.get("current_product_type") == "deposit_account")
    
    
    should_send = should_send_slot_filling_update(
        info_changed, scenario_changed, product_type_changed, stage_changed,
        scenario_active, is_info_collection_stage
    )
    
    if should_send:
        await send_slot_filling_update(websocket, current_state, session_id)
    else:
        pass


async def process_tts_for_response(
    session_id: str,
    full_text: str,
    tts_service: Optional[StreamTTSService],
    input_mode: str,
    current_session_state: Dict[str, Any]
) -> None:
    """TTS 처리"""
    if (input_mode == "voice" and 
        tts_service and 
        GOOGLE_SERVICES_AVAILABLE and 
        full_text and 
        not current_session_state.get("error_message")):
        
        print(f"[{session_id}] Processing TTS for: '{full_text[:70]}...'")
        sentences = split_into_sentences(full_text)
        
        for i, sentence in enumerate(sentences):
            if current_session_state.get('tts_cancelled'):
                print(f"[{session_id}] TTS cancelled by client")
                break
                
            sentence_strip = sentence.strip()
            if sentence_strip:
                print(f"[{session_id}] TTS sentence {i+1}/{len(sentences)}")
                await tts_service.start_tts_stream(sentence_strip)


async def get_agent_generator(
    user_text: str,
    session_id: str,
    current_session_state: Dict[str, Any],
    websocket: Any,
    input_mode: str = "text"
) -> AsyncGenerator:
    """새로운 LLM 기반 에이전트 사용"""
    # choice_exact 모드일 때는 간단한 처리만 수행
    if input_mode == "choice_exact":
        # 현재 스테이지 정보에 따라 다음 스테이지로 이동하는 로직만 실행
        # 실제 값은 이미 process_input_through_agent에서 저장됨
        pass
    
    # 새로운 LLM 기반 에이전트 사용
    async for chunk in run_agent_streaming(
        user_input_text=user_text,
        session_id=session_id,
        current_state_dict=current_session_state,
        input_mode=input_mode
    ):
        yield chunk