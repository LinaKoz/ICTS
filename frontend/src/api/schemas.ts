/** Named aliases over the generated OpenAPI types (`types.ts`, from backend/openapi.json). */
import type { components } from './types'

type S = components['schemas']

export type AssignmentOut = S['AssignmentOut']
export type ViolationOut = S['ViolationOut']
export type CoverageGapOut = S['CoverageGapOut']
export type HourShortfallOut = S['HourShortfallOut']
export type CostsOut = S['CostsOut']
export type ShiftCostOut = S['ShiftCostOut']
export type WorkerRefOut = S['WorkerRefOut']
export type GenerateOutcomeOut = S['GenerateOutcomeOut']
export type SaveRequest = S['SaveRequest']
export type SaveResponseOut = S['SaveResponseOut']
export type RosterOut = S['RosterOut']
export type Shift = AssignmentOut['shift']
export type Role = AssignmentOut['role']
export type ViolationCode = ViolationOut['code']

export type EditableAssignmentOut = S['EditableAssignmentOut']
export type AddAssignmentRequest = S['AddAssignmentRequest']
export type MoveAssignmentRequest = S['MoveAssignmentRequest']
export type RemoveAssignmentRequest = S['RemoveAssignmentRequest']
export type EditResultOut = S['EditResultOut']
export type SuggestionOut = S['SuggestionOut']
export type SuggestionsOut = S['SuggestionsOut']
