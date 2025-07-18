# 백엔드 (Python FastAPI & LangGraph)

## 실행 방법
```bash
# 로컬 개발
uvicorn app.main:app --reload --port 8001

# 프로덕션 (외부 접속)
uvicorn app.main:app --reload --port 8000
```

⏺ 백엔드 에이전트 플로우 분석 결과

  1. 아키텍처 개요

  - Orchestration-Worker 패턴: 메인 오케스트레이터가 작업을 전문 워커들에게 분배
  - LangGraph 기반: 상태 관리와 노드 간 전환을 그래프 구조로 관리
  - 모듈화된 노드 구조: 각 기능별로 독립된 노드로 분리

  2. 입출금통장 개설 대화 흐름

  단계별 진행:

  1. 초기 인사 (greeting)
    - 고객 정보 확인 (이름: 홍길동, 연락처: 010-1234-5678)
    - 개인정보 확인 여부 질문
  2. 평생계좌 선택 (ask_lifelong_account)
    - 평생계좌번호 등록 여부 질문
    - 사용자 응답에 따라 boolean 값 저장
  3. 인터넷뱅킹 가입 (ask_internet_banking)
    - 인터넷뱅킹 가입 의사 확인
    - "네" 응답시 상세 정보 수집 단계로 전환
  4. 인터넷뱅킹 정보 수집 (collect_internet_banking_info)
    - 다중 정보 수집 모드 활성화
    - 보안매체, 이체한도, 알림설정 등 한번에 수집
    - Entity Agent가 사용자 발화에서 정보 추출
  5. 체크카드 신청 (ask_check_card)
    - 체크카드 신청 여부 확인
    - 추가 정보 수집 프로세스 진행
  6. 최종 요약 (final_summary)
    - 수집된 모든 정보 요약 제시
    - 수정 사항 확인

  3. 핵심 처리 메커니즘

  Entity Agent 활용:

  - extraction_prompt 필드 기반 정보 추출
  - LLM과 패턴 매칭 병행 사용
  - 추출된 정보 검증 프로세스

  상태 관리 (AgentState):

  - Pydantic 모델로 타입 안전성 확보
  - collected_product_info: 수집된 정보 저장
  - current_scenario_stage_id: 현재 단계 추적
  - scenario_agent_output: NLU 결과 저장

  대화 연속성:

  - 시나리오 단계별 전환 로직
  - 조건부 분기 처리 (transitions)
  - 필수 정보 완료 여부 확인

  4. 워크플로우 노드 구조

  entry_point_node → main_agent_router_node
                           ↓
                 scenario_worker → scenario_flow_worker
                           ↓
                  synthesize_response_node → END

  각 노드는 특정 역할 수행:
  - scenario_worker: 사용자 의도/개체 추출
  - scenario_flow_worker: 시나리오 로직 처리 및 정보 수집
  - synthesize_response_node: 최종 응답 생성