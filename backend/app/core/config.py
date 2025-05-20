import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "gpt-4o-mini") # 환경 변수 또는 기본값 사용

# WebSocket 설정 (필요시)
# WEBSOCKET_MAX_SIZE_MB = int(os.getenv("WEBSOCKET_MAX_SIZE_MB", 10))

# STT/TTS 기본 설정 (google_services.py 에서 직접 사용하거나 여기서 정의 후 전달 가능)
# DEFAULT_STT_LANGUAGE_CODE = "ko-KR"
# DEFAULT_TTS_LANGUAGE_CODE = "ko-KR"
# DEFAULT_TTS_VOICE_NAME = "ko-KR-Wavenet-D" # 예시