# TRD (Technical Requirements Document) - 디딤돌 음성 상담 에이전트 동시신규 서비스

## 1. 시스템 아키텍처

### 1.1 전체 아키�ecture 개요
```
[사용자] ↔ [Vue.js Frontend] ↔ [WebSocket] ↔ [FastAPI Backend] ↔ [External APIs]
                   ↓                          ↓
              [Pinia Store]              [LangGraph Engine]
                                              ↓
                                     [Google STT/TTS APIs]
                                     [OpenAI GPT APIs]
```

### 1.2 시스템 구성요소

#### 1.2.1 Frontend (Vue.js + TypeScript)
- **Framework**: Vue 3.4+ with Composition API
- **Language**: TypeScript 5.0+
- **State Management**: Pinia 2.1+
- **Build Tool**: Vite 5.0+
- **Real-time Communication**: WebSocket API

#### 1.2.2 Backend (Python + FastAPI)
- **Framework**: FastAPI 0.104+
- **Language**: Python 3.11+
- **State Management**: LangGraph + Pydantic 2.0+
- **LLM Integration**: LangChain + OpenAI GPT-4
- **Real-time Communication**: WebSocket

#### 1.2.3 External Services
- **STT**: Google Cloud Speech-to-Text API
- **TTS**: Google Cloud Text-to-Speech API  
- **LLM**: OpenAI GPT-4 (JSON mode)

## 2. 상세 기술 스펙

### 2.1 Frontend 기술 스택

#### 2.1.1 핵심 컴포넌트 구조
```
src/
├── components/
│   ├── ChatInterface.vue          # 메인 채팅 인터페이스
│   ├── StageResponse.vue          # 단계별 응답 UI
│   ├── SlotFillingPanel.vue       # 진행상황 시각화
│   ├── ProgressBar.vue            # 진행률 바
│   └── SlotFillingDebug.vue       # 디버깅 도구
├── stores/
│   ├── chatStore.ts               # 채팅 상태 관리
│   └── slotFillingStore.ts        # 슬롯필링 상태 관리
└── types/
    ├── stageResponse.ts           # 단계 응답 타입
    └── slotFilling.ts             # 슬롯필링 타입
```

#### 2.1.2 상태 관리 (Pinia)
**chatStore.ts 주요 기능**:
- WebSocket 연결 관리
- 메시지 히스토리 관리
- 음성 입력/출력 상태 관리
- 현재 단계 응답 데이터 관리

**slotFillingStore.ts 주요 기능**:
- 수집 정보 실시간 추적
- 진행률 계산 및 캐싱
- 그룹별 가시성 관리
- 업데이트 최적화 (디바운싱)

#### 2.1.3 UI 컴포넌트 스펙

**StageResponse.vue 지원 타입**:
- `narrative`: 일반 텍스트 응답
- `bullet`: 단일 선택지 목록
- `boolean`: 토글 스위치 배열
- 추가 질문 표시 (`additional_questions`)

**SlotFillingPanel.vue 기능**:
- 3단계 계층 구조 (그룹 → 필드 → 값)
- 실시간 진행률 애니메이션
- 모바일 최적화 (스와이프, 터치)
- 접근성 지원 (ARIA, 키보드 네비게이션)

#### 2.1.4 성능 최적화
- **디바운싱**: 100ms 업데이트 지연
- **캐싱**: 필드 가시성 캐시 (최대 500개 항목)
- **중복 방지**: 해시 기반 중복 업데이트 감지
- **메모리 관리**: 5분마다 캐시 정리

### 2.2 Backend 기술 스택

