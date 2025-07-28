// Stage Response 관련 타입 정의

export type ResponseType = 'narrative' | 'bullet' | 'boolean'

export interface Choice {
  value?: string
  label: string
  key?: string
  default?: boolean
}

export interface ChoiceGroup {
  title: string
  items: Choice[]
}

export interface StageResponseMessage {
  type: 'stage_response'
  stageId: string
  responseType: ResponseType
  prompt: string
  choices?: Choice[]
  choiceGroups?: ChoiceGroup[]
  defaultChoice?: string
  skippable: boolean
  modifiableFields?: string[]
}

export interface UserChoiceMessage {
  type: 'user_choice_selection'
  stageId: string
  selectedChoice: string
}

export interface UserBooleanMessage {
  type: 'user_boolean_selection'
  stageId: string
  booleanSelections: Record<string, boolean>
}

export interface UserModificationMessage {
  type: 'user_modification_request'
  field: string
  newValue: any
}