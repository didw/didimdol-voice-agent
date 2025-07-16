"""
UnifiedMainAgent를 기존 LangGraph 에이전트와 통합하는 모듈
"""

import json
from typing import Dict, Any, Optional, AsyncGenerator
from langchain_core.messages import HumanMessage, AIMessage
from ..agents.unified_main_agent import unified_main_agent
from .state import AgentState


async def process_with_unified_agent(
    state: AgentState,
    user_input: str,
    websocket: Any
) -> AsyncGenerator[Any, None]:
    """
    UnifiedMainAgent를 사용하여 사용자 입력 처리
    """
    
    # 현재 상태 정보 추출
    current_stage = state.get("current_scenario_stage_id", "greeting")
    collected_info = state.get("collected_product_info", {})
    messages = state.get("messages", [])
    
    # 마지막 시스템 메시지 찾기
    last_system_message = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            last_system_message = msg.content
            break
    
    # 진행 상황 스트리밍
    yield {"type": "stream_start", "message": "처리 중..."}
    
    # UnifiedMainAgent 호출
    try:
        result = await unified_main_agent.process_user_input(
            user_input=user_input,
            current_stage=current_stage,
            collected_info=collected_info,
            last_system_message=last_system_message
        )
        
        # 응답 스트리밍
        response_message = result.get("message", "")
        for i in range(0, len(response_message), 10):
            chunk = response_message[i:i+10]
            yield chunk
        
        yield {"type": "stream_end"}
        
        # 수집된 정보 업데이트
        new_collected_info = result.get("collected_info", {})
        if new_collected_info:
            collected_info.update(new_collected_info)
            
            # WebSocket으로 slot filling 업데이트 전송
            if websocket:
                await send_slot_filling_update_unified(
                    websocket,
                    state,
                    collected_info,
                    current_stage
                )
        
        # 다음 단계 처리
        next_action = result.get("next_action")
        if next_action == "next_stage":
            current_stage = result.get("next_stage", current_stage)
        
        # 최종 상태 업데이트
        updated_state = {
            **state,
            "current_scenario_stage_id": current_stage,
            "collected_product_info": collected_info,
            "final_response_text_for_tts": response_message,
            "is_final_turn_response": True,
            "messages": messages + [
                HumanMessage(content=user_input),
                AIMessage(content=response_message)
            ]
        }
        
        yield {"type": "final_state", "data": updated_state}
        
    except Exception as e:
        print(f"UnifiedMainAgent error: {e}")
        error_message = "죄송합니다. 처리 중 오류가 발생했습니다."
        yield error_message
        yield {"type": "stream_end"}
        yield {
            "type": "final_state",
            "data": {
                **state,
                "final_response_text_for_tts": error_message,
                "error_message": str(e)
            }
        }


async def send_slot_filling_update_unified(
    websocket: Any,
    state: AgentState,
    collected_info: Dict[str, Any],
    current_stage: str
) -> None:
    """
    UnifiedMainAgent용 slot filling 업데이트 전송
    """
    
    # 시나리오 데이터 가져오기
    from ..graph.simple_scenario_engine import simple_scenario_engine
    
    # 전체 필드 정보
    all_fields = simple_scenario_engine.get_all_collected_fields()
    
    # 필드 그룹 정보
    field_groups = simple_scenario_engine.scenario_data.get("field_groups", [])
    
    # 현재 단계의 필드들
    current_fields = simple_scenario_engine.get_required_fields_for_stage(current_stage)
    current_field_keys = [f["key"] for f in current_fields]
    
    # 그룹별 진행 상황 계산
    groups_status = []
    for group in field_groups:
        group_fields = group.get("fields", [])
        collected_count = sum(1 for field in group_fields if field in collected_info)
        total_count = len(group_fields)
        
        # 현재 활성 그룹인지 확인
        is_active = any(field in current_field_keys for field in group_fields)
        
        groups_status.append({
            "id": group["id"],
            "name": group["name"],
            "progress": (collected_count / total_count * 100) if total_count > 0 else 0,
            "collected": collected_count,
            "total": total_count,
            "is_active": is_active
        })
    
    # 개별 필드 상태
    fields_status = []
    for field in all_fields:
        field_key = field["key"]
        is_collected = field_key in collected_info
        is_current = field_key in current_field_keys
        
        fields_status.append({
            "key": field_key,
            "display_name": field["display_name"],
            "value": collected_info.get(field_key, ""),
            "is_collected": is_collected,
            "is_current": is_current,
            "stage": field.get("stage", "")
        })
    
    # 전체 진행률
    total_collected = len(collected_info)
    total_required = len([f for f in all_fields if f.get("required", False)])
    overall_progress = (total_collected / total_required * 100) if total_required > 0 else 0
    
    # WebSocket 메시지 전송
    slot_filling_data = {
        "type": "slot_filling_update",
        "data": {
            "product_type": "deposit_account",
            "current_stage": current_stage,
            "overall_progress": overall_progress,
            "groups": groups_status,
            "fields": fields_status,
            "collected_info": collected_info
        }
    }
    
    try:
        await websocket.send_json(slot_filling_data)
        print(f"[UnifiedAgent] Slot filling update sent: {overall_progress:.1f}% complete")
    except Exception as e:
        print(f"[UnifiedAgent] Failed to send slot filling update: {e}")