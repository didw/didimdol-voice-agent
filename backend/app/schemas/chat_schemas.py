from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class UserMessageInput(BaseModel):
    """클라이언트에서 오는 메시지 형식 (텍스트 또는 오디오) - WebSocket용으로는 직접 사용 안함"""
    session_id: str
    text: Optional[str] = None
    audio_base64: Optional[str] = None # Base64 인코딩된 오디오 데이터 (Opus WebM 등)

class AIMessageOutput(BaseModel):
    """서버에서 클라이언트로 보내는 AI 응답 형식 - WebSocket용으로는 직접 사용 안함"""
    session_id: str
    text: str
    tts_audio_base64: Optional[str] = Field(default=None, description="Base64 인코딩된 TTS 오디오 (단건 응답 시)")
    # 스트리밍 시에는 audio_chunk 메시지로 별도 전송
    current_stage_id: Optional[str] = None
    collected_info: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    is_final_response: bool = True # 턴의 최종 응답인지 여부