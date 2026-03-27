import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, extractDetail } from '../api/client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Settings {
  suwayomi_url: string | null
  suwayomi_username: string | null
  suwayomi_password: string | null
  suwayomi_download_path: string | null
  library_path: string | null
  default_poll_days: number
  chapter_naming_format: string
  relocation_strategy: 'auto' | 'hardlink' | 'copy' | 'move'
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Settings() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: settings, isLoading, error } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiFetch<Settings>('/api/settings'),
  })

  // Suwayomi connection
  const [connUrl, setConnUrl] = useState('')
  const [connUsername, setConnUsername] = useState('')
  const [connPassword, setConnPassword] = useState('')
  const [connSaving, setConnSaving] = useState(false)
  const [connError, setConnError] = useState<string | null>(null)
  const [connSuccess, setConnSuccess] = useState(false)

  // Paths
  const [downloadPath, setDownloadPath] = useState('')
  const [libraryPath, setLibraryPath] = useState('')
  const [pathsSaving, setPathsSaving] = useState(false)
  const [pathsError, setPathsError] = useState<string | null>(null)

  // Naming format
  const [namingFormat, setNamingFormat] = useState('')
  const [namingSaving, setNamingSaving] = useState(false)
  const [namingError, setNamingError] = useState<string | null>(null)

  // Polling
  const [pollDays, setPollDays] = useState(7)
  const [pollSaving, setPollSaving] = useState(false)
  const [pollError, setPollError] = useState<string | null>(null)

  useEffect(() => {
    if (!settings) return
    setConnUrl(settings.suwayomi_url ?? '')
    setConnUsername(settings.suwayomi_username ?? '')
    setDownloadPath(settings.suwayomi_download_path ?? '')
    setLibraryPath(settings.library_path ?? '')
    setNamingFormat(settings.chapter_naming_format)
    setPollDays(settings.default_poll_days)
  }, [settings])

  async function saveConnection(e: React.FormEvent) {
    e.preventDefault()
    setConnSaving(true)
    setConnError(null)
    setConnSuccess(false)
    try {
      const body: Record<string, string | null> = {
        suwayomi_url: connUrl,
        suwayomi_username: connUsername || null,
      }
      if (connPassword) body.suwayomi_password = connPassword
      await apiFetch('/api/settings', { method: 'PATCH', body: JSON.stringify(body) })
      setConnPassword('')
      setConnSuccess(true)
      await queryClient.invalidateQueries({ queryKey: ['settings'] })
    } catch (err) {
      setConnError(extractDetail(err))
    } finally {
      setConnSaving(false)
    }
  }

  async function savePaths(e: React.FormEvent) {
    e.preventDefault()
    setPathsSaving(true)
    setPathsError(null)
    try {
      await apiFetch('/api/settings', {
        method: 'PATCH',
        body: JSON.stringify({ suwayomi_download_path: downloadPath, library_path: libraryPath }),
      })
      await queryClient.invalidateQueries({ queryKey: ['settings'] })
    } catch (err) {
      setPathsError(extractDetail(err))
    } finally {
      setPathsSaving(false)
    }
  }

  async function saveNaming(e: React.FormEvent) {
    e.preventDefault()
    setNamingSaving(true)
    setNamingError(null)
    try {
      await apiFetch('/api/settings', {
        method: 'PATCH',
        body: JSON.stringify({ chapter_naming_format: namingFormat }),
      })
      await queryClient.invalidateQueries({ queryKey: ['settings'] })
    } catch (err) {
      setNamingError(extractDetail(err))
    } finally {
      setNamingSaving(false)
    }
  }

  async function savePoll(e: React.FormEvent) {
    e.preventDefault()
    setPollSaving(true)
    setPollError(null)
    try {
      await apiFetch('/api/settings', {
        method: 'PATCH',
        body: JSON.stringify({ default_poll_days: pollDays }),
      })
      await queryClient.invalidateQueries({ queryKey: ['settings'] })
    } catch (err) {
      setPollError(extractDetail(err))
    } finally {
      setPollSaving(false)
    }
  }

  const namingPreview = namingFormat
    .replace(/\{title\}/g, 'One Piece')
    .replace(/\{chapter\}/g, '0001')

  return (
    <div style={{ maxWidth: 640, margin: '0 auto', padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 32 }}>
        <h1 style={{ margin: 0 }}>Settings</h1>
        <button onClick={() => navigate('/library')} style={linkButtonStyle}>← Library</button>
      </div>

      {isLoading && <p>Loading…</p>}
      {error && <p style={{ color: 'red' }}>{extractDetail(error)}</p>}

      {settings && (
        <>
          {/* Suwayomi connection */}
          <section style={sectionStyle}>
            <h2 style={sectionHeadingStyle}>Suwayomi connection</h2>
            <form onSubmit={saveConnection}>
              <div style={fieldStyle}>
                <label style={labelStyle} htmlFor="conn-url">URL</label>
                <input
                  id="conn-url"
                  type="url"
                  value={connUrl}
                  onChange={e => setConnUrl(e.target.value)}
                  required
                  style={inputStyle}
                />
              </div>
              <div style={fieldStyle}>
                <label style={labelStyle} htmlFor="conn-username">Username</label>
                <input
                  id="conn-username"
                  type="text"
                  value={connUsername}
                  onChange={e => setConnUsername(e.target.value)}
                  style={inputStyle}
                />
              </div>
              <div style={fieldStyle}>
                <label style={labelStyle} htmlFor="conn-password">Password</label>
                <input
                  id="conn-password"
                  type="password"
                  value={connPassword}
                  onChange={e => setConnPassword(e.target.value)}
                  placeholder={settings.suwayomi_password ? '(leave blank to keep current)' : ''}
                  style={inputStyle}
                />
              </div>
              {connError && <p style={errorStyle}>{connError}</p>}
              {connSuccess && <p style={{ color: 'green', fontSize: 13, margin: '4px 0' }}>Connected successfully.</p>}
              <button type="submit" disabled={connSaving}>
                {connSaving ? 'Saving…' : 'Save & Test'}
              </button>
            </form>
          </section>

          {/* Paths */}
          <section style={sectionStyle}>
            <h2 style={sectionHeadingStyle}>Paths</h2>
            <form onSubmit={savePaths}>
              <div style={fieldStyle}>
                <label style={labelStyle} htmlFor="download-path">Download path</label>
                <input
                  id="download-path"
                  type="text"
                  value={downloadPath}
                  onChange={e => setDownloadPath(e.target.value)}
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
                  style={inputStyle}
                />
              </div>
              {pathsError && <p style={errorStyle}>{pathsError}</p>}
              <button type="submit" disabled={pathsSaving}>
                {pathsSaving ? 'Saving…' : 'Save'}
              </button>
            </form>
          </section>

          {/* Chapter naming */}
          <section style={sectionStyle}>
            <h2 style={sectionHeadingStyle}>Chapter naming</h2>
            <form onSubmit={saveNaming}>
              <div style={fieldStyle}>
                <label style={labelStyle} htmlFor="naming-format">Format</label>
                <input
                  id="naming-format"
                  type="text"
                  value={namingFormat}
                  onChange={e => setNamingFormat(e.target.value)}
                  style={inputStyle}
                />
                <p style={{ fontSize: 12, color: '#888', margin: '4px 0 0' }}>
                  Tokens: <code>{'{title}'}</code>, <code>{'{chapter}'}</code>
                </p>
              </div>
              <div style={fieldStyle}>
                <label style={labelStyle}>Preview</label>
                <code style={{ fontSize: 12, color: '#444' }}>{namingPreview}</code>
              </div>
              {namingError && <p style={errorStyle}>{namingError}</p>}
              <button type="submit" disabled={namingSaving}>
                {namingSaving ? 'Saving…' : 'Save'}
              </button>
            </form>
          </section>

          {/* Polling */}
          <section style={{ marginBottom: 0 }}>
            <h2 style={sectionHeadingStyle}>Polling</h2>
            <form onSubmit={savePoll}>
              <div style={fieldStyle}>
                <label style={labelStyle} htmlFor="poll-days">Default poll interval (days)</label>
                <input
                  id="poll-days"
                  type="number"
                  min={1}
                  value={pollDays}
                  onChange={e => setPollDays(parseInt(e.target.value, 10) || 1)}
                  style={{ ...inputStyle, width: 80 }}
                />
              </div>
              {pollError && <p style={errorStyle}>{pollError}</p>}
              <button type="submit" disabled={pollSaving}>
                {pollSaving ? 'Saving…' : 'Save'}
              </button>
            </form>
          </section>
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const linkButtonStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#0070f3',
  cursor: 'pointer',
  fontSize: 14,
  padding: 0,
}

const sectionStyle: React.CSSProperties = {
  marginBottom: 32,
  paddingBottom: 32,
  borderBottom: '1px solid #eee',
}

const sectionHeadingStyle: React.CSSProperties = {
  fontSize: 16,
  fontWeight: 600,
  margin: '0 0 16px',
}

const fieldStyle: React.CSSProperties = {
  marginBottom: 12,
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 13,
  fontWeight: 500,
  marginBottom: 4,
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '6px 8px',
  fontSize: 13,
  boxSizing: 'border-box',
}

const errorStyle: React.CSSProperties = {
  color: 'red',
  fontSize: 13,
  margin: '4px 0',
}
