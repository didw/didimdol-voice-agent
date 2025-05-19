<template>
  <div class="chat-container">
    <div class="messages-area" ref="messagesAreaRef">
      <div v-for="msg in messages" :key="msg.id" :class="['message', msg.sender]">
        <p>{{ msg.text }}</p>
        <small>{{ new Date(msg.timestamp).toLocaleTimeString() }}</small>
      </div>
    </div>

    <div class="input-area">
      <button @click="handleToggleRecording" :disabled="isProcessing">
        {{ isRecording ? '녹음 중지' : isProcessing ? '처리 중...' : '음성 입력' }}
      </button>
      <input
        ref="textInputRef"
        type="text"
        v-model="currentTextMessage"
        @keyup.enter="handleSendTextMessage"
        placeholder="텍스트로 입력하세요..."
        :disabled="isRecording || isProcessing"
      />
      <button
        @click="handleSendTextMessage"
        :disabled="isRecording || isProcessing || !currentTextMessage.trim()"
      >
        전송
      </button>
    </div>

    <div v-if="chatStore.getCurrentAiAudio" class="audio-player">
      <audio
        ref="audioPlayerRef"
        @ended="handleAiAudioEnded"
        controls
        style="display: none"
      ></audio>
      <p>AI 음성 재생 중...</p>
      <button @click="handleStopAiAudio">AI 음성 중지</button>
    </div>
    <div v-if="errorText" class="error-message">
      <p style="color: red">{{ errorText }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
// lang="ts" 추가
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useChatStore } from '../stores/chatStore' // chatStore 임포트 경로 확인

const chatStore = useChatStore()

// Pinia 스토어 상태 및 getter 사용
const messages = computed(() => chatStore.getMessages)
const isProcessing = computed(() => chatStore.getIsProcessing)
const errorText = computed(() => chatStore.getError)
const currentAiAudioFromStore = computed(() => chatStore.getCurrentAiAudio)

const currentTextMessage = ref('')
const isRecording = ref(false)
const textInputRef = ref<HTMLInputElement | null>(null) // 텍스트 입력 참조 추가

const mediaRecorderRef = ref<MediaRecorder | null>(null)
const audioChunks = ref<Blob[]>([])
const audioPlayerRef = ref<HTMLAudioElement | null>(null)
const messagesAreaRef = ref<HTMLDivElement | null>(null)

let stream: MediaStream | null = null
let currentAudioObjectURL: string | null = null // Object URL 관리를 위해 추가

// --- AI 음성 재생 ---
const playAiAudio = (base64Data: string) => {
  if (base64Data && audioPlayerRef.value) {
    // 이전 오디오 Object URL 해제
    if (currentAudioObjectURL) {
      URL.revokeObjectURL(currentAudioObjectURL)
      currentAudioObjectURL = null
    }

    try {
      const byteCharacters = atob(base64Data)
      const byteNumbers = new Array(byteCharacters.length)
      for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i)
      }
      const byteArray = new Uint8Array(byteNumbers)
      const audioBlob = new Blob([byteArray], { type: 'audio/mpeg' }) // 백엔드에서 MP3로 인코딩 가정
      currentAudioObjectURL = URL.createObjectURL(audioBlob)

      audioPlayerRef.value.src = currentAudioObjectURL
      audioPlayerRef.value.play().catch((e) => {
        console.error('오디오 재생 실패:', e)
        chatStore.error = 'AI 음성 재생에 실패했습니다. 브라우저 설정을 확인해주세요.' // 스토어 에러 업데이트
        if (currentAudioObjectURL) {
          // 실패 시 즉시 해제
          URL.revokeObjectURL(currentAudioObjectURL)
          currentAudioObjectURL = null
        }
      })
    } catch (e) {
      console.error('Base64 디코딩 또는 Blob 생성 실패:', e)
      chatStore.error = '오디오 데이터 처리 중 오류가 발생했습니다.'
    }
  }
}

