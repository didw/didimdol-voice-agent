// frontend/src/stores/chatStore.ts
import { defineStore } from 'pinia'
import { v4 as uuidv4 } from 'uuid'

interface Message {
  id: string
  sender: 'user' | 'ai'
  text: string
  timestamp: Date
  isStreaming?: boolean
  isInterimStt?: boolean
}

interface ChatState {
  sessionId: string | null
  messages: Message[]
  isProcessingLLM: boolean
  isSynthesizingTTS: boolean 
  error: string | null
  currentInterimStt: string
  isWebSocketConnected: boolean
  webSocket: WebSocket | null
  
  isVoiceModeActive: boolean
  isRecording: boolean
  mediaRecorder: MediaRecorder | null
  audioStream: MediaStream | null // This stream will be used for MediaRecorder and VAD
  
  ttsAudioQueue: string[] 
  isPlayingTTS: boolean 
  currentPlayingAudioElement: HTMLAudioElement | null 

  isEPDDetectedByServer: boolean

  // VAD related state
  vadContext: { // Encapsulate VAD resources
    audioContext: AudioContext | null;
    analyserNode: AnalyserNode | null;
    dataArray: Uint8Array | null;
    vadIntervalId: number | null;
    vadActivationTimeoutId: number | null; // For delaying VAD start
  }
}


