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
  currentStageGroups?: string[]  // 현재 단계의 그룹만
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
  totalRequiredCount?: number  // 전체 필수 필드 수
  completedRequiredCount?: number  // 완료된 필수 필드 수
  fieldGroups?: FieldGroup[]
  currentStage?: CurrentStageInfo
  displayLabels?: Record<string, string>  // 시나리오의 표시 레이블
}

// 하위 호환성을 위한 별칭
export type RequiredField = SmartField

// WebSocket Message Types
export enum SlotFillingMessageType {
  UPDATE = 'slot_filling_update',
  MODIFICATION_REQUEST = 'field_modification_request',
  MODIFICATION_RESPONSE = 'field_modification_response',
  STAGE_CHANGED = 'stage_changed'
}

export interface FieldModificationRequest {
  type: 'field_modification_request'
  field: string
  newValue: any
  currentValue?: any
}

export interface FieldModificationResponse {
  type: 'field_modification_response'
  success: boolean
  field: string
  newValue?: any
  error?: string
}

export interface SlotFillingDebugHistory {
  timestamp: Date
  data: SlotFillingUpdate
}