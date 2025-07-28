import { defineStore } from 'pinia'
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import type { SlotFillingState, SlotFillingUpdate, SmartField, FieldGroup, CurrentStageInfo } from '@/types/slotFilling'

// 디버그 모드 활성화 여부
const DEBUG_MODE = import.meta.env.DEV

// 성능 최적화 상수
const UPDATE_DEBOUNCE_MS = 100 // 업데이트 디바운싱
const MAX_FIELD_CACHE_SIZE = 500 // 필드 캐시 최대 크기 (줄임)
const CACHE_CLEANUP_INTERVAL = 5 * 60 * 1000 // 5분마다 캐시 정리

export const useSlotFillingStore = defineStore('slotFilling', () => {
  // State (새로운 구조)
  const productType = ref<string | null>(null)
  const requiredFields = ref<SmartField[]>([])
  const collectedInfo = ref<Record<string, any>>({})
  const completionStatus = ref<Record<string, boolean>>({})
  const completionRate = ref<number>(0)
  const totalRequiredCount = ref<number>(0)  // 전체 필수 필드 수
  const completedRequiredCount = ref<number>(0)  // 완료된 필수 필드 수
  const fieldGroups = ref<FieldGroup[]>([])
  const currentStage = ref<CurrentStageInfo | null>(null)
  const visibleFields = ref<SmartField[]>([])  // Backend에서 계산된 표시 필드
  const fieldsByDepth = ref<Record<number, SmartField[]>>({})
  const displayLabels = ref<Record<string, string>>({})
  
  // 성능 최적화 관련 상태
  const lastUpdateHash = ref<string>('')
  const updateDebounceTimer = ref<number | null>(null)
  const fieldVisibilityCache = ref<Map<string, boolean>>(new Map())
  const cacheCleanupInterval = ref<number | null>(null)
  
  // 수정 모드 관련 상태
  const modificationMode = ref<boolean>(false)
  const selectedFieldForModification = ref<string | null>(null)
  const modificationPending = ref<boolean>(false)
  
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

  // Getters (새로운 구조)
  const getState = computed<SlotFillingState>(() => ({
    productType: productType.value,
    requiredFields: requiredFields.value,
    collectedInfo: collectedInfo.value,
    completionStatus: completionStatus.value,
    completionRate: completionRate.value,
    fieldGroups: fieldGroups.value,
    currentStage: currentStage.value || undefined,
    visibleFields: visibleFields.value,
    fieldsByDepth: fieldsByDepth.value
  }))

  // 계층적 필드 그룹 (Backend에서 계산된 visibleFields 사용)
  const hierarchicalFieldGroups = computed(() => {
    if (!fieldGroups.value || fieldGroups.value.length === 0) {
      // 그룹이 없으면 깊이별로 자동 그룹화
      return [{
        id: 'default',
        name: '정보 수집',
        fields: visibleFields.value
      }]
    }

    // currentStage.visibleGroups가 있으면 해당 그룹만 필터링
    // 단, 이미 수집된 정보가 있는 그룹은 항상 표시
    let groupsToShow = fieldGroups.value
    if (currentStage.value?.visibleGroups?.length) {
      console.log('[SlotFillingStore] Current stage visible groups:', currentStage.value.visibleGroups)
      console.log('[SlotFillingStore] All field groups:', fieldGroups.value.map(g => ({ id: g.id, fields: g.fields })))
      console.log('[SlotFillingStore] Collected info keys:', Object.keys(collectedInfo.value))
      
      groupsToShow = fieldGroups.value.filter(group => {
        // 현재 단계의 visible 그룹인지 확인
        const isCurrentStageGroup = currentStage.value!.visibleGroups.includes(group.id)
        
        // 해당 그룹에 이미 수집된 정보가 있는지 확인
        // visibleFields를 통해 실제 표시되는 필드들로 확인
        const hasCollectedData = visibleFields.value.some(field => {
          // 이 필드가 현재 그룹에 속하는지 확인
          if (!group.fields.includes(field.key)) return false
          
          const hasData = collectedInfo.value[field.key] !== undefined && 
                         collectedInfo.value[field.key] !== null &&
                         collectedInfo.value[field.key] !== ''
          if (hasData) {
            console.log(`[SlotFillingStore] Group ${group.id} has collected data: ${field.key} = ${collectedInfo.value[field.key]}`)
          }
          return hasData
        })
        
        // boolean 필드 그룹의 특별 처리: 값이 있으면(true든 false든) 완료된 것으로 간주
        let keepVisible = false
        
        // final_summary 단계에서는 모든 visible_groups를 표시
        const isFinalSummary = currentStage.value?.stageId === 'final_summary'
        if (isFinalSummary && currentStage.value?.visibleGroups?.includes(group.id)) {
          keepVisible = true
          console.log(`[SlotFillingStore] final_summary: Keeping group ${group.id} visible (in visible_groups)`)
        }
        
        // internet_banking 그룹: boolean 값이 있거나 관련 필드가 완료되었으면 표시
        if (group.id === 'internet_banking') {
          const useInternetBanking = collectedInfo.value['use_internet_banking']
          const isCompleted = completionStatus.value['use_internet_banking']
          
          if (useInternetBanking !== undefined || isCompleted) {
            keepVisible = true
            console.log(`[SlotFillingStore] Keeping internet_banking group visible: value=${useInternetBanking}, completed=${isCompleted}`)
          }
        }
        
        // check_card 그룹: boolean 값이 있거나 관련 필드가 완료되었으면 표시
        if (group.id === 'check_card') {
          const useCheckCard = collectedInfo.value['use_check_card']
          const isCompleted = completionStatus.value['use_check_card']
          
          if (useCheckCard !== undefined || isCompleted) {
            keepVisible = true
            console.log(`[SlotFillingStore] Keeping check_card group visible: value=${useCheckCard}, completed=${isCompleted}`)
          }
        }
        
        const shouldShow = isCurrentStageGroup || hasCollectedData || keepVisible
        console.log(`[SlotFillingStore] Group ${group.id}: isCurrentStage=${isCurrentStageGroup}, hasData=${hasCollectedData}, keepVisible=${keepVisible}, show=${shouldShow}`)
        
        // 현재 단계 그룹이거나 이미 수집된 정보가 있거나 특별히 유지해야 하면 표시
        return shouldShow
      })
    }

    return groupsToShow.map(group => ({
      ...group,
      fields: visibleFields.value.filter(field => 
        group.fields.includes(field.key)
      )
    }))
  })

  // 깊이별 필드 그룹화
  const computeFieldsByDepth = () => {
    const byDepth: Record<number, SmartField[]> = {}
    
    visibleFields.value.forEach(field => {
      const depth = field.depth || 0
      if (!byDepth[depth]) {
        byDepth[depth] = []
      }
      byDepth[depth].push(field)
    })
    
    fieldsByDepth.value = byDepth
  }

  // 최대 깊이 계산
  const maxDepth = computed(() => {
    if (visibleFields.value.length === 0) return 0
    return Math.max(...visibleFields.value.map(f => f.depth || 0))
  })

  // 표시 가능한 필드 기준 완료율 계산 (Backend에서 계산된 값 사용)
  const visibleCompletionRate = computed(() => {
    if (visibleFields.value.length === 0) return completionRate.value

    const completed = visibleFields.value.filter(field => 
      completionStatus.value[field.key]
    ).length

    return Math.round((completed / visibleFields.value.length) * 100)
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
    console.log('🔥🔥🔥 [SlotFilling] UPDATE SLOT FILLING CALLED!')
    console.log('[SlotFilling] ===== UPDATE SLOT FILLING START =====')
    console.log('[SlotFilling] Received message:', message)
    console.log('[SlotFilling] Message type:', message.type)
    console.log('[SlotFilling] Product type:', message.productType)
    console.log('[SlotFilling] Required fields:', message.requiredFields)
    console.log('[SlotFilling] Collected info:', message.collectedInfo)
    console.log('[SlotFilling] Completion status:', message.completionStatus)
    console.log('[SlotFilling] Field groups:', message.fieldGroups)
    console.log('[SlotFilling] Current stage:', message.currentStage)
    
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
      totalRequiredCount.value = message.totalRequiredCount || 0
      completedRequiredCount.value = message.completedRequiredCount || 0
      fieldGroups.value = message.fieldGroups ? [...message.fieldGroups] : []
      currentStage.value = message.currentStage || null
      displayLabels.value = message.displayLabels || {}
      
      // Backend에서 계산된 표시 필드 사용 (모든 필드가 이제 depth 정보를 가짐)
      visibleFields.value = message.requiredFields || []
      
      // 깊이별 필드 그룹화
      computeFieldsByDepth()
      
      if (DEBUG_MODE) {
        console.log('[SlotFilling] Visible fields updated:', visibleFields.value.length)
        console.log('[SlotFilling] Fields by depth:', fieldsByDepth.value)
        
        // 중요한 필드 상태만 로깅
        const importantFields = ['use_check_card', 'use_internet_banking', 'confirm_personal_info']
        const importantStatus = importantFields.reduce((acc, key) => {
          if (collectedInfo.value[key] !== undefined) {
            acc[key] = collectedInfo.value[key]
          }
          return acc
        }, {} as Record<string, any>)
        
        if (Object.keys(importantStatus).length > 0) {
          console.log('[SlotFilling] Important fields status:', importantStatus)
        }
      }
      
      if (DEBUG_MODE) {
        // 업데이트 후 상태 요약
        console.log('[SlotFilling] Updated state summary:', {
          productType: productType.value,
          fieldsCount: requiredFields.value.length,
          collectedCount: Object.keys(collectedInfo.value).length,
          completionRate: completionRate.value,
          currentStage: currentStage.value
        })
        
        // 완료되지 않은 필드만 로깅
        const incompleteFields = requiredFields.value.filter(field => 
          !completionStatus.value[field.key]
        )
        if (incompleteFields.length > 0) {
          console.log('[SlotFilling] Incomplete fields:', incompleteFields.map(f => f.key))
        }
      }
      
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
      totalRequiredCount.value = 0
      completedRequiredCount.value = 0
      fieldGroups.value = []
      currentStage.value = null
      visibleFields.value = []
      fieldsByDepth.value = {}
      
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
  
  // 필드 수정 요청
  const requestFieldModification = async (fieldKey: string, newValue: any) => {
    if (DEBUG_MODE) {
      console.log('[SlotFilling] Requesting field modification:', { fieldKey, newValue })
    }
    
    modificationPending.value = true
    selectedFieldForModification.value = fieldKey
    
    try {
      // chatStore를 통해 WebSocket으로 수정 요청 전송
      // 실제 구현은 chatStore에서 처리
      const chatStore = await import('@/stores/chatStore').then(m => m.useChatStore())
      await chatStore.sendFieldModificationRequest(fieldKey, newValue, collectedInfo.value[fieldKey])
      
      return true
    } catch (error) {
      console.error('[SlotFilling] Failed to send modification request:', error)
      modificationPending.value = false
      selectedFieldForModification.value = null
      return false
    }
  }
  
  // 수정 응답 처리
  const handleModificationResponse = (response: any) => {
    if (DEBUG_MODE) {
      console.log('[SlotFilling] Handling modification response:', response)
    }
    
    modificationPending.value = false
    
    if (response.success && response.field === selectedFieldForModification.value) {
      // 성공적으로 수정된 경우 로컬 상태 업데이트
      updateFieldValue(response.field, response.newValue)
      selectedFieldForModification.value = null
      
      if (DEBUG_MODE) {
        console.log('[SlotFilling] Field modification successful:', response.field)
      }
    } else if (!response.success) {
      console.error('[SlotFilling] Field modification failed:', response.error)
      selectedFieldForModification.value = null
    }
  }
  
  // 수정 모드 토글
  const toggleModificationMode = () => {
    modificationMode.value = !modificationMode.value
    if (!modificationMode.value) {
      selectedFieldForModification.value = null
    }
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
        fieldGroups: fieldGroups.value,
        currentStage: currentStage.value || undefined
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
        currentStage.value = state.currentStage || null
        
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
    totalRequiredCount,
    completedRequiredCount,
    fieldGroups,
    currentStage,
    visibleFields,
    fieldsByDepth,
    displayLabels,
    modificationMode,
    selectedFieldForModification,
    modificationPending,

    // Getters
    getState,
    hierarchicalFieldGroups,
    visibleCompletionRate,
    maxDepth,

    // Actions
    updateSlotFilling,
    clearSlotFilling,
    updateFieldValue,
    removeFieldValue,
    computeFieldsByDepth,
    requestFieldModification,
    handleModificationResponse,
    toggleModificationMode,
    
    // localStorage 관련 (선택적 사용)
    saveToLocalStorage,
    loadFromLocalStorage,
    clearLocalStorage,
    
    // 정리 함수
    cleanup
  }
})