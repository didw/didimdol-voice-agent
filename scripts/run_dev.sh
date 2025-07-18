#!/bin/bash

# 백엔드 실행
echo "백엔드 FastAPI 서버를 시작합니다... (Port 8000)"
cd ../backend
#source venv/bin/activate # 가상환경 활성화 (경로 확인 필요)
uvicorn app.main:app --reload --port 8000 &
BACKEND_PID=$!
cd ..

# 프론트엔드 실행
echo "프론트엔드 Vue 개발 서버를 시작합니다... (Port 5173 or 8080)"
cd frontend
npm run dev & # 또는 yarn dev
FRONTEND_PID=$!

# 종료 처리
trap "echo '서버 종료 중...'; kill $BACKEND_PID $FRONTEND_PID; exit" SIGINT SIGTERM

wait
