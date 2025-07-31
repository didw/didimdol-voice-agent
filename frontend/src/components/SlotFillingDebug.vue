<template>
  <div class="debug-panel" v-if="showDebugPanel">
    <div class="debug-header">
      <h3>Slot Filling Debug Panel</h3>
      <button @click="toggleDebugPanel" class="close-btn">×</button>
    </div>
    
    <div class="debug-content">
      <!-- 기본 정보 -->
      <div class="debug-section">
        <h4>기본 정보</h4>
        <div class="debug-item">
          <span class="label">Product Type:</span>
          <span class="value">{{ productType || 'None' }}</span>
        </div>
        <div class="debug-item">
          <span class="label">Completion Rate:</span>
          <span class="value">{{ completionRate }}%</span>
        </div>
        <div class="debug-item">
          <span class="label">Required Fields:</span>
          <span class="value">{{ requiredFields.length }}</span>
        </div>
        <div class="debug-item">
          <span class="label">Collected Info:</span>
          <span class="value">{{ Object.keys(collectedInfo).length }}</span>
        </div>
        <div class="debug-item">
          <span class="label">Field Groups:</span>
          <span class="value">{{ fieldGroups.length }}</span>
        </div>
      </div>

      <!-- 필드별 상세 정보 -->
      <div class="debug-section">
        <h4>필드별 상세 정보</h4>
        <div class="fields-table">
          <div class="table-header">
            <span>Key</span>
            <span>Display Name</span>
            <span>Type</span>
            <span>Required</span>
            <span>Value</span>
            <span>Completed</span>
          </div>
          <div 
            v-for="field in requiredFields" 
            :key="field.key"
            class="table-row"
            :class="{ 'completed': completionStatus[field.key] }"
          >
            <span class="field-key">{{ field.key }}</span>
            <span class="field-display-name">{{ field.displayName }}</span>
            <span class="field-type">{{ field.type }}</span>
            <span class="field-required">{{ field.required ? '✓' : '○' }}</span>
            <span class="field-value">{{ formatValue(collectedInfo[field.key], field.key) }}</span>
            <span class="field-completed">{{ completionStatus[field.key] ? '✓' : '○' }}</span>
          </div>
        </div>
      </div>

      <!-- 수집된 정보 원본 -->
      <div class="debug-section">
        <h4>수집된 정보 (Raw Data)</h4>
        <pre class="json-display">{{ JSON.stringify(collectedInfo, null, 2) }}</pre>
      </div>

      <!-- 필드 그룹 정보 -->
      <div class="debug-section" v-if="fieldGroups.length > 0">
        <h4>필드 그룹</h4>
        <div v-for="group in fieldGroups" :key="group.id" class="group-item">
          <div class="group-header">
            <span class="group-name">{{ group.name }}</span>
            <span class="group-id">({{ group.id }})</span>
          </div>
          <div class="group-fields">
            <span v-for="fieldKey in group.fields" :key="fieldKey" class="group-field">
              {{ fieldKey }}
            </span>
          </div>
        </div>
      </div>

      <!-- 최근 업데이트 히스토리 -->
      <div class="debug-section">
        <h4>최근 업데이트 히스토리</h4>
        <div class="update-history">
          <div 
            v-for="(update, index) in recentUpdates.slice().reverse()" 
            :key="index"
            class="update-item"
          >
            <div class="update-timestamp">{{ update.timestamp }}</div>
            <div class="update-summary">
              Product: {{ update.productType }}, 
              Fields: {{ update.fieldsCount }}, 
              Collected: {{ update.collectedCount }}, 
              Rate: {{ update.completionRate }}%
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  
  <!-- 디버그 패널 토글 버튼 -->
  <button 
    @click="toggleDebugPanel" 
    class="debug-toggle-btn"
    :class="{ 'active': showDebugPanel }"
  >
    🐛 Debug
  </button>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useSlotFillingStore } from '@/stores/slotFillingStore'

const slotFillingStore = useSlotFillingStore()
const showDebugPanel = ref(false)

