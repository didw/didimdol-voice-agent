# 로컬 개발 환경 설정 가이드

이 문서는 로컬 개발 환경과 프로덕션 환경을 올바르게 설정하는 방법을 안내합니다.

## 환경별 설정 파일

### 1. 백엔드 환경 설정

#### 로컬 개발 (.env.local)
```env
# 백엔드 포트 (로컬에서 충돌 시 8001 사용)
PORT=8001

# API Keys
OPENAI_API_KEY=your_openai_api_key
GOOGLE_APPLICATION_CREDENTIALS=/path/to/google-credentials.json

# 개발 환경 설정
DEBUG=True
LOG_LEVEL=DEBUG
```

#### 프로덕션 (.env.production)
```env
# 백엔드 포트 (표준 포트)
PORT=8000

# API Keys
OPENAI_API_KEY=your_production_api_key
GOOGLE_APPLICATION_CREDENTIALS=/path/to/production-credentials.json

# 프로덕션 환경 설정
DEBUG=False
LOG_LEVEL=INFO
```

### 2. 프론트엔드 환경 설정

#### 로컬 개발 (.env.development)
```env
# 로컬 백엔드 연결 (포트 주의)
VITE_API_BASE_URL=http://localhost:8001/api/v1
VITE_WEBSOCKET_URL=ws://localhost:8001/api/v1/chat/ws/
```

#### 프로덕션 (.env.production)
```env
# 프로덕션 서버 연결
VITE_API_BASE_URL=https://aibranch.zapto.org/api/v1
VITE_WEBSOCKET_URL=wss://aibranch.zapto.org/api/v1/chat/ws/
```

## 로컬 개발 환경 실행

### 1. 환경 파일 복사
```bash
# 백엔드
cd backend
cp .env.example .env.local
# .env.local 파일을 편집하여 API 키 입력

# 프론트엔드
cd ../frontend
# .env.development 파일은 이미 설정되어 있음
```

### 2. 백엔드 실행 (포트 8001)
```bash
cd backend
source venv/bin/activate
export $(cat .env.local | xargs)  # 환경 변수 로드
uvicorn app.main:app --reload --port 8001
```

### 3. 프론트엔드 실행
```bash
cd frontend
npm install
npm run dev
```

### 4. 로컬 nginx 사용 (선택사항)
로컬에서도 프로덕션과 동일한 환경을 원한다면:

```nginx
# /usr/local/etc/nginx/nginx.conf (Mac) 또는 /etc/nginx/sites-available/local (Linux)
server {
    listen 80;
    server_name localhost;
    
    location /api/v1/chat/ws/ {
        proxy_pass http://127.0.0.1:8001/api/v1/chat/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    location /api {
        proxy_pass http://127.0.0.1:8001;
    }
    
    location / {
        proxy_pass http://127.0.0.1:5173;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

## 프로덕션 배포

### 1. 코드 업데이트
```bash
git pull origin main
```

### 2. 백엔드 실행
```bash
cd backend
source venv/bin/activate
export $(cat .env.production | xargs)
uvicorn app.main:app --reload --port 8000
```

### 3. 프론트엔드 빌드
```bash
cd frontend
NODE_ENV=production npm run build
```

### 4. nginx 재시작
```bash
sudo systemctl reload nginx
```

## 환경별 차이점

| 항목 | 로컬 개발 | 프로덕션 |
|------|----------|----------|
| 백엔드 포트 | 8001 | 8000 |
| 프론트엔드 | 개발 서버 (5173) | 정적 파일 (nginx) |
| WebSocket | ws://localhost:8001 | wss://aibranch.zapto.org |
| SSL | 없음 | nginx에서 처리 |
| CORS | localhost:5173 | aibranch.zapto.org |

## 주의사항

1. **환경 파일 관리**
   - `.env` 파일들은 Git에 커밋하지 마세요
   - `.env.example` 파일만 커밋하세요
   - API 키와 인증 정보는 절대 공유하지 마세요

2. **포트 충돌**
   - 로컬에서 8000 포트가 사용 중이면 8001 사용
   - 프론트엔드 환경 변수도 함께 수정 필요

3. **SSL 인증서**
   - 로컬 개발에서는 HTTP 사용
   - 프로덕션에서만 HTTPS 사용

4. **데이터베이스**
   - LanceDB는 로컬 파일 시스템 사용
   - 각 환경별로 별도 관리

## 문제 해결

### WebSocket 연결 실패
1. 백엔드 포트 확인
2. 프론트엔드 환경 변수 확인
3. CORS 설정 확인

### 502 Bad Gateway
1. 백엔드 서버 실행 확인
2. nginx 프록시 포트 확인
3. 파일 권한 확인 (프로덕션)

### 환경 변수 문제
1. `.env` 파일 위치 확인
2. 환경 변수 이름 오타 확인
3. export 명령어로 수동 로드