from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio

from .api.V1 import chat as chat_router_v1
from .core.config import OPENAI_API_KEY, GOOGLE_APPLICATION_CREDENTIALS
from .services.rag_service import rag_service
import os

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("--- Server Starting Up ---")
    try:
        # RAG 서비스를 비동기적으로 초기화합니다.
        # force_recreate=True로 설정하면 서버가 시작될 때마다 DB를 새로 만듭니다.
        # 개발 중에는 True로 두고, 안정화되면 False로 바꾸는 것이 좋습니다.
        await rag_service.initialize(force_recreate=False) 
        print("RAG service initialized successfully during startup.")
    except Exception as e:
        # 초기화 실패 시, 서버 시작을 중단하지는 않되, 치명적인 에러 로그를 남깁니다.
        print(f"FATAL: RAG service initialization failed during startup: {e}")
        # 여기서 raise e를 하면 서버 시작이 실패합니다.
        # 일단은 에러를 로깅만 하고 넘어가서 다른 기능은 동작하도록 할 수 있습니다.
    
    yield
    # Shutdown
    print("--- Server Shutting Down ---")


app = FastAPI(
    title="Didimdol Voice Agent API",
    lifespan=lifespan
)

# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",      # 로컬 개발
        "http://127.0.0.1:5173",     # 로컬 개발
        "https://aibranch.zapto.org", # 외부 호스팅
        "https://43.202.47.188"       # 외부 호스팅 IP
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 환경 변수 및 API 키 로드 확인
if not OPENAI_API_KEY:
    print("Warning: OPENAI_API_KEY is not set.")
if not GOOGLE_APPLICATION_CREDENTIALS or not os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
    print(f"Warning: GOOGLE_APPLICATION_CREDENTIALS is not set or file not found at {GOOGLE_APPLICATION_CREDENTIALS}")
else:
    print(f"Google Cloud Credentials 로드됨: {GOOGLE_APPLICATION_CREDENTIALS}")

print("API V1 라우터 로드 중...")
app.include_router(chat_router_v1.router, prefix="/api/v1/chat", tags=["Chat Service V1"])

@app.get("/")
async def root():
    return {"message": "디딤돌 음성 상담 에이전트 API"}

# LangGraph 에이전트 및 기타 서비스 초기화는 각 모듈에서 처리