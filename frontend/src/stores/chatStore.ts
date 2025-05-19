// src/stores/chatStore.ts
import { defineStore } from 'pinia'
import { v4 as uuidv4 } from 'uuid' // 세션 ID 생성을 위해 uuid 설치 필요 (npm install uuid @types/uuid)
import api from '../services/api'   // api.js 경로 확인

interface Message {
  id: string;
  sender: 'user' | 'ai';
  text: string;
  timestamp: Date;
}

interface ChatState {
  sessionId: string | null;
  messages: Message[];
  isProcessing: boolean;
  error: string | null;
  currentAiAudioBase64: string | null; // 현재 재생해야 할 AI 음성 (base64)
}

export const useChatStore = defineStore('chat', {
  state: (): ChatState => ({
    sessionId: null,
    messages: [],
    isProcessing: false,
    error: null,
    currentAiAudioBase64: null,
  }),
  actions: {
    initializeSession() {
      if (!this.sessionId) {
        this.sessionId = uuidv4();
        console.log('새 세션 시작:', this.sessionId);
        // 초기 시스템 메시지 추가 등
        this.messages.push({
          id: uuidv4(),
          sender: 'ai',
          text: '안녕하세요! 디딤돌 대출 상담을 시작하시려면 음성 또는 텍스트로 말씀해주세요.',
          timestamp: new Date()
        });
      }
    },
    addMessage(sender: 'user' | 'ai', text: string) {
      const newMessage: Message = {
        id: uuidv4(),
        sender,
        text,
        timestamp: new Date(),
      };
      this.messages.push(newMessage);
    },
    async processAndSendMessage(payload: { text?: string; audioBase64?: string }) {
      if (!this.sessionId) {
        this.initializeSession(); // 세션이 없다면 초기화
      }
      this.isProcessing = true;
      this.error = null;
      this.currentAiAudioBase64 = null; // 이전 오디오 초기화

      if (payload.text) {
        this.addMessage('user', payload.text);
      } else if (payload.audioBase64) {
        this.addMessage('user', '[음성 메시지 전송됨]'); // 또는 STT 결과를 먼저 보여줄 수도 있음
      }

      try {
        const response = await api.processMessage({
          session_id: this.sessionId,
          text: payload.text,
          audio_bytes_str: payload.audioBase64,
        });

        // AIMessage 스키마 (backend/app/schemas/chat_schemas.py) 참고
        const aiResponseData = response.data;
        this.addMessage('ai', aiResponseData.text);

        if (aiResponseData.tts_audio_base64) {
          this.currentAiAudioBase64 = aiResponseData.tts_audio_base64;
        } else if (aiResponseData.debug_info?.tts_audio_base64) { // 이전 응답 형식 호환
            this.currentAiAudioBase64 = aiResponseData.debug_info.tts_audio_base64;
        }

      } catch (err: any) {
        console.error('메시지 처리 오류:', err);
        const errorMessage = err.response?.data?.detail || err.message || '메시지 처리 중 오류가 발생했습니다.';
        this.error = errorMessage;
        this.addMessage('ai', `오류: ${errorMessage}`);
      } finally {
        this.isProcessing = false;
      }
    },
    clearCurrentAiAudio() {
      this.currentAiAudioBase64 = null;
    }
  },
  getters: {
    getMessages: (state): Message[] => state.messages,
    getIsProcessing: (state): boolean => state.isProcessing,
    getError: (state): string | null => state.error,
    getSessionId: (state): string | null => state.sessionId,
    getCurrentAiAudio: (state): string | null => state.currentAiAudioBase64,
  }
})