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
# 로컬 개발 (포트 충돌 시)
uvicorn app.main:app --reload --port 8001

# 프로덕션 (표준 포트)
uvicorn app.main:app --reload --port 8000
```

## 주요 라이브러리

- **FastAPI**: API 서버 및 WebSocket
- **LangGraph**: 대화 흐름 관리 및 Slot Filling
- **LangChain**: LLM 통합
- **LanceDB**: 벡터 검색 (RAG)
- **Google Cloud**: STT/TTS
- **Tavily**: 웹 검색

## 아키텍처 및 주요 기능

### Orchestration-Worker 아키텍처
- `app/graph/agent.py`: 메인 Orchestrator와 Worker들
- Workers: scenario_worker, rag_worker, web_worker
- direct_response 필드를 통한 즉시 응답

### 🆕 모듈화된 노드 구조 (2025-07-17)
```
app/graph/nodes/
├── orchestrator/
│   ├── entry_point.py      # 진입점 노드
│   └── main_router.py      # 메인 라우터
├── workers/
│   ├── scenario_agent.py   # 시나리오 에이전트 노드
│   ├── scenario_logic.py   # 시나리오 로직 처리
│   ├── scenario_helpers.py # 시나리오 헬퍼 함수들
│   ├── rag_worker.py       # RAG 검색 워커
│   └── web_worker.py       # 웹 검색 워커
└── control/
    ├── synthesize.py       # 응답 합성
    ├── set_product.py      # 상품 설정
    └── end_conversation.py # 대화 종료
```

### 🆕 Pydantic 상태 관리 시스템
- `app/graph/state.py`: AgentState, ScenarioAgentOutput (Pydantic BaseModel)
- 타입 안전성 및 validation 강화
- LangGraph 호환성을 위한 dict-like 인터페이스 제공

### Entity Agent
- `app/agents/entity_agent.py`: LLM 기반 개체 추출
- 시나리오 JSON의 `extraction_prompt` 필드 활용

### Product ID
- `didimdol`: 디딤돌 대출
- `jeonse`: 전세 대출
- `deposit_account`: 입출금통장

### 설정 파일
- `app/config/main_agent_prompts.yaml`: 에이전트 프롬프트
- `app/config/service_descriptions.yaml`: 서비스 설명
- `app/data/scenarios/`: 시나리오 JSON 파일

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

## 코드 품질 가이드

### 1. 파일 수정 원칙
- 파일명에 접미사 (_v2, _new, _temp) 금지
- 기존 파일 직접 수정 또는 브랜치 사용

### 2. 로깅
- 노드 실행: `🔄 [NodeName] input → output`
- 중요 이벤트만 로깅
- 개발 환경에서만 DEBUG 레벨 사용

### 3. 예외 처리
- 모든 API 엔드포인트에 try-except 추가
- 사용자 친화적 에러 메시지 반환

## 개발 완료 후

```bash
# 기능 브랜치에서 작업
git add .
git commit -m "feat: 기능 설명"
git push origin feature/branch-name

# PR 생성 후 리뷰 요청
```

## 관련 문서

- [메인 개발 가이드](../CLAUDE.md)
- [Frontend 개발 가이드](../frontend/CLAUDE.md)
- [테스트 가이드](../README_TESTING.md)