from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware # CORS 추가
from .api.V1 import chat as chat_router_v1
from .core.config import OPENAI_API_KEY, GOOGLE_APPLICATION_CREDENTIALS # 설정 로드 확인용
import os

app = FastAPI(title="Didimdol Voice Agent API")

# CORS 미들웨어 설정
# 실제 운영 환경에서는 origins를 구체적으로 명시해야 합니다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 개발 중에는 모든 origin 허용, 프로덕션에서는 프론트엔드 주소로 제한
    allow_credentials=True,
    allow_methods=["*"], # 모든 HTTP 메소드 허용
    allow_headers=["*"], # 모든 HTTP 헤더 허용
)

@app.on_event("startup")
async def startup_event():
    print("애플리케이션 시작...")
    if not OPENAI_API_KEY:
        print("경고: OPENAI_API_KEY가 설정되지 않았습니다.")
    if not GOOGLE_APPLICATION_CREDENTIALS or not os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
        print(f"경고: GOOGLE_APPLICATION_CREDENTIALS 경로가 유효하지 않거나 파일이 없습니다: {GOOGLE_APPLICATION_CREDENTIALS}")
    print("API V1 라우터 로드 중...")
    app.include_router(chat_router_v1.router, prefix="/api/v1/chat", tags=["Chat Service"])



@app.get("/")
async def root():
    return {"message": "디딤돌 음성 상담 에이전트 API에 오신 것을 환영합니다!"}

# LangGraph 에이전트 초기화 및 실행 로직은 chat.py 또는 graph/agent.py 에서 처리