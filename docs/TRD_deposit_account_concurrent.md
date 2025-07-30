# 입출금 동시신규 시나리오 TRD

## 1. 개요

### 1.1 목적
PRD_deposit_account_concurrent.md에 정의된 입출금 동시신규 시나리오의 기술적 구현 방안을 상세히 정의한다.

### 1.2 대상 시스템
- Backend: Python/FastAPI/LangGraph
- Frontend: Vue.js/TypeScript
- 음성 처리: Google STT/TTS
- LLM: OpenAI GPT

## 2. 시나리오 구조 정의

### 2.1 시나리오 ID
- **scenario_id**: `deposit_account_concurrent`
- **scenario_name**: "입출금 동시신규"
- **product_type**: `deposit_account`

### 2.2 Stage 구조

```json
{
  "scenario_id": "deposit_account_concurrent",
  "scenario_name": "입출금 동시신규",
  "stages": {
    "1": {
      "stage_id": "select_services",
      "stage_name": "필요 업무 확인",
      "response_type": "bullet",
      "prompt": "입출금 계좌는 한도계좌로만 가입할 수 있어요.\\n지금 만드시는 계좌를 모바일 앱과 체크카드로 함께 이용할 수 있도록 가입해 드릴까요?",
      "choices": [
        {
          "display": "모두 가입할게요",
          "value": "all",
          "default": true
        },
        {
          "display": "모바일 앱만",
          "value": "mobile_only"
        },
        {
          "display": "체크카드만",
          "value": "card_only"
        },
        {
          "display": "입출금 계좌만",
          "value": "account_only"
        }
      ],
      "additional_questions": [
        "한도 제한 계좌 해제 방법 알려줘",
        "한도가 어느정도 제한되는지 알려줘"
      ]
    },
    "2": {
      "stage_id": "confirm_personal_info",
      "stage_name": "고객 정보 확인",
      "response_type": "narrative",
      "prompt": "네, 먼저 고객님의 개인정보를 확인하겠습니다. 화면에 보이는 내용이 모두 맞으신가요?",
      "fields_to_collect": ["name", "english_name", "ssn", "phone_number", "email", "address", "work_address"],
      "modifiable": true,
      "transition_conditions": {
        "next_stage": {
          "if_value_is": {
            "services_selected": "all"
          },
          "then_go_to": "3"
        }
      }
    },
    "3": {
      "stage_id": "security_medium_registration",
      "stage_name": "보안매체 등록",
      "response_type": "bullet",
      "choice_groups": [
        {
          "group_name": "내가 보유한 보안매체",
          "choices": [
            {
              "display": "미래테크 19284019384",
              "value": "futuretech_19284019384",
              "default": true,
              "metadata": {
                "transfer_limit_once": "50000000",
                "transfer_limit_daily": "100000000"
              }
            },
            {
              "display": "코마스(RSA) 12930295",
              "value": "comas_rsa_12930295",
              "metadata": {
                "transfer_limit_once": "50000000",
                "transfer_limit_daily": "100000000"
              }
            }
          ]
        },
        {
          "group_name": "새로 발급 가능한 보안매체",
          "choices": [
            {
              "display": "보안카드",
              "value": "security_card"
            },
            {
              "display": "신한OTP (10,000원)",
              "value": "shinhan_otp",
              "metadata": {
                "fee": "10000"
              }
            }
          ]
        }
      ],
      "dynamic_prompt": "이어서 보안매체 등록을 진행할게요.\\n고객님이 보유하신 {default_choice}는 1회 5,000만원, 1일 1억까지 이체할 수 있어요.\\n이걸로 등록할까요?",
      "fields_to_collect": ["security_medium", "transfer_limit_once", "transfer_limit_daily"],
      "modifiable_fields": ["transfer_limit_once", "transfer_limit_daily"]
    },
    "4": {
      "stage_id": "additional_services",
      "stage_name": "추가 정보 선택",
      "response_type": "narrative",
      "prompt": "추가 신청 정보를 확인할게요. 중요거래 알림과 출금 알림, 해외 IP 이체 제한을 모두 신청해 드릴까요?",
      "fields_to_collect": ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"],
      "multi_select": true,
      "default_values": {
        "important_transaction_alert": "신청",
        "withdrawal_alert": "신청",
        "overseas_ip_restriction": "신청"
      }
    },
    "5": {
      "stage_id": "card_selection",
      "stage_name": "카드 선택",
      "response_type": "card_list",
      "dynamic_prompt": "이어서 체크카드 발급에 필요한 정보를 확인할게요.\\n지금 바로 수령할 수 있는 {default_choice}로 발급해드릴까요?",
      "cards": [
        {
          "card_id": "sline_transit",
          "display": "S-Line\\n체크카드\\n(후불교통)",
          "value": "sline_transit",
          "default": true,
          "metadata": {
            "receipt_method": "즉시발급",
            "transit_enabled": true
          }
        },
        {
          "card_id": "sline_regular",
          "display": "S-Line\\n체크카드\\n(일반)",
          "value": "sline_regular",
          "metadata": {
            "receipt_method": "즉시발급",
            "transit_enabled": false
          }
        },
        {
          "card_id": "deepdream_transit",
          "display": "신한 Deep Dream\\n체크카드\\n(후불교통)",
          "value": "deepdream_transit",
          "metadata": {
            "receipt_method": "배송",
            "transit_enabled": true
          }
        },
        {
          "card_id": "deepdream_regular",
          "display": "신한 Deep Dream\\n체크카드\\n(일반)",
          "value": "deepdream_regular",
          "metadata": {
            "receipt_method": "배송",
            "transit_enabled": false
          }
        },
        {
          "card_id": "heyyoung_regular",
          "display": "신한카드 Hey Young\\n체크카드\\n(일반)",
          "value": "heyyoung_regular",
          "metadata": {
            "receipt_method": "배송",
            "transit_enabled": false
          }
        }
      ],
      "fields_to_collect": ["card_receipt_method", "card_selection", "transit_function"],
      "additional_questions": [
        "배송되는 카드로 보여줘",
        "후불 교통 카드 기능이 있는 카드만 보여줘"
      ]
    },
    "6": {
      "stage_id": "statement_delivery",
      "stage_name": "명세서 수령 정보 선택",
      "response_type": "bullet",
      "prompt": "카드 명세서는 매월 10일에 휴대폰으로 받아보시겠어요?",
      "choices": [
        {
          "display": "휴대폰",
          "value": "mobile",
          "default": true
        },
        {
          "display": "이메일",
          "value": "email"
        },
        {
          "display": "홈페이지",
          "value": "website"
        }
      ],
      "fields_to_collect": ["statement_delivery_method", "statement_delivery_date"],
      "default_values": {
        "statement_delivery_date": "10"
      }
    },
    "7": {
      "stage_id": "card_usage_alert",
      "stage_name": "카드 사용 알림",
      "response_type": "bullet",
      "prompt": "5만원 이상 결제 시 문자로 사용하신 내역을 보내드릴까요?",
      "choices": [
        {
          "display": "5만원 이상 결제시 발송 (무료)",
          "value": "over_50000_free",
          "default": true
        },
        {
          "display": "모든 내역 발송 (200원, 포인트 우선 차감)",
          "value": "all_transactions_200won"
        },
        {
          "display": "문자 받지 않음",
          "value": "no_alert"
        }
      ],
      "fields_to_collect": ["card_usage_alert"]
    },
    "8": {
      "stage_id": "card_password_setting",
      "stage_name": "카드 비밀번호 설정",
      "response_type": "narrative",
      "prompt": "마지막으로 카드 비밀번호는 계좌 비밀번호와 동일하게 설정하시겠어요?",
      "fields_to_collect": ["card_password_same_as_account"],
      "field_type": "boolean"
    },
    "9": {
      "stage_id": "completion",
      "stage_name": "상담 완료",
      "response_type": "narrative",
      "prompt": "말씀해주신 정보로 가입 도와드릴게요.\\n입력 화면으로 이동하겠습니다.",
      "is_final": true
    }
  }
}
```

