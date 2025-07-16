# 디딤돌 음성 상담 에이전트 개발 가이드

**이 문서는 개발자를 위한 핵심 가이드입니다. 심플하고 명확하게 유지하세요.**

## 프로젝트 개요

**디딤돌 음성 상담 에이전트** - 한국 금융 대출 상담을 위한 실시간 음성 AI 시스템

- **Backend**: Python, FastAPI, LangGraph
- **Frontend**: Vue.js, Vite, TypeScript  
- **주요 서비스**: OpenAI (LLM), Google Cloud (STT/TTS), LanceDB (RAG), Tavily (검색)

## 개발 규칙

### 1. Git 브랜치 전략
```bash
# 기능 개발 시 브랜치 생성
git checkout -b feature/feature-name

# 개발 완료 후 main 브랜치에 머지
git checkout main
git merge feature/feature-name
```

### 2. 코드 수정 원칙
- 파일 수정 시 접미사(_v2, _new 등) 사용 금지
- 기존 파일을 직접 수정하거나 브랜치 사용
- 임시 파일 생성 최소화

## 개발 시작하기

### 1. 개발 전 필수사항
```bash
# 항상 최신 코드를 받아오세요
git pull origin main
```

### 2. 환경 설정

**Backend (.env 파일을 backend/ 디렉토리에 생성)**
```env
OPENAI_API_KEY=your_openai_api_key
GOOGLE_APPLICATION_CREDENTIALS=/path/to/google-credentials.json
```

### 3. 개발 서버 실행

**Backend**
```bash
cd backend
pip install -r requirements.txt
# 로컬 개발 (포트 충돌 시)
uvicorn app.main:app --reload --port 8001
```

**Frontend**
```bash
cd frontend
npm install
npm run dev  # .env.development 설정 사용
```

**전체 실행**
```bash
./scripts/run_dev.sh
```

## 주요 라이브러리

### Backend
- **FastAPI**: REST API 및 WebSocket 서버
- **LangGraph**: 대화 흐름 관리 및 Slot Filling
- **LangChain**: LLM 통합
- **LanceDB**: 벡터 검색
- **pytest**: 테스트

### Frontend
- **Vue 3**: UI 프레임워크 (Composition API)
- **Pinia**: 상태 관리 (Slot Filling Store)
- **TypeScript**: 타입 안정성
- **Vite**: 빌드 도구
- **Vitest**: 테스트

## 테스트 실행

### Backend 테스트
```bash
cd backend
pip install -r requirements-test.txt

# 단위 테스트
python test_runner.py unit

# 전체 테스트 (커버리지 포함)
python test_runner.py coverage
```

### Frontend 테스트
```bash
cd frontend
npm run test:unit
```

### 통합 테스트
```bash
# 프로젝트 루트에서
python test_runner.py integration
```

## 개발 후 필수사항

```bash
# 변경사항 커밋
git add .
git commit -m "작업 내용 설명"

# 원격 저장소에 푸시
git push origin main
```

## 프로젝트 구조

### 디렉토리 구조
```
├── backend/
│   ├── app/
│   │   ├── agents/         # AI 에이전트
│   │   ├── api/V1/         # API 엔드포인트
│   │   ├── config/         # 설정 파일
│   │   ├── data/           # 시나리오 및 지식베이스
│   │   └── graph/          # LangGraph 워크플로우
│   └── tests/              # 테스트 파일
├── frontend/
│   ├── src/
│   │   ├── components/     # Vue 컴포넌트
│   │   ├── stores/         # Pinia 상태 관리
│   │   └── types/          # TypeScript 타입
│   └── dist/               # 빌드 결과물 (gitignore)
└── nginx/                  # 프로덕션 설정
```

## 개발 모범 사례

### 1. 환경 변수 관리
- `.env` 파일은 절대 커밋하지 않기
- `.env.example` 파일로 템플릿 제공
- 로컬/프로덕션 환경 분리

### 2. 테스트
```bash
# 백엔드 테스트
cd backend
python test_runner.py unit

# 프론트엔드 테스트
cd frontend
npm run test:unit
```

### 3. 커밋 메시지
- 명확하고 간결하게 작성
- 예: `feat: Add WebSocket reconnection logic`
- 예: `fix: Resolve CORS issue for production`

## 추가 문서

- [Backend 개발 가이드](backend/CLAUDE.md)
- [Frontend 개발 가이드](frontend/CLAUDE.md)
- [로컬 환경 설정](LOCAL_SETUP.md)
- [테스트 가이드](README_TESTING.md)
