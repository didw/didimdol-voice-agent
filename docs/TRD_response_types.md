# TRD: 입출금통장 개설 시나리오 답변 유형 시스템 기술 요구사항

## 1. 개요

### 1.1 목적
PRD에서 정의한 답변 유형 시스템을 구현하기 위한 기술적 요구사항과 구현 방안을 정의한다.

### 1.2 기술 스택
- **Backend**: Python, FastAPI, LangGraph, Pydantic
- **Frontend**: Vue.js 3, TypeScript, Pinia
- **통신**: WebSocket (실시간 양방향 통신)

## 2. 데이터 모델 설계

### 2.1 답변 유형 열거형
```python
# backend/app/graph/models.py
from enum import Enum

class ResponseType(str, Enum):
    NARRATIVE = "narrative"  # 줄글 형태
    BULLET = "bullet"        # 블릿 형태
    BOOLEAN = "boolean"      # True/False 형태
```

### 2.2 단계별 응답 구조
```python
# backend/app/graph/state.py
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

class StageResponse(BaseModel):
    stage_id: str
    response_type: ResponseType
    prompt: str
    choices: Optional[List[Dict[str, Any]]] = None  # bullet/boolean용
    skippable: bool = False
    modifiable_fields: Optional[List[str]] = None
```

### 2.3 WebSocket 메시지 구조
```typescript
// frontend/src/types/response.ts
export interface StageResponseMessage {
  type: 'stage_response';
  stageId: string;
  responseType: 'narrative' | 'bullet' | 'boolean';
  prompt: string;
  choices?: Array<{
    value: string;
    label: string;
    metadata?: any;
  }>;
  skippable: boolean;
  modifiableFields?: string[];
}
```

## 3. 시나리오 JSON 구조 수정

### 3.1 deposit_account_scenario.json 업데이트
```json
{
  "stages": {
    "account_limit_notice": {
      "stage_id": "account_limit_notice",
      "response_type": "narrative",
      "prompt": "입출금 계좌 가입을 도와드릴게요. 통장은 한도계좌로 먼저 개설되며, 서류지참시 일반 계좌로 전환가능합니다. 한도계좌로 개설 진행해 드릴까요?",
      "expected_info_key": "proceed_with_limit_account",
      "skippable": false
    },
    "customer_info_check": {
      "stage_id": "customer_info_check",
      "response_type": "narrative",
      "prompt": "감사합니다. 그럼 한도계좌로 입출금 통장 개설 도와드릴게요. 제가 가지고 있는 정보는 다음과 같습니다. 아래 내용이 모두 맞으신가요?",
      "display_fields": ["customer_name", "phone_number", "address"],
      "modifiable_fields": ["customer_name", "phone_number", "address"],
      "expected_info_key": "confirm_personal_info"
    },
    "lifelong_account_check": {
      "stage_id": "lifelong_account_check",
      "response_type": "narrative",
      "prompt": "다음으로, 통장 개설 시 평생 계좌 등록여부를 선택하실 수 있습니다. 평생계좌로 등록하시겠어요?",
      "expected_info_key": "use_lifelong_account",
      "skippable": true
    },
    "internet_banking_check": {
      "stage_id": "internet_banking_check",
      "response_type": "narrative",
      "prompt": "쏠이나 인터넷에서도 개설하시는 통장 사용할 수 있도록 도와드릴까요?",
      "expected_info_key": "use_internet_banking",
      "skippable": true,
      "sub_stages": ["security_medium_select", "transfer_limit_set", "notification_settings"]
    },
    "security_medium_select": {
      "stage_id": "security_medium_select",
      "response_type": "bullet",
      "prompt": "보안매체는 어떤걸로 하시겠어요?",
      "choices": [
        {"value": "security_card", "label": "보안카드"},
        {"value": "shinhan_otp", "label": "신한 OTP"},
        {"value": "other_otp", "label": "타행 OTP"}
      ],
      "expected_info_key": "security_medium",
      "parent_stage": "internet_banking_check",
      "show_when": "use_internet_banking == true"
    },
    "notification_settings": {
      "stage_id": "notification_settings",
      "response_type": "boolean",
      "prompt": "중요거래 알림, 출금내역 알림, 해외IP 제한 여부를 말씀해주세요.",
      "choices": [
        {"key": "important_transaction_alert", "label": "중요거래 알림", "default": true},
        {"key": "withdrawal_alert", "label": "출금내역 알림", "default": true},
        {"key": "overseas_ip_restriction", "label": "해외IP 제한", "default": false}
      ],
      "expected_info_key": "notification_preferences",
      "parent_stage": "internet_banking_check"
    }
  }
}
```