## 3. 조건부 플로우 구현

### 3.1 Stage Transition Logic

```python
def determine_next_stage(current_stage_id: str, collected_info: dict) -> str:
    """스테이지 전환 로직"""
    
    # Stage 1 완료 후
    if current_stage_id == "1":
        services_selected = collected_info.get("services_selected")
        if services_selected == "account_only":
            return "9"  # 바로 완료 단계로
        else:
            return "2"  # 고객 정보 확인으로
    
    # Stage 2 완료 후
    elif current_stage_id == "2":
        services_selected = collected_info.get("services_selected")
        info_confirmed = collected_info.get("personal_info_confirmed")
        
        if not info_confirmed:
            # 정보 수정 필요 시 별도 처리
            return "customer_info_update"  # 특수 스테이지
        
        if services_selected == "all" or services_selected == "mobile_only":
            return "3"  # 보안매체 등록으로
        elif services_selected == "card_only":
            return "5"  # 카드 선택으로
    
    # Stage 3 완료 후
    elif current_stage_id == "3":
        return "4"  # 추가 정보 선택으로
    
    # Stage 4 완료 후
    elif current_stage_id == "4":
        services_selected = collected_info.get("services_selected")
        if services_selected == "all":
            return "5"  # 카드 선택으로
        else:
            return "9"  # 완료로
    
    # Stage 5-8: 순차 진행
    elif current_stage_id in ["5", "6", "7"]:
        return str(int(current_stage_id) + 1)
    
    # Stage 8 완료 후
    elif current_stage_id == "8":
        return "9"  # 완료로
    
    return current_stage_id  # 기본값
```

