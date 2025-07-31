<template>
  <div class="stage-response" v-if="responseData">
    <!-- Narrative 타입 -->
    <div v-if="responseData.responseType === 'narrative'" class="narrative-response">
      <p class="narrative-text">
        <strong>AI:</strong> 
        <span v-html="formatPromptText(responseData.prompt)"></span>
      </p>
    </div>
    
    <!-- Bullet 타입 -->
    <div v-else-if="responseData.responseType === 'bullet'" class="bullet-response">
      <p class="bullet-text">
        <strong>AI:</strong> 
        <span v-html="formatPromptText(responseData.prompt)"></span>
      </p>
      
      <!-- choice_groups가 있는 경우 그룹으로 표시 -->
      <div v-if="responseData.choiceGroups && responseData.choiceGroups.length > 0" class="choice-groups">
        <div v-for="group in responseData.choiceGroups" :key="group.title" class="choice-group">
          <h4 class="group-title">{{ group.title }}</h4>
          <div class="group-choices">
            <button 
              v-for="(choice, index) in (group.items || [])" 
              :key="choice?.value || choice?.label || index"
              @click="selectChoice(choice?.value || choice?.label || '', choice?.display || choice?.label)"
              class="choice-button"
              :class="{ 'selected': isSelectedChoice(choice) }"
              :aria-label="`선택: ${choice?.display || choice?.label || choice?.value || '선택지'}`"
            >
              {{ choice?.display || choice?.label || choice?.value || `선택지 ${index + 1}` }}
            </button>
          </div>
        </div>
      </div>
      
      <!-- 일반 bullet 응답 처리 (choice_groups가 없는 경우) -->
      <div v-else :class="['choices', { 'horizontal-cards': responseData.stageId === 'card_selection' }]">
        <button 
          v-for="(choice, index) in (responseData.choices || [])" 
          :key="choice?.value || choice?.label || index"
          @click="selectChoice(choice?.value || choice?.label || '', choice?.display || choice?.label)"
          :class="['choice-button', { 'selected': isSelectedChoice(choice), 'card-choice': responseData.stageId === 'card_selection' }]"
          :aria-label="`선택: ${choice?.display || choice?.label || choice?.value || '선택지'}`"
        >
          {{ choice?.display || choice?.label || choice?.value || `선택지 ${index + 1}` }}
        </button>
      </div>
    </div>
    
    <!-- Boolean 타입 -->
    <div v-else-if="responseData.responseType === 'boolean'" class="boolean-response">
      <p class="boolean-text">
        <strong>AI:</strong> 
        <span v-html="formatPromptText(responseData.prompt)"></span>
      </p>
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
            <span class="toggle-text">{{ getBooleanText(booleanSelections[choice.key!]) }}</span>
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
    
    <!-- 추가 질문 표시 -->
    <div v-if="responseData.additionalQuestions && responseData.additionalQuestions.length > 0" class="additional-questions">
      <div class="additional-questions-header">
        <span class="plus-icon">+</span>
        <span class="additional-questions-title">다른 질문도 할 수 있어요.</span>
      </div>
      <div class="additional-questions-list">
        <button 
          v-for="(question, index) in responseData.additionalQuestions" 
          :key="index"
          @click="handleAdditionalQuestion(question)"
          class="additional-question-button"
          :aria-label="`추가 질문: ${question}`"
        >
          <span class="arrow-icon">→</span>
          <span class="question-text">{{ question }}</span>
        </button>
      </div>
    </div>
    
    <!-- 수정 가능한 필드 표시 (특정 단계 제외) -->
    <div v-if="responseData.modifiableFields && responseData.modifiableFields.length > 0 && !['customer_info_check', 'confirm_personal_info', 'security_medium_registration'].includes(responseData.stageId)" class="modifiable-info">
      <small>수정하실 항목이 있으시면 말씀해주세요.</small>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { useChatStore } from '@/stores/chatStore';
import { useSlotFillingStore } from '@/stores/slotFillingStore';
import type { StageResponseMessage, Choice } from '@/types/stageResponse';

interface Props {
  responseData: StageResponseMessage | null;
}

const props = defineProps<Props>();
const chatStore = useChatStore();

