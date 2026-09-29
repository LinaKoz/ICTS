import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import './App.css'
import App from './App'
import { AuthProvider } from './auth/AuthProvider'
import { mapError } from './errors/mapError'
import { Toaster } from './errors/toast'
import { showToast } from './errors/toastStore'

// Network and unexpected errors surface as toasts; everything else is shown inline by the caller.
const toastIfNeeded = (err: unknown) => {
  const m = mapError(err)
  if (m.presentation === 'toast') showToast(m.message)
}
const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: toastIfNeeded }),
  mutationCache: new MutationCache({ onError: toastIfNeeded }),
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <App />
          <Toaster />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
