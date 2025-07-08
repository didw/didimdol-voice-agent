# 디딤돌 음성 에이전트 - 업무 프로세스 개선 계획

## 🎯 개선 목표

현재 **0% 업무 완료율**을 **65% 이상**으로 향상시켜 실제 업무 처리가 가능한 상담원 역할 수행

---

## 🔍 현재 문제점 분석

### 1. 라우터 프롬프트의 구조적 한계

#### 문제점
```yaml
# 현재 initial_task_selection_prompt
- set_product_type(product_id: str)  # 너무 일반적
- available_product_types: [didimdol, jeonse, deposit_account]  # 제한적
```

#### 결과
- `set_product_type_didimdol` 대신 `set_product_type` 생성
- 구체적인 제품 식별 실패
- 시나리오 자동 트리거 불가

### 2. 액션 매핑 로직 부재

현재 **`main_agent_router_node`**에서 생성되는 액션이 **시나리오 실행**으로 연결되지 않음

#### 현재 흐름
```
사용자: "디딤돌 대출 신청하고 싶어요"
↓
라우터: set_product_type
↓ 
시나리오 트리거 없음 ❌
```

#### 기대 흐름
```
사용자: "디딤돌 대출 신청하고 싶어요"
↓
라우터: set_product_type_didimdol
↓
시나리오 자동 실행 ✅
```

---

## 💡 개선 방안 (현재 구조 내)

### Phase 1: 라우터 프롬프트 개선

#### 1.1 제품별 의도 인식 강화

**개선된 initial_task_selection_prompt**:

```yaml
initial_task_selection_prompt: |
  You are the master orchestrator of a sophisticated AI banking assistant.
  Your task is to analyze the user's input and determine their SPECIFIC business intent.

  **Step 1: Identify Product Intent**
  Look for specific product mentions:
  
  - **"디딤돌 대출"** keywords → use `set_product_type_didimdol`
  - **"전세자금 대출", "전세 대출"** keywords → use `set_product_type_jeonse`  
  - **"계좌", "통장", "입출금"** keywords → use `set_product_type_deposit_account`
  - **General "대출"** without specifics → use `clarify_loan_type`

  **Step 2: Identify Business Action Intent**
  Look for action keywords:
  - **"신청하고 싶어요", "받고 싶어요", "하고 싶어요"** → Intent: APPLICATION
  - **"궁금해요", "알고 싶어요", "뭔가요"** → Intent: INQUIRY
  - **"비교", "차이점"** → Intent: COMPARISON

  **Enhanced Actions:**
  1. `set_product_type_didimdol_application()` - 디딤돌 대출 신청 의도
  2. `set_product_type_jeonse_application()` - 전세자금 대출 신청 의도  
  3. `set_product_type_deposit_application()` - 계좌 개설 신청 의도
  4. `invoke_qa_agent_didimdol(query)` - 디딤돌 대출 문의
  5. `invoke_qa_agent_jeonse(query)` - 전세자금 대출 문의
  6. `clarify_loan_type()` - 대출 유형 명확화 필요
  7. `handle_multiple_products()` - 복합 업무 처리

  User input: "{user_input}"
  {format_instructions}
```

#### 1.2 복합 의도 처리 로직

```yaml
# 복합 의도 예시
사용자: "디딤돌 대출 받고 나서 새 계좌도 만들고 싶어요"
→ 분석: [DIDIMDOL_APPLICATION, DEPOSIT_APPLICATION]
→ 액션: handle_multiple_products(primary="didimdol", secondary="deposit_account")
```

### Phase 2: 액션 실행 로직 개선

#### 2.1 main_agent_router_node 확장

**현재 코드** (`app/graph/agent.py:80`):
```python
async def main_agent_router_node(state: AgentState) -> AgentState:
    # 기존 로직...
    action_plan = result.get("action_plan", [])
    return {**state, "action_plan": action_plan}
```

**개선된 코드**:
```python
async def main_agent_router_node(state: AgentState) -> AgentState:
    # 기존 로직...
    action_plan = result.get("action_plan", [])
    
    # 새로운 액션 매핑 로직
    if action_plan:
        first_action = action_plan[0]
        updated_state = await _execute_enhanced_action(state, first_action)
        return {**state, **updated_state, "action_plan": action_plan}
    
    return {**state, "action_plan": action_plan}

async def _execute_enhanced_action(state: AgentState, action: str) -> dict:
    """Enhanced action execution with automatic scenario triggering"""
    
    # 제품별 신청 의도 자동 처리
    if action == "set_product_type_didimdol_application":
        return {
            "current_product_type": "didimdol",
            "business_intent": "application",
            "should_trigger_scenario": True,
            "action_plan": ["invoke_scenario_agent"]
        }
    
    elif action == "set_product_type_jeonse_application":
        return {
            "current_product_type": "jeonse", 
            "business_intent": "application",
            "should_trigger_scenario": True,
            "action_plan": ["invoke_scenario_agent"]
        }
    
    elif action == "set_product_type_deposit_application":
        return {
            "current_product_type": "deposit_account",
            "business_intent": "application", 
            "should_trigger_scenario": True,
            "action_plan": ["invoke_scenario_agent"]
        }
    
    # 복합 업무 처리
    elif action.startswith("handle_multiple_products"):
        # 첫 번째 업무 우선 처리
        primary_product = _extract_primary_product(action)
        return {
            "current_product_type": primary_product,
            "business_intent": "application",
            "pending_secondary_products": _extract_secondary_products(action),
            "should_trigger_scenario": True,
            "action_plan": ["invoke_scenario_agent"]
        }
    
    return {}
```