// CRITICAL DEBUG: Log all stage responses
watch(() => props.responseData, (newData) => {
  if (newData) {
    console.log('🔍 STAGE RESPONSE COMPONENT RECEIVED DATA:');
    console.log('  Full responseData:', JSON.stringify(newData, null, 2));
    console.log('  stageId:', newData.stageId);
    console.log('  responseType:', newData.responseType);
    console.log('  choices:', newData.choices);
    console.log('  choices.length:', newData.choices?.length);
    console.log('  choiceGroups:', newData.choiceGroups);
    console.log('  choiceGroups.length:', newData.choiceGroups?.length);
    console.log('  additionalQuestions:', newData.additionalQuestions);
    console.log('  additionalQuestions.length:', newData.additionalQuestions?.length);
    console.log('  typeof choiceGroups:', typeof newData.choiceGroups);
    console.log('  Array.isArray(choiceGroups):', Array.isArray(newData.choiceGroups));
    
    // 각 choice의 구조를 자세히 확인
    if (newData.choices && newData.choices.length > 0) {
      newData.choices.forEach((choice, index) => {
        console.log(`🔍 Choice ${index}:`, choice);
        console.log(`🔍 Choice ${index} keys:`, Object.keys(choice));
        console.log(`🔍 Choice ${index} display:`, choice.display);
        console.log(`🔍 Choice ${index} value:`, choice.value);
      });
    }
    
    // choiceGroups가 있는 경우 구조 확인
    if (newData.choiceGroups && newData.choiceGroups.length > 0) {
      newData.choiceGroups.forEach((group, groupIndex) => {
        console.log(`🔍 Group ${groupIndex}:`, group);
        console.log(`🔍 Group ${groupIndex} title:`, group.title);
        console.log(`🔍 Group ${groupIndex} items:`, group.items);
        if (group.items && group.items.length > 0) {
          group.items.forEach((item, itemIndex) => {
            console.log(`🔍 Group ${groupIndex} Item ${itemIndex}:`, item);
          });
        }
      });
    }
    
    console.log('  full data:', newData);
  }
}, { immediate: true });

const booleanSelections = ref<Record<string, boolean>>({});
const selectedChoice = ref<string>('');

// 선택된 선택지 확인
const isSelectedChoice = (choice: Choice) => {
  const value = choice?.value || choice?.display || choice?.label || '';
  return selectedChoice.value === value;
};

// 기본 선택값 설정 (bullet 타입)
watch(() => props.responseData, (newData) => {
  if (newData && newData.responseType === 'bullet') {
    let defaultChoice = newData.defaultChoice;
    
    // defaultChoice가 없으면 choices에서 default: true인 항목 찾기
    if (!defaultChoice && newData.choices) {
      for (const choice of newData.choices) {
        if (choice.default) {
          defaultChoice = choice.value || choice.display || choice.label;
          break;
        }
      }
    }
    
    // choices에서 못찾으면 choiceGroups에서 찾기
    if (!defaultChoice && newData.choiceGroups) {
      for (const group of newData.choiceGroups) {
        for (const item of (group.items || [])) {
          if (item.default) {
            defaultChoice = item.value || item.display || item.label;
            break;
          }
        }
        if (defaultChoice) break;
      }
    }
    
    if (defaultChoice) {
      selectedChoice.value = defaultChoice;
      console.log('🎯 Default choice set:', defaultChoice);
    }
  }
}, { immediate: true });

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

const selectChoice = (value: string, label?: string) => {
  if (!props.responseData) return;
  selectedChoice.value = value;
  console.log('🎯 Choice selected:', value, 'Label:', label);
  // label이 있으면 label을 사용, 없으면 value를 사용
  chatStore.sendUserChoice(props.responseData.stageId, value, label || value);
};

const updateBoolean = () => {
  // Boolean 값이 변경될 때마다 호출됨
  console.log('Boolean selections updated:', booleanSelections.value);
};

// Format prompt text with line breaks
const formatPromptText = (text: string): string => {
  if (!text) return '';
  
  // Handle various newline patterns
  return text
    .replace(/(\r\n|\r|\n)/g, '<br>')  // Standard newlines
    .replace(/\\n/g, '<br>')            // Escaped newlines
    .replace(/\n\n/g, '<br><br>');     // Double newlines for paragraphs
};

const submitBooleanSelections = () => {
  if (!props.responseData) return;
  chatStore.sendBooleanSelections(props.responseData.stageId, booleanSelections.value);
};

