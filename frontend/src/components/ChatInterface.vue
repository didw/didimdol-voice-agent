<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useChatStore } from '@/stores/chatStore'
import { storeToRefs } from 'pinia'

const chatStore = useChatStore()
const {
  messages,
  isProcessingLLM,
  isSynthesizingTTS,
  error,
  currentInterimStt,
  isWebSocketConnected,
  sessionId,
  getAudioChunks, // TTS 오디오 청크 가져오기
  isEPDDetected,
} = storeToRefs(chatStore)

const userInput = ref('')
const isRecording = ref(false)
let mediaRecorder: MediaRecorder | null = null
let audioChunks: Blob[] = []

// 오디오 재생 관련
const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)()
let audioQueue: string[] = [] // Base64 청크 저장 큐
let isPlayingQueue = false
let sourceNode: AudioBufferSourceNode | null = null // 현재 재생 중인 source node

// EPD, Barge-in 관련
const VAD_THRESHOLD = 0.01 // Voice Activity Detection 임계값 (조정 필요)
const SILENCE_TIMEOUT_MS = 1500 // EPD를 위한 침묵 시간 (ms)
let silenceTimer: number | null = null
let audioProcessorNode: ScriptProcessorNode | null = null

const messagesContainer = ref<HTMLElement | null>(null)

const scrollToBottom = async () => {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

watch(messages, scrollToBottom, { deep: true })
watch(currentInterimStt, scrollToBottom)

onMounted(() => {
  chatStore.initializeSessionAndConnect()
  scrollToBottom()
})

onBeforeUnmount(() => {
  stopRecording()
  if (audioProcessorNode) {
    audioProcessorNode.disconnect()
  }
  if (audioContext.state !== 'closed') {
    audioContext.close()
  }
  chatStore.disconnectWebSocket()
})

const sendTextMessage = () => {
  if (userInput.value.trim() && isWebSocketConnected.value) {
    chatStore.sendWebSocketTextMessage(userInput.value)
    userInput.value = ''
  } else if (!isWebSocketConnected.value) {
    alert('서버와 연결되지 않았습니다. 잠시 후 다시 시도해주세요.')
  }
}

const toggleRecording = async () => {
  if (!isWebSocketConnected.value) {
    alert('서버와 연결되지 않았습니다. 음성 입력을 사용할 수 없습니다.')
    return
  }
  if (isRecording.value) {
    stopRecording()
  } else {
    await startRecording()
  }
}

const startRecording = async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    isRecording.value = true
    audioChunks = []
    // 오디오 컨텍스트가 suspended 상태일 수 있으므로 resume 시도
    if (audioContext.state === 'suspended') {
      await audioContext.resume()
    }

    // MediaRecorder 설정
    const options = { mimeType: 'audio/webm;codecs=opus' } // Opus 코덱 사용 권장
    mediaRecorder = new MediaRecorder(stream, options)

    mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        audioChunks.push(event.data)
        chatStore.sendAudioBlob(event.data) // 청크를 실시간으로 서버에 전송
      }
    }

    mediaRecorder.onstop = () => {
      isRecording.value = false
      // 남아있는 청크가 있다면 한번 더 전송 (옵션)
      // if (audioChunks.length > 0) {
      //   const finalBlob = new Blob(audioChunks, { type: options.mimeType });
      //   chatStore.sendAudioBlob(finalBlob);
      // }
      stream.getTracks().forEach((track) => track.stop()) // 스트림 트랙 중지
      console.log('Recording stopped, final chunks sent (if any).')
    }

    mediaRecorder.onerror = (event) => {
      console.error('MediaRecorder error:', event)
      chatStore.error = '녹음 중 오류가 발생했습니다.'
      isRecording.value = false
    }

    // 100ms 마다 청크 전송 (또는 서버 요구사항에 맞게 조절)
    mediaRecorder.start(250) // EPD/Barge-in을 위해 더 짧은 간격으로 청크 전송
    console.log('Recording started...')

    // EPD 로직 (클라이언트 사이드 VAD - 간단 버전)
    // 더 정교한 VAD는 Web Audio API의 AnalyserNode 사용 또는 외부 라이브러리 사용
    const audioSource = audioContext.createMediaStreamSource(stream)
    audioProcessorNode = audioContext.createScriptProcessor(4096, 1, 1) // bufferSize, inputChannels, outputChannels

    audioProcessorNode.onaudioprocess = (e) => {
      if (!isRecording.value) return // 녹음 중이 아니면 처리 안함

      const inputData = e.inputBuffer.getChannelData(0)
      let sum = 0
      for (let i = 0; i < inputData.length; ++i) {
        sum += inputData[i] * inputData[i]
      }
      const rms = Math.sqrt(sum / inputData.length)

      if (rms > VAD_THRESHOLD) {
        // 음성 감지
        if (silenceTimer) {
          clearTimeout(silenceTimer)
          silenceTimer = null
        }
      } else {
        // 침묵 감지
        if (!silenceTimer && isRecording.value) {
          // isRecording.value 체크 추가
          silenceTimer = window.setTimeout(() => {
            if (isRecording.value) {
              // 타임아웃 시점에도 녹음 중인지 재확인
              console.log('Client-side EPD: Silence detected, stopping recording.')
              stopRecording() // 침묵 길어지면 녹음 중지 (EPD)
            }
          }, SILENCE_TIMEOUT_MS)
        }
      }
    }
    audioSource.connect(audioProcessorNode)
    audioProcessorNode.connect(audioContext.destination) // 실제 오디오 출력은 안 함
  } catch (err) {
    console.error('Error starting recording:', err)
    chatStore.error = '음성 녹음을 시작할 수 없습니다. 마이크 권한을 확인해주세요.'
    isRecording.value = false
  }
}