### 3.2 Dynamic Response Generation

```python
def generate_dynamic_response(stage_info: dict, collected_info: dict) -> str:
    """동적 응답 생성"""
    
    if stage_info.get("dynamic_prompt"):
        prompt = stage_info["dynamic_prompt"]
        
        # 기본값 대체
        if "{default_choice}" in prompt:
            default_choice = get_default_choice_display(stage_info)
            prompt = prompt.replace("{default_choice}", default_choice)
        
        # 수집된 정보로 대체
        for key, value in collected_info.items():
            placeholder = f"{{{key}}}"
            if placeholder in prompt:
                prompt = prompt.replace(placeholder, str(value))
        
        return prompt
    
    return stage_info.get("prompt", "")
```

## 4. Slot Filling 구현

### 4.1 슬롯 그룹 정의

```typescript
interface SlotGroup {
  groupId: string;
  groupName: string;
  stageIds: string[];
  fields: SlotField[];
  isCollapsed: boolean;
}

interface SlotField {
  fieldId: string;
  fieldName: string;
  fieldType: 'text' | 'boolean' | 'select';
  value: any;
  options?: string[];
  isRequired: boolean;
}

const slotGroups: SlotGroup[] = [
  {
    groupId: "personal_info",
    groupName: "개인정보 확인",
    stageIds: ["2"],
    fields: [
      { fieldId: "name", fieldName: "이름", fieldType: "text", value: null, isRequired: true },
      { fieldId: "english_name", fieldName: "영문이름", fieldType: "text", value: null, isRequired: true },
      { fieldId: "ssn", fieldName: "주민등록번호", fieldType: "text", value: null, isRequired: true },
      { fieldId: "phone_number", fieldName: "휴대폰번호", fieldType: "text", value: null, isRequired: true },
      { fieldId: "email", fieldName: "이메일", fieldType: "text", value: null, isRequired: true },
      { fieldId: "address", fieldName: "집주소", fieldType: "text", value: null, isRequired: true },
      { fieldId: "work_address", fieldName: "직장주소", fieldType: "text", value: null, isRequired: true }
    ],
    isCollapsed: false
  },
  {
    groupId: "security_medium",
    groupName: "보안매체 등록",
    stageIds: ["3"],
    fields: [
      { fieldId: "security_medium", fieldName: "보안매체", fieldType: "text", value: null, isRequired: true },
      { fieldId: "transfer_limit_once", fieldName: "1회 이체한도", fieldType: "text", value: null, isRequired: true },
      { fieldId: "transfer_limit_daily", fieldName: "1일 이체한도", fieldType: "text", value: null, isRequired: true }
    ],
    isCollapsed: false
  },
  {
    groupId: "additional_services",
    groupName: "추가 정보 선택",
    stageIds: ["4"],
    fields: [
      { 
        fieldId: "important_transaction_alert", 
        fieldName: "중요거래 통보", 
        fieldType: "select", 
        value: null, 
        options: ["신청", "미신청"],
        isRequired: true 
      },
      { 
        fieldId: "withdrawal_alert", 
        fieldName: "출금내역 통보", 
        fieldType: "select", 
        value: null, 
        options: ["신청", "미신청"],
        isRequired: true 
      },
      { 
        fieldId: "overseas_ip_restriction", 
        fieldName: "해외IP이체 제한", 
        fieldType: "select", 
        value: null, 
        options: ["신청", "미신청"],
        isRequired: true 
      }
    ],
    isCollapsed: false
  },
  {
    groupId: "card_selection",
    groupName: "카드 선택",
    stageIds: ["5"],
    fields: [
      { fieldId: "card_receipt_method", fieldName: "카드 수령 방법", fieldType: "text", value: null, isRequired: true },
      { fieldId: "card_selection", fieldName: "카드 선택", fieldType: "text", value: null, isRequired: true },
      { 
        fieldId: "transit_function", 
        fieldName: "후불 교통 기능", 
        fieldType: "boolean", 
        value: null, 
        isRequired: true 
      }
    ],
    isCollapsed: false
  },
  {
    groupId: "statement_info",
    groupName: "명세서 수령 정보",
    stageIds: ["6"],
    fields: [
      { fieldId: "statement_delivery_method", fieldName: "명세서 수령방법", fieldType: "text", value: null, isRequired: true },
      { fieldId: "statement_delivery_date", fieldName: "명세서 수령일", fieldType: "text", value: "10", isRequired: true }
    ],
    isCollapsed: false
  },
  {
    groupId: "card_alert",
    groupName: "카드 사용 알림",
    stageIds: ["7"],
    fields: [
      { fieldId: "card_usage_alert", fieldName: "카드 사용 알림", fieldType: "text", value: null, isRequired: true }
    ],
    isCollapsed: false
  },
  {
    groupId: "card_password",
    groupName: "카드 비밀번호 설정",
    stageIds: ["8"],
    fields: [
      { 
        fieldId: "card_password_same_as_account", 
        fieldName: "카드 비밀번호", 
        fieldType: "boolean", 
        value: null, 
        isRequired: true 
      }
    ],
    isCollapsed: false
  }
];
```

