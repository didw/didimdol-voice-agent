# 디딤돌 음성 상담 에이전트 개발 가이드

**이 문서를 심플하게 유지하세요. 복잡한 설명보다는 핵심에 집중하세요.**

## 프로젝트 개요

**디딤돌 음성 상담 에이전트** - 한국 금융 대출 상담을 위한 실시간 음성 AI 시스템

- **Backend**: Python, FastAPI, LangGraph
- **Frontend**: Vue.js, Vite, TypeScript  
- **주요 서비스**: OpenAI (LLM), Google Cloud (STT/TTS), LanceDB (RAG), Tavily (검색)

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
uvicorn app.main:app --reload --port 8000
```

**Frontend**
```bash
cd frontend
npm install
npm run dev
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

## 구조 개선사항

### 정리된 프로젝트 구조
- `backend/app/agents/`: 핵심 에이전트만 유지, 미사용 파일은 archive/ 폴더로 이동
- `backend/app/api/V1/`: 중복 API 파일 통합 및 리팩토링
- `backend/app/config/`: 모든 설정 및 프롬프트 파일 통합
- `backend/tests/`: 모든 테스트 파일을 tests/ 디렉토리로 통합
- `docs/design/`: PRD 및 설계 문서 별도 관리

## 추가 문서

- [Backend 개발 가이드](backend/CLAUDE.md)
- [Frontend 개발 가이드](frontend/CLAUDE.md)
- [Nginx 설정 가이드](nginx/CLAUDE.md)
- [테스트 가이드](README_TESTING.md)
- [설계 문서](docs/design/)
