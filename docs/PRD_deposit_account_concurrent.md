# 입출금 동시신규 시나리오 PRD

## 1. 개요

### 1.1 목적
은행 입출금 계좌 신규 개설 시 전자금융(모바일 앱)과 체크카드를 동시에 신청할 수 있는 음성 상담 시나리오를 정의한다.

### 1.2 범위
- 입출금 계좌 개설
- 전자금융(모바일 앱) 가입
- 체크카드 발급
- 개인정보 확인 및 수정

## 2. 시나리오 플로우

### Step 1: 필요 업무 확인
**응답 타입**: 블릿 (bullet)
**음성/터치 인터랙션**: 모두 지원
**기본값**: "모두 가입할게요"

**LLM 응답**:
```
입출금 계좌는 한도계좌로만 가입할 수 있어요.
지금 만드시는 계좌를 모바일 앱과 체크카드로 함께 이용할 수 있도록 가입해 드릴까요?
```

**선택지**:
- 모두 가입할게요 *default
- 모바일 앱만
- 체크카드만
- 입출금 계좌만

**추가 질문 예시**:
- 한도 제한 계좌 해제 방법 알려줘
- 한도가 어느정도 제한되는지 알려줘

### Step 2: 고객 정보 확인
**조건**: Step 1에서 "모두 가입할게요" 선택 시
**응답 타입**: 줄글 (narrative)

**LLM 응답**:
```
네, 먼저 고객님의 개인정보를 확인하겠습니다. 화면에 보이는 내용이 모두 맞으신가요?
```

**표시 정보**:
- 이름: 김신한
- 영문이름: KIM SHINHAN
- 주민등록번호: 880122-*******
- 휴대폰번호: 010-1234-OOOO
- 이메일: shinhan11@naver.com
- 집주소: 서울 중구 소공로 센트레빌 201동 201호
- 직장주소: 서울 중구 소공로 35-1 7층

### Step 3: (전자금융) 보안매체 등록_보유 고객
**조건**: Step 2에서 정보가 모두 맞을 경우
**응답 타입**: 그룹 블릿 (grouped bullet)
**음성/터치 인터랙션**: 모두 지원
**기본값**: "미래테크 19284019384"

**LLM 응답**:
```
이어서 보안매체 등록을 진행할게요.
고객님이 보유하신 {default}는 1회 5,000만원, 1일 1억까지 이체할 수 있어요.
이걸로 등록할까요?
```

**선택지**:
**내가 보유한 보안매체**
- 미래테크 19284019384 *default
- 코마스(RSA) 12930295

**새로 발급 가능한 보안매체**
- 보안카드
- 신한OTP (10,000원)

### Step 4: (전자금융) 추가 정보 선택
**응답 타입**: 줄글 (narrative)

**LLM 응답**:
```
추가 신청 정보를 확인할게요. 중요거래 알림과 출금 알림, 해외 IP 이체 제한을 모두 신청해 드릴까요?
```

### Step 5: (체크카드) 카드 선택
**응답 타입**: 카드 리스트 (card list)
**음성/터치 인터랙션**: 모두 지원
**UI 특징**: 좌우 스와이프로 추가 카드 확인
**기본값**: "S-Line 체크카드 (후불교통)"

**LLM 응답**:
```
이어서 체크카드 발급에 필요한 정보를 확인할게요.
지금 바로 수령할 수 있는 {default}로 발급해드릴까요?
```

**카드 목록**:
1. S-Line 체크카드 (후불교통) *default
2. S-Line 체크카드 (일반)
3. 신한 Deep Dream 체크카드 (후불교통)
4. 신한 Deep Dream 체크카드 (일반)
5. 신한카드 Hey Young 체크카드 (일반)

**추가 질문 예시**:
- 배송되는 카드로 보여줘
- 후불 교통 카드 기능이 있는 카드만 보여줘

### Step 6: (체크카드) 명세서 수령 정보 선택
**응답 타입**: 블릿 (bullet)
**음성/터치 인터랙션**: 모두 지원
**기본값**: "휴대폰"

**LLM 응답**:
```
카드 명세서는 매월 10일에 휴대폰으로 받아보시겠어요?
```

**명세서 수령방법**:
- 휴대폰 *default
- 이메일
- 홈페이지

### Step 7: (체크카드) 카드 사용 알림
**응답 타입**: 블릿 (bullet)
**음성/터치 인터랙션**: 모두 지원
**기본값**: "5만원 이상 결제시 발송 (무료)"

**LLM 응답**:
```
5만원 이상 결제 시 문자로 사용하신 내역을 보내드릴까요?
```