#### 2.2.1 핵심 모듈 구조
```
backend/app/
├── graph/
│   ├── agent.py                   # 메인 오케스트레이터
│   ├── state.py                   # Pydantic 상태 모델
│   ├── nodes/
│   │   ├── orchestrator/          # 라우팅 노드
│   │   ├── workers/               # 작업 노드
│   │   └── control/               # 제어 노드
│   └── simple_scenario_engine.py  # 시나리오 엔진
├── data/
│   ├── scenarios/                 # 시나리오 JSON 파일
│   ├── deposit_account_fields.py  # 필드 정의
│   └── slot_filling_groups.py     # 그룹 정의
├── api/V1/
│   ├── chat.py                    # WebSocket 엔드포인트
│   ├── chat_handlers.py           # 메시지 핸들러
│   └── websocket_manager.py       # 연결 관리
└── services/
    └── google_services.py         # Google Cloud 서비스
```

#### 2.2.2 LangGraph 워크플로우
**주요 노드 타입**:
- **Orchestrator**: `entry_point_node`, `main_agent_router_node`
- **Workers**: `scenario_worker`, `rag_worker`, `web_worker`
- **Control**: `synthesize_response_node`, `set_product_type_node`

**상태 전이 흐름**:
```
Entry Point → Main Router → Scenario Worker → Scenario Logic → Response
```

#### 2.2.3 시나리오 엔진 (Simple Scenario Engine)
**8단계 선형 프로세스**:
1. `select_services` - 필요 업무 확인
2. `confirm_personal_info` - 고객 정보 확인  
3. `security_medium_registration` - 보안매체 등록
4. `additional_services` - 추가 정보 선택
5. `card_selection` - 카드 선택
6. `statement_delivery` - 명세서 수령 정보
7. `card_usage_alert` - 카드 사용 알림 설정
8. `card_password_setting` - 카드 비밀번호 설정

**핵심 로직**:
- 단계별 완료 조건 검증
- 필드 매핑 및 검증
- 조건부 플로우 처리 (서비스 선택에 따른 단계 스킵)
- 기본값 자동 설정

#### 2.2.4 데이터 모델 (Pydantic)

**AgentState 주요 필드**:
```python
class AgentState(BaseModel):
    session_id: str
    current_product_type: Optional[str]
    current_scenario_stage_id: Optional[str]
    collected_product_info: Dict[str, Any]
    correction_mode: bool = False
    pending_modifications: Optional[Dict[str, Any]]
    scenario_ready_for_continuation: bool = False
```

**필드 타입 정의**:
- `text`: 문자열 입력
- `boolean`: 참/거짓 선택
- `choice`: 선택지 목록 (단일/다중)
- `number`: 숫자 입력 (한국어 숫자 변환 지원)

### 2.3 외부 서비스 통합

#### 2.3.1 Google Cloud Speech-to-Text
**설정 스펙**:
```python
RecognitionConfig(
    encoding=RecognitionConfig.AudioEncoding.WEBM_OPUS,
    sample_rate_hertz=48000,
    language_code="ko-KR",
    model="chirp",
    use_enhanced=True,
    enable_automatic_punctuation=True,
    enable_word_time_offsets=True,
    speech_contexts=[SpeechContext(phrases=["디딤돌", "신한은행", ...])]
)
```

**실시간 스트리밍**:
- WebRTC VAD (Voice Activity Detection) 기반
- 청크 단위 처리 (1024 bytes)
- End-point Detection으로 문장 단위 인식

#### 2.3.2 Google Cloud Text-to-Speech
**음성 모델**: Chirp3-HD-Orus (한국어 최적화)
**설정**:
```python
VoiceSelectionParams(
    language_code="ko-KR",
    name="ko-KR-Neural2-A",
    ssml_gender=SsmlVoiceGender.NEUTRAL
)
AudioConfig(
    audio_encoding=AudioEncoding.LINEAR16,
    speaking_rate=1.2,
    pitch=0.0,
    volume_gain_db=0.0
)
```

#### 2.3.3 OpenAI GPT-4 Integration
**JSON Mode 활용**:
- 구조화된 응답 생성
- 필드 추출 및 검증
- 자연어 의도 분석

**Entity Agent 구현**:
- 시나리오 기반 프롬프트 활용
- 추출 규칙 및 패턴 매칭
- Fallback 처리 로직