// Store 데이터
const productType = computed(() => slotFillingStore.productType)
const requiredFields = computed(() => slotFillingStore.requiredFields)
const collectedInfo = computed(() => slotFillingStore.collectedInfo)
const completionStatus = computed(() => slotFillingStore.completionStatus)
const completionRate = computed(() => slotFillingStore.completionRate)
const fieldGroups = computed(() => slotFillingStore.fieldGroups)

// 최근 업데이트 히스토리 (간단한 구현)
const recentUpdates = ref<Array<{
  timestamp: string
  productType: string
  fieldsCount: number
  collectedCount: number
  completionRate: number
}>>([])

// 업데이트 히스토리 추가
const addUpdateHistory = () => {
  const now = new Date()
  const timestamp = now.toLocaleTimeString()
  
  recentUpdates.value.push({
    timestamp,
    productType: productType.value || 'None',
    fieldsCount: requiredFields.value.length,
    collectedCount: Object.keys(collectedInfo.value).length,
    completionRate: completionRate.value
  })
  
  // 최근 10개만 유지
  if (recentUpdates.value.length > 10) {
    recentUpdates.value.shift()
  }
}

// 한국어 통화 단위 변환 함수
const formatKoreanCurrency = (amount: number): string => {
  if (amount >= 100000000) { // 1억 이상
    if (amount % 100000000 === 0) {
      return `${amount / 100000000}억원`
    } else {
      const awk = Math.floor(amount / 100000000)
      const remainder = amount % 100000000
      if (remainder % 10000 === 0) {
        const man = remainder / 10000
        return `${awk}억${man}만원`
      } else {
        return `${amount.toLocaleString()}원` // 복잡한 경우 기존 방식
      }
    }
  } else if (amount >= 10000) { // 1만원 이상
    if (amount % 10000 === 0) {
      return `${amount / 10000}만원`
    } else {
      const man = Math.floor(amount / 10000)
      const remainder = amount % 10000
      return remainder > 0 ? `${man}만${remainder.toLocaleString()}원` : `${man}만원`
    }
  } else { // 1만원 미만
    return `${amount.toLocaleString()}원`
  }
}

// 값 포맷팅
const formatValue = (value: any, fieldKey: string = ''): string => {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'string' && value === '') return 'empty'
  if (typeof value === 'object') return JSON.stringify(value)
  
  // 이체한도 필드는 한국어 통화 형식으로 표시
  if ((fieldKey === 'transfer_limit_once' || fieldKey === 'transfer_limit_daily') && 
      (typeof value === 'number' || (typeof value === 'string' && /^\d+$/.test(value)))) {
    try {
      const numericValue = typeof value === 'string' ? parseInt(value) : value
      return formatKoreanCurrency(numericValue)
    } catch (error) {
      return String(value)
    }
  }
  
  return String(value)
}

// 디버그 패널 토글
const toggleDebugPanel = () => {
  showDebugPanel.value = !showDebugPanel.value
  if (showDebugPanel.value) {
    addUpdateHistory()
  }
}

// Store 변경 감지하여 히스토리 업데이트
const unwatchCollectedInfo = slotFillingStore.$subscribe((mutation, state) => {
  if (showDebugPanel.value) {
    addUpdateHistory()
  }
})

// 컴포넌트 언마운트 시 구독 해제
import { onUnmounted } from 'vue'
onUnmounted(() => {
  unwatchCollectedInfo()
})
</script>

<style scoped>
.debug-panel {
  position: fixed;
  top: 20px;
  right: 20px;
  width: 600px;
  max-height: 80vh;
  background: #f8f9fa;
  border: 1px solid #dee2e6;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  z-index: 1000;
  overflow: hidden;
  font-family: monospace;
  font-size: 12px;
}

.debug-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 15px;
  background: #343a40;
  color: white;
  border-bottom: 1px solid #dee2e6;
}

.debug-header h3 {
  margin: 0;
  font-size: 14px;
}

