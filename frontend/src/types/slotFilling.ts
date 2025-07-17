// SlotFilling 관련 타입 정의 (새로운 구조)
export interface SmartField {
  key: string
  displayName: string
  type: 'boolean' | 'text' | 'choice' | 'number'
  required: boolean
  choices?: string[]
  unit?: string
  description?: string
  showWhen?: string  // 새로운 조건 표현식
  parentField?: string  // 부모 필드
  depth?: number  // 계층 깊이
  default?: any  // 기본값
}

export interface FieldGroup {
  id: string
  name: string
  fields: string[]
}

export interface CurrentStageInfo {
  stageId: string
  visibleGroups: string[]
}

export interface SlotFillingState {
  productType: string | null
  requiredFields: SmartField[]  // 새로운 타입 사용
  collectedInfo: Record<string, any>
  completionStatus: Record<string, boolean>
  completionRate: number
  fieldGroups?: FieldGroup[]
  currentStage?: CurrentStageInfo
  visibleFields?: SmartField[]  // 표시되는 필드들
  fieldsByDepth?: Record<number, SmartField[]>  // 깊이별 필드
}

export interface SlotFillingUpdate {
  type: 'slot_filling_update'
  productType: string | null
  requiredFields: SmartField[]  // 새로운 타입 사용
  collectedInfo: Record<string, any>
  completionStatus: Record<string, boolean>
  completionRate: number
  fieldGroups?: FieldGroup[]
  currentStage?: CurrentStageInfo
}

// 하위 호환성을 위한 별칭
export type RequiredField = SmartField