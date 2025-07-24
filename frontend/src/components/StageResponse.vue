<template>
  <div class="stage-response" v-if="responseData">
    <!-- Narrative 타입 -->
    <div v-if="responseData.responseType === 'narrative'" class="narrative-response">
      <p><strong>AI:</strong> {{ responseData.prompt }}</p>
    </div>
    
    <!-- Bullet 타입 -->
    <div v-else-if="responseData.responseType === 'bullet'" class="bullet-response">
      <p><strong>AI:</strong> {{ responseData.prompt }}</p>
      <div class="choices">
        <button 
          v-for="choice in responseData.choices" 
          :key="choice.value"
          @click="selectChoice(choice.value || choice.label)"
          class="choice-button"
          :aria-label="`선택: ${choice.label}`"
        >
          {{ choice.label }}
        </button>
      </div>
    </div>
    
    <!-- Boolean 타입 -->
    <div v-else-if="responseData.responseType === 'boolean'" class="boolean-response">
      <p><strong>AI:</strong> {{ responseData.prompt }}</p>
      <div class="boolean-choices">
        <div 
          v-for="choice in responseData.choices" 
          :key="choice.key"
          class="boolean-item"
        >
          <span class="choice-label">{{ choice.label }}</span>
          <label class="toggle-switch">
            <input 
              type="checkbox" 
              v-model="booleanSelections[choice.key!]"
              @change="updateBoolean"
              :aria-label="`${choice.label} 토글`"
            />
            <span class="toggle-slider"></span>
            <span class="toggle-text">{{ booleanSelections[choice.key!] ? '신청' : '미신청' }}</span>
          </label>
        </div>
      </div>
      <button 
        @click="submitBooleanSelections"
        class="submit-button"
        :disabled="!hasAnySelection"
      >
        선택 완료
      </button>
    </div>
    
    <!-- 수정 가능한 필드 표시 -->
    <div v-if="responseData.modifiableFields && responseData.modifiableFields.length > 0" class="modifiable-info">
      <small>수정하실 항목이 있으시면 말씀해주세요.</small>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { useChatStore } from '@/stores/chatStore';
import type { StageResponseMessage, Choice } from '@/types/stageResponse';

interface Props {
  responseData: StageResponseMessage | null;
}

const props = defineProps<Props>();
const chatStore = useChatStore();

const booleanSelections = ref<Record<string, boolean>>({});

// Boolean 초기값 설정
watch(() => props.responseData, (newData) => {
  if (newData && newData.responseType === 'boolean' && newData.choices) {
    const newSelections: Record<string, boolean> = {};
    newData.choices.forEach(choice => {
      if (choice.key) {
        newSelections[choice.key] = choice.default || false;
      }
    });
    booleanSelections.value = newSelections;
  }
}, { immediate: true });

const hasAnySelection = computed(() => {
  return Object.values(booleanSelections.value).some(v => v === true);
});

const selectChoice = (value: string) => {
  if (!props.responseData) return;
  chatStore.sendUserChoice(props.responseData.stageId, value);
};

const updateBoolean = () => {
  // Boolean 값이 변경될 때마다 호출됨
  console.log('Boolean selections updated:', booleanSelections.value);
};

const submitBooleanSelections = () => {
  if (!props.responseData) return;
  chatStore.sendBooleanSelections(props.responseData.stageId, booleanSelections.value);
};
</script>

<style scoped>
.stage-response {
  margin: 0;
}

.narrative-response p,
.bullet-response p,
.boolean-response p {
  margin: 0;
  margin-bottom: 0.5rem;
  line-height: 1.6;
}

/* Bullet 스타일 */
.choices {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-top: 1rem;
}

.choice-button {
  padding: 0.75rem 1.25rem;
  background-color: #f7f8fa;
  border: 2px solid transparent;
  border-radius: 0.5rem;
  font-size: 1rem;
  cursor: pointer;
  transition: all 0.2s ease;
  text-align: left;
}

.choice-button:hover {
  background-color: #e8f0fe;
  border-color: #1976d2;
}

.choice-button:active {
  transform: translateY(1px);
}

/* Boolean 스타일 */
.boolean-choices {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  margin: 1rem 0;
}

.boolean-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem;
  background-color: #ffffff;
  border: 1px solid #e0e0e0;
  border-radius: 0.5rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.choice-label {
  font-weight: 500;
  color: #333333;
  font-size: 1rem;
}

/* 토글 스위치 스타일 */
.toggle-switch {
  position: relative;
  display: inline-flex;
  align-items: center;
  cursor: pointer;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: relative;
  width: 3rem;
  height: 1.5rem;
  background-color: #ccc;
  border-radius: 1.5rem;
  transition: 0.3s;
  margin-right: 0.5rem;
}

.toggle-slider:before {
  position: absolute;
  content: "";
  height: 1.1rem;
  width: 1.1rem;
  left: 0.2rem;
  bottom: 0.2rem;
  background-color: white;
  border-radius: 50%;
  transition: 0.3s;
}

.toggle-switch input:checked + .toggle-slider {
  background-color: #1976d2;
}

.toggle-switch input:checked + .toggle-slider:before {
  transform: translateX(1.5rem);
}

.toggle-text {
  font-size: 0.875rem;
  min-width: 3rem;
  color: #555555;
  font-weight: 500;
}

/* Submit 버튼 */
.submit-button {
  margin-top: 1.5rem;
  padding: 0.75rem 2rem;
  background-color: #1976d2;
  color: white;
  border: none;
  border-radius: 0.5rem;
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  width: 100%;
}

.submit-button:hover:not(:disabled) {
  background-color: #1565c0;
}

.submit-button:disabled {
  background-color: #ccc;
  cursor: not-allowed;
}

/* 수정 가능 정보 */
.modifiable-info {
  margin-top: 1rem;
  padding: 0.5rem;
  background-color: #f0f7ff;
  border-radius: 0.25rem;
  text-align: center;
}

.modifiable-info small {
  color: #666;
  font-size: 0.875rem;
}

/* 모바일 반응형 */
@media (max-width: 640px) {
  .choice-button {
    font-size: 0.875rem;
    padding: 0.625rem 1rem;
  }
  
  .boolean-item {
    padding: 0.625rem;
  }
  
  .toggle-slider {
    width: 2.5rem;
    height: 1.25rem;
  }
  
  .toggle-slider:before {
    height: 0.9rem;
    width: 0.9rem;
  }
  
  .toggle-switch input:checked + .toggle-slider:before {
    transform: translateX(1.25rem);
  }
}
</style>