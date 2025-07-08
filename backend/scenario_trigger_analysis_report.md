# 디딤돌 음성 에이전트 - 시나리오 트리거 메커니즘 분석 리포트

## 🔍 핵심 발견사항

### ✅ 정상 작동하는 부분
1. **시나리오 로딩**: `set_product_type_node`는 올바르게 시나리오를 로드하고 첫 번째 응답을 생성
2. **제품 타입 매핑**: "디딤돌 대출 신청"과 "전세자금대출 신청"은 올바른 시나리오로 매핑됨
3. **RAG 시스템**: 단순 정보 문의는 정상적으로 처리됨

### 🚨 문제점 식별

#### 1. 시나리오 연속성 문제
**위치**: `app/graph/agent.py:505-510`
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

**문제**: `set_product_type_node`에서 첫 번째 시나리오 응답 후 `is_final_turn_response: True`로 설정하여 대화가 즉시 종료됩니다.

#### 2. 계좌개설 라우팅 문제
**관찰**: "계좌 개설하고 싶어요" → `select_product_type` 액션으로 라우팅
**원인**: 라우터가 계좌개설을 명확한 제품 타입으로 인식하지 못함

#### 3. 워크플로우 설계 문제
**현재 워크플로우**:
```
set_product_type_node → END  # 즉시 종료
```

**필요한 워크플로우**:
```
set_product_type_node → 시나리오 진행 → 다음 턴에서 자동 시나리오 실행
```

---

## 🎯 시나리오별 상세 분석

### 1. 디딤돌 대출 신청
**입력**: "디딤돌 대출 신청하고 싶어요"
**실행 흐름**:
```
main_agent_router_node: ['set_product_type']
→ set_product_type_node: 시나리오 로드 성공
→ 응답: "안녕하세요, 고객님! 신한은행 디딤돌 주택담보대출 상담 서비스입니다. 지금 바로 상담을 시작하시겠습니까?"
→ END (is_final_turn_response: True)
```

**문제**: 첫 번째 응답 후 대화 종료. 고객이 "네"라고 답변해도 다음 단계로 진행되지 않음.

### 2. 전세자금 대출 신청  
**입력**: "다음 주에 전세 계약해야 하는데 전세자금대출 신청하고 싶어요"
**실행 흐름**:
```
main_agent_router_node: ['set_product_type']
→ set_product_type_node: 시나리오 로드 성공 (product_id: jeonse)
→ 응답: "안녕하세요, 고객님! 신한은행 전세자금대출 상담 서비스입니다..."
→ END (is_final_turn_response: True)
```

**특이사항**: 긴급성 키워드("다음 주")가 인식되지 않음. 일반적인 전세대출 시나리오로만 처리됨.

### 3. 계좌 개설
**입력**: "계좌 개설하고 싶어요"
**실행 흐름**:
```
main_agent_router_node: ['select_product_type']
→ prepare_direct_response_node: chit-chat 응답 생성
→ END
```

**문제**: 계좌개설이 `set_product_type`으로 라우팅되지 않아 시나리오가 전혀 트리거되지 않음.

### 4. 모호한 대출 문의
**입력**: "대출 받고 싶어요"  
**실행 흐름**:
```
main_agent_router_node: ['select_product_type']
→ prepare_direct_response_node: 명확화 질문 생성
→ END
```

**결과**: 올바른 라우팅. 모호한 요청에 대해 명확화를 요구하는 것이 정상.

### 5. 단순 정보 문의
**입력**: "디딤돌 대출이 뭔가요?"
**실행 흐름**:
```
main_agent_router_node: ['invoke_qa_agent']
→ factual_answer_node: RAG 파이프라인 실행
→ synthesize_response_node: 최종 답변 생성
→ END
```

**결과**: 완벽하게 작동. 상세한 정보를 제공함.

---

## 🔧 문제 해결 방안

### 1. 시나리오 연속성 해결

#### 방안 A: set_product_type_node 수정
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
        "scenario_continuation_ready": True  # 다음 턴에서 시나리오 계속
    }
```

#### 방안 B: 워크플로우 수정
```python
# workflow.add_edge("set_product_type_node", END)  # 기존
workflow.add_edge("set_product_type_node", "scenario_waiting_node")  # 새로운 방법
```

### 2. 계좌개설 라우팅 개선

#### 프롬프트 개선
```yaml
# app/config/main_agent_prompts.yaml 수정
- **Keywords**: "디딤돌 대출", "전세자금 대출", "입출금 통장", "계좌 개설"
- **Example User Input**: "계좌 개설하고 싶어요" -> `set_product_type(product_id='deposit_account')`
```

### 3. 자동 시나리오 진행 메커니즘

#### entry_point_node 확장
```python
async def entry_point_node(state: AgentState) -> AgentState:
    # ... 기존 로직 ...
    
    # 시나리오 연속 진행 확인
    if (state.get("scenario_continuation_ready") and 
        state.get("current_product_type") and 
        state.get("user_input_text")):
        
        updated_state["action_plan"] = ["invoke_scenario_agent"]
        updated_state["scenario_continuation_ready"] = False
        print("🔄 시나리오 자동 진행 모드 활성화")
    
    return updated_state
```

---

## 📊 개선 후 예상 흐름

### 개선된 디딤돌 대출 신청 흐름:

#### 턴 1
```
사용자: "디딤돌 대출 신청하고 싶어요"
→ set_product_type_node: 시나리오 로드
→ 응답: "안녕하세요! 신한은행 디딤돌 주택담보대출 상담 서비스입니다. 지금 바로 상담을 시작하시겠습니까?"
→ 상태: scenario_continuation_ready = True
```

#### 턴 2  
```
사용자: "네, 시작해주세요"
→ entry_point_node: 시나리오 연속 진행 감지
→ action_plan = ["invoke_scenario_agent"]
→ call_scenario_agent_node → process_scenario_logic_node
→ 응답: "디딤돌 대출은 주택 구입 자금 마련을 위한 대출입니다. 주택 구입 목적으로 문의주신 것이 맞으실까요?"
```

#### 턴 3
```
사용자: "집 사려고 해요"
→ 시나리오 계속 진행
→ 다음 단계: ask_marital_status
→ 응답: "고객님의 혼인 상태를 말씀해주시겠어요?"
```

---

## 🎯 구현 우선순위

### 1단계: 시나리오 연속성 확보 (1주)
- `set_product_type_node` 수정
- `entry_point_node`에 자동 진행 로직 추가

### 2단계: 라우팅 개선 (1주)
- 계좌개설 키워드 인식 개선
- 프롬프트 템플릿 업데이트

### 3단계: 테스트 및 검증 (1주)
- 수정된 흐름 테스트
- 각 시나리오별 end-to-end 검증

이 개선을 통해 **시나리오가 자연스럽게 시작되고 연속적으로 진행**되어 실제 업무 프로세스를 완료할 수 있을 것입니다.