// 스토어의 currentAiAudioBase64 변경 감지하여 재생
watch(currentAiAudioFromStore, (newAudioBase64) => {
  if (newAudioBase64) {
    playAiAudio(newAudioBase64)
  } else {
    // newAudioBase64가 null이면 (예: clearCurrentAiAudio 호출 시) 재생 중지 및 리소스 정리
    if (audioPlayerRef.value && !audioPlayerRef.value.paused) {
      audioPlayerRef.value.pause()
    }
    if (audioPlayerRef.value) {
      audioPlayerRef.value.src = ''
    }
    if (currentAudioObjectURL) {
      URL.revokeObjectURL(currentAudioObjectURL)
      currentAudioObjectURL = null
    }
    // AI 응답이 끝나면 텍스트 입력 칸으로 포커스
    nextTick(() => {
      textInputRef.value?.focus()
    })
  }
})

// --- 음성 녹음 관련 ---
const startRecording = async () => {
  if (isProcessing.value) return // 스크립트 내에서는 .value로 접근
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    isRecording.value = true
    // chatStore.error = null; // 새 녹음 시작 시 이전 에러 클리어 (옵션)
    audioChunks.value = []

    // Barge-in: AI 음성 재생 중이면 중지
    if (audioPlayerRef.value && !audioPlayerRef.value.paused) {
      console.log('Barge-in: AI 음성 재생 중지')
      audioPlayerRef.value.pause()
      audioPlayerRef.value.currentTime = 0
      // src 및 ObjectURL은 watch 로직 또는 onAiAudioEnded/stopAiAudio에서 정리됨
      chatStore.clearCurrentAiAudio()
    }

    const options = { mimeType: 'audio/webm; codecs=opus' }
    try {
      mediaRecorderRef.value = new MediaRecorder(stream, options)
    } catch (e) {
      console.warn(
        "지정된 mimeType ('audio/webm; codecs=opus')이(가) 지원되지 않아 기본값으로 시도합니다.",
        e,
      )
      mediaRecorderRef.value = new MediaRecorder(stream)
    }

    mediaRecorderRef.value.ondataavailable = (event) => {
      audioChunks.value.push(event.data)
    }

    mediaRecorderRef.value.onstop = async () => {
      // isRecording.value = false; // stopRecording에서 처리
      const audioBlob = new Blob(audioChunks.value, {
        type: mediaRecorderRef.value?.mimeType || 'audio/webm',
      })
      audioChunks.value = [] // 청크 초기화

      const reader = new FileReader()
      reader.readAsDataURL(audioBlob)
      reader.onloadend = async () => {
        const base64Audio = reader.result?.toString().split(',')[1]
        if (base64Audio) {
          await chatStore.processAndSendMessage({ audioBase64: base64Audio })
        } else {
          chatStore.error = '음성 데이터를 변환하는 데 실패했습니다.'
        }
      }
    }
    mediaRecorderRef.value.start() // 녹음 시작
  } catch (err) {
    console.error('마이크 접근 또는 녹음 시작 오류:', err)
    chatStore.error = '마이크를 사용할 수 없거나 녹음 시작에 실패했습니다. 권한을 확인해주세요.'
    isRecording.value = false // 오류 발생 시 녹음 상태 해제
  }
}

const stopRecording = () => {
  if (mediaRecorderRef.value && isRecording.value) {
    mediaRecorderRef.value.stop() // onstop 이벤트 핸들러 트리거
    isRecording.value = false
    if (stream) {
      stream.getTracks().forEach((track) => track.stop())
      stream = null
    }
  }
}

// toggleRecording 함수 하나만 사용
const handleToggleRecording = async () => {
  if (isProcessing.value) return
  if (isRecording.value) {
    stopRecording()
  } else {
    await startRecording()
  }
}

// --- 텍스트 메시지 전송 ---
const handleSendTextMessage = async () => {
  if (!currentTextMessage.value.trim() || isProcessing.value) return
  const textToSend = currentTextMessage.value
  currentTextMessage.value = ''
  await chatStore.processAndSendMessage({ text: textToSend })
  // 메시지 전송 후 포커스 유지
  nextTick(() => {
    textInputRef.value?.focus()
  })
}

