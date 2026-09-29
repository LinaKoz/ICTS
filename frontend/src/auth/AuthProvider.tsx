import { useEffect, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, setUnauthorizedHandler } from '../api/client'
import { AuthContext, type AuthValue, type Status, type User } from './authContext'
import { ApiError } from '../errors/ApiError'


const ME_KEY = ['auth', 'me'] as const

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()

  const me = useQuery({
    queryKey: ME_KEY,
    retry: false,
    staleTime: Infinity,
    queryFn: async () => {
      try {
        return await apiFetch<User>('/auth/me', { skipUnauthorizedHandler: true })
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
  })

  // Any 401 from a data request drops the session; RequireAuth then redirects to /login.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      qc.setQueryData(ME_KEY, null)
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
    })
    return () => setUnauthorizedHandler(null)
  }, [qc])

  const loginMut = useMutation({
    mutationFn: (v: { username: string; password: string }) =>
      apiFetch<User>('/auth/login', { method: 'POST', body: v, skipUnauthorizedHandler: true }),
    onSuccess: (u) => qc.setQueryData(ME_KEY, u),
  })

  const logoutMut = useMutation({
    mutationFn: () => apiFetch<void>('/auth/logout', { method: 'POST', skipUnauthorizedHandler: true }),
    onSettled: () => {
      qc.setQueryData(ME_KEY, null)
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
    },
  })

  const user = me.data ?? null
  const status: Status = me.isPending ? 'loading' : user ? 'authenticated' : 'anonymous'
  const value: AuthValue = {
    user,
    status,
    login: (username, password) => loginMut.mutateAsync({ username, password }),
    logout: () => logoutMut.mutateAsync(),
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