### 4.2 슬롯 업데이트 로직

```typescript
function updateSlotValue(groupId: string, fieldId: string, value: any): void {
  const group = slotGroups.find(g => g.groupId === groupId);
  if (group) {
    const field = group.fields.find(f => f.fieldId === fieldId);
    if (field) {
      field.value = value;
      
      // 모든 필드가 채워졌는지 확인
      const allFieldsFilled = group.fields.every(f => f.value !== null);
      if (allFieldsFilled) {
        // 1초 후 그룹 접기
        setTimeout(() => {
          group.isCollapsed = true;
        }, 1000);
      }
    }
  }
}

function getActiveSlotGroup(currentStageId: string): SlotGroup | null {
  return slotGroups.find(group => group.stageIds.includes(currentStageId)) || null;
}
```

## 5. Entity Extraction 구현

### 5.1 Stage별 Entity 추출 프롬프트

```python
ENTITY_EXTRACTION_PROMPTS = {
    "1": """
    사용자가 선택한 서비스를 추출하세요:
    - "모두", "전부", "다" → "all"
    - "모바일", "앱" → "mobile_only"
    - "체크카드", "카드" → "card_only"
    - "계좌만", "입출금만" → "account_only"
    """,
    
    "2": """
    개인정보 확인 응답을 추출하세요:
    - "맞아", "네", "확인" → personal_info_confirmed: true
    - "아니", "틀려", "수정" → personal_info_confirmed: false
    - 특정 필드 수정 요청 시 해당 필드명과 새 값 추출
    """,
    
    "3": """
    보안매체 선택과 이체한도 정보를 추출하세요:
    - 보안매체명 추출
    - 이체한도 금액 추출 (숫자만)
    """,
    
    "4": """
    추가 서비스 신청 여부를 추출하세요:
    - "모두", "다", "전부" → 모든 서비스 "신청"
    - "안해", "필요없어" → 모든 서비스 "미신청"
    - 개별 서비스 언급 시 해당 서비스만 추출
    """,
    
    "5": """
    카드 선택 정보를 추출하세요:
    - 카드명 추출
    - "배송" 언급 시 → filter: "delivery"
    - "후불교통" 언급 시 → filter: "transit"
    """,
    
    "8": """
    카드 비밀번호 설정 방법을 추출하세요:
    - "같게", "동일", "네" → card_password_same_as_account: true
    - "다르게", "따로", "아니" → card_password_same_as_account: false
    """
}
```

