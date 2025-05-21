<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useChatStore } from '@/stores/chatStore' // 경로 확인
import { storeToRefs } from 'pinia' // storeToRefs can be useful if not using computed for everything

const chatStore = useChatStore()

// Using computed properties for most store state as per the new script
const messages = computed(() => chatStore.getMessages)
const interimStt = computed(() => chatStore.getInterimStt) // Renamed from currentInterimStt for consistency
const error = computed(() => chatStore.getError)
const isVoiceModeActive = computed(() => chatStore.getIsVoiceModeActive)
const isRecording = computed(() => chatStore.getIsRecording)
const isProcessingLLM = computed(() => chatStore.getIsProcessingLLM)
const isPlayingTTS = computed(() => chatStore.getIsPlayingTTS)
const isSynthesizingTTS = computed(() => chatStore.getIsSynthesizingTTS) // For "음성 준비 중..."
const isEPDDetectedByServer = computed(() => chatStore.getIsEPDDetectedByServer)
const isWebSocketConnected = computed(() => chatStore.getIsWebSocketConnected)
const sessionId = computed(() => chatStore.getSessionId)

const userInputText = ref('') // For the text input field
const messagesContainer = ref<HTMLElement | null>(null)

// --- Scrolling Logic (Retained from original) ---
const scrollToBottom = async () => {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

watch(messages, scrollToBottom, { deep: true })
watch(interimStt, scrollToBottom) // Scroll also on interim results

// --- Lifecycle Hooks ---
onMounted(() => {
  chatStore.initializeSessionAndConnect()
  scrollToBottom() // Initial scroll
})

onUnmounted(() => {
  chatStore.disconnectWebSocket()
  // Clean up client-side VAD resources if they were initialized
  if (vadInterval) clearInterval(vadInterval)
  if (audioContextForVAD && audioContextForVAD.state !== 'closed') {
    audioContextForVAD.close()
  }
})

// --- Text Message Handling ---
const handleSendTextMessage = () => {
  if (userInputText.value.trim()) {
    chatStore.sendWebSocketTextMessage(userInputText.value.trim())
    userInputText.value = ''
  }
}

// --- Voice Mode Toggle ---
const toggleMicrophone = async () => {
  await chatStore.toggleVoiceMode()
}

// --- Watch for user typing to potentially deactivate voice mode ---
watch(userInputText, (newValue) => {
  if (newValue.length > 0 && isVoiceModeActive.value) {
    // console.log('User started typing, consider deactivating voice mode.')
    // chatStore.deactivateVoiceRecognition(); // Consider if this is desired UX
  }
})

// --- Client-side Barge-in VAD Logic (From new script) ---
// let localMediaStreamForVAD: MediaStream | null = null; // Not needed, use chatStore.audioStream
let audioContextForVAD: AudioContext | null = null
let analyserNode: AnalyserNode | null = null
let dataArrayForVAD: Uint8Array | null = null
let vadInterval: number | null = null

const monitorMicActivityForBargeIn = () => {
  if (!isVoiceModeActive.value || !isPlayingTTS.value || !chatStore.audioStream) {
    if (vadInterval) clearInterval(vadInterval)
    vadInterval = null
    return
  }

  if (!audioContextForVAD || audioContextForVAD.state === 'closed') {
    audioContextForVAD = new AudioContext()
    analyserNode = audioContextForVAD.createAnalyser()
    analyserNode.fftSize = 2048
    dataArrayForVAD = new Uint8Array(analyserNode.frequencyBinCount)

    try {
      // Ensure audioStream is valid and has tracks
      if (chatStore.audioStream && chatStore.audioStream.getAudioTracks().length > 0) {
        const source = audioContextForVAD.createMediaStreamSource(chatStore.audioStream)
        source.connect(analyserNode)
      } else {
        console.warn('VAD: chatStore.audioStream is null or has no audio tracks.')
        if (vadInterval) clearInterval(vadInterval)
        vadInterval = null
        return
      }
    } catch (e) {
      console.error('Error connecting mic to VAD analyser:', e)
      if (vadInterval) clearInterval(vadInterval)
      vadInterval = null
      // Attempt to close context if source creation failed
      if (audioContextForVAD && audioContextForVAD.state !== 'closed') {
        audioContextForVAD.close()
        audioContextForVAD = null
      }
      return
    }
  }

  if (vadInterval) clearInterval(vadInterval) // Clear previous interval

  vadInterval = window.setInterval(() => {
    // Check audioContextForVAD state inside interval
    if (
      !analyserNode ||
      !dataArrayForVAD ||
      !isPlayingTTS.value ||
      !isVoiceModeActive.value ||
      !audioContextForVAD ||
      audioContextForVAD.state === 'closed'
    ) {
      if (vadInterval) clearInterval(vadInterval)
      vadInterval = null
      return
    }
    analyserNode.getByteFrequencyData(dataArrayForVAD)
    let sum = 0
    for (let i = 0; i < dataArrayForVAD.length; i++) {
      sum += dataArrayForVAD[i]
    }
    const average = dataArrayForVAD.length > 0 ? sum / dataArrayForVAD.length : 0

    const VAD_THRESHOLD = 10 // Example threshold, adjust as needed
    if (average > VAD_THRESHOLD) {
      console.log('Client-side VAD: User speaking detected during TTS. Stopping TTS.')
      chatStore.stopClientSideTTSPlayback(true) // Stop client TTS and notify server
      if (vadInterval) clearInterval(vadInterval) // Stop VAD monitoring once triggered
      vadInterval = null
    }
  }, 100) // Check every 100ms
}

watch(isPlayingTTS, (newValue) => {
  if (newValue && isVoiceModeActive.value) {
    monitorMicActivityForBargeIn()
  } else {
    if (vadInterval) clearInterval(vadInterval)
    vadInterval = null
  }
})

watch(isVoiceModeActive, (newValue) => {
  if (!newValue) {
    if (vadInterval) clearInterval(vadInterval)
    vadInterval = null
    // Ensure VAD audio context is closed when voice mode is off
    if (audioContextForVAD && audioContextForVAD.state !== 'closed') {
      audioContextForVAD.close().then(() => (audioContextForVAD = null))
    }
  } else if (newValue && isPlayingTTS.value) {
    monitorMicActivityForBargeIn()
  }
})

// Watcher from original for server-side EPD (if any specific UI reaction is needed beyond the indicator)
// This was for stopping client recording, which is now handled by toggleVoiceMode / server instructions.
// The EPD indicator div below is sufficient for the new requirements.
// watch(isEPDDetectedByServer, (newVal) => {
//   if (newVal && isRecording.value) { // isRecording from store
//     console.log('EPD detected from server, (client recording might be stopped by store logic if applicable).')
//     // chatStore.isEPDDetectedByServer = false // Reset in store if needed
//   }
// })
</script>

<template>
  <div class="chat-container">
    <header class="chat-header">
      <h2>
        디딤돌 대출 음성봇
        <small v-if="sessionId"> (세션: {{ sessionId?.substring(0, 8) }})</small>
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
        <span
          v-if="isSynthesizingTTS && !isProcessingLLM && !isPlayingTTS"
          class="status-text"
          title="음성 합성 중"
          >음성 준비 중...</span
        >
        <span v-if="isPlayingTTS" class="status-text" title="음성 재생 중">음성 재생 중...</span>
      </div>
    </header>

    <div class="messages-area" ref="messagesContainer">
      <div
        v-for="message in messages"
        :key="message.id"
        :class="['message', message.sender, message.isInterimStt ? 'interim-stt-finalized' : '']"
      >
        <p>
          <strong>{{ message.sender === 'user' ? 'You' : 'AI' }}:</strong>
          {{ message.text }}
          <span
            v-if="message.isStreaming && message.sender === 'ai'"
            class="streaming-cursor"
          ></span>
        </p>
        <span class="timestamp">{{ new Date(message.timestamp).toLocaleTimeString() }}</span>
      </div>
      <div v-if="interimStt && isVoiceModeActive" class="message user interim-stt">
        <p>
          <em>{{ interimStt }}<span class="streaming-cursor"></span></em>
        </p>
      </div>
    </div>

    <div v-if="error" class="error-message">오류: {{ error }}</div>

    <div v-if="isEPDDetectedByServer && isVoiceModeActive" class="epd-indicator">
      음성 입력 감지 완료 (서버)
    </div>

    <div class="input-area">
      <input
        type="text"
        v-model="userInputText"
        @keyup.enter="handleSendTextMessage"
        placeholder="메시지를 입력하세요..."
        :disabled="isVoiceModeActive || isProcessingLLM || !isWebSocketConnected"
      />
      <button
        @click="handleSendTextMessage"
        :disabled="
          isVoiceModeActive || isProcessingLLM || !userInputText.trim() || !isWebSocketConnected
        "
        class="send-button"
      >
        전송
      </button>
      <button
        @click="toggleMicrophone"
        :class="{
          'mic-button': true,
          'mic-active': isVoiceModeActive,
          'mic-recording': isRecording,
        }"
        :disabled="!isWebSocketConnected"
        :title="isVoiceModeActive ? (isRecording ? '녹음 중지' : '음성 활성화 중...') : '음성 시작'"
      >
        <span v-if="isVoiceModeActive && isRecording">🔴 중지</span>
        <span v-else-if="isVoiceModeActive && !isRecording">🎙️ 활성...</span>
        <span v-else>🎙️ 음성</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.chat-container {
  display: flex;
  flex-direction: column;
  /* height: 90vh; Adjust as needed, or use 100% if parent has height */
  height: 100%;
  width: 100%;
  max-width: 700px;
  margin: auto;
  border: 1px solid #ccc;
  border-radius: 8px;
  overflow: hidden;
  background-color: #f9f9f9; /* Added from original for consistency */
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1); /* Added from original */
}

