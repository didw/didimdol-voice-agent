# TRD: 동시신규 입출금계좌 개설 시스템

## 1. 기술 개요

### 1.1 시스템 아키텍처
**마이크로서비스 기반 실시간 음성 상담 시스템**

```
[Client Browser] ←→ [Nginx Reverse Proxy] ←→ [FastAPI Backend] ←→ [External APIs]
     ↑                                           ↑
     ↓                                           ↓
[Vue.js Frontend] ←←←←← WebSocket ←←←←←← [LangGraph Agent System]
```

### 1.2 핵심 기술 스택

#### Backend
- **Python 3.9+**: 백엔드 메인 언어
- **FastAPI**: 고성능 비동기 웹 프레임워크
- **LangGraph**: 대화 흐름 관리 및 에이전트 오케스트레이션
- **LangChain**: LLM 통합 및 RAG 구현
- **Pydantic v2**: 데이터 검증 및 타입 안전성
- **WebSocket**: 실시간 양방향 통신
- **LanceDB**: 벡터 검색 데이터베이스

#### Frontend
- **Vue.js 3**: Composition API 기반 반응형 UI
- **TypeScript**: 타입 안전성 및 개발자 경험
- **Vite**: 고속 빌드 시스템
- **Pinia**: 상태 관리 라이브러리
- **Web Audio API**: 실시간 음성 처리

#### 외부 서비스
- **OpenAI GPT-4**: 자연어 이해 및 생성
- **Google Cloud STT**: 음성-텍스트 변환
- **Google Cloud TTS**: 텍스트-음성 변환
- **Tavily API**: 웹 검색 서비스

## 2. 시스템 컴포넌트 상세

### 2.1 Backend 아키텍처

#### 2.1.1 LangGraph Agent System
```python
# backend/app/graph/state.py
class AgentState(BaseModel):
    """메인 에이전트 상태 관리"""
    session_id: str
    user_input_text: Optional[str] = None
    current_product_type: Optional[PRODUCT_TYPES] = None
    collected_product_info: Dict[str, Any] = Field(default_factory=dict)
    scenario_agent_output: Optional[ScenarioAgentOutput] = None
    # ... 기타 상태 필드
```

#### 2.1.2 노드 기반 워크플로우
```
graph/nodes/
├── orchestrator/
│   ├── entry_point.py      # 진입점 노드
│   └── main_router.py      # 라우팅 로직
├── workers/
│   ├── scenario_agent.py   # 시나리오 처리
│   ├── scenario_logic.py   # 비즈니스 로직
│   ├── rag_worker.py       # 지식베이스 검색
│   └── web_worker.py       # 웹 검색
└── control/
    ├── synthesize.py       # 응답 합성
    └── end_conversation.py # 대화 종료
```

#### 2.1.3 시나리오 관리 시스템
```json
{
  "stage_id": {
    "response_type": "bullet|boolean|narrative",
    "prompt": "사용자에게 표시할 메시지",
    "choices": [
      {
        "value": "internal_value",
        "display": "사용자에게 표시되는 텍스트",
        "keywords": ["키워드1", "키워드2"],
        "ordinal_keywords": ["첫번째", "1번"],
        "default": true,
        "slot_fields": ["field1", "field2"]
      }
    ],
    "choice_groups": [
      {
        "title": "그룹 제목",
        "choices": [...]
      }
    ],
    "next_step": "다음_단계_ID",
    "slot_fields": ["연결할_슬롯_필드"]
  }
}
```

### 2.2 Frontend 아키텍처

#### 2.2.1 컴포넌트 구조
```typescript
// types/slotFilling.ts
interface SmartField {
  key: string
  displayName: string
  type: 'boolean' | 'text' | 'choice' | 'number'
  required: boolean
  showWhen?: string  // 조건부 표시
  parentField?: string
  depth?: number
  choices?: string[]
}

interface SlotFillingState {
  productType: string | null
  requiredFields: SmartField[]
  collectedInfo: Record<string, any>
  completionRate: number
  fieldGroups?: FieldGroup[]
}
```

#### 2.2.2 상태 관리 (Pinia)
```typescript
// stores/slotFillingStore.ts
export const useSlotFillingStore = defineStore('slotFilling', () => {
  const state = ref<SlotFillingState>()
  
  // 필드 가시성 계산 (캐싱 포함)
  const fieldVisibilityCache = new Map<string, boolean>()
  
  // 디바운싱으로 성능 최적화
  const UPDATE_DEBOUNCE_MS = 100
  
  const calculateVisibleFields = computed(() => {
    // 조건부 필드 표시 로직
  })
  
  return { state, calculateVisibleFields }
})
```

