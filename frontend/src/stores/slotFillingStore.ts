import { defineStore } from 'pinia'
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import type { SlotFillingState, SlotFillingUpdate, RequiredField, FieldGroup } from '@/types/slotFilling'

// 디버그 모드 활성화 여부
const DEBUG_MODE = import.meta.env.DEV

// 성능 최적화 상수
const UPDATE_DEBOUNCE_MS = 100 // 업데이트 디바운싱
const MAX_FIELD_CACHE_SIZE = 500 // 필드 캐시 최대 크기 (줄임)
const CACHE_CLEANUP_INTERVAL = 5 * 60 * 1000 // 5분마다 캐시 정리

export const useSlotFillingStore = defineStore('slotFilling', () => {
  // State
  const productType = ref<string | null>(null)
  const requiredFields = ref<RequiredField[]>([])
  const collectedInfo = ref<Record<string, any>>({})
  const completionStatus = ref<Record<string, boolean>>({})
  const completionRate = ref<number>(0)
  const fieldGroups = ref<FieldGroup[]>([])
  
  // 성능 최적화 관련 상태
  const lastUpdateHash = ref<string>('')
  const updateDebounceTimer = ref<number | null>(null)
  const fieldVisibilityCache = ref<Map<string, boolean>>(new Map())
  const cacheCleanupInterval = ref<number | null>(null)
  
  // 메모리 누수 방지를 위한 정리 함수
  const cleanup = () => {
    if (updateDebounceTimer.value) {
      clearTimeout(updateDebounceTimer.value)
      updateDebounceTimer.value = null
    }
    if (cacheCleanupInterval.value) {
      clearInterval(cacheCleanupInterval.value)
      cacheCleanupInterval.value = null
    }
    fieldVisibilityCache.value.clear()
  }

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

  // 필드가 표시되어야 하는지 확인 (의존성 체크 + 캐시)
  const isFieldVisible = (field: RequiredField): boolean => {
    if (!field.dependsOn) return true

    try {
      const { field: dependsOnField, value: dependsOnValue } = field.dependsOn
      const currentValue = collectedInfo.value[dependsOnField]

      // 간단한 캐시 키 생성 (JSON.stringify 대신 문자열 조합)
      const cacheKey = `${field.key}:${dependsOnField}:${currentValue}:${Array.isArray(dependsOnValue) ? dependsOnValue.join(',') : dependsOnValue}`
      
      // 캐시에서 확인
      if (fieldVisibilityCache.value.has(cacheKey)) {
        return fieldVisibilityCache.value.get(cacheKey)!
      }

      let isVisible: boolean
      
      // 배열인 경우 포함 여부 확인
      if (Array.isArray(dependsOnValue)) {
        isVisible = dependsOnValue.includes(currentValue)
      } else {
        // 단일 값인 경우 일치 여부 확인
        isVisible = currentValue === dependsOnValue
      }
      
      // 캐시에 저장 (LRU 방식으로 개선)
      if (fieldVisibilityCache.value.size >= MAX_FIELD_CACHE_SIZE) {
        // 가장 오래된 항목 제거
        const firstKey = fieldVisibilityCache.value.keys().next().value
        if (firstKey) {
          fieldVisibilityCache.value.delete(firstKey)
        }
      }
      fieldVisibilityCache.value.set(cacheKey, isVisible)
      
      return isVisible
    } catch (error) {
      console.error('[SlotFilling] Error in isFieldVisible:', error)
      return true // 에러 시 기본적으로 표시
    }
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

  // 메시지 해시 계산 (중복 업데이트 방지용)
  const calculateUpdateHash = (message: SlotFillingUpdate): string => {
    const hashData = {
      productType: message.productType,
      collectedInfo: message.collectedInfo,
      completionStatus: message.completionStatus,
      completionRate: message.completionRate
    }
    return JSON.stringify(hashData)
  }

  // Actions
  const updateSlotFilling = (message: SlotFillingUpdate) => {
    // DEBUG: 업데이트 시작 로그
    console.log('[SlotFilling] ===== UPDATE SLOT FILLING START =====')
    console.log('[SlotFilling] Received message:', message)
    console.log('[SlotFilling] Message type:', message.type)
    console.log('[SlotFilling] Product type:', message.productType)
    console.log('[SlotFilling] Required fields:', message.requiredFields)
    console.log('[SlotFilling] Collected info:', message.collectedInfo)
    console.log('[SlotFilling] Completion status:', message.completionStatus)
    console.log('[SlotFilling] Field groups:', message.fieldGroups)
    
    // 중복 업데이트 방지
    const messageHash = calculateUpdateHash(message)
    console.log('[SlotFilling] Message hash:', messageHash)
    console.log('[SlotFilling] Last update hash:', lastUpdateHash.value)
    
    if (lastUpdateHash.value === messageHash) {
      console.log('[SlotFilling] Skipping duplicate update')
      return
    }
    lastUpdateHash.value = messageHash

    // 디바운싱 처리
    if (updateDebounceTimer.value) {
      clearTimeout(updateDebounceTimer.value)
      console.log('[SlotFilling] Cleared previous debounce timer')
    }

    updateDebounceTimer.value = setTimeout(() => {
      console.log('[SlotFilling] Executing debounced update')
      
      // 이전 상태 로그
      console.log('[SlotFilling] Previous state:', {
        productType: productType.value,
        fieldsCount: requiredFields.value.length,
        collectedCount: Object.keys(collectedInfo.value).length,
        completionRate: completionRate.value
      })
      
      // 캐시 클리어 (의존성이 변경될 수 있음)
      fieldVisibilityCache.value.clear()
      
      // Backend에서 이미 camelCase로 보내주므로 직접 할당
      productType.value = message.productType
      requiredFields.value = message.requiredFields || []
      collectedInfo.value = { ...message.collectedInfo }
      completionStatus.value = { ...message.completionStatus }
      completionRate.value = message.completionRate
      fieldGroups.value = message.fieldGroups ? [...message.fieldGroups] : []
      
      // 업데이트 후 상태 로그
      console.log('[SlotFilling] Updated state:', {
        productType: productType.value,
        fieldsCount: requiredFields.value.length,
        collectedCount: Object.keys(collectedInfo.value).length,
        completionRate: completionRate.value,
        fieldGroups: fieldGroups.value
      })
      
      // 필드별 상세 정보
      requiredFields.value.forEach(field => {
        const value = collectedInfo.value[field.key]
        const completed = completionStatus.value[field.key]
        console.log(`[SlotFilling] Field '${field.key}': ${value} (completed: ${completed})`)
      })
      
      // localStorage에 상태 저장 (선택사항)
      nextTick(() => {
        saveToLocalStorage()
      })
      
      updateDebounceTimer.value = null
      console.log('[SlotFilling] ===== UPDATE SLOT FILLING END =====')
    }, UPDATE_DEBOUNCE_MS)
  }

  const clearSlotFilling = () => {
    try {
      // 디바운스 타이머 클리어
      if (updateDebounceTimer.value) {
        clearTimeout(updateDebounceTimer.value)
        updateDebounceTimer.value = null
      }
      
      // 캐시 클리어
      fieldVisibilityCache.value.clear()
      lastUpdateHash.value = ''
      
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
    } catch (error) {
      console.error('[SlotFilling] Error clearing state:', error)
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
      
      // 크기 제한 (5MB)
      const stateStr = JSON.stringify(state)
      if (stateStr.length > 5 * 1024 * 1024) {
        console.warn('[SlotFilling] State too large for localStorage, skipping save')
        return
      }
      
      localStorage.setItem(STORAGE_KEY, stateStr)
    } catch (error) {
      if (error instanceof DOMException && error.code === 22) {
        console.warn('[SlotFilling] localStorage quota exceeded, clearing old data')
        clearLocalStorage()
      } else {
        console.error('[SlotFilling] Failed to save to localStorage:', error)
      }
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
  
  // 캐시 정리 간격 설정
  cacheCleanupInterval.value = setInterval(() => {
    if (fieldVisibilityCache.value.size > MAX_FIELD_CACHE_SIZE / 2) {
      if (DEBUG_MODE) {
        console.log('[SlotFilling] Cleaning up cache:', fieldVisibilityCache.value.size)
      }
      fieldVisibilityCache.value.clear()
    }
  }, CACHE_CLEANUP_INTERVAL)
  
  // 특정 필드 변경 감지 예시
  if (DEBUG_MODE) {
    watch(collectedInfo, (newInfo, oldInfo) => {
      if (oldInfo) {
        const changedKeys = Object.keys(newInfo).filter(
          key => newInfo[key] !== oldInfo[key]
        )
        if (changedKeys.length > 0) {
          console.log('[SlotFilling] Fields changed:', changedKeys)
        }
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
    clearLocalStorage,
    
    // 정리 함수
    cleanup
  }
})