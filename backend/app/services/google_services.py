# backend/app/services/google_services.py
from google.cloud import speech
from google.cloud import texttospeech as tts
import os
import asyncio
import base64
from typing import Callable, Optional, AsyncGenerator, Union # Union 추가

from ..core.config import GOOGLE_APPLICATION_CREDENTIALS

# Google Cloud 인증 정보 설정
GOOGLE_SERVICES_AVAILABLE = False
if GOOGLE_APPLICATION_CREDENTIALS and os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS
    GOOGLE_SERVICES_AVAILABLE = True
    print("Google Cloud Credentials가 성공적으로 로드되었습니다.")
else:
    print(f"Google 서비스 경고: GOOGLE_APPLICATION_CREDENTIALS({GOOGLE_APPLICATION_CREDENTIALS}) 설정이 유효하지 않습니다. Google 서비스 기능이 비활성화될 수 있습니다.")

# --- 기존 단건 처리 함수 ---
async def transcribe_audio_bytes(audio_bytes: bytes,
                                 sample_rate_hertz: int = 16000,
                                 encoding: speech.RecognitionConfig.AudioEncoding = speech.RecognitionConfig.AudioEncoding.LINEAR16
                                 ) -> str:
    """
    오디오 바이트를 텍스트로 변환 (Google STT - 단건, 짧은 오디오용)
    인코딩 및 샘플레이트는 클라이언트 오디오 포맷에 맞춰 전달되어야 합니다.
    (예: WebM Opus의 경우 encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS, sample_rate_hertz=48000)
    """
    if not GOOGLE_SERVICES_AVAILABLE:
        print("STT 서비스 사용 불가: Google Credentials 누락.")
        return "죄송합니다, 음성 인식을 위한 서비스 설정을 찾을 수 없습니다."

    client = speech.SpeechClient() # 짧은 오디오는 동기 클라이언트 사용 후 비동기 래핑
    audio = speech.RecognitionAudio(content=audio_bytes)
    config = speech.RecognitionConfig(
        encoding=encoding,
        sample_rate_hertz=sample_rate_hertz,
        language_code="ko-KR",
        enable_automatic_punctuation=True,
    )

    print(f"Google STT (단건) 요청 중... 샘플레이트: {sample_rate_hertz}, 인코딩: {encoding.name}")
    try:
        response = await asyncio.to_thread(client.recognize, config=config, audio=audio)
        transcript = ""
        for result in response.results:
            transcript += result.alternatives[0].transcript
        print(f"STT (단건) 결과: {transcript}")
        return transcript
    except Exception as e:
        print(f"Google STT (단건) Error: {e}")
        return ""


async def synthesize_text_to_audio_bytes(text: str) -> bytes:
    """
    텍스트를 음성 오디오 바이트로 변환 (Google TTS - 단건)
    """
    if not GOOGLE_SERVICES_AVAILABLE:
        print("TTS 서비스 사용 불가: Google Credentials 누락.")
        return b"TTS service credentials missing."

    client = tts.TextToSpeechAsyncClient()
    synthesis_input = tts.SynthesisInput(text=text)
    voice = tts.VoiceSelectionParams(
        language_code="ko-KR",
        name="ko-KR-Wavenet-D",
        ssml_gender=tts.SsmlVoiceGender.NEUTRAL,
    )
    audio_config = tts.AudioConfig(
        audio_encoding=tts.AudioEncoding.MP3,
        speaking_rate=1.0
    )
    print(f"Google TTS (단건) 요청 중 (텍스트: {text[:30]}...)")
    try:
        response = await client.synthesize_speech(
            request={"input": synthesis_input, "voice": voice, "audio_config": audio_config}
        )
        print("Google TTS (단건) 응답 수신 완료.")
        return response.audio_content
    except Exception as e:
        print(f"Google TTS (단건) Error: {e}")
        return b""