## 4. Backend 구현

### 4.1 시나리오 로직 확장
```python
# backend/app/graph/nodes/workers/scenario_logic.py

async def generate_stage_response(
    state: AgentState,
    stage_info: Dict[str, Any]
) -> Dict[str, Any]:
    """단계별 응답 유형에 맞는 메시지 생성"""
    
    response_type = stage_info.get("response_type", "narrative")
    prompt = stage_info.get("prompt", "")
    
    # 동적 내용 처리 (예: 고객 정보 표시)
    if stage_info.get("display_fields"):
        prompt = format_prompt_with_fields(
            prompt, 
            state.collected_product_info,
            stage_info["display_fields"]
        )
    
    response_data = {
        "stage_id": stage_info["stage_id"],
        "response_type": response_type,
        "prompt": prompt,
        "skippable": stage_info.get("skippable", False)
    }
    
    # 선택지가 있는 경우
    if response_type in ["bullet", "boolean"]:
        response_data["choices"] = stage_info.get("choices", [])
    
    # 수정 가능한 필드 정보
    if stage_info.get("modifiable_fields"):
        response_data["modifiable_fields"] = stage_info["modifiable_fields"]
    
    return response_data

def format_prompt_with_fields(
    prompt: str, 
    collected_info: Dict[str, Any],
    display_fields: List[str]
) -> str:
    """프롬프트에 수집된 정보 동적 삽입"""
    
    field_display = []
    for field_key in display_fields:
        value = collected_info.get(field_key, "미입력")
        field_name = get_field_display_name(field_key)
        field_display.append(f"- {field_name}: {value}")
    
    if field_display:
        prompt += "\n" + "\n".join(field_display)
    
    return prompt
```

### 4.2 WebSocket 메시지 전송
```python
# backend/app/api/V1/chat.py

async def send_stage_response(
    websocket: WebSocket,
    stage_response: Dict[str, Any],
    session_id: str
) -> None:
    """단계별 응답을 WebSocket으로 전송"""
    
    message = {
        "type": "stage_response",
        "sessionId": session_id,
        **stage_response
    }
    
    await websocket.send_json(message)
    print(f"[{session_id}] Stage response sent: {stage_response['stage_id']} ({stage_response['response_type']})")
```

### 4.3 사용자 입력 처리
```python
# backend/app/graph/nodes/workers/scenario_helpers.py

def parse_user_input_by_response_type(
    user_input: str,
    response_type: str,
    choices: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """응답 유형에 따른 사용자 입력 파싱"""
    
    if response_type == "narrative":
        # 자유로운 텍스트 입력 처리
        return {"raw_input": user_input}
    
    elif response_type == "bullet":
        # 선택지 매칭
        if choices:
            matched = match_user_input_to_choice(user_input, choices)
            if matched:
                return {"selected_choice": matched["value"]}
        return {"raw_input": user_input}
    
    elif response_type == "boolean":
        # True/False 변환
        boolean_values = parse_boolean_inputs(user_input, choices)
        return {"boolean_selections": boolean_values}
    
    return {"raw_input": user_input}

def parse_boolean_inputs(
    user_input: str,
    choices: List[Dict[str, str]]
) -> Dict[str, bool]:
    """복수의 boolean 선택 파싱"""
    
    results = {}
    for choice in choices:
        key = choice["key"]
        # 긍정/부정 표현 분석
        if "신청" in user_input and choice["label"] in user_input:
            results[key] = True
        elif "미신청" in user_input and choice["label"] in user_input:
            results[key] = False
        else:
            # 기본값 사용
            results[key] = choice.get("default", False)
    
    return results
```

