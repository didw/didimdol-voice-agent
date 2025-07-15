import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type { SlotFillingState, SlotFillingUpdate, RequiredField, FieldGroup } from '@/types/slotFilling'

// 디버그 모드 활성화 여부
const DEBUG_MODE = import.meta.env.DEV

export const useSlotFillingStore = defineStore('slotFilling', () => {
  // State
  const productType = ref<string | null>(null)
  const requiredFields = ref<RequiredField[]>([])
  const collectedInfo = ref<Record<string, any>>({})
  const completionStatus = ref<Record<string, boolean>>({})
  const completionRate = ref<number>(0)
  const fieldGroups = ref<FieldGroup[]>([])

  // Getters
  const getState = computed<SlotFillingState>(() => ({
    productType: productType.value,
    requiredFields: requiredFields.value,
    collectedInfo: collectedInfo.value,
    completionStatus: completionStatus.value,
    completionRate: completionRate.value,
    fieldGroups: fieldGroups.value
  }))

  // 그룹별 필드 반환
  const getFieldsByGroup = computed(() => {
    if (!fieldGroups.value || fieldGroups.value.length === 0) {
      // 그룹이 없으면 모든 필드를 하나의 그룹으로
      return [{
        id: 'default',
        name: '정보 수집',
        fields: requiredFields.value
      }]
    }

    return fieldGroups.value.map(group => ({
      ...group,
      fields: requiredFields.value.filter(field => 
        group.fields.includes(field.key)
      )
    }))
  })

  // 필드가 표시되어야 하는지 확인 (의존성 체크)
  const isFieldVisible = (field: RequiredField): boolean => {
    if (!field.dependsOn) return true

    const { field: dependsOnField, value: dependsOnValue } = field.dependsOn
    const currentValue = collectedInfo.value[dependsOnField]

    // 배열인 경우 포함 여부 확인
    if (Array.isArray(dependsOnValue)) {
      return dependsOnValue.includes(currentValue)
    }
    
    // 단일 값인 경우 일치 여부 확인
    return currentValue === dependsOnValue
  }

  // 표시 가능한 필드만 필터링
  const visibleFields = computed(() => 
    requiredFields.value.filter(field => isFieldVisible(field))
  )

  // 표시 가능한 필드 기준 완료율 계산
  const visibleCompletionRate = computed(() => {
    const visible = visibleFields.value
    if (visible.length === 0) return 0

    const completed = visible.filter(field => 
      completionStatus.value[field.key]
    ).length

    return Math.round((completed / visible.length) * 100)
  })

  // Actions
  const updateSlotFilling = (message: SlotFillingUpdate) => {
    // Backend에서 이미 camelCase로 보내주므로 직접 할당
    productType.value = message.productType
    requiredFields.value = message.requiredFields
    collectedInfo.value = { ...message.collectedInfo }
    completionStatus.value = { ...message.completionStatus }
    completionRate.value = message.completionRate
    fieldGroups.value = message.fieldGroups ? [...message.fieldGroups] : []
    
    if (DEBUG_MODE) {
      console.log('[SlotFilling] State updated:', {
        productType: productType.value,
        fieldsCount: requiredFields.value.length,
        collectedCount: Object.keys(collectedInfo.value).length,
        completionRate: completionRate.value
      })
    }
    
    // localStorage에 상태 저장 (선택사항)
    saveToLocalStorage()
  }

  const clearSlotFilling = () => {
    productType.value = null
    requiredFields.value = []
    collectedInfo.value = {}
    completionStatus.value = {}
    completionRate.value = 0
    fieldGroups.value = []
    
    // localStorage 클리어
    clearLocalStorage()
    
    if (DEBUG_MODE) {
      console.log('[SlotFilling] State cleared')
    }
  }

  // 특정 필드 값 업데이트 (로컬 업데이트용)
  const updateFieldValue = (key: string, value: any) => {
    collectedInfo.value[key] = value
    completionStatus.value[key] = value !== null && value !== undefined && value !== ''
    
    // 완료율 재계산
    const total = requiredFields.value.length
    const completed = Object.values(completionStatus.value).filter(Boolean).length
    completionRate.value = total > 0 ? Math.round((completed / total) * 100) : 0
  }

  // 필드 값 제거
  const removeFieldValue = (key: string) => {
    delete collectedInfo.value[key]
    completionStatus.value[key] = false
    
    // 완료율 재계산
    const total = requiredFields.value.length
    const completed = Object.values(completionStatus.value).filter(Boolean).length
    completionRate.value = total > 0 ? Math.round((completed / total) * 100) : 0
  }
  
  // localStorage 관련 함수들
  const STORAGE_KEY = 'didimdol_slot_filling'
  
  const saveToLocalStorage = () => {
    try {
      const state: SlotFillingState = {
        productType: productType.value,
        requiredFields: requiredFields.value,
        collectedInfo: collectedInfo.value,
        completionStatus: completionStatus.value,
        completionRate: completionRate.value,
        fieldGroups: fieldGroups.value
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
    } catch (error) {
      console.error('[SlotFilling] Failed to save to localStorage:', error)
    }
  }
  
  const loadFromLocalStorage = () => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        const state: SlotFillingState = JSON.parse(stored)
        productType.value = state.productType
        requiredFields.value = state.requiredFields
        collectedInfo.value = state.collectedInfo
        completionStatus.value = state.completionStatus
        completionRate.value = state.completionRate
        fieldGroups.value = state.fieldGroups || []
        
        if (DEBUG_MODE) {
          console.log('[SlotFilling] Loaded from localStorage:', state)
        }
      }
    } catch (error) {
      console.error('[SlotFilling] Failed to load from localStorage:', error)
    }
  }
  
  const clearLocalStorage = () => {
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch (error) {
      console.error('[SlotFilling] Failed to clear localStorage:', error)
    }
  }
  
  // 초기화 시 localStorage에서 로드 (선택사항)
  // loadFromLocalStorage()
  
  // 특정 필드 변경 감지 예시
  if (DEBUG_MODE) {
    watch(collectedInfo, (newInfo, oldInfo) => {
      const changedKeys = Object.keys(newInfo).filter(
        key => newInfo[key] !== oldInfo[key]
      )
      if (changedKeys.length > 0) {
        console.log('[SlotFilling] Fields changed:', changedKeys)
      }
    }, { deep: true })
  }

  return {
    // State
    productType,
    requiredFields,
    collectedInfo,
    completionStatus,
    completionRate,
    fieldGroups,

    // Getters
    getState,
    getFieldsByGroup,
    visibleFields,
    visibleCompletionRate,

    // Actions
    updateSlotFilling,
    clearSlotFilling,
    updateFieldValue,
    removeFieldValue,
    isFieldVisible,
    
    // localStorage 관련 (선택적 사용)
    saveToLocalStorage,
    loadFromLocalStorage,
    clearLocalStorage
  }
})