### 5.2 패턴 매칭 및 유사도 기반 추출

```python
class DepositAccountEntityAgent:
    def __init__(self):
        self.patterns = {
            "services": {
                "all": ["모두", "전부", "다", "모두 가입"],
                "mobile_only": ["모바일만", "앱만", "모바일 앱만"],
                "card_only": ["체크카드만", "카드만"],
                "account_only": ["계좌만", "입출금만", "입출금 계좌만"]
            },
            "confirmation": {
                "yes": ["네", "맞아", "맞습니다", "확인", "좋아"],
                "no": ["아니", "틀려", "아니요", "수정", "변경"]
            },
            "security_medium": {
                "futuretech": ["미래테크", "미래"],
                "comas": ["코마스", "RSA"],
                "security_card": ["보안카드"],
                "otp": ["OTP", "신한OTP"]
            }
        }
    
    async def extract_entities(self, user_input: str, stage_id: str, stage_info: dict) -> dict:
        """스테이지별 엔티티 추출"""
        
        # 1. 패턴 매칭 시도
        pattern_result = self._pattern_matching(user_input, stage_id)
        if pattern_result:
            return pattern_result
        
        # 2. 유사도 기반 매칭
        similarity_result = await self._similarity_matching(user_input, stage_id, stage_info)
        if similarity_result and similarity_result.get("confidence", 0) > 0.7:
            return similarity_result
        
        # 3. LLM 기반 추출
        return await self._llm_extraction(user_input, stage_id, stage_info)
```

## 6. 응답 타입별 UI 구현

### 6.1 Bullet Type with Default

```vue
<template>
  <div class="bullet-response" v-if="responseType === 'bullet'">
    <div class="prompt">{{ prompt }}</div>
    <div class="choices">
      <div 
        v-for="choice in choices" 
        :key="choice.value"
        class="choice-item"
        :class="{ 'default': choice.default, 'selected': selectedValue === choice.value }"
        @click="selectChoice(choice.value)"
      >
        <span class="choice-text">{{ choice.display }}</span>
        <span v-if="choice.default" class="default-badge">기본값</span>
      </div>
    </div>
    <div v-if="additionalQuestions" class="additional-questions">
      <p>+ 다른 질문도 할 수 있어요.</p>
      <ul>
        <li v-for="question in additionalQuestions" :key="question">
          > {{ question }}
        </li>
      </ul>
    </div>
  </div>
</template>
```

### 6.2 Grouped Bullet Type

```vue
<template>
  <div class="grouped-bullet-response" v-if="responseType === 'grouped_bullet'">
    <div class="prompt">{{ prompt }}</div>
    <div v-for="group in choiceGroups" :key="group.groupName" class="choice-group">
      <h4>{{ group.groupName }}</h4>
      <div class="choices">
        <div 
          v-for="choice in group.choices" 
          :key="choice.value"
          class="choice-item"
          :class="{ 'default': choice.default, 'selected': selectedValue === choice.value }"
          @click="selectChoice(choice.value)"
        >
          <span class="choice-text">{{ choice.display }}</span>
          <span v-if="choice.default" class="default-badge">기본값</span>
        </div>
      </div>
    </div>
  </div>
</template>
```

### 6.3 Card List Type

```vue
<template>
  <div class="card-list-response" v-if="responseType === 'card_list'">
    <div class="prompt">{{ prompt }}</div>
    <div class="card-container">
      <div class="card-scroll-wrapper" ref="scrollWrapper">
        <div class="card-list">
          <div 
            v-for="(card, index) in cards" 
            :key="card.value"
            class="card-item"
            :class="{ 'default': card.default, 'selected': selectedValue === card.value }"
            @click="selectCard(card.value)"
          >
            <div class="card-number">{{ index + 1 }}</div>
            <div class="card-content">
              <pre>{{ card.display }}</pre>
            </div>
            <span v-if="card.default" class="default-badge">기본값</span>
          </div>
        </div>
      </div>
      <div class="scroll-indicator">
        <span>옆으로 밀어 더보기</span>
      </div>
    </div>
    <div v-if="additionalQuestions" class="additional-questions">
      <p>+ 다른 질문도 할 수 있어요</p>
      <ul>
        <li v-for="question in additionalQuestions" :key="question">
          > {{ question }}
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.card-scroll-wrapper {
  overflow-x: auto;
  scroll-behavior: smooth;
  -webkit-overflow-scrolling: touch;
}

.card-list {
  display: flex;
  gap: 16px;
  padding: 16px 0;
}

.card-item {
  min-width: 150px;
  padding: 16px;
  border: 2px solid #e0e0e0;
  border-radius: 8px;
  cursor: pointer;
  position: relative;
}

.card-item.default {
  border-color: #1976d2;
  background-color: #e3f2fd;
}

.card-item.selected {
  border-color: #4caf50;
  background-color: #e8f5e9;
}
</style>
```

