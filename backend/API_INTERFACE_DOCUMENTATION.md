# 디딤돌 음성 상담 에이전트 API 인터페이스 문서

**버전**: 1.1  
**작성일**: 2025-07-20  
**최종 업데이트**: 2025-08-04  
**대상**: 프론트엔드 개발자, API 사용자

## 개요

이 문서는 디딤돌 음성 상담 에이전트의 백엔드 API와 프론트엔드 간의 통신 인터페이스를 정의합니다. 백엔드는 FastAPI + LangGraph 기반으로 구축되었으며, WebSocket을 통한 실시간 통신을 지원합니다.

## 1. 기본 정보

### API 기본 URL
- **개발 환경**: `http://localhost:8000` 또는 `http://localhost:8001`
- **프로덕션**: `https://aibranch.zapto.org`

### 지원하는 통신 방식
- **WebSocket**: 실시간 음성/텍스트 대화 (`/api/v1/chat/ws/{session_id}`)
- **HTTP REST**: 추후 확장 예정

## 2. WebSocket 통신

### 2.1 연결 방법

```javascript
const sessionId = generateUUID(); // 클라이언트에서 생성
const websocket = new WebSocket(`wss://aibranch.zapto.org/api/v1/chat/ws/${sessionId}`);
```

### 2.2 연결 상태

| 상태 | 설명 |
|------|------|
| `CONNECTING` | 연결 시도 중 |
| `OPEN` | 연결 성공, 통신 가능 |
| `CLOSING` | 연결 종료 중 |
| `CLOSED` | 연결 종료됨 |

## 3. 메시지 타입 및 형식

### 3.1 클라이언트 → 서버 (송신)

#### 3.1.1 텍스트 메시지 전송
```json
{
  "type": "process_text",
  "text": "통장 만들고 싶어요",
  "input_mode": "text"
}
```

#### 3.1.2 음성 모드 활성화
```json
{
  "type": "activate_voice"
}
```

#### 3.1.3 음성 모드 비활성화
```json
{
  "type": "deactivate_voice"
}
```

#### 3.1.4 TTS 중단
```json
{
  "type": "stop_tts"
}
```

#### 3.1.5 오디오 청크 전송
- **타입**: Binary (ArrayBuffer)
- **형식**: 오디오 바이너리 데이터 (PCM, 16kHz, 16bit)

### 3.2 서버 → 클라이언트 (수신)

#### 3.2.1 세션 초기화 완료
```json
{
  "type": "session_initialized",
  "message": "안녕하세요! 신한은행 AI 금융 상담 서비스입니다."
}
```

#### 3.2.2 음성 인식 결과

**중간 결과 (실시간)**
```json
{
  "type": "stt_interim_result",
  "transcript": "통장 만들"
}
```

**최종 결과**
```json
{
  "type": "stt_final_result",
  "transcript": "통장 만들고 싶어요"
}
```

#### 3.2.3 AI 응답 스트리밍

**응답 청크**
```json
{
  "type": "llm_response_chunk",
  "chunk": "네, 입출금통장 신규 개설을 도와드리겠습니다."
}
```

**응답 완료**
```json
{
  "type": "llm_response_end",
  "full_text": "네, 입출금통장 신규 개설을 도와드리겠습니다. 현재 등록된 고객님 정보를 확인해보겠습니다."
}
```

#### 3.2.4 TTS 오디오 스트리밍

**오디오 청크**
```json
{
  "type": "tts_audio_chunk",
  "audio_chunk_base64": "UklGRiQAAABXQVZFZm10IBAAAAABA..."
}
```

**스트림 종료**
```json
{
  "type": "tts_stream_end"
}
```

#### 3.2.5 슬롯 필링 상태 업데이트
```json
{
  "type": "slot_filling_update",
  "data": {
    "product_type": "deposit_account",
    "current_stage": "greeting",
    "collected_info": {
      "customer_name": "홍길동",
      "customer_phone": "010-1234-5678",
      "confirm_personal_info": true
    },
    "required_fields": [
      {
        "key": "customer_name",
        "label": "고객명",
        "type": "string",
        "required": true,
        "collected": true
      }
    ],
    "completion_rate": 0.6
  }
}
```

#### 3.2.6 스테이지 응답 (버튼 템플릿)

사용자가 버튼으로 답변할 수 있도록 선택지를 제공하는 메시지 타입입니다.

**기본 선택지 응답**
```json
{
  "type": "stage_response",
  "stageId": "select_services",
  "responseType": "bullet",
  "prompt": "입출금 계좌는 한도계좌로만 가입할 수 있어요.\n지금 만드시는 계좌를 모바일 앱과 체크카드로 함께 이용할 수 있도록 가입해 드릴까요?",
  "choices": [
    {
      "display": "입출금 계좌 + 체크카드 + 모바일 뱅킹",
      "value": "all"
    },
    {
      "display": "입출금 계좌만",
      "value": "account_only"
    }
  ],
  "defaultChoice": "all",
  "skippable": false
}
```

**그룹화된 선택지 응답**
```json
{
  "type": "stage_response",
  "stageId": "security_medium_registration",
  "responseType": "bullet",
  "prompt": "보안매체를 선택해주세요.",
  "choiceGroups": [
    {
      "title": "내가 보유한 보안매체",
      "items": [
        {
          "value": "futuretech_19284019384",
          "label": "미래테크 19284019384",
          "display": "미래테크 19284019384",
          "default": true,
          "metadata": {
            "transfer_limit_once": "50000000",
            "transfer_limit_daily": "100000000"
          }
        }
      ]
    },
    {
      "title": "새로 발급 가능한 보안매체",
      "items": [
        {
          "value": "shinhan_otp",
          "label": "신한OTP (10,000원)",
          "display": "신한OTP (10,000원)",
          "metadata": {
            "fee": "10000"
          }
        }
      ]
    }
  ],
  "additionalQuestions": [
    "OTP가 뭐예요?",
    "보안카드와 차이점이 뭔가요?"
  ]
}
```

**불리언 선택지 응답**
```json
{
  "type": "stage_response",
  "stageId": "additional_services",
  "responseType": "boolean",
  "prompt": "중요거래 알림과 출금 알림을 모두 신청해드릴까요?",
  "choices": [
    {"key": "important_transaction_alert", "label": "중요거래 알림", "default": true},
    {"key": "withdrawal_alert", "label": "출금내역 알림", "default": true}
  ]
}
```

**응답 타입별 UI 렌더링 가이드**

| responseType | 설명 | UI 권장사항 |
|--------------|------|-------------|
| `narrative` | 자유 텍스트 입력 | 텍스트 입력 필드 표시 |
| `bullet` | 단일 선택 | 라디오 버튼 또는 선택 버튼 그룹 |
| `boolean` | 예/아니오 또는 다중 선택 | 체크박스 또는 토글 스위치 |

#### 3.2.7 오류 및 상태 메시지

**오류**
```json
{
  "type": "error",
  "message": "STT Error: 음성 인식 서비스에 연결할 수 없습니다."
}
```

**경고**
```json
{
  "type": "warning",
  "message": "음성 입력이 너무 짧습니다."
}
```

**기타 상태**
```json
{
  "type": "epd_detected"          // 음성 입력 종료 감지
}
{
  "type": "voice_activated"       // 음성 모드 활성화 확인
}
{
  "type": "voice_deactivated"     // 음성 모드 비활성화 확인
}
```

## 4. 데이터 모델

### 4.1 AgentState (핵심 상태 모델)

```typescript
interface AgentState {
  // 세션 정보
  session_id: string;
  user_input_text?: string;
  user_input_audio_b64?: string;
  
