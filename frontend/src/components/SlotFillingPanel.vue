<script setup lang="ts">
import { computed } from 'vue'
import { useSlotFillingStore } from '@/stores/slotFillingStore'
import type { RequiredField } from '@/types/slotFilling'

const slotFillingStore = useSlotFillingStore()

// Store에서 데이터 가져오기
const productType = computed(() => slotFillingStore.productType)
const fieldGroups = computed(() => slotFillingStore.getFieldsByGroup)
const completionRate = computed(() => slotFillingStore.visibleCompletionRate)
const collectedInfo = computed(() => slotFillingStore.collectedInfo)
const completionStatus = computed(() => slotFillingStore.completionStatus)

// 필드 값 포맷팅
const formatFieldValue = (field: RequiredField, value: any): string => {
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

// 필드가 완료되었는지 확인
const isFieldCompleted = (fieldKey: string): boolean => {
  return completionStatus.value[fieldKey] || false
}

// 필드가 표시되어야 하는지 확인
const isFieldVisible = (field: RequiredField): boolean => {
  return slotFillingStore.isFieldVisible(field)
}
</script>

<template>
  <div class="slot-filling-panel">
    <div class="panel-header">
      <h3>정보 수집 현황</h3>
      <div class="progress-section">
        <div class="progress-bar">
          <div 
            class="progress-fill" 
            :style="{ width: `${completionRate}%` }"
          ></div>
        </div>
        <span class="progress-text">{{ completionRate }}%</span>
      </div>
      <div v-if="productType" class="product-type">
        {{ productType }}
      </div>
    </div>

    <div class="panel-body">
      <div 
        v-for="group in fieldGroups" 
        :key="group.id"
        class="field-group"
      >
        <h4 class="group-title">{{ group.name }}</h4>
        
        <div class="fields-list">
          <div 
            v-for="field in group.fields" 
            :key="field.key"
            v-show="isFieldVisible(field)"
            :class="[
              'field-item',
              { 'completed': isFieldCompleted(field.key) }
            ]"
          >
            <div class="field-status">
              <span v-if="isFieldCompleted(field.key)" class="check-mark">✓</span>
              <span v-else class="empty-circle">○</span>
            </div>
            
            <div class="field-content">
              <div class="field-name">
                {{ field.displayName }}
                <span v-if="field.required" class="required-mark">*</span>
              </div>
              
              <div 
                v-if="isFieldCompleted(field.key)" 
                class="field-value"
              >
                {{ formatFieldValue(field, collectedInfo[field.key]) }}
              </div>
            </div>
            
            <div 
              v-if="field.description" 
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
      <div v-if="fieldGroups.length === 0" class="empty-message">
        대화를 시작하면 수집된 정보가 여기에 표시됩니다.
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

.progress-section {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.progress-bar {
  flex: 1;
  height: 10px;
  background-color: #e0e0e0;
  border-radius: 5px;
  overflow: hidden;
  position: relative;
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.1);
}

.progress-fill {
  height: 100%;
  background: linear-gradient(135deg, #66bb6a 0%, #4caf50 50%, #43a047 100%);
  transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);
  border-radius: 5px;
  position: relative;
  overflow: hidden;
}

.progress-fill::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(
    45deg,
    transparent 30%,
    rgba(255, 255, 255, 0.3) 50%,
    transparent 70%
  );
  animation: progressShine 2s infinite;
}

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
</style>