### 4.4 부분 응답 처리 및 유효성 검증
```python
# backend/app/graph/nodes/workers/scenario_logic.py

async def process_partial_response(
    stage_id: str,
    user_input: str,
    required_fields: List[str],
    collected_info: Dict[str, Any],
    field_validators: Dict[str, Any]
) -> Dict[str, Any]:
    """부분 응답 처리 및 유효성 검증"""
    
    # 1. Entity Agent를 통한 개별 필드 추출
    extracted_entities = await entity_agent.extract_entities(
        user_input, 
        required_fields
    )
    
    # 2. 유효성 검증
    validation_results = {}
    for field_key, value in extracted_entities.items():
        validator = field_validators.get(field_key)
        if validator:
            is_valid, error_message = validator.validate(value)
            validation_results[field_key] = {
                "is_valid": is_valid,
                "error_message": error_message,
                "value": value
            }
    
    # 3. 유효한 값만 collected_info에 저장
    valid_fields = []
    invalid_fields = []
    for field_key, result in validation_results.items():
        if result["is_valid"]:
            collected_info[field_key] = result["value"]
            valid_fields.append(field_key)
        else:
            invalid_fields.append({
                "field": field_key,
                "error": result["error_message"]
            })
    
    # 4. 미수집 필드 확인
    missing_fields = [
        field for field in required_fields 
        if field not in collected_info
    ]
    
    # 5. 재질문 생성
    if invalid_fields or missing_fields:
        response_text = generate_re_prompt(
            valid_fields, 
            invalid_fields, 
            missing_fields
        )
    else:
        response_text = None  # 모든 정보 수집 완료
    
    return {
        "collected_info": collected_info,
        "valid_fields": valid_fields,
        "invalid_fields": invalid_fields,
        "missing_fields": missing_fields,
        "response_text": response_text,
        "is_complete": not (invalid_fields or missing_fields)
    }

def generate_re_prompt(
    valid_fields: List[str],
    invalid_fields: List[Dict[str, str]],
    missing_fields: List[str]
) -> str:
    """재질문 프롬프트 생성"""
    
    response_parts = []
    
    # 유효한 필드에 대한 확인 메시지
    if valid_fields:
        field_names = get_display_names(valid_fields)
        response_parts.append(
            f"{', '.join(field_names)}은(는) 확인했습니다."
        )
    
    # 유효하지 않은 필드에 대한 재질문
    if invalid_fields:
        for field_info in invalid_fields:
            response_parts.append(field_info["error"])
    
    # 누락된 필드에 대한 질문
    if missing_fields:
        field_names = get_display_names(missing_fields)
        response_parts.append(
            f"{', '.join(field_names)}도 함께 말씀해주세요."
        )
    
    return " ".join(response_parts)
```

### 4.5 필드별 검증 규칙
```python
# backend/app/graph/validators.py

class TransferLimitValidator:
    """이체한도 검증"""
    
    def __init__(self, max_limit: int, field_type: str):
        self.max_limit = max_limit
        self.field_type = field_type
    
    def validate(self, value: Any) -> Tuple[bool, Optional[str]]:
        try:
            amount = int(value)
            if amount <= 0:
                return False, f"{self.field_type}는 0보다 커야 합니다."
            if amount > self.max_limit:
                return False, f"{self.field_type}는 최대 {self.max_limit:,}만원까지 가능합니다. {self.max_limit:,}만원 이하로 다시 말씀해주세요."
            return True, None
        except (ValueError, TypeError):
            return False, f"올바른 숫자 형식으로 말씀해주세요."

class PhoneNumberValidator:
    """전화번호 검증"""
    
    def validate(self, value: str) -> Tuple[bool, Optional[str]]:
        import re
        pattern = r'^01[0-9]-?\d{3,4}-?\d{4}$'
        if re.match(pattern, value.replace("-", "")):
            return True, None
        return False, "올바른 휴대폰 번호 형식으로 다시 말씀해주세요. 예: 010-1234-5678"

# 필드별 검증기 매핑
FIELD_VALIDATORS = {
    "transfer_limit_per_time": TransferLimitValidator(5000, "1회 이체한도"),
    "transfer_limit_per_day": TransferLimitValidator(10000, "1일 이체한도"),
    "phone_number": PhoneNumberValidator(),
    # ... 추가 필드별 검증기
}
```

## 5. Frontend 구현

