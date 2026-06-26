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
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      alignItems: 'center',
      minHeight: '100vh',
      background: 'var(--bg)',
    }}>
      {/* Logo mark */}
      <div style={{ marginBottom: 24, textAlign: 'center' }}>
        <div style={{
          width: 48, height: 48, borderRadius: 12, margin: '0 auto 12px',
          background: 'linear-gradient(135deg, #007aff 0%, #5856d6 100%)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 24, fontWeight: 700, color: '#fff',
          boxShadow: '0 4px 16px rgba(0, 122, 255, 0.35)',
        }}>O</div>
        <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)', letterSpacing: '-0.3px' }}>Otaki</div>
        <div style={{ fontSize: 13, color: 'var(--text-2)', marginTop: 2 }}>Sign in to continue</div>
      </div>

      {/* Card */}
      <div className="card" style={{ padding: 32, width: 340 }}>
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label style={labelStyle} htmlFor="username">Username</label>
            <input
              id="username"
              className="input"
              style={{ marginTop: 4 }}
              value={username}
              onChange={e => setUsername(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div style={{ marginBottom: 20 }}>
            <label style={labelStyle} htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              className="input"
              style={{ marginTop: 4 }}
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
          </div>
          {error && <p style={{ color: 'var(--danger)', fontSize: 13, margin: '0 0 12px' }}>{error}</p>}
          <button
            className="btn primary"
            type="submit"
            disabled={loading}
            style={{ width: '100%', opacity: loading ? 0.6 : 1 }}
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 13,
  fontWeight: 500,
  color: 'var(--text)',
}