// Get boolean display text from store or use defaults
const getBooleanText = (value: boolean) => {
  const slotFillingStore = useSlotFillingStore();
  const displayLabels = slotFillingStore.displayLabels || {};
  return value 
    ? (displayLabels.boolean_true_alt || displayLabels.boolean_true || '신청') 
    : (displayLabels.boolean_false_alt || displayLabels.boolean_false || '미신청');
};

// 추가 질문 처리
const handleAdditionalQuestion = (question: string) => {
  console.log('🔍 Additional question clicked:', question);
  // 챗 스토어에 사용자 메시지로 추가
  chatStore.sendMessage(question);
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

.narrative-text,
.bullet-text,
.boolean-text {
  white-space: pre-wrap;
  word-break: break-word;
}

/* Bullet 스타일 */
.choices {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-top: 1rem;
}

/* 카드 선택 단계 수평 스크롤 */
.horizontal-cards {
  flex-direction: row;
  overflow-x: auto;
  gap: 1rem;
  padding: 0.5rem 0;
  scroll-behavior: smooth;
  -webkit-overflow-scrolling: touch;
}

.horizontal-cards::-webkit-scrollbar {
  height: 8px;
}

.horizontal-cards::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 4px;
}

.horizontal-cards::-webkit-scrollbar-thumb {
  background: #1976d2;
  border-radius: 4px;
}

.horizontal-cards::-webkit-scrollbar-thumb:hover {
  background: #1565c0;
}

/* Choice Groups 스타일 */
.choice-groups {
  margin-top: 1rem;
}

.choice-group {
  margin-bottom: 1.5rem;
}

.choice-group:last-child {
  margin-bottom: 0;
}

.group-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: #1976d2;
  margin-bottom: 0.75rem;
  padding-bottom: 0.5rem;
  border-bottom: 2px solid #1976d2;
  letter-spacing: 0.3px;
}

.group-choices {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding-left: 0.5rem;
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

.choice-button.selected {
  background-color: #1976d2;
  color: white;
  border-color: #1976d2;
}

.choice-button:active {
  transform: translateY(1px);
}

/* 카드 선택 버튼 스타일 */
.card-choice {
  min-width: 200px;
  height: 140px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  white-space: pre-line;
  font-size: 0.9rem;
  line-height: 1.3;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  background: linear-gradient(135deg, #f7f8fa 0%, #ffffff 100%);
  border: 2px solid #e0e0e0;
}

.card-choice:hover {
  box-shadow: 0 4px 12px rgba(25, 118, 210, 0.2);
  transform: translateY(-2px);
  border-color: #1976d2;
  background: linear-gradient(135deg, #e8f0fe 0%, #f7f8fa 100%);
}

.card-choice.selected {
  background: linear-gradient(135deg, #1976d2 0%, #1565c0 100%);
  box-shadow: 0 4px 16px rgba(25, 118, 210, 0.4);
  transform: translateY(-2px);
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

/* 추가 질문 스타일 */
.additional-questions {
  margin-top: 1.5rem;
  padding: 0;
}

.additional-questions-header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin-bottom: 0.5rem;
}

.plus-icon {
  font-size: 1.1rem;
  font-weight: 600;
  color: #6c757d;
}

.additional-questions-title {
  font-size: 0.95rem;
  font-weight: 500;
  color: #6c757d;
}

.additional-questions-list {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  margin-left: 1.5rem;
}

.additional-question-button {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background-color: transparent;
  border: none;
  font-size: 0.875rem;
  color: #495057;
  cursor: pointer;
  transition: all 0.2s ease;
  text-align: left;
  width: fit-content;
}

.additional-question-button:hover {
  color: #1976d2;
  transform: translateX(3px);
}

.arrow-icon {
  font-size: 0.875rem;
  color: #6c757d;
  flex-shrink: 0;
}

.additional-question-button:hover .arrow-icon {
  color: #1976d2;
}

.question-text {
  line-height: 1.4;
}

/* 모바일 반응형 */
@media (max-width: 640px) {
  .choice-button {
    font-size: 0.875rem;
    padding: 0.625rem 1rem;
  }
  
  .card-choice {
    min-width: 160px;
    height: 120px;
    font-size: 0.8rem;
    padding: 0.5rem;
  }
  
  .horizontal-cards {
    gap: 0.75rem;
    padding: 0.25rem 0;
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