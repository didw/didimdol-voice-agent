# backend/app/graph/state.py
from typing import Dict, TypedDict, Optional, Sequence, Literal, Any, List
from langchain_core.messages import BaseMessage

# Scenario Agent의 예상 출력 구조
class ScenarioAgentOutput(TypedDict, total=False):
    intent: Optional[str]
    entities: Optional[Dict[str, Any]]
    is_scenario_related: bool
    # user_sentiment: Optional[Literal['positive', 'negative', 'neutral']] # 필요시 추가

# QA Agent의 예상 출력 (스트리밍에서는 사용되지 않을 수 있음, 결과는 직접 텍스트로)
class QAAgentOutput(TypedDict, total=False):
    answer: Optional[str]
    # retrieved_context_summary: Optional[str] # 디버깅용

class AgentState(TypedDict):
    # --- 초기 입력 및 세션 정보 ---
    session_id: str # 세션 ID 추가
    user_input_text: Optional[str]
    user_input_audio_b64: Optional[str] # Base64 인코딩된 오디오 (STT용)

    # --- STT 결과 ---
    stt_result: Optional[str]

    # --- Main Agent (라우터) 판단 ---
    main_agent_routing_decision: Optional[Literal[
        "invoke_scenario_agent",    # 시나리오 에이전트 호출 (NLU)
        "invoke_qa_agent",          # QA 에이전트 호출 (RAG)
        "answer_directly_chit_chat",# LLM 직접 답변 (자유 대화)
        "process_next_scenario_step",# 단순 응답으로 다음 시나리오 단계 진행
        "end_conversation",         # 대화 종료
        "unclear_input"             # 입력 불분명, 재질문 유도
    ]]
    main_agent_direct_response: Optional[str] # 칫챗 등 직접 답변 내용
    
    # --- Scenario Agent (NLU) 출력 ---
    scenario_agent_output: Optional[ScenarioAgentOutput]

    # --- 대화 상태 ---
    messages: Sequence[BaseMessage] # 전체 대화 히스토리 (Langchain Message 객체)
    current_scenario_stage_id: str  # 현재 대출 시나리오 단계 ID
    collected_loan_info: Dict[str, Any] # 시나리오 통해 수집된 정보
    loan_scenario_data: Dict        # 로드된 전체 대출 시나리오 JSON

    # --- 최종 응답 (LangGraph 실행 후 run_agent_streaming에서 채워짐) ---
    final_response_text_for_tts: Optional[str] # TTS로 변환될 최종 AI 응답 텍스트

    # --- 오류 상태 ---
    error_message: Optional[str]    # 처리 중 발생한 오류 메시지 (사용자 안내용)
    is_final_turn_response: bool    # 해당 턴의 응답이 생성 완료되었는지 여부