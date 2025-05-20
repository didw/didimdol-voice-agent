// frontend/src/components/ChatInterface.vue
<template>
  <div class="chat-container">
    <div class="messages-area" ref="messagesAreaRef">
      <div v-if="interimSttText" class="message stt-interim">
        <p>
          <em>{{ interimSttText }}</em>
        </p>
      </div>
      <div
        v-for="msg in messages"
        :key="msg.id"
        :class="['message', msg.sender, { streaming: msg.isStreaming }]"
      >
        <p>{{ msg.text }}<span v-if="msg.isStreaming" class="typing-cursor"></span></p>
        <small>{{ new Date(msg.timestamp).toLocaleTimeString() }}</small>
      </div>
    </div>

    <div class="input-area">
      <button @click="handleToggleRecording" :disabled="isProcessing && !isRecording">
        {{ isRecording ? '말씀하세요...' : isProcessing ? '처리 중...' : '음성 입력' }}
      </button>
      <input
        ref="textInputRef"
        type="text"
        v-model="currentTextMessage"
        @keyup.enter="handleSendTextMessage"
        placeholder="텍스트로 입력하거나 음성 입력 버튼을 누르세요..."
        :disabled="isRecording || (isProcessing && !currentTextMessage.trim())"
      />
      <button
        @click="handleSendTextMessage"
        :disabled="isRecording || isProcessing || !currentTextMessage.trim()"
      >
        전송
      </button>
    </div>

    <div v-if="aiAudioStreamUrl" class="audio-player">
      <audio
        ref="audioPlayerRef"
        :src="aiAudioStreamUrl"
        autoplay
        controls
        @ended="handleAiAudioEnded"
        @error="handleAiAudioError"
        style="width: 100%"
      ></audio>
      <p>AI 음성 재생 중...</p>
      <button @click="handleStopAiAudio">음성 중지</button>
    </div>
    <div v-if="errorText" class="error-message">
      <p style="color: red">{{ errorText }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useChatStore } from '../stores/chatStore'

const chatStore = useChatStore()

const messages = computed(() => chatStore.getMessages)
const isProcessing = computed(() => chatStore.getIsProcessing) // LLM 처리 등
const errorText = computed(() => chatStore.getError)
const interimSttText = computed(() => chatStore.getInterimStt)
const aiAudioStreamUrl = computed(() => chatStore.getAiAudioStreamUrl) // TTS 스트리밍 URL

const currentTextMessage = ref('')
const isRecording = ref(false)
const textInputRef = ref<HTMLInputElement | null>(null)
const audioPlayerRef = ref<HTMLAudioElement | null>(null)
const messagesAreaRef = ref<HTMLDivElement | null>(null)

let mediaRecorder: MediaRecorder | null = null
let audioStream: MediaStream | null = null
let audioContext: AudioContext | null = null
let analyser: AnalyserNode | null = null
let speakingTimer: number | null = null
const SILENCE_THRESHOLD = -50 // dB, 조정 필요
const SILENCE_DELAY = 1500 // ms, 조정 필요

// --- WebSocket 초기화 ---
onMounted(() => {
  chatStore.initializeSession() // 세션 초기화 및 WebSocket 연결 시도
  nextTick(() => textInputRef.value?.focus())

  // EPD 감지를 위한 이벤트 리스너 (chatStore에서 이벤트 발생 시)
  // EventBus 사용 또는 watch로 chatStore의 특정 상태 감지
  // 예: watch(() => chatStore.someEpdFlag, (isEpd) => { if (isEpd) stopRecording(); });
})

onUnmounted(() => {
  stopRecording() // 컴포넌트 파괴 시 녹음 중지
  if (audioContext && audioContext.state !== 'closed') {
    audioContext.close()
  }
  chatStore.disconnectWebSocket() // WebSocket 연결 해제
  if (aiAudioStreamUrl.value && audioPlayerRef.value) {
    audioPlayerRef.value.pause()
    chatStore.clearAiAudioStreamUrl()
  }
})

// --- 실시간 STT 및 EPD ---
const startRecording = async () => {
  if (isProcessing.value && !isRecording.value) return // LLM 처리 중에는 새 녹음 방지 (옵션)
  try {
    audioStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    isRecording.value = true
    chatStore.currentInterimStt = '' // 이전 중간 결과 초기화
    chatStore.error = null

    // Barge-in: AI 음성 재생 중이면 중지
    if (audioPlayerRef.value && !audioPlayerRef.value.paused) {
      handleStopAiAudio()
    }
    // 서버에도 사용자 발화 시작 알림 (필요시)
    // chatStore.sendWebSocketMessage({ type: 'user_speaking_started' });

    const options = { mimeType: 'audio/webm; codecs=opus', timeslice: 500 } // timeslice로 청크 발생 주기 설정
    try {
      mediaRecorder = new MediaRecorder(audioStream, options)
    } catch (e) {
      console.warn('opus/webm 지원 안됨, 기본값 시도', e)
      mediaRecorder = new MediaRecorder(audioStream, { timeslice: 500 })
    }

    mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        chatStore.sendAudioChunk(event.data) // Blob 직접 전송
      }
    }

    mediaRecorder.onstop = () => {
      // EPD에 의해 중지되거나 사용자가 수동 중지 시
      isRecording.value = false
      // 서버에 녹음 종료 알림 (필요시, STT 서버가 EPD로 자동 판단하면 불필요)
      // chatStore.sendWebSocketMessage({ type: 'audio_stream_ended' });
      if (audioStream) {
        audioStream.getTracks().forEach((track) => track.stop())
        audioStream = null
      }
      if (analyser) {
        // EPD 관련 정리
        analyser.disconnect()
        analyser = null
      }
      if (speakingTimer) {
        clearTimeout(speakingTimer)
        speakingTimer = null
      }
    }

    mediaRecorder.start() // timeslice에 따라 ondataavailable 주기적 호출

    // 클라이언트 사이드 EPD (옵션, 서버 STT의 EPD가 더 정확할 수 있음)
    setupClientSideEPD(audioStream)
  } catch (err) {
    console.error('마이크 접근 또는 녹음 시작 오류:', err)
    chatStore.error = '마이크를 사용할 수 없거나 녹음 시작에 실패했습니다.'
    isRecording.value = false
  }
}

