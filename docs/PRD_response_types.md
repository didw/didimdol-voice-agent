# PRD: 입출금통장 개설 시나리오 답변 유형 시스템

## 1. 개요

### 1.1 목적
입출금통장 개설 과정에서 각 단계별로 사용자에게 최적화된 답변 형태를 제공하여 상담 효율성과 사용자 경험을 향상시킨다.

### 1.2 범위
- 입출금통장(deposit_account) 시나리오의 각 단계별 답변 유형 정의
- 음성 및 UI 인터랙션을 고려한 답변 형태 구분
- 사용자의 정보 수정 및 단계 건너뛰기 기능 포함

## 2. 답변 유형 정의

### 2.1 줄글 형태 (narrative)
- 일반적인 대화형 문장으로 정보 전달
- 단순 확인이나 안내가 필요한 경우 사용

### 2.2 블릿 형태 (bullet)
- 선택지를 명확히 제시하여 음성/터치 모두 가능
- 여러 옵션 중 선택이 필요한 경우 사용

### 2.3 True/False 형태 (boolean)
- 신청/미신청 등 이진 선택
- 터치 시 토글 형태로 선택 가능

## 3. 단계별 상세 명세

### Step 0: 한도제한계좌안내
- **답변 유형**: 줄글 형태
- **예시 답변**: "입출금 계좌 가입을 도와드릴게요. 통장은 한도계좌로 먼저 개설되며, 서류지참시 일반 계좌로 전환가능합니다. 한도계좌로 개설 진행해 드릴까요?"

### Step 1: 고객정보확인
- **답변 유형**: 줄글 형태
- **예시 답변**: 
  ```
  감사합니다. 그럼 한도계좌로 입출금 통장 개설 도와드릴게요. 
  제가 가지고 있는 정보는 다음과 같습니다. 아래 내용이 모두 맞으신가요?
  - 성함: 홍길동
  - 연락처: 010-1234-5678
  - 집주소: 서울특별시 종로구 숭인동 123
  ```
- **정보 수정 가능**: 각 항목별로 수정 요청 시 처리

### Step 2: 평생계좌 등록확인
- **답변 유형**: 줄글 형태
- **예시 답변**: "다음으로, 통장 개설 시 평생 계좌 등록여부를 선택하실 수 있습니다. 평생계좌로 등록하시겠어요?"
- **건너뛰기 가능**: 사용자가 원하지 않으면 다음 단계로

### Step 3: 전자금융_신규
- **답변 유형**: 줄글 형태
- **예시 답변**: "쏠이나 인터넷에서도 개설하시는 통장 사용할 수 있도록 도와드릴까요?"
- **건너뛰기 가능**: 사용자가 원하지 않으면 Step 4로

#### Step 3-1: 보안매체 선택
- **답변 유형**: 블릿 형태
- **예시 답변**:
  ```
  보안매체는 어떤걸로 하시겠어요?
  - 보안카드
  - 신한 OTP
  - 타행 OTP
  ```
- **인터랙션**: 음성 및 터치/클릭 모두 가능

##### Step 3-1-1: 타행 보안매체 선택 (조건부)
- **조건**: Step 3-1에서 "타행 OTP" 선택 시
- **답변 유형**: 줄글 형태
- **예시 답변**: "타행 OTP의 제조사와 일련번호를 말씀해주세요."

#### Step 3-2: 이체한도 설정
- **답변 유형**: 줄글 형태
- **예시 답변**: "이체 한도를 말씀해주세요. (1회 이체한도 최대 5천만원, 1일 이체한도 최대 1억원)"

#### Step 3-3: 알림설정
- **답변 유형**: True/False 형태
- **예시 답변**:
  ```
  중요거래 알림, 출금내역 알림, 해외IP 제한 여부를 말씀해주세요.
  - 중요거래 알림 [신청 / 미신청]
  - 출금내역 알림 [신청 / 미신청]
  - 해외IP 제한 [신청 / 미신청]
  ```
- **인터랙션**: 음성 및 터치/클릭 (토글) 가능

### Step 4: 체크카드_신규
- **답변 유형**: 줄글 형태
- **예시 답변**: "체크카드 신청을 도와드릴까요?"
- **건너뛰기 가능**: 사용자가 원하지 않으면 Step 5로

