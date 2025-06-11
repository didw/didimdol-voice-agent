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

interface AudioSegment { // Represents audio for one sentence
  id: string;
  audioChunks: string[]; // base64 encoded MP3 chunks
}

interface ChatState {
  sessionId: string | null
  messages: Message[]
  isProcessingLLM: boolean
  isSynthesizingTTS: boolean

  ttsAudioSegmentQueue: AudioSegment[]
  _incomingTTSChunksForSentence: string[] 
  
  error: string | null
  currentInterimStt: string
  isWebSocketConnected: boolean
  webSocket: WebSocket | null
  
  isVoiceModeActive: boolean
  isRecording: boolean
  audioContext: AudioContext | null
  // --- 변경점: ScriptProcessorNode를 AudioWorkletNode로 교체 ---
  audioWorkletNode: AudioWorkletNode | null
  audioStream: MediaStream | null 
  
  isPlayingTTS: boolean
  currentPlayingAudioElement: HTMLAudioElement | null 
  _currentPlayingAudioSegmentChunks: string[]

  isEPDDetectedByServer: boolean

  vadContext: { 
    audioContext: AudioContext | null;
    analyserNode: AnalyserNode | null;
    dataArray: Uint8Array | null;
    vadIntervalId: number | null;
    vadActivationTimeoutId: number | null; 
  }
}


const WEBSOCKET_URL_BASE =
  import.meta.env.VITE_WEBSOCKET_URL || 'wss://3.36.13.147/api/v1/chat/ws/'

