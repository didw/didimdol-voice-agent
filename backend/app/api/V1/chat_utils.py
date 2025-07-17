"""
채팅 관련 유틸리티 함수들
"""

import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from ...graph.state import AgentState


def should_send_slot_filling_update(
    info_changed: bool,
    scenario_changed: bool,
    product_type_changed: bool,
    scenario_active: bool,
    is_info_collection_stage: bool
) -> bool:
    """슬롯 필링 업데이트를 전송해야 하는지 확인"""
    return (
        info_changed or 
        scenario_changed or 
        product_type_changed or
        (scenario_active and is_info_collection_stage)
    )


async def send_slot_filling_update(
    websocket: Any,
    state: AgentState,
    session_id: str
) -> None:
    """슬롯 필링 상태 업데이트를 WebSocket으로 전송"""
    
    # 시나리오 데이터 확인
    scenario_data = state.get("active_scenario_data")
    if not scenario_data:
        print(f"[{session_id}] No active scenario data for slot filling update")
        
        # deposit_account의 경우 기본 시나리오 데이터 생성
        if state.get("current_product_type") == "deposit_account":
            await _send_deposit_account_update(websocket, state, session_id)
        return
    
    try:
        # 필요한 정보 필드들 (시나리오 데이터 구조에 맞춤)
        required_fields = scenario_data.get("required_info_fields", [])
        if not required_fields:
            required_fields = scenario_data.get("slot_fields", [])
        field_groups = scenario_data.get("field_groups", [])
        collected_info = state.get("collected_product_info", {})
        current_stage = state.get("current_scenario_stage_id", "")
        
        # 각 필드의 수집 상태 확인
        fields_status = []
        for field in required_fields:
            field_key = field.get("key", "")
            field_status = {
                "key": field_key,
                "display_name": field.get("display_name", field_key),
                "value": collected_info.get(field_key, ""),
                "is_collected": field_key in collected_info,
                "is_required": field.get("required", True)
            }
            fields_status.append(field_status)
        
        # 그룹별 진행률 계산
        groups_status = []
        for group in field_groups:
            group_fields = group.get("fields", [])
            collected_count = sum(1 for field in group_fields if field in collected_info)
            total_count = len(group_fields)
            
            groups_status.append({
                "id": group.get("id", ""),
                "name": group.get("name", ""),
                "progress": (collected_count / total_count * 100) if total_count > 0 else 0,
                "collected": collected_count,
                "total": total_count
            })
        
        # 전체 진행률
        total_required = len([f for f in required_fields if f.get("required", True)])
        total_collected = sum(1 for f in required_fields if f.get("key") in collected_info and f.get("required", True))
        overall_progress = (total_collected / total_required * 100) if total_required > 0 else 0
        
        # 현재 stage에서 표시할 그룹 정보 가져오기
        visible_groups = get_stage_visible_groups(scenario_data, current_stage)
        
        # WebSocket 메시지 구성 (프론트엔드 인터페이스에 맞게)
        slot_filling_data = {
            "type": "slot_filling_update",
            "productType": state.get("current_product_type", ""),
            "requiredFields": [{
                "key": f["key"],
                "displayName": f["display_name"],
                "type": f.get("type", "text"),
                "required": f.get("required", True),
                "choices": f.get("choices", []) if f.get("type") == "choice" else None,
                "unit": f.get("unit") if f.get("type") == "number" else None,
                "description": f.get("description", ""),
                "dependsOn": f.get("depends_on") if "depends_on" in f else None
            } for f in required_fields],
            "collectedInfo": collected_info,
            "completionStatus": {f["key"]: f["key"] in collected_info for f in required_fields},
            "completionRate": overall_progress,
            "fieldGroups": [{
                "id": group["id"],
                "name": group["name"],
                "fields": group["fields"]
            } for group in field_groups] if field_groups else [],
            "currentStage": {
                "stageId": current_stage,
                "visibleGroups": visible_groups
            }
        }
        
        await websocket.send_json(slot_filling_data)
        print(f"[{session_id}] Slot filling update sent: {overall_progress:.1f}% complete")
        print(f"[{session_id}] Collected info in update: {collected_info}")
        print(f"[{session_id}] Required fields in update: {[f['key'] for f in required_fields]}")
        
        # DEBUG: 디버깅용 상세 로그
        print(f"[{session_id}] ===== SLOT FILLING DEBUG =====")
        print(f"[{session_id}] Product Type: {slot_filling_data['productType']}")
        print(f"[{session_id}] Current Stage: {slot_filling_data['currentStage']['stageId']}")
        print(f"[{session_id}] Visible Groups: {slot_filling_data['currentStage']['visibleGroups']}")
        print(f"[{session_id}] Required Fields Count: {len(slot_filling_data['requiredFields'])}")
        print(f"[{session_id}] Collected Info Count: {len(slot_filling_data['collectedInfo'])}")
        print(f"[{session_id}] Completion Rate: {slot_filling_data['completionRate']}")
        print(f"[{session_id}] Field Groups Count: {len(slot_filling_data.get('fieldGroups', []))}")
        
        # 필드별 상세 정보
        for field in slot_filling_data['requiredFields']:
            key = field['key']
            value = slot_filling_data['collectedInfo'].get(key, 'NOT_SET')
            completed = slot_filling_data['completionStatus'].get(key, False)
            print(f"[{session_id}] Field '{key}': {value} (completed: {completed})")
        
        # 전송할 JSON 데이터 전체 출력
        print(f"[{session_id}] Full JSON Data: {json.dumps(slot_filling_data, ensure_ascii=False, indent=2)}")
        print(f"[{session_id}] ===== END DEBUG =====")
        
        # 프론트엔드에서 수신 확인을 위한 디버그 메시지도 함께 전송
        debug_message = {
            "type": "debug_slot_filling",
            "timestamp": json.dumps({"timestamp": str(datetime.now())}),
            "data_hash": hash(json.dumps(slot_filling_data, sort_keys=True)),
            "summary": {
                "productType": slot_filling_data['productType'],
                "fieldsCount": len(slot_filling_data['requiredFields']),
                "collectedCount": len(slot_filling_data['collectedInfo']),
                "completionRate": slot_filling_data['completionRate']
            }
        }
        await websocket.send_json(debug_message)
        
    except Exception as e:
        print(f"[{session_id}] Error sending slot filling update: {e}")