### 2.3 실시간 통신 시스템

#### 2.3.1 WebSocket 메시지 프로토콜
```typescript
// WebSocket 메시지 타입
interface SlotFillingUpdate {
  type: 'slot_filling_update'
  productType: string
  requiredFields: SmartField[]
  collectedInfo: Record<string, any>
  completionRate: number
  fieldGroups?: FieldGroup[]
}

interface StageResponseMessage {
  type: 'stage_response'
  stageId: string
  responseType: 'narrative' | 'bullet' | 'boolean'
  prompt: string
  choices?: Choice[]
  choiceGroups?: ChoiceGroup[]
}
```

#### 2.3.2 음성 처리 파이프라인
```javascript
// 실시간 음성 처리 흐름
WebSocket → STT (Google Cloud) → LLM Processing → TTS → Audio Playback
    ↑                                                          ↓
Microphone Input ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←← Speaker Output
```

## 3. 데이터 모델 및 구조

### 3.1 에이전트 상태 모델
```python
class AgentState(BaseModel):
    # 세션 관리
    session_id: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    # 입력 처리
    user_input_text: Optional[str] = None
    user_input_audio_b64: Optional[str] = None
    input_mode: str = "text"  # text, voice, choice
    
    # 상품 및 시나리오
    current_product_type: Optional[PRODUCT_TYPES] = None
    collected_product_info: Dict[str, Any] = Field(default_factory=dict)
    current_scenario_stage_id: Optional[str] = None
    
    # 에이전트 출력
    scenario_agent_output: Optional[ScenarioAgentOutput] = None
    final_response_text_for_tts: Optional[str] = None
```

### 3.2 시나리오 데이터 구조
```json
{
  "scenario_id": "deposit_account_scenario_v3",
  "version": "3.0",
  "slot_fields": {
    "field_key": {
      "display_name": "표시명",
      "type": "text|choice|boolean|number",
      "required": true,
      "group": "basic_info|electronic_banking|check_card",
      "extraction_prompt": "LLM 추출 프롬프트",
      "show_when": "parent_field == 'value'",
      "depth": 0,
      "choices": ["선택지1", "선택지2"]
    }
  },
  "stages": {
    "stage_id": {
      "response_type": "bullet|boolean|narrative",
      "prompt": "사용자 질문",
      "dynamic_prompt": "템플릿 변수 {default_choice} 포함",
      "choices": [...],
      "next_step": "다음_단계_또는_조건부_라우팅",
      "slot_fields": ["연결할_필드들"]
    }
  }
}
```

### 3.3 슬롯 필링 필드 구조
```typescript
interface SmartField {
  key: string                    // 고유 식별자
  displayName: string           // UI 표시명
  type: 'text' | 'choice' | 'boolean' | 'number'
  required: boolean             // 필수 여부
  group: string                 // 필드 그룹
  showWhen?: string            // 조건부 표시 로직
  parentField?: string         // 부모 필드 (계층 구조)
  depth?: number               // 계층 깊이
  choices?: string[]           // 선택 옵션
  unit?: string                // 단위 (예: 원, %)
  default?: any                // 기본값
  extraction_prompt?: string   // LLM 추출 프롬프트
}
```

## 4. API 사양

### 4.1 REST API 엔드포인트

#### 4.1.1 채팅 API
```http
POST /api/v1/chat/message
Content-Type: application/json

{
  "session_id": "unique-session-id",
  "message": "사용자 메시지",
  "input_mode": "text|voice|choice",
  "audio_data": "base64-encoded-audio", // 음성 모드일 때
  "stage_response": {  // 버튼 선택일 때
    "stage_id": "current_stage",
    "selected_choice": "choice_value"
  }
}

Response:
{
  "session_id": "unique-session-id",
  "response_text": "AI 응답",
  "audio_data": "base64-encoded-tts",
  "slot_filling_update": {
    "type": "slot_filling_update",
    "collected_info": {...},
    "completion_rate": 0.75
  },
  "stage_response": {
    "type": "stage_response",
    "stage_id": "next_stage",
    "choices": [...]
  }
}
```

#### 4.1.2 세션 관리 API
```http
POST /api/v1/chat/start_session
GET /api/v1/chat/session/{session_id}
DELETE /api/v1/chat/session/{session_id}
```

### 4.2 WebSocket API

