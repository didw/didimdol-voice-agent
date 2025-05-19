from google.cloud import speech
from google.cloud import texttospeech as tts
import os
from ..core.config import GOOGLE_APPLICATION_CREDENTIALS

# Google Cloud 인증 정보 설정 (main.py에서 startup 시점에 확인하지만, 여기서도 명시적으로)
if GOOGLE_APPLICATION_CREDENTIALS and os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS
else:
    print(f"Google 서비스 경고: GOOGLE_APPLICATION_CREDENTIALS({GOOGLE_APPLICATION_CREDENTIALS}) 설정이 유효하지 않습니다.")


async def transcribe_audio_bytes(audio_bytes: bytes, sample_rate_hertz: int = 16000) -> str:
    """
    오디오 바이트를 텍스트로 변환 (Google STT)
    """
    if not GOOGLE_APPLICATION_CREDENTIALS or not os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
        raise EnvironmentError("Google Cloud Credentials not set or invalid.")

    client = speech.SpeechAsyncClient() # 비동기 클라이언트 사용

    audio = speech.RecognitionAudio(content=audio_bytes)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16, # 또는 MP3, OGG_OPUS 등
        sample_rate_hertz=sample_rate_hertz, # 프론트엔드에서 넘어오는 오디오 샘플레이트에 맞춰야 함
        language_code="ko-KR",
        enable_automatic_punctuation=True,
    )

    print("Google STT 요청 중...")
    try:
        operation = await client.long_running_recognize(config=config, audio=audio) # 긴 오디오 파일용
        # 짧은 오디오는 `await client.recognize(config=config, audio=audio)` 사용
        response = await operation.result(timeout=120) # 타임아웃 설정 (초)

        transcript = ""
        for result in response.results:
            transcript += result.alternatives[0].transcript
        print(f"STT 결과: {transcript}")
        return transcript
    except Exception as e:
        print(f"Google STT Error: {e}")
        return ""


async def synthesize_text_to_audio_bytes(text: str) -> bytes:
    """
    텍스트를 음성 오디오 바이트로 변환 (Google TTS)
    """
    if not GOOGLE_APPLICATION_CREDENTIALS or not os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
        raise EnvironmentError("Google Cloud Credentials not set or invalid.")

    client = tts.TextToSpeechAsyncClient() # 비동기 클라이언트

    synthesis_input = tts.SynthesisInput(text=text)

    voice = tts.VoiceSelectionParams(
        language_code="ko-KR",
        name="ko-KR-Wavenet-D",  # Wavenet 음성 (고품질) 또는 Standard 음성
        # name="ko-KR-Standard-A",
        ssml_gender=tts.SsmlVoiceGender.NEUTRAL,
    )

    audio_config = tts.AudioConfig(
        audio_encoding=tts.AudioEncoding.MP3, # MP3 또는 LINEAR16 등
        speaking_rate=1.0 # 0.25 ~ 4.0
    )
    print(f"Google TTS 요청 중 (텍스트: {text[:30]}...)")
    try:
        response = await client.synthesize_speech(
            request={"input": synthesis_input, "voice": voice, "audio_config": audio_config}
        )
        print("Google TTS 응답 수신 완료.")
        return response.audio_content
    except Exception as e:
        print(f"Google TTS Error: {e}")
        return b""
    