  // 상품 및 시나리오
  current_product_type?: "didimdol" | "jeonse" | "deposit_account";
  current_scenario_stage_id?: string;
  active_scenario_name?: string;
  
  // 수집된 정보
  collected_product_info: Record<string, any>;
  
  // 응답 정보
  final_response_text_for_tts?: string;
  messages: Array<HumanMessage | AIMessage>;
  
  // 오류 및 상태
  error_message?: string;
  is_final_turn_response: boolean;
}
```

### 4.2 슬롯 필링 필드 모델

```typescript
interface SmartField {
  key: string;              // 필드 식별자
  display_name: string;     // 표시명
  type: "text" | "choice" | "number" | "boolean";  // 데이터 타입
  required: boolean;        // 필수 여부
  collected: boolean;       // 수집 완료 여부
  value?: any;              // 수집된 값
  group?: string;           // 그룹명 (field_groups)
  depth?: number;           // 계층 깊이 (0: 최상위, 1: 하위)
  show_when?: string;       // 조건부 표시 (예: "parent_field == 'value'")
  parent_field?: string;    // 부모 필드 키
  choices?: Array<{         // 선택지 (type이 choice인 경우)
    value: string;
    display: string;
    default?: boolean;
  }>;
}
```

### 4.3 슬롯 필링 업데이트 상세 모델

```typescript
interface SlotFillingUpdate {
  product_type: "didimdol" | "jeonse" | "deposit_account";
  current_stage: string;           // 현재 시나리오 단계
  collected_info: Record<string, any>;  // 수집된 정보
  required_fields: SmartField[];   // 필수 필드 목록
  field_groups?: Array<{           // 필드 그룹 정보
    group_name: string;
    group_id: string;
    fields: string[];             // 그룹에 속한 필드 키 목록
  }>;
  completion_rate: number;          // 완료율 (0~1)
  scenario_name?: string;           // 시나리오 이름
  is_complete?: boolean;            // 시나리오 완료 여부
}
```

## 5. 상품 타입별 시나리오

### 5.1 지원 상품 타입

| 상품 ID | 상품명 | 시나리오 파일 | 버전 |
|---------|--------|---------------|------|
| `didimdol` | 디딤돌 대출 | `didimdol_loan_scenario.json` | v1 |
| `jeonse` | 전세 대출 | `jeonse_loan_scenario.json` | v1 |
| `deposit_account` | 입출금통장 | `deposit_account_scenario_v3.json` | v3 (최신) |

**참고**: 입출금통장은 v1, v2, v3 버전이 있으며, 현재 v3가 사용됩니다.

### 5.2 시나리오 단계 구조 (v3)

```json
{
  "scenario_id": "deposit_account_concurrent",
  "scenario_name": "입출금 동시신규",
  "product_type": "deposit_account",
  "initial_stage_id": "select_services",
  "stages": {
    "select_services": {
      "stage_id": "select_services",
      "stage_name": "필요 업무 확인",
      "response_type": "bullet",
      "prompt": "입출금 계좌는 한도계좌로만 가입할 수 있어요...",
      "choices": [
        {
          "display": "입출금 계좌 + 체크카드 + 모바일 뱅킹",
          "value": "all",
          "default": true
        }
      ],
      "fields_to_collect": ["services_selected"],
      "next_step": {
        "all": "confirm_personal_info",
        "mobile_only": "confirm_personal_info"
      }
    }
  }
}
```

### 5.3 시나리오 필드 수집 방식

시나리오는 다음과 같은 방식으로 정보를 수집합니다:

1. **단계별 진행**: 각 stage에서 특정 필드를 수집
2. **조건부 분기**: 사용자 응답에 따라 다음 단계 결정
3. **동적 프롬프트**: `{default_choice}` 같은 템플릿 변수 치환
4. **선택지 그룹화**: `choice_groups`로 관련 선택지 묶음

## 6. 오류 처리

### 6.1 연결 오류

| 오류 코드 | 설명 | 대응 방안 |
|-----------|------|-----------|
| 1000 | 정상 종료 | 재연결 불필요 |
| 1001 | 클라이언트 종료 | 재연결 불필요 |
| 1006 | 비정상 종료 | 자동 재연결 시도 |
| 1015 | TLS 오류 | SSL 인증서 확인 |

### 6.2 서비스 오류

```json
{
  "type": "error",
  "message": "LLM service is not initialized. Please check API key."
}
```

일반적인 오류 메시지:
- `"STT Error: ..."` - 음성 인식 서비스 오류
- `"TTS Error: ..."` - 음성 합성 서비스 오류
- `"LLM Error: ..."` - AI 모델 처리 오류
- `"세션 정보를 찾을 수 없습니다."` - 세션 상태 오류

## 7. 개발 환경 설정

### 7.1 환경 변수

**백엔드 (.env)**
```env
OPENAI_API_KEY=your_openai_api_key
GOOGLE_APPLICATION_CREDENTIALS=/path/to/google-credentials.json
```

**프론트엔드 (.env.development)**
```env
VITE_API_BASE_URL=http://localhost:8000
VITE_WEBSOCKET_URL=ws://localhost:8000
```

### 7.2 CORS 설정

백엔드에서 허용된 Origin:
- `http://localhost:5173` (Vite 개발 서버)
- `http://127.0.0.1:5173`
- `https://aibranch.zapto.org`

