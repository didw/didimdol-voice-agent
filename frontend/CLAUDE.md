# Frontend 개발 가이드

**심플하게 작성하세요. 핵심만 전달하세요.**

## 역할

디딤돌 음성 상담 에이전트의 **웹 UI** - 음성 기반 금융 상담 인터페이스

## 개발 시작

### 1. Git Pull (필수)
```bash
git pull origin main
```

### 2. 서버 실행
```bash
npm install
npm run dev
```

## 주요 라이브러리

- **Vue 3**: UI 프레임워크 (Composition API)
- **TypeScript**: 타입 안정성
- **Vite**: 빌드 도구
- **Pinia**: 상태 관리 (Chat + Slot Filling)
- **Web Audio API**: 음성 처리
- **Vitest**: 테스트

## 새로운 기능

### Slot Filling Panel
- 실시간 정보 수집 현황 표시
- 진행률 바 및 애니메이션
- 모바일 스와이프 제스처 지원
- 접근성 최적화 (ARIA, 키보드 네비게이션)

### Slot Filling 디버깅 시스템
- `SlotFillingDebug.vue`: 실시간 개체 수집 상태 모니터링
- 필드별 상세 정보 테이블 (키, 타입, 값, 완료 상태)
- 수집된 정보 Raw 데이터 표시
- 업데이트 히스토리 추적 (최근 10개)
- 토글 버튼을 통한 디버그 패널 제어
- 개발 환경에서 상세 로그 출력

## 테스트

```bash
# 단위 테스트
npm run test:unit
```

## 개발 완료 후

```bash
git add .
git commit -m "작업 설명"
git push origin main
```

## 관련 문서

- [메인 개발 가이드](../CLAUDE.md)
- [Backend 개발 가이드](../backend/CLAUDE.md)
- [Nginx 설정 가이드](../nginx/CLAUDE.md)