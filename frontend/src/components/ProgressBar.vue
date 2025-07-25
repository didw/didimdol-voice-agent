<template>
  <div class="progress-section">
    <div class="progress-header">
      <h3>정보 수집 현황</h3>
      <span class="percentage">{{ completionRate }}%</span>
    </div>
    <div class="progress-bar-container">
      <div 
        class="progress-bar-fill" 
        :style="{ width: completionRate + '%' }"
        :class="{ 
          'in-progress': completionRate > 0 && completionRate < 100,
          'complete': completionRate === 100 
        }"
      >
        <div class="progress-animation"></div>
      </div>
    </div>
    <p class="progress-detail">
      수집 완료: {{ completedCount }}개 / 전체: {{ totalCount }}개
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useSlotFillingStore } from '@/stores/slotFillingStore'

const slotFillingStore = useSlotFillingStore()

// 진행률 관련 데이터
const completionRate = computed(() => {
  // 조건부 필드를 고려한 완료율 계산
  if (totalCount.value === 0) return 0
  const rate = (completedCount.value / totalCount.value) * 100
  return Math.round(rate)  // 반올림
})
const completedCount = computed(() => {
  // 백엔드에서 계산한 완료된 필수 필드 수 사용
  let count = slotFillingStore.completedRequiredCount
  
  // card_receive_method가 "즉시수령"이고 card_delivery_location이 완료로 표시되어 있다면 제외
  const collectedInfo = slotFillingStore.collectedInfo
  const completionStatus = slotFillingStore.completionStatus
  if (collectedInfo?.card_receive_method === '즉시수령' && 
      completionStatus?.card_delivery_location === true) {
    console.log('[ProgressBar] 즉시수령 selected - adjusting completed count')
    count = Math.max(0, count - 1)
  }
  
  return count
})
const totalCount = computed(() => {
  // 백엔드에서 계산한 전체 필수 필드 수 사용
  let count = slotFillingStore.totalRequiredCount || 0
  
  // card_receive_method가 "즉시수령"일 때 card_delivery_location 제외
  const collectedInfo = slotFillingStore.collectedInfo
  if (collectedInfo?.card_receive_method === '즉시수령') {
    // card_delivery_location이 아직 포함되어 있다면 1개 감소
    const hasDeliveryField = slotFillingStore.visibleFields.some(
      field => field.key === 'card_delivery_location'
    )
    if (hasDeliveryField) {
      console.log('[ProgressBar] 즉시수령 selected - adjusting total count')
      count = Math.max(0, count - 1)
    }
  }
  
  return count || 19  // 기본값 19
})
</script>

<style scoped>
.progress-section {
  padding: 1.5rem;
  background-color: var(--color-background-soft);
  border-radius: 0.75rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  margin-bottom: 1.5rem;
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.progress-header h3 {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--color-heading);
  margin: 0;
}

.percentage {
  font-size: 1.5rem;
  font-weight: bold;
  color: #4caf50;
}

.progress-bar-container {
  width: 100%;
  height: 24px;
  background-color: #f0f0f0;
  border-radius: 12px;
  overflow: hidden;
  position: relative;
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.1);
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #4caf50, #45a049);
  transition: width 0.3s ease;
  position: relative;
  box-shadow: 0 2px 4px rgba(76, 175, 80, 0.3);
}

.progress-bar-fill.in-progress {
  background: linear-gradient(90deg, #4caf50, #45a049);
}

.progress-bar-fill.complete {
  background: linear-gradient(90deg, #2196f3, #1976d2);
}

.progress-animation {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(255, 255, 255, 0.3),
    transparent
  );
  animation: progress-shine 2s infinite;
}

@keyframes progress-shine {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

.progress-detail {
  margin-top: 0.75rem;
  text-align: center;
  font-size: 0.875rem;
  color: var(--color-text-secondary);
}

/* 반응형 디자인 */
@media (max-width: 768px) {
  .progress-section {
    padding: 1rem;
  }
  
  .progress-header h3 {
    font-size: 1rem;
  }
  
  .percentage {
    font-size: 1.25rem;
  }
  
  .progress-bar-container {
    height: 20px;
  }
}

/* 다크 모드 지원 */
@media (prefers-color-scheme: dark) {
  .progress-bar-container {
    background-color: #333;
  }
  
  .progress-detail {
    color: #aaa;
  }
}
</style>