#### 2.2 시나리오 자동 트리거 메커니즘

**조건부 시나리오 실행**:
```python
# entry_point_node에서 자동 시나리오 트리거 확인
async def entry_point_node(state: AgentState) -> AgentState:
    # 기존 로직...
    
    # 시나리오 자동 트리거 조건 체크
    if state.get("should_trigger_scenario") and state.get("current_product_type"):
        active_scenario = get_active_scenario_data(state)
        if active_scenario:
            updated_state["current_scenario_stage_id"] = active_scenario.get("initial_stage_id")
            updated_state["scenario_auto_triggered"] = True
    
    return updated_state
```

### Phase 3: 상태 관리 개선

#### 3.1 업무 진행 상태 추적

**확장된 AgentState**:
```python
# app/graph/state.py 확장
@dataclass
class AgentState:
    # 기존 필드들...
    
    # 새로운 업무 추적 필드
    business_intent: Optional[str] = None  # "application", "inquiry", "comparison"
    intent_confidence: float = 0.0  # 의도 신뢰도 (0.0 ~ 1.0)
    required_info_checklist: Dict[str, bool] = field(default_factory=dict)
    scenario_completion_rate: float = 0.0  # 시나리오 완성도
    pending_secondary_products: List[str] = field(default_factory=list)
    should_trigger_scenario: bool = False
```

#### 3.2 정보 수집 완성도 추적

```python
def calculate_scenario_completion_rate(state: AgentState) -> float:
    """현재 시나리오의 정보 수집 완성도 계산"""
    
    scenario_data = state.get("active_scenario_data", {})
    collected_info = state.get("collected_product_info", {})
    
    if not scenario_data:
        return 0.0
    
    # 시나리오별 필수 정보 체크리스트
    required_fields = _get_required_fields_for_scenario(scenario_data)
    collected_fields = set(collected_info.keys())
    
    if not required_fields:
        return 1.0
    
    completion_rate = len(collected_fields & required_fields) / len(required_fields)
    return completion_rate

def _get_required_fields_for_scenario(scenario_data: dict) -> set:
    """시나리오별 필수 수집 정보 정의"""
    
    scenario_name = scenario_data.get("scenario_name", "")
    
    if "디딤돌" in scenario_name:
        return {"loan_purpose_confirmed", "marital_status", "has_home", "annual_income", "target_home_price"}
    elif "전세자금" in scenario_name:
        return {"lease_contract_date", "deposit_amount", "property_location", "urgency_level"}
    elif "입출금통장" in scenario_name:
        return {"account_purpose", "initial_deposit", "additional_services_choice"}
    
    return set()
```

---

## 🚀 구현 단계별 계획

### Step 1: 라우터 프롬프트 교체 (1주차)
1. `main_agent_prompts.yaml` 업데이트
2. 새로운 액션 유형 정의
3. 기본 테스트 수행

### Step 2: 액션 실행 로직 구현 (2주차)  
1. `main_agent_router_node` 함수 확장
2. `_execute_enhanced_action` 함수 구현
3. 시나리오 자동 트리거 메커니즘 추가

### Step 3: 상태 관리 개선 (3주차)
1. `AgentState` 확장
2. 정보 수집 완성도 추적 구현
3. 복합 업무 처리 로직 구현

### Step 4: 통합 테스트 및 최적화 (4주차)
1. 업무 프로세스 완료 테스트 재실행
2. 성능 최적화
3. 예외 상황 처리 강화

---

## 📊 기대 성과

### 개선 후 예상 지표

| 지표 | 현재 | 목표 | 개선율 |
|------|------|------|--------|
| 업무 의도 파악률 | 0% | 80% | +80%p |
| 시나리오 트리거 성공률 | 0% | 75% | +75%p |
| 정보 수집 완성률 | 0% | 70% | +70%p |
| 전체 업무 완료율 | 0% | 65% | +65%p |

### 테스트 시나리오별 예상 결과

1. **디딤돌대출_신청상담**: 25% → 80%
2. **전세자금대출_급한신청**: 0% → 75%  
3. **계좌개설_목적**: 0% → 70%
4. **복합_업무_처리**: 0% → 60%
5. **문의만_하는_고객**: 0% → 85%

---

## 🎯 추가 고려사항

### 1. 기존 Q&A 성능 유지
- 현재 **100% Q&A 성공률** 유지
- 개선 과정에서 기존 기능 저하 방지

### 2. 사용자 경험 향상
- 업무 진행 상황 실시간 안내
- 필요 서류 및 다음 단계 명확한 가이드

### 3. 확장성 고려
- 새로운 금융 상품 추가 용이성
- 시나리오 설정 파일 기반 확장

이 개선 계획을 통해 디딤돌 음성 에이전트가 **단순 정보 제공**을 넘어 **실제 업무 프로세스 완료**까지 지원하는 전문 상담원 역할을 수행할 수 있을 것입니다.