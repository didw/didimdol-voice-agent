# Technical Requirements Document - Slot Filling Panel UI

## 개요
대화 중 수집되는 정보를 실시간으로 표시하는 Slot Filling 패널을 채팅 인터페이스 왼쪽에 추가

## 목표
- 사용자가 어떤 정보가 수집되었는지 실시간으로 확인
- 필수 정보 중 무엇이 부족한지 시각적으로 표시
- 기존 채팅 UI와 자연스럽게 통합

## 기술 요구사항

### 1. Pinia Store 생성
**파일**: `src/stores/slotFillingStore.ts`

```typescript
interface SlotFillingState {
  productType: string | null
  requiredFields: RequiredField[]
  collectedInfo: Record<string, any>
  completionStatus: Record<string, boolean>
  completionRate: number
  fieldGroups?: FieldGroup[]
}

interface RequiredField {
  key: string
  displayName: string
  type: 'boolean' | 'text' | 'choice' | 'number'
  required: boolean
  choices?: string[]
  unit?: string
  description?: string
  dependsOn?: {
    field: string
    value: any
  }
}

interface FieldGroup {
  id: string
  name: string
  fields: string[]
}
```

주요 액션:
- `updateSlotFilling(message: SlotFillingUpdate)`: WebSocket 메시지로부터 상태 업데이트
- `clearSlotFilling()`: 세션 초기화 시 상태 클리어
- `getFieldsByGroup()`: 그룹별 필드 반환
- `isFieldVisible(field: RequiredField)`: 의존성에 따른 필드 표시 여부

### 2. SlotFillingPanel 컴포넌트
**파일**: `src/components/SlotFillingPanel.vue`

기능:
- 필수 정보 필드 목록 표시
- 수집된 정보는 체크마크(✓)와 함께 값 표시
- 미수집 정보는 회색으로 표시
- 그룹별로 섹션 구분 (예: 개인 정보, 재무 정보)
- 진행률 표시 (completionRate)
- 조건부 필드 표시 (dependsOn 로직)
- 필드 설명 툴팁 표시

### 3. ChatInterface 레이아웃 수정
**파일**: `src/components/ChatInterface.vue`

변경사항:
- 그리드 레이아웃으로 변경 (기존: 전체 화면 채팅)
- 왼쪽 패널(30%) + 오른쪽 채팅(70%)
- 모바일에서는 탭 또는 슬라이드 방식

### 4. WebSocket 핸들러 추가
**파일**: `src/stores/chatStore.ts`

`connectWebSocket()` 메서드에 추가:
```typescript
case 'slot_filling_update':
  const slotFillingStore = useSlotFillingStore()
  slotFillingStore.updateSlotFilling(message as SlotFillingUpdate)
  break
```

메시지 타입 정의:
```typescript
interface SlotFillingUpdate {
  type: 'slot_filling_update'
  productType: string | null
  requiredFields: RequiredField[]
  collectedInfo: Record<string, any>
  completionStatus: Record<string, boolean>
  completionRate: number
  fieldGroups?: FieldGroup[]
}
```

### 5. UI/UX 디자인

**데스크톱 레이아웃**:
```
┌─────────────────────┬─────────────────────────┐
│  수집 정보 현황      │                         │
│  진행률: 40%        │      채팅 인터페이스     │
├─────────────────────┤                         │
│ 개인 정보           │                         │
│  ✓ 대출 목적        │                         │
│  ✓ 결혼 상태: 미혼  │                         │
│  ○ 주택 소유 여부   │                         │
│                     │                         │
│ 재무 정보           │                         │
│  ○ 연소득          │                         │
│  ○ 목표 주택가격    │                         │
└─────────────────────┴─────────────────────────┘
```

**모바일 레이아웃**:
- 상단 토글 버튼으로 패널 표시/숨김
- 또는 스와이프로 패널 전환

### 6. 스타일링
- 수집 완료: 초록색 체크마크, 진한 텍스트
- 미수집: 회색 원형 아이콘, 연한 텍스트
- 애니메이션: 정보 수집 시 부드러운 전환 효과
- 다크모드 지원 고려

## 구현 순서
1. slotFillingStore 생성 및 WebSocket 핸들러 연결
2. SlotFillingPanel 컴포넌트 기본 구조 구현
3. ChatInterface 레이아웃 수정
4. 스타일링 및 애니메이션 적용
5. 모바일 반응형 처리

## 테스트 요구사항
1. WebSocket 메시지 수신 시 UI 업데이트 확인
2. 다양한 화면 크기에서 레이아웃 테스트
3. 정보 수집/삭제 시 애니메이션 동작 확인
4. 세션 초기화 시 상태 클리어 확인

## 성능 고려사항
- 불필요한 리렌더링 방지 (computed 속성 활용)
- 애니메이션은 CSS transition 사용
- 모바일에서 패널 토글 시 부드러운 전환
- WebSocket 메시지 디바운싱 (동일 정보 중복 업데이트 방지)

## Backend 인터페이스 연동
- Backend의 `display_name` → Frontend의 `displayName` 매핑
- 시나리오 JSON의 `required_info_fields` 구조 활용
- `field_groups` 정보가 있을 경우 그룹별 표시
- 의존성 필드는 조건에 따라 동적으로 표시/숨김