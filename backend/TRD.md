# 입출금통장 슬롯필링 개선 TRD
## Technical Requirements Document

### 1. 기술 아키텍처 개요
현재 LangGraph 기반의 Orchestration-Worker 패턴을 활용하여 단계별 확인 절차가 포함된 슬롯필링 시스템 구현

### 2. 구현 시 발견된 주요 이슈 및 해결 방안

#### 2.1 재귀 루프 문제
**문제**: LangGraph에서 확인 단계 추가 시 무한 재귀 발생 (RecursionError: Recursion limit of 25 reached)

**원인**:
- 확인 단계와 수집 단계 간의 상태 전환 로직이 명확하지 않음
- 동일한 노드가 반복적으로 호출되는 구조

**해결 방안**:
```python
# 명확한 상태 분리
STAGE_TYPES = {
    "collection": ["collect_basic_info", "collect_ib_info"],
    "confirmation": ["confirm_basic_info", "confirm_ib_info"],
    "correction": ["correct_basic_info", "correct_ib_info"]
}

# 각 타입별 별도 처리 로직
async def handle_stage_by_type(state, stage_info):
    stage_type = get_stage_type(stage_info["id"])
    if stage_type == "confirmation":
        return await handle_confirmation_stage(state, stage_info)
    elif stage_type == "correction":
        return await handle_correction_stage(state, stage_info)
    else:
        return await handle_collection_stage(state, stage_info)
```

#### 2.2 Intent 인식 문제
**문제**: 확인/수정 의도가 제대로 인식되지 않음

**해결 방안**:
```python
# 명확한 Intent 매핑
CONFIRMATION_INTENTS = {
    "positive": ["네", "맞아요", "예", "맞습니다", "확인"],
    "negative": ["아니요", "틀려요", "수정", "변경"],
    "specific": ["번호가", "이름이", "주소가"]  # 특정 필드 언급
}

# Intent 우선순위 처리
def classify_confirmation_intent(user_input: str):
    # 1. 특정 필드 수정 요청 확인
    for field_mention in CONFIRMATION_INTENTS["specific"]:
        if field_mention in user_input:
            return "specific_correction"
    
    # 2. 긍정/부정 확인
    for positive in CONFIRMATION_INTENTS["positive"]:
        if positive in user_input:
            return "confirmed"
    
    return "needs_correction"
```

### 3. 개선된 기술 요구사항

#### 3.1 시나리오 구조 개선
```json
{
  "stages": {
    "greeting": {
      "id": "greeting",
      "stage_type": "collection",  // 명시적 타입 선언
      "prompt": "안녕하세요. 입출금통장 개설을 도와드리겠습니다.",
      "apply_defaults": true,  // 기본값 자동 적용
      "default_next_stage_id": "confirm_basic_info"
    },
    "confirm_basic_info": {
      "id": "confirm_basic_info",
      "stage_type": "confirmation",  // 확인 단계임을 명시
      "prompt": "등록된 정보를 확인하겠습니다:\n- 성함: %{customer_name}%\n- 연락처: %{customer_phone}%\n\n이 정보가 맞으신가요?",
      "fields_to_confirm": ["customer_name", "customer_phone"],
      "confirmation_group": "basic_info",  // 그룹 단위 확인
      "transitions": [
        {
          "next_stage_id": "ask_lifelong_account",
          "condition": "confirmed",
          "intent_keywords": ["네", "맞아요", "예", "맞습니다"]
        },
        {
          "next_stage_id": "correct_basic_info",
          "condition": "needs_correction",
          "intent_keywords": ["아니요", "틀려요", "수정"]
        }
      ]
    },
    "correct_basic_info": {
      "id": "correct_basic_info",
      "stage_type": "correction",  // 수정 단계
      "prompt": "어떤 정보를 수정하시겠어요? 성함과 연락처를 말씀해주세요.",
      "correction_for_group": "basic_info",
      "default_next_stage_id": "confirm_basic_info"  // 수정 후 다시 확인
    }
  }
}
```

#### 3.2 State 관리 확장
```python
class AgentState(BaseModel):
    # 기존 필드들...
    
    # 확인 관리
    pending_confirmation_groups: List[str] = Field(default_factory=list)
    confirmed_groups: Set[str] = Field(default_factory=set)
    correction_context: Dict[str, Any] = Field(default_factory=dict)
    
    # 상태 추적
    current_stage_type: Optional[str] = None  # collection, confirmation, correction
    previous_stage_id: Optional[str] = None  # 이전 단계 추적
    stage_visit_count: Dict[str, int] = Field(default_factory=dict)  # 무한 루프 방지
```

