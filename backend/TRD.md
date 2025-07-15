# Technical Requirements Document - Slot Filling Updates

## 개요
프론트엔드에서 실시간으로 slot filling 정보를 표시할 수 있도록 WebSocket을 통해 업데이트를 전송하는 기능 구현

## 목표
- 에이전트가 정보를 수집할 때마다 프론트엔드에 실시간 업데이트 전송
- 현재 수집된 정보와 필요한 정보를 구조화된 형태로 제공
- 시나리오별 required_info_fields 진행 상황 표시

## 현재 구조 분석
- WebSocket 핸들러는 `app/api/V1/chat.py`에 통합되어 있음
- 상태 관리는 `app/graph/state.py`의 `AgentState`를 통해 이루어짐
- 모든 시나리오 JSON에 `required_info_fields` 배열이 정의됨

## 기술 요구사항

### 1. WebSocket 메시지 타입 추가
**파일**: `app/api/V1/chat.py`

새로운 메시지 타입 추가:
```python
# 기존 메시지 타입들과 함께 추가
slot_filling_update = {
    "type": "slot_filling_update",
    "product_type": str,  # 현재 상품 타입
    "required_fields": List[Dict],  # 필요한 필드 정보
    "collected_info": Dict[str, Any],  # 수집된 정보
    "completion_status": Dict[str, bool]  # 각 필드의 완료 상태
}
```

### 2. 에이전트 실행 후 업데이트 전송
**파일**: `app/api/V1/chat.py`의 `websocket_endpoint()` 함수 수정

collect_product_info 노드 실행 후:
- `collected_product_info` 변경 감지
- 변경사항이 있을 경우 `slot_filling_update` 메시지 전송

### 3. Slot Filling 정보 구조화
**구현 위치**: `app/api/V1/chat.py` 내 유틸리티 함수

필요한 함수:
- `get_slot_filling_status()`: 현재 수집 상태 반환
- `send_slot_filling_update()`: WebSocket으로 업데이트 전송

### 4. 구현 세부사항

```python
# chat.py 내 구현
async def send_slot_filling_update(websocket: WebSocket, state: AgentState):
    """Slot filling 상태 업데이트를 WebSocket으로 전송"""
    scenario_data = state.get("active_scenario_data")
    if not scenario_data:
        return
    
    required_fields = scenario_data.get("required_info_fields", [])
    collected_info = state.get("collected_product_info", {})
    
    # Frontend 인터페이스에 맞게 필드 변환
    frontend_fields = []
    for field in required_fields:
        frontend_field = {
            "key": field["key"],
            "displayName": field.get("display_name", field.get("name", "")),
            "type": field.get("type", "text"),
            "required": field.get("required", True),
        }
        
        # 선택형 필드의 choices 추가
        if field.get("type") == "choice" and "choices" in field:
            frontend_field["choices"] = field["choices"]
        
        # 숫자형 필드의 unit 추가
        if field.get("type") == "number" and "unit" in field:
            frontend_field["unit"] = field["unit"]
            
        # 설명 추가
        if "description" in field:
            frontend_field["description"] = field["description"]
            
        # 의존성 정보 추가
        if "depends_on" in field:
            frontend_field["dependsOn"] = field["depends_on"]
            
        frontend_fields.append(frontend_field)
    
    # completion_status 계산
    completion_status = {
        field["key"]: field["key"] in collected_info 
        for field in required_fields
    }
    
    # 수집률 계산
    total_fields = len(required_fields)
    completed_fields = sum(completion_status.values())
    completion_rate = (completed_fields / total_fields * 100) if total_fields > 0 else 0
    
    update_message = {
        "type": "slot_filling_update",
        "product_type": state.get("current_product_type"),
        "required_fields": frontend_fields,  # 변환된 필드 사용
        "collected_info": collected_info,
        "completion_status": completion_status,
        "completion_rate": completion_rate
    }
    
    # field_groups가 있으면 추가
    if "field_groups" in scenario_data:
        update_message["field_groups"] = scenario_data["field_groups"]
    
    await websocket.send_json(update_message)
```

### 5. 업데이트 트리거 위치
- `collect_product_info` 노드 실행 후
- 시나리오 변경 시
- 사용자가 정보를 수정할 때
- 세션 초기화 시 (초기 상태 전송)

## 시나리오 JSON 구조 개선사항

### 1. 필드 타입 명확화
각 `required_info_fields`의 항목에 추가 메타데이터:
```json
{
  "key": "marital_status",
  "name": "결혼 상태",
  "type": "choice",
  "options": ["미혼", "기혼", "예비부부"],
  "required": true,
  "description": "고객의 결혼 상태 정보"
}
```

### 2. 그룹화 지원
관련 필드들을 그룹으로 표시:
```json
"field_groups": [
  {
    "id": "personal_info",
    "name": "개인 정보",
    "fields": ["marital_status", "has_home"]
  },
  {
    "id": "financial_info", 
    "name": "재무 정보",
    "fields": ["annual_income", "target_home_price"]
  }
]
```

### 3. 의존성 표현
특정 필드가 다른 필드에 의존하는 경우:
```json
{
  "key": "spouse_income",
  "depends_on": {
    "field": "marital_status",
    "value": "기혼"
  }
}
```

## 테스트 요구사항
1. 정보 수집 시 WebSocket 메시지 전송 확인
2. 여러 정보가 동시에 수집될 때 정확한 업데이트
3. 시나리오 변경 시 required_fields 업데이트
4. 수집률(completion_rate) 계산 정확도

## Frontend 인터페이스 고려사항

### 1. WebSocket 메시지 형식
Frontend가 기대하는 메시지 구조:
```typescript
interface SlotFillingUpdate {
  type: 'slot_filling_update'
  productType: string | null
  requiredFields: RequiredField[]
  collectedInfo: Record<string, any>
  completionStatus: Record<string, boolean>
  completionRate?: number
}

interface RequiredField {
  key: string
  displayName: string  // Frontend 표시용 이름
  type: 'boolean' | 'text' | 'choice' | 'number'
  required: boolean
  choices?: string[]   // choice 타입일 경우
  unit?: string       // number 타입일 경우 (예: "만원")
}
```

### 2. 시나리오 JSON 필드 매핑
현재 Backend 필드를 Frontend 인터페이스에 맞게 변환:
- `display_name` → `displayName`
- `choices` → 배열 형태로 제공
- `description` → Frontend에서는 툴팁으로 활용 가능

### 3. 업데이트 빈도 최적화
- 정보가 변경될 때만 업데이트 전송
- 동일한 정보 재전송 방지를 위한 이전 상태 비교

### 4. 그룹화 정보 제공
Frontend의 섹션별 표시를 위해 `field_groups` 추가 고려

## 배포 고려사항
- 기존 WebSocket 연결과의 호환성 유지
- 메시지 크기 최적화 (불필요한 데이터 제거)
- 프론트엔드 타입 정의와 동기화
- CORS 설정 확인 (개발/운영 환경별)