<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useChatStore } from '@/stores/chatStore' // 경로 확인
import { useSlotFillingStore } from '@/stores/slotFillingStore'
import { storeToRefs } from 'pinia' // storeToRefs can be useful if not using computed for everything
import SlotFillingPanel from './SlotFillingPanel.vue'
import SlotFillingDebug from './SlotFillingDebug.vue'

// Props for layout control
interface Props {
  showSlotFilling?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  showSlotFilling: true
})

const chatInputRef = ref<HTMLInputElement | null>(null);
const userInput = ref('');
const chatStore = useChatStore()
const slotFillingStore = useSlotFillingStore()

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

// 레이아웃 제어
const isPanelOpen = ref(true)
const isMobileView = ref(window.innerWidth < 768)

// 스와이프 제스처 지원
const touchStartX = ref(0)
const touchStartY = ref(0)
const touchEndX = ref(0)
const touchEndY = ref(0)
const MIN_SWIPE_DISTANCE = 100
const MAX_VERTICAL_DISTANCE = 150

// 화면 크기 변경 감지
const handleResize = () => {
  isMobileView.value = window.innerWidth < 768
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})

// 모바일에서 패널 토글
const togglePanel = () => {
  isPanelOpen.value = !isPanelOpen.value
}

// 스와이프 이벤트 핸들러
const handleTouchStart = (event: TouchEvent) => {
  if (!isMobileView.value) return
  
  touchStartX.value = event.touches[0].clientX
  touchStartY.value = event.touches[0].clientY
}

const handleTouchEnd = (event: TouchEvent) => {
  if (!isMobileView.value) return
  
  touchEndX.value = event.changedTouches[0].clientX
  touchEndY.value = event.changedTouches[0].clientY
  
  handleSwipe()
}

const handleSwipe = () => {
  const deltaX = touchEndX.value - touchStartX.value
  const deltaY = Math.abs(touchEndY.value - touchStartY.value)
  
  // 세로 스와이프가 너무 크면 무시
  if (deltaY > MAX_VERTICAL_DISTANCE) return
  
  // 오른쪽으로 스와이프 (패널 열기)
  if (deltaX > MIN_SWIPE_DISTANCE && !isPanelOpen.value) {
    isPanelOpen.value = true
  }
  // 왼쪽으로 스와이프 (패널 닫기)
  else if (deltaX < -MIN_SWIPE_DISTANCE && isPanelOpen.value) {
    isPanelOpen.value = false
  }
}

// --- Scrolling Logic (Retained from original) ---
const scrollToBottom = async () => {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

const focusInput = async () => {
  await nextTick();
  console.log('Attempting to focus:', chatInputRef.value); // Log the element
  if (chatInputRef.value) {
    if (!chatInputRef.value.disabled) {
      chatInputRef.value.focus();
      console.log('document.activeElement:', document.activeElement); // Check what actually has focus
    } else {
      console.log('Focus skipped: Input is disabled.');
    }
  } else {
    console.error('chatInputRef is null, cannot focus.');
  }
};

const sendMessage = () => {
  if (userInput.value.trim()) {
    chatStore.sendWebSocketTextMessage(userInput.value.trim());
    userInput.value = '';
    // focusInput(); // Focus immediately after sending
  }
};

watch(
  () => chatStore.messages.length, // Watch the number of messages
  async (newMessageCount, oldMessageCount) => {
    if (newMessageCount > oldMessageCount) {
      const lastMessage = chatStore.messages[chatStore.messages.length - 1];
      if (lastMessage?.sender === 'ai' && !lastMessage.isStreaming) {
        await focusInput();
      } else if (lastMessage?.sender === 'user') { // This condition relies on a 'user' message being added
         await focusInput();
      }
    }
  }
);

watch(messages, scrollToBottom, { deep: true })
watch(interimStt, scrollToBottom) // Scroll also on interim results

// --- Lifecycle Hooks ---
onMounted(async () => {
  chatStore.initializeSessionAndConnect();
  await nextTick(); // Wait for initial rendering
  messagesContainer.value = document.querySelector('.messages-area'); // Or use ref on messages-area
  await scrollToBottom();
  await focusInput(); // Focus on mount
});

onUnmounted(() => {
  chatStore.disconnectWebSocket()
  slotFillingStore.cleanup() // 메모리 누수 방지
})

const handleSendTextMessage = async () => {
  if (userInputText.value.trim() && !chatInputRef.value?.disabled) {
    chatStore.sendWebSocketTextMessage(userInputText.value.trim());
    userInputText.value = '';
    await focusInput();
  }
};

// --- Voice Mode Toggle ---
const toggleMicrophone = async () => {
  await chatStore.toggleVoiceMode()
}

// Scroll to bottom when messages change
watch(messages, async () => {
  await nextTick();
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight;
  }
}, { deep: true });