#### 3.3 확인 로직 구현 (무한 루프 방지)
```python
# scenario_logic.py 개선
MAX_STAGE_VISITS = 3  # 동일 단계 최대 방문 횟수

async def process_stage_with_loop_prevention(state: AgentState, stage_info: Dict):
    """무한 루프 방지를 위한 단계 처리"""
    stage_id = stage_info["id"]
    
    # 방문 횟수 체크
    visit_count = state.stage_visit_count.get(stage_id, 0)
    if visit_count >= MAX_STAGE_VISITS:
        # 무한 루프 감지 - 다음 단계로 강제 이동
        return stage_info.get("default_next_stage_id", "END_SCENARIO")
    
    # 방문 횟수 증가
    state.stage_visit_count[stage_id] = visit_count + 1
    
    # 단계 타입별 처리
    stage_type = stage_info.get("stage_type", "collection")
    if stage_type == "confirmation":
        return await handle_confirmation_stage(state, stage_info)
    elif stage_type == "correction":
        return await handle_correction_stage(state, stage_info)
    else:
        return await handle_collection_stage(state, stage_info)

async def handle_confirmation_stage(state: AgentState, stage_info: Dict):
    """확인 단계 처리 (개선된 버전)"""
    confirmation_group = stage_info.get("confirmation_group")
    fields_to_confirm = stage_info.get("fields_to_confirm", [])
    
    # 이미 확인된 그룹인지 체크
    if confirmation_group in state.confirmed_groups:
        # 이미 확인된 경우 다음 단계로
        return get_next_stage_after_confirmation(state, stage_info)
    
    # 사용자 응답 분석 (명확한 intent 매칭)
    user_intent = classify_confirmation_intent(state.stt_result)
    
    if user_intent == "confirmed":
        state.confirmed_groups.add(confirmation_group)
        state.stage_visit_count[stage_info["id"]] = 0  # 리셋
        return get_transition_by_condition(stage_info, "confirmed")
    
    elif user_intent == "needs_correction":
        state.correction_context = {
            "group": confirmation_group,
            "fields": fields_to_confirm
        }
        return get_transition_by_condition(stage_info, "needs_correction")
    
    elif user_intent == "specific_correction":
        # 특정 필드 수정 요청 처리
        field, value = extract_correction_request(state.stt_result)
        if field and value:
            state.collected_product_info[field] = value
            # 동일 확인 단계로 돌아가서 재확인
            return stage_info["id"]
    
    # 명확하지 않은 경우 재질문
    return stage_info["id"]
```

#### 3.4 정보 그룹핑 전략 (개선된 버전)
```python
# 개선된 그룹 구조 - 우선순위와 의존성 포함
INFO_GROUPS = {
    "basic_info": {
        "fields": ["customer_name", "customer_phone"],
        "priority": 1,
        "max_items": 2,
        "confirmation_required": True
    },
    "account_settings": {
        "fields": ["use_lifelong_account"],
        "priority": 2,
        "max_items": 1,
        "confirmation_required": False  # 단일 항목은 확인 불필요
    },
    "internet_banking_basic": {
        "fields": ["security_medium", "transfer_limit_per_time", "transfer_limit_per_day"],
        "priority": 3,
        "max_items": 2,  # 한 번에 2개씩만
        "depends_on": {"use_internet_banking": True},
        "confirmation_required": True
    },
    "internet_banking_alerts": {
        "fields": ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"],
        "priority": 4,
        "max_items": 3,  # 알림은 한 번에 처리 가능
        "depends_on": {"use_internet_banking": True},
        "confirmation_required": True
    }
}

def get_next_info_group(state: AgentState) -> Tuple[str, List[str]]:
    """우선순위와 의존성을 고려한 다음 그룹 결정"""
    collected_info = state.collected_product_info
    confirmed_groups = state.confirmed_groups
    
    # 우선순위 순으로 정렬
    sorted_groups = sorted(
        INFO_GROUPS.items(), 
        key=lambda x: x[1]["priority"]
    )
    
    for group_name, group_info in sorted_groups:
        # 의존성 체크
        if "depends_on" in group_info:
            dependency_met = all(
                collected_info.get(field) == value
                for field, value in group_info["depends_on"].items()
            )
            if not dependency_met:
                continue
        
        # 아직 수집되지 않은 필드 찾기
        missing_fields = [
            field for field in group_info["fields"]
            if field not in collected_info
        ]
        
        if missing_fields:
            # max_items 제한 적용
            fields_to_collect = missing_fields[:group_info["max_items"]]
            return group_name, fields_to_collect
        
        # 모든 필드가 수집되었지만 확인이 필요한 경우
        elif group_info["confirmation_required"] and group_name not in confirmed_groups:
            return f"confirm_{group_name}", group_info["fields"]
    
    return None, []
```