export const useChatStore = defineStore('chat', {
  state: (): ChatState => ({
    sessionId: null,
    messages: [],
    isProcessingLLM: false,
    isSynthesizingTTS: false,

    ttsAudioSegmentQueue: [],
    _incomingTTSChunksForSentence: [],
    _currentPlayingAudioSegmentChunks: [],

    error: null,
    currentInterimStt: '',
    isWebSocketConnected: false,
    webSocket: null,
    
    isVoiceModeActive: false,
    isRecording: false,
    audioContext: null,
    // --- 변경점: 초기 상태값 변경 ---
    audioWorkletNode: null,
    audioStream: null,

    isPlayingTTS: false,
    currentPlayingAudioElement: null,
    isEPDDetectedByServer: false,

    vadContext: { 
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
        console.log('ONOPEN: WebSocket connection established for session:', this.sessionId);
        this.isWebSocketConnected = true;
        this.error = null;
      };

      this.webSocket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data as string)
          switch (data.type) {
            case 'session_initialized':
              this.addMessage('ai', data.message)
              break
            case 'stt_interim_result':
              if (this.isVoiceModeActive) {
                this.currentInterimStt = data.transcript
              }
              break
            case 'stt_final_result':
              this.currentInterimStt = '' 
              if (data.transcript) {
                this.addMessage('user', data.transcript)
                this.isProcessingLLM = true 
              }
              break
            case 'llm_response_chunk':
              this.appendAiMessageChunk(data.chunk)
              this.isProcessingLLM = true
              break
            case 'llm_response_end':
              this.finalizeAiMessage()
              this.isProcessingLLM = false
              break
            case 'tts_audio_chunk': 
              this._incomingTTSChunksForSentence.push(data.audio_chunk_base64);
              break;
            case 'tts_stream_end':
              if (this._incomingTTSChunksForSentence.length > 0) {
                this.ttsAudioSegmentQueue.push({
                  id: uuidv4(),
                  audioChunks: [...this._incomingTTSChunksForSentence],
                });
                this._incomingTTSChunksForSentence = [];
              }
              this.playNextQueuedAudioSegment();
              break;
            case 'epd_detected': 
              console.log('EPD detected by server (Google STT for previous user utterance)');
              this.isEPDDetectedByServer = true; 
              if (this.isPlayingTTS && this.isVoiceModeActive) {
                console.log('Server EPD received while AI TTS playing in voice mode. Client-side VAD handles barge-in.');
              } else if (this.isPlayingTTS && !this.isVoiceModeActive) {
                console.log('Server EPD received while AI TTS playing (NOT in voice mode). Stopping client TTS playback locally.');
                this.stopClientSideTTSPlayback(false);
              }
              break;
            case 'voice_activated':
              console.log('Voice mode activated by server confirmation.')
              break
            case 'voice_deactivated':
              console.log('Voice mode deactivated by server confirmation.')
              this.isVoiceModeActive = false 
              this.stopRecording() 
              break
            case 'error':
              this.error = data.message
              this.isProcessingLLM = false
              this.isPlayingTTS = false
              this._incomingTTSChunksForSentence = [];
              this._currentPlayingAudioSegmentChunks = [];
              this.ttsAudioSegmentQueue = [];
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
      this.webSocket.onerror = (errorEvent) => {
        console.error('ONERROR: WebSocket error. Event:', errorEvent);
        this.error = 'WebSocket 연결 중 오류가 발생했습니다.'
        this.isWebSocketConnected = false
        this.isProcessingLLM = false
        this.isPlayingTTS = false
        this.isVoiceModeActive = false
        this.stopRecording()
      }
      this.webSocket.onclose = (closeEvent) => {
        console.log(
          'ONCLOSE: WebSocket connection closed. Code:', closeEvent.code,
          'Reason:', closeEvent.reason,
          'WasClean:', closeEvent.wasClean
        );
        this.isWebSocketConnected = false
        this.isProcessingLLM = false
        this.isPlayingTTS = false
        if (!closeEvent.wasClean) {
          this.error = 'WebSocket 연결이 예상치 않게 종료되었습니다. (Code: ' + closeEvent.code + ')';
        }
        this.isVoiceModeActive = false
        this.stopRecording()
      }
    },

    async toggleVoiceMode() {
      if (!this.isWebSocketConnected || (this.webSocket && this.webSocket.readyState !== WebSocket.OPEN) ) {
          this.initializeSessionAndConnect();
          await new Promise(resolve => {
              const interval = setInterval(() => {
                  if (this.isWebSocketConnected) {
                      clearInterval(interval);
                      resolve(true);
                  }
              }, 100);
              setTimeout(() => {
                  clearInterval(interval);
                  if (!this.isWebSocketConnected) resolve(false);
              }, 3000);
          });
      }

      if (!this.isWebSocketConnected) { 
          this.error = "서버 연결 실패. 음성 인식을 시작할 수 없습니다.";
          console.error(this.error);
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
    if (this.isPlayingTTS) {
        console.log("Activating voice recognition, stopping current TTS playback.");
        this.stopClientSideTTSPlayback(true);
    }
    this.isVoiceModeActive = true;
    this.webSocket.send(JSON.stringify({ type: 'activate_voice' }));
    await this.startRecording(); 
    this.currentInterimStt = "듣고 있어요...";
    this.error = null;
},

async deactivateVoiceRecognition() {
  await this.stopRecording(); 
  if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN && this.isVoiceModeActive) { 
      this.webSocket.send(JSON.stringify({ type: 'deactivate_voice' }));
  }
  this.isVoiceModeActive = false; 
  this.currentInterimStt = "";
  this.isEPDDetectedByServer = false;
  this.stopClientSideVAD();
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

    // --- 변경점: Web Audio API 로직을 AudioWorklet으로 전면 교체 ---
    this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
    
    // AudioWorklet 모듈을 로드합니다. 파일 경로는 public 폴더를 기준으로 합니다.
    await this.audioContext.audioWorklet.addModule('/audio-processor.js');
    
    // 'audio-processor'라는 이름으로 등록된 커스텀 노드를 생성합니다.
    this.audioWorkletNode = new AudioWorkletNode(this.audioContext, 'audio-processor');

    // 마이크 스트림을 AudioContext의 소스로 연결합니다.
    const source = this.audioContext.createMediaStreamSource(this.audioStream);
    
    // 소스를 워크릿 노드에 연결하여 오디오 데이터 처리를 시작합니다.
    source.connect(this.audioWorkletNode);

    // (선택사항) 워크릿 노드를 스피커(destination)에 연결하면 마이크 소리를 들을 수 있습니다.
    // 디버깅 용도가 아니라면 주석 처리하는 것이 좋습니다.
    // this.audioWorkletNode.connect(this.audioContext.destination);

    // 워크릿에서 처리된 오디오 데이터를 받을 리스너를 설정합니다.
    this.audioWorkletNode.port.onmessage = (event) => {
      // 녹음 중이 아닐 때는 데이터를 무시합니다.
      if (!this.isRecording) return;

      // event.data는 워크릿에서 보낸 ArrayBuffer입니다.
      const audioChunk = event.data as ArrayBuffer;

      if (audioChunk.byteLength > 0 && this.isWebSocketConnected && this.isVoiceModeActive) {
        this.sendAudioChunk(audioChunk);
      }
    };
    
    this.audioWorkletNode.port.onmessageerror = (error) => {
        console.error("Error receiving message from AudioWorklet:", error);
    };

    this.isRecording = true;
    console.log('Recording started using AudioWorklet.');
    // --- 교체 끝 ---

  } catch (err) {
    console.error('Error starting recording or setting up AudioWorklet:', err);
    this.error = '마이크 접근 또는 오디오 처리 모듈 설정에 실패했습니다.';
    if(this.isVoiceModeActive) this.isVoiceModeActive = false;
    await this.stopRecording(); // 실패 시 자원 정리
  }
},

async stopRecording() {
  if (!this.isRecording && !this.audioContext) return;

  this.isRecording = false;

  // --- 변경점: AudioWorkletNode 및 AudioContext 정리 로직으로 수정 ---
  if (this.audioWorkletNode) {
    this.audioWorkletNode.port.close(); // 포트 닫기
    this.audioWorkletNode.disconnect();
    this.audioWorkletNode = null;
  }
  if (this.audioContext && this.audioContext.state !== 'closed') {
    // close()는 Promise를 반환하는 비동기 작업입니다.
    await this.audioContext.close();
    this.audioContext = null;
  }
  // --- 교체 끝 ---

  this.stopClientSideVAD(); 
  if (this.audioStream) {
      this.audioStream.getTracks().forEach(track => track.stop());
      this.audioStream = null;
  }
  console.log('Recording stopped.');
},

sendAudioChunk(audioChunk: ArrayBuffer) {
  if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN && this.isVoiceModeActive) {
    this.webSocket.send(audioChunk);
    this.error = null;
  } else if (!this.isVoiceModeActive) {
    // console.log("Audio chunk not sent: Voice mode is not active.");
  } else {
    this.handleWebSocketNotConnected('오디오 데이터');
  }
},

sendWebSocketTextMessage(text: string) {
  if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
    if (this.isVoiceModeActive) { 
        this.deactivateVoiceRecognition();
    }
    if (this.isPlayingTTS) {
        this.stopClientSideTTSPlayback(true);
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
      this.currentPlayingAudioElement.removeAttribute('src'); 
      this.currentPlayingAudioElement.load(); 
      this.currentPlayingAudioElement.onended = null; 
      this.currentPlayingAudioElement.onerror = null;
      this.currentPlayingAudioElement = null;
  }
  this._currentPlayingAudioSegmentChunks = []; 
  this.ttsAudioSegmentQueue = []; 
  this._incomingTTSChunksForSentence = [];
  
  this.isPlayingTTS = false;

  this.stopClientSideVAD(); 

  if (notifyServer && this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
      this.webSocket.send(JSON.stringify({ type: 'stop_tts' }));
      console.log('Sent stop_tts to server.');
  }
},

playNextQueuedAudioSegment() {
  if (this.isPlayingTTS || this.ttsAudioSegmentQueue.length === 0) {
    if (this.ttsAudioSegmentQueue.length === 0 && !this.isPlayingTTS) {
        console.log("All TTS audio segments played.");
        if(this.isVoiceModeActive && !this.isRecording) {
        }
    }
    return;
  }

  const segmentToPlay = this.ttsAudioSegmentQueue.shift();
  if (segmentToPlay && segmentToPlay.audioChunks.length > 0) {
    this._currentPlayingAudioSegmentChunks = [...segmentToPlay.audioChunks];
    console.log(`Starting playback for new audio segment with ${this._currentPlayingAudioSegmentChunks.length} chunks.`);
    this.playNextChunkFromCurrentSegment();
  } else {
    this.playNextQueuedAudioSegment();
  }
},

playNextChunkFromCurrentSegment() {
  if (this._currentPlayingAudioSegmentChunks.length === 0) {
    console.log("Finished all chunks for the current audio segment.");
    if(this.currentPlayingAudioElement) {
        this.currentPlayingAudioElement.onended = null;
        this.currentPlayingAudioElement.onerror = null;
    }
    this.isPlayingTTS = false; 
    this.playNextQueuedAudioSegment();
    return;
  }

  this.isPlayingTTS = true;
  const audioBase64 = this._currentPlayingAudioSegmentChunks.shift();
  
  if (audioBase64) {
    const audioSrc = `data:audio/mp3;base64,${audioBase64}`;
    this.currentPlayingAudioElement = new Audio(audioSrc); 
    
    this.currentPlayingAudioElement.play()
        .then(() => { })
        .catch(error => {
            console.error("Error playing TTS audio chunk:", error);
            this.isPlayingTTS = false;
            this._currentPlayingAudioSegmentChunks = [];
            this.playNextQueuedAudioSegment();
        });

    this.currentPlayingAudioElement.onended = () => {
        this.playNextChunkFromCurrentSegment();
    };
    this.currentPlayingAudioElement.onerror = (e) => {
        console.error("Error during TTS audio element playback:", e);
        this.error = "TTS 오디오 재생 중 오류가 발생했습니다.";
        this.isPlayingTTS = false;
        this._currentPlayingAudioSegmentChunks = [];
        this.playNextQueuedAudioSegment();
    };
    
    if(this.isVoiceModeActive) {
        this.startClientSideVAD();
    }

  } else { 
    this.isPlayingTTS = false;
    this.playNextQueuedAudioSegment();
  }
},

startClientSideVAD() {
  this.stopClientSideVAD(); 

  if (!this.isVoiceModeActive || !this.isPlayingTTS || !this.audioStream) {
      return;
  }

  this.vadContext.vadActivationTimeoutId = window.setTimeout(() => {
      if (!this.isVoiceModeActive || !this.isPlayingTTS || !this.audioStream || this.audioStream.getAudioTracks().every(t => t.readyState === 'ended')) {
          this.stopClientSideVAD(); 
          return;
      }

      try {
          if (!this.vadContext.audioContext || this.vadContext.audioContext.state === 'closed') {
            this.vadContext.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
          }
          if (!this.vadContext.analyserNode) { 
              this.vadContext.analyserNode = this.vadContext.audioContext.createAnalyser();
              this.vadContext.analyserNode.fftSize = 512; 
              this.vadContext.analyserNode.smoothingTimeConstant = 0.5;
              this.vadContext.dataArray = new Uint8Array(this.vadContext.analyserNode.frequencyBinCount);
              if (this.audioStream && this.audioStream.getAudioTracks().length > 0 && this.audioStream.getAudioTracks()[0].readyState === 'live') {
                  const source = this.vadContext.audioContext.createMediaStreamSource(this.audioStream);
                  source.connect(this.vadContext.analyserNode);
              } else {
                  console.warn("VAD: AudioStream not valid for creating source.");
                  this.stopClientSideVAD();
                  return;
              }
          }
      } catch (e) {
          console.error("Error setting up VAD audio context:", e);
          this.stopClientSideVAD();
          return;
      }
      
      const VAD_THRESHOLD = 10;
      const SPEECH_FRAMES_NEEDED_FOR_BARGE_IN = 2;
      let consecutiveSpeechFrames = 0;

      this.vadContext.vadIntervalId = window.setInterval(() => {
          if (!this.vadContext.analyserNode || !this.vadContext.dataArray || !this.isPlayingTTS || !this.isVoiceModeActive) {
              this.stopClientSideVAD();
              return;
          }
          this.vadContext.analyserNode.getByteFrequencyData(this.vadContext.dataArray);
          let sum = 0;
          for (let i = 0; i < this.vadContext.dataArray.length; i++) { sum += this.vadContext.dataArray[i]; }
          const average = this.vadContext.dataArray.length > 0 ? sum / this.vadContext.dataArray.length : 0;
          
          if (average > VAD_THRESHOLD) {
              consecutiveSpeechFrames++;
              if (consecutiveSpeechFrames >= SPEECH_FRAMES_NEEDED_FOR_BARGE_IN) {
                 console.log(`Client VAD: User speaking detected (avg: ${average.toFixed(2)}). Stopping TTS for barge-in.`);
                 this.stopClientSideTTSPlayback(true); 
              }
          } else {
              consecutiveSpeechFrames = 0;
          }
      }, 100);
  }, 300);
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
},

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
disconnectWebSocket() {
if (this.isVoiceModeActive) { this.deactivateVoiceRecognition(); }
this.stopClientSideTTSPlayback(false); 
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
getMessages: (state): Message[] => state.messages,
getIsProcessingLLM: (state): boolean => state.isProcessingLLM,
getIsPlayingTTS: (state): boolean => state.isPlayingTTS, 
getError: (state): string | null => state.error,
getSessionId: (state): string | null => state.sessionId,
getInterimStt: (state): string => state.currentInterimStt,
getIsWebSocketConnected: (state): boolean => state.isWebSocketConnected,
getIsVoiceModeActive: (state): boolean => state.isVoiceModeActive,
getIsRecording: (state): boolean => state.isRecording,
getIsEPDDetectedByServer: (state): boolean => state.isEPDDetectedByServer,
getIsSynthesizingTTS: (state) => state.isSynthesizingTTS,
},
})