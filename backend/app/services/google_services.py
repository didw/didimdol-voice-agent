# backend/app/services/google_services.py
from google.cloud import speech
from google.cloud import texttospeech as tts
import os
import asyncio
import base64
from typing import Callable, Optional, AsyncGenerator, Union, List, Awaitable # Added List and Awaitable
import queue # 동기 큐
import webrtcvad
import numpy as np

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
                 on_interim_result: Callable[[str], Awaitable[None]], # Awaitable로 타입 수정
                 on_final_result: Callable[[str], Awaitable[None]], # Awaitable로 타입 수정
                 on_error: Callable[[str], Awaitable[None]], # Awaitable로 타입 수정
                 on_epd_detected: Optional[Callable[[], Awaitable[None]]] = None, # Awaitable로 타입 수정
                 language_code: str = "ko-KR",
                 audio_encoding: speech.RecognitionConfig.AudioEncoding = speech.RecognitionConfig.AudioEncoding.LINEAR16,
                 sample_rate_hertz: int = 16000): # VAD 권장 샘플레이트: 8000, 16000, 32000
        
        self._is_active = False # 스트림 활성화 상태
        self.session_id = session_id

        if not GOOGLE_SERVICES_AVAILABLE:
            print(f"StreamSTTService ({self.session_id}) 초기화 실패: Google 서비스 사용 불가.")
            return

        # --- VAD 인스턴스 생성 및 설정 ---
        self.vad = webrtcvad.Vad()
        self.vad.set_mode(1)
        
        # VAD는 10, 20, 30ms 프레임에서 작동합니다.
        self.frame_duration_ms = 30 
        self.frame_size = int(sample_rate_hertz * self.frame_duration_ms / 1000)
        # 16-bit 오디오이므로 바이트 크기는 샘플 수의 2배
        self.frame_bytes = self.frame_size * 2 
        # 클라이언트에서 오는 청크를 처리하기 위한 내부 버퍼
        self._internal_buffer = b'' 
        # --- VAD 설정 끝 ---

        self.client = speech.SpeechAsyncClient() # 비동기 클라이언트 사용
        self.config = speech.RecognitionConfig(
            encoding=audio_encoding,
            sample_rate_hertz=sample_rate_hertz,
            language_code=language_code,
            enable_automatic_punctuation=True,
            model="latest_long",
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
        
        self._audio_queue = asyncio.Queue() 
        self._processing_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        
        # --- 오디오 저장을 위한 파일 핸들러 추가 ---
        # try:
        #     self.debug_audio_file = open("debug_audio.raw", "wb")
        #     print("🔊 디버그 오디오 파일 'debug_audio.raw'가 생성되었습니다.")
        # except Exception as e:
        #     self.debug_audio_file = None
        #     print(f"⚠️ 디버그 오디오 파일을 생성할 수 없습니다: {e}")
        # --- 추가 끝 ---

        self._is_speech_active = False # 현재 음성 구간인지 상태
        self._silence_frames_after_speech = 0 # 음성 후 묵음 프레임 카운터
        self.SPEECH_FRAMES_TRIGGER = 2  # 2프레임(60ms) 연속 음성이면 발화 시작으로 판단
        self.SILENCE_FRAMES_TRIGGER = 10 # 10프레임(300ms) 연속 묵음이면 발화 종료로 판단
        self._speech_frames_buffer = [] # 음성 시작점 보정을 위한 버퍼

        print(f"StreamSTTService ({self.session_id}) initialized. Encoding: {audio_encoding.name}, Sample Rate: {sample_rate_hertz}")

    async def _request_generator(self):
        if not GOOGLE_SERVICES_AVAILABLE: 
            print(f"STT request generator ({self.session_id}): Google 서비스 사용 불가, 생성기 중단.")
            return
        try:
            yield speech.StreamingRecognizeRequest(streaming_config=self.streaming_config)
            first_chunk_received = False
            initial_audio_timeout = 5.0 

            while not self._stop_event.is_set():
                try:
                    current_timeout = initial_audio_timeout if not first_chunk_received else 0.2 
                    if not first_chunk_received:
                        print(f"STT request generator ({self.session_id}): Waiting for first audio chunk (max {current_timeout}s)...")
                    chunk = await asyncio.wait_for(self._audio_queue.get(), timeout=current_timeout)
                    if not first_chunk_received:
                        print(f"STT request generator ({self.session_id}): First audio chunk received.")
                        first_chunk_received = True
                    if chunk is None: 
                        self._stop_event.set() 
                        print(f"STT request generator ({self.session_id}): Termination signal received from queue.")
                        break 
                    yield speech.StreamingRecognizeRequest(audio_content=chunk)
                    self._audio_queue.task_done()
                except asyncio.TimeoutError:
                    if not first_chunk_received:
                        print(f"STT request generator ({self.session_id}): Timeout waiting for the first audio chunk. Stopping stream.")
                        if self.on_error: 
                            await self.on_error("음성 데이터가 수신되지 않아 STT를 시작할 수 없습니다 (초기 타임아웃).")
                        self._stop_event.set() 
                        break 
                    continue 
                except asyncio.CancelledError:
                    print(f"STT request generator ({self.session_id}): Task was cancelled.")
                    self._stop_event.set()
                    break 
                except Exception as e:
                    print(f"STT request generator ({self.session_id}) error in loop: {type(e).__name__} - {e}")
                    if self.on_error:
                         await self.on_error(f"STT 스트림 요청 생성 중 오류: {e}")
                    self._stop_event.set()
                    break 
            print(f"STT request generator ({self.session_id}) loop finished. Stop event: {self._stop_event.is_set()}")
        except Exception as e: 
            print(f"STT request generator ({self.session_id}) initial setup error: {type(e).__name__} - {e}")
            if self.on_error:
                await self.on_error(f"STT 스트림 초기 설정 오류: {e}")
            self._stop_event.set() 
        finally:
            print(f"STT request generator ({self.session_id}) fully terminated.")

    async def _process_responses(self):
        if not GOOGLE_SERVICES_AVAILABLE or not self._is_active:
            print(f"STT response processing ({self.session_id}): Not starting, Google services unavailable or not active.")
            return

        print(f"STT stream ({self.session_id}): Starting to listen for responses.")
        try:
            if not hasattr(self, 'client') or not hasattr(self, 'streaming_config'):
                 if self.on_error: await self.on_error("STT 서비스가 올바르게 초기화되지 않았습니다.")
                 return

            responses = await self.client.streaming_recognize(
                requests=self._request_generator(), 
            )
            async for response in responses:
                if self._stop_event.is_set(): 
                    print(f"STT response processing ({self.session_id}): Stop event detected, breaking loop.")
                    break 
                if not response.results: continue
                result = response.results[0]
                if not result.alternatives: continue
                transcript = result.alternatives[0].transcript
                if result.is_final:
                    print(f"STT Final ({self.session_id}): {transcript}")
                    if self.on_final_result:
                        await self.on_final_result(transcript)
                    if self.on_epd_detected: 
                        await self.on_epd_detected()
                else:
                    if self.on_interim_result:
                        await self.on_interim_result(transcript)
        except asyncio.CancelledError:
            print(f"STT response processing task ({self.session_id}) was cancelled.")
        except Exception as e: 
            error_msg = f"STT stream API error ({self.session_id}): {type(e).__name__} - {e}"
            print(error_msg)
            if self.on_error:
                await self.on_error(error_msg)
        finally:
            self._is_active = False 
            if not self._stop_event.is_set():
                self._stop_event.set() 
            print(f"STT stream ({self.session_id}): Response listening loop fully ended.")

    async def start_stream(self):
        if not GOOGLE_SERVICES_AVAILABLE:
            await self.on_error("STT 서비스를 시작할 수 없습니다 (Google 서비스 비활성).") # await 추가
            return
        if self._processing_task and not self._processing_task.done():
            print(f"STT stream ({self.session_id}): Stream already running.")
            return
        print(f"STT stream ({self.session_id}): Starting processing task.")
        self._stop_event.clear()
        self._is_active = True
        while not self._audio_queue.empty(): self._audio_queue.get_nowait(); self._audio_queue.task_done()
        self._processing_task = asyncio.create_task(self._process_responses())

    async def process_audio_chunk(self, chunk: bytes):
        if not GOOGLE_SERVICES_AVAILABLE or not self._is_active or self._stop_event.is_set():
            return
        if not self._processing_task or self._processing_task.done():
            print(f"STT stream ({self.session_id}): Dropping audio chunk, stream task not healthy.")
            return

        # print(f"--- Chunk Received (size: {len(chunk)} bytes) ---")
        self._internal_buffer += chunk
        
        ENERGY_THRESHOLD = 100 

        # 버퍼에 처리할 프레임이 충분히 쌓였는지 확인
        while len(self._internal_buffer) >= self.frame_bytes:
            frame_to_process = self._internal_buffer[:self.frame_bytes]
            self._internal_buffer = self._internal_buffer[self.frame_bytes:]

            try:
                # --- 에너지 필터링 로직 추가 ---
                # 16-bit 오디오 데이터를 numpy 배열로 변환
                audio_as_np_int16 = np.frombuffer(frame_to_process, dtype=np.int16)
                # RMS 에너지 계산
                rms = np.sqrt(np.mean(audio_as_np_int16.astype(np.float64)**2))
                
                # 에너지가 임계값보다 낮으면 무시 (노이즈로 간주)
                if rms < ENERGY_THRESHOLD:
                    # print(f"VAD: Dropped frame due to low energy (RMS: {rms:.2f})")
                    continue
                # --- 로직 추가 끝 ---

                # VAD로 음성인지 아닌지 판단
                is_speech = self.vad.is_speech(frame_to_process, self.config.sample_rate_hertz)
                
                # 음성인 경우에만 Google STT로 전송
                if is_speech:
                    # --- 파일에 쓰기 로직 추가 ---
                    # if self.debug_audio_file:
                    #     self.debug_audio_file.write(frame_to_process)
                    # --- 추가 끝 ---
                    # print(f"✅ VAD: Speech detected! Queueing frame (size: {len(frame_to_process)} bytes)")
                    self._audio_queue.put_nowait(frame_to_process)
                # else:
                #    print("VAD: Noise chunk detected and dropped.")

            except asyncio.QueueFull:
                print(f"STT audio queue full for session {self.session_id}. Dropping frame.")
            except Exception as e:
                print(f"Error during VAD processing or queueing ({self.session_id}): {e}")

    async def stop_stream(self):
        # --- 파일 닫기 로직 추가 ---
        # if self.debug_audio_file:
        #     print("🔊 디버그 오디오 파일을 닫습니다.")
        #     self.debug_audio_file.close()
        #     self.debug_audio_file = None
        # --- 추가 끝 ---
        if not GOOGLE_SERVICES_AVAILABLE or not self._is_active:
            self._is_active = False 
            return
        if not self._stop_event.is_set():
            print(f"STT stream ({self.session_id}): Attempting to stop.")
            self._stop_event.set()
            try:
                await self._audio_queue.put(None) 
            except Exception as e: 
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

# --- TTS 스트리밍 서비스 클래스 ---
class StreamTTSService:
    def __init__(self,
                 session_id: str,
                 on_audio_chunk: Callable[[str], Awaitable[None]], # Corrected typing
                 on_stream_complete: Callable[[], Awaitable[None]], # Corrected typing
                 on_error: Callable[[str], Awaitable[None]], # Corrected typing
                 language_code: str = "ko-KR",
                 voice_name: str = "ko-KR-Chirp3-HD-Orus", # Updated voice model
                 audio_encoding: tts.AudioEncoding = tts.AudioEncoding.MP3, 
                 speaking_rate: float = 1.2,
                 pitch: float = 0.0):
        
        self.session_id = session_id
        if not GOOGLE_SERVICES_AVAILABLE:
            print(f"StreamTTSService ({self.session_id}) 초기화 실패: Google 서비스 사용 불가.")
            # Consider calling on_error or raising an exception if services are critical
            return

        self.client = tts.TextToSpeechAsyncClient()
        self.voice_params = tts.VoiceSelectionParams(language_code=language_code, name=voice_name)
        self.audio_config = tts.AudioConfig(
            audio_encoding=audio_encoding,
            speaking_rate=speaking_rate,
            pitch=pitch,
        )
        self.on_audio_chunk = on_audio_chunk
        self.on_stream_complete = on_stream_complete
        self.on_error = on_error
        self._current_tts_task: Optional[asyncio.Task] = None
        # Increased chunk size for potentially smoother delivery of MP3
        self.simulated_chunk_size_bytes = 32768 # <--- 변경된 기본값 (예: 32KB)

        print(f"StreamTTSService ({self.session_id}) initialized. Voice: {voice_name}, Encoding: {audio_encoding.name}, Speaking Rate: {speaking_rate}, Chunk Size: {self.simulated_chunk_size_bytes}") #

    async def _generate_and_stream_audio(self, text: str):
        if not GOOGLE_SERVICES_AVAILABLE: 
            if self.on_error: await self.on_error("TTS 스트림 생성 불가 (Google 서비스 비활성).")
            if self.on_stream_complete: await self.on_stream_complete()
            return
        try:
            print(f"TTS stream ({self.session_id}): Synthesizing for text: '{text[:50]}...'")
            synthesis_input = tts.SynthesisInput(text=text)
            response = await self.client.synthesize_speech(
                request={"input": synthesis_input, "voice": self.voice_params, "audio_config": self.audio_config}
            )
            audio_content = response.audio_content
            print(f"TTS stream ({self.session_id}): Synthesis complete, size: {len(audio_content)} bytes for '{text[:30]}...'")

            if not audio_content:
                 print(f"TTS stream ({self.session_id}): No audio content received for '{text[:30]}...'")
                 if self.on_error: await self.on_error(f"TTS 오디오 생성 실패: '{text[:30]}...'")
                 if self.on_stream_complete: await self.on_stream_complete()
                 return

            for i in range(0, len(audio_content), self.simulated_chunk_size_bytes):
                if self._current_tts_task and self._current_tts_task.cancelled():
                    print(f"TTS stream ({self.session_id}): Cancelled during chunking for '{text[:30]}...'")
                    break
                chunk = audio_content[i:i + self.simulated_chunk_size_bytes]
                encoded_chunk = base64.b64encode(chunk).decode('utf-8')
                if self.on_audio_chunk:
                    await self.on_audio_chunk(encoded_chunk)
                # Reduced sleep or make it configurable for faster streaming if network allows
                await asyncio.sleep(0.02) 
            
            if not (self._current_tts_task and self._current_tts_task.cancelled()):
                 if self.on_stream_complete:
                    await self.on_stream_complete()
            print(f"TTS stream ({self.session_id}): Finished streaming for '{text[:30]}...'")

        except asyncio.CancelledError:
            print(f"TTS generation task ({self.session_id}): Was cancelled for '{text[:30]}...'")
            # on_stream_complete is called in finally
        except Exception as e:
            error_msg = f"TTS synthesis/streaming error for session {self.session_id}, text '{text[:30]}...': {type(e).__name__} - {e}"
            print(error_msg)
            if self.on_error: 
                await self.on_error(error_msg)
        finally:
             # Ensure on_stream_complete is called if the task was not cancelled mid-way through on_audio_chunk calls
             # and it hasn't been called yet.
             # If _generate_and_stream_audio exits, it means processing for this text is over.
             if self._current_tts_task and not self._current_tts_task.cancelled() and self.on_stream_complete:
                 # This ensures that if there was an error before the natural end, but after some chunks,
                 # the client still gets a completion signal for this text segment.
                 # However, the original on_stream_complete in the happy path (after loop) is preferred.
                 # This might be redundant if on_stream_complete is already called at the end of the try block.
                 # To avoid double calls, only call if not already called.
                 # The main call is after the for loop in the try block.
                 pass
             print(f"TTS stream ({self.session_id}): Audio generation/streaming task for '{text[:30]}...' finished.")


    async def start_tts_stream(self, text_to_speak: str):
        if not GOOGLE_SERVICES_AVAILABLE:
            if self.on_error: await self.on_error("TTS 스트림 시작 불가: 서비스가 초기화되지 않았습니다.")
            if self.on_stream_complete: await self.on_stream_complete()
            return

        # Stop any currently running TTS task for a *previous text segment*
        await self.stop_tts_stream() 
        
        print(f"TTS stream ({self.session_id}): Queueing TTS task for text: '{text_to_speak[:50]}...'")
        # Create and store the task for the current text_to_speak
        self._current_tts_task = asyncio.create_task(self._generate_and_stream_audio(text_to_speak))
        
        try:
            # Await the completion of the current sentence's TTS streaming
            await self._current_tts_task
        except asyncio.CancelledError:
            print(f"TTS stream ({self.session_id}): Task for '{text_to_speak[:30]}...' was cancelled during start_tts_stream.")
        except Exception as e:
            print(f"TTS stream ({self.session_id}): Error awaiting task in start_tts_stream for '{text_to_speak[:30]}...': {e}")
            if self.on_error: await self.on_error(f"TTS 작업 실행 중 오류: {e}")
            if self.on_stream_complete: await self.on_stream_complete() # Ensure cleanup


    async def stop_tts_stream(self):
        if not GOOGLE_SERVICES_AVAILABLE: return

        task_to_stop = self._current_tts_task
        if task_to_stop and not task_to_stop.done():
            print(f"TTS stream ({self.session_id}): Attempting to cancel active TTS task.")
            task_to_stop.cancel()
            try:
                await task_to_stop 
            except asyncio.CancelledError:
                print(f"TTS stream ({self.session_id}): Active TTS task successfully cancelled.")
            except Exception as e:
                print(f"TTS stream ({self.session_id}): Error during TTS task cancellation: {e}")
            finally:
                if self._current_tts_task is task_to_stop: # Ensure we only nullify if it's the same task
                    self._current_tts_task = None
        else: 
            if self._current_tts_task is task_to_stop:
                 self._current_tts_task = None
        print(f"TTS stream ({self.session_id}): Stop TTS stream completed.")


# --- 단건 처리 함수 (기존 제공된 파일 참고, 비상용 또는 초기 테스트용) ---
async def transcribe_audio_bytes_non_streaming(audio_bytes: bytes,
                                 sample_rate_hertz: int = 48000, 
                                 encoding: speech.RecognitionConfig.AudioEncoding = speech.RecognitionConfig.AudioEncoding.WEBM_OPUS
                                 ) -> str:
    if not GOOGLE_SERVICES_AVAILABLE:
        print("STT (단건) 서비스 사용 불가: Google Credentials 누락.")
        return "음성 인식을 위한 서비스 설정을 찾을 수 없습니다."
    client = speech.SpeechClient() 
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

async def synthesize_text_to_audio_bytes_non_streaming(text: str) -> bytes:
    if not GOOGLE_SERVICES_AVAILABLE:
        print("TTS (단건) 서비스 사용 불가: Google Credentials 누락.")
        return b"TTS service credentials missing."
    client = tts.TextToSpeechAsyncClient() 
    synthesis_input = tts.SynthesisInput(text=text)
    voice = tts.VoiceSelectionParams(
        language_code="ko-KR",
        name="ko-KR-Chirp3-HD-Orus", # Updated voice model
    )
    audio_config = tts.AudioConfig(
        audio_encoding=tts.AudioEncoding.MP3,
        speaking_rate=1.2 # <--- 단건 처리 함수에도 반영
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