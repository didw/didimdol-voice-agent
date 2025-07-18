# 입출금통장 슬롯필링 개선 TRD
## Technical Requirements Document

### 1. 기술 아키텍처 개요
현재 LangGraph 기반의 Orchestration-Worker 패턴을 활용하여 단계별 확인 절차가 포함된 슬롯필링 시스템 구현

### 2. 주요 기술 요구사항

#### 2.1 시나리오 구조 개선
```json
{
  "stages": {
    "greeting": {...},
    "confirm_basic_info": {
      "id": "confirm_basic_info",
      "prompt": "수집된 정보를 확인하겠습니다:\n- 성함: %{customer_name}%\n- 연락처: %{customer_phone}%\n\n이 정보가 맞으신가요?",
      "is_confirmation": true,
      "fields_to_confirm": ["customer_name", "customer_phone"],
      "transitions": [
        {
          "next_stage_id": "ask_lifelong_account",
          "condition": "confirmed"
        },
        {
          "next_stage_id": "collect_basic_info_correction",
          "condition": "needs_correction"
        }
      ]
    }
  }
}
```

#### 2.2 State 관리 확장
```python
class AgentState(BaseModel):
    # 기존 필드들...
    pending_confirmation_fields: List[str] = Field(default_factory=list)
    confirmation_status: Dict[str, bool] = Field(default_factory=dict)
    correction_requests: Dict[str, str] = Field(default_factory=dict)
```

#### 2.3 확인 로직 구현
```python
# scenario_logic.py 개선
async def handle_confirmation_stage(state: AgentState, stage_info: Dict):
    """확인 단계 처리"""
    fields_to_confirm = stage_info.get("fields_to_confirm", [])
    
    # 수집된 정보 포맷팅
    confirmation_prompt = format_confirmation_prompt(
        stage_info["prompt"], 
        state.collected_product_info,
        fields_to_confirm
    )
    
    # 사용자 응답 분석
    if user_confirmed:
        state.confirmation_status.update({
            field: True for field in fields_to_confirm
        })
        return next_stage
    else:
        return correction_stage
```

#### 2.4 정보 그룹핑 전략
```python
INFO_GROUPS = {
    "internet_banking_basic": ["security_medium", "transfer_limit_per_time", "transfer_limit_per_day"],
    "internet_banking_alerts": ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"],
    "check_card_basic": ["card_receive_method", "card_type"],
    "check_card_options": ["postpaid_transport", "payment_date", "statement_method"]
}

def get_next_info_group(collected_info: Dict, required_groups: List[str]):
    """다음에 수집할 정보 그룹 결정"""
    for group_name, fields in INFO_GROUPS.items():
        if not all(field in collected_info for field in fields):
            return group_name, fields
    return None, []
```

#### 2.5 Entity Agent 개선
- 여러 필드를 동시에 추출할 수 있도록 개선
- 확인/수정 의도 파악 기능 추가
```python
async def extract_confirmation_intent(self, user_input: str):
    """사용자의 확인/수정 의도 파악"""
    prompt = """
    사용자 응답: {user_input}
    
    사용자가 정보를 확인했는지, 수정을 원하는지 판단하세요.
    - confirmed: 맞다, 네, 확인 등
    - needs_correction: 아니요, 틀려요, 수정 등
    - specific_correction: 특정 항목 수정 요청
    
    JSON 형식으로 응답:
    {
        "intent": "confirmed|needs_correction|specific_correction",
        "correction_field": "수정할 필드명 (있는 경우)",
        "correction_value": "새로운 값 (있는 경우)"
    }
    """
```

### 3. 구현 단계

#### Phase 1: 시나리오 JSON 구조 개선
- confirmation stage 타입 추가
- fields_to_confirm 속성 추가
- 그룹별 정보 수집 stage 정의

#### Phase 2: State 및 로직 개선
- AgentState에 확인 관련 필드 추가
- scenario_logic.py에 확인 단계 처리 로직 구현
- 정보 그룹핑 및 단계별 수집 로직 구현

#### Phase 3: Entity Agent 확장
- 확인/수정 의도 파악 기능 추가
- 복수 필드 동시 추출 개선

#### Phase 4: 테스트 및 최적화
- 각 단계별 확인 프로세스 테스트
- 대화 흐름 자연스러움 검증
- 성능 최적화

### 4. 기술적 고려사항
- 기존 시나리오와의 호환성 유지
- 확인 단계 추가로 인한 대화 턴 수 증가 최소화
- 사용자가 한 번에 여러 정보를 제공한 경우의 처리
- 기본값이 모두 설정된 경우의 빠른 처리

### 5. 예상 코드 변경사항
- `scenario_logic.py`: 약 150줄 추가/수정
- `entity_agent.py`: 약 50줄 추가
- `deposit_account_scenario.json`: 구조 재설계
- 테스트 코드: 새로운 테스트 케이스 추가