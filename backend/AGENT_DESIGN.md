# Agent Architecture Design for Enhanced Scenario Processing

## Overview
이 문서는 입출금통장 시나리오와 같은 복잡한 다단계 정보 수집 시나리오를 효과적으로 처리하기 위한 agent.py의 구조 개선 설계를 담고 있습니다.

## 핵심 설계 원칙

### 1. 조건부 정보 수집 (Conditional Information Collection)
- **필수 필드(required: true)**: 시나리오 전체에서 반드시 수집해야 하는 정보
- **조건부 필드(required: false)**: 특정 서비스 선택 시에만 수집하는 정보
- **기본값(default)**: 사용자가 명시하지 않을 경우 자동으로 적용되는 값

### 2. 지능형 스테이지 전환 (Intelligent Stage Transition)
- **자동 진행**: 분기가 없고 필요 정보가 수집된 경우
- **LLM 판단**: 복수의 분기가 있는 경우
- **조건부 진행**: 특정 필드 값에 따른 동적 경로 결정

## 구현 전략

### 1. Enhanced State Management
```python
class AgentState(TypedDict):
    # 기존 필드들...
    collected_product_info: Dict[str, Any]
    pending_required_fields: List[str]  # 아직 수집되지 않은 필수 필드
    conditional_fields_map: Dict[str, List[str]]  # 조건별 필요 필드 매핑
    field_defaults: Dict[str, Any]  # 필드별 기본값
```

### 2. Field Collection Logic
```python
def process_field_collection(state: AgentState, scenario_data: Dict) -> Dict:
    """필드 수집 로직 처리"""
    
    # 1. 필수 필드 확인
    required_fields = get_required_fields(scenario_data, state)
    
    # 2. 조건부 필드 확인
    conditional_fields = get_conditional_fields(state)
    
    # 3. 수집 완료 여부 판단
    if all_required_collected(state, required_fields + conditional_fields):
        return advance_to_next_stage(state)
    
    # 4. 미수집 정보 요청
    return request_missing_info(state, required_fields + conditional_fields)
```

### 3. Dynamic Field Requirements
```python
def get_conditional_fields(state: AgentState) -> List[Dict]:
    """현재 상태에 따른 조건부 필드 결정"""
    
    conditional_fields = []
    collected = state.get("collected_product_info", {})
    
    # 인터넷뱅킹 선택 시
    if collected.get("use_internet_banking") == True:
        conditional_fields.extend([
            "security_medium",
            "transfer_limit_per_time",
            "transfer_limit_per_day",
            "important_transaction_alert",
            "withdrawal_alert",
            "overseas_ip_restriction",
            "additional_withdrawal_account"
        ])
        
        # 타행 OTP 선택 시 추가 필드
        if collected.get("security_medium") == "타행 OTP":
            conditional_fields.extend([
                "other_otp_manufacturer",
                "other_otp_serial"
            ])
    
    # 체크카드 선택 시
    if collected.get("use_check_card") == True:
        conditional_fields.extend([
            "card_receive_method",
            "card_type",
            "postpaid_transport",
            "payment_date",
            "statement_method",
            "same_password_as_account",
            "card_usage_alert"
        ])
        
        # 배송 선택 시 추가 필드
        if collected.get("card_receive_method") == "배송":
            conditional_fields.append("card_delivery_location")
    
    return conditional_fields
```

### 4. Stage Processing Enhancement
```python
async def process_scenario_logic_node(state: AgentState) -> AgentState:
    """개선된 시나리오 로직 처리"""
    
    current_stage_info = get_current_stage_info(state)
    
    # 1. 정보 수집 스테이지 처리
    if current_stage_info.get("collect_multiple_info"):
        return await process_enhanced_info_collection(state, current_stage_info)
    
    # 2. 프로세스 스테이지 처리 (prompt가 없는 로직 전용)
    if not current_stage_info.get("prompt"):
        return await process_logic_stage(state, current_stage_info)
    
    # 3. 일반 대화 스테이지 처리
    return await process_conversation_stage(state, current_stage_info)
```

### 5. Information Collection Strategy
```python
async def process_enhanced_info_collection(state: AgentState, stage_info: Dict) -> AgentState:
    """향상된 정보 수집 처리"""
    
    # 1. 사용자 입력에서 다중 정보 추출
    extracted_info = extract_multiple_info_from_text(
        user_input=state.get("stt_result", ""),
        scenario_data=state.get("active_scenario_data")
    )
    
    # 2. 기본값 적용
    apply_defaults_to_collected_info(extracted_info, state)
    
    # 3. 조건부 필드 검증
    validate_conditional_fields(extracted_info, state)
    
    # 4. 수집 상태 업데이트
    update_collection_state(state, extracted_info)
    
    # 5. 다음 단계 결정
    return determine_next_collection_stage(state)
```

### 6. Process Stage Handler
```python
def handle_process_stages(stage_id: str, state: AgentState) -> str:
    """프로세스 스테이지 자동 처리"""
    
    process_handlers = {
        "process_internet_banking_info": handle_ib_process,
        "process_check_card_info": handle_card_process,
        # 다른 프로세스 핸들러들...
    }
    
    handler = process_handlers.get(stage_id)
    if handler:
        return handler(state)
    
    # 기본 처리
    return determine_next_stage_by_conditions(state)
```

## 주요 개선사항

### 1. 유연한 필드 관리
- required/optional 구분을 통한 동적 검증
- 조건부 필드의 자동 활성화/비활성화
- 기본값 자동 적용 메커니즘

### 2. 스마트 스테이지 네비게이션
- 단순 경로는 자동 진행
- 복잡한 분기는 LLM 판단
- 프로세스 스테이지의 투명한 처리

### 3. 효율적인 정보 수집
- 한 번에 여러 정보 수집 가능
- 미수집 정보만 선별적 요청
- 컨텍스트 기반 정보 추출

### 4. 향상된 사용자 경험
- 불필요한 질문 최소화
- 자연스러운 대화 흐름
- 명확한 진행 상황 피드백

## 구현 로드맵

### Phase 1: Core Infrastructure
1. AgentState 확장 (필드 관리 추가)
2. 조건부 필드 로직 구현
3. 기본값 적용 시스템

### Phase 2: Process Optimization
1. 프로세스 스테이지 핸들러 구현
2. 자동/수동 스테이지 전환 로직 개선
3. 다중 정보 수집 최적화

### Phase 3: Intelligence Enhancement
1. LLM 기반 필드 추출 개선
2. 컨텍스트 인식 정보 수집
3. 동적 대화 흐름 생성

### Phase 4: Testing & Refinement
1. 시나리오별 테스트 케이스 작성
2. 엣지 케이스 처리
3. 성능 최적화

## 예상 효과

1. **개발 효율성**: 새로운 시나리오 추가 시 코드 변경 최소화
2. **유지보수성**: 시나리오 로직과 코드 로직의 명확한 분리
3. **사용자 만족도**: 더 자연스럽고 효율적인 대화 경험
4. **확장성**: 다양한 복잡도의 시나리오 지원 가능