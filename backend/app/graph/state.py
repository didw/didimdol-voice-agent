# backend/app/graph/state.py

from typing import Dict, TypedDict, Optional, Sequence, Literal, Any, List
from langchain_core.messages import BaseMessage

# Scenario Agent의 예상 출력 구조
class ScenarioAgentOutput(TypedDict, total=False):
    intent: Optional[str]                   # 예: "provide_income", "confirm_eligibility", "ask_loan_limit"
    entities: Optional[Dict[str, Any]]      # 예: {"income": 5000, "marital_status": "미혼"}
    is_scenario_related: bool               # 입력이 현재 시나리오와 관련 있는지 여부
    confidence: Optional[float]             # 의도/개체 추출에 대한 신뢰도 (옵션)
    next_action_suggestion: Optional[str] # Scenario Agent가 제안하는 다음 액션 (옵션)

# QA Agent의 예상 출력 구조
class QAAgentOutput(TypedDict, total=False):
    answer: Optional[str]                   # 생성된 답변
    retrieved_context_summary: Optional[str] # 참조된 문서 내용 요약 (디버깅/표시용)
    confidence: Optional[float]             # 답변 신뢰도 (옵션)

class AgentState(TypedDict):
    # --- 초기 입력 ---
    user_input_text: Optional[str]          # 사용자의 원본 텍스트 입력
    user_input_audio_b64: Optional[str]     # 사용자의 원본 오디오 입력 (base64)

    # --- STT 처리 결과 ---
    stt_result: Optional[str]               # STT 변환 결과 텍스트

    # --- Main Agent의 판단 및 라우팅 정보 ---
    main_agent_routing_decision: Optional[Literal[
        "answer_directly_chit_chat",        # 칫챗으로 바로 답변
        "answer_directly_scenario_prompt",  # 시나리오 JSON의 프롬프트를 바로 사용
        "invoke_scenario_agent",            # Scenario Agent 호출 필요
        "invoke_qa_agent",                  # QA Agent 호출 필요
        "process_scenario_info",            # Scenario Agent 결과 또는 직접 입력으로 시나리오 진행
        "unclear_input",                    # 사용자 입력이 불분명함
        "end_conversation"                  # 대화 종료 처리
    ]]
    # Main Agent가 직접 생성한 답변 (칫챗, 간단한 시나리오 안내 등)
    main_agent_direct_response: Optional[str]

    # --- Specialist Agent들의 출력 ---
    scenario_agent_output: Optional[ScenarioAgentOutput]
    qa_agent_output: Optional[QAAgentOutput]

    # --- 핵심 대화 상태 (기존 상태 유지 및 확장) ---
    messages: Sequence[BaseMessage]         # 전체 대화 기록
    current_scenario_stage_id: str          # 현재 시나리오 단계 ID
    collected_loan_info: Dict[str, any]     # 시나리오를 통해 수집된 사용자 정보
    loan_scenario_data: Dict                # 로드된 전체 시나리오 JSON 데이터

    # --- 최종 사용자 응답 생성용 ---
    final_response_text_for_tts: Optional[str] # TTS로 변환될 최종 텍스트
    tts_audio_b64: Optional[str]            # TTS 변환 결과 오디오 (base64)
    is_final_turn_response: bool            # 이 턴의 응답이 사용자에게 전달될 최종 응답인지 여부

    # --- 시스템 및 오류 처리 ---
    error_message: Optional[str]
    # next_node_override는 main_agent_routing_decision으로 대체 가능성 높음