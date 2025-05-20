# backend/app/services/google_services.py
from google.cloud import speech
from google.cloud import texttospeech as tts
import os
import asyncio
import base64
from typing import Callable, Optional, AsyncGenerator, Union
import queue # 동기 큐

from ..core.config import GOOGLE_APPLICATION_CREDENTIALS

# Google Cloud 인증 정보 설정
GOOGLE_SERVICES_AVAILABLE = False
if GOOGLE_APPLICATION_CREDENTIALS and os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS
    GOOGLE_SERVICES_AVAILABLE = True
    print(f"Google Cloud Credentials가 성공적으로 로드되었습니다: {GOOGLE_APPLICATION_CREDENTIALS}")
else:
    if not GOOGLE_APPLICATION_CREDENTIALS:
        print("Google 서비스 경고: GOOGLE_APPLICATION_CREDENTIALS 환경 변수가 설정되지 않았습니다.")
    elif not os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
        print(f"Google 서비스 경고: GOOGLE_APPLICATION_CREDENTIALS 경로의 파일을 찾을 수 없습니다: {GOOGLE_APPLICATION_CREDENTIALS}")
    print("Google STT/TTS 서비스 기능이 비활성화될 수 있습니다.")


# --- STT 스트리밍 서비스 클래스 ---
class StreamSTTService:
    def __init__(self,
                 session_id: str,
                 on_interim_result: Callable[[str], None],
                 on_final_result: Callable[[str], None],
                 on_error: Callable[[str], None],
                 on_epd_detected: Optional[Callable[[], None]] = None,
                 language_code: str = "ko-KR",
                 audio_encoding: speech.RecognitionConfig.AudioEncoding = speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
                 sample_rate_hertz: int = 48000): # EPD, Barge-in을 위해선 높은 샘플레이트 및 적절한 인코딩
        
        self._is_active = False # 스트림 활성화 상태
        self.session_id = session_id

        if not GOOGLE_SERVICES_AVAILABLE:
            print(f"StreamSTTService ({self.session_id}) 초기화 실패: Google 서비스 사용 불가.")
            # 초기화 실패 시 on_error 콜백을 호출하거나, chat.py에서 GOOGLE_SERVICES_AVAILABLE로 분기 처리
            # self.on_error("STT 서비스 초기화 실패: Google 서비스 인증 정보를 확인하세요.") # 생성자에서 on_error 직접 호출은 부적절할 수 있음
            return

        self.client = speech.SpeechAsyncClient() # 비동기 클라이언트 사용
        self.config = speech.RecognitionConfig(
            encoding=audio_encoding,
            sample_rate_hertz=sample_rate_hertz,
            language_code=language_code,
            enable_automatic_punctuation=True,
            model="latest_long",  # EPD 및 정확도 향상, 음성 활동 감지
            # enable_word_time_offsets=True, # 필요시 단어 시간 오프셋
            # use_enhanced=True, # 향상된 모델 (비용 확인 필요)
            # 음성 활동 감지 관련 설정 (더 미세 조정 가능)
            # speech_contexts=[speech.SpeechContext(phrases=["디딤돌대출", "주택담보대출", "신한은행"])], # 인식률 향상을 위한 문맥 정보
        )
        self.streaming_config = speech.StreamingRecognitionConfig(
            config=self.config,
            interim_results=True,
            single_utterance=False, # Barge-in 및 연속 발화를 위해 False. EPD로 발화 구분.
            # enable_voice_activity_events=True, # 음성 활동 이벤트 활성화
            # voice_activity_timeout=speech.StreamingRecognitionConfig.VoiceActivityTimeout(
            #     speech_start_timeout=datetime.timedelta(seconds=3), # 3초간 음성 없으면 시작 타임아웃 (기본값)
            #     speech_end_timeout=datetime.timedelta(milliseconds=800) # 0.8초간 음성 없으면 종료 (기본값)
            # )
        )
        self.on_interim_result = on_interim_result
        self.on_final_result = on_final_result
        self.on_error = on_error
        self.on_epd_detected = on_epd_detected
        
        self._audio_queue = asyncio.Queue() # 비동기 큐
        self._processing_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

        print(f"StreamSTTService ({self.session_id}) initialized. Encoding: {audio_encoding.name}, Sample Rate: {sample_rate_hertz}")

    async def _request_generator(self):
        if not GOOGLE_SERVICES_AVAILABLE: # 추가된 방어 코드
            print(f"STT request generator ({self.session_id}): Google 서비스 사용 불가, 생성기 중단.")
            return

        try:
            yield speech.StreamingRecognizeRequest(streaming_config=self.streaming_config)
            
            first_chunk_received = False
            while not self._stop_event.is_set():
                try:
                    current_timeout = 2.0 if not first_chunk_received else 0.1 # 첫 청크는 2초, 이후는 0.1초 대기

                    if not first_chunk_received:
                        print(f"STT request generator ({self.session_id}): 첫 번째 오디오 청크 대기 중 (최대 {current_timeout}초)...")
                    
                    chunk = await asyncio.wait_for(self._audio_queue.get(), timeout=current_timeout)
                    
                    if not first_chunk_received:
                        print(f"STT request generator ({self.session_id}): 첫 번째 오디오 청크 수신 완료.")
                        first_chunk_received = True

                    if chunk is None: # 종료 신호
                        self._stop_event.set()
                        print(f"STT request generator ({self.session_id}): 종료 신호 수신.")
                        break
                    
                    yield speech.StreamingRecognizeRequest(audio_content=chunk)
                    self._audio_queue.task_done()

                except asyncio.TimeoutError:
                    if not first_chunk_received:
                        # 첫 번째 청크를 기다리다가 지정된 시간(예: 2초) 동안 받지 못한 경우
                        print(f"STT request generator ({self.session_id}): 첫 번째 오디오 청크 대기 시간 초과. 스트림 중단 시도.")
                        if self.on_error: # on_error 콜백이 있다면 호출
                            await self.on_error("음성 데이터가 수신되지 않아 STT를 시작할 수 없습니다.")
                        self._stop_event.set() # 생성기 중단
                        break 
                    # 이후 청크에 대한 타임아웃은 정상적인 상황일 수 있음 (클라이언트가 잠시 말을 멈춘 경우 등)
                    # print(f"STT request generator ({self.session_id}): 오디오 큐 비어있음 (일시적 타임아웃).") # 너무 많은 로그 방지
                    continue 
                except asyncio.CancelledError: # 명시적인 작업 취소 처리
                    print(f"STT request generator ({self.session_id}): 작업 취소됨.")
                    self._stop_event.set()
                    break
                except Exception as e:
                    print(f"STT request generator ({self.session_id}) 내부 루프 오류: {type(e).__name__} - {e}")
                    if self.on_error: # on_error 콜백이 있다면 호출
                         await self.on_error(f"STT 스트림 요청 생성 중 내부 오류: {e}")
                    self._stop_event.set()
                    break
            print(f"STT request generator ({self.session_id}) 루프 종료됨. (stop_event: {self._stop_event.is_set()})")
        except Exception as e: # yield streaming_config 에서 발생할 수 있는 예외 처리
            print(f"STT request generator ({self.session_id}) 초기 설정 오류: {type(e).__name__} - {e}")
            if self.on_error:
                await self.on_error(f"STT 스트림 초기 설정 중 오류: {e}")
            self._stop_event.set() # 확실히 중단
        finally:
            print(f"STT request generator ({self.session_id}) 완전히 종료됨.")

    async def _process_responses(self):
        if not GOOGLE_SERVICES_AVAILABLE or not self._is_active: return

        print(f"STT stream ({self.session_id}): Starting to listen for responses.")
        try:
            responses = await self.client.streaming_recognize(
                requests=self._request_generator(),
                # timeout=300 # 전체 스트리밍 타임아웃 (선택적)
            )
            async for response in responses:
                if self._stop_event.is_set(): break
                if not response.results: continue

                result = response.results[0]
                if not result.alternatives: continue
                transcript = result.alternatives[0].transcript

                # # EPD (End of Single Utterance) 감지 - single_utterance=True 일 때 유효
                # if response.speech_event_type == speech.StreamingRecognizeResponse.SpeechEventType.END_OF_SINGLE_UTTERANCE:
                #     print(f"EPD detected by Google STT API ({self.session_id})")
                #     if self.on_epd_detected:
                #         self.on_epd_detected()
                #     # single_utterance=False 일때는 is_final로 EPD 판단.

                if result.is_final:
                    print(f"STT Final ({self.session_id}): {transcript}")
                    if self.on_final_result: # 콜백 존재 여부 확인 후 호출
                        await self.on_final_result(transcript)
                    if self.on_epd_detected:
                         if self.on_epd_detected: # 콜백 존재 여부 확인 후 호출
                            await self.on_epd_detected()
                else:
                    if self.on_interim_result: # 콜백 존재 여부 확인 후 호출
                        await self.on_interim_result(transcript)
        
        except asyncio.CancelledError:
            print(f"STT response processing task ({self.session_id}) was cancelled.")
        except Exception as e:
            error_msg = f"STT stream error ({self.session_id}): {type(e).__name__} - {e}"
            print(error_msg)
            if self.on_error: # 콜백 존재 여부 확인 후 호출
                await self.on_error(error_msg)
        finally:
            self._is_active = False
            self._stop_event.set() # 확실히 종료
            print(f"STT stream ({self.session_id}): Response listening loop ended.")


    async def start_stream(self):
        if not GOOGLE_SERVICES_AVAILABLE:
            self.on_error("STT 서비스를 시작할 수 없습니다 (Google 서비스 비활성).")
            return

        if self._processing_task and not self._processing_task.done():
            print(f"STT stream ({self.session_id}): Stream already running.")
            return

        print(f"STT stream ({self.session_id}): Starting processing task.")
        self._stop_event.clear()
        self._is_active = True
        # 이전 큐 데이터 비우기
        while not self._audio_queue.empty(): self._audio_queue.get_nowait(); self._audio_queue.task_done()
        
        self._processing_task = asyncio.create_task(self._process_responses())


    async def process_audio_chunk(self, chunk: bytes):
        if not GOOGLE_SERVICES_AVAILABLE or not self._is_active or self._stop_event.is_set():
            # print(f"STT stream ({self.session_id}): Not active or stopping, dropping audio chunk.")
            return

        if not self._processing_task or self._processing_task.done():
            # print(f"STT stream ({self.session_id}): Stream not active. Client sent chunk. Attempting to start.")
            # await self.start_stream() # 클라이언트가 오디오를 보내기 시작하면 스트림 자동 시작 고려
            # await asyncio.sleep(0.1) # 스트림 시작 대기
            # 위의 자동 시작은 chat.py에서 websocket_endpoint 연결 시점으로 변경
            print(f"STT stream ({self.session_id}): Dropping audio chunk, stream task not healthy.")
            return

        try:
            self._audio_queue.put_nowait(chunk)
        except asyncio.QueueFull:
            print(f"STT audio queue full for session {self.session_id}. Dropping chunk.")
        except Exception as e:
            print(f"Error putting audio chunk to STT queue ({self.session_id}): {e}")


    async def stop_stream(self):
        if not GOOGLE_SERVICES_AVAILABLE or not self._is_active:
            self._is_active = False # 확실히 비활성화
            return

        if not self._stop_event.is_set():
            print(f"STT stream ({self.session_id}): Attempting to stop.")
            self._stop_event.set()
            try:
                await self._audio_queue.put(None) # 제너레이터 종료 신호 (None)
            except Exception as e: # 큐가 닫힌 후 put 시도 등
                print(f"Error sending stop signal to STT queue ({self.session_id}): {e}")


        if self._processing_task and not self._processing_task.done():
            print(f"STT stream ({self.session_id}): Waiting for processing task to complete.")
            try:
                await asyncio.wait_for(self._processing_task, timeout=2.0)
            except asyncio.TimeoutError:
                print(f"STT stream ({self.session_id}): Timeout waiting for task. Forcing cancellation.")
                self._processing_task.cancel()
            except Exception as e:
                print(f"STT stream ({self.session_id}): Error during task shutdown: {e}")
        
        self._processing_task = None
        self._is_active = False
        print(f"STT stream ({self.session_id}): Stopped.")


