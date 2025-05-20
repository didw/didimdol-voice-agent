from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.V1 import chat as chat_router_v1
from .core.config import OPENAI_API_KEY, GOOGLE_APPLICATION_CREDENTIALS
import os

app = FastAPI(title="Didimdol Voice Agent API")

# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], # 개발 프론트엔드 주소
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    print("애플리케이션 시작...")
    if not OPENAI_API_KEY:
        print("경고: OPENAI_API_KEY가 설정되지 않았습니다.")
    if not GOOGLE_APPLICATION_CREDENTIALS or not os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
        print(f"경고: GOOGLE_APPLICATION_CREDENTIALS 경로가 유효하지 않거나 파일이 없습니다: {GOOGLE_APPLICATION_CREDENTIALS}")
    else:
        print(f"Google Cloud Credentials 로드됨: {GOOGLE_APPLICATION_CREDENTIALS}")
    print("API V1 라우터 로드 중...")
    app.include_router(chat_router_v1.router, prefix="/api/v1/chat", tags=["Chat Service V1"])

@app.get("/")
async def root():
    return {"message": "디딤돌 음성 상담 에이전트 API"}

# LangGraph 에이전트 및 기타 서비스 초기화는 각 모듈에서 처리