import { Navigate, Route, Routes } from 'react-router-dom'
import { LoginPage } from './auth/LoginPage'
import { RequireAuth } from './auth/RequireAuth'
import { AppLayout } from './layout/AppLayout'
import { RosterPage } from './features/roster/RosterPage'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route path="/roster" element={<RosterPage />} />
          <Route path="*" element={<Navigate to="/roster" replace />} />
        </Route>
      </Route>
    </Routes>
  )
}