**카드 사용 알림 문자 서비스**:
- 5만원 이상 결제시 발송 (무료) *default
- 모든 내역 발송 (200원, 포인트 우선 차감)
- 문자 받지 않음

### Step 8: (체크카드) 카드 비밀번호 설정
**응답 타입**: 줄글 (narrative)

**LLM 응답**:
```
마지막으로 카드 비밀번호는 계좌 비밀번호와 동일하게 설정하시겠어요?
```

### Step 9: LLM 상담 완료
**응답 타입**: 줄글 (narrative)

**LLM 응답**:
```
말씀해주신 정보로 가입 도와드릴게요.
입력 화면으로 이동하겠습니다.
```

## 3. 조건부 플로우

### 3.1 기본값 외 선택 시
모든 단계에서 기본값이 아닌 다른 값이 선택되면:
- LLM 응답: "선택된 값으로 해드리겠습니다"

### 3.2 Step 1 선택에 따른 분기
1. **"모바일 앱만" 선택 시**
   - 전자금융 단계만 진행 (Step 2, 3, 4 → Step 9)
   - 체크카드 단계 생략 (Step 5, 6, 7, 8 생략)

2. **"체크카드만" 선택 시**
   - 체크카드 단계만 진행 (Step 2, 5, 6, 7, 8 → Step 9)
   - 전자금융 단계 생략 (Step 3, 4 생략)

3. **"입출금 계좌만" 선택 시**
   - 바로 Step 9로 이동
   - 전자금융/체크카드 단계 모두 생략

### 3.3 정보 수정 처리
- **Step 2**: 정보 수정 요청 시
  - LLM 응답: "[은행 고객정보 변경]화면으로 이동"

### 3.4 추가 옵션 처리
- **Step 3**: 이체한도 수정 요청 가능
- **Step 4**: 3가지 항목 중 일부만 신청 가능

## 4. Slot Filling 구조

### 4.1 표시 원칙
- 각 그룹과 항목들을 slot으로 표시
- 사용자 응답에 따라 slot에 값 채움
- 현재 진행 중인 step에 해당하는 그룹만 표시
- 그룹의 모든 항목이 채워지면 그룹명만 표시하고 항목 접기

### 4.2 그룹 정의

#### Group 1: 개인정보 확인
- **대상 Step**: Step 2
- **항목**:
  - 이름 (텍스트)
  - 영문이름 (텍스트)
  - 주민등록번호 (텍스트)
  - 휴대폰번호 (텍스트)
  - 이메일 (텍스트)
  - 집주소 (텍스트)
  - 직장주소 (텍스트)

#### Group 2: 보안매체 등록
- **대상 Step**: Step 3
- **항목**:
  - 보안매체 (텍스트)
  - 1회 이체한도 (텍스트)
  - 1일 이체한도 (텍스트)

#### Group 3: 추가 정보 선택
- **대상 Step**: Step 4
- **항목**:
  - 중요거래 통보 (신청/미신청)
  - 출금내역 통보 (신청/미신청)
  - 해외IP이체 제한 (신청/미신청)

#### Group 4: 카드 선택
- **대상 Step**: Step 5
- **항목**:
  - 카드 수령 방법 (텍스트)
  - 카드 선택 (텍스트)
  - 후불 교통 기능 (예/아니요)

#### Group 5: 명세서 수령 정보
- **대상 Step**: Step 6
- **항목**:
  - 명세서 수령방법 (텍스트)
  - 명세서 수령일 (텍스트)

#### Group 6: 카드 사용 알림
- **대상 Step**: Step 7
- **항목**:
  - 카드 사용 알림 (텍스트)

#### Group 7: 카드 비밀번호 설정
- **대상 Step**: Step 8
- **항목**:
  - 카드 비밀번호 (예/아니요)

## 5. 기술 요구사항

### 5.1 응답 타입
- **narrative**: 일반 텍스트 응답
- **bullet**: 단일 선택지 목록
- **grouped bullet**: 그룹으로 구분된 선택지 목록
- **card list**: 좌우 스와이프 가능한 카드 형태 목록

### 5.2 인터랙션
- 음성 인식 및 응답
- 터치/클릭 입력 지원
- 기본값 자동 선택 및 표시

### 5.3 상태 관리
- 각 단계별 선택 결과 저장
- 조건부 플로우 처리
- Slot filling 실시간 업데이트

## 6. 예외 처리

### 6.1 타임아웃
- 각 단계별 응답 대기 시간 설정
- 타임아웃 시 재질문 또는 기본값 선택

### 6.2 오류 처리
- 잘못된 입력 시 재입력 요청
- 시스템 오류 시 안내 메시지 표시

### 6.3 취소/이탈
- 상담 중단 시 진행 상황 저장
- 재접속 시 이어서 진행 옵션 제공