### 5.1 동적 UI 컴포넌트
```vue
<!-- frontend/src/components/StageResponse.vue -->
<template>
  <div class="stage-response">
    <!-- Narrative 타입 -->
    <div v-if="responseType === 'narrative'" class="narrative-response">
      <p>{{ prompt }}</p>
    </div>
    
    <!-- Bullet 타입 -->
    <div v-else-if="responseType === 'bullet'" class="bullet-response">
      <p>{{ prompt }}</p>
      <div class="choices">
        <button 
          v-for="choice in choices" 
          :key="choice.value"
          @click="selectChoice(choice.value)"
          class="choice-button"
        >
          {{ choice.label }}
        </button>
      </div>
    </div>
    
    <!-- Boolean 타입 -->
    <div v-else-if="responseType === 'boolean'" class="boolean-response">
      <p>{{ prompt }}</p>
      <div class="boolean-choices">
        <div 
          v-for="choice in choices" 
          :key="choice.key"
          class="boolean-item"
        >
          <span>{{ choice.label }}</span>
          <label class="toggle-switch">
            <input 
              type="checkbox" 
              v-model="booleanSelections[choice.key]"
              @change="updateBoolean(choice.key)"
            />
            <span class="toggle-slider"></span>
          </label>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { useWebSocketStore } from '@/stores/webSocket';

interface Props {
  stageId: string;
  responseType: 'narrative' | 'bullet' | 'boolean';
  prompt: string;
  choices?: Array<{
    value?: string;
    label: string;
    key?: string;
    default?: boolean;
  }>;
}

const props = defineProps<Props>();
const wsStore = useWebSocketStore();

const booleanSelections = ref<Record<string, boolean>>({});

// Boolean 초기값 설정
if (props.responseType === 'boolean' && props.choices) {
  props.choices.forEach(choice => {
    if (choice.key) {
      booleanSelections.value[choice.key] = choice.default || false;
    }
  });
}

const selectChoice = (value: string) => {
  wsStore.sendMessage({
    type: 'user_choice_selection',
    stageId: props.stageId,
    selectedChoice: value
  });
};

const updateBoolean = (key: string) => {
  wsStore.sendMessage({
    type: 'user_boolean_selection',
    stageId: props.stageId,
    booleanSelections: booleanSelections.value
  });
};
</script>
```

### 5.2 Pinia Store 업데이트
```typescript
// frontend/src/stores/conversation.ts
import { defineStore } from 'pinia';

interface StageResponseData {
  stageId: string;
  responseType: 'narrative' | 'bullet' | 'boolean';
  prompt: string;
  choices?: any[];
  skippable: boolean;
  modifiableFields?: string[];
}

export const useConversationStore = defineStore('conversation', {
  state: () => ({
    currentStageResponse: null as StageResponseData | null,
    stageHistory: [] as StageResponseData[],
  }),
  
  actions: {
    updateStageResponse(response: StageResponseData) {
      this.currentStageResponse = response;
      this.stageHistory.push(response);
    },
    
    handleUserModificationRequest(field: string) {
      // 정보 수정 요청 처리
      if (this.currentStageResponse?.modifiableFields?.includes(field)) {
        // 수정 모드 진입
        this.enterModificationMode(field);
      }
    },
    
    skipCurrentStage() {
      if (this.currentStageResponse?.skippable) {
        // 현재 단계 건너뛰기
        this.sendSkipRequest();
      }
    }
  }
});
```

## 6. 테스트 계획