const WEBSOCKET_URL_BASE =
  import.meta.env.VITE_WEBSOCKET_URL || 'ws://localhost:8000/api/v1/chat/ws/'

  export const useChatStore = defineStore('chat', {
    state: (): ChatState => ({
      sessionId: null,
      messages: [],
      isProcessingLLM: false,
      isSynthesizingTTS: false,
      error: null,
      currentInterimStt: '',
      isWebSocketConnected: false,
      webSocket: null,
      
      isVoiceModeActive: false,
      isRecording: false,
      mediaRecorder: null,
      audioStream: null,
  
      ttsAudioQueue: [],
      isPlayingTTS: false,
      currentPlayingAudioElement: null,
      isEPDDetectedByServer: false,
  
      vadContext: { // Initialize VAD context
          audioContext: null,
          analyserNode: null,
          dataArray: null,
          vadIntervalId: null,
          vadActivationTimeoutId: null,
      }
    }),
  actions: {
    initializeSessionAndConnect() {
      if (!this.sessionId) {
        this.sessionId = uuidv4()
        console.log('New session initialized:', this.sessionId)
      }
      if (!this.webSocket || this.webSocket.readyState === WebSocket.CLOSED) {
        this.connectWebSocket()
      } else if (this.webSocket.readyState === WebSocket.OPEN) {
        console.log('WebSocket already connected.')
      }
    },

    connectWebSocket() {
      if (!this.sessionId) {
        console.error('Session ID is not set. Cannot connect WebSocket.')
        this.error = '세션 ID가 없어 연결할 수 없습니다.'
        return
      }
      if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        console.log('WebSocket is already connected.')
        return
      }

      const fullWebSocketUrl = `${WEBSOCKET_URL_BASE}${this.sessionId}`
      console.log('Attempting to connect WebSocket to:', fullWebSocketUrl)
      this.webSocket = new WebSocket(fullWebSocketUrl)

      this.webSocket.onopen = () => {
        console.log('WebSocket connection established for session:', this.sessionId)
        this.isWebSocketConnected = true
        this.error = null
        // Do not automatically activate voice mode or send activate_voice here
      }

      this.webSocket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data as string)
          console.log('WebSocket message received:', data)
          // this.isEPDDetectedByServer = false; // Reset on any message for barge-in readiness - or handle more specifically

          switch (data.type) {
            case 'session_initialized':
              this.addMessage('ai', data.message)
              break
            case 'stt_interim_result':
              if (this.isVoiceModeActive) {
                // Only update if voice mode is on
                this.currentInterimStt = data.transcript
              }
              break
            case 'stt_final_result':
              this.currentInterimStt = '' // Clear interim
              if (data.transcript) {
                this.addMessage('user', data.transcript)
                this.isProcessingLLM = true // Backend auto-processes LLM after STT final
              }
              // If voice mode is active, recording continues.
              // If barge-in occurred, client-side TTS playback should have stopped.
              break
            case 'llm_response_chunk':
              this.appendAiMessageChunk(data.chunk)
              this.isProcessingLLM = true
              break
            case 'llm_response_end':
              this.finalizeAiMessage()
              this.isProcessingLLM = false
              // TTS audio chunks will follow if input mode was voice
              break
            case 'tts_audio_chunk':
              this.isSynthesizingTTS = true // Server is sending TTS
              this.ttsAudioQueue.push(data.audio_chunk_base64)
              this.playNextTtsAudioFromQueue() // Attempt to play
              break
            case 'tts_stream_end':
              this.isSynthesizingTTS = false // Server finished sending this TTS segment
              // playNextTtsAudioFromQueue will continue if there are more chunks or segments
              break
            case 'epd_detected': // Server (Google STT) detected end of user's utterance
              console.log('EPD detected by server (Google STT)')
              this.isEPDDetectedByServer = true
              // This can be a signal for barge-in if TTS is playing.
              if (this.isPlayingTTS) {
                console.log('Barge-in: EPD detected during TTS. Stopping client TTS.')
                this.stopClientSideTTSPlayback(false) // Stop client playback, don't tell server yet as STT->LLM is processing
              }
              // If voice mode is on, client continues sending audio until explicitly stopped.
              break
            case 'voice_activated':
              console.log('Voice mode activated by server confirmation.')
              // UI can reflect this if needed, actual recording started by client action
              break
            case 'voice_deactivated':
              console.log('Voice mode deactivated by server confirmation.')
              this.isVoiceModeActive = false // Ensure client state matches
              this.stopRecording() // Ensure recording stops
              break
            case 'error':
              this.error = data.message
              this.isProcessingLLM = false
              this.isSynthesizingTTS = false
              this.isPlayingTTS = false
              this.currentInterimStt = ''
              break
            case 'warning':
              this.addMessage('ai', `경고: ${data.message}`)
              break
            default:
              console.warn('Unknown WebSocket message type:', data.type)
          }
        } catch (e) {
          console.error('Error parsing WebSocket message or in handler:', e)
          this.error = '서버로부터 잘못된 형식의 메시지를 받았습니다.'
        }
      }
      // ... (onerror, onclose handlers remain similar)
      this.webSocket.onerror = (errorEvent) => {
        console.error('WebSocket error:', errorEvent)
        this.error = 'WebSocket 연결 중 오류가 발생했습니다.'
        this.isWebSocketConnected = false
        this.isProcessingLLM = false
        this.isSynthesizingTTS = false
        this.isPlayingTTS = false
        this.isVoiceModeActive = false
        this.stopRecording()
      }

      this.webSocket.onclose = (closeEvent) => {
        console.log('WebSocket connection closed:', closeEvent.code, closeEvent.reason)
        this.isWebSocketConnected = false
        this.isProcessingLLM = false
        this.isSynthesizingTTS = false
        this.isPlayingTTS = false
        if (!closeEvent.wasClean) {
          this.error = 'WebSocket 연결이 비정상적으로 종료되었습니다.'
        }
        this.isVoiceModeActive = false
        this.stopRecording()
      }
    },

    async toggleVoiceMode() {
      if (!this.isWebSocketConnected) {
          this.initializeSessionAndConnect();
          await new Promise(resolve => {
              const check = () => this.isWebSocketConnected ? resolve(true) : setTimeout(check, 100);
              check();
          });
      }
      if (!this.isWebSocketConnected) { // Still not connected after attempt
           this.error = "서버 연결 실패. 음성 인식을 시작할 수 없습니다.";
           return;
      }

      if (this.isVoiceModeActive) {
          await this.deactivateVoiceRecognition();
      } else {
          await this.activateVoiceRecognition();
      }
  },

  async activateVoiceRecognition() {
      if (!this.isWebSocketConnected || !this.webSocket || this.webSocket.readyState !== WebSocket.OPEN) {
          this.error = "음성 인식을 시작하려면 서버에 연결되어 있어야 합니다.";
          return;
      }
      this.isVoiceModeActive = true;
      this.webSocket.send(JSON.stringify({ type: 'activate_voice' }));
      await this.startRecording(); 
      this.currentInterimStt = "듣고 있어요...";
      this.error = null; // Clear previous errors
  },

  async deactivateVoiceRecognition() {
      await this.stopRecording(); // Stop client-side recording first
      if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN && this.isVoiceModeActive) { // Check isVoiceModeActive before sending
          this.webSocket.send(JSON.stringify({ type: 'deactivate_voice' }));
      }
      this.isVoiceModeActive = false; // Set after operations
      this.currentInterimStt = "";
      this.isEPDDetectedByServer = false;
      this.stopClientSideVAD(); // VAD 중지
  },

  async startRecording() {
    if (this.isRecording || !this.isVoiceModeActive) return;
    try {
      const constraints = { audio: { echoCancellation: true, noiseSuppression: true } };
      this.audioStream = await navigator.mediaDevices.getUserMedia(constraints);
      
      if (this.isPlayingTTS) {
          console.log("사용자 녹음 시작 중 TTS 재생 감지. Barge-in을 위해 TTS 중단.");
          this.stopClientSideTTSPlayback(true); 
      }

      const options = { mimeType: 'audio/webm; codecs=opus', audioBitsPerSecond: 64000 };
      this.mediaRecorder = new MediaRecorder(this.audioStream, options);

      this.mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0 && this.isWebSocketConnected && this.isVoiceModeActive && this.isRecording) {
          this.sendAudioBlob(event.data);
        }
      };
      this.mediaRecorder.onstart = () => { this.isRecording = true; console.log('MediaRecorder started.'); };
      this.mediaRecorder.onstop = () => {
        this.isRecording = false;
        console.log('MediaRecorder stopped.');
        if (this.audioStream) {
          this.audioStream.getTracks().forEach(track => track.stop());
        }
        // Note: Don't nullify this.audioStream here if VAD needs it right after.
        // VAD should use its own reference or be stopped before this.audioStream is nullified.
        // Best to stop VAD in deactivateVoiceRecognition or when isVoiceModeActive turns false.
        this.currentInterimStt = ""; 
      };
      this.mediaRecorder.onerror = (event) => {
          console.error('MediaRecorder error:', event);
          this.error = `마이크 녹음 오류: ${ (event as any)?.error?.name || '알수없음'}`;
          this.deactivateVoiceRecognition();
      };
      this.mediaRecorder.start(500); 
    } catch (err) {
      console.error('Error starting recording:', err);
      this.error = '마이크 접근에 실패했습니다. 브라우저 설정을 확인해주세요.';
      if(this.isVoiceModeActive) this.isVoiceModeActive = false; 
    }
  },

  async stopRecording() {
    if (this.mediaRecorder && this.isRecording) {
      this.mediaRecorder.stop();
    }
    // audioStream is stopped in mediaRecorder.onstop
    // VAD should also be stopped if recording stops due to voice deactivation
    this.stopClientSideVAD();
  },

  sendWebSocketTextMessage(text: string) {
    if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
      if (this.isVoiceModeActive) { // 사용자가 텍스트 입력시 음성모드 비활성화
          this.deactivateVoiceRecognition();
      }
      this.addMessage('user', text);
      this.webSocket.send(JSON.stringify({ type: 'process_text', text: text, input_mode: 'text' }));
      this.isProcessingLLM = true;
      this.error = null;
    } else {
      this.handleWebSocketNotConnected('텍스트 메시지');
    }
  },

  sendAudioBlob(audioBlob: Blob) {
    if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN && this.isVoiceModeActive) {
      this.webSocket.send(audioBlob);
      this.error = null;
    } else if (!this.isVoiceModeActive) {
      // console.log("Audio blob not sent: Voice mode is not active.");
    } else {
      this.handleWebSocketNotConnected('오디오 데이터');
    }
  },
  
  stopClientSideTTSPlayback(notifyServer: boolean) {
      console.log(`Client attempting to stop TTS. Notify server: ${notifyServer}. Currently playing: ${this.isPlayingTTS}`);
      if (this.currentPlayingAudioElement) {
          this.currentPlayingAudioElement.pause();
          this.currentPlayingAudioElement.src = ''; 
          this.currentPlayingAudioElement.onended = null; // 중요: 이전 onended 핸들러 제거
          this.currentPlayingAudioElement.onerror = null; // 중요: 이전 onerror 핸들러 제거
          this.currentPlayingAudioElement = null;
      }
      this.ttsAudioQueue = []; 
      this.isPlayingTTS = false;
      this.isSynthesizingTTS = false; // 서버로부터 TTS 데이터를 더 이상 기대하지 않음 (또는 현재 세그먼트 중단)
      this.stopClientSideVAD(); // TTS 중단 시 VAD도 일단 중지 (필요시 playNextTtsAudioFromQueue에서 다시 시작)

      if (notifyServer && this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
          this.webSocket.send(JSON.stringify({ type: 'stop_tts' }));
          console.log('Sent stop_tts to server.');
      }
  },
  
  playNextTtsAudioFromQueue() {
      if (this.isPlayingTTS || this.ttsAudioQueue.length === 0) {
          return;
      }
      this.isPlayingTTS = true;
      const audioBase64 = this.ttsAudioQueue.shift();
      
      if (audioBase64) {
          const audioSrc = `data:audio/mp3;base64,${audioBase64}`;
          this.currentPlayingAudioElement = new Audio(audioSrc); // 항상 새 Audio 객체 생성
          
          this.currentPlayingAudioElement.play()
              .then(() => { console.log("TTS audio chunk playing."); })
              .catch(error => {
                  console.error("Error playing TTS audio chunk:", error);
                  this.isPlayingTTS = false;
                  this.playNextTtsAudioFromQueue(); 
              });

          this.currentPlayingAudioElement.onended = () => {
              console.log("TTS audio chunk finished.");
              this.isPlayingTTS = false;
              if (this.currentPlayingAudioElement) { // Defensive check
                  this.currentPlayingAudioElement.onended = null; // Clean up to prevent multiple calls
                  this.currentPlayingAudioElement.onerror = null;
              }
              this.playNextTtsAudioFromQueue(); 
          };
          this.currentPlayingAudioElement.onerror = (e) => {
              console.error("Error during TTS audio element playback:", e);
              this.isPlayingTTS = false;
              this.error = "TTS 오디오 재생 중 오류가 발생했습니다.";
               if (this.currentPlayingAudioElement) { // Defensive check
                  this.currentPlayingAudioElement.onended = null;
                  this.currentPlayingAudioElement.onerror = null;
              }
              this.playNextTtsAudioFromQueue();
          };
          
          // TTS 재생 시작 시 Client VAD 활성화 (지연 포함)
          if(this.isVoiceModeActive) {
              this.startClientSideVAD();
          }

      } else {
          this.isPlayingTTS = false; 
      }
  },

  startClientSideVAD() {
      this.stopClientSideVAD(); // Clear any existing VAD intervals/timeouts

      if (!this.isVoiceModeActive || !this.isPlayingTTS || !this.audioStream) {
          return;
      }

      this.vadContext.vadActivationTimeoutId = window.setTimeout(() => {
          if (!this.isVoiceModeActive || !this.isPlayingTTS || !this.audioStream) {
              this.stopClientSideVAD(); // Re-check conditions
              return;
          }

          if (!this.vadContext.audioContext && this.audioStream) {
              try {
                  this.vadContext.audioContext = new AudioContext();
                  this.vadContext.analyserNode = this.vadContext.audioContext.createAnalyser();
                  this.vadContext.analyserNode.fftSize = 512; // Smaller FFT for faster response
                  this.vadContext.analyserNode.smoothingTimeConstant = 0.5;
                  this.vadContext.dataArray = new Uint8Array(this.vadContext.analyserNode.frequencyBinCount);
                  const source = this.vadContext.audioContext.createMediaStreamSource(this.audioStream);
                  source.connect(this.vadContext.analyserNode);
              } catch (e) {
                  console.error("Error setting up VAD audio context:", e);
                  this.stopClientSideVAD();
                  return;
              }
          }
          
          const VAD_THRESHOLD = 8; // 매우 낮은 값으로 시작하여 민감도 테스트 필요
          const SILENCE_FRAMES_NEEDED = 3; // 연속된 침묵 프레임 수 (150ms * 3 = 450ms 침묵 후 비활성 간주)
          let silenceFrames = 0;

          this.vadContext.vadIntervalId = window.setInterval(() => {
              if (!this.vadContext.analyserNode || !this.vadContext.dataArray || !this.isPlayingTTS || !this.isVoiceModeActive) {
                  this.stopClientSideVAD();
                  return;
              }
              this.vadContext.analyserNode.getByteFrequencyData(this.vadContext.dataArray);
              let sum = 0;
              for (let i = 0; i < this.vadContext.dataArray.length; i++) { sum += this.vadContext.dataArray[i]; }
              const average = sum / this.vadContext.dataArray.length;
              
              if (average > VAD_THRESHOLD) {
                  console.log(`Client VAD: User speaking detected (avg: ${average.toFixed(2)}). Stopping TTS for barge-in.`);
                  this.stopClientSideTTSPlayback(true); 
                  // VAD 자체는 여기서 중단 (stopClientSideTTSPlayback이 stopClientSideVAD 호출)
              } else {
                  // console.log(`Client VAD: silence (avg: ${average.toFixed(2)})`);
              }
          }, 150); // Check every 150ms
      }, 400); // VAD 활성화까지 400ms 지연 (TTS 시작음 무시)
  },

  stopClientSideVAD() {
      if (this.vadContext.vadActivationTimeoutId) {
          clearTimeout(this.vadContext.vadActivationTimeoutId);
          this.vadContext.vadActivationTimeoutId = null;
      }
      if (this.vadContext.vadIntervalId) {
          clearInterval(this.vadContext.vadIntervalId);
          this.vadContext.vadIntervalId = null;
      }
      // 오디오 컨텍스트는 재사용 가능하지만, 스트림이 변경될 때마다 소스를 다시 연결해야 하므로
      // 필요에 따라 여기서 닫거나 null로 설정할 수 있습니다.
      // if (this.vadContext.audioContext && this.vadContext.audioContext.state !== 'closed') {
      //     this.vadContext.audioContext.close();
      // }
      // this.vadContext.audioContext = null;
      // this.vadContext.analyserNode = null;
      // this.vadContext.dataArray = null;
      // console.log("Client-side VAD stopped.");
  },
  
  // ... (addMessage, appendAiMessageChunk, finalizeAiMessage, handleWebSocketNotConnected 등은 이전과 유사하게 유지) ...
  handleWebSocketNotConnected(actionDescription: string) {
    console.error(`Cannot send ${actionDescription}: WebSocket is not connected.`)
    this.error = `서버와 연결되지 않아 ${actionDescription}을 전송할 수 없습니다. 페이지를 새로고침하거나 잠시 후 다시 시도해주세요.`
  },
  addMessage(sender: 'user' | 'ai', text: string) {
    const newMessage: Message = { id: uuidv4(), sender, text, timestamp: new Date(), isStreaming: false, isInterimStt: false, };
    this.messages.push(newMessage);
  },
  appendAiMessageChunk(chunk: string) {
    const lastMessage = this.messages[this.messages.length - 1];
    if (lastMessage && lastMessage.sender === 'ai' && lastMessage.isStreaming) {
      lastMessage.text += chunk;
    } else {
      this.finalizeAiMessage(); 
      this.messages.push({ id: uuidv4(), sender: 'ai', text: chunk, timestamp: new Date(), isStreaming: true, });
    }
  },
  finalizeAiMessage() {
    const lastMessage = this.messages[this.messages.length - 1];
    if (lastMessage && lastMessage.sender === 'ai' && lastMessage.isStreaming) {
      lastMessage.isStreaming = false;
    }
  },
  clearTtsAudioQueue() { this.ttsAudioQueue = [] },
  disconnectWebSocket() {
    if (this.isVoiceModeActive) { this.deactivateVoiceRecognition(); }
    this.stopClientSideTTSPlayback(false); // 로컬 재생 중단
    if (this.webSocket) {
      this.webSocket.onopen = null; this.webSocket.onmessage = null; this.webSocket.onerror = null; this.webSocket.onclose = null;
      if (this.webSocket.readyState === WebSocket.OPEN || this.webSocket.readyState === WebSocket.CONNECTING) {
          this.webSocket.close(1000, 'Client initiated disconnect');
      }
      this.webSocket = null; 
    }
    this.isWebSocketConnected = false;
    console.log('WebSocket disconnected by client action.');
  },
},
getters: {
  // ... (기존 getters) ...
  getMessages: (state): Message[] => state.messages,
  getIsProcessingLLM: (state): boolean => state.isProcessingLLM,
  getIsSynthesizingTTS: (state): boolean => state.isSynthesizingTTS, 
  getIsPlayingTTS: (state): boolean => state.isPlayingTTS, 
  getError: (state): string | null => state.error,
  getSessionId: (state): string | null => state.sessionId,
  getInterimStt: (state): string => state.currentInterimStt,
  getIsWebSocketConnected: (state): boolean => state.isWebSocketConnected,
  getIsVoiceModeActive: (state): boolean => state.isVoiceModeActive,
  getIsRecording: (state): boolean => state.isRecording,
  getIsEPDDetectedByServer: (state): boolean => state.isEPDDetectedByServer,
},
})