## 7. 음성 인터랙션 처리

### 7.1 STT 결과 처리

```python
async def process_voice_input(audio_b64: str, stage_id: str, stage_info: dict) -> dict:
    """음성 입력 처리"""
    
    # 1. STT 변환
    text = await google_stt_service.transcribe(audio_b64)
    
    # 2. 스테이지별 특수 처리
    if stage_info.get("response_type") in ["bullet", "grouped_bullet"]:
        # 선택지 매칭 시도
        matched_choice = match_choice_by_voice(text, stage_info.get("choices", []))
        if matched_choice:
            return {
                "input_text": text,
                "matched_value": matched_choice["value"],
                "input_mode": "voice"
            }
    
    # 3. 일반 텍스트로 처리
    return {
        "input_text": text,
        "input_mode": "voice"
    }
```

### 7.2 TTS 응답 생성

```python
async def generate_tts_response(response_text: str, stage_info: dict) -> str:
    """TTS 응답 생성"""
    
    # 특수 문자 및 포맷팅 처리
    tts_text = response_text
    
    # 줄바꿈을 일시정지로 변환
    tts_text = tts_text.replace("\\n", ". ")
    
    # 선택지는 읽지 않음 (UI로만 표시)
    if stage_info.get("response_type") in ["bullet", "grouped_bullet", "card_list"]:
        # prompt만 읽기
        tts_text = stage_info.get("prompt", "")
    
    return await google_tts_service.synthesize(tts_text)
```

## 8. 상태 관리 및 세션 처리

### 8.1 AgentState 확장

```python
class DepositAccountAgentState(AgentState):
    """입출금 동시신규용 상태 확장"""
    
    # 서비스 선택 정보
    services_selected: Optional[str] = None  # all, mobile_only, card_only, account_only
    
    # 개인정보 확인
    personal_info_confirmed: Optional[bool] = None
    personal_info_modifications: Optional[Dict[str, str]] = None
    
    # 전자금융 정보
    security_medium_selected: Optional[str] = None
    transfer_limit_once: Optional[str] = None
    transfer_limit_daily: Optional[str] = None
    important_transaction_alert: Optional[str] = None
    withdrawal_alert: Optional[str] = None
    overseas_ip_restriction: Optional[str] = None
    
    # 체크카드 정보
    card_selected: Optional[str] = None
    card_receipt_method: Optional[str] = None
    transit_function: Optional[bool] = None
    statement_delivery_method: Optional[str] = None
    statement_delivery_date: Optional[str] = None
    card_usage_alert: Optional[str] = None
    card_password_same_as_account: Optional[bool] = None
```

### 8.2 세션 데이터 저장

```python
async def save_session_data(session_id: str, state: DepositAccountAgentState):
    """세션 데이터 저장"""
    
    session_data = {
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
        "scenario_id": "deposit_account_concurrent",
        "current_stage_id": state.current_scenario_stage_id,
        "collected_info": state.collected_product_info,
        "services_selected": state.services_selected,
        "completion_status": state.current_scenario_stage_id == "9"
    }
    
    # Redis 또는 DB에 저장
    await session_store.save(session_id, session_data, ttl=3600)
```

## 9. 에러 처리 및 예외 상황

### 9.1 타임아웃 처리

