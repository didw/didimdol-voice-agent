from typing import List, Dict, TypedDict, Optional, Sequence, Literal # Literal 추가
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    # --- 필수 입력 (매 턴마다 프론트에서 전달) ---
    user_input_text: Optional[str] # 사용자의 원본 텍스트 입력
    user_input_audio_b64: Optional[str] # 사용자의 원본 오디오 입력 (base64)

    # --- 세션/대화 관리 (매 턴마다 이전 상태를 받아 이어감) ---
    messages: Sequence[BaseMessage] # 전체 대화 기록 (시스템, 사람, AI 메시지 포함)
    current_scenario_stage_id: str # 현재 시나리오 단계 ID
    collected_loan_info: Dict[str, any] # 시나리오를 통해 수집된 사용자 정보

    # --- 내부 처리 상태 (각 노드에서 업데이트) ---
    stt_result: Optional[str] # STT 변환 결과 텍스트
    intent: Optional[Literal["scenario_answer", "qa_question", "chit_chat", "end_conversation", "unclear"]] # 사용자 의도
    loan_scenario_data: Dict # 로드된 전체 시나리오 데이터 (매번 로드할 수도 있지만, 상태에 포함 가능)
    llm_prompt_for_response: Optional[str] # LLM에게 전달할 최종 프롬프트 또는 메시지 (디버깅용)
    llm_response_text: Optional[str] # LLM의 최종 응답 텍스트
    tts_audio_b64: Optional[str] # TTS 변환 결과 오디오 (base64)
    error_message: Optional[str] # 처리 중 발생한 오류 메시지
    is_final_turn_response: bool # 이 턴의 응답이 사용자에게 전달될 최종 응답인지 여부
    next_node_override: Optional[str] # 특정 조건에 따라 다음 노드를 강제 지정할 때 사용