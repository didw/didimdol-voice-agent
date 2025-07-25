<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import { useSlotFillingStore } from '@/stores/slotFillingStore'
import type { SmartField } from '@/types/slotFilling'
import ProgressBar from './ProgressBar.vue'

const slotFillingStore = useSlotFillingStore()

// refs for auto-scroll
const panelBodyRef = ref<HTMLElement>()
const lastFieldCount = ref(0)

// Store에서 데이터 가져오기 (새로운 구조)
const productType = computed(() => slotFillingStore.productType)
const hierarchicalFieldGroups = computed(() => {
  // limit_account_guide 단계에서는 아무것도 표시하지 않음
  if (currentStage.value?.stageId === 'limit_account_guide') {
    return []
  }
  return slotFillingStore.hierarchicalFieldGroups
})
const currentStage = computed(() => {
  const stage = slotFillingStore.currentStage
  if (stage) {
    console.log('[SlotFillingPanel] Current stage:', stage.stageId, 'visibleGroups:', stage.visibleGroups)
  }
  return stage
})
const completionRate = computed(() => slotFillingStore.visibleCompletionRate)
const collectedInfo = computed(() => slotFillingStore.collectedInfo)
const completionStatus = computed(() => slotFillingStore.completionStatus)

// 필드 값 포맷팅
const formatFieldValue = (field: SmartField, value: any): string => {
  if (value === null || value === undefined) return ''
  
  switch (field.type) {
    case 'boolean':
      return value ? '예' : '아니오'
    case 'number':
      return field.unit ? `${value.toLocaleString()}${field.unit}` : value.toString()
    case 'choice':
    case 'text':
    default:
      return value.toString()
  }
}

// 필드가 완료되었는지 확인 (default 값이 있는 경우도 완료로 간주)
const isFieldCompleted = (field: SmartField): boolean => {
  // 백엔드에서 default 값이 있는 필드는 자동으로 collected_info에 포함되므로
  // completionStatus만 확인하면 됨
  return completionStatus.value[field.key] || false
}

// 현재 스테이지의 필드인지 확인 (시각적 강조용)
const isCurrentStageField = (field: SmartField): boolean => {
  if (!currentStage.value?.visibleGroups) return false
  
  // 현재 표시되는 그룹에 속한 필드인지 확인
  const currentGroups = hierarchicalFieldGroups.value
  return currentGroups.some(group => 
    group.fields.some(f => f.key === field.key)
  )
}

// 필드 깊이에 따른 스타일 계산
const getFieldDepthStyle = (field: SmartField) => {
  const depth = field.depth || 0
  return {
    marginLeft: `${depth * 20}px`,
    paddingLeft: `${depth > 0 ? 12 : 10}px`,
    borderLeft: depth > 0 ? `2px solid rgba(76, 175, 80, ${0.3 + (depth * 0.2)})` : 'none'
  }
}

// 현재 단계의 그룹인지 확인
const isCurrentStageGroup = (group: any): boolean => {
  if (!currentStage.value) {
    return false
  }
  
  // currentStageGroups가 있으면 우선 사용 (더 정확함)
  if (currentStage.value.currentStageGroups) {
    console.log('[SlotFillingPanel] Checking group:', group.id, 'against currentStageGroups:', currentStage.value.currentStageGroups)
    return currentStage.value.currentStageGroups.includes(group.id)
  }
  
  // fallback: visibleGroups 사용
  if (currentStage.value.visibleGroups) {
    console.log('[SlotFillingPanel] Checking group:', group.id, 'against visibleGroups:', currentStage.value.visibleGroups)
    return currentStage.value.visibleGroups.includes(group.id)
  }
  
  return false
}