### 6.1 단위 테스트
```python
# backend/tests/test_response_types.py
import pytest
from app.graph.nodes.workers.scenario_helpers import parse_user_input_by_response_type

class TestResponseTypeParsing:
    def test_bullet_type_parsing(self):
        choices = [
            {"value": "security_card", "label": "보안카드"},
            {"value": "shinhan_otp", "label": "신한 OTP"}
        ]
        result = parse_user_input_by_response_type(
            "보안카드로 할게요", 
            "bullet", 
            choices
        )
        assert result["selected_choice"] == "security_card"
    
    def test_boolean_type_parsing(self):
        choices = [
            {"key": "important_alert", "label": "중요거래 알림"},
            {"key": "withdrawal_alert", "label": "출금내역 알림"}
        ]
        result = parse_user_input_by_response_type(
            "중요거래 알림은 신청하고 출금내역은 미신청할게요",
            "boolean",
            choices
        )
        assert result["boolean_selections"]["important_alert"] == True
        assert result["boolean_selections"]["withdrawal_alert"] == False
    
    def test_partial_response_processing(self):
        """부분 응답 처리 테스트"""
        collected_info = {}
        required_fields = ["transfer_limit_per_time", "transfer_limit_per_day"]
        
        # 첫 번째 응답: 1회 이체한도만 제공
        result = await process_partial_response(
            "ask_transfer_limit",
            "1회 500만원으로 해주세요",
            required_fields,
            collected_info,
            FIELD_VALIDATORS
        )
        
        assert result["valid_fields"] == ["transfer_limit_per_time"]
        assert result["missing_fields"] == ["transfer_limit_per_day"]
        assert "1일 이체한도도 함께 말씀해주세요" in result["response_text"]
        
    def test_validation_failure(self):
        """유효성 검증 실패 테스트"""
        collected_info = {}
        required_fields = ["transfer_limit_per_time"]
        
        # 한도 초과 값 입력
        result = await process_partial_response(
            "ask_transfer_limit",
            "1회 1억원으로 해주세요",
            required_fields,
            collected_info,
            FIELD_VALIDATORS
        )
        
        assert result["invalid_fields"][0]["field"] == "transfer_limit_per_time"
        assert "최대 5,000만원까지 가능합니다" in result["invalid_fields"][0]["error"]
```

### 6.2 통합 테스트
- 각 단계별 응답 유형 전송 확인
- UI 컴포넌트 렌더링 검증
- 사용자 입력 처리 및 상태 업데이트 확인
- 부분 응답 처리 흐름 검증
- 유효성 검증 및 재질문 생성 확인

## 7. 배포 고려사항

### 7.1 하위 호환성
- 기존 시나리오 JSON과의 호환성 유지
- response_type 필드가 없는 경우 기본값 "narrative" 사용

### 7.2 점진적 마이그레이션
1. 새로운 필드 추가 (response_type, choices 등)
2. Frontend UI 컴포넌트 배포
3. Backend 로직 업데이트
4. 시나리오 JSON 점진적 업데이트

### 7.3 모니터링
- 각 응답 유형별 사용률 추적
- 사용자 입력 오류율 모니터링
- 응답 시간 성능 측정

## 8. Slot Filling UI 시스템 기술 요구사항

### 8.1 실시간 정보 수집 표시 시스템

#### 8.1.1 데이터 모델
```python
# backend/app/api/V1/chat_utils.py
@dataclass
class SlotFillingUpdate:
    """WebSocket으로 전송될 Slot Filling 업데이트 구조"""
    type: str = "slot_filling_update"
    product_type: str
    required_fields: List[Dict[str, Any]]  # 표시할 필드들
    collected_info: Dict[str, Any]  # 수집된 정보
    completion_status: Dict[str, bool]  # 필드별 완료 상태
    completion_rate: float  # 진행률 (%)
    completed_count: int  # 완료된 필드 수
    total_count: int  # 전체 필드 수
    field_groups: List[Dict[str, Any]]  # 필드 그룹 정보
    current_stage: str  # 현재 진행 단계
```

#### 8.1.2 단계별 필드 노출 로직
```python
def get_contextual_visible_fields(scenario_data: Dict, collected_info: Dict, current_stage: str) -> List[Dict]:
    """현재 단계에 맞는 필드들만 선별적으로 반환"""
    
    # 단계별 필드 그룹 정의
    stage_groups = {
        "customer_info": ["customer_name", "phone_number", "address", "confirm_personal_info"],
        "transfer_limit": ["transfer_limit_per_time", "transfer_limit_per_day"],
        "notification": ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"],
        "check_card": ["use_check_card", "card_type", "card_receive_method", "card_delivery_location", 
                      "postpaid_transport", "card_usage_alert", "statement_method"],
        "internet_banking": ["use_internet_banking", "security_medium", "initial_password", "other_otp_info",
                            "transfer_limit_per_time", "transfer_limit_per_day",
                            "important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
    }
    
    # 현재 단계와 수집 상태에 따른 필드 필터링
    allowed_fields = determine_allowed_fields(current_stage, collected_info, stage_groups)
    
    # 조건부 필드 평가 (show_when)
    visible_fields = evaluate_conditional_fields(scenario_data, allowed_fields, collected_info)
    
    return visible_fields
```