const stopRecording = () => {
  if (mediaRecorder && isRecording.value) {
    mediaRecorder.stop() // onstop 핸들러에서 isRecording.value = false 처리
    console.log('Recording stop requested.')
  }
  if (silenceTimer) {
    clearTimeout(silenceTimer)
    silenceTimer = null
  }
  if (audioProcessorNode) {
    audioProcessorNode.disconnect()
    // audioProcessorNode = null; // 필요시 null 처리
  }
}

// 서버에서 EPD 감지 시 녹음 중지
watch(isEPDDetected, (newVal) => {
  if (newVal && isRecording.value) {
    console.log('EPD detected from server, stopping client recording.')
    stopRecording()
    chatStore.isEPDDetected = false // 상태 다시 초기화
  }
})

// TTS 오디오 청크 재생 로직
watch(
  getAudioChunks,
  async (newChunks) => {
    if (newChunks.length > 0) {
      audioQueue.push(...newChunks) // 새 청크를 큐에 추가
      chatStore.clearAudioChunks() // 스토어의 청크는 비움
      if (!isPlayingQueue) {
        playNextChunkFromQueue()
      }
    }
  },
  { deep: true },
)

const playNextChunkFromQueue = async () => {
  if (audioQueue.length === 0) {
    isPlayingQueue = false
    return
  }
  isPlayingQueue = true
  const base64Chunk = audioQueue.shift()

  if (base64Chunk) {
    try {
      const audioData = Uint8Array.from(atob(base64Chunk), (c) => c.charCodeAt(0)).buffer
      const audioBuffer = await audioContext.decodeAudioData(audioData)

      // 이전 sourceNode가 있다면 중지 (Barge-in 대비)
      if (sourceNode) {
        sourceNode.stop()
        sourceNode.disconnect()
      }

      sourceNode = audioContext.createBufferSource()
      sourceNode.buffer = audioBuffer
      sourceNode.connect(audioContext.destination)
      sourceNode.start()
      sourceNode.onended = () => {
        if (sourceNode) {
          // onended 콜백 시점에는 sourceNode가 null이 아님을 보장
          sourceNode.disconnect() // 연결 해제
        }
        sourceNode = null // 재생 완료 후 null로 설정
        if (audioQueue.length > 0) {
          playNextChunkFromQueue() // 다음 청크 재생
        } else {
          isPlayingQueue = false // 큐 비면 재생 중지 상태
        }
      }
    } catch (e) {
      console.error('Error decoding or playing audio chunk:', e)
      chatStore.error = '오디오 재생 중 오류가 발생했습니다.'
      isPlayingQueue = false
      playNextChunkFromQueue() // 오류 발생 시 다음 청크 시도
    }
  } else {
    playNextChunkFromQueue() // 빈 청크면 다음으로
  }
}

// Barge-in: 사용자 발화 시작 시 TTS 중단
const handleUserInputFocus = () => {
  if (isPlayingQueue || isSynthesizingTTS.value) {
    console.log('User input focus, attempting to stop TTS for Barge-in.')
    chatStore.requestStopTTS() // 서버에 TTS 중단 요청

    // 클라이언트 측에서도 즉시 중단
    if (sourceNode) {
      sourceNode.stop()
      sourceNode.disconnect()
      sourceNode = null
    }
    audioQueue = [] // 오디오 재생 큐 비우기
    isPlayingQueue = false
  }
}
</script>