// 자동 스크롤 기능
watch(() => slotFillingStore.visibleFields, (newFields, oldFields) => {
  // 새로운 필드가 추가되었는지 확인
  if (newFields.length > lastFieldCount.value) {
    console.log('[SlotFillingPanel] New fields added, auto-scrolling...')
    
    // DOM이 업데이트된 후 스크롤
    nextTick(() => {
      if (panelBodyRef.value) {
        // 현재 단계의 모든 필드가 보이도록 스크롤
        const currentStageGroups = panelBodyRef.value.querySelectorAll('.field-group')
        
        if (currentStageGroups.length > 0) {
          // 현재 단계 배지가 있는 그룹 찾기
          let targetGroup: HTMLElement | null = null
          currentStageGroups.forEach((group) => {
            if (group.querySelector('.stage-badge')) {
              targetGroup = group as HTMLElement
            }
          })
          
          if (targetGroup) {
            // 현재 단계 그룹으로 스크롤
            targetGroup.scrollIntoView({ 
              behavior: 'smooth', 
              block: 'start' 
            })
            
            // 해당 그룹의 모든 필드에 하이라이트 효과
            const groupFields = targetGroup.querySelectorAll('.field-item')
            groupFields.forEach((field) => {
              field.classList.add('newly-added')
              setTimeout(() => {
                field.classList.remove('newly-added')
              }, 2000)
            })
          } else {
            // 현재 단계 배지가 없으면 마지막 필드로 스크롤
            const fieldItems = panelBodyRef.value.querySelectorAll('.field-item')
            if (fieldItems.length > 0) {
              const lastFieldItem = fieldItems[fieldItems.length - 1] as HTMLElement
              lastFieldItem.scrollIntoView({ 
                behavior: 'smooth', 
                block: 'center' 
              })
            }
          }
        }
      }
    })
  }
  
  // 현재 필드 수 업데이트
  lastFieldCount.value = newFields.length
}, { immediate: true })

// 현재 단계 변경 감지
watch(() => slotFillingStore.currentStage, (newStage, oldStage) => {
  if (newStage && newStage.stageId !== oldStage?.stageId) {
    console.log('[SlotFillingPanel] Stage changed to:', newStage.stageId)
    
    // 새로운 단계로 자동 스크롤
    nextTick(() => {
      if (panelBodyRef.value) {
        const currentStageGroups = panelBodyRef.value.querySelectorAll('.field-group')
        
        currentStageGroups.forEach((group) => {
          const stageBadge = group.querySelector('.stage-badge')
          if (stageBadge) {
            const groupElement = group as HTMLElement
            groupElement.scrollIntoView({ 
              behavior: 'smooth', 
              block: 'start' 
            })
          }
        })
      }
    })
  }
})
</script>

<template>
  <div class="slot-filling-panel">
    <!-- 진행률 바 컴포넌트 -->
    <ProgressBar />
    
    <div class="panel-header">
      <h3>수집 정보 상세</h3>
      
      <!-- 현재 스테이지 정보 표시 -->
      <div v-if="currentStage" class="stage-info">
        <div class="stage-label">현재 단계</div>
        <div class="stage-name">{{ currentStage.stageId }}</div>
      </div>
      
      <div v-if="productType" class="product-type">
        {{ productType }}
      </div>
    </div>

    <div class="panel-body" ref="panelBodyRef">
      <!-- 새로운 계층적 필드 표시 -->
      <div 
        v-for="group in hierarchicalFieldGroups" 
        :key="group.id"
        class="field-group"
      >
        <h4 class="group-title">
          {{ group.name }}
          <span v-if="isCurrentStageGroup(group)" class="stage-badge">현재 단계</span>
        </h4>
        
        <!-- 계층적 필드 렌더링 (간소화) -->
        <div class="hierarchical-fields">
          <div 
            v-for="field in group.fields" 
            :key="field.key"
            :class="[
              'field-item',
              `depth-${field.depth || 0}`,
              { 
                'completed': isFieldCompleted(field),
                'current-stage': isCurrentStageField(field)
              }
            ]"
            :style="getFieldDepthStyle(field)"
          >
              <div class="field-status">
                <span v-if="isFieldCompleted(field)" class="check-mark">✓</span>
                <span v-else class="empty-circle">○</span>
              </div>
              
              <div class="field-content">
                <div class="field-name">
                  {{ field.displayName }}
                  <span v-if="field.required" class="required-mark">*</span>
                  <span v-if="field.depth && field.depth > 0" class="depth-indicator">
                    ↳
                  </span>
                </div>
                
                <div 
                  v-if="isFieldCompleted(field)" 
                  class="field-value"
                >
                  {{ formatFieldValue(field, collectedInfo[field.key]) }}
                </div>
                
                <!-- 조건 표시 (개발 환경에서만) -->
                <div 
                  v-if="false && field.showWhen" 
                  class="field-condition"
                  :title="`조건: ${field.showWhen}`"
                >
                  <small>{{ field.showWhen }}</small>
                </div>
              </div>
              
              <div 
                v-if="field.description && !isFieldCompleted(field)" 
                class="field-tooltip"
                :title="field.description"
                :aria-label="field.description"
                role="tooltip"
                tabindex="0"
              >
                <span aria-hidden="true">?</span>
              </div>
            </div>
        </div>
      </div>

      <!-- 필드가 없을 때 메시지 -->
      <div v-if="hierarchicalFieldGroups.length === 0" class="empty-message">
        <template v-if="currentStage?.stageId === 'limit_account_guide'">
          한도계좌 개설에 동의하시면 정보 수집을 시작합니다.
        </template>
        <template v-else>
          대화를 시작하면 수집된 정보가 여기에 표시됩니다.
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.slot-filling-panel {
  height: 100%;
  background-color: var(--color-background);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  padding: 20px;
  border-bottom: 1px solid var(--color-border);
  background-color: var(--color-background-soft);
}

