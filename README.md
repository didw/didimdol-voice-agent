# 디딤돌 음성 상담 에이전트 프로젝트

## 프로젝트 개요

본 프로젝트는 웹에서 작동하는 디딤돌 주택담보대출 상담 서비스 데모 페이지를 개발합니다. chatGPT 음성봇과 유사한 음성 인터페이스(EPD, Barge-in 지원)를 제공하며, 사용자의 발화와 AI의 LLM 응답을 실시간으로 화면에 출력하고 TTS를 재생합니다.

### 주요 기술 스택

- **Frontend**: Vue.js (Vite)
- **Backend**: Python (FastAPI, LangGraph)
- **LLM**: OpenAI API
- **STT/TTS**: Google Cloud STT/TTS API
- **Communication**: REST API 및 WebSocket

### 주요 기능

- 음성 기반 대출 상담 인터페이스
- 실시간 발화 및 응답 텍스트/음성 출력
- **실시간 Slot Filling 패널** - 수집된 정보 시각화
- 디딤돌 대출 관련 QA (제공된 `didimdol.md` 기반)
- **단계별 Slot Filling** 지원 - 시나리오 단계별 필요한 필드 그룹만 표시
- 다양한 주제에 대한 자유 대화
- 모바일 최적화 (스와이프 제스처, 반응형 UI)

## 실행 방법

### 로컬 개발 환경

1. **환경 설정**: `LOCAL_SETUP.md` 참고
2. **Backend 실행**: 
   ```bash
   cd backend
   uvicorn app.main:app --reload --port 8001
   ```
   - 기본 포트: 8000 (사용 중인 경우 8001 등으로 변경 가능)
   
3. **Frontend 실행**:
   ```bash
   cd frontend
   npm run dev
   ```
   - `.env.development.example`을 `.env.development`로 복사하여 사용
   - 백엔드 포트를 변경했다면 `.env.development` 파일의 포트 번호도 수정

### 프로덕션 환경
- nginx 설정 및 빌드 배포: `LOCAL_SETUP.md` 참고

## 데이터 파일

- 디딤돌 대출 상담 시나리오: `backend/app/data/scenarios/didimdol_loan_scenario.json`
- 전세 대출 상담 시나리오: `backend/app/data/scenarios/jeonse_loan_scenario.json`
- 입출금통장 상담 시나리오: `backend/app/data/scenarios/deposit_account_scenario.json`
- 디딤돌 대출 QA 지식베이스: `backend/app/data/kb/didimdol.md`
- 서비스 설명 정보: `backend/app/config/service_descriptions.yaml`
- 개체 추출 에이전트: `backend/app/agents/entity_agent.py`

**참고**: 시나리오 JSON 파일의 각 필드에 `extraction_prompt` 필드가 추가되어 LLM 기반 개체 추출을 지원합니다.

## 🧪 테스팅

프로젝트는 포괄적인 테스트 스위트를 제공합니다:

### 빠른 테스트 실행

```bash
# 테스트 의존성 설치
pip install -r requirements-test.txt

# 빠른 테스트 실행
python test_runner.py quick

# 전체 테스트 스위트
python test_runner.py all
```

### 테스트 유형

- **단위 테스트** (`backend/tests/`) - 에이전트 라우팅, RAG, 서비스 모듈
- **통합 테스트** (`tests/`) - 완전한 대화 플로우, API 엔드포인트
- **E2E 테스트** - 전체 시스템 시나리오
- **성능 테스트** - 동시 사용자 및 부하 테스트

### 커버리지 목표

- 백엔드 단위 테스트: **80%** 이상
- 통합 테스트: **70%** 이상

자세한 테스트 가이드는 [README_TESTING.md](README_TESTING.md)를 참조하세요.
