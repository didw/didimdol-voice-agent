
### Nginx 설정 (리버스 프록시)

Nginx는 외부의 HTTPS(포트 443) 요청을 받아 SSL 처리를 한 후, 내부에서 실행 중인 Vue 프론트엔드 개발 서버(포트 5173)와 FastAPI 백엔드 서버(포트 8000)로 요청을 분배하는 역할을 합니다.

`/etc/nginx/sites-available/` 경로에 아래 내용으로 `your-project.conf` 파일을 생성하고, `/etc/nginx/sites-enabled/`에 심볼릭 링크를 만드세요.

```nginx
server {
    listen 80;
    server_name 43.202.47.188 aibranch.zapto.org;

    # HTTP 요청을 HTTPS로 리디렉션
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name 43.202.47.188 aibranch.zapto.org;

    # SSL 인증서 경로 설정
    # 프로젝트 root 디렉토리 아래 key 폴더에 인증서가 위치한 경로를 정확히 입력해야 합니다.
    # 예: /home/ubuntu/didimdol-voice-agent/key/cert.pem
    ssl_certificate /home/ubuntu/didimdol-voice-agent/key/cert.pem;
    ssl_certificate_key /home/ubuntu/didimdol-voice-agent/key/key.pem;

    # SSL 프로토콜 및 암호화 스위트 설정 (보안 강화)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';

    # 백엔드 API 및 WebSocket 프록시 설정
    location /api {
        proxy_pass http://127.0.0.1:8000; # FastAPI 서버 주소
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket을 위한 설정
        location /api/v1/chat/ws/ {
            proxy_pass http://127.0.0.1:8000/api/v1/chat/ws/;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_read_timeout 86400s; # WebSocket 연결 유지 시간 (필요시 조절)
        }
    }

    # 프론트엔드 (Vue 개발 서버) 프록시 설정
    location / {
        proxy_pass http://127.0.0.1:5173; # Vue 개발 서버 주소
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Vite 개발 서버의 WebSocket을 위한 설정 (Hot-Reload)
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

**설정 적용 방법:**
1.  위 내용으로 설정 파일을 작성합니다.
2.  Nginx 설정에 오류가 없는지 테스트합니다: `sudo nginx -t`
3.  오류가 없으면 Nginx를 재시작하여 설정을 적용합니다: `sudo systemctl restart nginx`

이러한 설정을 통해 외부에서 `https://43.202.47.188` 또는 `https://aibranch.zapto.org`로 접속하면 Nginx가 안전한 연결을 수립하고, 내부적으로는 개발 중인 Vue 및 FastAPI 서버와 통신하게 됩니다.