.panel-header h3 {
  margin: 0 0 15px 0;
  font-size: 1.2em;
  color: var(--color-heading);
}

/* 현재 스테이지 정보 스타일 */
.stage-info {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding: 6px 10px;
  background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
  border-radius: 6px;
  border-left: 3px solid #2196f3;
}

.stage-label {
  font-size: 0.75em;
  color: #1976d2;
  font-weight: 500;
  opacity: 0.8;
}

.stage-name {
  font-size: 0.85em;
  color: #1976d2;
  font-weight: 600;
}

/* Progress section styles moved to ProgressBar.vue component */

@keyframes progressShine {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(100%);
  }
}

.progress-text {
  font-size: 0.9em;
  font-weight: 500;
  color: var(--color-text);
  min-width: 40px;
}

.product-type {
  font-size: 0.85em;
  color: var(--color-text);
  opacity: 0.8;
  padding: 4px 8px;
  background-color: var(--color-background-mute);
  border-radius: 4px;
  display: inline-block;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.field-group {
  margin-bottom: 25px;
}

.field-group:last-child {
  margin-bottom: 0;
}

.group-title {
  font-size: 0.95em;
  font-weight: 600;
  color: var(--color-heading);
  margin: 0 0 12px 0;
  padding: 8px 12px;
  background: linear-gradient(135deg, var(--color-background-soft) 0%, var(--color-background-mute) 100%);
  border-radius: 6px;
  border-left: 4px solid #4caf50;
  position: relative;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  transition: all 0.2s ease;
}

.group-title:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
}

/* 스테이지 배지 스타일 */
.stage-badge {
  font-size: 0.7em;
  color: #2196f3;
  background-color: rgba(33, 150, 243, 0.1);
  padding: 2px 6px;
  border-radius: 3px;
  margin-left: 8px;
  font-weight: 500;
}