#### Step 4-1: 체크카드_수령방법
- **답변 유형**: 블릿 형태
- **예시 답변**:
  ```
  체크카드 수령 방법을 선택해주세요.
  - 즉시수령
  - 배송(자택/직장)
  ```
- **인터랙션**: 음성 및 터치/클릭 모두 가능

#### Step 4-2: 체크카드_카드종류
- **답변 유형**: 블릿 형태
- **예시 답변**:
  ```
  {4-1에서 선택한 값: 즉시수령|배송} 가능한 카드를 보여드릴게요. 
  어떤 카드로 발급하시겠어요?
  - S-Line 카드
  - Deep Dream 카드
  - Shinhan Good 카드
  ```
- **동적 콘텐츠**: 수령 방법에 따라 선택 가능한 카드 목록 변경

#### Step 4-3: 체크카드_후불교통기능
- **답변 유형**: 줄글 형태
- **예시 답변**: "후불 교통 기능을 추가해드릴까요?"

#### Step 4-4: 체크카드_명세서수령방법
- **답변 유형**: 블릿 형태
- **예시 답변**:
  ```
  카드 명세서 수령 방법을 선택해주세요.
  - 휴대폰
  - 이메일
  - 홈페이지
  ```
- **인터랙션**: 음성 및 터치/클릭 모두 가능

#### Step 4-5: 체크카드_사용알림문자서비스
- **답변 유형**: 블릿 형태
- **예시 답변**:
  ```
  카드 사용 알림 문자 서비스를 선택해주세요.
  - 선택안함
  - 모든 내용 발송 (200원)
  - 5만원 이상 결제시 발송 (무료)
  ```
- **인터랙션**: 음성 및 터치/클릭 모두 가능

### Step 5: 선택한 정보 확인
- **답변 유형**: 줄글 형태
- **예시 답변**: "아래 정보들로 입출금 통장 가입을 도와드릴까요? {각 step마다 선택한 값들}"
- **동적 콘텐츠**: 이전 단계에서 수집/선택한 모든 정보 요약 표시

### Step 6: 상담 종료
- **답변 유형**: 줄글 형태
- **예시 답변**: "상담을 종료하고 입출금 통장 가입을 도와드리겠습니다."

## 4. 핵심 기능 요구사항

### 4.1 정보 수정 기능
- 모든 단계에서 사용자가 정보 수정을 요청할 수 있음
- 수정 완료 후 현재 단계를 다시 진행하거나 다음 단계로 이동

### 4.2 단계 건너뛰기
- Step 2, 3(하위 포함), 4(하위 포함)는 선택적 단계
- 사용자가 원하지 않으면 다음 필수 단계로 이동

### 4.3 답변 유형별 처리
- **narrative**: 일반 텍스트 응답
- **bullet**: 선택지 포함 응답 (음성/UI 모두 지원)
- **boolean**: 토글 형태 응답 (음성/UI 모두 지원)

### 4.4 부분 응답 처리 및 유효성 검증
- **부분 응답 처리**: 여러 정보를 요구하는 질문에 고객이 일부만 대답한 경우
  - 이미 제공된 정보는 저장하고 인정
  - 누락된 정보만 재질문하여 효율적인 정보 수집
  - 예시: "이체한도를 말씀해주세요" → 고객이 "1회 500만원"만 답변 → "1일 이체한도도 함께 말씀해주세요"
  
- **유효성 검증 및 재질문**: 부적절하거나 유효하지 않은 값을 받은 경우
  - 입력값의 범위, 형식, 타입을 검증
  - 검증 실패 시 구체적인 안내와 함께 재질문
  - 예시: 
    - "1회 이체한도 1억원" → "1회 이체한도는 최대 5천만원까지 가능합니다. 5천만원 이하로 다시 말씀해주세요"
    - "전화번호 1234" → "올바른 휴대폰 번호 형식으로 다시 말씀해주세요. 예: 010-1234-5678"
  
- **진행상황 피드백**: 부분적으로 정보가 수집될 때마다 고객에게 진행상황 제공
  - "1회 이체한도 500만원으로 설정했습니다. 1일 이체한도도 말씀해주세요"

## 5. 기술 구현 방안

