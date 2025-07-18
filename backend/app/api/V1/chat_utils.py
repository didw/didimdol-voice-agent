"""
채팅 관련 유틸리티 함수들
"""

import json
import re
from typing import Dict, Any, List, Optional
from datetime import datetime
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from ...graph.state import AgentState


# ===== 새로운 조건 평가 엔진 (심플 구조) =====

def evaluate_show_when(show_when: str, collected_info: Dict[str, Any]) -> bool:
    """간단한 표현식으로 조건 평가
    
    지원하는 표현식:
    - field == value
    - field != null  
    - condition1 && condition2
    - condition1 || condition2
    """
    if not show_when or not show_when.strip():
        return True
    
    try:
        expression = show_when.strip()
        
        # && 및 || 연산자로 분리
        if '&&' in expression:
            conditions = [cond.strip() for cond in expression.split('&&')]
            return all(evaluate_single_condition(cond, collected_info) for cond in conditions)
        elif '||' in expression:
            conditions = [cond.strip() for cond in expression.split('||')]
            return any(evaluate_single_condition(cond, collected_info) for cond in conditions)
        else:
            return evaluate_single_condition(expression, collected_info)
    
    except Exception as e:
        print(f"Error evaluating show_when expression '{show_when}': {e}")
        return True  # 에러 시 기본적으로 표시


def evaluate_single_condition(condition: str, collected_info: Dict[str, Any]) -> bool:
    """단일 조건 평가"""
    condition = condition.strip()
    
    # field != null 패턴
    if ' != null' in condition:
        field_name = condition.replace(' != null', '').strip()
        value = collected_info.get(field_name)
        return value is not None and value != '' and value != False
    
    # field == null 패턴  
    if ' == null' in condition:
        field_name = condition.replace(' == null', '').strip()
        value = collected_info.get(field_name)
        return value is None or value == '' or value == False
    
    # field == value 패턴
    if ' == ' in condition:
        parts = condition.split(' == ', 1)
        if len(parts) == 2:
            field_name = parts[0].strip()
            expected_value = parts[1].strip().strip("'\"")
            current_value = collected_info.get(field_name)
            
            # boolean 값 처리
            if expected_value.lower() == 'true':
                return current_value is True
            elif expected_value.lower() == 'false':
                return current_value is False
            
            return str(current_value) == expected_value
    
    # field != value 패턴
    if ' != ' in condition:
        parts = condition.split(' != ', 1)
        if len(parts) == 2:
            field_name = parts[0].strip()
            expected_value = parts[1].strip().strip("'\"")
            current_value = collected_info.get(field_name)
            
            # boolean 값 처리
            if expected_value.lower() == 'true':
                return current_value is not True
            elif expected_value.lower() == 'false':
                return current_value is not False
            
            return str(current_value) != expected_value
    
    return True


def get_visible_fields_with_hierarchy(scenario_data: Dict, collected_info: Dict) -> List[Dict]:
    """계층적 구조로 표시 가능한 필드 반환"""
    if not scenario_data:
        return []
    
    required_fields = scenario_data.get("required_info_fields", [])
    visible_fields = []
    
    for field in required_fields:
        # show_when 조건 확인
        show_when = field.get("show_when")
        if show_when and not evaluate_show_when(show_when, collected_info):
            continue
        
        # 계층 정보 추가
        field_with_hierarchy = field.copy()
        field_with_hierarchy["depth"] = calculate_field_depth(field, required_fields)
        field_with_hierarchy["is_visible"] = True
        
        visible_fields.append(field_with_hierarchy)
    
    return visible_fields


def calculate_field_depth(field: Dict, all_fields: List[Dict]) -> int:
    """필드의 계층 깊이 계산"""
    parent_field = field.get("parent_field")
    if not parent_field:
        return 0
    
    # 부모 필드 찾기
    for parent in all_fields:
        if parent.get("key") == parent_field:
            return calculate_field_depth(parent, all_fields) + 1
    
    return 0


