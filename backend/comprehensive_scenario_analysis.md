# 디딤돌 음성 에이전트 - 종합 시나리오 분석 및 개선 계획

## 📋 분석 요약

시나리오 즉, 특정 업무를 시작하는 단계에 대한 로직을 면밀히 검토한 결과, **핵심 문제는 시나리오 연속성**에 있었습니다.

### 🔍 주요 발견사항

1. **시나리오 로딩은 정상**: `set_product_type` 액션이 올바르게 시나리오를 로드하고 첫 번째 응답을 생성
2. **연속성 중단**: `is_final_turn_response: True`로 인해 첫 번째 응답 후 대화가 즉시 종료
3. **자동 진행 부재**: 다음 턴에서 시나리오를 자동으로 계속하는 메커니즘이 없음

---

## 🎯 시나리오별 상세 분석

### 1. 디딤돌 대출 신청 시나리오

#### 현재 흐름 분석
```
입력: "디딤돌 대출 신청하고 싶어요"
↓
main_agent_router_node: ['set_product_type']
├─ 프롬프트: 'initial_task_selection_prompt'
├─ 제품 인식: ✅ "디딤돌 대출" 키워드 감지
└─ 액션 생성: set_product_type (올바름)
↓
set_product_type_node:
├─ product_id 추출: "didimdol" ✅
├─ 시나리오 로드: "신한은행 디딤돌 주택담보대출 상담" ✅
├─ 초기 스테이지: "greeting" ✅
├─ 응답 생성: "안녕하세요, 고객님! 신한은행 디딤돌 주택담보대출 상담 서비스입니다. 지금 바로 상담을 시작하시겠습니까?" ✅
└─ 종료 설정: is_final_turn_response: True ❌
```

#### 문제점
- 시나리오가 성공적으로 시작되지만 **즉시 종료**됨
- 고객이 "네"라고 답변해도 다음 단계로 진행되지 않음

#### 기대되는 흐름
```
턴 1: 시나리오 시작 → "상담을 시작하시겠습니까?"
턴 2: "네" → ask_loan_purpose 단계로 자동 진행
턴 3: "집 사려고 해요" → ask_marital_status 단계로 진행
```

### 2. 전세자금 대출 신청 시나리오

#### 현재 흐름 분석
```
입력: "다음 주에 전세 계약해야 하는데 전세자금대출 신청하고 싶어요"
↓
main_agent_router_node: ['set_product_type']
├─ 제품 인식: ✅ "전세자금대출" 키워드 감지
└─ 액션 생성: set_product_type (올바름)
↓
set_product_type_node:
├─ product_id 추출: "jeonse" ✅
├─ 시나리오 로드: "신한은행 전세자금대출 상담" ✅
├─ 초기 스테이지: "greeting_jeonse" ✅
├─ 응답 생성: "전세자금 대출 관련하여 어떤 점을 도와드릴까요?" ✅
└─ 종료 설정: is_final_turn_response: True ❌
```

#### 특이사항
- **긴급성 인식 부족**: "다음 주에" 키워드가 시나리오에 반영되지 않음
- 일반적인 전세대출 시나리오로만 처리됨

### 3. 계좌 개설 시나리오

#### 현재 흐름 분석
```
입력: "계좌 개설하고 싶어요"
↓
main_agent_router_node: ['select_product_type'] ❌
├─ 문제: "계좌 개설" → set_product_type으로 라우팅 안됨
└─ 잘못된 액션: select_product_type
↓
prepare_direct_response_node:
└─ chit-chat 응답 생성 (시나리오 트리거 안됨)
```

#### 문제점
1. **라우팅 실패**: 계좌개설이 명확한 제품 타입으로 인식되지 않음
2. **키워드 인식 부족**: "계좌", "통장" 키워드가 프롬프트에 명시되지 않음