/* 계층적 필드 스타일 */
.hierarchical-fields {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.depth-layer {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.fields-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.field-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px;
  border-radius: 6px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  background-color: var(--color-background-mute);
  opacity: 0.7;
  border: 1px solid transparent;
  transform: translateX(0);
}

.field-item.completed {
  opacity: 1;
  background-color: #e8f5e9;
  border-color: #4caf50;
  transform: translateX(2px);
  box-shadow: 0 2px 8px rgba(76, 175, 80, 0.2);
}

/* 깊이별 필드 스타일 */
.field-item.depth-0 {
  background-color: var(--color-background-mute);
  border-radius: 8px;
}

.field-item.depth-1 {
  background-color: rgba(76, 175, 80, 0.05);
  border-radius: 6px;
  margin-top: 4px;
}

.field-item.depth-2 {
  background-color: rgba(33, 150, 243, 0.05);
  border-radius: 4px;
  margin-top: 2px;
}

.field-item.depth-3 {
  background-color: rgba(255, 193, 7, 0.05);
  border-radius: 4px;
}

/* 깊이 표시기 스타일 */
.depth-indicator {
  color: #4caf50;
  font-size: 0.8em;
  margin-left: 4px;
  opacity: 0.7;
}

/* 조건 표시 스타일 */
.field-condition {
  margin-top: 2px;
  opacity: 0.6;
}

.field-condition small {
  font-size: 0.7em;
  color: #666;
  font-style: italic;
}

/* 현재 스테이지 필드 강조 스타일 */
.field-item.current-stage {
  border-left: 4px solid #2196f3;
  background: linear-gradient(135deg, #e3f2fd 0%, #ffffff 100%);
}

.field-item.current-stage:not(.completed) {
  opacity: 0.9;
  animation: pulseCurrentStage 2s ease-in-out infinite;
}

@keyframes pulseCurrentStage {
  0%, 100% {
    box-shadow: 0 2px 8px rgba(33, 150, 243, 0.2);
  }
  50% {
    box-shadow: 0 2px 12px rgba(33, 150, 243, 0.4);
  }
}

.field-item:hover {
  transform: translateX(2px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.field-status {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.check-mark {
  color: #4caf50;
  font-weight: bold;
  font-size: 14px;
}

.empty-circle {
  color: #ccc;
  font-size: 14px;
}

.field-content {
  flex: 1;
}

.field-name {
  font-size: 0.9em;
  font-weight: 500;
  color: var(--color-text);
  margin-bottom: 2px;
}

.required-mark {
  color: #e74c3c;
  margin-left: 2px;
}

.field-value {
  font-size: 0.85em;
  color: var(--color-text);
  opacity: 0.9;
}

.field-item.completed .field-value {
  font-weight: 500;
  color: #2e7d32;
}


.field-tooltip {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background-color: #e0e0e0;
  color: #666;
  font-size: 0.75em;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: help;
  transition: background-color 0.2s;
}

.field-tooltip:hover {
  background-color: #d0d0d0;
}

/* 필수 필드가 미완료일 때 강조 */
.field-item:not(.completed) .required-mark {
  font-weight: bold;
  font-size: 1.1em;
}

/* 키보드 포커스 스타일 */
.field-tooltip:focus {
  outline: 2px solid var(--color-border-hover);
  outline-offset: 2px;
}

.empty-message {
  text-align: center;
  color: var(--color-text);
  opacity: 0.6;
  padding: 40px 20px;
  font-size: 0.9em;
}

/* 스크롤바 스타일링 */
.panel-body::-webkit-scrollbar {
  width: 6px;
}

.panel-body::-webkit-scrollbar-track {
  background: transparent;
}

.panel-body::-webkit-scrollbar-thumb {
  background-color: #ccc;
  border-radius: 3px;
}

.panel-body::-webkit-scrollbar-thumb:hover {
  background-color: #999;
}

/* 다크 모드 지원 */
@media (prefers-color-scheme: dark) {
  .field-item.completed {
    background-color: #1b5e20;
    opacity: 0.9;
  }
  
  .field-item.completed .field-value {
    color: #81c784;
  }
  
  .field-item.current-stage {
    background: linear-gradient(135deg, #1a237e 0%, #303f9f 100%);
    border-left-color: #3f51b5;
  }
  
  .stage-info {
    background: linear-gradient(135deg, #1a237e 0%, #303f9f 100%);
    border-left-color: #3f51b5;
  }
  
  .stage-label,
  .stage-name {
    color: #90caf9;
  }
  
  .stage-badge {
    color: #90caf9;
    background-color: rgba(144, 202, 249, 0.1);
  }
  
  .progress-bar {
    background-color: #424242;
  }
}

/* 애니메이션 */
@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(-10px) scale(0.95);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes slideInCompleted {
  from {
    transform: translateX(-20px);
    background-color: var(--color-background-mute);
  }
  to {
    transform: translateX(2px);
    background-color: #e8f5e9;
  }
}

.field-item {
  animation: fadeIn 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.field-item.completed {
  animation: slideInCompleted 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 필드 값 변경 시 강조 효과 */
@keyframes valueUpdate {
  0% {
    background-color: #fff3cd;
    transform: scale(1.02);
  }
  100% {
    background-color: #e8f5e9;
    transform: scale(1);
  }
}

.field-item.value-updated {
  animation: valueUpdate 0.6s ease;
}

/* 새로 추가된 필드 애니메이션 */
.field-item.newly-added {
  animation: highlightNewField 2s ease-out;
}

@keyframes highlightNewField {
  0% {
    background-color: #ffeb3b;
    transform: scale(1.05);
    box-shadow: 0 4px 20px rgba(255, 235, 59, 0.5);
  }
  50% {
    background-color: #fff59d;
    transform: scale(1.02);
  }
  100% {
    background-color: var(--color-background-mute);
    transform: scale(1);
    box-shadow: none;
  }
}

/* 완료된 필드에 대한 newly-added 애니메이션 */
.field-item.completed.newly-added {
  animation: highlightNewCompletedField 2s ease-out;
}

@keyframes highlightNewCompletedField {
  0% {
    background-color: #81c784;
    transform: scale(1.05);
    box-shadow: 0 4px 20px rgba(76, 175, 80, 0.5);
  }
  50% {
    background-color: #a5d6a7;
    transform: scale(1.02);
  }
  100% {
    background-color: #e8f5e9;
    transform: scale(1);
    box-shadow: 0 2px 8px rgba(76, 175, 80, 0.2);
  }
}
</style>