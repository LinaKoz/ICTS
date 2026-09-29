import { Navigate, Route, Routes } from 'react-router-dom'
import { LoginPage } from './auth/LoginPage'
import { RequireAuth } from './auth/RequireAuth'
import { AppLayout } from './layout/AppLayout'
import { RosterPage } from './features/roster/RosterPage'
import { WorkersPage } from './features/workers/WorkersPage'
import { WorkerDetailPage } from './features/workers/WorkerDetailPage'
import { ImportPage } from './features/imports/ImportPage'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route path="/roster" element={<RosterPage />} />
          <Route path="/workers" element={<WorkersPage />} />
          <Route path="/workers/:id" element={<WorkerDetailPage />} />
          <Route path="/imports" element={<ImportPage />} />
          <Route path="*" element={<Navigate to="/roster" replace />} />
        </Route>
      </Route>
    </Routes>
  )
}