## 8. 사용 예시

### 8.1 기본 텍스트 대화 플로우

```javascript
// 1. WebSocket 연결
const ws = new WebSocket('ws://localhost:8000/api/v1/chat/ws/session123');

// 2. 연결 완료 대기
ws.onopen = () => {
  console.log('WebSocket 연결됨');
};

// 3. 메시지 수신 처리
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  switch(data.type) {
    case 'session_initialized':
      console.log('세션 초기화:', data.message);
      break;
    case 'llm_response_chunk':
      // AI 응답 실시간 표시
      updateResponseText(data.chunk);
      break;
    case 'slot_filling_update':
      // 슬롯 필링 상태 업데이트
      updateSlotFillingUI(data.data);
      break;
  }
};

// 4. 텍스트 메시지 전송
function sendMessage(text) {
  ws.send(JSON.stringify({
    type: 'process_text',
    text: text,
    input_mode: 'text'
  }));
}
```

### 8.2 음성 모드 사용

```javascript
// 음성 모드 활성화
function activateVoice() {
  ws.send(JSON.stringify({ type: 'activate_voice' }));
}

// 오디오 데이터 전송
function sendAudioChunk(audioBuffer) {
  ws.send(audioBuffer); // ArrayBuffer 직접 전송
}

// 음성 모드 비활성화
function deactivateVoice() {
  ws.send(JSON.stringify({ type: 'deactivate_voice' }));
}
```