#### 필요한 개선
```yaml
# initial_task_selection_prompt 개선 필요
Keywords: "디딤돌 대출", "전세자금 대출", "입출금 통장", "계좌 개설"
Example: "계좌 개설하고 싶어요" -> set_product_type(product_id='deposit_account')
```

### 4. 모호한 대출 문의

#### 현재 흐름 분석
```
입력: "대출 받고 싶어요"
↓
main_agent_router_node: ['select_product_type'] ✅
├─ 올바른 판단: 모호한 요청에 대한 명확화
└─ 적절한 액션: select_product_type
↓
prepare_direct_response_node:
└─ 명확화 질문 생성 ✅
```

#### 결과
- **정상 작동**: 모호한 요청에 대해 적절히 명확화를 요구

### 5. 단순 정보 문의

#### 현재 흐름 분석
```
입력: "디딤돌 대출이 뭔가요?"
↓
main_agent_router_node: ['invoke_qa_agent'] ✅
├─ 올바른 판단: 정보 문의로 인식
└─ 적절한 액션: invoke_qa_agent
↓
factual_answer_node → synthesize_response_node:
└─ 상세한 정보 제공 ✅
```

#### 결과
- **완벽하게 작동**: RAG 파이프라인을 통해 상세한 정보 제공

---

## 🔧 핵심 문제 해결 방안

### 1. 시나리오 연속성 확보 (최우선)

#### 현재 문제 코드
```python
# app/graph/agent.py:505-510
return {
    **state, 
    "current_product_type": new_product_type, 
    "active_scenario_data": active_scenario,
    "current_scenario_stage_id": initial_stage_id,
    "final_response_text_for_tts": response_text,
    "is_final_turn_response": True  # ❌ 여기서 대화가 종료됨
}
```

#### 해결 방안 A: 상태 기반 접근
```python
async def set_product_type_node(state: AgentState) -> AgentState:
    # ... 기존 로직 ...
    
    return {
        **state, 
        "current_product_type": new_product_type, 
        "active_scenario_data": active_scenario,
        "current_scenario_stage_id": initial_stage_id,
        "final_response_text_for_tts": response_text,
        "is_final_turn_response": True,  # 첫 번째 응답은 종료
        "scenario_ready_for_continuation": True,  # 다음 턴에서 시나리오 계속
        "scenario_awaiting_user_response": True
    }
```

#### 해결 방안 B: entry_point_node 확장
```python
async def entry_point_node(state: AgentState) -> AgentState:
    # ... 기존 로직 ...
    
    # 시나리오 연속 진행 확인
    if (state.get("scenario_ready_for_continuation") and 
        state.get("current_product_type") and 
        state.get("user_input_text")):
        
        print("🔄 시나리오 자동 진행 모드 활성화")
        updated_state["action_plan"] = ["invoke_scenario_agent"]
        updated_state["scenario_ready_for_continuation"] = False
    
    return updated_state
```

### 2. 계좌개설 라우팅 개선

#### 프롬프트 템플릿 수정
```yaml
# app/config/main_agent_prompts.yaml
initial_task_selection_prompt: |
  # ... 기존 내용 ...
  
  1. **`set_product_type(product_id: str)`**: Use this *only* when the user explicitly mentions a specific financial product we offer.
      - **Keywords**: "디딤돌 대출", "전세자금 대출", "입출금 통장", "계좌 개설", "통장 만들기"
      - **Example User Input**: 
        - "디딤돌 대출 받고 싶어요." -> `set_product_type(product_id='didimdol')`
        - "계좌 개설하고 싶어요." -> `set_product_type(product_id='deposit_account')`
```

### 3. 긴급성 인식 개선

#### 시나리오 매개변수 확장
```python
# 긴급성 키워드 감지 로직 추가
def detect_urgency(user_input: str) -> dict:
    urgency_keywords = ["급", "빨리", "다음 주", "내일", "오늘", "당장"]
    urgency_level = "normal"
    
    for keyword in urgency_keywords:
        if keyword in user_input:
            urgency_level = "high"
            break
    
    return {"urgency_level": urgency_level}

# set_product_type_node에서 활용
urgency_info = detect_urgency(user_input)
updated_state["urgency_context"] = urgency_info
```

