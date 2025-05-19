from pydantic import BaseModel, Field # Field 추가
from typing import Optional, List, Dict, Any

class UserMessage(BaseModel):
    session_id: Optional[str] = None
    text: Optional[str] = None
    audio_bytes_str: Optional[str] = None # Base64 인코딩된 오디오 바이트 문자열

class AIMessage(BaseModel):
    session_id: str
    text: str
    tts_audio_base64: Optional[str] = Field(default=None, description="Base64 인코딩된 TTS 오디오 데이터") # 명시적 필드 추가
    # audio_url: Optional[str] = None # URL 방식 사용 시
    debug_info: Optional[Dict[str, Any]] = Field(default=None, description="디버깅 정보 (예: 현재 스테이지, 수집 정보)")
    is_final: bool = True