```python
STAGE_TIMEOUTS = {
    "1": 30,  # 30초
    "2": 60,  # 60초 (정보 확인에 더 많은 시간 필요)
    "3": 45,  # 45초
    "4": 30,  # 30초
    "5": 45,  # 45초 (카드 선택)
    "6": 30,  # 30초
    "7": 30,  # 30초
    "8": 30,  # 30초
    "9": 10   # 10초
}

async def handle_stage_timeout(session_id: str, stage_id: str):
    """스테이지 타임아웃 처리"""
    
    if stage_id in ["1", "3", "5", "6", "7"]:
        # 기본값으로 자동 진행
        default_value = get_stage_default_value(stage_id)
        return {
            "action": "auto_proceed",
            "value": default_value,
            "message": "응답이 없어 기본값으로 진행합니다."
        }
    else:
        # 재질문
        return {
            "action": "retry",
            "message": "죄송합니다. 다시 한 번 말씀해 주시겠어요?"
        }
```

### 9.2 잘못된 입력 처리

```python
async def handle_invalid_input(user_input: str, stage_id: str, stage_info: dict) -> dict:
    """잘못된 입력 처리"""
    
    retry_count = get_retry_count(session_id, stage_id)
    
    if retry_count < 2:
        # 재시도 요청
        return {
            "action": "retry",
            "message": generate_retry_message(stage_id, stage_info),
            "suggestions": get_stage_suggestions(stage_id)
        }
    else:
        # 3회 이상 실패 시 상담원 연결
        return {
            "action": "transfer_to_agent",
            "message": "원활한 상담을 위해 상담원을 연결해 드리겠습니다."
        }
```

## 10. 보안 및 개인정보 처리

### 10.1 개인정보 마스킹

```python
def mask_personal_info(info_type: str, value: str) -> str:
    """개인정보 마스킹"""
    
    if info_type == "ssn":
        # 주민등록번호: 880122-*******
        return f"{value[:6]}-*******"
    
    elif info_type == "phone_number":
        # 전화번호: 010-1234-OOOO
        parts = value.split("-")
        if len(parts) == 3:
            return f"{parts[0]}-{parts[1]}-{'O' * len(parts[2])}"
    
    elif info_type == "email":
        # 이메일: shi****@naver.com
        local, domain = value.split("@")
        masked_local = local[:3] + "*" * (len(local) - 3)
        return f"{masked_local}@{domain}"
    
    return value
```

### 10.2 데이터 암호화

```python
from cryptography.fernet import Fernet

class DataEncryption:
    def __init__(self, key: bytes):
        self.cipher = Fernet(key)
    
    def encrypt_sensitive_data(self, data: dict) -> dict:
        """민감 데이터 암호화"""
        
        sensitive_fields = ["ssn", "phone_number", "email", "address", "work_address"]
        encrypted_data = data.copy()
        
        for field in sensitive_fields:
            if field in data and data[field]:
                encrypted_data[field] = self.cipher.encrypt(
                    data[field].encode()
                ).decode()
        
        return encrypted_data
```

## 11. 로깅 및 모니터링

### 11.1 스테이지 전환 로깅

```python
import logging

logger = logging.getLogger("deposit_account_concurrent")

def log_stage_transition(session_id: str, from_stage: str, to_stage: str, 
                        trigger: str, collected_info: dict):
    """스테이지 전환 로깅"""
    
    logger.info(f"[STAGE_TRANSITION] {session_id}", extra={
        "session_id": session_id,
        "from_stage": from_stage,
        "to_stage": to_stage,
        "trigger": trigger,
        "timestamp": datetime.now().isoformat(),
        "collected_fields": list(collected_info.keys())
    })
```

### 11.2 성능 메트릭

```python
from prometheus_client import Counter, Histogram

# 메트릭 정의
stage_completion_counter = Counter(
    'deposit_account_stage_completions', 
    'Number of stage completions',
    ['stage_id', 'services_selected']
)

stage_duration_histogram = Histogram(
    'deposit_account_stage_duration_seconds',
    'Time spent in each stage',
    ['stage_id']
)

scenario_completion_rate = Counter(
    'deposit_account_scenario_completions',
    'Number of scenario completions',
    ['completion_type']  # success, partial, abandoned
)
```

## 12. 테스트 시나리오

### 12.1 정상 플로우 테스트

