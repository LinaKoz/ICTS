import type { Role } from '../../api/schemas'

export const ROLES: Role[] = ['GENERAL_GUARD', 'SCREENER', 'SUPERVISOR']

const LABEL: Record<Role, string> = { GENERAL_GUARD: 'General guard', SCREENER: 'Screener', SUPERVISOR: 'Supervisor' }
export const roleLabel = (r: Role): string => LABEL[r]
