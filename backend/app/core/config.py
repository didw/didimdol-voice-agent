import os
from dotenv import load_dotenv

load_dotenv() # .env 파일에서 환경 변수 로드

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

# LLM 모델 설정
LLM_MODEL_NAME = "gpt-4o-mini"

# 필요시 추가 설정
# DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() == "true"