```python
async def test_normal_flow():
    """정상 플로우 테스트"""
    
    test_cases = [
        {
            "name": "전체 서비스 가입",
            "inputs": [
                ("1", "모두 가입할게요"),
                ("2", "네 맞습니다"),
                ("3", "미래테크로 할게요"),
                ("4", "네 모두 신청할게요"),
                ("5", "S-Line 체크카드로 할게요"),
                ("6", "휴대폰으로 받을게요"),
                ("7", "5만원 이상일 때만요"),
                ("8", "네 같게 설정할게요")
            ],
            "expected_stages": ["1", "2", "3", "4", "5", "6", "7", "8", "9"]
        },
        {
            "name": "모바일 앱만 가입",
            "inputs": [
                ("1", "모바일 앱만 가입할게요"),
                ("2", "확인했습니다"),
                ("3", "코마스로 할게요"),
                ("4", "중요거래 알림만 신청할게요")
            ],
            "expected_stages": ["1", "2", "3", "4", "9"]
        }
    ]
    
    for test_case in test_cases:
        result = await run_test_scenario(test_case)
        assert result["success"], f"Test failed: {test_case['name']}"
```

### 12.2 예외 상황 테스트

```python
async def test_exception_cases():
    """예외 상황 테스트"""
    
    test_cases = [
        {
            "name": "개인정보 수정 요청",
            "inputs": [
                ("1", "모두 가입"),
                ("2", "전화번호가 틀렸어요")
            ],
            "expected_action": "info_modification"
        },
        {
            "name": "이체한도 변경 요청",
            "inputs": [
                ("1", "모두"),
                ("2", "맞아요"),
                ("3", "이체한도를 3천만원으로 변경하고 싶어요")
            ],
            "expected_fields": {
                "transfer_limit_once": "30000000"
            }
        }
    ]
    
    for test_case in test_cases:
        result = await run_exception_test(test_case)
        assert result["handled_correctly"], f"Exception test failed: {test_case['name']}"
```

## 13. 배포 및 환경 설정

### 13.1 환경 변수

```bash
# 시나리오 설정
DEPOSIT_ACCOUNT_SCENARIO_PATH=/app/data/scenarios/deposit_account_concurrent.json
DEPOSIT_ACCOUNT_TIMEOUT_MULTIPLIER=1.0  # 타임아웃 배수 (테스트 시 늘릴 수 있음)

# 기능 플래그
ENABLE_AUTO_DEFAULT_SELECTION=true
ENABLE_CARD_FILTER_QUESTIONS=true
ENABLE_PERSONAL_INFO_MODIFICATION=true

# 로깅
DEPOSIT_ACCOUNT_LOG_LEVEL=INFO
ENABLE_STAGE_TRANSITION_LOGGING=true
```

### 13.2 스케일링 고려사항

```yaml
# Kubernetes 설정 예시
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: deposit-account-service
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: voice-agent-backend
  minReplicas: 3
  maxReplicas: 50
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
      - type: Percent
        value: 100
        periodSeconds: 60
```

## 14. 유지보수 가이드

### 14.1 시나리오 수정 절차

1. **시나리오 JSON 수정**
   - `/app/data/scenarios/deposit_account_concurrent.json` 파일 수정
   - 스테이지 추가/삭제/수정

2. **엔티티 추출 로직 업데이트**
   - `DepositAccountEntityAgent` 클래스의 패턴 및 프롬프트 수정

3. **UI 컴포넌트 수정**
   - 새로운 response_type 추가 시 Vue 컴포넌트 개발

4. **테스트 케이스 업데이트**
   - 변경된 플로우에 맞춰 테스트 시나리오 수정

5. **문서 업데이트**
   - PRD, TRD 문서 최신화

### 14.2 모니터링 체크리스트

- [ ] 각 스테이지별 평균 소요 시간
- [ ] 스테이지별 이탈률
- [ ] 서비스 선택 분포 (all, mobile_only, card_only, account_only)
- [ ] 개인정보 수정 빈도
- [ ] 음성 인식 정확도
- [ ] 시스템 에러율
- [ ] 상담원 전환율

## 15. 참고 문서

- [PRD_deposit_account_concurrent.md](./PRD_deposit_account_concurrent.md) - 제품 요구사항 정의
- [시나리오 JSON 스키마](../backend/app/data/scenarios/README.md)
- [LangGraph 워크플로우 가이드](../backend/app/graph/README.md)
- [Vue 컴포넌트 개발 가이드](../frontend/src/components/README.md)