# Backend 개발 가이드

**심플하게 작성하세요. 핵심만 전달하세요.**

## 역할

디딤돌 음성 상담 에이전트의 **백엔드 서버** - AI 대화 처리 및 API 제공

## 개발 시작

### 1. Git Pull (필수)
```bash
git pull origin main
```

### 2. 환경 설정
`.env` 파일 생성:
```env
OPENAI_API_KEY=your_openai_api_key
GOOGLE_APPLICATION_CREDENTIALS=/path/to/google-credentials.json
```

### 3. 서버 실행
```bash
# 가상환경 활성화
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# 서버 실행
uvicorn app.main:app --reload --port 8000
```

## 주요 라이브러리

- **FastAPI**: API 서버 및 WebSocket
- **LangGraph**: 대화 흐름 관리 및 Slot Filling
- **LangChain**: LLM 통합
- **LanceDB**: 벡터 검색 (RAG)
- **Google Cloud**: STT/TTS
- **Tavily**: 웹 검색

## 구조 개선사항

### 정리된 디렉토리 구조
- `app/agents/`: 핵심 에이전트 (entity_agent, unified_main_agent)
- `app/agents/archive/`: 미사용 에이전트 보관
- `app/api/V1/`: 리팩토링된 API 엔드포인트
- `app/config/`: 통합된 설정 및 프롬프트 파일
- `tests/`: 모든 테스트 파일 통합
- `docs/design/`: PRD 및 설계 문서

### Slot Filling 시스템
- 실시간 정보 수집 상태 추적
- WebSocket을 통한 Frontend 업데이트
- 시나리오별 필드 그룹화 지원

## 테스트

```bash
# 가상환경 활성화
source venv/bin/activate

# 테스트 의존성 설치
pip install -r requirements-test.txt

# 단위 테스트
python test_runner.py unit

# 커버리지 포함 전체 테스트
python test_runner.py coverage
```

## 개발 완료 후

```bash
git add .
git commit -m "작업 설명"
git push origin main
```

## 관련 문서

- [메인 개발 가이드](../CLAUDE.md)
- [Frontend 개발 가이드](../frontend/CLAUDE.md)
- [테스트 가이드](../README_TESTING.md)