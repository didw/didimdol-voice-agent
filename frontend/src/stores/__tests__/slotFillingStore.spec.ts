import { setActivePinia, createPinia } from 'pinia'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useSlotFillingStore } from '../slotFillingStore'
import type { SlotFillingUpdate } from '@/types/slotFilling'

describe('SlotFillingStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('updateSlotFilling', () => {
    it('should update slot filling state correctly', () => {
      const store = useSlotFillingStore()
      
      const mockUpdate: SlotFillingUpdate = {
        type: 'slot_filling_update',
        productType: '동시신규',
        requiredFields: [
          { 
            key: 'name', 
            displayName: '이름', 
            type: 'text', 
            required: true 
          },
          { 
            key: 'use_internet_banking', 
            displayName: '인터넷뱅킹 신청', 
            type: 'boolean', 
            required: true 
          }
        ],
        collectedInfo: { name: '홍길동' },
        completionStatus: { name: true, use_internet_banking: false },
        completionRate: 50
      }
      
      store.updateSlotFilling(mockUpdate)
      
      expect(store.productType).toBe('동시신규')
      expect(store.requiredFields).toHaveLength(2)
      expect(store.collectedInfo.name).toBe('홍길동')
      expect(store.completionRate).toBe(50)
    })

    it('should skip duplicate updates', () => {
      const store = useSlotFillingStore()
      const consoleSpy = vi.spyOn(console, 'log')
      
      const mockUpdate: SlotFillingUpdate = {
        type: 'slot_filling_update',
        productType: '동시신규',
        requiredFields: [],
        collectedInfo: { test: 'value' },
        completionStatus: {},
        completionRate: 0
      }
      
      // 첫 번째 업데이트
      store.updateSlotFilling(mockUpdate)
      
      // 동일한 업데이트 (건너뛰어야 함)
      store.updateSlotFilling(mockUpdate)
      
      expect(consoleSpy).toHaveBeenCalledWith('[SlotFilling] Skipping duplicate update')
    })
  })

  describe('Field Modification', () => {
    it('should handle field modification request', async () => {
      const store = useSlotFillingStore()
      
      // Mock chatStore import
      vi.mock('@/stores/chatStore', () => ({
        useChatStore: () => ({
          sendFieldModificationRequest: vi.fn().mockResolvedValue(true)
        })
      }))
      
      const result = await store.requestFieldModification('name', '김철수')
      
      expect(result).toBe(true)
      expect(store.selectedFieldForModification).toBe('name')
      expect(store.modificationPending).toBe(true)
    })

    it('should handle modification response', () => {
      const store = useSlotFillingStore()
      
      // 초기 설정
      store.requiredFields = [
        { key: 'name', displayName: '이름', type: 'text', required: true }
      ]
      store.collectedInfo = { name: '홍길동' }
      store.selectedFieldForModification = 'name'
      store.modificationPending = true
      
      // 성공 응답 처리
      store.handleModificationResponse({
        success: true,
        field: 'name',
        newValue: '김철수'
      })
      
      expect(store.collectedInfo.name).toBe('김철수')
      expect(store.completionStatus.name).toBe(true)
      expect(store.modificationPending).toBe(false)
      expect(store.selectedFieldForModification).toBeNull()
    })

    it('should toggle modification mode', () => {
      const store = useSlotFillingStore()
      
      expect(store.modificationMode).toBe(false)
      
      store.toggleModificationMode()
      expect(store.modificationMode).toBe(true)
      
      store.selectedFieldForModification = 'test'
      store.toggleModificationMode()
      expect(store.modificationMode).toBe(false)
      expect(store.selectedFieldForModification).toBeNull()
    })
  })

  describe('Progress Calculation', () => {
    it('should calculate visible completion rate correctly', () => {
      const store = useSlotFillingStore()
      
      store.visibleFields = [
        { key: 'field1', displayName: 'Field 1', type: 'text', required: true },
        { key: 'field2', displayName: 'Field 2', type: 'text', required: true },
        { key: 'field3', displayName: 'Field 3', type: 'text', required: true }
      ]
      
      store.completionStatus = {
        field1: true,
        field2: false,
        field3: true
      }
      
      expect(store.visibleCompletionRate).toBe(67) // 2/3 = 66.67 rounded to 67
    })
  })

  describe('Field Value Management', () => {
    it('should update field value and completion status', () => {
      const store = useSlotFillingStore()
      
      store.requiredFields = [
        { key: 'email', displayName: '이메일', type: 'text', required: true }
      ]
      
      store.updateFieldValue('email', 'test@example.com')
      
      expect(store.collectedInfo.email).toBe('test@example.com')
      expect(store.completionStatus.email).toBe(true)
    })

    it('should remove field value', () => {
      const store = useSlotFillingStore()
      
      store.collectedInfo = { email: 'test@example.com' }
      store.completionStatus = { email: true }
      store.requiredFields = [
        { key: 'email', displayName: '이메일', type: 'text', required: true }
      ]
      
      store.removeFieldValue('email')
      
      expect(store.collectedInfo.email).toBeUndefined()
      expect(store.completionStatus.email).toBe(false)
    })
  })

  describe('Clear State', () => {
    it('should clear all state', () => {
      const store = useSlotFillingStore()
      
      // 상태 설정
      store.productType = '동시신규'
      store.requiredFields = [{ key: 'test', displayName: 'Test', type: 'text', required: true }]
      store.collectedInfo = { test: 'value' }
      store.completionRate = 50
      
      store.clearSlotFilling()
      
      expect(store.productType).toBeNull()
      expect(store.requiredFields).toHaveLength(0)
      expect(store.collectedInfo).toEqual({})
      expect(store.completionRate).toBe(0)
    })
  })
})