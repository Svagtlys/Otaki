import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import Library from './pages/Library'
import Login from './pages/Login'
import Setup from './pages/Setup'
import Search from './pages/Search'
import Comic from './pages/Comic'
import Sources from './pages/Sources'
import Settings from './pages/Settings'

function RequireAuth() {
  const { isAuthenticated } = useAuth()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <Outlet />
}


export default function App() {
  const [setupComplete, setSetupComplete] = useState<boolean | null>(null)

  useEffect(() => {
    fetch('/api/setup/complete')
      .then(r => r.json())
      .then((data: { complete: boolean }) => setSetupComplete(data.complete))
      .catch(() => setSetupComplete(false))
  }, [])

  if (setupComplete === null) return null

  if (!setupComplete) {
    return (
      <BrowserRouter>
        <Routes>
          <Route
            path="/setup"
            element={<Setup onComplete={() => setSetupComplete(true)} />}
          />
          <Route path="*" element={<Navigate to="/setup" replace />} />
        </Routes>
      </BrowserRouter>
    )
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/setup" element={<Navigate to="/login" replace />} />
        <Route path="/login" element={<Login />} />
        <Route element={<RequireAuth />}>
          <Route path="/library" element={<Library />} />
          <Route path="/search" element={<Search />} />
          <Route path="/comics/:id" element={<Comic />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
        <Route path="*" element={<Navigate to="/library" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
