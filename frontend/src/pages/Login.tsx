import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { ApiError, apiFetch } from '../api/client'
import { useAuth } from '../context/AuthContext'

function extractDetail(err: unknown): string {
  if (err instanceof ApiError) {
    try {
      return (JSON.parse(err.message) as { detail: string }).detail
    } catch {
      return err.message
    }
  }
  return 'An unexpected error occurred'
}

const fieldStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  marginBottom: 12,
}

const inputStyle: React.CSSProperties = {
  padding: '6px 8px',
  fontSize: 14,
  width: '100%',
  boxSizing: 'border-box',
}

const errorStyle: React.CSSProperties = {
  color: 'red',
  fontSize: 13,
  marginTop: 8,
}

interface TokenResponse {
  access_token: string
  token_type: string
}

export default function Login() {
  const { isAuthenticated, login } = useAuth()
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (isAuthenticated) {
    return <Navigate to="/library" replace />
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetch<TokenResponse>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      login(data.access_token)
      navigate('/library')
    } catch (err) {
      setError(extractDetail(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
        background: '#f5f5f5',
      }}
    >
      <div
        style={{
          background: '#fff',
          padding: 32,
          borderRadius: 8,
          width: 320,
          boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
        }}
      >
        <h2 style={{ marginTop: 0, marginBottom: 24 }}>Log in to Otaki</h2>
        <form onSubmit={handleSubmit}>
          <div style={fieldStyle}>
            <label htmlFor="username">Username</label>
            <input
              id="username"
              style={inputStyle}
              value={username}
              onChange={e => setUsername(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div style={fieldStyle}>
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              style={inputStyle}
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
          </div>
          {error && <p style={errorStyle}>{error}</p>}
          <button type="submit" disabled={loading} style={{ marginTop: 8 }}>
            {loading ? 'Logging in…' : 'Log in'}
          </button>
        </form>
      </div>
    </div>
  )
}
