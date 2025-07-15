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
- 정의된 시나리오에 따른 단계별 정보 요청
- 다양한 주제에 대한 자유 대화
- 모바일 최적화 (스와이프 제스처, 반응형 UI)

## 실행 방법

1.  **Backend 설정 및 실행**: `backend/README.md` 참고
2.  **Frontend 설정 및 실행**: `frontend/README.md` 참고
3.  개발 환경 동시 실행: `scripts/run_dev.sh` 스크립트 사용 (필요시 경로 및 명령어 수정)

## 데이터 파일

- 대출 상담 시나리오: `backend/app/data/loan_scenario.json`
- 디딤돌 대출 QA 지식베이스: `backend/app/data/didimdol.md`

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
