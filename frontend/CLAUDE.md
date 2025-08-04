# Frontend 개발 가이드

**Vue 3 + TypeScript 기반 지능형 음성 상담 UI 개발 가이드**

## 역할

**디딤돌 음성 상담 에이전트 웹 UI** - 실시간 음성 기반 금융 상담 및 지능형 Slot Filling 인터페이스

## 개발 시작

### 1. Git Pull (필수)
```bash
git pull origin main
```

### 2. 환경 설정
`.env.development` 파일 생성:
```env
VITE_API_BASE_URL=http://localhost:8001
VITE_WS_BASE_URL=ws://localhost:8001
```

### 3. 서버 실행
```bash
npm install
npm run dev
```

## 주요 라이브러리

- **Vue 3**: Composition API 기반 반응형 UI 프레임워크
- **TypeScript**: 타입 안전성 및 개발 경험 향상
- **Vite**: 고속 빌드 도구 및 개발 서버
- **Pinia**: 현대적 상태 관리 (Chat + Slot Filling)
- **Web Audio API**: 실시간 음성 처리 및 오디오 제어
- **Vitest**: 단위 테스트 프레임워크

## 🏗️ 아키텍처 개요

### 컴포넌트 구조
```
src/
├── components/
│   ├── ChatInterface.vue       # 메인 채팅 인터페이스
│   ├── SlotFillingPanel.vue    # 지능형 정보 수집 패널
│   └── SlotFillingDebug.vue    # 개발자 디버깅 도구
├── stores/
│   ├── chatStore.ts           # 대화 상태 관리
│   └── slotFillingStore.ts    # Slot Filling 상태 관리
├── services/
│   └── api.ts                 # Backend API 통신
└── types/
    └── slotFilling.ts         # Slot Filling 타입 정의
```

### 상태 관리 패턴
- **chatStore**: 대화 이력, WebSocket 연결, 음성 처리
- **slotFillingStore**: 정보 수집 상태, 진행률, 필드 가시성

## 🎯 핵심 기능

### 🎤 실시간 음성 처리
- **Web Audio API** 기반 음성 녹음/재생
- **WebSocket** 실시간 통신
- **EPD (End Point Detection)** 지원
- **Barge-in** 기능 (사용자 중단 입력)

### 📊 지능형 Slot Filling Panel

#### 주요 특징
- **실시간 정보 수집 현황** 시각화
- **계층적 필드 표시** (depth 기반 그룹화)
- **조건부 필드 렌더링** (show_when 조건 처리)
- **진행률 바 및 애니메이션**
- **모바일 스와이프 제스처** 지원

### 🎮 버튼 템플릿 시스템 (Stage Response)

#### 컴포넌트 구조
`StageResponse.vue`가 백엔드의 stage_response 메시지를 처리하여 사용자에게 버튼 선택지를 제공합니다.

#### 응답 타입별 UI 렌더링
```typescript
// types/stageResponse.ts
export type ResponseType = 'narrative' | 'bullet' | 'boolean'

// narrative: 자유 텍스트 입력 (버튼 없음)
// bullet: 단일 선택 버튼
// boolean: 다중 선택 토글 스위치
```

#### 버튼 선택지 구조
```typescript
// 단순 선택지
interface Choice {
  value?: string      // 실제 값
  label: string       // 표시 텍스트
  display?: string    // 대체 표시 텍스트
  default?: boolean   // 기본 선택 여부
}

// 그룹화된 선택지
interface ChoiceGroup {
  title: string       // 그룹 제목
  items: Choice[]     // 그룹 내 선택지들
}
```

#### 사용자 선택 처리
```vue
<!-- StageResponse.vue -->
<button 
  v-for="choice in choices"
  @click="selectChoice(choice.value, choice.display)"
  :class="{ 'selected': isSelectedChoice(choice) }"
>
  {{ choice.display || choice.label }}
</button>
```

#### WebSocket 메시지 흐름
1. **서버 → 클라이언트**: stage_response 메시지 수신
2. **UI 렌더링**: 응답 타입에 따른 버튼/토글 표시
3. **사용자 선택**: 버튼 클릭 또는 토글 변경
4. **클라이언트 → 서버**: 선택 결과 전송

#### 성능 최적화 (`slotFillingStore.ts`)
```typescript
// 디바운싱으로 불필요한 업데이트 방지
const UPDATE_DEBOUNCE_MS = 100

// 캐시 시스템으로 메모리 효율성
const fieldVisibilityCache = new Map<string, boolean>()

// 중복 업데이트 방지
const calculateUpdateHash = (message: SlotFillingUpdate): string => {...}
```

#### 계층적 필드 구조
```json
{
  "key": "field_name",
  "display_name": "필드명",
  "type": "text|choice|number|boolean",
  "depth": 0,  // 계층 깊이
  "show_when": "parent_field == 'value'",  // 조건부 표시
  "parent_field": "parent_field_key"
}
```

### 🔍 Slot Filling 디버깅 시스템

#### `SlotFillingDebug.vue` 주요 기능
- **실시간 개체 수집 상태** 모니터링
- **필드별 상세 정보 테이블** (키, 타입, 값, 완료 상태)
- **수집된 정보 Raw 데이터** JSON 표시
- **업데이트 히스토리 추적** (최근 10개 변경사항)
- **토글 버튼**을 통한 디버그 패널 제어
- **개발 환경 전용** 상세 로그 출력