## 9. 성능 고려사항

### 9.1 WebSocket 최적화
- **재연결 정책**: 지수 백오프 알고리즘 사용
- **하트비트**: 30초마다 ping/pong 확인
- **메시지 큐**: 연결 끊김 시 메시지 보관 및 재전송

### 9.2 오디오 처리
- **오디오 청크 크기**: 1024 샘플 (약 64ms)
- **샘플링 레이트**: 16kHz
- **비트 깊이**: 16bit
- **채널**: 모노

### 9.3 메모리 관리
- **세션 상태**: 메모리 내 저장 (추후 Redis 확장)
- **오디오 버퍼**: 순환 버퍼 사용으로 메모리 절약
- **메시지 히스토리**: 최대 50개 메시지 유지

## 10. 보안 고려사항

### 10.1 인증 (추후 구현)
- JWT 토큰 기반 인증
- 세션별 권한 관리

### 10.2 데이터 보호
- 음성 데이터: 실시간 처리 후 즉시 삭제
- 개인정보: 암호화 저장
- 로그: 민감 정보 마스킹

---

## 문의 및 지원

이 문서에 대한 문의사항이나 API 사용 중 문제가 발생하면 백엔드 개발팀에 문의하시기 바랍니다.

**문서 버전**: 1.1  
**최종 업데이트**: 2025-08-04  
**변경 이력**:
- v1.1 (2025-08-04): stage_response 메시지 타입 추가, 버튼 템플릿 구조 문서화, 슬롯 필링 모델 상세화
- v1.0 (2025-07-20): 최초 작성