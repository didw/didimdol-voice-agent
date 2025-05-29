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
  // isSynthesizingTTS: boolean // Indicates if server is *currently* sending any TTS chunk for *any* sentence
  
  // New state for sentence-based TTS playback
  ttsAudioSegmentQueue: AudioSegment[] // Queue of complete sentence audio data
  _incomingTTSChunksForSentence: string[] // Temp buffer for chunks of the sentence currently being received from server
  
  error: string | null
  currentInterimStt: string
  isWebSocketConnected: boolean
  webSocket: WebSocket | null
  
  isVoiceModeActive: boolean
  isRecording: boolean
  mediaRecorder: MediaRecorder | null
  audioStream: MediaStream | null 
  
  isPlayingTTS: boolean // True if any audio element is currently playing a chunk
  currentPlayingAudioElement: HTMLAudioElement | null 
  _currentPlayingAudioSegmentChunks: string[] // Chunks of the sentence currently being played by audio element

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
  import.meta.env.VITE_WEBSOCKET_URL || 'ws://localhost:8000/api/v1/chat/ws/'

export const useChatStore = defineStore('chat', {
  state: (): ChatState => ({
    sessionId: null,
    messages: [],
    isProcessingLLM: false,
    // isSynthesizingTTS: false, // Replaced by queue logic mostly

    ttsAudioSegmentQueue: [],
    _incomingTTSChunksForSentence: [],
    _currentPlayingAudioSegmentChunks: [],

    error: null,
    currentInterimStt: '',
    isWebSocketConnected: false,
    webSocket: null,
    
    isVoiceModeActive: false,
    isRecording: false,
    mediaRecorder: null,
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
        console.log('WebSocket connection established for session:', this.sessionId)
        this.isWebSocketConnected = true
        this.error = null
      }

      this.webSocket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data as string)
          // console.log('WebSocket message received:', data); // Can be too verbose for chunks

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
              // Backend will now start sending TTS sentence by sentence if in voice mode.
              break
            case 'tts_audio_chunk': // Chunk for the current sentence from backend
              // console.log("Received TTS audio chunk from server.");
              this._incomingTTSChunksForSentence.push(data.audio_chunk_base64);
              break;
            case 'tts_stream_end': // All chunks for *one sentence* have been received
              console.log("End of TTS audio stream for one sentence received from server.");
              if (this._incomingTTSChunksForSentence.length > 0) {
                this.ttsAudioSegmentQueue.push({
                  id: uuidv4(),
                  audioChunks: [...this._incomingTTSChunksForSentence],
                });
                this._incomingTTSChunksForSentence = []; // Reset for next sentence
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
              this.isPlayingTTS = false // Stop TTS on error
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
        console.error('WebSocket error:', errorEvent)
        this.error = 'WebSocket 연결 중 오류가 발생했습니다.'
        this.isWebSocketConnected = false
        this.isProcessingLLM = false
        this.isPlayingTTS = false
        this.isVoiceModeActive = false
        this.stopRecording()
      }
      this.webSocket.onclose = (closeEvent) => {
        console.log('WebSocket connection closed:', closeEvent.code, closeEvent.reason)
        this.isWebSocketConnected = false
        this.isProcessingLLM = false
        this.isPlayingTTS = false
        if (!closeEvent.wasClean) {
          this.error = 'WebSocket 연결이 비정상적으로 종료되었습니다.'
        }
        this.isVoiceModeActive = false
        this.stopRecording()
      }
    },

    async toggleVoiceMode() {
        if (!this.isWebSocketConnected || (this.webSocket && this.webSocket.readyState !== WebSocket.OPEN) ) {
            this.initializeSessionAndConnect();
            // Wait for connection to establish
            await new Promise(resolve => {
                const interval = setInterval(() => {
                    if (this.isWebSocketConnected) {
                        clearInterval(interval);
                        resolve(true);
                    }
                }, 100);
                setTimeout(() => { // Timeout for connection attempt
                    clearInterval(interval);
                    if (!this.isWebSocketConnected) resolve(false);
                }, 3000); // 3 seconds timeout
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
        // Stop any ongoing TTS playback before activating voice input
        if (this.isPlayingTTS) {
            console.log("Activating voice recognition, stopping current TTS playback.");
            this.stopClientSideTTSPlayback(true); // Notify server to stop sending more TTS
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
        const constraints = { audio: { echoCancellation: true, noiseSuppression: true, sampleRate: 48000 } };
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
            // this.audioStream = null; // VAD might still need this reference if active right after
          }
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
      // If VAD is using audioStream, it should be stopped before or when audioStream is nullified
      this.stopClientSideVAD(); 
      if (this.audioStream) { // Ensure audioStream tracks are stopped if recorder didn't do it
          this.audioStream.getTracks().forEach(track => track.stop());
          this.audioStream = null;
      }
    },

    sendWebSocketTextMessage(text: string) {
      if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        if (this.isVoiceModeActive) { 
            this.deactivateVoiceRecognition();
        }
        // If TTS is playing when user sends text, stop it for barge-in
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
            this.currentPlayingAudioElement.removeAttribute('src'); // More robust than src = ''
            this.currentPlayingAudioElement.load(); // Advised after changing src
            this.currentPlayingAudioElement.onended = null; 
            this.currentPlayingAudioElement.onerror = null;
            this.currentPlayingAudioElement = null;
        }
        this._currentPlayingAudioSegmentChunks = []; // Clear chunks of the sentence that was playing
        this.ttsAudioSegmentQueue = []; // Clear queue of upcoming sentences
        this._incomingTTSChunksForSentence = []; // Clear any partially received sentence
        
        this.isPlayingTTS = false;
        // this.isSynthesizingTTS = false; // Only backend truly knows this; client stops expecting

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
            // Potentially enable VAD again if in voice mode and expecting user input
            if(this.isVoiceModeActive && !this.isRecording) {
                // This case is tricky: if AI just finished speaking, should VAD auto-start for user?
                // Typically, user clicks mic button or there's hotword detection.
                // For now, we don't auto-start VAD here.
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
        // Segment was empty or undefined, try next
        this.playNextQueuedAudioSegment();
      }
    },

    playNextChunkFromCurrentSegment() {
      if (this._currentPlayingAudioSegmentChunks.length === 0) {
        console.log("Finished all chunks for the current audio segment.");
        // this.isPlayingTTS should be set to false before trying to play the next segment
        // to avoid race conditions / re-entry issues in playNextQueuedAudioSegment.
        if(this.currentPlayingAudioElement) { // Clean up previous audio element
            this.currentPlayingAudioElement.onended = null;
            this.currentPlayingAudioElement.onerror = null;
        }
        this.isPlayingTTS = false; 
        this.playNextQueuedAudioSegment(); // Attempt to play the next sentence/segment
        return;
      }

      this.isPlayingTTS = true; // Mark as playing *before* taking a chunk
      const audioBase64 = this._currentPlayingAudioSegmentChunks.shift();
      
      if (audioBase64) {
        const audioSrc = `data:audio/mp3;base64,${audioBase64}`;
        this.currentPlayingAudioElement = new Audio(audioSrc); 
        
        this.currentPlayingAudioElement.play()
            .then(() => { /* console.log("TTS audio chunk playing."); */ })
            .catch(error => {
                console.error("Error playing TTS audio chunk:", error);
                this.isPlayingTTS = false; // Error, so not playing
                this._currentPlayingAudioSegmentChunks = []; // Clear rest of this problematic segment
                this.playNextQueuedAudioSegment(); // Try next sentence
            });

        this.currentPlayingAudioElement.onended = () => {
            // console.log("TTS audio chunk finished playing.");
            // isPlayingTTS is managed by the start of this function and when segment is fully done.
            // Don't set isPlayingTTS to false here, as more chunks for the *same sentence* might follow.
            this.playNextChunkFromCurrentSegment(); // Play next chunk of the same sentence
        };
        this.currentPlayingAudioElement.onerror = (e) => {
            console.error("Error during TTS audio element playback:", e);
            this.error = "TTS 오디오 재생 중 오류가 발생했습니다.";
            this.isPlayingTTS = false; // Error, so not playing
            this._currentPlayingAudioSegmentChunks = []; // Clear rest of this problematic segment
            this.playNextQueuedAudioSegment(); // Try next sentence
        };
        
        // Start client-side VAD if in voice mode (will only run if also this.isPlayingTTS is true)
        if(this.isVoiceModeActive) {
            this.startClientSideVAD();
        }

      } else { // Should not happen if length check is done, but as a safeguard
        this.isPlayingTTS = false;
        this.playNextQueuedAudioSegment();
      }
    },

    startClientSideVAD() {
        this.stopClientSideVAD(); 

        if (!this.isVoiceModeActive || !this.isPlayingTTS || !this.audioStream) {
            // console.log("VAD prerequisites not met. VAD not started.");
            return;
        }
        // console.log("Attempting to start client-side VAD.");

        this.vadContext.vadActivationTimeoutId = window.setTimeout(() => {
            if (!this.isVoiceModeActive || !this.isPlayingTTS || !this.audioStream || this.audioStream.getAudioTracks().every(t => t.readyState === 'ended')) {
                this.stopClientSideVAD(); 
                // console.log("VAD activation timed out or conditions changed. VAD stopped.");
                return;
            }

            try {
                if (!this.vadContext.audioContext || this.vadContext.audioContext.state === 'closed') {
                  this.vadContext.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
                }
                if (!this.vadContext.analyserNode) { // Only create if not exists or context was recreated
                    this.vadContext.analyserNode = this.vadContext.audioContext.createAnalyser();
                    this.vadContext.analyserNode.fftSize = 512; 
                    this.vadContext.analyserNode.smoothingTimeConstant = 0.5; // Adjust for responsiveness
                    this.vadContext.dataArray = new Uint8Array(this.vadContext.analyserNode.frequencyBinCount);
                    // Ensure audioStream is still valid and has tracks
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
            
            const VAD_THRESHOLD = 10; // Adjusted threshold, test this value
            const SPEECH_FRAMES_NEEDED_FOR_BARGE_IN = 2; // Consecutive speech frames for barge-in
            let consecutiveSpeechFrames = 0;

            // console.log("VAD interval starting.");
            this.vadContext.vadIntervalId = window.setInterval(() => {
                if (!this.vadContext.analyserNode || !this.vadContext.dataArray || !this.isPlayingTTS || !this.isVoiceModeActive) {
                    // console.log("VAD stopping due to state change.");
                    this.stopClientSideVAD();
                    return;
                }
                this.vadContext.analyserNode.getByteFrequencyData(this.vadContext.dataArray);
                let sum = 0;
                for (let i = 0; i < this.vadContext.dataArray.length; i++) { sum += this.vadContext.dataArray[i]; }
                const average = this.vadContext.dataArray.length > 0 ? sum / this.vadContext.dataArray.length : 0;
                
                if (average > VAD_THRESHOLD) {
                    consecutiveSpeechFrames++;
                    // console.log(`Client VAD: Potential speech (avg: ${average.toFixed(2)}, count: ${consecutiveSpeechFrames})`);
                    if (consecutiveSpeechFrames >= SPEECH_FRAMES_NEEDED_FOR_BARGE_IN) {
                       console.log(`Client VAD: User speaking detected (avg: ${average.toFixed(2)}). Stopping TTS for barge-in.`);
                       this.stopClientSideTTSPlayback(true); 
                       // VAD interval will be cleared by stopClientSideTTSPlayback calling stopClientSideVAD
                    }
                } else {
                    consecutiveSpeechFrames = 0; // Reset counter on silence
                    // console.log(`Client VAD: silence (avg: ${average.toFixed(2)})`);
                }
            }, 100); // Check every 100ms
        }, 300); // VAD 활성화까지 300ms 지연 (TTS 시작음 무시)
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
        // Do not close audioContext here if it's meant to be reused by MediaRecorder.
        // MediaRecorder should ideally get its own stream or share the context carefully.
        // For VAD, it's safer to disconnect the analyser if the stream stops or VAD stops.
        // if (this.vadContext.analyserNode) {
        //     this.vadContext.analyserNode.disconnect(); // Disconnect to free up resources
        //     // this.vadContext.analyserNode = null; // Nullify if it needs recreation
        // }
        // console.log("Client-side VAD stopped/cleaned.");
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
  },
})