# --- STT 스트리밍 서비스 클래스 ---
class StreamSTTService:
    def __init__(self,
                 session_id: str,
                 on_interim_result: Callable[[str], None], # 콜백 타입 간소화
                 on_final_result: Callable[[str], None],
                 on_error: Callable[[str], None],
                 on_epd_detected: Optional[Callable[[], None]] = None,
                 language_code: str = "ko-KR",
                 # 클라이언트에서 WebM/Opus 사용 시 기본값 설정
                 audio_encoding: speech.RecognitionConfig.AudioEncoding = speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
                 sample_rate_hertz: int = 48000):
        self._is_available = GOOGLE_SERVICES_AVAILABLE
        if not self._is_available:
            print(f"StreamSTTService ({session_id}) 사용 불가: Google Credentials 누락.")
            # on_error 콜백은 비동기 컨텍스트에서 호출되도록 chat.py에서 처리
            return

        self.client = speech.SpeechClient()
        self.config = speech.RecognitionConfig(
            encoding=audio_encoding,
            sample_rate_hertz=sample_rate_hertz,
            language_code=language_code,
            enable_automatic_punctuation=True,
            model="latest_long", # EPD 및 정확도 향상
        )
        self.streaming_config = speech.StreamingRecognitionConfig(
            config=self.config,
            interim_results=True,
            single_utterance=False,
        )
        self.on_interim_result = on_interim_result
        self.on_final_result = on_final_result
        self.on_error = on_error
        self.on_epd_detected = on_epd_detected
        self.session_id = session_id
        self._audio_queue = asyncio.Queue()
        self._processing_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event() # 스트림 종료를 위한 이벤트

        print(f"StreamSTTService ({session_id}) initialized. Encoding: {audio_encoding.name}, Sample Rate: {sample_rate_hertz}")

    async def _request_generator(self):
        yield speech.StreamingRecognizeRequest(streaming_config=self.streaming_config)
        while not self._stop_event.is_set():
            try:
                # 큐에서 데이터를 가져오되, stop_event가 설정되면 즉시 종료
                chunk = await asyncio.wait_for(self._audio_queue.get(), timeout=0.1)
                if chunk is None: # 명시적 종료 신호
                    self._stop_event.set()
                    break
                yield speech.StreamingRecognizeRequest(audio_content=chunk)
                self._audio_queue.task_done()
            except asyncio.TimeoutError:
                continue # 타임아웃 발생 시 다시 루프 시작 (stop_event 체크)
            except asyncio.CancelledError:
                self._stop_event.set()
                break


    def _process_responses_sync(self):
        """동기 방식으로 응답을 처리하는 내부 함수 (run_in_executor에서 실행됨)"""
        if not self._is_available: return

        requests = self._request_generator_sync_wrapper() # 동기 제너레이터 사용
        try:
            print(f"STT stream ({self.session_id}): Starting to listen for responses (sync).")
            responses = self.client.streaming_recognize(self.streaming_config, requests)

            for response in responses:
                if self._stop_event.is_set(): break # 외부에서 중단 요청 시 루프 종료
                if not response.results: continue
                result = response.results[0]
                if not result.alternatives: continue
                transcript = result.alternatives[0].transcript

                # 콜백은 메인 이벤트 루프에서 실행되도록 예약
                loop = asyncio.get_running_loop()
                if result.is_final:
                    print(f"STT Final ({self.session_id}): {transcript}")
                    loop.call_soon_threadsafe(self.on_final_result, transcript)
                    if self.on_epd_detected:
                        loop.call_soon_threadsafe(self.on_epd_detected)
                else:
                    loop.call_soon_threadsafe(self.on_interim_result, transcript)
        except Exception as e:
            error_msg = f"STT stream error (sync loop) for session {self.session_id}: {type(e).__name__} - {e}"
            print(error_msg)
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(self.on_error, error_msg)
        finally:
            print(f"STT stream ({self.session_id}): Response listening loop (sync) ended.")
            self._stop_event.set() # 루프 종료 시 stop_event 설정 보장


    def _request_generator_sync_wrapper(self):
        """_request_generator를 동기 컨텍스트에서 호출하기 위한 래퍼"""
        # 이 부분은 asyncio.run을 사용하여 비동기 제너레이터를 동기적으로 실행해야 함
        # 또는 _request_generator 자체를 동기 제너레이터로 변경해야 함.
        # 여기서는 _request_generator의 로직을 단순화하고 동기적으로 만듦
        yield speech.StreamingRecognizeRequest(streaming_config=self.streaming_config)
        while not self._stop_event.is_set():
            try:
                # 큐에서 데이터를 가져오는 부분을 동기적으로 처리 (asyncio.Queue는 비동기 전용)
                # 이 클래스 설계에서 _audio_queue를 일반 queue.Queue로 변경하거나,
                # _process_responses_sync 내부에서 _audio_queue 접근 방식을 변경해야 함.
                # 가장 간단한 방법은 process_audio_chunk에서 받은 데이터를 바로 requests로 전달하는 것.
                # 여기서는 _audio_queue를 계속 사용한다고 가정하고, get을 블로킹 호출로 간주.
                # (실제로는 queue.Queue 사용 또는 다른 동기화 메커니즘 필요)
                # 지금은 _process_audio_chunk가 비동기이므로, 이 설계는 수정 필요.

                # --- 임시 수정: _audio_queue를 사용하지 않고, process_audio_chunk가 직접 데이터 공급 ---
                # 이 방식은 StreamSTTService의 구조 변경을 의미함.
                # 원래 설계대로 _audio_queue를 사용하려면 _process_responses_sync가 비동기가 되어야 하거나,
                # _audio_queue를 동기 큐로 변경하고 _request_generator도 동기화해야 함.

                # 현재로서는 _process_responses_sync가 올바르게 동작하기 어려움.
                # google-cloud-python 라이브러리의 streaming_recognize는 동기 반복자이므로,
                # 이를 비동기적으로 사용하려면 run_in_executor가 필요.
                # 이 내부에서 비동기 큐를 직접 사용하는 것은 복잡함.

                # --- 올바른 접근 ---
                # 1. StreamSTTService 전체를 동기 클래스로 만들고, chat.py에서 run_in_executor로 전체를 실행.
                # 2. gRPC 비동기 스트리밍을 직접 구현 (매우 복잡).
                # 3. google-cloud-speech 최신 버전에서 비동기 streaming_recognize 지원 확인 (현재는 미지원으로 보임).

                # 여기서는 _process_responses_sync를 호출하는 start_stream 부분을 수정하여
                # _request_generator를 올바르게 전달하는 방식으로 시도.
                # _request_generator는 비동기 제너레이터이므로, 동기 함수 내에서 직접 사용 불가.
                # 대신, _audio_queue에서 데이터를 가져오는 부분을 동기화된 방식으로 수정해야 함.
                # (이 부분은 구현의 복잡성으로 인해 실제 동작 가능한 코드로 즉시 변환하기 어려움.
                #  Google 공식 문서나 예제를 참조하여 비동기 환경에서의 스트리밍 처리 권장)

                # 현재 코드는 컨셉만 제시하며, 실제 실행에는 추가적인 동기/비동기 처리 조정이 필요함을 명시.
                # 아래는 실제 동작보다는 의도만 나타내는 코드.
                if self._audio_queue.empty() and not self._stop_event.is_set(): # 임시 non-blocking get
                    # time.sleep(0.01) # 동기 환경이면 time.sleep
                    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.01)) # 임시
                    continue

                if not self._audio_queue.empty():
                    chunk = self._audio_queue.get_nowait() # Non-blocking, 동기 큐라면 .get(block=False)
                    if chunk is None: self._stop_event.set(); break
                    yield speech.StreamingRecognizeRequest(audio_content=chunk)
                    self._audio_queue.task_done()

            except asyncio.QueueEmpty: # 비동기 큐에 대한 예외, 동기 큐라면 queue.Empty
                if self._stop_event.is_set(): break
                continue
            except Exception: # 모든 예외 처리
                if self._stop_event.is_set(): break
                # 예외 발생 시 로그 기록 및 루프 계속 또는 중단
                break


    async def start_stream(self):
        if not self._is_available: return
        async with self._lock:
            if self._processing_task and not self._processing_task.done():
                print(f"STT stream ({self.session_id}): Stream already running.")
                return

            print(f"STT stream ({self.session_id}): Starting processing task.")
            self._stop_event.clear()
            # 이전 큐 데이터 비우기 (선택적)
            while not self._audio_queue.empty(): self._audio_queue.get_nowait(); self._audio_queue.task_done()

            # _process_responses_sync는 동기 함수이므로 run_in_executor 사용
            loop = asyncio.get_event_loop()
            self._processing_task = loop.run_in_executor(None, self._process_responses_sync)

    async def process_audio_chunk(self, chunk: bytes):
        if not self._is_available or self._stop_event.is_set(): return
        if not self._processing_task or self._processing_task.done():
            print(f"STT stream ({self.session_id}): Stream not active. Attempting to start.")
            await self.start_stream()
            await asyncio.sleep(0.1) # 스트림 시작 대기

        if self._processing_task and not self._processing_task.done() and not self._stop_event.is_set():
            await self._audio_queue.put(chunk)
        else:
            print(f"STT stream ({self.session_id}): Dropping audio chunk, stream task not healthy or stopping.")

    async def stop_stream(self):
        if not self._is_available: return
        async with self._lock:
            if not self._stop_event.is_set():
                print(f"STT stream ({self.session_id}): Attempting to stop.")
                self._stop_event.set() # 루프 및 제너레이터 종료 신호
                await self._audio_queue.put(None) # 제너레이터 종료를 위한 None 추가 (선택적)

            if self._processing_task and not self._processing_task.done():
                try:
                    print(f"STT stream ({self.session_id}): Waiting for processing task to complete.")
                    await asyncio.wait_for(self._processing_task, timeout=5.0)
                except asyncio.TimeoutError:
                    print(f"STT stream ({self.session_id}): Timeout waiting for task. It might be already finishing.")
                except Exception as e:
                    print(f"STT stream ({self.session_id}): Error during task shutdown: {e}")
                finally:
                    self._processing_task = None
            print(f"STT stream ({self.session_id}): Stopped.")

