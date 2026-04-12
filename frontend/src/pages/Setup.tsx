import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, apiFetch } from '../api/client'
import { useAuth } from '../context/AuthContext'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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
  marginBottom: 14,
}

const inputStyle: React.CSSProperties = {
  padding: '7px 10px',
  fontSize: 13,
  width: '100%',
  boxSizing: 'border-box',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-sm)',
  background: 'var(--surface)',
  color: 'var(--text)',
  fontFamily: 'inherit',
  outline: 'none',
}

const errorStyle: React.CSSProperties = {
  color: 'var(--danger)',
  fontSize: 13,
  marginTop: 8,
}

const labelStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: 500,
  color: 'var(--text)',
}

const stepHeadingStyle: React.CSSProperties = {
  fontSize: 18,
  fontWeight: 700,
  color: 'var(--text)',
  margin: '0 0 20px',
}

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

interface SetupStatus {
  admin_created: boolean
  suwayomi_url: string | null
  suwayomi_username: string | null
  download_path: string | null
  library_path: string | null
}

interface TokenResponse {
  access_token: string
  token_type: string
}

// ---------------------------------------------------------------------------
// Step 1 — Create admin account
// ---------------------------------------------------------------------------

function Step1({ onAdvance }: { onAdvance: (username: string, status: SetupStatus) => void }) {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function doLogin(u: string, p: string) {
    const tok = await apiFetch<TokenResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username: u, password: p }),
    })
    login(tok.access_token)
    const status = await apiFetch<SetupStatus>('/api/setup/status')
    onAdvance(u, status)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await apiFetch('/api/setup/user', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      await doLogin(username, password)
    } catch (err) {
      const detail = extractDetail(err)
      if (detail === 'Admin user already exists') {
        try {
          await doLogin(username, password)
        } catch (loginErr) {
          const d = extractDetail(loginErr)
          setError(d === 'Invalid credentials' ? 'Incorrect password.' : d)
          setLoading(false)
        }
        return
      } else if (detail === 'Setup already complete') {
        navigate('/login', { replace: true })
      } else {
        setError(detail)
        setLoading(false)
      }
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <h2 style={stepHeadingStyle}>Create admin account</h2>
      <div style={fieldStyle}>
        <label style={labelStyle} htmlFor="username">Username</label>
        <input
          id="username"
          type="text"
          value={username}
          onChange={e => setUsername(e.target.value)}
          required
          autoFocus
          style={inputStyle}
        />
      </div>
      <div style={fieldStyle}>
        <label style={labelStyle} htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          required
          style={inputStyle}
        />
      </div>
      {error && <p style={errorStyle}>{error}</p>}
      <button className="btn primary" type="submit" disabled={loading}
        style={{ width: '100%', opacity: loading ? 0.6 : 1, marginTop: 4 }}>
        {loading ? 'Creating…' : 'Create account'}
      </button>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Step 2 — Connect Suwayomi
//
// Normal mode:   empty fields → Connect → success message → Continue
// Confirm mode:  pre-filled disabled fields → Connect → success message → Confirm
// ---------------------------------------------------------------------------

function Step2({
  status,
  onAdvance,
}: {
  status: SetupStatus
  onAdvance: () => void
}) {
  const isConfirm = Boolean(status.suwayomi_url)
  const [url, setUrl] = useState(status.suwayomi_url ?? '')
  const [username, setUsername] = useState(status.suwayomi_username ?? '')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [connected, setConnected] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await apiFetch('/api/setup/connect', {
        method: 'POST',
        body: JSON.stringify({ url, username, password }),
      })
      setConnected(true)
    } catch (err) {
      setError(extractDetail(err))
    } finally {
      setLoading(false)
    }
  }

  if (connected) {
    return (
      <div>
        <h2 style={stepHeadingStyle}>Connect to Suwayomi</h2>
        <p style={{ color: 'var(--success)', marginBottom: 16 }}>Connected to Suwayomi successfully.</p>
        <button className="btn primary" onClick={onAdvance} style={{ width: '100%' }}>
          {isConfirm ? 'Confirm' : 'Continue'}
        </button>
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit}>
      <h2 style={stepHeadingStyle}>Connect to Suwayomi</h2>
      <div style={fieldStyle}>
        <label style={labelStyle} htmlFor="suwayomi-url">Suwayomi URL</label>
        <input
          id="suwayomi-url"
          type="url"
          value={url}
          onChange={e => setUrl(e.target.value)}
          placeholder="http://localhost:4567"
          required
          autoFocus={!isConfirm}
          style={inputStyle}
        />
      </div>
      <div style={fieldStyle}>
        <label style={labelStyle} htmlFor="suwayomi-username">Username (optional)</label>
        <input
          id="suwayomi-username"
          type="text"
          value={username}
          onChange={e => setUsername(e.target.value)}
          style={inputStyle}
        />
      </div>
      <div style={fieldStyle}>
        <label style={labelStyle} htmlFor="suwayomi-password">Password (optional)</label>
        <input
          id="suwayomi-password"
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          placeholder={isConfirm ? '(leave blank to keep current)' : undefined}
          style={inputStyle}
        />
      </div>
      {error && <p style={errorStyle}>{error}</p>}
      <button className="btn primary" type="submit" disabled={loading}
        style={{ width: '100%', opacity: loading ? 0.6 : 1, marginTop: 4 }}>
        {loading ? 'Connecting…' : 'Connect'}
      </button>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Step 3 — Select and order sources
// ---------------------------------------------------------------------------

interface Source {
  id: string
  name: string
  lang: string
  icon_url: string
}

function SourceIcon({ src }: { src: Source }) {
  return (
    <img
      src={src.icon_url}
      alt=""
      width={20}
      height={20}
      style={{ objectFit: 'contain', flexShrink: 0 }}
      onError={e => {
        ;(e.target as HTMLImageElement).style.display = 'none'
      }}
    />
  )
}

function Step3({ onAdvance }: { onAdvance: () => void }) {
  const [available, setAvailable] = useState<Source[]>([])
  const [selected, setSelected] = useState<Source[]>([])
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [loadingFetch, setLoadingFetch] = useState(true)
  const [loadingSave, setLoadingSave] = useState(false)

  useEffect(() => {
    apiFetch<Source[]>('/api/setup/sources')
      .then(setAvailable)
      .catch(err => setFetchError(extractDetail(err)))
      .finally(() => setLoadingFetch(false))
  }, [])

  function add(src: Source) {
    setAvailable(prev => prev.filter(s => s.id !== src.id))
    setSelected(prev => [...prev, src])
  }

  function remove(src: Source) {
    setSelected(prev => prev.filter(s => s.id !== src.id))
    setAvailable(prev => [...prev, src])
  }

  function moveUp(i: number) {
    setSelected(prev => {
      const next = [...prev]
      ;[next[i - 1], next[i]] = [next[i], next[i - 1]]
      return next
    })
  }

  function moveDown(i: number) {
    setSelected(prev => {
      const next = [...prev]
      ;[next[i], next[i + 1]] = [next[i + 1], next[i]]
      return next
    })
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoadingSave(true)
    setSaveError(null)
    try {
      await apiFetch('/api/setup/sources', {
        method: 'POST',
        body: JSON.stringify({ sources: selected }),
      })
      onAdvance()
    } catch (err) {
      setSaveError(extractDetail(err))
    } finally {
      setLoadingSave(false)
    }
  }

  if (loadingFetch) return <p style={{ color: 'var(--text-2)' }}>Loading sources…</p>
  if (fetchError) return <p style={errorStyle}>{fetchError}</p>

  const srcRowStyle: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 8,
    padding: '8px 10px', borderRadius: 'var(--radius-sm)',
    border: `1px solid var(--border)`, background: 'var(--surface)', marginBottom: 6,
  }

  return (
    <form onSubmit={handleSubmit}>
      <h2 style={stepHeadingStyle}>Select sources</h2>

      {selected.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <p style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 8 }}>
            Selected — position 1 is highest priority
          </p>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {selected.map((src, i) => (
              <li key={src.id} style={srcRowStyle}>
                <span style={{ minWidth: 20, color: 'var(--accent)', fontSize: 12, fontWeight: 700 }}>{i + 1}</span>
                <SourceIcon src={src} />
                <span style={{ flex: 1, color: 'var(--text)', fontSize: 13 }}>{src.name}</span>
                <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{src.lang}</span>
                <button className="btn icon" type="button" onClick={() => moveUp(i)} disabled={i === 0}
                  style={{ opacity: i === 0 ? 0.3 : 1 }} aria-label={`Move ${src.name} up`}><i className="bx bx-chevron-up" /></button>
                <button className="btn icon" type="button" onClick={() => moveDown(i)} disabled={i === selected.length - 1}
                  style={{ opacity: i === selected.length - 1 ? 0.3 : 1 }} aria-label={`Move ${src.name} down`}><i className="bx bx-chevron-down" /></button>
                <button className="btn icon" type="button" onClick={() => remove(src)} aria-label={`Remove ${src.name}`}><i className="bx bx-x" /></button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {available.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <p style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 8 }}>
            {selected.length > 0 ? 'Add more sources' : 'Available sources'}
          </p>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {available.map(src => (
              <li key={src.id} style={{ ...srcRowStyle, opacity: 0.7 }}>
                <span style={{ minWidth: 20 }} />
                <SourceIcon src={src} />
                <span style={{ flex: 1, color: 'var(--text)', fontSize: 13 }}>{src.name}</span>
                <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{src.lang}</span>
                <button className="btn" type="button" onClick={() => add(src)}
                  style={{ fontSize: 12 }} aria-label={`Add ${src.name}`}>+ Add</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {saveError && <p style={errorStyle}>{saveError}</p>}
      <button className="btn primary" type="submit" disabled={loadingSave || selected.length === 0}
        style={{ width: '100%', opacity: (loadingSave || selected.length === 0) ? 0.6 : 1, marginTop: 4 }}>
        {loadingSave ? 'Saving…' : 'Save order'}
      </button>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Step 4 — Set paths
// ---------------------------------------------------------------------------

interface MissingDir {
  field: string
  path: string
}

const FIELD_LABELS: Record<string, string> = {
  download_path: 'Suwayomi download path',
  library_path: 'Library path',
}

function Step4({
  status,
  onDone,
}: {
  status: SetupStatus
  onDone: () => void
}) {
  const isConfirm = Boolean(status.download_path && status.library_path)
  const [downloadPath, setDownloadPath] = useState(status.download_path ?? '')
  const [libraryPath, setLibraryPath] = useState(status.library_path ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [missingDirs, setMissingDirs] = useState<MissingDir[] | null>(null)

  async function submit(create: boolean) {
    setLoading(true)
    setError(null)
    try {
      await apiFetch('/api/setup/paths', {
        method: 'POST',
        body: JSON.stringify({ download_path: downloadPath, library_path: libraryPath, create }),
      })
      onDone()
    } catch (err) {
      if (err instanceof ApiError) {
        try {
          const body = JSON.parse(err.message) as {
            detail: { code: string; missing: MissingDir[] }
          }
          if (body.detail?.code === 'directories_missing') {
            setMissingDirs(body.detail.missing)
            return
          }
        } catch {
          // fall through to generic error
        }
      }
      setError(extractDetail(err))
    } finally {
      setLoading(false)
    }
  }

  if (missingDirs) {
    return (
      <div>
        <h2 style={stepHeadingStyle}>Set paths</h2>
        <p style={{ fontSize: 13, color: 'var(--text)', marginBottom: 8 }}>
          The following {missingDirs.length === 1 ? 'directory does' : 'directories do'} not exist yet:
        </p>
        <ul style={{ margin: '0 0 16px', paddingLeft: 20 }}>
          {missingDirs.map(({ field, path }) => (
            <li key={field} style={{ marginBottom: 6, fontSize: 13, color: 'var(--text)' }}>
              <strong>{FIELD_LABELS[field] ?? field}</strong>:{' '}
              <code style={{ fontSize: 12, color: 'var(--text-2)', background: 'var(--surface-2)', padding: '1px 4px', borderRadius: 3 }}>{path}</code>
            </li>
          ))}
        </ul>
        <p style={{ fontSize: 13, color: 'var(--text)', marginBottom: 16 }}>
          Create {missingDirs.length === 1 ? 'it' : 'them'} now?
        </p>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn primary" onClick={() => submit(true)} disabled={loading}
            style={{ opacity: loading ? 0.6 : 1 }}>
            {loading ? 'Creating…' : 'Yes, create'}
          </button>
          <button className="btn" type="button" onClick={() => setMissingDirs(null)} disabled={loading}>
            Go back
          </button>
        </div>
        {error && <p style={errorStyle}>{error}</p>}
      </div>
    )
  }

  return (
    <form onSubmit={e => { e.preventDefault(); submit(false) }}>
      <h2 style={stepHeadingStyle}>Set paths</h2>
      <div style={fieldStyle}>
        <label style={labelStyle} htmlFor="download-path">Suwayomi download path</label>
        <input
          id="download-path"
          type="text"
          value={downloadPath}
          onChange={e => setDownloadPath(e.target.value)}
          placeholder="/app/suwayomi_data/downloads"
          required
          autoFocus={!isConfirm}
          style={inputStyle}
        />
      </div>
      <div style={fieldStyle}>
        <label style={labelStyle} htmlFor="library-path">Library path</label>
        <input
          id="library-path"
          type="text"
          value={libraryPath}
          onChange={e => setLibraryPath(e.target.value)}
          placeholder="/app/library"
          required
          style={inputStyle}
        />
      </div>
      <small style={{ display: 'block', fontSize: 12, color: 'var(--text-2)', marginBottom: 12 }}>
        Docker users: use <code style={{ background: 'var(--surface-2)', padding: '1px 4px', borderRadius: 3 }}>/app/suwayomi_data/downloads</code> and <code style={{ background: 'var(--surface-2)', padding: '1px 4px', borderRadius: 3 }}>/app/library</code>
      </small>
      {error && <p style={errorStyle}>{error}</p>}
      <button className="btn primary" type="submit" disabled={loading}
        style={{ width: '100%', opacity: loading ? 0.6 : 1, marginTop: 4 }}>
        {loading ? 'Saving…' : isConfirm ? 'Confirm' : 'Save paths'}
      </button>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Setup wizard (parent)
// ---------------------------------------------------------------------------

export default function Setup({ onComplete }: { onComplete: () => void }) {
  const [currentStep, setCurrentStep] = useState<1 | 2 | 3 | 4>(1)
  const [loggedInUser, setLoggedInUser] = useState<string | null>(null)
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const navigate = useNavigate()

  function handleStep1Advance(username: string, s: SetupStatus) {
    setLoggedInUser(username)
    setStatus(s)
    setCurrentStep(2)
  }

  function advance() {
    setCurrentStep(s => (s < 4 ? ((s + 1) as 1 | 2 | 3 | 4) : s))
  }

  const STEP_LABELS = ['Account', 'Suwayomi', 'Sources', 'Paths']

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center',
      minHeight: '100vh', background: 'var(--bg)', padding: '24px 16px',
    }}>
      {/* Logo */}
      <div style={{ marginBottom: 24, textAlign: 'center' }}>
        <div style={{
          width: 40, height: 40, borderRadius: 10, margin: '0 auto 10px',
          background: 'linear-gradient(135deg, #007aff 0%, #5856d6 100%)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 20, fontWeight: 700, color: '#fff',
        }}>O</div>
        <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>Otaki setup</div>
        {loggedInUser && (
          <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 2 }}>Signed in as {loggedInUser}</div>
        )}
      </div>

      {/* Step dots */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 24 }}>
        {STEP_LABELS.map((label, i) => {
          const stepNum = i + 1
          const done = currentStep > stepNum
          const active = currentStep === stepNum
          return (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                <div style={{
                  width: 28, height: 28, borderRadius: '50%',
                  background: done ? 'var(--success)' : active ? 'var(--accent)' : 'var(--surface-2)',
                  color: (done || active) ? '#fff' : 'var(--text-3)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 12, fontWeight: 700,
                  border: `2px solid ${done ? 'var(--success)' : active ? 'var(--accent)' : 'var(--border)'}`,
                }}>{done ? <i className="bx bx-check" style={{ fontSize: 16 }} /> : stepNum}</div>
                <span style={{ fontSize: 10, color: active ? 'var(--accent)' : 'var(--text-3)', fontWeight: active ? 600 : 400 }}>
                  {label}
                </span>
              </div>
              {i < STEP_LABELS.length - 1 && (
                <div style={{ width: 32, height: 2, background: done ? 'var(--success)' : 'var(--border)', marginBottom: 18 }} />
              )}
            </div>
          )
        })}
      </div>

      {/* Card */}
      <div className="card" style={{ width: '100%', maxWidth: 480, padding: 32 }}>
        {currentStep === 1 && <Step1 onAdvance={handleStep1Advance} />}
        {currentStep === 2 && status && (
          <Step2 status={status} onAdvance={advance} />
        )}
        {currentStep === 3 && <Step3 onAdvance={advance} />}
        {currentStep === 4 && status && (
          <Step4
            status={status}
            onDone={() => {
              onComplete()
              navigate('/login', { replace: true })
            }}
          />
        )}
      </div>
    </div>
  )
}
