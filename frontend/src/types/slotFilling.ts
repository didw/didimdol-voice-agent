// SlotFilling 관련 타입 정의
export interface RequiredField {
  key: string
  displayName: string
  type: 'boolean' | 'text' | 'choice' | 'number'
  required: boolean
  choices?: string[]
  unit?: string
  description?: string
  dependsOn?: {
    field: string
    value: any
  }
}

export interface FieldGroup {
  id: string
  name: string
  fields: string[]
}

export interface SlotFillingState {
  productType: string | null
  requiredFields: RequiredField[]
  collectedInfo: Record<string, any>
  completionStatus: Record<string, boolean>
  completionRate: number
  fieldGroups?: FieldGroup[]
}

export interface SlotFillingUpdate {
  type: 'slot_filling_update'
  productType: string | null
  requiredFields: RequiredField[]
  collectedInfo: Record<string, any>
  completionStatus: Record<string, boolean>
  completionRate: number
  fieldGroups?: FieldGroup[]
}