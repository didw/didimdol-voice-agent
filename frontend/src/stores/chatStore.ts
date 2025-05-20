// src/stores/chatStore.ts
import { defineStore } from 'pinia'
import { v4 as uuidv4 } from 'uuid'
// import api from '../services/api'; // HTTP API 대신 WebSocket 사용

interface Message {
  id: string
  sender: 'user' | 'ai'
  text: string
  timestamp: Date
  isStreaming?: boolean // LLM 응답 스트리밍 중 여부
  isStt?: boolean // STT 중간 결과 여부
}

interface ChatState {
  sessionId: string | null
  messages: Message[]
  isProcessing: boolean // 전체적인 처리 상태 (예: LLM 응답 기다리는 중)
  error: string | null
  // currentAiAudioBase64: string | null; // 스트리밍 방식으로 변경되므로 제거 또는 수정
  currentInterimStt: string // STT 중간 결과
  isWebSocketConnected: boolean
  webSocket: WebSocket | null
}

// WebSocket 서버 주소 (환경 변수 등으로 관리하는 것이 좋음)
const WEBSOCKET_URL = `ws://localhost:8000/api/v1/chat/ws/` // 백엔드 WebSocket 엔드포인트

export const useChatStore = defineStore('chat', {
  state: (): ChatState => ({
    sessionId: null,
    messages: [],
    isProcessing: false,
    error: null,
    currentInterimStt: '',
    isWebSocketConnected: false,
    webSocket: null,
  }),
  actions: {
    // --- WebSocket 관련 액션 ---
    connectWebSocket() {
      if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        console.log('WebSocket is already connected.')
        return
      }
      if (!this.sessionId) {
        this.initializeSession() // 세션 ID가 먼저 필요
      }

      this.webSocket = new WebSocket(
        `<span class="math-inline">\{WEBSOCKET\_URL\}</span>{this.sessionId}`,
      )

      this.webSocket.onopen = () => {
        console.log('WebSocket connection established for session:', this.sessionId)
        this.isWebSocketConnected = true
        this.error = null
        // 연결 성공 후 초기 메시지 요청 또는 환영 메시지 로직 (필요시)
      }

      this.webSocket.onmessage = (event) => {
        const data = JSON.parse(event.data as string)
        console.log('WebSocket message received:', data)

        switch (data.type) {
          case 'stt_interim_result':
            this.currentInterimStt = data.transcript
            break
          case 'stt_final_result':
            this.currentInterimStt = '' // 중간 결과 초기화
            this.addMessage('user', data.transcript)
            // 최종 STT 결과를 LLM으로 보내도록 서버에 메시지 전송
            // 서버가 STT 최종 후 자동으로 LLM 처리하도록 설계했다면 이 부분은 필요 없을 수 있음
            this.sendWebSocketMessage({ type: 'process_text', text: data.transcript })
            this.isProcessing = true // LLM 처리 시작
            break
          case 'llm_response_chunk':
            this.appendAiMessageChunk(data.chunk)
            this.isProcessing = true // 계속 처리 중
            break
          case 'llm_response_end':
            this.finalizeAiMessage()
            this.isProcessing = false // LLM 텍스트 스트리밍 완료
            // 여기서 TTS 요청을 보내거나, 서버가 자동으로 TTS 시작하도록 설계 가능
            break
          case 'tts_audio_chunk': // 이 부분은 MediaSource API와 연동 필요
            // audioPlayerStore.playAudioChunk(data.audio_chunk_base64);
            console.log('Received audio chunk (not implemented yet for playback)')
            break
          case 'tts_stream_url': // 간단한 방법: 서버가 스트리밍 URL을 주면 audio 태그 src에 설정
            this.setAiAudioStreamUrl(data.url) // 아래 getter/action 추가 필요
            break
          case 'epd_detected':
            // ChatInterface.vue에서 이 이벤트를 구독하여 녹음 중지
            // 또는 여기서 직접 isRecording 상태 변경 (컴포넌트와 연동 필요)
            console.log('EPD detected from server')
            // this.stopRecording(); // 컴포넌트의 함수를 직접 호출하긴 어려우므로 이벤트 버스나 콜백 사용
            break
          case 'error':
            this.error = data.message
            this.isProcessing = false
            this.currentInterimStt = ''
            break
          case 'ai_message': // 기존 방식처럼 한번에 AI 메시지를 받는 경우 (스트리밍 아닐 때)
            this.addMessage('ai', data.text)
            if (data.tts_audio_base64) {
              // 기존 방식의 base64 오디오 처리 (하이브리드 지원 시)
              // this.currentAiAudioBase64 = data.tts_audio_base64;
            }
            this.isProcessing = false
            break
          case 'session_initialized': // 서버에서 세션 초기화 응답
            this.messages.push({
              id: uuidv4(),
              sender: 'ai',
              text: data.message,
              timestamp: new Date(),
            })
            break
          default:
            console.warn('Unknown WebSocket message type:', data.type)
        }
      }

      this.webSocket.onerror = (error) => {
        console.error('WebSocket error:', error)
        this.error = 'WebSocket 연결에 실패했습니다. 서버 상태를 확인해주세요.'
        this.isWebSocketConnected = false
        this.isProcessing = false
      }

      this.webSocket.onclose = (event) => {
        console.log('WebSocket connection closed:', event.reason)
        this.isWebSocketConnected = false
        // 필요시 자동 재연결 로직
        if (!event.wasClean) {
          this.error = 'WebSocket 연결이 예기치 않게 종료되었습니다.'
        }
      }
    },

    sendWebSocketMessage(payload: object) {
      if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        this.webSocket.send(JSON.stringify(payload))
      } else {
        console.error('WebSocket is not connected.')
        this.error = 'WebSocket이 연결되지 않았습니다.'
      }
    },

    disconnectWebSocket() {
      if (this.webSocket) {
        this.webSocket.close()
        this.webSocket = null
        this.isWebSocketConnected = false
      }
    },

    sendAudioChunk(audioBlob: Blob) {
      if (this.webSocket && this.webSocket.readyState === WebSocket.OPEN) {
        // Blob을 직접 보내거나 Base64로 인코딩하여 JSON 객체로 감싸서 보낼 수 있음
        // 서버에서 Blob을 바로 처리할 수 있다면 직접 보내는 것이 효율적
        this.webSocket.send(audioBlob)
        // 또는 Base64 인코딩:
        // const reader = new FileReader();
        // reader.readAsDataURL(audioBlob);
        // reader.onloadend = () => {
        //   const base64Audio = reader.result?.toString().split(',')[1];
        //   if (base64Audio) {
        //     this.sendWebSocketMessage({ type: 'audio_chunk', data: base64Audio });
        //   }
        // };
      }
    },

    // --- 기존 액션 수정 ---
    initializeSession() {
      if (!this.sessionId) {
        this.sessionId = uuidv4()
        console.log('새 세션 시작:', this.sessionId)
        // WebSocket 연결 시 서버에서 초기 메시지를 받도록 변경
        this.connectWebSocket()
      } else if (!this.isWebSocketConnected) {
        // 세션 ID는 있지만 연결이 끊긴 경우
        this.connectWebSocket()
      }
    },

    addMessage(
      sender: 'user' | 'ai',
      text: string,
      isStreaming: boolean = false,
      isStt: boolean = false,
    ) {
      const newMessage: Message = {
        id: uuidv4(),
        sender,
        text,
        timestamp: new Date(),
        isStreaming,
        isStt,
      }
      // STT 중간 결과는 messages 배열에 추가하지 않고 별도 상태(currentInterimStt)로 관리
      if (!isStt) {
        this.messages.push(newMessage)
      }
    },

    appendAiMessageChunk(chunk: string) {
      this.isProcessing = true
      const lastMessage = this.messages[this.messages.length - 1]
      if (lastMessage && lastMessage.sender === 'ai' && lastMessage.isStreaming) {
        lastMessage.text += chunk
      } else {
        // 새 스트리밍 메시지 시작
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
      this.isProcessing = false // LLM 텍스트 스트리밍 최종 완료
    },

    // processAndSendMessage는 WebSocket 위주로 변경
    async sendTextMessage(text: string) {
      if (!text.trim()) return
      this.addMessage('user', text)
      this.sendWebSocketMessage({ type: 'process_text', text: text })
      this.isProcessing = true
    },

    // clearCurrentAiAudio는 스트리밍 방식에 따라 수정/제거
    // ...

    // TTS 스트리밍 URL을 위한 상태 및 액션
    currentAiAudioStreamUrl: '', // 상태에 추가
    setAiAudioStreamUrl(url: string) {
      // 액션에 추가
      this.currentAiAudioStreamUrl = url
    },
    clearAiAudioStreamUrl() {
      // 액션에 추가
      this.currentAiAudioStreamUrl = ''
    },
  },
  getters: {
    getMessages: (state): Message[] => state.messages,
    getIsProcessing: (state): boolean => state.isProcessing,
    getError: (state): string | null => state.error,
    getSessionId: (state): string | null => state.sessionId,
    // getCurrentAiAudio는 스트리밍 방식에 따라 수정/제거
    getInterimStt: (state): string => state.currentInterimStt,
    getIsWebSocketConnected: (state): boolean => state.isWebSocketConnected,
    getAiAudioStreamUrl: (state): string => state.currentAiAudioStreamUrl, // getter 추가
  },
})
