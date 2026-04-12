import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, extractDetail } from '../api/client'
import PageLayout from '../components/PageLayout'

const TOKEN_KEY = 'otaki_token'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SourceConflict {
  backup_id: number
  suwayomi_source_id: string
  name: string
  import_priority: number
  import_enabled: boolean
  existing_priority: number
  existing_enabled: boolean
}

interface ComicConflict {
  backup_id: number
  title: string
  existing_id: number
  import_chapters: number
  import_aliases: number
  import_pins: number
  existing_has_cover: boolean
  import_has_cover: boolean
}

interface NewComicEntry {
  backup_id: number
  title: string
  import_chapters: number
  import_aliases: number
  import_pins: number
  import_has_cover: boolean
}

interface NewSourceEntry {
  backup_id: number
  suwayomi_source_id: string
  name: string
}

interface PreviewResult {
  source_conflicts: SourceConflict[]
  comic_conflicts: ComicConflict[]
  new_sources: NewSourceEntry[]
  new_comics: NewComicEntry[]
  totals: { sources: number; comics: number; chapters: number; covers: number }
}

interface SourceResolution {
  backup_id: number
  action: 'overwrite' | 'skip'
}

interface ComicResolution {
  backup_id: number
  action: 'merge' | 'create' | 'skip'
  target_id?: number
  title_override?: string
  replace_cover?: boolean
}

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

type Section = 'polling' | 'paths' | 'relocation' | 'suwayomi' | 'backup'