def format_messages_for_display(messages: List[BaseMessage]) -> List[Dict[str, str]]:
    """메시지 리스트를 표시용 포맷으로 변환"""
    formatted = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            formatted.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            formatted.append({"role": "assistant", "content": msg.content})
        elif isinstance(msg, SystemMessage):
            formatted.append({"role": "system", "content": msg.content})
    return formatted


async def _send_deposit_account_update(
    websocket: Any,
    state: AgentState,
    session_id: str
) -> None:
    """입출금통장용 기본 슬롯 필링 업데이트"""
    try:
        collected_info = state.get("collected_product_info", {})
        current_stage = state.get("current_scenario_stage_id", "collect_basic")
        
        # 실제 시나리오 데이터에서 필드 가져오기
        scenario_data = state.get("active_scenario_data")
        print(f"[{session_id}] DEBUG: scenario_data keys: {list(scenario_data.keys()) if scenario_data else 'None'}")
        
        if scenario_data and "required_info_fields" in scenario_data:
            default_fields = scenario_data["required_info_fields"]
            print(f"[{session_id}] DEBUG: Using required_info_fields, count: {len(default_fields)}")
        elif scenario_data and "slot_fields" in scenario_data:
            default_fields = scenario_data["slot_fields"]
            print(f"[{session_id}] DEBUG: Using slot_fields, count: {len(default_fields)}")
        else:
            print(f"[{session_id}] DEBUG: Using fallback fields")
            # 폴백 필드 정의
            default_fields = [
                {"key": "customer_name", "display_name": "성함", "required": True},
                {"key": "phone_number", "display_name": "연락처", "required": True},
                {"key": "use_lifelong_account", "display_name": "평생계좌 사용", "required": True},
                {"key": "ib_service_type", "display_name": "인터넷뱅킹 서비스", "required": False},
                {"key": "cc_type", "display_name": "체크카드 종류", "required": False}
            ]
        
        # 그룹 정의 (시나리오 데이터에서 가져오기)
        field_groups = scenario_data.get("field_groups", []) if scenario_data else []
        if not field_groups:
            # 폴백 그룹 정의
            field_groups = [
                {
                    "id": "basic_info",
                    "name": "기본 정보",
                    "fields": ["customer_name", "phone_number", "birth_date", "address"]
                },
                {
                    "id": "service_options", 
                    "name": "부가 서비스",
                    "fields": ["lifelong_account", "internet_banking", "check_card"]
                }
            ]
        
        # 그룹별 진행률 계산
        groups_status = []
        for group in field_groups:
            group_fields = group["fields"]
            collected_count = sum(1 for field in group_fields if field in collected_info)
            total_count = len(group_fields)
            
            groups_status.append({
                "id": group["id"],
                "name": group["name"],
                "progress": (collected_count / total_count * 100) if total_count > 0 else 0,
                "collected": collected_count,
                "total": total_count
            })
        
        # 전체 진행률 (필수 필드만)
        required_fields = [f for f in default_fields if f["required"]]
        total_required = len(required_fields)
        total_collected = sum(1 for f in required_fields if f["key"] in collected_info)
        overall_progress = (total_collected / total_required * 100) if total_required > 0 else 0
        
        # 필드 상태
        fields_status = []
        for field in default_fields:
            field_key = field["key"]
            fields_status.append({
                "key": field_key,
                "display_name": field["display_name"],
                "value": collected_info.get(field_key, ""),
                "is_collected": field_key in collected_info,
                "is_required": field["required"]
            })
        
        # WebSocket 메시지 전송 (프론트엔드 인터페이스에 맞게)
        slot_filling_data = {
            "type": "slot_filling_update",
            "productType": "deposit_account",
            "requiredFields": [{
                "key": f["key"],
                "displayName": f["display_name"],
                "type": f.get("type", "text"),
                "required": f["required"],
                "choices": f.get("choices", []) if f.get("type") == "choice" else None,
                "unit": f.get("unit") if f.get("type") == "number" else None,
                "description": f.get("description", ""),
                "dependsOn": f.get("depends_on") if "depends_on" in f else None
            } for f in default_fields],
            "collectedInfo": collected_info,
            "completionStatus": {f["key"]: f["key"] in collected_info for f in default_fields},
            "completionRate": overall_progress,
            "fieldGroups": [{
                "id": group["id"],
                "name": group["name"],
                "fields": group["fields"]
            } for group in field_groups] if field_groups else []
        }
        
        await websocket.send_json(slot_filling_data)
        print(f"[{session_id}] Deposit account slot filling update sent: {overall_progress:.1f}% complete")
        
    except Exception as e:
        print(f"[{session_id}] Error sending deposit account slot filling update: {e}")


