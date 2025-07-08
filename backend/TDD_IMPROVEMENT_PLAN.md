# 디딤돌 Voice Agent - TDD 기반 시스템 개선 계획

## 📊 현재 상태 분석

### 테스트 실행 결과 (2025-07-04)
- **전체 테스트**: 45개
- **성공률**: 37.78% (17/45)
- **실패**: 2개
- **에러**: 26개
- **주요 문제점**: 테스트 인프라 구조 결함, OpenAI API 설정 문제, 서비스 초기화 오류

## 🎯 TDD 개선 전략

### 1. 테스트 우선 개발 (Test-First Development)
- **Red**: 실패하는 테스트 작성
- **Green**: 최소한의 코드로 테스트 통과
- **Refactor**: 코드 품질 개선

### 2. 단계별 개선 로드맵
각 단계마다 TDD 사이클을 완전히 완료한 후 다음 단계로 진행

---

## 🚀 Phase 1: 테스트 인프라 구조 개선 (Critical)

### 목표
- 24개의 테스트 픽스처 오류 해결
- 테스트 실행 환경 안정화
- 기본 테스트 통과율 80% 달성

### TDD 접근법

#### 1.1 테스트 픽스처 수정
**Red Phase**: 현재 실패하는 테스트
```python
# 현재 오류: missing 2 required positional arguments: 'validator' and 'mock_services'
def test_didimdol_basic_info_inquiry(validator, mock_services):
    # 테스트 실행 불가
```

**Green Phase**: 최소한의 픽스처 구현
```python
# conftest.py 수정 필요
@pytest.fixture
def validator():
    return RealisticScenarioValidator()

@pytest.fixture  
def mock_services():
    return MockServices()
```

**Refactor Phase**: 픽스처 최적화 및 재사용성 개선

#### 1.2 테스트 실행 스크립트 개선
**Red Phase**: 가상환경 활성화 없이 실행 시 실패
**Green Phase**: 자동 가상환경 활성화 구현
**Refactor Phase**: 크로스 플랫폼 지원 및 에러 처리

### 예상 결과
- 테스트 통과율: 37.78% → 80%
- 픽스처 관련 오류: 24개 → 0개

---

## 🔧 Phase 2: OpenAI API 설정 및 서비스 초기화 (Critical)

### 목표
- OpenAI API JSON 형식 오류 해결
- 서비스 초기화 실패 문제 해결
- RAG 쿼리 확장 기능 정상화

### TDD 접근법

#### 2.1 OpenAI API JSON 형식 수정
**Red Phase**: 현재 실패하는 테스트
```python
def test_openai_json_format():
    # 현재 오류: 'messages' must contain the word 'json' in some form
    response = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": "질문"}],
        response_format={"type": "json_object"}  # 실패
    )
```

**Green Phase**: 메시지에 JSON 키워드 추가
```python
def test_openai_json_format():
    response = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": "질문에 대해 JSON 형식으로 답변해주세요"}],
        response_format={"type": "json_object"}  # 성공
    )
```

**Refactor Phase**: 프롬프트 템플릿 개선 및 재사용성 증대

#### 2.2 서비스 초기화 로직 개선
**Red Phase**: 설정 파일 누락으로 서비스 초기화 실패
**Green Phase**: 기본 설정 및 fallback 메커니즘 구현
**Refactor Phase**: 의존성 주입 패턴 적용

### 예상 결과
- OpenAI API 호출 성공률: 0% → 95%
- 서비스 초기화 성공률: 60% → 100%

---

## 🎭 Phase 3: 실제 시나리오 테스트 구현 (Medium)

### 목표
- 15개 실제 한국어 대화 시나리오 100% 커버리지
- 다중 턴 대화 맥락 관리 검증
- 문화적 적절성 검증 자동화

### TDD 접근법

#### 3.1 기본 디딤돌 대출 시나리오
**Red Phase**: 실패하는 시나리오 테스트
```python
def test_didimdol_basic_conversation():
    user_input = "디딤돌 대출이 뭔가요?"
    response = agent.process_message(user_input)
    
    # 현재 실패하는 검증
    assert "디딤돌 대출" in response
    assert "만39세 이하" in response
    assert politeness_score(response) >= 0.95
```

**Green Phase**: 최소한의 응답 로직 구현
```python
def basic_didimdol_handler(user_input):
    return "디딤돌 대출은 만39세 이하 청년을 위한 주택담보대출입니다."
```