// Watch for changes that should trigger a focus on the input
watch(
  [
    () => chatStore.messages, // More direct way to watch messages array for changes
    isProcessingLLM,         // Watch when LLM processing state changes
    isVoiceModeActive        // Watch when voice mode changes (input might become enabled)
  ],
  async ([currentMessages, currentIsProcessingLLM, currentIsVoiceMode], [oldMessages, oldIsProcessingLLM, oldIsVoiceMode]) => {
    await nextTick(); // Ensure DOM is updated based on these state changes

    const lastMessage = currentMessages.length > 0 ? currentMessages[currentMessages.length - 1] : null;

    // Scenario 1: AI has finished responding (and is not streaming)
    // and LLM processing is now false.
    if (
      lastMessage?.sender === 'ai' &&
      !lastMessage.isStreaming && // Ensure AI message streaming is complete
      oldIsProcessingLLM === true && currentIsProcessingLLM === false // LLM just finished
    ) {
      // console.log('AI finished, attempting to focus input.');
      await focusInput();
      return; // Focused, no need for other checks this run
    }

    // Scenario 2: User just sent a message
    // Check if a new user message was added
    if (lastMessage?.sender === 'user' && currentMessages.length > (oldMessages?.length || 0)) {
       // console.log('User message sent, attempting to focus input.');
       await focusInput();
       return;
    }

    // Scenario 3: Input becomes enabled after being disabled
    // e.g., LLM processing finished, or voice mode deactivated
    if (!chatInputRef.value?.disabled) {
        // If the input was previously disabled by LLM processing and now it's not
        if (oldIsProcessingLLM === true && currentIsProcessingLLM === false) {
            // console.log('Input enabled after LLM processing, focusing.');
            await focusInput();
            return;
        }
        // If the input was previously disabled by voice mode and now it's not
        if (oldIsVoiceMode === true && currentIsVoiceMode === false) {
            // console.log('Input enabled after voice mode deactivation, focusing.');
            await focusInput();
            return;
        }
    }
  },
  { deep: true, immediate: false } // 'deep' for messages array, 'immediate: false' to run after initial setup
);

// --- Watch for user typing to potentially deactivate voice mode ---
watch(userInputText, (newValue) => {
  if (newValue.length > 0 && isVoiceModeActive.value) {
    // console.log('User started typing, consider deactivating voice mode.')
    // chatStore.deactivateVoiceRecognition(); // Consider if this is desired UX
  }
})

// --- Client-side Barge-in VAD Logic (From new script) ---
// This entire section is now removed as the logic is fully centralized in chatStore.ts
</script>