# --- TTS 스트리밍 서비스 클래스 ---
class StreamTTSService:
    def __init__(self,
                 session_id: str,
                 on_audio_chunk: Callable[[str], None], # base64 encoded audio chunk
                 on_stream_complete: Callable[[], None],
                 on_error: Callable[[str], None],
                 language_code: str = "ko-KR",
                 voice_name: str = "ko-KR-Wavenet-D",
                 audio_encoding: tts.AudioEncoding = tts.AudioEncoding.MP3,
                 speaking_rate: float = 1.0):
        self._is_available = GOOGLE_SERVICES_AVAILABLE
        if not self._is_available:
            print(f"StreamTTSService ({session_id}) 사용 불가: Google Credentials 누락.")
            return

        self.client = tts.TextToSpeechAsyncClient()
        self.voice_params = tts.VoiceSelectionParams(language_code=language_code, name=voice_name)
        self.audio_config = tts.AudioConfig(audio_encoding=audio_encoding, speaking_rate=speaking_rate)
        self.on_audio_chunk = on_audio_chunk
        self.on_stream_complete = on_stream_complete
        self.on_error = on_error
        self.session_id = session_id
        self._current_tts_task: Optional[asyncio.Task] = None
        self.simulated_chunk_size_bytes = 8192 # 8KB 청크

        print(f"StreamTTSService ({self.session_id}) initialized. Voice: {voice_name}, Encoding: {audio_encoding.name}")

    async def _generate_and_stream_audio(self, text: str):
        if not self._is_available: return
        try:
            print(f"TTS stream ({self.session_id}): Synthesizing for text: '{text[:50]}...'")
            synthesis_input = tts.SynthesisInput(text=text)
            response = await self.client.synthesize_speech(
                request={"input": synthesis_input, "voice": self.voice_params, "audio_config": self.audio_config}
            )
            audio_content = response.audio_content
            print(f"TTS stream ({self.session_id}): Synthesis complete, size: {len(audio_content)} bytes.")

            for i in range(0, len(audio_content), self.simulated_chunk_size_bytes):
                if self._current_tts_task and self._current_tts_task.cancelled():
                    print(f"TTS stream ({self.session_id}): Cancelled during chunking.")
                    break
                chunk = audio_content[i:i + self.simulated_chunk_size_bytes]
                encoded_chunk = base64.b64encode(chunk).decode('utf-8')
                self.on_audio_chunk(encoded_chunk) # 콜백 호출
                await asyncio.sleep(0.05) # 약간의 지연 (클라이언트 처리 시간 확보)
            
            if not (self._current_tts_task and self._current_tts_task.cancelled()):
                 self.on_stream_complete()
        except asyncio.CancelledError:
            print(f"TTS generation task ({self.session_id}): Was cancelled.")
            # 취소 시에도 on_stream_complete를 호출하여 클라이언트가 대기 상태에서 벗어나도록 할 수 있음
            self.on_stream_complete()
        except Exception as e:
            error_msg = f"TTS synthesis/streaming error for session {self.session_id}: {type(e).__name__} - {e}"
            print(error_msg)
            self.on_error(error_msg)
            self.on_stream_complete() # 오류 발생 시에도 완료 콜백 호출
        finally:
             print(f"TTS stream ({self.session_id}): Audio generation/streaming loop finished.")

    async def start_tts_stream(self, text_to_speak: str):
        if not self._is_available:
            self.on_error("TTS 스트림 시작 불가: 서비스가 초기화되지 않았습니다.")
            self.on_stream_complete()
            return

        await self.stop_tts_stream()
        print(f"TTS stream ({self.session_id}): Queueing TTS task for text: '{text_to_speak[:50]}...'")
        self._current_tts_task = asyncio.create_task(self._generate_and_stream_audio(text_to_speak))

    async def stop_tts_stream(self):
        if not self._is_available: return
        if self._current_tts_task and not self._current_tts_task.done():
            print(f"TTS stream ({self.session_id}): Attempting to cancel active task.")
            self._current_tts_task.cancel()
            try:
                await self._current_tts_task
            except asyncio.CancelledError:
                print(f"TTS stream ({self.session_id}): Active task successfully cancelled.")
            finally:
                self._current_tts_task = None
        else:
            self._current_tts_task = None