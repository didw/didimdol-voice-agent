# 디딤돌 음성 에이전트 - 업무 의도 파악 및 시나리오 실행 분석 리포트

## 📊 핵심 문제 재평가 (업데이트)

### ✅ 수정된 문제 이해

**이전 분석 오류**: 테스트 케이스에서 기대한 액션명이 실제 시스템과 달랐습니다.
- ❌ 잘못된 기대: `set_product_type_didimdol`
- ✅ 실제 정상: `set_product_type` (with product_id parameter)

### 🎯 실제 핵심 문제 식별

업무 프로세스 완료 테스트와 시나리오 흐름 분석을 통해 **진짜 문제**를 발견했습니다:

1. **시나리오 연속성 중단**: `set_product_type_node`에서 `is_final_turn_response: True`로 설정하여 첫 응답 후 대화 즉시 종료
2. **자동 진행 메커니즘 부재**: 시나리오가 시작된 후 다음 턴에서 자동으로 계속되지 않음
3. **부분적 라우팅 문제**: 계좌개설 등 일부 업무가 `select_product_type`으로 잘못 라우팅

---

## 🔍 상세 문제 분석 (수정됨)

### 1. 시나리오 연속성 문제 ⚠️ 최우선

#### 위치: `app/graph/agent.py:505-510`
```python
return {
    **state, 
    "current_product_type": new_product_type, 
    "active_scenario_data": active_scenario,
    "current_scenario_stage_id": initial_stage_id,
    "final_response_text_for_tts": response_text,
    "is_final_turn_response": True  # ⚠️ 여기서 대화가 종료됨
}
```

#### 실제 흐름 vs 기대 흐름
**현재 실제 흐름**:
```
사용자: "디딤돌 대출 신청하고 싶어요"
→ set_product_type_node: 시나리오 로드 성공
→ 응답: "상담을 시작하시겠습니까?"
→ END (is_final_turn_response: True) ❌
```

**기대되는 흐름**:
```
사용자: "디딤돌 대출 신청하고 싶어요"
→ set_product_type_node: 시나리오 로드
→ 응답: "상담을 시작하시겠습니까?"
→ 사용자: "네"
→ 자동 시나리오 진행 ✅
```

### 2. 라우팅 문제 (부분적)

#### 정상 작동하는 케이스
- "디딤돌 대출 신청" → `set_product_type` (product_id: didimdol) ✅
- "전세자금대출 신청" → `set_product_type` (product_id: jeonse) ✅
- "디딤돌 대출이 뭔가요?" → `invoke_qa_agent` ✅

#### 문제가 있는 케이스
- "계좌 개설하고 싶어요" → `select_product_type` ❌
  - 기대: `set_product_type` (product_id: deposit_account)
  - 원인: 라우터 프롬프트에서 계좌개설 키워드 인식 부족

### 3. 워크플로우 설계 문제

#### 현재 워크플로우
```python
workflow.add_edge("set_product_type_node", END)  # 즉시 종료
```

#### 필요한 워크플로우
```
set_product_type_node → 시나리오 준비 상태 설정
→ 다음 턴: entry_point_node에서 자동 시나리오 진행 감지
→ invoke_scenario_agent → 실제 업무 프로세스 진행
```

---

## 🎯 대화 시나리오별 상세 분석

### 1. 디딤돌대출_신청상담 (25% 성공률)
**사용자**: "디딤돌 대출 신청하고 싶어요"
- **문제**: 명확한 의도(`디딤돌 대출 신청`)를 표현했지만 `set_product_type_didimdol` 액션 생성 실패
- **현재 결과**: 일반적인 `set_product_type` 액션만 생성

### 2. 전세자금대출_급한신청 (0% 성공률)
**사용자**: "다음 주에 전세 계약해야 하는데 전세자금대출 신청하고 싶어요"
- **문제**: 복합 정보(긴급성 + 제품 유형)를 포함한 명확한 의도를 파악하지 못함
- **놓친 요소**: 
  - 제품 유형: 전세자금대출
  - 긴급성: "다음 주에"
  - 업무 목적: 신청

### 3. 계좌개설_목적 (0% 성공률)
**사용자**: "계좌 개설하고 싶어요"
- **문제**: 대출이 아닌 다른 금융 상품에 대한 의도를 처리하지 못함
- **현재 시스템**: 대출 중심으로만 설계됨

### 4. 복합_업무_처리 (0% 성공률)
**사용자**: "디딤돌 대출 받고 나서 새 계좌도 만들고 싶어요"
- **문제**: 여러 업무를 순차적으로 처리하는 복합 의도를 인식하지 못함
- **필요 기능**: 우선순위 결정 및 업무 큐 관리

### 5. 문의만_하는_고객 (0% 성공률)
**사용자**: "디딤돌 대출이 뭔가요?"
- **첫 번째 턴은 성공**: `invoke_qa_agent` 정확히 실행
- **두 번째 턴 실패**: "그냥 궁금해서..." → 적절한 마무리 액션 부재

---

## 💡 개선 방향 (현재 구조 내에서)

### 1. 라우터 프롬프트 강화

#### 현재 문제
```python
prompt_key = 'initial_task_selection_prompt' if not current_product_type else 'router_prompt'
```

#### 개선 방안
- **제품별 의도 인식** 강화
- **업무 우선순위** 판단 로직 추가
- **복합 의도** 분해 및 처리

### 2. 액션 플랜 세분화

#### 현재 액션 유형 확장
```
기존: set_product_type
개선: set_product_type_didimdol, set_product_type_jeonse, set_product_type_deposit_account

기존: select_product_type  
개선: confirm_product_selection, clarify_product_intent
```

### 3. 시나리오 트리거링 메커니즘 개선

#### 필요한 조건 체크
- 제품 유형 명확화 확인
- 고객 의도 명확성 검증
- 필수 정보 수집 상태 확인

### 4. 상태 관리 개선

#### 현재 상태 추적 부족
```python
current_product_type = state.get("current_product_type")  # None으로 유지됨
```

#### 개선된 상태 관리
- **의도 명확성 점수** 추가
- **수집된 정보 완성도** 추적
- **다음 단계 준비도** 평가

---

## 📋 구체적 개선 계획

### Phase 1: 라우터 로직 개선
1. **제품별 의도 인식 패턴** 추가
2. **복합 의도 분해** 로직 구현
3. **우선순위 기반 업무 선택** 메커니즘

### Phase 2: 액션 플랜 세분화
1. **구체적인 액션 유형** 정의
2. **액션 체이닝** 로직 구현
3. **상태 전이 조건** 명확화

### Phase 3: 시나리오 실행 연결
1. **트리거 조건 체크** 강화
2. **정보 수집 상태 추적** 개선
3. **스테이지 진행 자동화** 구현

---

## 🎯 기대 효과

개선 후 예상되는 성과:
- **업무 의도 파악률**: 0% → 80% 이상
- **시나리오 트리거 성공률**: 0% → 75% 이상
- **정보 수집 완성률**: 0% → 70% 이상
- **전체 업무 완료율**: 0% → 65% 이상

이러한 개선을 통해 에이전트가 단순한 Q&A 기능을 넘어 **실제 업무 프로세스를 완료할 수 있는 상담원 역할**을 수행할 수 있을 것으로 기대됩니다.