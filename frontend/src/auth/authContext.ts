import { createContext, useContext } from 'react'
import type { components } from '../api/types'

export type User = components['schemas']['UserOut']
export type Status = 'loading' | 'anonymous' | 'authenticated'

export interface AuthValue {
  user: User | null
  status: Status
  login: (username: string, password: string) => Promise<User>
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthValue | null>(null)

export function useAuth(): AuthValue {
  const v = useContext(AuthContext)
  if (!v) throw new Error('useAuth must be used inside <AuthProvider>')
  return v
}