# --- TTS 스트리밍 서비스 클래스 (기존과 유사, google_services.py 참고) ---
class StreamTTSService:
    def __init__(self,
                 session_id: str,
                 on_audio_chunk: Callable[[str], None], # base64 encoded audio chunk
                 on_stream_complete: Callable[[], None],
                 on_error: Callable[[str], None],
                 language_code: str = "ko-KR",
                 voice_name: str = "ko-KR-Wavenet-D", # 표준 여성
                 # voice_name: str = "ko-KR-Wavenet-C", # 표준 남성
                 audio_encoding: tts.AudioEncoding = tts.AudioEncoding.MP3, # MP3 또는 LINEAR16 (Opus는 직접 지원 안함)
                 speaking_rate: float = 1.0,
                 pitch: float = 0.0):
        
        self.session_id = session_id
        if not GOOGLE_SERVICES_AVAILABLE:
            print(f"StreamTTSService ({self.session_id}) 초기화 실패: Google 서비스 사용 불가.")
            return

        self.client = tts.TextToSpeechAsyncClient()
        self.voice_params = tts.VoiceSelectionParams(language_code=language_code, name=voice_name)
        self.audio_config = tts.AudioConfig(
            audio_encoding=audio_encoding,
            speaking_rate=speaking_rate,
            pitch=pitch,
            # sample_rate_hertz=24000 # MP3의 경우 불필요, LINEAR16 사용 시 웹에서 재생 가능한 값으로 (e.g., 24000, 44100, 48000)
        )
        self.on_audio_chunk = on_audio_chunk
        self.on_stream_complete = on_stream_complete
        self.on_error = on_error
        self._current_tts_task: Optional[asyncio.Task] = None
        self.simulated_chunk_size_bytes = 8192 # 예: 8KB, MP3는 가변적이라 실제 스트리밍 API와는 다름

        print(f"StreamTTSService ({self.session_id}) initialized. Voice: {voice_name}, Encoding: {audio_encoding.name}")

    async def _generate_and_stream_audio(self, text: str):
        if not GOOGLE_SERVICES_AVAILABLE: return
        try:
            print(f"TTS stream ({self.session_id}): Synthesizing for text: '{text[:50]}...'")
            synthesis_input = tts.SynthesisInput(text=text)
            
            # Google TTS는 StreamingSynthesizeSpeech API를 제공함
            request = tts.StreamingSynthesizeSpeechRequest(
                input=synthesis_input,
                voice=self.voice_params,
                audio_config=self.audio_config
            )
            
            stream = await self.client.streaming_synthesize_speech(request=request)
            
            async for response_chunk in stream:
                if self._current_tts_task and self._current_tts_task.cancelled():
                    print(f"TTS stream ({self.session_id}): Cancelled during chunking.")
                    break
                if response_chunk.audio_content:
                    encoded_chunk = base64.b64encode(response_chunk.audio_content).decode('utf-8')
                    if self.on_audio_chunk: # 콜백 존재 여부 확인 후 호출
                        await self.on_audio_chunk(encoded_chunk) # <<< await 추가
            
            if not (self._current_tts_task and self._current_tts_task.cancelled()):
                if self.on_stream_complete: # 콜백 존재 여부 확인 후 호출
                    await self.on_stream_complete() # <<< await 추가

        except asyncio.CancelledError:
            print(f"TTS generation task ({self.session_id}): Was cancelled.")
            if self.on_stream_complete: # 콜백 존재 여부 확인 후 호출
                await self.on_stream_complete() # <<< await 추가
        except Exception as e:
            error_msg = f"TTS synthesis/streaming error for session {self.session_id}: {type(e).__name__} - {e}"
            print(error_msg)
            if self.on_error: # 콜백 존재 여부 확인 후 호출
                await self.on_error(error_msg) # <<< await 추가
            if self.on_stream_complete: # 콜백 존재 여부 확인 후 호출
                await self.on_stream_complete() # <<< await 추가
        finally:
             print(f"TTS stream ({self.session_id}): Audio generation/streaming loop finished.")


    async def start_tts_stream(self, text_to_speak: str):
        if not GOOGLE_SERVICES_AVAILABLE:
            self.on_error("TTS 스트림 시작 불가: 서비스가 초기화되지 않았습니다.")
            self.on_stream_complete()
            return

        await self.stop_tts_stream() # 이전 스트림 중지
        print(f"TTS stream ({self.session_id}): Queueing TTS task for text: '{text_to_speak[:50]}...'")
        self._current_tts_task = asyncio.create_task(self._generate_and_stream_audio(text_to_speak))

    async def stop_tts_stream(self):
        if not GOOGLE_SERVICES_AVAILABLE: return

        if self._current_tts_task and not self._current_tts_task.done():
            print(f"TTS stream ({self.session_id}): Attempting to cancel active task.")
            self._current_tts_task.cancel()
            try:
                await self._current_tts_task # 작업이 실제로 취소될 때까지 대기
            except asyncio.CancelledError:
                print(f"TTS stream ({self.session_id}): Active task successfully cancelled.")
            finally:
                self._current_tts_task = None
        else: # 작업이 없거나 이미 완료된 경우
            self._current_tts_task = None