const stopRecording = () => {
  if (mediaRecorder && isRecording.value) {
    mediaRecorder.stop() // onstop 핸들러 자동 호출
  }
  // isRecording.value = false; // onstop에서 처리
}

const handleToggleRecording = async () => {
  if (isRecording.value) {
    stopRecording()
  } else {
    if (!chatStore.getIsWebSocketConnected) {
      chatStore.error = '서버에 연결되지 않았습니다. 잠시 후 다시 시도해주세요.'
      chatStore.connectWebSocket() // 연결 시도
      return
    }
    await startRecording()
  }
}

// 클라이언트 사이드 EPD 설정 (Web Audio API)
const setupClientSideEPD = (stream: MediaStream) => {
  if (!audioContext || audioContext.state === 'closed') {
    audioContext = new (window.AudioContext || (window as any).webkitAudioContext)()
  }
  analyser = audioContext.createAnalyser()
  const source = audioContext.createMediaStreamSource(stream)
  source.connect(analyser)
  analyser.fftSize = 512
  const bufferLength = analyser.frequencyBinCount
  const dataArray = new Uint8Array(bufferLength)

  let silenceStartTime: number | null = null

  function checkSilence() {
    if (!isRecording.value) return // 녹음 중이 아니면 중단

    analyser!.getByteFrequencyData(dataArray)
    let sum = 0
    for (let i = 0; i < bufferLength; i++) {
      sum += dataArray[i]
    }
    const average = sum / bufferLength
    const volume = 20 * Math.log10(average / 255) // 대략적인 dB 값

    if (volume < SILENCE_THRESHOLD) {
      // 임계값보다 조용하면
      if (silenceStartTime === null) {
        silenceStartTime = Date.now()
      } else if (Date.now() - silenceStartTime > SILENCE_DELAY) {
        console.log('Client-side EPD: Silence detected, stopping recording.')
        stopRecording()
        silenceStartTime = null // 타이머 리셋
        return // 검사 중지
      }
    } else {
      silenceStartTime = null // 소리가 감지되면 리셋
    }
    requestAnimationFrame(checkSilence)
  }
  checkSilence()
}

// --- 텍스트 메시지 전송 (WebSocket) ---
const handleSendTextMessage = async () => {
  if (!currentTextMessage.value.trim() || (isProcessing.value && !isRecording.value)) return
  if (!chatStore.getIsWebSocketConnected) {
    chatStore.error = '서버에 연결되지 않았습니다. 잠시 후 다시 시도해주세요.'
    chatStore.connectWebSocket() // 연결 시도
    return
  }
  chatStore.sendTextMessage(currentTextMessage.value)
  currentTextMessage.value = ''
  nextTick(() => textInputRef.value?.focus())
}

// --- TTS 오디오 플레이어 이벤트 핸들러 ---
watch(aiAudioStreamUrl, (newUrl, oldUrl) => {
  if (newUrl && audioPlayerRef.value) {
    // audioPlayerRef.value.src = newUrl; // <audio :src="url"> 로 이미 바인딩됨
    // audioPlayerRef.value.load(); // autoplay가 있다면 필요 없을 수 있음
    audioPlayerRef.value.play().catch((e) => console.error('Audio play failed:', e))
  } else if (!newUrl && audioPlayerRef.value) {
    audioPlayerRef.value.pause()
    audioPlayerRef.value.removeAttribute('src')
    audioPlayerRef.value.load() // 리소스 정리
  }
})

const handleAiAudioEnded = () => {
  console.log('AI 음성 재생 완료.')
  chatStore.clearAiAudioStreamUrl() // 스토어의 URL도 정리
  nextTick(() => textInputRef.value?.focus())
}

const handleAiAudioError = (e: Event) => {
  console.error('AI 음성 재생 오류:', e)
  chatStore.error = 'AI 음성 재생 중 오류가 발생했습니다.'
  chatStore.clearAiAudioStreamUrl()
  nextTick(() => textInputRef.value?.focus())
}

const handleStopAiAudio = () => {
  console.log('사용자가 AI 음성 중지.')
  if (audioPlayerRef.value) {
    audioPlayerRef.value.pause()
  }
  chatStore.clearAiAudioStreamUrl()
  // 서버에 TTS 중단 메시지 전송 (필요시)
  // chatStore.sendWebSocketMessage({ type: 'stop_tts' });
  nextTick(() => textInputRef.value?.focus())
}

// --- 메시지 영역 스크롤 ---
watch(
  messages,
  async () => {
    await nextTick()
    if (messagesAreaRef.value) {
      messagesAreaRef.value.scrollTop = messagesAreaRef.value.scrollHeight
    }
  },
  { deep: true },
)
</script>

<style scoped>
/* STT 중간 결과 스타일 */
.message.stt-interim p {
  color: #888;
  font-style: italic;
}

/* LLM 스트리밍 중 커서 효과 */
.message.streaming p .typing-cursor::after {
  content: '▋';
  animation: blink 1s step-start infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}

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
.audio-player audio {
  margin-bottom: 5px;
} /* 오디오 컨트롤 기본 스타일 */
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