/* Header styles from original, slightly adapted if needed */
.chat-header {
  background-color: #4caf50;
  color: white;
  padding: 10px 15px;
  text-align: center;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #ddd; /* Added for separation */
}
.chat-header h2 {
  margin: 0;
  font-size: 1.2em;
}
.chat-header h2 small {
  font-size: 0.7em;
  opacity: 0.9;
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
  padding: 3px 7px;
  border-radius: 4px;
  background-color: rgba(255, 255, 255, 0.2);
  color: white;
}
.status-text.recording-active {
  background-color: #ff9800; /* Orange for recording */
}

.messages-area {
  flex-grow: 1;
  padding: 15px; /* Original padding */
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px; /* Gap from original */
  background-color: #ffffff; /* Original background */
}

.message {
  padding: 10px 15px; /* Original padding */
  border-radius: 18px; /* Original radius */
  max-width: 75%; /* Original max-width */
  word-wrap: break-word;
  line-height: 1.4; /* Original line-height */
}
.message p {
  margin: 0;
}

.message.user {
  background-color: #dcf8c6;
  align-self: flex-end;
  /* border-bottom-right-radius: 0; */ /* From new, but original had full radius */
  margin-left: auto; /* Original alignment */
}

.message.ai {
  background-color: #ececec; /* Original AI color */
  align-self: flex-start;
  /* border-bottom-left-radius: 0; */ /* From new, but original had full radius */
  margin-right: auto; /* Original alignment */
}