# --- 단건 처리 함수 (기존 제공된 파일 참고, 비상용 또는 초기 테스트용) ---
async def transcribe_audio_bytes_non_streaming(audio_bytes: bytes,
                                 sample_rate_hertz: int = 48000, # WebM/Opus 기본값
                                 encoding: speech.RecognitionConfig.AudioEncoding = speech.RecognitionConfig.AudioEncoding.WEBM_OPUS
                                 ) -> str:
    if not GOOGLE_SERVICES_AVAILABLE:
        print("STT (단건) 서비스 사용 불가: Google Credentials 누락.")
        return "음성 인식을 위한 서비스 설정을 찾을 수 없습니다."

    client = speech.SpeechClient() # 단건은 동기 클라이언트 사용 후 비동기 래핑
    audio = speech.RecognitionAudio(content=audio_bytes)
    config = speech.RecognitionConfig(
        encoding=encoding,
        sample_rate_hertz=sample_rate_hertz,
        language_code="ko-KR",
        enable_automatic_punctuation=True,
    )
    print(f"Google STT (단건) 요청 중... 샘플레이트: {sample_rate_hertz}, 인코딩: {encoding.name}")
    try:
        # 동기 함수를 비동기로 실행
        response = await asyncio.to_thread(client.recognize, config=config, audio=audio)
        transcript = ""
        for result in response.results:
            transcript += result.alternatives[0].transcript
        print(f"STT (단건) 결과: {transcript}")
        return transcript
    except Exception as e:
        print(f"Google STT (단건) Error: {e}")
        return "" # 오류 시 빈 문자열 반환

async def synthesize_text_to_audio_bytes_non_streaming(text: str) -> bytes:
    if not GOOGLE_SERVICES_AVAILABLE:
        print("TTS (단건) 서비스 사용 불가: Google Credentials 누락.")
        return b"TTS service credentials missing."

    client = tts.TextToSpeechAsyncClient() # 비동기 클라이언트 사용
    synthesis_input = tts.SynthesisInput(text=text)
    voice = tts.VoiceSelectionParams(
        language_code="ko-KR",
        name="ko-KR-Wavenet-D",
    )
    audio_config = tts.AudioConfig(
        audio_encoding=tts.AudioEncoding.MP3
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