### 8.2 진행률 표시 시스템

#### 8.2.1 진행률 계산 로직
```python
def calculate_completion_rate(visible_fields: List[Dict], collected_info: Dict) -> Dict[str, Any]:
    """전체 필수 정보 대비 수집 완료 비율 계산"""
    
    # 필수 필드만 추출
    required_fields = [f for f in visible_fields if f.get("required", True)]
    total_required = len(required_fields)
    
    # 완료된 필드 수 계산
    completed_fields = [
        f for f in required_fields 
        if is_field_completed(f, collected_info)
    ]
    completed_count = len(completed_fields)
    
    # 진행률 계산
    completion_rate = (completed_count / total_required * 100) if total_required > 0 else 0
    
    return {
        "completion_rate": round(completion_rate, 1),
        "completed_count": completed_count,
        "total_count": total_required
    }
```

#### 8.2.2 Frontend 진행률 컴포넌트
```vue
<!-- frontend/src/components/ProgressBar.vue -->
<template>
  <div class="progress-section">
    <div class="progress-header">
      <h3>정보 수집 현황</h3>
      <span class="percentage">{{ completionRate }}%</span>
    </div>
    <div class="progress-bar-container">
      <div 
        class="progress-bar-fill" 
        :style="{ width: completionRate + '%' }"
        :class="{ 
          'in-progress': completionRate > 0 && completionRate < 100,
          'complete': completionRate === 100 
        }"
      >
        <div class="progress-animation"></div>
      </div>
    </div>
    <p class="progress-detail">
      수집 완료: {{ completedCount }}개 / 전체: {{ totalCount }}개
    </p>
  </div>
</template>

<style scoped>
.progress-bar-container {
  width: 100%;
  height: 24px;
  background-color: #f0f0f0;
  border-radius: 12px;
  overflow: hidden;
  position: relative;
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #4caf50, #45a049);
  transition: width 0.3s ease;
  position: relative;
}

.progress-bar-fill.complete {
  background: linear-gradient(90deg, #2196f3, #1976d2);
}

.progress-animation {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(255, 255, 255, 0.3),
    transparent
  );
  animation: progress-shine 2s infinite;
}

@keyframes progress-shine {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}
</style>
```

### 8.3 사용자 정보 수정 시스템

#### 8.3.1 수정 요청 처리 엔진
```python
# backend/app/graph/nodes/workers/modification_handler.py
class ModificationHandler:
    """사용자의 정보 수정 요청 처리"""
    
    async def process_modification_request(
        self, 
        user_input: str, 
        collected_info: Dict[str, Any],
        scenario_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        
        # 1. 수정 의도 분석
        modification_intent = await self.extract_modification_intent(user_input)
        
        # 2. 대조 표현 처리
        if self.is_contrast_expression(user_input):
            return await self.handle_contrast_modification(user_input, collected_info)
        
        # 3. 직접 수정 요청 처리
        if modification_intent.field and modification_intent.new_value:
            return await self.apply_direct_modification(
                modification_intent.field,
                modification_intent.new_value,
                collected_info
            )
        
        return {"status": "no_modification_needed"}
```

#### 8.3.2 Frontend 수정 인터페이스
```typescript
// frontend/src/stores/slotFillingStore.ts
export const useSlotFillingStore = defineStore('slotFilling', {
  state: () => ({
    // ... 기존 state
    modificationMode: false,
    selectedFieldForModification: null as string | null,
  }),
  
  actions: {
    async requestFieldModification(field: string, newValue: any) {
      // WebSocket으로 수정 요청 전송
      const chatStore = useChatStore()
      await chatStore.sendModificationRequest({
        type: 'field_modification',
        field: field,
        newValue: newValue,
        currentValue: this.collectedInfo[field]
      })
    },
    
    handleModificationResponse(response: any) {
      if (response.success) {
        // 수정 성공 시 즉시 UI 업데이트
        this.collectedInfo[response.field] = response.newValue
        this.updateCompletionStatus()
        
        // 시각적 피드백
        this.showModificationSuccess(response.field)
      }
    }
  }
})
```

### 8.4 WebSocket 통신 프로토콜