### 2.4 데이터 플로우

#### 2.4.1 음성 입력 처리 플로우
```
[사용자 음성] → [WebRTC VAD] → [Google STT] → [텍스트 정규화] 
→ [Entity Agent] → [필드 매칭] → [시나리오 엔진] → [상태 업데이트]
```

#### 2.4.2 응답 생성 플로우  
```
[시나리오 단계] → [응답 타입 결정] → [선택지 생성] → [추가 질문 포함]
→ [Google TTS] → [오디오 청크] → [WebSocket 전송]
```

#### 2.4.3 실시간 상태 동기화
```
[Backend 상태 변경] → [WebSocket 메시지] → [Frontend Store 업데이트]
→ [UI 컴포넌트 리렌더링] → [사용자 피드백]
```

## 3. 보안 및 데이터 처리

### 3.1 개인정보 보호
**데이터 마스킹**:
- 주민등록번호: 앞 6자리만 표시
- 전화번호: 뒷 4자리 마스킹  
- 주소: 상세주소 일부 마스킹

**암호화**:
- 전송 구간: TLS 1.3
- 저장 구간: AES-256
- 세션 데이터: 메모리 기반 임시 저장

### 3.2 세션 관리
**세션 생명주기**:
- 생성: WebSocket 연결 시 UUID 기반 세션 ID 생성
- 유지: 30분 비활성 시간 기준
- 정리: 세션 종료 시 모든 임시 데이터 삭제

### 3.3 입력 검증
**클라이언트 사이드**:
- TypeScript 타입 체크
- 실시간 유효성 검사
- XSS 방지 처리

**서버 사이드**:
- Pydantic 데이터 검증
- SQL Injection 방지
- Rate Limiting (세션당 분당 60회)

## 4. 성능 요구사항

### 4.1 응답 시간
- **음성 인식**: 평균 1.5초, 최대 3초
- **응답 생성**: 평균 2초, 최대 5초
- **TTS 변환**: 평균 1초, 최대 2초
- **전체 턴**: 평균 4.5초, 최대 10초

### 4.2 동시 사용자
- **목표**: 100명 동시 연결
- **WebSocket 연결**: 최대 200개 유지
- **메모리 사용량**: 사용자당 평균 50MB

### 4.3 캐싱 전략
**Frontend**:
- 필드 가시성 캐시: 500개 항목, 5분 TTL
- API 응답 캐시: 1000개 항목, 10분 TTL

**Backend**:
- 시나리오 데이터: 메모리 캐시, 1시간 TTL
- 사용자 세션: Redis 클러스터, 30분 TTL

## 5. 확장성 및 모니터링

### 5.1 수평적 확장
**Load Balancing**:
- WebSocket Sticky Session 지원
- Health Check 엔드포인트
- Graceful Shutdown 처리

**Service Mesh**:
- 마이크로서비스 분리 준비
- API Gateway 통합
- Circuit Breaker 패턴

### 5.2 모니터링 및 로깅
**성능 메트릭**:
- 응답 시간 분포
- 에러율 및 성공률
- 리소스 사용량 (CPU, 메모리, 네트워크)

**비즈니스 메트릭**:
- 단계별 완료율
- 이탈 지점 분석
- 음성 인식 정확도

**로깅 레벨**:
- ERROR: 시스템 오류
- WARN: 비즈니스 예외
- INFO: 주요 플로우
- DEBUG: 상세 디버깅 (개발 환경만)

### 5.3 에러 처리 및 복구
**Retry 정책**:
- 외부 API 호출: 3회 재시도, 지수 백오프
- WebSocket 재연결: 5초 간격으로 3회 시도
- TTS 스트림: 실패 시 텍스트로 fallback

**Circuit Breaker**:
- 외부 서비스 장애 시 자동 차단
- Health Check 기반 복구
- Fallback 응답 제공

## 6. 배포 및 운영