def get_info_collection_stages() -> List[str]:
    """정보 수집 단계 목록 반환"""
    return [
        # 디딤돌 대출
        "ask_address_status", "ask_residence_type", "ask_acquisition_details",
        "ask_loan_details", "ask_marital_houseowner_status", 
        "ask_missing_info_group_personal", "ask_missing_info_group_property",
        "ask_missing_info_group_financial", "process_collected_info",
        
        # 전세자금 대출
        "ask_property_info", "ask_contract_info", "ask_tenant_info",
        "ask_existing_loans",
        
        # 입출금통장
        "greeting_deposit", "collect_customer_info",
        "clarify_services", "process_service_choices", 
        "collect_basic", "ask_internet_banking", "collect_ib_info",
        "ask_check_card", "collect_cc_info", "confirm_all"
    ]


def get_stage_visible_groups(scenario_data: Dict, stage_id: str) -> List[str]:
    """현재 stage에서 표시할 field_groups 반환 (시나리오 데이터 기반)"""
    
    if not scenario_data or not stage_id:
        return []
    
    # 시나리오 데이터에서 stage 정보 가져오기
    stages = scenario_data.get("stages", {})
    current_stage = stages.get(stage_id, {})
    
    # stage에 visible_groups가 정의되어 있으면 사용
    visible_groups = current_stage.get("visible_groups", [])
    
    if visible_groups:
        return visible_groups
    
    # fallback: 모든 그룹 표시
    field_groups = scenario_data.get("field_groups", [])
    return [group["id"] for group in field_groups]


def initialize_default_values(state: Dict[str, Any]) -> Dict[str, Any]:
    """시나리오 시작 시 default 값들을 collected_info에 설정"""
    from ...graph.utils import get_active_scenario_data
    
    scenario_data = get_active_scenario_data(state)
    collected_info = state.get("collected_product_info", {}).copy()
    
    if not scenario_data:
        return collected_info
    
    for field in scenario_data.get("required_info_fields", []):
        field_key = field["key"]
        
        # 이미 값이 있으면 skip
        if field_key in collected_info:
            continue
            
        # default 값이 있으면 설정
        if "default" in field:
            collected_info[field_key] = field["default"]
            print(f"Initialized default value: {field_key} = {field['default']}")
    
    return collected_info