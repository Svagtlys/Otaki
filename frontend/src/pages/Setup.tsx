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
      <h2>Create admin account</h2>
      <div style={fieldStyle}>
        <label htmlFor="username">Username</label>
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
        <label htmlFor="password">Password</label>
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
      <button type="submit" disabled={loading}>
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
        <h2>Connect to Suwayomi</h2>
        <p style={{ color: 'green' }}>Connected to Suwayomi successfully.</p>
        <button onClick={onAdvance}>{isConfirm ? 'Confirm' : 'Continue'}</button>
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit}>
      <h2>Connect to Suwayomi</h2>
      <div style={fieldStyle}>
        <label htmlFor="suwayomi-url">Suwayomi URL</label>
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
        <label htmlFor="suwayomi-username">Username (optional)</label>
        <input
          id="suwayomi-username"
          type="text"
          value={username}
          onChange={e => setUsername(e.target.value)}
          style={inputStyle}
        />
      </div>
      <div style={fieldStyle}>
        <label htmlFor="suwayomi-password">Password (optional)</label>
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
      <button type="submit" disabled={loading}>
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

  if (loadingFetch) return <p>Loading sources…</p>
  if (fetchError) return <p style={errorStyle}>{fetchError}</p>

  const rowStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '5px 0',
    borderBottom: '1px solid #eee',
  }

  return (
    <form onSubmit={handleSubmit}>
      <h2>Select sources</h2>

      {selected.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <p style={{ fontSize: 13, color: '#555', marginBottom: 6 }}>
            Selected — position 1 is highest priority
          </p>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {selected.map((src, i) => (
              <li key={src.id} style={rowStyle}>
                <span style={{ minWidth: 20, color: '#999', fontSize: 13 }}>{i + 1}.</span>
                <SourceIcon src={src} />
                <span style={{ flex: 1 }}>{src.name}</span>
                <span style={{ fontSize: 12, color: '#999' }}>{src.lang}</span>
                <button type="button" onClick={() => moveUp(i)} disabled={i === 0} aria-label={`Move ${src.name} up`}>↑</button>
                <button type="button" onClick={() => moveDown(i)} disabled={i === selected.length - 1} aria-label={`Move ${src.name} down`}>↓</button>
                <button type="button" onClick={() => remove(src)} aria-label={`Remove ${src.name}`}>×</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {available.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <p style={{ fontSize: 13, color: '#555', marginBottom: 6 }}>
            {selected.length > 0 ? 'Add more sources' : 'Available sources'}
          </p>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {available.map(src => (
              <li key={src.id} style={{ ...rowStyle, color: '#555' }}>
                <span style={{ minWidth: 20 }} />
                <SourceIcon src={src} />
                <span style={{ flex: 1 }}>{src.name}</span>
                <span style={{ fontSize: 12, color: '#999' }}>{src.lang}</span>
                <button type="button" onClick={() => add(src)} aria-label={`Add ${src.name}`}>+ Add</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {saveError && <p style={errorStyle}>{saveError}</p>}
      <button type="submit" disabled={loadingSave || selected.length === 0}>
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
        <h2>Set paths</h2>
        <p>The following {missingDirs.length === 1 ? 'directory does' : 'directories do'} not exist yet:</p>
        <ul style={{ margin: '8px 0 16px', paddingLeft: 20 }}>
          {missingDirs.map(({ field, path }) => (
            <li key={field} style={{ marginBottom: 4 }}>
              <strong>{FIELD_LABELS[field] ?? field}</strong>:{' '}
              <code style={{ fontSize: 13 }}>{path}</code>
            </li>
          ))}
        </ul>
        <p>Create {missingDirs.length === 1 ? 'it' : 'them'} now?</p>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => submit(true)} disabled={loading}>
            {loading ? 'Creating…' : 'Yes, create'}
          </button>
          <button type="button" onClick={() => setMissingDirs(null)} disabled={loading}>
            Go back
          </button>
        </div>
        {error && <p style={errorStyle}>{error}</p>}
      </div>
    )
  }

  return (
    <form onSubmit={e => { e.preventDefault(); submit(false) }}>
      <h2>Set paths</h2>
      <div style={fieldStyle}>
        <label htmlFor="download-path">Suwayomi download path</label>
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
        <label htmlFor="library-path">Library path</label>
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
      <small style={{ display: 'block', color: '#555', marginBottom: 12 }}>
        Docker users: use <code>/app/suwayomi_data/downloads</code> and <code>/app/library</code>
      </small>
      {error && <p style={errorStyle}>{error}</p>}
      <button type="submit" disabled={loading}>
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

  return (
    <main
      style={{
        maxWidth: 480,
        margin: '60px auto',
        padding: '0 16px',
        fontFamily: 'sans-serif',
        position: 'relative',
      }}
    >
      {loggedInUser && (
        <div style={{ position: 'absolute', top: -40, right: 0, fontSize: 14, color: '#666' }}>
          {loggedInUser}
        </div>
      )}
      <h1 style={{ marginBottom: 4 }}>Otaki setup</h1>
      <p style={{ color: '#666', marginBottom: 24 }}>Step {currentStep} of 4</p>
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
    </main>
  )
}