#### 3.5 Entity Agent 개선
```python
class EntityRecognitionAgent:
    """개선된 Entity Agent - 확인/수정 의도 파악 추가"""
    
    def __init__(self):
        self.extraction_prompt = self._get_extraction_prompt()
        self.validation_prompt = self._get_validation_prompt()
        self.confirmation_prompt = self._get_confirmation_prompt()  # 새로 추가
    
    async def extract_confirmation_intent(self, user_input: str, context: Dict):
        """확인/수정 의도 파악 (컨텍스트 포함)"""
        prompt = f"""
        현재 상황:
        - AI가 확인 요청: "{context.get('confirmation_prompt', '')}"
        - 사용자 응답: "{user_input}"
        - 확인 대상 필드: {context.get('fields_to_confirm', [])}
        
        사용자의 의도를 정확히 파악하세요:
        
        1. "confirmed": 정보가 맞다고 확인
           - 예: "네", "맞아요", "확인했습니다"
           
        2. "needs_correction": 전체적인 수정 필요
           - 예: "아니요", "틀려요", "다시 알려드릴게요"
           
        3. "specific_correction": 특정 필드만 수정
           - 예: "번호가 틀렸어요", "이름은 김철수가 아니라 김민수예요"
        
        JSON 형식으로 응답:
        {{
            "intent": "confirmed|needs_correction|specific_correction",
            "correction_field": "수정할 필드 키 (specific_correction인 경우)",
            "correction_value": "새로운 값 (specific_correction인 경우)",
            "confidence": 0.0-1.0
        }}
        """
        
        response = await json_llm.ainvoke([HumanMessage(content=prompt)])
        return json.loads(response.content)
    
    def extract_correction_from_text(self, user_input: str, fields_to_check: List[str]):
        """텍스트에서 수정 요청 추출 (패턴 매칭)"""
        corrections = {}
        
        # 필드별 수정 패턴
        field_patterns = {
            "customer_name": [
                r"(?:이름|성함)(?:은|이)?\s*([가-힣]{2,4})(?:입니다|이에요|예요)?",
                r"([가-힣]{2,4})(?:으로|로)\s*(?:수정|변경)"
            ],
            "customer_phone": [
                r"(?:번호|연락처)(?:는)?\s*(010[-\s]?\d{4}[-\s]?\d{4})",
                r"(010[-\s]?\d{4}[-\s]?\d{4})(?:으로|로)\s*(?:수정|변경)"
            ]
        }
        
        for field in fields_to_check:
            if field in field_patterns:
                for pattern in field_patterns[field]:
                    match = re.search(pattern, user_input)
                    if match:
                        corrections[field] = match.group(1).strip()
                        break
        
        return corrections
```

### 4. 구현 단계 (개선된 접근법)

#### Phase 1: 기반 구조 정비
- State에 루프 방지 메커니즘 추가
- 단계 타입(stage_type) 명시적 분리
- Intent 매칭 로직 강화

#### Phase 2: 시나리오 점진적 개선
- 기존 시나리오 구조 유지하면서 점진적 개선
- 먼저 기본 정보 확인 단계만 추가
- 작동 확인 후 다른 그룹으로 확대

#### Phase 3: Entity Agent 확장
- 확인 의도 파악 메서드 추가
- 패턴 기반 수정 요청 추출
- 컨텍스트 aware 처리

#### Phase 4: 테스트 주도 개발
- 각 기능별 단위 테스트 작성
- 통합 테스트로 전체 흐름 검증
- 무한 루프 방지 테스트 필수

### 5. 기술적 위험 관리

#### 5.1 무한 루프 방지
- 각 단계별 최대 방문 횟수 제한
- 강제 진행 메커니즘
- 상태 추적 및 모니터링