**Refactor Phase**: 템플릿 기반 응답 생성 및 컨텍스트 활용

#### 3.2 다중 턴 대화 시나리오
**Red Phase**: 컨텍스트 유지 실패
**Green Phase**: 기본 세션 상태 관리
**Refactor Phase**: 고급 컨텍스트 추론 및 개인화

### 예상 결과
- 실제 시나리오 테스트 통과율: 0% → 90%
- 한국어 정중함 점수: 측정 불가 → 95%+

---

## 🔍 Phase 4: 고급 검증 시스템 구현 (Medium)

### 목표
- AI 기반 응답 품질 자동 평가
- 실시간 성능 모니터링
- 지속적 품질 개선 파이프라인

### TDD 접근법

#### 4.1 응답 품질 검증 시스템
**Red Phase**: 품질 점수 측정 실패
```python
def test_response_quality_validation():
    response = "대출 정보를 알려드릴게요."
    quality_score = validator.validate_response(response)
    
    # 현재 실패
    assert quality_score.overall >= 0.8
    assert quality_score.politeness >= 0.95
    assert quality_score.completeness >= 0.9
```

**Green Phase**: 기본 품질 지표 구현
```python
class QualityValidator:
    def validate_response(self, response):
        return QualityScore(
            overall=self._calculate_overall_score(response),
            politeness=self._check_politeness(response),
            completeness=self._check_completeness(response)
        )
```

**Refactor Phase**: 머신러닝 기반 품질 평가 도입

### 예상 결과
- 응답 품질 자동 평가 정확도: 0% → 85%
- 실시간 품질 모니터링 가능

---

## 📈 성과 지표 및 마일스톤

### Phase 1 완료 기준
- [ ] 전체 테스트 통과율 80% 이상
- [ ] 픽스처 관련 오류 0개
- [ ] CI/CD 파이프라인 안정화

### Phase 2 완료 기준
- [ ] OpenAI API 호출 성공률 95% 이상
- [ ] 서비스 초기화 성공률 100%
- [ ] RAG 쿼리 확장 기능 정상 동작

### Phase 3 완료 기준
- [ ] 실제 시나리오 테스트 90% 이상 통과
- [ ] 한국어 정중함 검증 95% 이상
- [ ] 다중 턴 대화 컨텍스트 관리 85% 이상

### Phase 4 완료 기준
- [ ] 자동 품질 평가 시스템 구축
- [ ] 실시간 성능 모니터링 대시보드
- [ ] 지속적 개선 파이프라인 구축

---

## 🛠️ 구현 우선순위

### 즉시 시작 (이번 주)
1. **테스트 픽스처 수정** - 24개 오류 해결
2. **OpenAI API 설정 수정** - JSON 형식 오류 해결
3. **기본 서비스 초기화** - 설정 파일 및 fallback 구현

### 다음 주
1. **실제 시나리오 테스트** - 디딤돌 대출 기본 시나리오
2. **한국어 검증 시스템** - 정중함 및 문화적 적절성
3. **다중 턴 대화 테스트** - 컨텍스트 관리 검증

### 2-3주 후
1. **고급 품질 검증** - AI 기반 응답 평가
2. **성능 모니터링** - 실시간 품질 추적
3. **지속적 개선** - 자동화된 품질 개선 파이프라인

---

## 🎯 성공 측정 지표

### 현재 → 목표
- **전체 테스트 통과율**: 37.78% → 90%+
- **실제 시나리오 커버리지**: 0% → 100%
- **한국어 품질 점수**: 측정 불가 → 95%+
- **응답 시간**: 측정 필요 → <2초
- **서비스 가용성**: 60% → 99.9%

### 품질 보증 체크리스트
- [ ] 모든 테스트가 가상환경에서 실행 가능
- [ ] OpenAI API 호출이 안정적으로 동작
- [ ] 한국어 대화가 문화적으로 적절함
- [ ] 다중 턴 대화에서 컨텍스트 유지
- [ ] 오류 발생 시 적절한 fallback 동작
- [ ] 실시간 성능 모니터링 가능

---

## 📝 다음 단계

1. **Phase 1 시작**: 테스트 인프라 개선
2. **일일 TDD 사이클**: Red-Green-Refactor 반복
3. **주간 리뷰**: 진행 상황 점검 및 조정
4. **지속적 피드백**: 사용자 테스트 및 품질 개선

이 계획을 통해 체계적이고 지속 가능한 품질 개선을 달성할 수 있을 것입니다.