// --- 오디오 플레이어 이벤트 핸들러 ---
const handleAiAudioEnded = () => {
  console.log('AI 음성 재생 완료.')
  // watch 로직에서 currentAiAudioFromStore가 null이 될 때 정리하므로 중복될 수 있으나, 명시적 정리
  if (audioPlayerRef.value) {
    audioPlayerRef.value.src = ''
  }
  if (currentAudioObjectURL) {
    URL.revokeObjectURL(currentAudioObjectURL)
    currentAudioObjectURL = null
  }
  chatStore.clearCurrentAiAudio()
}

const handleStopAiAudio = () => {
  console.log('사용자가 AI 음성 중지.')
  if (audioPlayerRef.value && !audioPlayerRef.value.paused) {
    audioPlayerRef.value.pause()
    audioPlayerRef.value.currentTime = 0
  }
  // src 및 ObjectURL 정리는 onAiAudioEnded 또는 watch 로직에 위임하거나 여기서도 수행
  if (audioPlayerRef.value) {
    audioPlayerRef.value.src = ''
  }
  if (currentAudioObjectURL) {
    URL.revokeObjectURL(currentAudioObjectURL)
    currentAudioObjectURL = null
  }
  chatStore.clearCurrentAiAudio()
}

// --- 메시지 영역 스크롤 ---
watch(
  messages,
  async () => {
    await nextTick() // DOM 업데이트 기다림
    if (messagesAreaRef.value) {
      messagesAreaRef.value.scrollTop = messagesAreaRef.value.scrollHeight
    }
    // 메시지가 추가될 때마다 포커스 유지
    textInputRef.value?.focus()
  },
  { deep: true },
)

// --- 라이프사이클 훅 ---
onMounted(() => {
  chatStore.initializeSession()
  // 컴포넌트 마운트 시 포커스
  nextTick(() => {
    textInputRef.value?.focus()
  })
})

onUnmounted(() => {
  if (stream) {
    stream.getTracks().forEach((track) => track.stop())
  }
  // 컴포넌트 제거 시 현재 재생 중인 오디오의 Object URL 해제
  if (currentAudioObjectURL) {
    URL.revokeObjectURL(currentAudioObjectURL)
  }
  // audioPlayerRef.value?.pause(); // 필요시
  // audioPlayerRef.value?.src = ""; // 필요시
})
</script>

<style scoped>
.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  max-width: 800px;
  margin: 0 auto;
  border: 1px solid #ccc;
  border-radius: 8px;
  overflow: hidden;
  background-color: #fff;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 15px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  background-color: #f9f9f9;
}

.message {
  padding: 10px 15px;
  border-radius: 18px;
  max-width: 75%;
  word-wrap: break-word;
}

.message p {
  margin: 0;
  font-size: 0.95em;
  line-height: 1.4;
}

.message small {
  font-size: 0.7em;
  color: #888;
  display: block;
  margin-top: 5px;
  text-align: right;
}

.message.user {
  background-color: #007bff;
  color: white;
  align-self: flex-end;
  border-bottom-right-radius: 4px;
}
.message.user small {
  color: #e0e0e0;
}

.message.ai {
  background-color: #e9e9eb;
  color: #333;
  align-self: flex-start;
  border-bottom-left-radius: 4px;
}

.input-area {
  display: flex;
  padding: 10px;
  border-top: 1px solid #ccc;
  background-color: #fff;
}

.input-area input[type='text'] {
  flex-grow: 1;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 20px;
  margin: 0 10px;
  font-size: 0.95em;
}

.input-area button {
  padding: 10px 15px;
  border: none;
  border-radius: 20px;
  background-color: #007bff;
  color: white;
  cursor: pointer;
  font-size: 0.9em;
  transition: background-color 0.2s;
}

.input-area button:disabled {
  background-color: #aaa;
  cursor: not-allowed;
}

.input-area button:hover:not(:disabled) {
  background-color: #0056b3;
}

.audio-player {
  padding: 10px;
  text-align: center;
  background-color: #f0f0f0;
  border-top: 1px solid #ccc;
}
.audio-player p {
  margin: 0 0 5px 0;
  font-size: 0.85em;
}
.audio-player button {
  padding: 5px 10px;
  font-size: 0.8em;
  background-color: #dc3545;
}

.error-message {
  padding: 10px;
  text-align: center;
  background-color: #f8d7da;
  color: #721c24;
  border-top: 1px solid #f5c6cb;
}
</style>
