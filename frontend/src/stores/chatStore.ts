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
  isSynthesizingTTS: boolean // Server is preparing/streaming TTS audio data
  error: string | null
  currentInterimStt: string
  isWebSocketConnected: boolean
  webSocket: WebSocket | null

  // Voice input state
  isVoiceModeActive: boolean // Is the microphone button toggled on?
  isRecording: boolean // Is MediaRecorder currently active?
  mediaRecorder: MediaRecorder | null
  audioStream: MediaStream | null

  // TTS Playback state
  ttsAudioQueue: string[] // Queue of base64 audio chunks to play
  isPlayingTTS: boolean // Is client currently playing TTS audio?
  currentPlayingAudioElement: HTMLAudioElement | null // Currently playing audio element

  isEPDDetectedByServer: boolean // EPD detected by Google STT on server
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
        this.initializeSessionAndConnect()
        // Wait for connection before proceeding
        await new Promise((resolve) => {
          const checkConnected = () => {
            if (this.isWebSocketConnected) resolve(true)
            else setTimeout(checkConnected, 100)
          }
          checkConnected()
        })
      }

      if (this.isVoiceModeActive) {
        await this.deactivateVoiceRecognition()
      } else {
        await this.activateVoiceRecognition()
      }
    },

    async activateVoiceRecognition() {
      if (
        !this.isWebSocketConnected ||
        !this.webSocket ||
        this.webSocket.readyState !== WebSocket.OPEN
      ) {
        this.error = '음성 인식을 시작하려면 서버에 연결되어 있어야 합니다.'
        console.error('Cannot activate voice: WebSocket not connected.')
        return
      }
      this.isVoiceModeActive = true
      this.webSocket.send(JSON.stringify({ type: 'activate_voice' }))
      await this.startRecording() // Start client-side recording
      console.log('Voice mode activated, recording started.')
      this.currentInterimStt = '듣고 있어요...'
    },

    async deactivateVoiceRecognition() {
      this.isVoiceModeActive = false
      await this.stopRecording() // Stop client-side recording first
      if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        this.webSocket.send(JSON.stringify({ type: 'deactivate_voice' }))
      }
      console.log('Voice mode deactivated, recording stopped.')
      this.currentInterimStt = ''
      this.isEPDDetectedByServer = false
    },

    async startRecording() {
      if (this.isRecording || !this.isVoiceModeActive) return
      try {
        this.audioStream = await navigator.mediaDevices.getUserMedia({ audio: true })

        // Barge-in: If TTS is playing, stop it now that user is actively starting to record/speak
        if (this.isPlayingTTS) {
          console.log('User started speaking/recording during TTS. Stopping TTS for barge-in.')
          this.stopClientSideTTSPlayback(true) // Stop client playback AND tell server
        }

        const options = {
          mimeType: 'audio/webm; codecs=opus',
          audioBitsPerSecond: 128000, // Optional: for higher quality
        }
        this.mediaRecorder = new MediaRecorder(this.audioStream, options)

        this.mediaRecorder.ondataavailable = (event) => {
          if (event.data.size > 0 && this.isWebSocketConnected && this.isVoiceModeActive) {
            this.sendAudioBlob(event.data)
          }
        }

        this.mediaRecorder.onstart = () => {
          this.isRecording = true
          console.log('MediaRecorder started.')
        }

        this.mediaRecorder.onstop = () => {
          this.isRecording = false
          console.log('MediaRecorder stopped.')
          if (this.audioStream) {
            this.audioStream.getTracks().forEach((track) => track.stop())
            this.audioStream = null
          }
          this.currentInterimStt = '' // Clear interim when recording fully stops
        }

        this.mediaRecorder.onerror = (event) => {
          console.error('MediaRecorder error:', event)
          this.error = `마이크 녹음 중 오류: ${(event as any)?.error?.name || '알 수 없는 오류'}`
          this.deactivateVoiceRecognition()
        }

        this.mediaRecorder.start(500) // Send data every 500ms
      } catch (err) {
        console.error('Error starting recording:', err)
        this.error = '마이크 접근에 실패했습니다. 권한을 확인해주세요.'
        this.isVoiceModeActive = false // Failed to activate
      }
    },

    async stopRecording() {
      if (this.mediaRecorder && this.isRecording) {
        this.mediaRecorder.stop()
      }
      // Stream and context cleanup is handled in onstop
    },

    sendWebSocketTextMessage(text: string) {
      if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        // Ensure voice mode is off if sending text manually
        if (this.isVoiceModeActive) {
          this.deactivateVoiceRecognition() // Turn off mic if user types
        }
        this.addMessage('user', text)
        this.webSocket.send(
          JSON.stringify({ type: 'process_text', text: text, input_mode: 'text' }),
        )
        this.isProcessingLLM = true
        this.error = null
      } else {
        this.handleWebSocketNotConnected('텍스트 메시지')
      }
    },

    sendAudioBlob(audioBlob: Blob) {
      if (
        this.webSocket &&
        this.webSocket.readyState === WebSocket.OPEN &&
        this.isVoiceModeActive
      ) {
        this.webSocket.send(audioBlob)
        this.error = null
        // currentInterimStt is updated by server responses
      } else if (!this.isVoiceModeActive) {
        console.log('Audio blob not sent: Voice mode is not active.')
      } else {
        this.handleWebSocketNotConnected('오디오 데이터')
      }
    },

    // Client-side immediate TTS stop + optional server notification
    stopClientSideTTSPlayback(notifyServer: boolean) {
      console.log(`Stopping client-side TTS playback. Notify server: ${notifyServer}`)
      if (this.currentPlayingAudioElement) {
        this.currentPlayingAudioElement.pause()
        this.currentPlayingAudioElement.src = '' // Release audio resources
        this.currentPlayingAudioElement = null
      }
      this.ttsAudioQueue = [] // Clear any pending queue
      this.isPlayingTTS = false
      this.isSynthesizingTTS = false // Reflect that we are no longer expecting/processing TTS

      if (notifyServer && this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        this.webSocket.send(JSON.stringify({ type: 'stop_tts' }))
        console.log('Requested server to stop TTS stream due to client action.')
      }
    },

    playNextTtsAudioFromQueue() {
      if (this.isPlayingTTS || this.ttsAudioQueue.length === 0) {
        return
      }

      this.isPlayingTTS = true
      const audioBase64 = this.ttsAudioQueue.shift()

      if (audioBase64) {
        const audioSrc = `data:audio/mp3;base64,${audioBase64}`
        if (!this.currentPlayingAudioElement) {
          this.currentPlayingAudioElement = new Audio()
        }
        this.currentPlayingAudioElement.src = audioSrc
        this.currentPlayingAudioElement
          .play()
          .then(() => {
            console.log('TTS audio chunk playing.')
          })
          .catch((error) => {
            console.error('Error playing TTS audio chunk:', error)
            this.isPlayingTTS = false
            // Try next chunk if error
            this.playNextTtsAudioFromQueue()
          })

        this.currentPlayingAudioElement.onended = () => {
          console.log('TTS audio chunk finished.')
          this.isPlayingTTS = false
          this.playNextTtsAudioFromQueue() // Play next in queue
        }
        this.currentPlayingAudioElement.onerror = (e) => {
          console.error('Error during TTS audio element playback:', e)
          this.isPlayingTTS = false
          this.error = 'TTS 오디오 재생 중 오류가 발생했습니다.'
          this.playNextTtsAudioFromQueue() // Attempt next if error
        }
      } else {
        this.isPlayingTTS = false // Should not happen if queue length was > 0
      }
    },

    handleWebSocketNotConnected(actionDescription: string) {
      console.error(`Cannot send ${actionDescription}: WebSocket is not connected.`)
      this.error = `서버와 연결되지 않아 ${actionDescription}을 전송할 수 없습니다. 페이지를 새로고침하거나 잠시 후 다시 시도해주세요.`
    },

    addMessage(sender: 'user' | 'ai', text: string) {
      const newMessage: Message = {
        id: uuidv4(),
        sender,
        text,
        timestamp: new Date(),
        isStreaming: false,
        isInterimStt: false,
      }
      this.messages.push(newMessage)
    },

    appendAiMessageChunk(chunk: string) {
      const lastMessage = this.messages[this.messages.length - 1]
      if (lastMessage && lastMessage.sender === 'ai' && lastMessage.isStreaming) {
        lastMessage.text += chunk
      } else {
        // If barge-in stopped previous AI message, start a new one
        this.finalizeAiMessage()
        this.messages.push({
          id: uuidv4(),
          sender: 'ai',
          text: chunk,
          timestamp: new Date(),
          isStreaming: true,
        })
      }
    },

    finalizeAiMessage() {
      const lastMessage = this.messages[this.messages.length - 1]
      if (lastMessage && lastMessage.sender === 'ai' && lastMessage.isStreaming) {
        lastMessage.isStreaming = false
      }
    },

    clearTtsAudioQueue() {
      // Renamed from clearAudioChunks
      this.ttsAudioQueue = []
    },

    disconnectWebSocket() {
      if (this.isVoiceModeActive) {
        this.deactivateVoiceRecognition()
      }
      if (this.webSocket) {
        this.webSocket.close(1000, 'Client initiated disconnect')
        this.webSocket = null // Important to nullify after close
      }
      this.isWebSocketConnected = false
      console.log('WebSocket disconnected by client action.')
    },
  },
  getters: {
    // ... (existing getters)
    getMessages: (state): Message[] => state.messages,
    getIsProcessingLLM: (state): boolean => state.isProcessingLLM,
    getIsSynthesizingTTS: (state): boolean => state.isSynthesizingTTS, // Server sending TTS data
    getIsPlayingTTS: (state): boolean => state.isPlayingTTS, // Client playing TTS audio
    getError: (state): string | null => state.error,
    getSessionId: (state): string | null => state.sessionId,
    getInterimStt: (state): string => state.currentInterimStt,
    getIsWebSocketConnected: (state): boolean => state.isWebSocketConnected,
    // getAudioChunks: (state): string[] => state.ttsAudioQueue, // Use a more descriptive name
    getIsVoiceModeActive: (state): boolean => state.isVoiceModeActive,
    getIsRecording: (state): boolean => state.isRecording,
    getIsEPDDetectedByServer: (state): boolean => state.isEPDDetectedByServer,
  },
})