const SECTIONS: { id: Section; label: string; icon: string }[] = [
  { id: 'polling',    label: 'Polling',    icon: 'bx-time-five' },
  { id: 'paths',      label: 'Paths',      icon: 'bx-folder' },
  { id: 'relocation', label: 'Relocation', icon: 'bx-transfer' },
  { id: 'suwayomi',   label: 'Suwayomi',   icon: 'bx-plug' },
  { id: 'backup',     label: 'Backup',     icon: 'bx-data' },
]

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Settings() {
  const queryClient = useQueryClient()
  const [activeSection, setActiveSection] = useState<Section>('polling')

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

  // Relocation strategy
  const [relocationStrategy, setRelocationStrategy] = useState<Settings['relocation_strategy']>('auto')
  const [relocationSaving, setRelocationSaving] = useState(false)
  const [relocationError, setRelocationError] = useState<string | null>(null)

  useEffect(() => {
    if (!settings) return
    setConnUrl(settings.suwayomi_url ?? '')
    setConnUsername(settings.suwayomi_username ?? '')
    setDownloadPath(settings.suwayomi_download_path ?? '')
    setLibraryPath(settings.library_path ?? '')
    setNamingFormat(settings.chapter_naming_format)
    setPollDays(settings.default_poll_days)
    setRelocationStrategy(settings.relocation_strategy)
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

  async function saveRelocation(strategy: Settings['relocation_strategy']) {
    setRelocationSaving(true)
    setRelocationError(null)
    try {
      await apiFetch('/api/settings', {
        method: 'PATCH',
        body: JSON.stringify({ relocation_strategy: strategy }),
      })
      await queryClient.invalidateQueries({ queryKey: ['settings'] })
    } catch (err) {
      setRelocationError(extractDetail(err))
    } finally {
      setRelocationSaving(false)
    }
  }

  // Live naming preview
  const namingPreview = namingFormat
    .replace(/\{title\}/g, 'One Piece')
    .replace(/\{chapter\}/g, '0001')
    .replace(/\{volume\}/g, '01')
    .replace(/\{year\}/g, '2024')
    .replace(/\{source\}/g, 'MangaDex')

  // Export state
  const [exportFormat, setExportFormat] = useState<'otaki' | 'json' | 'csv'>('otaki')
  const [exportAllAssignments, setExportAllAssignments] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  // Import state
  const importFileRef = useRef<HTMLInputElement>(null)
  const importCardRef = useRef<HTMLDivElement>(null)
  const previewPanelRef = useRef<HTMLDivElement>(null)
  const [importServerPath, setImportServerPath] = useState('')
  const [previewing, setPreviewing] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [previewFile, setPreviewFile] = useState<File | null>(null)
  const [previewTab, setPreviewTab] = useState<'conflicts' | 'new' | 'all'>('conflicts')
  const [sourceResolutions, setSourceResolutions] = useState<Record<number, 'overwrite' | 'skip'>>({})
  const [comicResolutions, setComicResolutions] = useState<Record<number, ComicResolution>>({})
  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const [applyResult, setApplyResult] = useState<{ comics: number; chapters: number; covers: number; skipped: number } | null>(null)
  const lastClickedComicRef = useRef<number | null>(null)

  async function handleExport() {
    setExporting(true)
    setExportError(null)
    try {
      const token = localStorage.getItem(TOKEN_KEY)
      const params = new URLSearchParams({ format: exportFormat })
      if (exportAllAssignments && exportFormat !== 'csv') params.set('include_all_assignments', 'true')
      const res = await fetch(`/api/settings/export?${params}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) {
        const text = await res.text().catch(() => res.statusText)
        throw new Error(text)
      }
      const blob = await res.blob()
      const ext = exportFormat === 'otaki' ? 'zip' : exportFormat
      const date = new Date().toISOString().slice(0, 10)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `otaki-backup-${date}.${ext}`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setExportError(extractDetail(err))
    } finally {
      setExporting(false)
    }
  }

  async function handlePreview() {
    const file = importFileRef.current?.files?.[0] ?? null
    if (!file && !importServerPath.trim()) return
    setPreviewing(true)
    setPreviewError(null)
    setPreview(null)
    setPreviewFile(file)
    setSourceResolutions({})
    setComicResolutions({})
    setApplyResult(null)
    setApplyError(null)
    try {
      const form = new FormData()
      if (file) form.append('file', file)
      else form.append('path', importServerPath.trim())
      const token = localStorage.getItem(TOKEN_KEY)
      const res = await fetch('/api/settings/import/preview', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      })
      if (!res.ok) {
        const text = await res.text().catch(() => res.statusText)
        throw new Error(text)
      }
      const data: PreviewResult = await res.json()
      setPreview(data)
      setTimeout(() => previewPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
      const srcRes: Record<number, 'overwrite' | 'skip'> = {}
      for (const c of data.source_conflicts) srcRes[c.backup_id] = 'skip'
      setSourceResolutions(srcRes)
      const comicRes: Record<number, ComicResolution> = {}
      for (const c of data.comic_conflicts) {
        comicRes[c.backup_id] = { backup_id: c.backup_id, action: 'skip' }
      }
      for (const c of data.new_comics) {
        comicRes[c.backup_id] = { backup_id: c.backup_id, action: 'create' }
      }
      setComicResolutions(comicRes)
      setPreviewTab(data.source_conflicts.length + data.comic_conflicts.length > 0 ? 'conflicts' : 'new')
    } catch (err) {
      setPreviewError(extractDetail(err))
    } finally {
      setPreviewing(false)
    }
  }

  async function handleApply() {
    if (!preview) return
    const file = previewFile
    const serverPath = importServerPath.trim()
    if (!file && !serverPath) return
    setApplying(true)
    setApplyError(null)
    setApplyResult(null)
    try {
      const srcRes: SourceResolution[] = preview.source_conflicts.map(c => ({
        backup_id: c.backup_id,
        action: sourceResolutions[c.backup_id] ?? 'skip',
      }))
      const comicRes: ComicResolution[] = [
        ...preview.comic_conflicts.map(c => comicResolutions[c.backup_id] ?? { backup_id: c.backup_id, action: 'skip' }),
        ...preview.new_comics.map(c => comicResolutions[c.backup_id] ?? { backup_id: c.backup_id, action: 'create' }),
      ]
      const form = new FormData()
      if (file) form.append('file', file)
      else form.append('path', serverPath)
      form.append('source_resolutions', JSON.stringify(srcRes))
      form.append('comic_resolutions', JSON.stringify(comicRes))
      const token = localStorage.getItem(TOKEN_KEY)
      const res = await fetch('/api/settings/import/apply', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      })
      if (!res.ok) {
        const text = await res.text().catch(() => res.statusText)
        throw new Error(text)
      }
      const result = await res.json()
      setApplyResult(result)
      setPreview(null)
    } catch (err) {
      setApplyError(extractDetail(err))
    } finally {
      setApplying(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const settingsActionBar = SECTIONS.map(({ id, label, icon }) => (
    <button
      key={id}
      className={`settings-nav-item${activeSection === id ? ' active' : ''}`}
      onClick={() => setActiveSection(id)}
    >
      <i className={`bx ${icon}`} style={{ marginRight: 8, fontSize: 15 }} />{label}
    </button>
  ))

  return (
    <PageLayout title="Settings" actionBar={settingsActionBar}>
      {isLoading && <p style={{ color: 'var(--text-2)' }}>Loading…</p>}
      {error && <p style={{ color: 'var(--danger)', fontSize: 13 }}>{extractDetail(error)}</p>}

      {settings && (
        <>

            {/* Polling */}
            {activeSection === 'polling' && (
              <div className="card" style={{ padding: 24 }}>
                <h2 style={panelHeadingStyle}>Polling</h2>
                <form onSubmit={savePoll}>
                  <div style={fieldStyle}>
                    <label style={labelStyle} htmlFor="poll-days">Default poll interval (days)</label>
                    <p style={fieldHintStyle}>How often Otaki checks for new chapters when no comic-specific override is set.</p>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
                      <input
                        id="poll-days"
                        type="number"
                        min={1}
                        value={pollDays}
                        onChange={e => setPollDays(parseInt(e.target.value, 10) || 1)}
                        className="input"
                        style={{ width: 80 }}
                      />
                      <span style={{ color: 'var(--text-2)', fontSize: 13 }}>days</span>
                    </div>
                  </div>
                  {pollError && <p style={errorStyle}>{pollError}</p>}
                  <button className="btn primary" type="submit" disabled={pollSaving}
                    style={{ opacity: pollSaving ? 0.6 : 1 }}>
                    {pollSaving ? 'Saving…' : 'Save'}
                  </button>
                </form>
              </div>
            )}

            {/* Paths */}
            {activeSection === 'paths' && (
              <div className="card" style={{ padding: 24 }}>
                <h2 style={panelHeadingStyle}>Paths</h2>
                <form onSubmit={savePaths}>
                  <div style={fieldStyle}>
                    <label style={labelStyle} htmlFor="download-path">Download path</label>
                    <p style={fieldHintStyle}>Where Suwayomi stores downloaded CBZ files (staging area).</p>
                    <input
                      id="download-path"
                      type="text"
                      value={downloadPath}
                      onChange={e => setDownloadPath(e.target.value)}
                      className="input"
                      style={{ marginTop: 6 }}
                    />
                  </div>
                  <div style={fieldStyle}>
                    <label style={labelStyle} htmlFor="library-path">Library path</label>
                    <p style={fieldHintStyle}>Final destination for relocated chapters — the directory your reader app points to.</p>
                    <input
                      id="library-path"
                      type="text"
                      value={libraryPath}
                      onChange={e => setLibraryPath(e.target.value)}
                      className="input"
                      style={{ marginTop: 6 }}
                    />
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                    <button className="btn primary" type="submit" disabled={pathsSaving}
                      style={{ opacity: pathsSaving ? 0.6 : 1 }}>
                      {pathsSaving ? 'Saving…' : 'Save'}
                    </button>
                    {pathsError && <span style={{ color: 'var(--danger)', fontSize: 13 }}>{pathsError}</span>}
                  </div>
                </form>

                {/* Chapter naming */}
                <div style={{ marginTop: 28, paddingTop: 24, borderTop: `1px solid var(--border)` }}>
                  <h3 style={{ ...panelHeadingStyle, fontSize: 15 }}>Chapter naming format</h3>
                  <form onSubmit={saveNaming}>
                    <div style={fieldStyle}>
                      <label style={labelStyle} htmlFor="naming-format">Format</label>
                      <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '3px 12px', marginTop: 6 }}>
                        {[
                          ['{title}',   'Comic title'],
                          ['{chapter}', 'Zero-padded chapter number'],
                          ['{volume}',  'Volume number'],
                          ['{year}',    'Publication year'],
                          ['{source}',  'Source name'],
                        ].map(([token, desc]) => (
                          <>
                            <code key={`k-${token}`} style={codeStyle}>{token}</code>
                            <span key={`d-${token}`} style={fieldHintStyle}>{desc}</span>
                          </>
                        ))}
                      </div>
                      <input
                        id="naming-format"
                        type="text"
                        value={namingFormat}
                        onChange={e => setNamingFormat(e.target.value)}
                        className="input"
                        style={{ marginTop: 6 }}
                      />
                    </div>
                    <div style={{ marginBottom: 16 }}>
                      <span style={labelStyle}>Preview</span>
                      <div style={{
                        marginTop: 6, padding: '8px 12px',
                        background: 'var(--surface-2)', borderRadius: 'var(--radius-sm)',
                        fontFamily: 'monospace', fontSize: 13, color: 'var(--text)',
                      }}>{namingPreview}.cbz</div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                      <button className="btn primary" type="submit" disabled={namingSaving}
                        style={{ opacity: namingSaving ? 0.6 : 1 }}>
                        {namingSaving ? 'Saving…' : 'Save'}
                      </button>
                      {namingError && <span style={{ color: 'var(--danger)', fontSize: 13 }}>{namingError}</span>}
                    </div>
                  </form>
                </div>
              </div>
            )}

            {/* Relocation */}
            {activeSection === 'relocation' && (
              <div className="card" style={{ padding: 24 }}>
                <h2 style={panelHeadingStyle}>Relocation strategy</h2>
                <p style={{ fontSize: 13, color: 'var(--text-2)', marginBottom: 20 }}>
                  Controls how Otaki moves chapter files from the Suwayomi download directory to your library.
                </p>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {RELOCATION_OPTIONS.map(opt => (
                    <button
                      key={opt.value}
                      type="button"
                      className={`relocation-card${relocationStrategy === opt.value ? ' selected' : ''}`}
                      onClick={() => {
                        setRelocationStrategy(opt.value)
                        saveRelocation(opt.value)
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                        <span style={{
                          width: 14, height: 14, borderRadius: '50%', flexShrink: 0, border: '2px solid',
                          borderColor: relocationStrategy === opt.value ? 'var(--accent)' : 'var(--border)',
                          background: relocationStrategy === opt.value ? 'var(--accent)' : 'transparent',
                        }} />
                        <strong style={{ fontSize: 14, color: 'var(--text)' }}>{opt.label}</strong>
                        {opt.recommended && (
                          <span style={{
                            fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 10,
                            background: 'var(--accent-soft)', color: 'var(--accent)',
                          }}>Recommended</span>
                        )}
                      </div>
                      <p style={{ fontSize: 13, color: 'var(--text-2)', margin: 0, paddingLeft: 24 }}>{opt.description}</p>
                    </button>
                  ))}
                </div>

                {relocationSaving && <p style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 8 }}>Saving…</p>}
                {relocationError && <p style={errorStyle}>{relocationError}</p>}
              </div>
            )}

            {/* Suwayomi */}
            {activeSection === 'suwayomi' && (
              <div className="card" style={{ padding: 24 }}>
                <h2 style={panelHeadingStyle}>Suwayomi connection</h2>
                <form onSubmit={saveConnection}>
                  <div style={fieldStyle}>
                    <label style={labelStyle} htmlFor="conn-url">Server URL</label>
                    <input
                      id="conn-url"
                      type="url"
                      value={connUrl}
                      onChange={e => setConnUrl(e.target.value)}
                      required
                      className="input"
                      style={{ marginTop: 4 }}
                    />
                  </div>
                  <div style={fieldStyle}>
                    <label style={labelStyle} htmlFor="conn-username">Username</label>
                    <input
                      id="conn-username"
                      type="text"
                      value={connUsername}
                      onChange={e => setConnUsername(e.target.value)}
                      className="input"
                      style={{ marginTop: 4 }}
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
                      className="input"
                      style={{ marginTop: 4 }}
                    />
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                    <button className="btn primary" type="submit" disabled={connSaving}
                      style={{ opacity: connSaving ? 0.6 : 1 }}>
                      {connSaving ? 'Saving…' : 'Save & Test'}
                    </button>
                    {connError && <span style={{ color: 'var(--danger)', fontSize: 13 }}>{connError}</span>}
                    {connSuccess && <span style={{ color: 'var(--success)', fontSize: 13 }}>Connected successfully.</span>}
                  </div>
                </form>
              </div>
            )}

            {/* Backup */}
            {activeSection === 'backup' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {/* Export card */}
                <div className="card" style={{ padding: 24 }}>
                  <h2 style={panelHeadingStyle}>Export backup</h2>
                  <div style={fieldStyle}>
                    <label style={labelStyle}>Format</label>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
                      {(['otaki', 'json', 'csv'] as const).map(f => (
                        <label key={f} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
                          <input type="radio" checked={exportFormat === f} onChange={() => setExportFormat(f)} />
                          <span>
                            <strong style={{ color: 'var(--text)' }}>
                              {f === 'otaki' ? 'Otaki zip (full)' : f === 'json' ? 'JSON (no assets)' : 'CSV (read-only)'}
                            </strong>
                            <span style={{ color: 'var(--text-2)', marginLeft: 6 }}>
                              {f === 'otaki' ? '— includes covers, chapter assignments, all settings' : f === 'json' ? '— structured data only, no cover images' : '— spreadsheet view, no import support'}
                            </span>
                          </span>
                        </label>
                      ))}
                    </div>
                  </div>
                  <div style={{ marginBottom: 16, opacity: exportFormat === 'csv' ? 0.4 : 1 }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: exportFormat === 'csv' ? 'not-allowed' : 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={exportAllAssignments}
                        disabled={exportFormat === 'csv'}
                        onChange={e => setExportAllAssignments(e.target.checked)}
                      />
                      <span style={{ color: 'var(--text)' }}>Include inactive chapter assignments (upgrade candidates)</span>
                    </label>
                    <p style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 4, marginLeft: 24, visibility: exportFormat === 'csv' ? 'visible' : 'hidden' }}>Not available for CSV exports.</p>
                  </div>
                  {exportError && <p style={errorStyle}>{exportError}</p>}
                  <button className="btn primary" onClick={handleExport} disabled={exporting}
                    style={{ opacity: exporting ? 0.6 : 1 }}>
                    {exporting ? 'Preparing…' : 'Download backup'}
                  </button>
                </div>

                {/* Import card */}
                <div ref={importCardRef} className="card" style={{ padding: 24 }}>
                  <h2 style={panelHeadingStyle}>Import backup</h2>
                  <div style={fieldStyle}>
                    <label style={labelStyle}>Backup file (.zip or .json)</label>
                    <input ref={importFileRef} type="file" accept=".zip,.json"
                      style={{ fontSize: 13, marginTop: 6, color: 'var(--text)' }} />
                  </div>
                  <div style={fieldStyle}>
                    <label style={labelStyle} htmlFor="import-path">Or load from server path</label>
                    <input
                      id="import-path"
                      type="text"
                      value={importServerPath}
                      onChange={e => setImportServerPath(e.target.value)}
                      placeholder="/data/otaki-backup-2026-04-08.zip"
                      className="input"
                      style={{ marginTop: 4 }}
                    />
                  </div>
                  {previewError && <p style={errorStyle}>{previewError}</p>}
                  <button className="btn" onClick={handlePreview} disabled={previewing}
                    style={{ opacity: previewing ? 0.6 : 1 }}>
                    {previewing ? 'Analysing…' : 'Preview import'}
                  </button>

                  {/* Preview panel */}
                  {preview && (
                    <div ref={previewPanelRef} style={{ marginTop: 20, border: `1px solid var(--border)`, borderRadius: 'var(--radius)' }}>
                      {/* Preview header with Import button */}
                      <div style={{ padding: '12px 16px', borderBottom: `1px solid var(--border)`, display: 'flex', alignItems: 'center', gap: 12 }}>
                        <button className="btn primary" onClick={handleApply} disabled={applying}
                          style={{ opacity: applying ? 0.6 : 1 }}>
                          {applying ? 'Importing…' : 'Import'}
                        </button>
                        <button
                          onClick={() => {
                            setPreview(null)
                            setTimeout(() => importCardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
                          }}
                          style={{ background: 'none', border: 'none', color: 'var(--text-2)', cursor: 'pointer', fontSize: 13, fontFamily: 'inherit' }}
                        >New</button>
                        {applyError && <span style={{ color: 'var(--danger)', fontSize: 13 }}>{applyError}</span>}
                      </div>

                      {/* Tabs */}
                      <div style={{ display: 'flex', borderBottom: `1px solid var(--border)` }}>
                        {(['conflicts', 'new', 'all'] as const).map(tab => {
                          const badge = tab === 'conflicts'
                            ? preview.source_conflicts.length + preview.comic_conflicts.length
                            : tab === 'new'
                              ? preview.new_sources.length + preview.new_comics.length
                              : preview.totals.sources + preview.totals.comics
                          return (
                            <button
                              key={tab}
                              onClick={() => setPreviewTab(tab)}
                              style={{
                                background: 'none', border: 'none',
                                borderBottom: previewTab === tab ? `2px solid var(--accent)` : '2px solid transparent',
                                padding: '10px 16px', cursor: 'pointer', fontSize: 13,
                                fontWeight: previewTab === tab ? 600 : 400,
                                color: previewTab === tab ? 'var(--accent)' : 'var(--text-2)',
                                fontFamily: 'inherit',
                              }}
                            >
                              {tab.charAt(0).toUpperCase() + tab.slice(1)}
                              {badge > 0 && (
                                <span style={{
                                  marginLeft: 6, borderRadius: 10, padding: '1px 6px', fontSize: 11,
                                  background: tab === 'conflicts' && badge > 0 ? 'var(--warning)' : 'var(--surface-2)',
                                  color: tab === 'conflicts' && badge > 0 ? '#fff' : 'var(--text)',
                                }}>{badge}</span>
                              )}
                            </button>
                          )
                        })}
                      </div>

                      <div style={{ padding: 16 }}>
                        {/* Conflicts tab */}
                        {previewTab === 'conflicts' && (
                          <>
                            {preview.source_conflicts.length === 0 && preview.comic_conflicts.length === 0 && (
                              <p style={{ color: 'var(--text-2)', fontSize: 13, margin: 0 }}>No conflicts — everything is new.</p>
                            )}
                            {preview.source_conflicts.length > 0 && (
                              <div style={{ marginBottom: 20 }}>
                                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: 'var(--text)' }}>Source conflicts</div>
                                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, tableLayout: 'fixed', userSelect: 'none' }}>
                                  <colgroup>
                                    <col style={{ width: '25%' }} />
                                    <col style={{ width: '30%' }} />
                                    <col style={{ width: '30%' }} />
                                    <col style={{ width: '7.5%' }} />
                                    <col style={{ width: '7.5%' }} />
                                  </colgroup>
                                  <thead>
                                    <tr style={{ borderBottom: `1px solid var(--border)` }}>
                                      <th style={conflictThStyle}>Source</th>
                                      <th style={conflictThStyle}>Import settings</th>
                                      <th style={conflictThStyle}>Existing settings</th>
                                      <th style={{ ...conflictThStyle, textAlign: 'center' }}>Overwrite</th>
                                      <th style={{ ...conflictThStyle, textAlign: 'center' }}>Keep existing</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {preview.source_conflicts.map(c => (
                                      <tr key={c.backup_id} style={{ borderBottom: `1px solid var(--border)` }}>
                                        <td style={conflictTdStyle}><strong style={{ color: 'var(--text)' }}>{c.name}</strong></td>
                                        <td style={{ ...conflictTdStyle, color: 'var(--text-2)' }}>priority {c.import_priority}, {c.import_enabled ? 'enabled' : 'disabled'}</td>
                                        <td style={{ ...conflictTdStyle, color: 'var(--text-2)' }}>priority {c.existing_priority}, {c.existing_enabled ? 'enabled' : 'disabled'}</td>
                                        <td style={{ ...conflictTdStyle, textAlign: 'center' }}>
                                          <RadioDot checked={sourceResolutions[c.backup_id] === 'overwrite'} onClick={() => setSourceResolutions(p => ({ ...p, [c.backup_id]: 'overwrite' }))} />
                                        </td>
                                        <td style={{ ...conflictTdStyle, textAlign: 'center' }}>
                                          <RadioDot checked={sourceResolutions[c.backup_id] === 'skip'} onClick={() => setSourceResolutions(p => ({ ...p, [c.backup_id]: 'skip' }))} />
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}
                            {preview.comic_conflicts.length > 0 && (() => {
                              const conflicts = preview.comic_conflicts
                              function setAllComicAction(action: 'merge' | 'create' | 'skip') {
                                setComicResolutions(p => {
                                  const next = { ...p }
                                  for (const c of conflicts) {
                                    next[c.backup_id] = { backup_id: c.backup_id, action, target_id: action === 'merge' ? c.existing_id : undefined }
                                  }
                                  return next
                                })
                              }
                              function handleComicRowClick(e: React.MouseEvent, idx: number, action: 'merge' | 'create' | 'skip') {
                                const c = conflicts[idx]
                                if (e.shiftKey && lastClickedComicRef.current !== null) {
                                  const from = Math.min(lastClickedComicRef.current, idx)
                                  const to = Math.max(lastClickedComicRef.current, idx)
                                  setComicResolutions(p => {
                                    const next = { ...p }
                                    for (let i = from; i <= to; i++) {
                                      const ci = conflicts[i]
                                      next[ci.backup_id] = { backup_id: ci.backup_id, action, target_id: action === 'merge' ? ci.existing_id : undefined }
                                    }
                                    return next
                                  })
                                } else if (e.ctrlKey || e.metaKey) {
                                  setComicResolutions(p => ({ ...p, [c.backup_id]: { backup_id: c.backup_id, action, target_id: action === 'merge' ? c.existing_id : undefined } }))
                                } else {
                                  setComicResolutions(p => ({ ...p, [c.backup_id]: { backup_id: c.backup_id, action, target_id: action === 'merge' ? c.existing_id : undefined } }))
                                }
                                lastClickedComicRef.current = idx
                              }
                              return (
                                <div>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                                    <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginRight: 4 }}>Comic conflicts</span>
                                    <span style={{ fontSize: 12, color: 'var(--text-3)' }}>Set all:</span>
                                    {(['merge', 'create', 'skip'] as const).map(action => (
                                      <button key={action} type="button" className="btn"
                                        style={{ padding: '3px 10px', fontSize: 12 }}
                                        onClick={() => setAllComicAction(action)}>
                                        {action === 'merge' ? 'Merge all' : action === 'create' ? 'Import all as new' : 'Skip all'}
                                      </button>
                                    ))}
                                    <span style={{ fontSize: 11, color: 'var(--text-3)', marginLeft: 4 }}>Shift+click or Ctrl+click for multi-select</span>
                                  </div>
                                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, tableLayout: 'fixed', userSelect: 'none' }}>
                                    <colgroup>
                                      <col style={{ width: '35%' }} />
                                      <col style={{ width: '30%' }} />
                                      <col style={{ width: '10%' }} />
                                      <col style={{ width: '15%' }} />
                                      <col style={{ width: '10%' }} />
                                    </colgroup>
                                    <thead>
                                      <tr style={{ borderBottom: `1px solid var(--border)` }}>
                                        <th style={conflictThStyle}>Title</th>
                                        <th style={conflictThStyle}>Import info</th>
                                        <th style={{ ...conflictThStyle, textAlign: 'center' }}>Merge</th>
                                        <th style={{ ...conflictThStyle, textAlign: 'center' }}>Import as new</th>
                                        <th style={{ ...conflictThStyle, textAlign: 'center' }}>Skip</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {conflicts.map((c, idx) => {
                                        const res = comicResolutions[c.backup_id] ?? { backup_id: c.backup_id, action: 'skip' as const }
                                        return (
                                          <tr key={c.backup_id} style={{ borderBottom: `1px solid var(--border)` }}>
                                            <td style={conflictTdStyle}>
                                              <strong style={{ color: 'var(--text)' }}>{c.title}</strong>
                                              <input
                                                type="text"
                                                placeholder={`Rename (default: "${c.title}")`}
                                                value={res.title_override ?? ''}
                                                onChange={e => setComicResolutions(p => ({ ...p, [c.backup_id]: { ...res, title_override: e.target.value || undefined } }))}
                                                className="input"
                                                style={{ fontSize: 12, marginTop: 4, visibility: res.action === 'create' ? 'visible' : 'hidden' }}
                                                onClick={e => e.stopPropagation()}
                                              />
                                              {c.import_has_cover && c.existing_has_cover && (
                                                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer', color: 'var(--text-2)', marginTop: 4, visibility: res.action === 'merge' ? 'visible' : 'hidden' }}
                                                  onClick={e => e.stopPropagation()}>
                                                  <input type="checkbox" checked={res.replace_cover ?? false}
                                                    onChange={e => setComicResolutions(p => ({ ...p, [c.backup_id]: { ...res, replace_cover: e.target.checked } }))} />
                                                  Replace cover
                                                </label>
                                              )}
                                            </td>
                                            <td style={{ ...conflictTdStyle, color: 'var(--text-2)', fontSize: 12 }}>
                                              {c.import_chapters} ch{c.import_aliases > 0 ? `, ${c.import_aliases} aliases` : ''}{c.import_pins > 0 ? `, ${c.import_pins} pins` : ''}{c.import_has_cover ? ', has cover' : ''}
                                            </td>
                                            {(['merge', 'create', 'skip'] as const).map(action => (
                                              <td key={action} style={{ ...conflictTdStyle, textAlign: 'center', cursor: 'pointer' }}
                                                onClick={e => handleComicRowClick(e, idx, action)}>
                                                <RadioDot checked={res.action === action} onClick={() => {}} />
                                              </td>
                                            ))}
                                          </tr>
                                        )
                                      })}
                                    </tbody>
                                  </table>
                                </div>
                              )
                            })()}
                          </>
                        )}

                        {/* New tab */}
                        {previewTab === 'new' && (
                          <>
                            {preview.new_sources.length === 0 && preview.new_comics.length === 0 && (
                              <p style={{ color: 'var(--text-2)', fontSize: 13, margin: 0 }}>No new records.</p>
                            )}
                            {preview.new_sources.length > 0 && (
                              <div style={{ marginBottom: 16 }}>
                                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: 'var(--text)' }}>New sources</div>
                                {preview.new_sources.map(s => (
                                  <div key={s.backup_id} style={{ fontSize: 13, color: 'var(--text)', marginBottom: 4 }}>
                                    {s.name} <span style={{ color: 'var(--text-3)', fontSize: 11 }}>{s.suwayomi_source_id}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                            {preview.new_comics.length > 0 && (
                              <div>
                                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: 'var(--text)' }}>New comics</div>
                                {preview.new_comics.map(c => (
                                  <div key={c.backup_id} style={{ fontSize: 13, color: 'var(--text)', marginBottom: 4 }}>
                                    {c.title}
                                    <span style={{ color: 'var(--text-2)', fontSize: 12, marginLeft: 8 }}>
                                      {c.import_chapters} ch{c.import_aliases > 0 ? `, ${c.import_aliases} aliases` : ''}{c.import_pins > 0 ? `, ${c.import_pins} pins` : ''}{c.import_has_cover ? ', has cover' : ''}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </>
                        )}

                        {/* All tab */}
                        {previewTab === 'all' && (
                          <>
                            <div style={{ fontSize: 13, color: 'var(--text-2)', marginBottom: 12 }}>
                              Backup contains: {preview.totals.sources} sources, {preview.totals.comics} comics, {preview.totals.chapters} chapter assignments, {preview.totals.covers} covers.
                            </div>
                            {[...preview.source_conflicts, ...preview.new_sources].length > 0 && (
                              <div style={{ marginBottom: 12 }}>
                                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4, color: 'var(--text)' }}>Sources</div>
                                {preview.source_conflicts.map(s => (
                                  <div key={s.backup_id} style={{ fontSize: 12, color: 'var(--warning)', marginBottom: 2 }}>
                                    <i className="bx bx-error" style={{ marginRight: 4 }} />{s.name} (conflict)
                                  </div>
                                ))}
                                {preview.new_sources.map(s => (
                                  <div key={s.backup_id} style={{ fontSize: 12, color: 'var(--text)', marginBottom: 2 }}>+ {s.name}</div>
                                ))}
                              </div>
                            )}
                            {[...preview.comic_conflicts, ...preview.new_comics].length > 0 && (
                              <div>
                                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4, color: 'var(--text)' }}>Comics</div>
                                {preview.comic_conflicts.map(c => (
                                  <div key={c.backup_id} style={{ fontSize: 12, color: 'var(--warning)', marginBottom: 2 }}>
                                    <i className="bx bx-error" style={{ marginRight: 4 }} />{c.title} (conflict — {c.import_chapters} ch)
                                  </div>
                                ))}
                                {preview.new_comics.map(c => (
                                  <div key={c.backup_id} style={{ fontSize: 12, color: 'var(--text)', marginBottom: 2 }}>+ {c.title} ({c.import_chapters} ch)</div>
                                ))}
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  )}

                  {applyResult && (
                    <div style={{
                      marginTop: 12, padding: '10px 14px',
                      background: 'var(--accent-soft)', border: `1px solid var(--accent)`,
                      borderRadius: 'var(--radius-sm)', fontSize: 13, color: 'var(--text)',
                    }}>
                      Import complete: {applyResult.comics} comic(s), {applyResult.chapters} chapter(s), {applyResult.covers} cover(s) imported. {applyResult.skipped} record(s) skipped.
                    </div>
                  )}
                </div>
              </div>
            )}

        </>
      )}
    </PageLayout>
  )
}

// ---------------------------------------------------------------------------
// Relocation strategy options
// ---------------------------------------------------------------------------

const RELOCATION_OPTIONS: {
  value: Settings['relocation_strategy']
  label: string
  description: string
  recommended?: boolean
}[] = [
  {
    value: 'auto',
    label: 'Auto (recommended)',
    description: 'Uses a hardlink when Suwayomi staging and the library are on the same filesystem, otherwise falls back to copy. Zero extra disk space when hardlinking; safe copy otherwise.',
    recommended: true,
  },
  {
    value: 'hardlink',
    label: 'Hardlink only',
    description: 'Always hardlinks. Requires staging and library to be on the same filesystem. Fails loudly if they are not. Uses zero extra disk space.',
  },
  {
    value: 'copy',
    label: 'Copy',
    description: 'Always copies the file to the library, then deletes the staging copy after verification. Works across filesystems but uses twice the disk space temporarily.',
  },
  {
    value: 'move',
    label: 'Move',
    description: 'Moves the file from staging to library (same filesystem only). No extra disk space, but the staging copy is gone immediately — no safety net if relocation is interrupted.',
  },
]

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const panelHeadingStyle: React.CSSProperties = {
  fontSize: 16,
  fontWeight: 700,
  color: 'var(--text)',
  margin: '0 0 16px',
}

const fieldStyle: React.CSSProperties = {
  marginBottom: 16,
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 13,
  fontWeight: 600,
  color: 'var(--text)',
}

const fieldHintStyle: React.CSSProperties = {
  fontSize: 12,
  color: 'var(--text-2)',
  margin: '4px 0 0',
}

const errorStyle: React.CSSProperties = {
  color: 'var(--danger)',
  fontSize: 13,
  margin: '4px 0 8px',
}

const conflictThStyle: React.CSSProperties = {
  padding: '6px 10px',
  fontSize: 12,
  fontWeight: 600,
  color: 'var(--text-2)',
  textAlign: 'left',
  whiteSpace: 'nowrap',
}

const conflictTdStyle: React.CSSProperties = {
  padding: '8px 10px',
  verticalAlign: 'middle',
}

function RadioDot({ checked, onClick }: { checked: boolean; onClick: () => void }) {
  return (
    <span
      onClick={onClick}
      style={{
        display: 'inline-block',
        width: 16,
        height: 16,
        borderRadius: '50%',
        border: `2px solid ${checked ? 'var(--accent)' : 'var(--border)'}`,
        background: checked ? 'var(--accent)' : 'transparent',
        cursor: 'pointer',
        transition: 'background 0.18s ease, border-color 0.18s ease',
        flexShrink: 0,
      }}
    />
  )
}

const codeStyle: React.CSSProperties = {
  background: 'var(--surface-2)',
  borderRadius: 3,
  padding: '1px 5px',
  fontFamily: 'monospace',
  fontSize: 12,
  color: 'var(--text)',
}