### 5.1 시나리오 JSON 구조 확장
```json
{
  "stages": {
    "stage_id": {
      "response_type": "narrative|bullet|boolean",
      "prompt": "...",
      "choices": [...],  // bullet/boolean 타입인 경우
      "skippable": true|false,
      "modifiable_fields": [...]
    }
  }
}
```

### 5.2 Frontend UI 컴포넌트
- 답변 유형에 따른 동적 UI 렌더링
- 터치/클릭 가능한 인터랙티브 요소 구현

### 5.3 Backend 처리
- 답변 유형 정보를 WebSocket 메시지에 포함
- 사용자 입력을 답변 유형에 맞게 파싱
- 부분 응답 처리 로직:
  - Entity Agent를 통한 개별 필드 추출
  - 수집된 필드와 미수집 필드 구분
  - 미수집 필드만을 위한 재질문 생성
- 유효성 검증 로직:
  - 각 필드별 validation 규칙 정의
  - 검증 실패 시 구체적인 오류 메시지와 재질문 생성

## 6. 웹 UI Slot Filling 기능

### 6.1 기능 개요
웹 인터페이스에서 사용자의 정보 수집 현황을 실시간으로 표시하고 관리하는 기능

### 6.2 주요 기능

#### 6.2.1 단계별 Slot 표시
- **현재 단계 기반 노출**: 진행 중인 Step에 해당하는 slot만 선별적으로 표시
- **점진적 공개**: 대화 진행에 따라 관련 필드들이 단계적으로 노출
- **계층적 구조**: 상위 선택(예: 인터넷뱅킹 가입)에 따른 하위 필드들 자동 표시

```
예시:
Step 3-1: 인터넷뱅킹 가입 → use_internet_banking 필드만 표시
Step 3-2: 보안매체 선택 → security_medium, initial_password 등 하위 필드 추가 표시
```

#### 6.2.2 실시간 Slot Value 업데이트
- **자동 추출**: 사용자 음성/텍스트 입력에서 Entity Agent가 자동으로 정보 추출
- **즉시 반영**: 추출된 값이 해당 slot에 실시간으로 표시
- **완료 상태 표시**: 수집 완료된 필드와 미완료 필드를 시각적으로 구분

#### 6.2.3 사용자 쿼리 기반 Slot 수정
- **직접 수정 요청**: "전화번호를 010-1234-5678로 바꿔주세요" 등의 수정 요청 처리
- **대조 표현 처리**: "전화번호는 010-9999-8888이 아니라 010-1111-2222입니다" 형태 지원
- **실시간 업데이트**: 수정 요청 즉시 slot 값 변경 및 화면 반영

### 6.3 UI/UX 명세

#### 6.3.1 Slot 표시 형태
```
[기본정보]
✓ 성함: 홍길동
✓ 연락처: 010-1234-5678
○ 집주소: 미입력

[인터넷뱅킹]
✓ 가입여부: 신청
○ 보안매체: 미입력
○ 초기비밀번호: 미입력
```

#### 6.3.2 단계별 노출 정책
- **Step 1 (개인정보)**: 기본정보 필드들만 표시
- **Step 2 (이체한도)**: 이체한도 관련 필드 추가
- **Step 3 (부가서비스)**: 선택한 서비스의 하위 필드들 표시
- **Step 4 (확인)**: 모든 수집된 정보 종합 표시

#### 6.3.3 상태 표시
- **완료 (✓)**: 값이 정상 수집된 필드
- **미입력 (○)**: 아직 값이 수집되지 않은 필드
- **수정필요 (!)**: 유효성 검증 실패한 필드

#### 6.3.4 진행률 표시 (Progress Bar)
- **전체 대비 수집 비율**: 전체 필수 정보 중 수집 완료된 정보의 비율을 백분율로 표시
- **실시간 업데이트**: 정보가 수집될 때마다 진행률 자동 갱신
- **시각적 피드백**: 프로그레스 바 형태로 진행 상황을 직관적으로 표시

```
예시:
정보 수집 현황: [■■■■■■■□□□] 70%
수집 완료: 7개 / 전체: 10개
```

##### 진행률 계산 방식
- **분자**: 현재 표시된 필드 중 값이 수집된 필드 개수
- **분모**: 현재 단계에서 표시된 전체 필수 필드 개수
- **계산식**: (수집 완료 필드 수 / 전체 필수 필드 수) × 100

