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
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## 주요 라이브러리

- **FastAPI**: API 서버 및 WebSocket
- **LangGraph**: 대화 흐름 관리
- **LangChain**: LLM 통합
- **LanceDB**: 벡터 검색 (RAG)
- **Google Cloud**: STT/TTS
- **Tavily**: 웹 검색

## 시나리오 구조

- `app/data/scenarios/`: 대화 시나리오 JSON 파일
- `app/data/docs/`: 지식베이스 MD 파일
- 개선된 다중 정보 수집 방식 지원

## 테스트

```bash
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