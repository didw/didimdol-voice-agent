# LangGraph 에이전트 리팩터링 Phase 1 – PRD

## 1. 배경
`backend/app/graph/agent.py` 파일은 1,000+ 라인으로 규모가 커 유지보수가 어렵습니다. 또한 `print` 기반 로깅, 동적 상태 객체, 부족한 아키텍처 문서가 기술 부채로 확인되었습니다.

## 2. 목표 (Scope)
1. **모듈 분리** – `agent.py` 내 노드를 `app/graph/nodes/` 폴더로 이전하고 `router.py`, `logger.py` 생성.
   - 노드를 orchestrator, workers, control 카테고리로 분류
   - 기존 import 경로 호환성을 위한 re-export 유지
2. **중앙 집중 로깅** – 모든 `print` 호출을 `LogManager`(PII 마스킹 지원)로 교체.
   - 비동기 로깅 래퍼 구현으로 성능 저하 방지
3. **정적 상태 모델** – `AgentState`를 `pydantic.BaseModel(extra="forbid")`로 재정의, turn-specific 서브모델 분리.
   - SessionState와 TurnState로 명확히 구분
   - 시나리오 연속성 관리 로직을 state_manager.py로 추출
4. **문서화 강화** – 최상위 `README`에 시스템 다이어그램, 노드 책임, 상태 변수 설명 추가.

## 3. 비-목표 (Out-of-Scope)
- LangGraph 로직 자체의 기능 변경
- 새로운 기능(시나리오, 서비스) 추가
- 프론트엔드 Vue 코드 변경

## 4. 이해관계자
- AI Architect (주 개발자)
- QA 팀
- DevOps (로깅 파이프라인 모니터링)

## 5. 성공 지표 (KPI)
- `agent.py` 코드 라인 < 200 라인
- `print` 0건, `LogManager` 커버리지 100 %
- `AgentState` 모델 테스트 커버리지 ≥ 90 %
- README CI 링커·맞춤법 오류 0건

## 6. 일정(예상)
| 단계 | 기간 | 산출물 |
| --- | --- | --- |
| 설계 & 문서 | Day 0–1 | PRD, TRD |
| 구현 | Day 2–5 | 모듈 코드, 테스트 |
| 리뷰 & QA | Day 6–7 | PR 머지 |

## 7. 리스크 및 완화책
- **단계적 마이그레이션 실패** → Feature flag 도입하여 신/구 흐름 전환 가능
- **로깅 성능 저하** → 비동기 로거 활용, 샘플링 전략 적용
- **테스트 호환성 문제** → agent.py에 임시 re-export 레이어 유지
- **동적 import 의존성** → entity_agent, chat_utils 정적 import로 전환
