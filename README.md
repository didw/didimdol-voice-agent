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
- 디딤돌 대출 관련 QA (제공된 `didimdol.md` 기반)
- 정의된 시나리오(`loan_scenario.json`)에 따른 단계별 정보 요청
- 다양한 주제에 대한 자유 대화

## 실행 방법

1.  **Backend 설정 및 실행**: `backend/README.md` 참고
2.  **Frontend 설정 및 실행**: `frontend/README.md` 참고
3.  개발 환경 동시 실행: `scripts/run_dev.sh` 스크립트 사용 (필요시 경로 및 명령어 수정)

## 데이터 파일

- 대출 상담 시나리오: `backend/app/data/loan_scenario.json`
- 디딤돌 대출 QA 지식베이스: `backend/app/data/didimdol.md`
