# 백엔드 (Python FastAPI & LangGraph)

## 개발 환경 설정

1.  **Python 3.12 설치**
2.  **가상 환경 생성 및 활성화**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # Linux/macOS
    # 또는
    # .\venv\Scripts\activate  # Windows
    ```
3.  **의존성 설치**:
    ```bash
    pip install -r requirements.txt
    ```
4.  **.env 파일 설정**:
    - `.env.example` 파일을 복사하여 `.env` 파일을 생성합니다.
    - `OPENAI_API_KEY`에 OpenAI API 키를 입력합니다.
    - `GOOGLE_APPLICATION_CREDENTIALS`에 Google Cloud 서비스 계정 키 JSON 파일의 절대 경로를 입력합니다.
      ([Google Cloud 서비스 계정 키 생성 가이드](https://cloud.google.com/iam/docs/creating-managing-service-account-keys))

## 실행

Uvicorn을 사용하여 FastAPI 애플리케이션을 실행합니다.

```bash
uvicorn app.main:app --reload --port 8000
```

(--reload는 개발 시 유용하며, 파일 변경 시 서버를 자동으로 재시작합니다.)

## 주요 라이브러리

- FastAPI (웹 프레임워크)
- Uvicorn (ASGI 서버)
- Langchain & LangGraph (LLM 애플리케이션 프레임워크)
- OpenAI Python Client
- Google Cloud Python Client (Speech-to-Text, Text-to-Speech)
- Pydantic (데이터 유효성 검사)
- python-dotenv (환경 변수 관리)
- websockets (FastAPI WebSocket 지원)

<!-- end list -->