##### UI 구현 예시
```vue
<div class="progress-container">
  <div class="progress-header">
    <span>정보 수집 현황</span>
    <span class="progress-percentage">{{ completionRate }}%</span>
  </div>
  <div class="progress-bar">
    <div class="progress-fill" :style="{ width: completionRate + '%' }"></div>
  </div>
  <div class="progress-detail">
    수집 완료: {{ completedCount }}개 / 전체: {{ totalCount }}개
  </div>
</div>
```

### 6.4 기술 구현

#### 6.4.1 Backend 처리
```python
def update_slot_filling_with_hierarchy(scenario_data, collected_info, current_stage):
    # 현재 단계에 맞는 필드들만 선별
    visible_fields = get_contextual_visible_fields(scenario_data, collected_info, current_stage)
    
    # 실시간 완료 상태 계산
    completion_status = calculate_field_completion(visible_fields, collected_info)
    
    # 진행률 계산 (표시되는 필수 필드 기준)
    required_visible_fields = [f for f in visible_fields if f.get("required", True)]
    total_required = len(required_visible_fields)
    completed_required = sum(1 for f in required_visible_fields if completion_status.get(f["key"], False))
    completion_rate = (completed_required / total_required * 100) if total_required > 0 else 0
    
    # WebSocket으로 프론트엔드에 전송
    return {
        "type": "slot_filling_update",
        "visible_fields": visible_fields,
        "collected_info": collected_info,
        "completion_status": completion_status,
        "completion_rate": round(completion_rate, 1),
        "completed_count": completed_required,
        "total_count": total_required,
        "current_stage": current_stage
    }
```

#### 6.4.2 Frontend 처리
```typescript
// SlotFillingStore에서 진행률 관리
interface SlotFillingState {
  completionRate: number
  completedCount: number
  totalCount: number
  // ... 기타 상태
}

// 실시간 slot 및 진행률 업데이트
watch(() => slotFillingStore.collectedInfo, (newInfo) => {
  updateSlotDisplay(newInfo)
  updateProgressBar(slotFillingStore.completionRate)
}, { deep: true })

// 진행률 바 컴포넌트
const ProgressBar = {
  template: `
    <div class="progress-section">
      <div class="progress-header">
        <h3>정보 수집 현황</h3>
        <span class="percentage">{{ completionRate }}%</span>
      </div>
      <div class="progress-bar-container">
        <div class="progress-bar-fill" 
             :style="{ width: completionRate + '%' }"
             :class="{ 'complete': completionRate === 100 }">
        </div>
      </div>
      <p class="progress-detail">
        수집 완료: {{ completedCount }}개 / 전체: {{ totalCount }}개
      </p>
    </div>
  `
}

// 사용자 수정 요청 처리
const handleUserModification = (field: string, newValue: any) => {
  chatStore.sendModificationRequest(field, newValue)
}
```

### 6.5 사용자 시나리오

#### 6.5.1 정보 수집 과정
1. **Step 시작**: 해당 단계의 slot들이 "미입력" 상태로 표시
2. **음성 입력**: 사용자가 정보를 말하면 Entity Agent가 추출
3. **실시간 반영**: 추출된 정보가 즉시 slot에 표시
4. **완료 확인**: 모든 필수 정보 수집 시 다음 단계로 진행

#### 6.5.2 정보 수정 과정
1. **수정 요청**: "전화번호를 다른 번호로 바꿔주세요"
2. **현재 값 표시**: "현재 010-1234-5678로 등록되어 있습니다"
3. **새 값 입력**: 사용자가 새로운 전화번호 제공
4. **즉시 업데이트**: slot에 새로운 값 반영

## 7. 예상 효과
- 사용자 경험 향상: 각 단계에 최적화된 인터랙션 제공
- 상담 효율성 증대: 명확한 선택지 제시로 빠른 진행
- 오류 감소: 구조화된 입력으로 잘못된 응답 최소화
- **정보 투명성**: 실시간 slot 표시로 수집 현황 명확 파악
- **수정 용이성**: 언제든지 정보 수정 가능한 유연한 시스템
- **단계별 최적화**: 현재 진행 단계에 집중할 수 있는 UI 제공
- **진행 상황 가시화**: 프로그레스 바를 통한 전체 진행률 직관적 파악
- **동기 부여**: 완료율 표시로 사용자의 작업 완수 의욕 고취