### 6.1 배포 환경
**Development**:
- 로컬 개발 환경
- Hot Reload 지원
- 디버깅 도구 활성화

**Staging**:
- Production 환경과 동일한 구성
- 통합 테스트 수행
- 성능 테스트 실행

**Production**:
- 고가용성 구성
- 자동 스케일링
- 모니터링 및 알람

### 6.2 CI/CD 파이프라인
**Build Stage**:
- 정적 분석 (ESLint, mypy)
- 단위 테스트 실행
- 보안 스캔 (SAST)

**Deploy Stage**:
- Blue-Green 배포
- 헬스 체크 검증
- 롤백 준비

### 6.3 운영 요구사항
**Backup**:
- 설정 파일: 일일 백업
- 사용자 데이터: 실시간 백업 (개인정보 제외)
- 로그 데이터: 30일 보관

**보안 업데이트**:
- 의존성 취약점 주간 스캔
- 보안 패치 월간 적용
- 침투 테스트 분기별 실행

## 7. 테스트 전략

### 7.1 단위 테스트
**Frontend (Vue Test Utils + Vitest)**:
- 컴포넌트 렌더링 테스트
- 사용자 인터랙션 테스트
- Store 로직 테스트
- 커버리지 목표: 80% 이상

**Backend (pytest)**:
- API 엔드포인트 테스트
- 시나리오 엔진 로직 테스트
- 데이터 모델 검증 테스트
- 커버리지 목표: 85% 이상

### 7.2 통합 테스트
**WebSocket 통신 테스트**:
- 실시간 메시지 전송/수신
- 연결 끊김 및 재연결
- 다중 사용자 동시 접속

**외부 서비스 연동 테스트**:
- Google STT/TTS API
- OpenAI GPT API
- Mock 서비스를 활용한 격리 테스트

### 7.3 성능 테스트
**Load Testing (k6)**:
- 동시 사용자 100명 목표
- 평균 응답 시간 측정
- 리소스 사용률 모니터링

**Stress Testing**:
- 임계점 확인
- 장애 복구 시간 측정
- 데이터 일관성 검증

## 8. 운영 환경 스펙

### 8.1 하드웨어 요구사항
**최소 사양 (개발환경)**:
- CPU: 2 cores, 2.5GHz
- RAM: 8GB
- Storage: 50GB SSD
- Network: 100Mbps

**권장 사양 (운영환경)**:
- CPU: 8 cores, 3.0GHz
- RAM: 32GB
- Storage: 500GB NVMe SSD
- Network: 1Gbps

### 8.2 소프트웨어 요구사항
**운영체제**: Ubuntu 22.04 LTS
**Container**: Docker 24.0+, Docker Compose 2.0+
**Reverse Proxy**: Nginx 1.22+
**Database**: Redis 7.0+ (세션 스토어)

### 8.3 외부 의존성
**필수 서비스**:
- Google Cloud Speech-to-Text API
- Google Cloud Text-to-Speech API  
- OpenAI GPT-4 API

**API 사용량 제한**:
- STT: 월 1,000시간
- TTS: 월 5,000,000 characters
- GPT-4: 월 1,000,000 tokens

## 9. 마이그레이션 및 업그레이드

### 9.1 데이터 마이그레이션
**시나리오 데이터**:
- JSON 스키마 버전 관리
- 하위 호환성 보장
- 점진적 마이그레이션

### 9.2 API 버전 관리
**Versioning 전략**:
- URL 기반 버전 관리 (/api/v1/, /api/v2/)
- 하위 호환성 최소 6개월 유지
- Deprecation 사전 공지

### 9.3 배포 전략
**Blue-Green 배포**:
- 무중단 서비스 업데이트
- 즉시 롤백 가능
- 점진적 트래픽 이전

---

**문서 정보**
- 작성일: 2025-01-31
- 버전: 1.0
- 작성자: AI Assistant
- 검토자: [검토자명]
- 승인자: [승인자명]