#### 5.2 기존 시스템 호환성
- 기존 시나리오 구조와 하위 호환
- 선택적 기능 활성화 (opt-in)
- 점진적 마이그레이션 전략

#### 5.3 성능 고려사항
- 확인 단계 추가로 인한 지연 최소화
- 병렬 처리 가능한 부분 식별
- 캐싱 전략 수립

### 6. 예상 구현 일정

| 단계 | 작업 내용 | 예상 시간 |
|------|-----------|-----------|
| 1 | State 및 기반 구조 개선 | 2시간 |
| 2 | 기본 정보 확인 단계 구현 | 3시간 |
| 3 | Entity Agent 확장 | 2시간 |
| 4 | 테스트 작성 및 검증 | 3시간 |
| 5 | 전체 그룹으로 확대 | 4시간 |

### 7. 성공 지표

- 무한 루프 발생 0건
- 확인 의도 정확도 95% 이상
- 평균 대화 턴 수 15턴 이하
- 사용자 수정 요청 처리율 100%

### 8. 추가 구현 요구사항 (테스트 기반 발견)

#### 8.1 Entity Agent 통합 강화
**문제**: 현재 다중 정보 수집 단계에서 Entity Agent가 호출되지 않음

**해결 방안**:
```python
# scenario_logic.py 수정
async def process_multiple_info_collection(state, ...):
    if current_stage_info.get("collect_multiple_info") and user_input:
        # Entity Agent 필수 호출
        from ....agents.entity_agent import entity_agent
        
        result = await entity_agent.process_slot_filling(
            user_input, 
            required_fields, 
            collected_info
        )
        
        # 추출된 정보로 상태 업데이트
        collected_info.update(result["valid_entities"])
```

#### 8.2 수정 요청 처리 플로우
**문제**: greeting 단계에서 "아니요" 응답 시 바로 종료됨

**해결 방안 1 - 시나리오 JSON 수정**:
```json
{
  "greeting": {
    "transitions": [
      {
        "next_stage_id": "ask_lifelong_account",
        "condition": "confirmed"
      },
      {
        "next_stage_id": "correct_basic_info",  // info_correction_end 대신
        "condition": "needs_correction"
      }
    ]
  },
  "correct_basic_info": {
    "id": "correct_basic_info",
    "prompt": "어떤 정보를 수정하시겠어요? 성함과 연락처를 다시 말씀해주세요.",
    "collect_multiple_info": true,
    "expected_info_keys": ["customer_name", "customer_phone"],
    "default_next_stage_id": "greeting"  // 수정 후 다시 확인
  }
}
```

**해결 방안 2 - 로직 레벨 처리**:
```python
# greeting 단계에서 Entity 추출 시도
if current_stage_id == "greeting" and "아니" in user_input:
    # Entity Agent로 새로운 정보 추출 시도
    extraction_result = await entity_agent.extract_entities(
        user_input, 
        [{"key": "customer_name"}, {"key": "customer_phone"}]
    )
    
    if extraction_result["extracted_entities"]:
        # 정보 업데이트 후 동일 단계 유지
        collected_info.update(extraction_result["extracted_entities"])
        return "greeting"  # 재확인을 위해
```

#### 8.3 스트리밍 응답 개선
**문제**: state_update 이벤트가 스트리밍되지 않음

**해결 방안**:
```python
# agent.py의 run_agent_streaming 수정
async def run_agent_streaming(...):
    # 기존 코드...
    
    # 상태 변경 시 즉시 스트리밍
    if prev_state != current_state:
        yield {
            "type": "state_update",
            "data": {
                "current_scenario_stage_id": current_state.current_scenario_stage_id,
                "collected_product_info": current_state.collected_product_info,
                "current_product_type": current_state.current_product_type
            }
        }
```

#### 8.4 시나리오 구조 개선 권장사항

1. **모든 확인 단계에 수정 경로 추가**
   - 각 확인 단계에서 needs_correction 전환 정의
   - 수정 단계는 원래 확인 단계로 돌아가도록 설계

2. **Entity Agent 호출 시점 명시**
   - collect_multiple_info: true인 모든 단계
   - 사용자 입력이 있는 모든 단계
   - 수정 요청이 포함된 입력

3. **기본값 처리 시점**
   - greeting 단계 진입 시 즉시 적용
   - 사용자가 수정하지 않는 한 유지