.message.interim-stt p {
  /* Styles for interim STT text */
  color: #777;
  font-style: italic;
}

.streaming-cursor::after {
  /* From original */
  content: '▋';
  animation: blink 1s step-end infinite;
  font-size: 0.9em; /* Adjusted to match common cursor sizes */
  margin-left: 2px;
  vertical-align: baseline;
}

@keyframes blink {
  /* From original */
  50% {
    opacity: 0;
  }
}

.timestamp {
  /* From original */
  display: block;
  font-size: 0.75em;
  color: #888;
  margin-top: 5px;
}
.message.user .timestamp {
  text-align: right;
}
.message.ai .timestamp {
  text-align: left;
}

.input-area {
  display: flex;
  padding: 10px;
  border-top: 1px solid #ccc;
  background-color: #f0f0f0; /* Original bg */
}

.input-area input[type='text'] {
  /* Target input specifically */
  flex-grow: 1;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 20px;
  margin-right: 10px;
  font-size: 1em; /* Original font size */
  line-height: 1.4; /* Original line-height */
  resize: none; /* From original textarea */
}

.input-area button {
  padding: 10px 15px;
  border: none;
  border-radius: 20px;
  cursor: pointer;
  font-size: 1em;
  /* margin-left: 5px; */ /* Removed to rely on gap or specific button margins */
}
.input-area button:disabled {
  background-color: #aaa;
  cursor: not-allowed;
}

.input-area button.send-button {
  /* Class from original for specificity */
  background-color: #4caf50; /* Original send color */
  color: white;
  margin-right: 5px; /* Spacing */
}
.input-area button.send-button:disabled {
  background-color: #a5d6a7; /* Original disabled send color */
}

.input-area button.mic-button {
  /* Class from original for specificity */
  background-color: #2196f3; /* Original mic color */
  color: white;
}
.input-area button.mic-button:disabled {
  background-color: #90caf9; /* Original disabled mic color */
}

.input-area button.mic-active {
  /* From new style, for active state */
  background-color: #ff4136; /* Red when voice mode is generally active */
}

.input-area button.mic-recording {
  /* From new style, specifically when recording */
  background-color: #e00000; /* Darker red when recording */
  animation: pulse 1.5s infinite alternate; /* Modified pulse */
}

.error-message {
  color: red;
  padding: 10px; /* Original padding */
  text-align: center;
  font-size: 0.9em;
  background-color: #ffebee; /* Original bg */
  border-bottom: 1px solid #e57373; /* Original border */
}

.epd-indicator {
  padding: 4px 10px; /* Slightly more padding */
  font-size: 0.8em;
  color: #333; /* Darker text */
  text-align: center;
  background-color: #e9e9e9; /* Slightly different bg */
  border-bottom: 1px solid #ccc;
}

@keyframes pulse {
  0% {
    opacity: 1;
    box-shadow: 0 0 2px 1px rgba(255, 0, 0, 0.7);
  }
  50% {
    opacity: 0.7;
    box-shadow: 0 0 4px 2px rgba(255, 0, 0, 0.4);
  }
  100% {
    opacity: 1;
    box-shadow: 0 0 2px 1px rgba(255, 0, 0, 0.7);
  }
}
</style>
