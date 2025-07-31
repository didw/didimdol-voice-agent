# Changelog

## [2025-07-31] - V3 시나리오 자연어 처리 및 오타 처리 개선

### ✨ 새로운 기능
- **LLM 기반 자연어 응답 처리**
  - "다 해줘", "전부" 등 다양한 표현을 올바른 선택지로 매핑
  - `map_user_intent_to_choice` 함수로 유연한 의도 매핑 구현
  - 키워드 기반 매칭과 LLM 기반 의미 매칭 결합

- **시나리오 유도 응답 생성**
  - 무관한 발화나 오타 입력 시 자연스러운 시나리오 유도
  - `generate_natural_response` 함수로 상황별 맞춤 응답 생성
  - 시나리오 이탈 감지 및 적절한 안내 제공

- **필수 필드 검증 강화**
  - V3 시나리오에서 필수 필드 미수집 시 다음 단계 진행 차단
  - `security_medium` 등 중요 필드 수집 전 단계 이동 방지
  - 오타나 무관한 입력 시 현재 단계 유지

- **애매한 지시어 처리**
  - "그걸로", "그것으로", "그거" 등 애매한 지시어 자동 감지
  - 구체적인 선택지 제시로 사용자 선택 유도
  - 그룹별 선택지 정리 및 메타데이터 정보 표시 (이체한도, 수수료 등)

### 🔧 개선사항
- V3 시나리오 `next_step` 처리 로직 개선
- 필수 필드 수집 여부 검증 로직 추가
- 시나리오 이탈 시 유도 응답 생성 로직 구현
- 애매한 지시어 감지 및 선택지 명확화 로직 구현
- LLM 호출 에러 처리 개선

### 📝 주요 코드 변경
- `scenario_logic.py`: 
  - `map_user_intent_to_choice` 함수 추가
  - `generate_natural_response` 함수 추가
  - `generate_choice_clarification_response` 함수 추가
  - V3 시나리오 필수 필드 검증 로직 강화
  - 시나리오 이탈 처리 로직 구현
  - 애매한 지시어 감지 및 명확화 유도 로직 구현

## [2025-07-17] - 고급 Slot Filling 시스템 구현

### ✨ 새로운 기능
- **계층적 필드 표시 시스템**
  - `show_when` 표현식 기반 조건부 필드 표시
  - `parent_field`를 통한 자동 계층 구조 생성
  - 깊이별 시각적 구분 (들여쓰기, 색상, 테두리)
  - 실시간 조건 평가 및 동적 UI 업데이트

- **Default 값 자동 처리**
  - 조건을 만족하는 필드의 default 값 자동 수집
  - Default 값이 있는 필드는 즉시 완료 상태로 표시
  - 사용자 입력과 동일하게 처리 (이탤릭 스타일 제거)

### 🏗️ 아키텍처 변경
- **Backend 조건 평가 엔진**
  - `evaluate_show_when()`: 표현식 기반 조건 평가
  - `get_visible_fields_with_hierarchy()`: 계층적 필드 계산
  - `calculate_field_depth()`: 자동 깊이 계산
  - 모든 복잡한 로직을 Backend에서 중앙 처리

- **Frontend 단순화**
  - Backend에서 계산된 visibility 정보만 렌더링
  - 복잡한 조건 로직 제거
  - 성능 최적화 (캐싱, 디바운싱)

### 📝 지원 표현식
- `field == value`: 특정 값 비교
- `field != null`: 값 존재 여부
- `condition1 && condition2`: AND 연산
- `condition1 || condition2`: OR 연산

### 🎯 구현 예시
```json
{
  "key": "security_medium",
  "show_when": "use_internet_banking == true",
  "parent_field": "use_internet_banking",
  "default": "신한 OTP"
}
```

### 🔧 개선사항
- 실시간 필드 업데이트 시 부모-자식 관계 자동 처리
- WebSocket을 통한 효율적인 상태 동기화
- 메모리 누수 방지 및 성능 최적화
- 타입 안정성 강화 (TypeScript)

### 📱 사용자 경험
- 선택에 따라 관련 필드만 표시되어 혼란 감소
- 계층 구조로 논리적 관계 시각화
- Default 값 자동 입력으로 입력 부담 감소
- 부드러운 애니메이션과 직관적인 UI

## [2025-07-17] - Step-based Slot Filling 개선

### ✨ 새로운 기능
- **단계별 슬롯필링 표시**
  - 현재 시나리오 단계에 해당하는 필드 그룹만 표시
  - 사용자 인지 부하 감소 및 UX 개선
  - 대상 시나리오: deposit_account (입출금통장 신규)

### 🏗️ 아키텍처 변경
- **데이터 기반 설계**
  - 시나리오 JSON에 `visible_groups` 속성 추가
  - 하드코딩 제거 및 유연한 시나리오 확장 구조
- **Backend 함수 추가**
  - `get_stage_visible_groups()`: 시나리오 데이터 기반 그룹 매핑
  - `initialize_default_values()`: default 값 자동 설정 및 완료 처리
- **Frontend 타입 확장**
  - `CurrentStageInfo` 타입 추가
  - `visibleFieldGroups` computed로 step-based 필터링