<template>
  <div class="chat-interface-wrapper">
    <!-- Mobile Overlay -->
    <Transition name="fade">
      <div
        v-if="showSlotFilling && isMobileView && isPanelOpen"
        class="overlay"
        @click="togglePanel"
        aria-hidden="true"
      ></div>
    </Transition>

    <!-- Slot Filling Panel -->
    <Transition name="slide">
      <aside 
        v-if="showSlotFilling && (!isMobileView || isPanelOpen)" 
        class="slot-filling-section"
        :class="{ 'mobile-panel': isMobileView }"
      >
        <SlotFillingPanel />
      </aside>
    </Transition>

    <!-- Chat Container -->
    <div 
      class="chat-container" 
      :class="{ 'full-width': !showSlotFilling || (isMobileView && !isPanelOpen) }"
      @touchstart="handleTouchStart"
      @touchend="handleTouchEnd"
    >
      <!-- Mobile Toggle Button -->
      <button 
        v-if="showSlotFilling && isMobileView" 
        @click="togglePanel"
        @keydown.enter="togglePanel"
        @keydown.space.prevent="togglePanel"
        class="panel-toggle-btn"
        :aria-label="isPanelOpen ? '정보 패널 닫기' : '정보 패널 열기'"
        :aria-expanded="isPanelOpen ? 'true' : 'false'"
        role="button"
      >
        <span v-if="!isPanelOpen" aria-hidden="true">☰</span>
        <span v-else aria-hidden="true">×</span>
      </button>
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
        ref="chatInputRef" v-model="userInputText"
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
  </div>
</template>

<style scoped>
.chat-interface-wrapper {
  display: grid;
  grid-template-columns: 300px 1fr;
  height: 100%;
  width: 100%;
  position: relative;
}

/* 모바일 레이아웃 */
@media (max-width: 767px) {
  .chat-interface-wrapper {
    grid-template-columns: 1fr;
  }
  
  .slot-filling-section.mobile-panel {
    position: fixed;
    top: 0;
    left: 0;
    width: 80%;
    max-width: 320px;
    height: 100%;
    z-index: 1000;
    box-shadow: 2px 0 10px rgba(0, 0, 0, 0.1);
  }
}

/* 오버레이 스타일 */
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  z-index: 999;
  backdrop-filter: blur(2px);
}

/* 트랜지션 정의 */
.slide-enter-active,
.slide-leave-active {
  transition: transform 0.3s ease;
}

.slide-enter-from {
  transform: translateX(-100%);
}

.slide-leave-to {
  transform: translateX(-100%);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 태블릿 레이아웃 */
@media (min-width: 768px) and (max-width: 1023px) {
  .chat-interface-wrapper {
    grid-template-columns: 250px 1fr;
  }
}

.slot-filling-section {
  overflow: hidden;
  background-color: var(--color-background);
}

.panel-toggle-btn {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 100;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background-color: var(--color-background-soft);
  border: 1px solid var(--color-border);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.2em;
  transition: all 0.2s ease;
  box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
}

.panel-toggle-btn:hover {
  background-color: var(--color-background-mute);
  transform: scale(1.05);
}

.panel-toggle-btn:focus {
  outline: 2px solid #4caf50;
  outline-offset: 2px;
}

.panel-toggle-btn:active {
  transform: scale(0.95);
}

/* 스와이프 인디케이터 */
.chat-container::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 5px;
  width: 3px;
  height: 30px;
  background: linear-gradient(to bottom, transparent, #4caf50, transparent);
  border-radius: 2px;
  transform: translateY(-50%);
  opacity: 0;
  transition: opacity 0.3s ease;
  z-index: 10;
}

@media (max-width: 767px) {
  .chat-container:not(.full-width)::before {
    opacity: 0.6;
  }
}

.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%; /* 모바일에서는 화면 전체 너비 사용 */
  margin: auto;
  border: 1px solid #ccc;
  border-radius: 8px;
  overflow: hidden;
  background-color: var(--color-background-soft);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
}

.chat-container.full-width {
  max-width: 100%;
}

/* 데스크톱에서 ChatInterface가 혼자 사용될 때 */
@media (min-width: 768px) {
  .chat-container.full-width {
    max-width: 700px;
    margin: 0 auto;
  }
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
  position: relative;
}

@media (max-width: 767px) {
  .chat-header {
    padding-left: 60px; /* Space for toggle button */
  }
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
  padding: 10px; /* 패딩 조정 */
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
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
  color: #181818;
  align-self: flex-end;
  margin-left: auto;
}

.message.ai {
  background-color: var(--color-background-mute);
  align-self: flex-start;
  margin-right: auto;
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
  background-color: #f0f0f0;
  flex-shrink: 0; /* 입력창 영역의 크기가 줄어들지 않도록 방지 */
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

<!-- Debug Panel -->
<SlotFillingDebug />