#### 8.4.1 메시지 타입 정의
```typescript
// frontend/src/types/slotFilling.ts
export enum SlotFillingMessageType {
  UPDATE = 'slot_filling_update',
  MODIFICATION_REQUEST = 'field_modification_request',
  MODIFICATION_RESPONSE = 'field_modification_response',
  STAGE_CHANGED = 'stage_changed'
}

export interface SlotFillingWebSocketMessage {
  type: SlotFillingMessageType
  sessionId: string
  timestamp: string
  data: any
}
```

#### 8.4.2 실시간 동기화 로직
```python
# backend/app/api/V1/chat.py
async def send_slot_filling_update(
    websocket: WebSocket, 
    session_id: str,
    trigger: str = "auto"
):
    """Slot Filling 상태를 실시간으로 전송"""
    
    session_state = SESSION_STATES.get(session_id)
    if not session_state:
        return
    
    # 현재 상태 기반 업데이트 데이터 생성
    update_data = update_slot_filling_with_hierarchy(
        session_state.get("active_scenario_data"),
        session_state.get("collected_product_info", {}),
        session_state.get("current_stage", "")
    )
    
    # WebSocket으로 전송
    await websocket.send_json({
        "type": "slot_filling_update",
        "trigger": trigger,
        **update_data
    })
```

### 8.5 성능 최적화

#### 8.5.1 Debouncing 전략
```typescript
// frontend/src/composables/useDebounce.ts
export function useDebouncedSlotUpdate() {
  const pending = ref(false)
  const timeoutId = ref<number | null>(null)
  
  const debouncedUpdate = (updateFn: () => void, delay: number = 300) => {
    if (timeoutId.value) {
      clearTimeout(timeoutId.value)
    }
    
    pending.value = true
    timeoutId.value = window.setTimeout(() => {
      updateFn()
      pending.value = false
    }, delay)
  }
  
  return { debouncedUpdate, pending }
}
```

#### 8.5.2 캐싱 전략
```python
# backend/app/api/V1/chat_utils.py
from functools import lru_cache

@lru_cache(maxsize=128)
def get_field_hierarchy_cached(scenario_json_str: str) -> Dict:
    """시나리오 필드 계층 구조를 캐싱하여 반복 계산 방지"""
    scenario_data = json.loads(scenario_json_str)
    return calculate_field_hierarchy(scenario_data)
```

## 9. 테스트 전략

### 9.1 단위 테스트
```python
# backend/tests/test_slot_filling.py
class TestSlotFilling:
    def test_contextual_field_visibility(self):
        """단계별 필드 노출이 올바른지 테스트"""
        collected_info = {"use_internet_banking": True}
        current_stage = "ask_security_medium"
        
        visible_fields = get_contextual_visible_fields(
            scenario_data, collected_info, current_stage
        )
        
        # security_medium 필드가 표시되는지 확인
        field_keys = [f["key"] for f in visible_fields]
        assert "security_medium" in field_keys
    
    def test_completion_rate_calculation(self):
        """진행률 계산이 정확한지 테스트"""
        visible_fields = [
            {"key": "name", "required": True},
            {"key": "phone", "required": True},
            {"key": "address", "required": False}
        ]
        collected_info = {"name": "홍길동", "phone": "010-1234-5678"}
        
        result = calculate_completion_rate(visible_fields, collected_info)
        
        assert result["completion_rate"] == 100.0  # 필수 필드 2개 모두 완료
        assert result["completed_count"] == 2
        assert result["total_count"] == 2
```

### 9.2 통합 테스트
- Slot Filling 실시간 업데이트 검증
- 진행률 바 동적 업데이트 확인
- 정보 수정 플로우 전체 검증
- WebSocket 연결 안정성 테스트

## 10. 향후 확장 계획

### 10.1 추가 응답 유형
- **grid**: 표 형태의 정보 표시
- **slider**: 수치 입력을 위한 슬라이더
- **multi-select**: 다중 선택 가능한 체크박스

### 10.2 AI 기반 입력 이해 향상
- 자연어 처리를 통한 선택지 매칭 정확도 향상
- 컨텍스트 기반 입력 해석
- 정보 수정 의도 자동 감지

### 10.3 개인화 및 학습
- 사용자별 선호 응답 유형 학습
- 상황별 최적 응답 유형 자동 선택
- 수정 패턴 학습을 통한 예측 제안