### 🔧 개선사항
- **자동 Default 값 처리**
  - 시나리오 시작 시 default 값 자동 입력
  - default 값이 있는 필드 자동 완료 상태 표시
- **UI/UX 개선**
  - 현재 스테이지 정보 표시
  - 현재 단계 필드 시각적 강조
  - "현재 단계" 배지 및 애니메이션 효과
- **호환성 보장**
  - 기존 시스템과 100% 호환
  - Fallback 로직으로 기존 방식 지원

### 📱 사용자 경험
- **단계별 집중**: 현재 필요한 정보만 표시하여 혼란 방지
- **진행 상황 인식**: 어떤 단계에 있는지 명확하게 표시
- **자동 완료**: 기본값이 있는 필드는 자동으로 완료 처리

### 🎯 구현 범위
- **deposit_account_scenario** 4단계 매핑:
  - `greeting`: 기본 정보 (basic_info)
  - `ask_lifelong_account`: 계좌 설정 (account_settings)
  - `collect_internet_banking_info`: 인터넷뱅킹 (internet_banking)
  - `collect_check_card_info`: 체크카드 (check_card)
  - `final_summary`: 전체 정보 확인

## [2025-07-16] - 환경 분리 및 WebSocket 설정 개선

### ✨ 새로운 기능
- **로컬/프로덕션 환경 분리**
  - `LOCAL_SETUP.md`: 환경별 설정 가이드 추가
  - `.env.example` 템플릿 파일 제공
  - 포트 설정 분리 (로컬: 8001, 프로덕션: 8000)

### 🔧 개선사항
- **nginx WebSocket 프록시 설정**
  - 중첩 location 블록 제거로 설정 단순화
  - WebSocket 전용 설정 추가 (buffering off, cache off)
  - 정적 파일 서빙으로 성능 향상
- **CORS 설정 업데이트**
  - `aibranch.zapto.org` 도메인 추가
  - 환경별 도메인 지원
- **문서 개선**
  - CLAUDE.md: 개발 가이드 중심으로 재구성
  - Git 브랜치 전략 및 코드 품질 가이드 추가

### 🐛 버그 수정
- WebSocket 연결 오류 (Error 1006) 해결
- nginx 권한 문제 (Permission denied) 수정
- 프론트엔드 TypeScript 타입 오류 수정
- 환경 변수 불일치 문제 해결

### 🗑️ 제거됨
- 임시 테스트 파일 및 불필요한 문서
- HTML 커버리지 리포트 (htmlcov/)

## [2025-07-16] - Entity Agent 및 아키텍처 개선

### ✨ 새로운 기능
- **Entity Agent 시스템**
  - LLM 기반 지능형 개체 추출
  - 시나리오별 extraction_prompt 필드
  - 키워드 매칭 방식 대체
- **Slot Filling 디버깅 도구**
  - SlotFillingDebug.vue 컴포넌트
  - 실시간 개체 수집 상태 모니터링
  - WebSocket 메시지 추적

### 🏗️ 아키텍처 변경
- **Orchestration-Worker 패턴**
  - 메인 Orchestrator와 특화 Worker 분리
  - scenario_worker, rag_worker, web_worker
  - direct_response 필드로 즉시 응답 지원

### 🔧 개선사항
- 통합 테스트 스위트 구축
- 프롬프트 관리 시스템 개선
- 디렉토리 구조 정리 (archive 폴더 활용)

## [2024-07-15] - Slot Filling System 구현

### ✨ 새로운 기능

#### Backend
- **Slot Filling 시스템** 구현
  - 실시간 정보 수집 상태 추적
  - WebSocket을 통한 Frontend 업데이트
  - 시나리오별 필드 그룹화 지원
  - 조건부 필드 의존성 처리
- **WebSocket 메시지 타입 추가**
  - `slot_filling_update` 메시지 타입
  - 변경 감지 및 최적화된 업데이트

#### Frontend
- **SlotFillingPanel 컴포넌트** 구현
  - 실시간 정보 수집 현황 표시
  - 진행률 바 및 고급 애니메이션
  - 필드 그룹화 및 조건부 표시
- **모바일 UX 최적화**
  - 스와이프 제스처 지원
  - 반응형 레이아웃 (데스크톱/태블릿/모바일)
  - 오버레이 및 슬라이드 애니메이션
- **접근성 개선**
  - ARIA 속성 추가
  - 키보드 네비게이션 지원
  - 스크린 리더 호환성

### 🔧 개선사항
- 상태 관리 구조 개선 (Pinia Store 분리)
- TypeScript 타입 정의 강화
- 에러 처리 및 로깅 개선
- 성능 최적화 (불필요한 업데이트 방지)

### 📱 사용자 경험
- 대화 중 수집된 정보를 실시간으로 확인 가능
- 모바일에서 직관적인 스와이프 제스처
- 부드러운 애니메이션과 시각적 피드백
- 완료된 필드와 미완료 필드 구분 표시

### 🏗️ 기술 스택
- **Backend**: FastAPI + LangGraph + WebSocket
- **Frontend**: Vue 3 (Composition API) + TypeScript + Pinia
- **UI/UX**: CSS Grid + Flexbox + CSS Animation