---

## 📊 개선 후 예상 시나리오 흐름

### 개선된 디딤돌 대출 신청 흐름

#### 턴 1: 시나리오 시작
```
사용자: "디딤돌 대출 신청하고 싶어요"
↓
시스템 처리:
- set_product_type(product_id='didimdol') 실행
- 시나리오 로드: "신한은행 디딤돌 주택담보대출 상담"
- scenario_ready_for_continuation = True 설정
↓
응답: "안녕하세요, 고객님! 신한은행 디딤돌 주택담보대출 상담 서비스입니다. 지금 바로 상담을 시작하시겠습니까?"
```

#### 턴 2: 자동 시나리오 진행
```
사용자: "네, 시작해주세요"
↓
시스템 처리:
- entry_point_node에서 scenario_ready_for_continuation 감지
- action_plan = ["invoke_scenario_agent"] 자동 설정
- call_scenario_agent_node → process_scenario_logic_node 실행
- 다음 단계: ask_loan_purpose
↓
응답: "디딤돌 대출은 주택 구입 자금 마련을 위한 대출입니다. 주택 구입 목적으로 문의주신 것이 맞으실까요?"
```

#### 턴 3: 정보 수집 진행
```
사용자: "집 사려고 해요"
↓
시스템 처리:
- 시나리오 계속 진행
- 정보 수집: loan_purpose_confirmed = True
- 다음 단계: ask_marital_status
↓
응답: "고객님의 혼인 상태를 말씀해주시겠어요? (예: 미혼, 기혼, 예비부부)"
```

### 개선된 계좌개설 흐름

#### 턴 1: 시나리오 시작 (개선 후)
```
사용자: "계좌 개설하고 싶어요"
↓
시스템 처리:
- 개선된 라우터: set_product_type(product_id='deposit_account') ✅
- 시나리오 로드: "신한은행 입출금통장 신규 상담"
↓
응답: "안녕하세요, 고객님! 신한은행 입출금통장 신규 서비스입니다. 혹시 체크카드나 인터넷뱅킹도 함께 신청하시겠어요?"
```

---

## 🚀 구현 로드맵

### Phase 1: 시나리오 연속성 확보 (1주차)
1. `set_product_type_node` 수정
   - `scenario_ready_for_continuation` 상태 추가
2. `entry_point_node` 확장
   - 자동 시나리오 진행 로직 추가
3. 기본 테스트 수행

### Phase 2: 라우팅 개선 (2주차)
1. `initial_task_selection_prompt` 업데이트
   - 계좌개설 키워드 추가
2. 라우팅 테스트 케이스 확장
3. 긴급성 감지 로직 구현

### Phase 3: 통합 테스트 및 검증 (3주차)
1. 전체 시나리오 end-to-end 테스트
2. 성능 최적화
3. 예외 상황 처리 강화

---

## 📈 예상 개선 효과

### 시나리오 트리거 성공률
- **현재**: 2/5 시나리오만 올바르게 시작 (40%)
- **개선 후**: 5/5 시나리오 모두 시작 (100%)

### 시나리오 연속성
- **현재**: 모든 시나리오가 첫 응답 후 종료 (0%)
- **개선 후**: 자연스러운 대화 흐름으로 업무 완료 (80%+)

### 전체 업무 완료율
- **현재**: 0% (업무 프로세스 미완료)
- **개선 후**: 65%+ (실제 상담원 수준의 업무 처리)

이 개선을 통해 디딤돌 음성 에이전트가 **시나리오를 자연스럽게 시작하고 연속적으로 진행**하여 실제 금융 업무를 완료할 수 있는 전문 상담원 역할을 수행할 것입니다.