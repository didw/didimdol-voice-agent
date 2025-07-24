# 구현 권장사항: 응답 유형 시스템 개발 방안

## 1. 결론: 기존 코드 수정 권장

현재 코드베이스를 분석한 결과, **기존 코드를 수정하여 구현하는 것을 강력히 권장**합니다.

### 이유:
1. **견고한 기반 구조**: LangGraph 기반 상태 관리와 모듈화된 노드 시스템이 잘 구축되어 있음
2. **재사용 가능한 컴포넌트**: 시나리오 처리, WebSocket 통신, 상태 관리 등 핵심 기능이 이미 구현됨
3. **최소한의 변경**: 응답 유형 추가는 기존 구조 위에 자연스럽게 확장 가능
4. **리스크 최소화**: 검증된 코드베이스를 유지하면서 점진적 개선 가능

## 2. Backend 수정 계획

### 2.1 시나리오 JSON 구조 확장
**파일**: `backend/app/data/scenarios/deposit_account_scenario.json`

**수정 내용**:
- 각 stage에 `response_type` 필드 추가
- `choices` 배열 추가 (bullet, boolean 타입용)
- `skippable` 플래그 추가

**예시**:
```json
"customer_info_check": {
  "response_type": "bullet",  // 새로 추가
  "choices": [                 // 새로 추가
    {"value": "confirm", "label": "네, 맞습니다"},
    {"value": "modify", "label": "수정이 필요합니다"}
  ],
  "skippable": false,         // 새로 추가
  // 기존 필드들 유지
}
```

### 2.2 시나리오 로직 확장
**파일**: `backend/app/graph/nodes/workers/scenario_logic.py`

**수정 내용**:
- `generate_stage_prompt()` 함수 확장하여 response_type 처리
- 사용자 입력을 response_type에 따라 파싱하는 로직 추가

### 2.3 Synthesizer 업데이트
**파일**: `backend/app/graph/nodes/control/synthesize.py`

**수정 내용**:
- 최종 응답에 response_type 정보 포함
- WebSocket 메시지 구조에 추가 필드 전달

### 2.4 WebSocket 메시지 확장
**파일**: `backend/app/api/V1/chat.py`

**수정 내용**:
- `stage_response` 타입의 새로운 메시지 추가
- 기존 `llm_response` 메시지와 병행 사용

## 3. Frontend 수정 계획

### 3.1 타입 정의 확장
**파일**: `frontend/src/types/index.ts`

**추가 내용**:
```typescript
export interface StageResponseMessage {
  type: 'stage_response';
  stageId: string;
  responseType: 'narrative' | 'bullet' | 'boolean';
  prompt: string;
  choices?: Array<{
    value: string;
    label: string;
  }>;
}
```

### 3.2 새로운 UI 컴포넌트
**신규 파일**: `frontend/src/components/StageResponse.vue`

**내용**:
- response_type에 따른 동적 UI 렌더링
- 터치/클릭 이벤트 처리
- 선택 결과를 WebSocket으로 전송

### 3.3 Chat Store 업데이트
**파일**: `frontend/src/stores/chat.ts`

**수정 내용**:
- `stage_response` 메시지 핸들러 추가
- 구조화된 응답 데이터 저장
- 사용자 선택 추적

### 3.4 ChatInterface 수정
**파일**: `frontend/src/components/ChatInterface.vue`

**수정 내용**:
- 메시지 렌더링 로직에 StageResponse 컴포넌트 통합
- response_type에 따른 조건부 렌더링

## 4. 단계별 구현 순서

### Phase 1: Backend 준비 (1-2일)
1. 시나리오 JSON 구조 확장
2. response_type 처리 로직 추가
3. WebSocket 메시지 타입 추가

### Phase 2: Frontend 기본 구현 (2-3일)
1. 타입 정의 및 인터페이스 추가
2. StageResponse 컴포넌트 개발
3. Chat Store 업데이트

### Phase 3: 통합 테스트 (1-2일)
1. End-to-end 테스트
2. 각 response_type별 시나리오 검증
3. 음성/터치 입력 호환성 테스트

### Phase 4: 최적화 및 마무리 (1일)
1. 성능 최적화
2. 에러 처리 강화
3. 문서화

## 5. 주요 리스크 및 대응 방안

### 리스크 1: 기존 시나리오 호환성
- **대응**: response_type 필드가 없으면 기본값 'narrative' 사용
- **영향**: 기존 시나리오는 변경 없이 작동

### 리스크 2: 음성 인식과의 통합
- **대응**: 음성 입력을 텍스트로 변환 후 기존 파싱 로직 활용
- **영향**: 추가 개발 최소화

### 리스크 3: UI 복잡도 증가
- **대응**: 컴포넌트 기반 설계로 복잡도 관리
- **영향**: 유지보수성 향상

## 6. 예상 작업량

- **Backend**: 약 500-700 라인 수정/추가
- **Frontend**: 약 300-500 라인 수정/추가
- **테스트 코드**: 약 200-300 라인 추가
- **총 예상 기간**: 5-8일 (1명 기준)

## 7. 대안: 처음부터 다시 개발하는 경우

### 장점:
- 최신 설계 패턴 적용 가능
- 기술 부채 제거

### 단점:
- **개발 기간 3-4배 증가** (15-20일)
- 기존 기능 재구현 필요
- 새로운 버그 발생 가능성
- 검증된 코드 포기

### 결론:
현재 코드베이스의 품질이 우수하고 확장성이 좋으므로, 처음부터 다시 개발하는 것은 **권장하지 않습니다**.

## 8. 최종 권장사항

1. **기존 코드 수정 방식으로 진행**
2. **점진적 구현**으로 리스크 최소화
3. **기능 플래그**를 사용하여 단계별 배포
4. **A/B 테스트**로 사용자 반응 검증

현재 아키텍처는 잘 설계되어 있으며, 응답 유형 시스템은 기존 구조에 자연스럽게 통합될 수 있습니다.