.close-btn {
  background: none;
  border: none;
  color: white;
  font-size: 18px;
  cursor: pointer;
  padding: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.2);
  border-radius: 4px;
}

.debug-content {
  max-height: calc(80vh - 50px);
  overflow-y: auto;
  padding: 15px;
}

.debug-section {
  margin-bottom: 20px;
  padding: 10px;
  background: white;
  border-radius: 4px;
  border: 1px solid #e9ecef;
}

.debug-section h4 {
  margin: 0 0 10px 0;
  font-size: 13px;
  color: #495057;
  border-bottom: 1px solid #e9ecef;
  padding-bottom: 5px;
}

.debug-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 3px 0;
  border-bottom: 1px solid #f8f9fa;
}

.debug-item:last-child {
  border-bottom: none;
}

.label {
  font-weight: bold;
  color: #6c757d;
  min-width: 120px;
}

.value {
  color: #495057;
  text-align: right;
}

.fields-table {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.table-header {
  display: grid;
  grid-template-columns: 120px 120px 60px 60px 120px 60px;
  gap: 8px;
  padding: 8px;
  background: #e9ecef;
  font-weight: bold;
  border-radius: 4px;
}

.table-row {
  display: grid;
  grid-template-columns: 120px 120px 60px 60px 120px 60px;
  gap: 8px;
  padding: 6px 8px;
  background: #f8f9fa;
  border-radius: 4px;
  transition: background-color 0.2s;
}

.table-row.completed {
  background: #d4edda;
  border-left: 3px solid #28a745;
}

.table-row:hover {
  background: #e9ecef;
}

.field-key {
  font-weight: bold;
  color: #007bff;
}

.field-value {
  color: #495057;
  word-break: break-all;
}

.json-display {
  background: #f8f9fa;
  padding: 10px;
  border-radius: 4px;
  border: 1px solid #e9ecef;
  font-size: 11px;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
}

.group-item {
  margin-bottom: 10px;
  padding: 8px;
  background: #f8f9fa;
  border-radius: 4px;
}

.group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 5px;
}

.group-name {
  font-weight: bold;
  color: #495057;
}

.group-id {
  color: #6c757d;
  font-size: 11px;
}

.group-fields {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.group-field {
  padding: 2px 6px;
  background: #e9ecef;
  border-radius: 3px;
  font-size: 11px;
  color: #495057;
}

.update-history {
  max-height: 150px;
  overflow-y: auto;
}

.update-item {
  padding: 5px 8px;
  margin-bottom: 5px;
  background: #f8f9fa;
  border-radius: 4px;
  border-left: 3px solid #007bff;
}

.update-timestamp {
  font-weight: bold;
  color: #495057;
  font-size: 11px;
}

.update-summary {
  color: #6c757d;
  font-size: 11px;
  margin-top: 2px;
}

.debug-toggle-btn {
  position: fixed;
  top: 20px;
  right: 20px;
  padding: 8px 12px;
  background: #007bff;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  z-index: 999;
  transition: background-color 0.2s;
}

.debug-toggle-btn:hover {
  background: #0056b3;
}

.debug-toggle-btn.active {
  background: #dc3545;
}

.debug-toggle-btn.active:hover {
  background: #c82333;
}

/* 스크롤바 스타일 */
.debug-content::-webkit-scrollbar,
.json-display::-webkit-scrollbar,
.update-history::-webkit-scrollbar {
  width: 6px;
}

.debug-content::-webkit-scrollbar-track,
.json-display::-webkit-scrollbar-track,
.update-history::-webkit-scrollbar-track {
  background: #f8f9fa;
}

.debug-content::-webkit-scrollbar-thumb,
.json-display::-webkit-scrollbar-thumb,
.update-history::-webkit-scrollbar-thumb {
  background: #6c757d;
  border-radius: 3px;
}

.debug-content::-webkit-scrollbar-thumb:hover,
.json-display::-webkit-scrollbar-thumb:hover,
.update-history::-webkit-scrollbar-thumb:hover {
  background: #495057;
}
</style>