#### 사용법
```vue
<template>
  <SlotFillingDebug 
    v-if="isDevelopment" 
    :slotFillingState="slotFillingStore.getState"
  />
</template>
```

## 🛠️ 개발 가이드

### 새 컴포넌트 개발 패턴
```vue
<template>
  <div class="component-wrapper">
    <!-- 템플릿 -->
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import type { ComponentProps } from '@/types/component'

// Props 정의
interface Props {
  data: ComponentProps
}
const props = defineProps<Props>()

// 반응형 상태
const isLoading = ref(false)
const computedValue = computed(() => props.data.value)

// 라이프사이클
onMounted(() => {
  // 초기화 로직
})
</script>

<style scoped>
.component-wrapper {
  /* 스타일 */
}
</style>
```

### Pinia Store 패턴
```typescript
export const useCustomStore = defineStore('custom', () => {
  // State
  const state = ref<CustomState>()
  
  // Getters  
  const computedData = computed(() => state.value?.data)
  
  // Actions
  const updateData = (newData: CustomData) => {
    state.value = { ...state.value, data: newData }
  }
  
  return {
    // State
    state,
    // Getters
    computedData, 
    // Actions
    updateData
  }
})
```

### Backend 통신 패턴
```typescript
// services/api.ts
export const apiService = {
  async sendMessage(message: string): Promise<ChatResponse> {
    const response = await fetch('/api/v1/chat/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message })
    })
    return response.json()
  }
}
```

## 🎨 UI/UX 최적화

### 반응형 디자인
- **모바일 퍼스트** 접근법
- **CSS Grid/Flexbox** 기반 레이아웃
- **Viewport 단위** 사용 (vw, vh, vmin, vmax)

### 접근성 (Accessibility)
```vue
<template>
  <!-- ARIA 라벨링 -->
  <button 
    :aria-label="buttonLabel"
    :aria-expanded="isExpanded"
    role="button"
  >
    {{ buttonText }}
  </button>
  
  <!-- 키보드 네비게이션 -->
  <div 
    tabindex="0"
    @keydown.enter="handleEnter"
    @keydown.space="handleSpace"
  >
    <!-- 내용 -->
  </div>
</template>
```

### 성능 최적화 전략
- **v-memo** 지시문으로 렌더링 최적화
- **defineAsyncComponent**로 코드 스플리팅
- **computed 캐싱** 활용
- **이벤트 디바운싱/스로틀링**

## 🧪 테스트

### 단위 테스트 작성
```typescript
// components/__tests__/Component.spec.ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import Component from '../Component.vue'

describe('Component', () => {
  it('renders properly', () => {
    const wrapper = mount(Component, { 
      props: { message: 'Hello' } 
    })
    expect(wrapper.text()).toContain('Hello')
  })
})
```

### 테스트 실행
```bash
# 단위 테스트
npm run test:unit

# 테스트 커버리지
npm run test:coverage

# 테스트 감시 모드
npm run test:watch
```

## 🚀 빌드 및 배포

### 개발 빌드
```bash
npm run build:dev
```

### 프로덕션 빌드
```bash
npm run build
```

### 타입 검사
```bash
npm run type-check
```

### 린팅
```bash
npm run lint
npm run lint:fix  # 자동 수정
```

## 🔧 개발 도구

### VS Code 확장 프로그램
- **Volar**: Vue 3 공식 확장
- **TypeScript Vue Plugin**: TS 지원
- **ESLint**: 코드 품질
- **Prettier**: 코드 포맷팅

### 디버깅
- **Vue DevTools**: 컴포넌트 상태 디버깅
- **SlotFillingDebug**: 실시간 데이터 모니터링
- **Chrome DevTools**: 네트워크, 성능 분석

## 🚨 코드 품질 가이드

### TypeScript 사용 규칙
```typescript
// 타입 정의 우선
interface User {
  id: number
  name: string
  email?: string  // 옵셔널 속성
}

// any 타입 지양, unknown 사용
const data: unknown = fetchData()

// 타입 가드 활용
function isUser(obj: unknown): obj is User {
  return typeof obj === 'object' && obj !== null && 'id' in obj
}
```

### 네이밍 컨벤션
- **컴포넌트**: PascalCase (`SlotFillingPanel.vue`)
- **변수/함수**: camelCase (`updateSlotFilling`)
- **상수**: UPPER_SNAKE_CASE (`MAX_RETRY_COUNT`)
- **타입/인터페이스**: PascalCase (`SlotFillingState`)

## 📚 개발 완료 후

```bash
# 변경사항 검증
npm run type-check
npm run lint
npm run test:unit

# 커밋
git add .
git commit -m "feat: 기능 설명"

# 푸시
git push origin main
```

## 📖 관련 문서

- [메인 개발 가이드](../CLAUDE.md) - 프로젝트 전반적인 개발 규칙
- [Backend 개발 가이드](../backend/CLAUDE.md) - API 연동 및 데이터 플로우
- [Nginx 설정 가이드](../nginx/CLAUDE.md) - 프로덕션 배포 설정
- [Vue 3 공식 문서](https://vuejs.org/) - Vue 3 및 Composition API
- [Pinia 공식 문서](https://pinia.vuejs.org/) - 상태 관리 가이드