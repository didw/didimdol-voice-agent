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

## 주요 개선사항

### Orchestration-Worker 아키텍처
- `app/graph/agent.py`: LLM 기반 Orchestrator와 특화된 Worker들
- 메인 에이전트가 모든 대화를 LLM으로 처리 (룰 기반 제거)
- Worker: scenario_worker, rag_worker, web_worker

### Product ID 매핑
- `didimdol`: 디딤돌 대출
- `jeonse`: 전세 대출
- `deposit_account`: 입출금통장

### 로깅 시스템
- 노드 실행 추적: `🔄 [NodeName] input → output`
- Agent Flow 시작/종료 표시
- Slot Filling 업데이트 추적

### 프롬프트 관리
- `app/config/main_agent_prompts.yaml`: 메인 에이전트 프롬프트
  - `business_guidance_prompt`: 일반 상담 모드
  - `task_management_prompt`: 특정 제품 상담 모드

### 시나리오 연속성
- 시나리오 진행 중 사용자 응답 대기 상태 자동 관리
- `scenario_ready_for_continuation` 플래그로 자동 진행

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