<template>
  <div class="chat-container">
    <header class="chat-header">
      <h2>
        디딤돌 대출 음성봇 <small v-if="sessionId"> (세션: {{ sessionId?.substring(0, 8) }})</small>
      </h2>
      <div class="status-indicators">
        <span
          :class="['status-dot', isWebSocketConnected ? 'connected' : 'disconnected']"
          :title="isWebSocketConnected ? '서버 연결됨' : '서버 연결 끊김'"
        ></span>
        <span v-if="isRecording" class="status-text recording-active" title="녹음 중">REC</span>
        <span v-if="isProcessingLLM" class="status-text" title="AI 생각 중"
          >AI 응답 생성 중...</span
        >
        <span v-if="isSynthesizingTTS && !isProcessingLLM" class="status-text" title="음성 합성 중"
          >음성 준비 중...</span
        >
      </div>
    </header>

    <div class="messages-area" ref="messagesContainer">
      <div
        v-for="message in messages"
        :key="message.id"
        :class="['message-bubble', message.sender]"
      >
        <p>
          <span v-if="message.sender === 'user'">👤:</span>
          <span v-else>🤖:</span>
          {{ message.text }}
          <span v-if="message.isStreaming" class="streaming-cursor"></span>
        </p>
        <span class="timestamp">{{ new Date(message.timestamp).toLocaleTimeString() }}</span>
      </div>
      <div v-if="currentInterimStt" class="message-bubble user interim-stt">
        <p>👤: {{ currentInterimStt }}<span class="streaming-cursor"></span></p>
      </div>
    </div>

    <div v-if="error" class="error-message">오류: {{ error }}</div>

    <div class="input-area">
      <textarea
        v-model="userInput"
        @keyup.enter.exact="sendTextMessage"
        @focus="handleUserInputFocus"
        placeholder="메시지를 입력하거나 마이크 버튼을 누르세요..."
        :disabled="isRecording || !isWebSocketConnected"
      ></textarea>
      <button
        @click="sendTextMessage"
        :disabled="!userInput.trim() || isRecording || !isWebSocketConnected"
        class="send-button"
      >
        전송
      </button>
      <button
        @click="toggleRecording"
        :class="['mic-button', { recording: isRecording }]"
        :disabled="!isWebSocketConnected"
        :title="isRecording ? '녹음 중지' : '녹음 시작'"
      >
        🎤
      </button>
    </div>
  </div>
</template>

<style scoped>
.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-width: 800px;
  margin: auto;
  border: 1px solid #ccc;
  border-radius: 8px;
  overflow: hidden;
  background-color: #f9f9f9;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
}

.chat-header {
  background-color: #4caf50;
  color: white;
  padding: 10px 15px;
  text-align: center;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.chat-header h2 {
  margin: 0;
  font-size: 1.2em;
}
.status-indicators {
  display: flex;
  align-items: center;
  gap: 8px;
}
.status-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  display: inline-block;
}
.status-dot.connected {
  background-color: #8bc34a; /* Light Green */
}
.status-dot.disconnected {
  background-color: #f44336; /* Red */
}

.status-text {
  font-size: 0.8em;
  padding: 2px 6px;
  border-radius: 4px;
  background-color: rgba(255, 255, 255, 0.2);
}
.recording-active {
  background-color: #ff9800; /* Orange for recording */
  color: white;
}

.messages-area {
  flex-grow: 1;
  overflow-y: auto;
  padding: 15px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  background-color: #ffffff;
}

.message-bubble {
  padding: 10px 15px;
  border-radius: 18px;
  max-width: 75%;
  word-wrap: break-word;
}

.message-bubble.user {
  background-color: #dcf8c6;
  align-self: flex-end;
  margin-left: auto;
  text-align: right;
}

.message-bubble.ai {
  background-color: #ececec;
  align-self: flex-start;
  margin-right: auto;
}
.message-bubble p {
  margin: 0;
  line-height: 1.4;
}

.timestamp {
  display: block;
  font-size: 0.75em;
  color: #888;
  margin-top: 5px;
}
.message-bubble.user .timestamp {
  text-align: right;
}
.message-bubble.ai .timestamp {
  text-align: left;
}

.interim-stt p {
  color: #777;
  font-style: italic;
}

.streaming-cursor::after {
  content: '▋';
  animation: blink 1s step-end infinite;
  font-size: 0.9em;
  margin-left: 2px;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

.input-area {
  display: flex;
  padding: 10px;
  border-top: 1px solid #ccc;
  background-color: #f0f0f0;
}

.input-area textarea {
  flex-grow: 1;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 20px;
  margin-right: 10px;
  resize: none;
  min-height: 24px; /* 최소 높이 */
  max-height: 120px; /* 최대 높이 */
  overflow-y: auto; /* 내용 많을 시 스크롤 */
  font-size: 1em;
  line-height: 1.4;
}

.input-area button {
  padding: 10px 15px;
  border: none;
  border-radius: 20px;
  cursor: pointer;
  font-size: 1em;
}
.send-button {
  background-color: #4caf50;
  color: white;
}
.send-button:disabled {
  background-color: #a5d6a7;
}

.mic-button {
  background-color: #2196f3;
  color: white;
  margin-left: 5px;
}
.mic-button.recording {
  background-color: #f44336; /* Red when recording */
}
.mic-button:disabled {
  background-color: #90caf9;
}

.error-message {
  color: red;
  padding: 10px;
  text-align: center;
  font-size: 0.9em;
  background-color: #ffebee;
  border-bottom: 1px solid #e57373;
}
</style>
