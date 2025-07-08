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

- **Vue 3**: UI 프레임워크
- **TypeScript**: 타입 안정성
- **Vite**: 빌드 도구
- **Pinia**: 상태 관리
- **Web Audio API**: 음성 처리
- **Vitest**: 테스트

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