#### 4.2.1 연결 설정
```javascript
const ws = new WebSocket('ws://localhost:8001/ws/chat/{session_id}')
```

#### 4.2.2 메시지 프로토콜
```typescript
// 클라이언트 → 서버
interface WSClientMessage {
  type: 'user_message' | 'user_choice_selection' | 'field_modification_request'
  session_id: string
  data: any
}

// 서버 → 클라이언트
interface WSServerMessage {
  type: 'slot_filling_update' | 'stage_response' | 'chat_response'
  session_id: string
  data: any
}
```

## 5. 보안 요구사항

### 5.1 데이터 보안
```python
# 개인정보 암호화
from cryptography.fernet import Fernet

class PersonalInfoEncryption:
    def __init__(self, key: bytes):
        self.cipher = Fernet(key)
    
    def encrypt_ssn(self, ssn: str) -> str:
        """주민등록번호 암호화"""
        return self.cipher.encrypt(ssn.encode()).decode()
```

### 5.2 API 보안
```python
# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# HTTPS 강제
@app.middleware("http")
async def force_https(request: Request, call_next):
    if request.headers.get("x-forwarded-proto") != "https":
        return RedirectResponse(url=f"https://{request.url}")
```

### 5.3 입력 검증
```python
class UserInput(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    session_id: str = Field(..., regex=r'^[a-zA-Z0-9\-_]+$')
    
    @field_validator('message')
    @classmethod
    def validate_message(cls, v):
        # XSS 방지 및 악성 입력 차단
        return sanitize_input(v)
```

## 6. 성능 요구사항

### 6.1 응답 시간 목표
- **STT 처리**: 평균 1초 이내
- **LLM 응답**: 평균 2초 이내  
- **TTS 생성**: 평균 1.5초 이내
- **전체 응답**: 평균 3초 이내

### 6.2 동시 처리 능력
```python
# FastAPI 설정
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        workers=4,  # CPU 코어 수에 맞춰 조정
        loop="uvloop",  # 고성능 이벤트 루프
        http="httptools"  # 고성능 HTTP 파서
    )
```

### 6.3 캐싱 전략
```python
from functools import lru_cache
import redis

# LRU 캐시로 자주 사용되는 시나리오 데이터 캐싱
@lru_cache(maxsize=128)
def load_scenario_data(scenario_id: str) -> Dict:
    return json.load(open(f"data/scenarios/{scenario_id}.json"))

# Redis 캐시로 세션 상태 관리
redis_client = redis.Redis(host='localhost', port=6379, db=0)

def cache_session_state(session_id: str, state: dict):
    redis_client.setex(session_id, 3600, json.dumps(state))
```

## 7. 개발 환경 구성

### 7.1 Backend 환경
```bash
# Python 가상환경
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

# 의존성 설치
pip install -r requirements.txt

# 환경 변수 설정 (.env)
OPENAI_API_KEY=your_openai_key
GOOGLE_APPLICATION_CREDENTIALS=path/to/credentials.json
TAVILY_API_KEY=your_tavily_key
```

### 7.2 Frontend 환경
```bash
# Node.js 18+ 필요
npm install

# 개발 서버 실행
npm run dev

# 환경 변수 설정 (.env.development)
VITE_API_BASE_URL=http://localhost:8001
VITE_WS_BASE_URL=ws://localhost:8001
```

### 7.3 Docker 구성
```dockerfile
# Dockerfile (Backend)
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Dockerfile (Frontend)
FROM node:18-alpine
WORKDIR /app
COPY package*.json .
RUN npm install
COPY . .
RUN npm run build
CMD ["npm", "run", "preview"]
```

### 7.4 Docker Compose
```yaml
version: '3.8'
services:
  backend:
    build: ./backend
    ports:
      - "8001:8000"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    volumes:
      - ./backend:/app
  
  frontend:
    build: ./frontend
    ports:
      - "5173:5173"
    depends_on:
      - backend
  
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - frontend
      - backend
```

## 8. 배포 아키텍처

### 8.1 프로덕션 배포 구조
```
[Load Balancer] → [Nginx Reverse Proxy] → [Backend Instances]
                         ↓
                  [Static File Serving] ← [Frontend Build]
```

