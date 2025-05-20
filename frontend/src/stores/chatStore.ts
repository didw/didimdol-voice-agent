// src/stores/chatStore.ts
import { defineStore } from 'pinia'
import { v4 as uuidv4 } from 'uuid'

interface Message {
  id: string
  sender: 'user' | 'ai'
  text: string
  timestamp: Date
  isStreaming?: boolean
  isInterimStt?: boolean // STT 중간 결과 여부
}

interface ChatState {
  sessionId: string | null
  messages: Message[]
  isProcessingLLM: boolean // LLM 응답 대기 상태
  isSynthesizingTTS: boolean // TTS 오디오 생성/스트리밍 중 상태
  error: string | null
  currentInterimStt: string // 현재 STT 중간 결과
  isWebSocketConnected: boolean
  webSocket: WebSocket | null
  currentAiAudioChunks: string[] // Base64 인코딩된 오디오 청크 배열
  isEPDDetected: boolean // EPD 감지 상태
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
    currentAiAudioChunks: [],
    isEPDDetected: false,
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
          console.log('WebSocket message received:', data)
          this.isEPDDetected = false // 메시지 받으면 EPD 상태 초기화 (Barge-in 대비)

          switch (data.type) {
            case 'session_initialized':
              this.addMessage('ai', data.message)
              break
            case 'stt_interim_result':
              this.currentInterimStt = data.transcript
              break
            case 'stt_final_result':
              this.currentInterimStt = ''
              if (data.transcript) {
                // 빈 텍스트는 메시지로 추가 안 함
                this.addMessage('user', data.transcript)
                // 서버가 STT final 후 바로 LLM 처리하므로 클라이언트에서 별도 요청 안함
                this.isProcessingLLM = true
              }
              break
            case 'llm_response_chunk':
              this.appendAiMessageChunk(data.chunk)
              this.isProcessingLLM = true
              break
            case 'llm_response_end': // LLM 텍스트 스트리밍 완료
              this.finalizeAiMessage()
              this.isProcessingLLM = false
              // TTS는 서버에서 llm_response_end 후 자동으로 시작될 것 (또는 audio_chunk로 바로 올 것)
              break
            case 'tts_audio_chunk':
              this.currentAiAudioChunks.push(data.audio_chunk_base64)
              this.isSynthesizingTTS = true
              break
            case 'tts_stream_end':
              this.isSynthesizingTTS = false
              // 여기서 모인 audio chunk 재생 트리거 (ChatInterface.vue에서 감지)
              break
            case 'epd_detected':
              console.log('EPD detected from server')
              this.isEPDDetected = true // EPD 상태 설정
              // ChatInterface.vue에서 이 상태를 보고 녹음 중지 등의 UI 처리
              break
            case 'error':
              this.error = data.message
              this.isProcessingLLM = false
              this.isSynthesizingTTS = false
              this.currentInterimStt = ''
              break
            case 'warning':
              // 경고 메시지는 에러와 별도로 처리하거나, 메시지 목록에 추가 가능
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
        this.isSynthesizingTTS = false
      }

      this.webSocket.onclose = (closeEvent) => {
        console.log('WebSocket connection closed:', closeEvent.code, closeEvent.reason)
        this.isWebSocketConnected = false
        if (!closeEvent.wasClean) {
          this.error = 'WebSocket 연결이 비정상적으로 종료되었습니다.'
        }
      }
    },

    sendWebSocketTextMessage(text: string) {
      if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        this.addMessage('user', text)
        this.webSocket.send(JSON.stringify({ type: 'process_text', text: text }))
        this.isProcessingLLM = true
        this.error = null
      } else {
        this.handleWebSocketNotConnected('텍스트 메시지')
      }
    },

    sendAudioBlob(audioBlob: Blob) {
      if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        this.webSocket.send(audioBlob) // Blob 직접 전송
        this.error = null
        this.currentInterimStt = '음성 인식 중...' // 사용자에게 피드백
      } else {
        this.handleWebSocketNotConnected('오디오 데이터')
      }
    },

    requestStopTTS() {
      if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        this.webSocket.send(JSON.stringify({ type: 'stop_tts' }))
        console.log('Requested server to stop TTS stream.')
      } else {
        this.handleWebSocketNotConnected('TTS 중지 요청')
      }
      // 클라이언트 측에서도 즉시 오디오 재생 중단 로직 필요
      this.currentAiAudioChunks = [] // 현재 쌓인 청크 비우기
      this.isSynthesizingTTS = false // TTS 합성/스트리밍 상태 중단
    },

    handleWebSocketNotConnected(actionDescription: string) {
      console.error(`Cannot send ${actionDescription}: WebSocket is not connected.`)
      this.error = `서버와 연결되지 않아 ${actionDescription}을 전송할 수 없습니다. 페이지를 새로고침하거나 잠시 후 다시 시도해주세요.`
      // 필요시 자동 재연결 시도 로직 추가
      // this.initializeSessionAndConnect();
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

    clearAudioChunks() {
      this.currentAiAudioChunks = []
    },

    disconnectWebSocket() {
      if (this.webSocket) {
        this.webSocket.close(1000, 'Client initiated disconnect')
        this.webSocket = null
        this.isWebSocketConnected = false
        console.log('WebSocket disconnected by client.')
      }
    },
  },
  getters: {
    getMessages: (state): Message[] => state.messages,
    getIsProcessingLLM: (state): boolean => state.isProcessingLLM,
    getIsSynthesizingTTS: (state): boolean => state.isSynthesizingTTS,
    getError: (state): string | null => state.error,
    getSessionId: (state): string | null => state.sessionId,
    getInterimStt: (state): string => state.currentInterimStt,
    getIsWebSocketConnected: (state): boolean => state.isWebSocketConnected,
    getAudioChunks: (state): string[] => state.currentAiAudioChunks,
    getIsEPDDetected: (state): boolean => state.isEPDDetected,
  },
})
