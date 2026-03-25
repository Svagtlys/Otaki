import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { useAuth } from './context/AuthContext'

function RequireAuth() {
  const { isAuthenticated } = useAuth()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <Outlet />
}

function Placeholder({ name }: { name: string }) {
  return <div>{name}</div>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/setup" element={<Placeholder name="Setup" />} />
        <Route path="/login" element={<Placeholder name="Login" />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<Placeholder name="Home" />} />
          <Route path="/search" element={<Placeholder name="Search" />} />
          <Route path="/comics/:id" element={<Placeholder name="Comic" />} />
          <Route path="/sources" element={<Placeholder name="Sources" />} />
          <Route path="/settings" element={<Placeholder name="Settings" />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