### 8.2 Nginx 설정
```nginx
# nginx/nginx.conf
upstream backend {
    server backend:8000;
}

server {
    listen 80;
    server_name yourdomain.com;
    
    # Frontend 정적 파일
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }
    
    # Backend API
    location /api/ {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    # WebSocket
    location /ws/ {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 8.3 SSL/TLS 설정
```nginx
server {
    listen 443 ssl http2;
    ssl_certificate /etc/ssl/certs/cert.pem;
    ssl_certificate_key /etc/ssl/private/key.pem;
    
    # SSL 보안 설정
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512;
    ssl_prefer_server_ciphers off;
}
```

## 9. 모니터링 및 로깅

### 9.1 애플리케이션 로깅
```python
import logging
from pythonjsonlogger import jsonlogger

# 구조화된 JSON 로깅
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter()
logHandler.setFormatter(formatter)
logger = logging.getLogger()
logger.addHandler(logHandler)

# 노드별 로깅 패턴
logger.info("🔄 [ScenarioAgent] Processing user input", extra={
    "session_id": session_id,
    "stage_id": current_stage,
    "user_input": user_input[:100]  # 처음 100자만
})
```

### 9.2 성능 모니터링
```python
import time
from functools import wraps

def monitor_performance(node_name: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            result = await func(*args, **kwargs)
            duration = time.time() - start_time
            
            logger.info(f"⏱️ [{node_name}] Execution time: {duration:.2f}s")
            return result
        return wrapper
    return decorator

@monitor_performance("ScenarioLogic")
async def process_scenario_logic(state: AgentState):
    # 처리 로직
    pass
```

### 9.3 에러 추적
```python
import traceback

class ErrorHandler:
    @staticmethod
    def log_error(error: Exception, context: dict):
        logger.error("❌ Application Error", extra={
            "error_type": type(error).__name__,
            "error_message": str(error),
            "traceback": traceback.format_exc(),
            "context": context
        })
```

## 10. 테스트 프레임워크

### 10.1 Backend 테스트
```python
# pytest 설정
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

@pytest.fixture
def sample_session():
    return {
        "session_id": "test-session-123",
        "user_input": "입출금계좌 개설하고 싶어요"
    }

def test_chat_message_endpoint(sample_session):
    response = client.post("/api/v1/chat/message", json=sample_session)
    assert response.status_code == 200
    assert "response_text" in response.json()

# LangGraph 노드 테스트
def test_scenario_logic_node():
    from app.graph.nodes.workers.scenario_logic import process_scenario_logic
    
    state = AgentState(
        session_id="test",
        user_input_text="전체 서비스",
        current_product_type="deposit_account"
    )
    
    result = process_scenario_logic(state)
    assert result.scenario_agent_output is not None
```

### 10.2 Frontend 테스트
```typescript
// Vitest 단위 테스트
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SlotFillingPanel from '@/components/SlotFillingPanel.vue'

describe('SlotFillingPanel', () => {
  it('renders completion rate correctly', () => {
    const wrapper = mount(SlotFillingPanel, {
      props: {
        slotFillingState: {
          completionRate: 0.75,
          requiredFields: [],
          collectedInfo: {}
        }
      }
    })
    
    expect(wrapper.find('.completion-rate').text()).toContain('75%')
  })
})

// E2E 테스트 (Playwright)
import { test, expect } from '@playwright/test'

test('complete account opening flow', async ({ page }) => {
  await page.goto('http://localhost:5173')
  
  // 음성 모드 활성화
  await page.click('[data-testid="voice-mode-toggle"]')
  
  // 시나리오 진행
  await page.fill('[data-testid="text-input"]', '입출금계좌 개설')
  await page.click('[data-testid="send-button"]')
  
  // 슬롯 필링 패널 확인
  await expect(page.locator('[data-testid="slot-filling-panel"]')).toBeVisible()
})
```

### 10.3 통합 테스트
```python
import asyncio
import websockets
import json

async def test_websocket_flow():
    uri = "ws://localhost:8001/ws/chat/test-session"
    
    async with websockets.connect(uri) as websocket:
        # 메시지 전송
        message = {
            "type": "user_message",
            "session_id": "test-session",
            "message": "입출금계좌 개설하고 싶어요"
        }
        await websocket.send(json.dumps(message))
        
        # 응답 확인
        response = await websocket.recv()
        data = json.loads(response)
        
        assert data["type"] in ["chat_response", "stage_response"]
        assert "session_id" in data
```

## 11. 코드 품질 표준

### 11.1 Python 코딩 표준
```python
# Type hints 필수
from typing import Dict, List, Optional, Union, Any

def process_user_input(
    user_input: str,
    session_data: Dict[str, Any],
    scenario_config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    사용자 입력 처리 함수
    
    Args:
        user_input: 사용자 입력 텍스트
        session_data: 세션 데이터
        scenario_config: 시나리오 설정 (선택사항)
    
    Returns:
        처리 결과 딕셔너리
    """
    pass

# 예외 처리 패턴
class BusinessLogicError(Exception):
    """비즈니스 로직 에러"""
    pass

try:
    result = process_user_input(user_input, session_data)
except BusinessLogicError as e:
    logger.error(f"Business logic error: {e}")
    return {"error": "처리 중 오류가 발생했습니다."}
```

### 11.2 TypeScript 코딩 표준
```typescript
// 인터페이스 정의 우선
interface UserMessage {
  readonly id: string
  readonly text: string
  readonly timestamp: Date
  readonly sender: 'user' | 'ai'
}

// 타입 가드 활용
function isUserMessage(message: unknown): message is UserMessage {
  return typeof message === 'object' && 
         message !== null && 
         'sender' in message
}

// Generic 타입 활용
interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
}

async function fetchData<T>(endpoint: string): Promise<ApiResponse<T>> {
  // API 호출 로직
}
```

### 11.3 Vue 컴포넌트 표준
```vue
<template>
  <!-- 명확한 데이터 속성 사용 -->
  <div 
    class="component-wrapper"
    :class="{ 'is-loading': isLoading }"
    :aria-label="ariaLabel"
  >
    <slot :data="processedData" />
  </div>
</template>

<script setup lang="ts">
// Props와 Emits 명시적 정의
interface Props {
  data: ComponentData
  disabled?: boolean
}

interface Emits {
  update: [value: string]
  error: [error: Error]
}

const props = withDefaults(defineProps<Props>(), {
  disabled: false
})

const emit = defineEmits<Emits>()

// Computed 속성으로 파생 상태 관리
const processedData = computed(() => {
  return props.data.filter(item => !item.hidden)
})

// 명확한 함수명과 단일 책임
const handleUserAction = (event: Event) => {
  if (props.disabled) return
  
  try {
    const result = processAction(event)
    emit('update', result)
  } catch (error) {
    emit('error', error as Error)
  }
}
</script>

<style scoped>
.component-wrapper {
  /* CSS 변수 활용 */
  --primary-color: #007bff;
  --border-radius: 4px;
  
  border-radius: var(--border-radius);
  transition: opacity 0.2s ease;
}

.is-loading {
  opacity: 0.6;
  pointer-events: none;
}
</style>
```

## 12. 통합 요구사항

### 12.1 외부 API 통합
```python
# Google Cloud 서비스 통합
from google.cloud import speech, texttospeech
from google.oauth2 import service_account

class GoogleCloudService:
    def __init__(self, credentials_path: str):
        self.credentials = service_account.Credentials.from_service_account_file(
            credentials_path
        )
        self.stt_client = speech.SpeechClient(credentials=self.credentials)
        self.tts_client = texttospeech.TextToSpeechClient(credentials=self.credentials)
    
    async def speech_to_text(self, audio_data: bytes) -> str:
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            sample_rate_hertz=48000,
            language_code="ko-KR",
            enable_automatic_punctuation=True
        )
        
        audio = speech.RecognitionAudio(content=audio_data)
        response = self.stt_client.recognize(config=config, audio=audio)
        
        return response.results[0].alternatives[0].transcript if response.results else ""

# OpenAI 통합
from openai import AsyncOpenAI

class OpenAIService:
    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)
    
    async def generate_response(
        self, 
        messages: List[Dict], 
        temperature: float = 0.1
    ) -> str:
        response = await self.client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=temperature,
            max_tokens=1000
        )
        
        return response.choices[0].message.content
```

### 12.2 에러 처리 및 재시도 로직
```python
import asyncio
from typing import Callable, TypeVar, Any
from functools import wraps

T = TypeVar('T')

def retry_on_failure(max_retries: int = 3, delay: float = 1.0):
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(f"Attempt {attempt + 1} failed: {e}")
                        await asyncio.sleep(delay * (2 ** attempt))  # 지수 백오프
                    else:
                        logger.error(f"All {max_retries + 1} attempts failed")
            
            raise last_exception
        return wrapper
    return decorator

@retry_on_failure(max_retries=3)
async def call_openai_api(prompt: str) -> str:
    # OpenAI API 호출
    pass
```

## 13. 운영 및 유지보수

### 13.1 Configuration Management
```python
# app/config/settings.py
from pydantic import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # API Keys
    openai_api_key: str
    google_credentials_path: str
    tavily_api_key: str
    
    # Database
    redis_url: str = "redis://localhost:6379"
    
    # Performance
    max_concurrent_sessions: int = 100
    response_timeout: int = 30
    
    # Feature Flags
    enable_web_search: bool = True
    enable_voice_interruption: bool = True
    
    class Config:
        env_file = ".env"

settings = Settings()
```

### 13.2 Health Check 및 Metrics
```python
from fastapi import FastAPI
from prometheus_client import Counter, Histogram, generate_latest
import time

app = FastAPI()

# Metrics
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint'])
REQUEST_DURATION = Histogram('http_request_duration_seconds', 'HTTP request duration')

@app.middleware("http")
async def add_metrics(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    
    REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path).inc()
    REQUEST_DURATION.observe(duration)
    
    return response

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    }

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

### 13.3 로그 관리
```python
import logging
import sys
from pythonjsonlogger import jsonlogger

def setup_logging():
    # JSON 형태의 구조화된 로그
    logHandler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    logHandler.setFormatter(formatter)
    
    # 루트 로거 설정
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(logHandler)
    
    # 외부 라이브러리 로그 레벨 조정
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

setup_logging()
```

## 14. 버전 관리 및 배포

### 14.1 Git 브랜치 전략
```bash
# 기능 개발
git checkout -b feature/new-scenario-logic
git commit -m "feat: Add conditional routing for OTP selection"

# 버그 수정
git checkout -b hotfix/slot-filling-update
git commit -m "fix: Resolve slot filling WebSocket sync issue"

# 릴리스 준비
git checkout -b release/v1.2.0
git commit -m "chore: Bump version to 1.2.0"
```

### 14.2 CI/CD 파이프라인
```yaml
# .github/workflows/deploy.yml
name: Deploy to Production

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'
      
      - name: Install dependencies
        run: |
          cd backend
          pip install -r requirements-test.txt
      
      - name: Run tests
        run: |
          cd backend
          python test_runner.py coverage
  
  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to server
        run: |
          # Docker 이미지 빌드 및 배포
          docker build -t voice-agent:latest .
          docker-compose up -d
```

### 14.3 데이터베이스 마이그레이션
```python
# 세션 데이터 구조 변경 시 마이그레이션
async def migrate_session_data_v1_to_v2():
    """v1 세션 데이터를 v2 형식으로 마이그레이션"""
    sessions = await get_all_sessions()
    
    for session in sessions:
        if session.get('version', '1.0') == '1.0':
            # 데이터 구조 변환
            migrated_data = {
                'version': '2.0',
                'session_id': session['session_id'],
                'collected_info': session.get('slot_data', {}),
                'current_stage': session.get('stage', 'start'),
                # 새로운 필드들
                'completion_rate': 0.0,
                'field_groups': []
            }
            
            await update_session(session['session_id'], migrated_data)
            logger.info(f"Migrated session {session['session_id']} to v2.0")
```

## 15. 장애 대응 및 복구

### 15.1 장애 감지 및 알림
```python
import smtplib
from email.mime.text import MIMEText

class AlertManager:
    def __init__(self, smtp_config: dict):
        self.smtp_config = smtp_config
    
    async def send_alert(self, level: str, message: str, context: dict):
        if level == "CRITICAL":
            await self._send_email_alert(message, context)
            await self._send_slack_alert(message, context)
    
    async def _send_email_alert(self, message: str, context: dict):
        msg = MIMEText(f"Alert: {message}\nContext: {context}")
        msg['Subject'] = f"[CRITICAL] Voice Agent Alert"
        msg['From'] = self.smtp_config['from']
        msg['To'] = self.smtp_config['to']
        
        # SMTP 전송 로직
```

### 15.2 자동 복구 메커니즘
```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    async def call(self, func, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
            else:
                raise Exception("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
            
            raise e

# OpenAI API 호출에 Circuit Breaker 적용
openai_circuit_breaker = CircuitBreaker(failure_threshold=3)

async def safe_openai_call(prompt: str) -> str:
    return await openai_circuit_breaker.call(openai_service.generate_response, prompt)
```

이 TRD는 동시신규 입출금계좌 개설 시스템의 완전한 기술적 구현 사양을 제공합니다. 개발팀이 이 문서를 바탕으로 다른 환경에서도 동일한 시스템을 구축할 수 있도록 모든 기술적 세부사항을 포함하였습니다.