def apply_conditional_defaults(scenario_data: Dict, collected_info: Dict) -> Dict:
    """조건부 필드의 default 값을 동적으로 적용"""
    enhanced_info = collected_info.copy()
    
    if not scenario_data:
        return enhanced_info
    
    for field in scenario_data.get("required_info_fields", []):
        field_key = field["key"]
        
        # 이미 값이 있으면 skip
        if field_key in enhanced_info:
            continue
        
        # show_when 조건 확인
        show_when = field.get("show_when")
        if show_when:
            # 조건이 만족되어도 default 값 자동 설정 비활성화
            if evaluate_show_when(show_when, enhanced_info) and "default" in field:
                # enhanced_info[field_key] = field["default"]
                # print(f"Applied conditional default: {field_key} = {field['default']}")
                pass
        elif "default" in field:
            # 조건이 없는 필드의 default 값도 비활성화
            # enhanced_info[field_key] = field["default"]
            # print(f"Applied default: {field_key} = {field['default']}")
            pass
    
    return enhanced_info


def update_slot_filling_with_hierarchy(scenario_data: Dict, collected_info: Dict, current_stage: str) -> Dict:
    """실시간으로 계층적 슬롯 필링 상태 계산"""
    if not scenario_data:
        return {}
    
    # 표시 가능한 필드들 가져오기
    visible_fields = get_visible_fields_with_hierarchy(scenario_data, collected_info)
    
    # Default 값 자동 추가 비활성화 - 고객 응답을 기다림
    enhanced_collected_info = collected_info.copy()
    # for field in visible_fields:
    #     field_key = field["key"]
    #     if field_key not in enhanced_collected_info and "default" in field and field["default"] is not None:
    #         enhanced_collected_info[field_key] = field["default"]
    #         print(f"Auto-collected default value: {field_key} = {field['default']}")
    
    # 필드 그룹 정보
    field_groups = scenario_data.get("field_groups", [])
    
    # 완료 상태 계산 (모든 필드, 표시되지 않는 필드도 포함)
    all_fields = scenario_data.get("required_info_fields", [])
    completion_status = {}
    
    for field in all_fields:
        field_key = field["key"]
        # enhanced_collected_info를 사용하여 default 값도 완료로 간주
        value = enhanced_collected_info.get(field_key)
        # boolean 필드의 경우 명시적으로 설정된 값만 완료로 간주
        if field.get("type") == "boolean":
            completion_status[field_key] = field_key in enhanced_collected_info and value is not None
        else:
            completion_status[field_key] = value is not None and value != '' and value != False
    
    # 완료율 계산 (표시되는 필수 필드 기준)
    required_visible_fields = [f for f in visible_fields if f.get("required", True)]
    total_required = len(required_visible_fields)
    completed_required = sum(1 for f in required_visible_fields if completion_status.get(f["key"], False))
    completion_rate = (completed_required / total_required * 100) if total_required > 0 else 0
    
    # 디버그 로그
    print(f"DEBUG: Total visible fields: {len(visible_fields)}")
    print(f"DEBUG: Required visible fields: {total_required}")
    print(f"DEBUG: Completed required fields: {completed_required}")
    print(f"DEBUG: Completion rate: {completion_rate}")
    
    return {
        "visible_fields": visible_fields,
        "completion_status": completion_status,
        "completion_rate": completion_rate,
        "field_groups": field_groups,
        "current_stage": current_stage,
        "enhanced_collected_info": enhanced_collected_info  # 반환에 추가
    }


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
        
        # 새로운 계층적 슬롯 필링 계산
        try:
            hierarchy_data = update_slot_filling_with_hierarchy(scenario_data, collected_info, current_stage)
            print(f"[{session_id}] Hierarchy calculation successful: {len(hierarchy_data.get('visible_fields', []))} visible fields")
            # enhanced_collected_info 사용
            if "enhanced_collected_info" in hierarchy_data:
                collected_info = hierarchy_data["enhanced_collected_info"]
                print(f"[{session_id}] Using enhanced collected info with defaults")
        except Exception as e:
            print(f"[{session_id}] Error in hierarchy calculation: {e}")
            hierarchy_data = {}
        
        # 계층 정보가 있는 필드들 준비
        enhanced_fields = []
        visible_fields = hierarchy_data.get("visible_fields", [])
        
        if visible_fields:
            # 계층 정보가 있는 경우 사용
            enhanced_fields = [{
                "key": f["key"],
                "displayName": f["display_name"],
                "type": f.get("type", "text"),
                "required": f.get("required", True),
                "choices": f.get("choices", []) if f.get("type") == "choice" else None,
                "unit": f.get("unit") if f.get("type") == "number" else None,
                "description": f.get("description", ""),
                "showWhen": f.get("show_when"),
                "parentField": f.get("parent_field"),
                "depth": f.get("depth", 0),
                "default": f.get("default")  # default 값 추가
            } for f in visible_fields]
        else:
            # fallback: 기존 방식
            enhanced_fields = [{
                "key": f["key"],
                "displayName": f["display_name"],
                "type": f.get("type", "text"),
                "required": f.get("required", True),
                "choices": f.get("choices", []) if f.get("type") == "choice" else None,
                "unit": f.get("unit") if f.get("type") == "number" else None,
                "description": f.get("description", ""),
                "showWhen": f.get("show_when"),
                "parentField": f.get("parent_field"),
                "depth": 0,  # 기본 depth
                "default": f.get("default")  # default 값 추가
            } for f in required_fields]
        
        # WebSocket 메시지 구성 (새로운 구조)
        slot_filling_data = {
            "type": "slot_filling_update",
            "productType": state.get("current_product_type", ""),
            "requiredFields": enhanced_fields,
            "collectedInfo": collected_info,
            "completionStatus": hierarchy_data.get("completion_status", {f["key"]: f["key"] in collected_info for f in required_fields}),
            "completionRate": hierarchy_data.get("completion_rate", overall_progress),
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
        
        # 디버그 로그 추가
        print(f"[{session_id}] Enhanced fields count: {len(enhanced_fields)}")
        print(f"[{session_id}] Visible fields from hierarchy: {len(visible_fields)}")
        print(f"[{session_id}] Current collected_info keys: {list(collected_info.keys())}")
        print(f"[{session_id}] Boolean fields in collected_info:")
        print(f"[{session_id}]   use_internet_banking: {collected_info.get('use_internet_banking')}")
        print(f"[{session_id}]   use_check_card: {collected_info.get('use_check_card')}")
        print(f"[{session_id}]   confirm_personal_info: {collected_info.get('confirm_personal_info')}")
        print(f"[{session_id}]   use_lifelong_account: {collected_info.get('use_lifelong_account')}")
        
        for field in enhanced_fields[:5]:  # 첫 5개만 로그
            print(f"[{session_id}] Field: {field['key']} (depth: {field.get('depth', 0)}, showWhen: {field.get('showWhen')})")
        
        await websocket.send_json(slot_filling_data)
        print(f"[{session_id}] Slot filling update sent: {slot_filling_data['completionRate']:.1f}% complete")
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
        
        # 새로운 계층적 슬롯 필링 계산
        if scenario_data:
            hierarchy_data = update_slot_filling_with_hierarchy(scenario_data, collected_info, current_stage)
            # enhanced_collected_info 사용
            if "enhanced_collected_info" in hierarchy_data:
                collected_info = hierarchy_data["enhanced_collected_info"]
                print(f"[{session_id}] Using enhanced collected info with defaults in deposit account")
        else:
            hierarchy_data = {}
        
        # WebSocket 메시지 전송 (새로운 구조)
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
                "showWhen": f.get("show_when"),
                "parentField": f.get("parent_field"),
                "depth": f.get("depth", 0)
            } for f in hierarchy_data.get("visible_fields", default_fields)],
            "collectedInfo": collected_info,
            "completionStatus": hierarchy_data.get("completion_status", {f["key"]: f["key"] in collected_info for f in default_fields}),
            "completionRate": hierarchy_data.get("completion_rate", overall_progress),
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
    """시나리오 시작 시 default 값들을 collected_info에 설정 (조건부 필드 고려)"""
    from ...graph.utils import get_active_scenario_data
    
    scenario_data = get_active_scenario_data(state)
    collected_info = state.get("collected_product_info", {}).copy()
    
    if not scenario_data:
        return collected_info
    
    # 기본정보(customer_name, customer_phone)만 default 값 설정
    for field in scenario_data.get("required_info_fields", []):
        field_key = field["key"]
        
        # 기본정보 필드만 처리
        if field_key not in ["customer_name", "customer_phone"]:
            continue
        
        # 이미 값이 있으면 skip
        if field_key in collected_info:
            continue
            
        # default 값이 있으면 설정
        if "default" in field:
            collected_info[field_key] = field["default"]
            print(f"Initialized default value: {field_key} = {field['default']}")
    
    return collected_info