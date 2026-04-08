import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, extractDetail } from '../api/client'

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

  // Export state
  const [exportFormat, setExportFormat] = useState<'otaki' | 'json' | 'csv'>('otaki')
  const [exportAllAssignments, setExportAllAssignments] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  // Import state
  const importFileRef = useRef<HTMLInputElement>(null)
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
      // Default resolutions
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
          <section style={sectionStyle}>
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

          {/* Export */}
          <section style={sectionStyle}>
            <h2 style={sectionHeadingStyle}>Export backup</h2>
            <div style={fieldStyle}>
              <label style={labelStyle}>Format</label>
              <div style={{ display: 'flex', gap: 12, fontSize: 13 }}>
                {(['otaki', 'json', 'csv'] as const).map(f => (
                  <label key={f} style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                    <input type="radio" checked={exportFormat === f} onChange={() => setExportFormat(f)} />
                    {f === 'otaki' ? 'Otaki zip (full)' : f === 'json' ? 'JSON (no assets)' : 'CSV (read-only)'}
                  </label>
                ))}
              </div>
            </div>
            {exportFormat !== 'csv' && (
              <div style={{ marginBottom: 12 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={exportAllAssignments}
                    onChange={e => setExportAllAssignments(e.target.checked)}
                  />
                  Include inactive chapter assignments (upgrade candidates)
                </label>
              </div>
            )}
            {exportError && <p style={errorStyle}>{exportError}</p>}
            <button onClick={handleExport} disabled={exporting}>
              {exporting ? 'Preparing…' : 'Download'}
            </button>
          </section>

          {/* Import */}
          <section style={{ marginBottom: 0 }}>
            <h2 style={sectionHeadingStyle}>Import backup</h2>
            <div style={fieldStyle}>
              <label style={labelStyle}>Backup file (.zip)</label>
              <input ref={importFileRef} type="file" accept=".zip,.json" style={{ fontSize: 13 }} />
            </div>
            <div style={fieldStyle}>
              <label style={labelStyle} htmlFor="import-path">Or load from server path</label>
              <input
                id="import-path"
                type="text"
                value={importServerPath}
                onChange={e => setImportServerPath(e.target.value)}
                placeholder="/data/otaki-backup-2026-04-08.zip"
                style={inputStyle}
              />
            </div>
            {previewError && <p style={errorStyle}>{previewError}</p>}
            <button onClick={handlePreview} disabled={previewing}>
              {previewing ? 'Analysing…' : 'Preview'}
            </button>

            {/* Preview panel */}
            {preview && (
              <div style={{ marginTop: 20, border: '1px solid #ddd', borderRadius: 6 }}>
                {/* Tabs */}
                <div style={{ display: 'flex', borderBottom: '1px solid #ddd' }}>
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
                          background: 'none',
                          border: 'none',
                          borderBottom: previewTab === tab ? '2px solid #0070f3' : '2px solid transparent',
                          padding: '10px 16px',
                          cursor: 'pointer',
                          fontSize: 13,
                          fontWeight: previewTab === tab ? 600 : 400,
                          color: previewTab === tab ? '#0070f3' : '#555',
                        }}
                      >
                        {tab.charAt(0).toUpperCase() + tab.slice(1)}
                        {badge > 0 && (
                          <span style={{ marginLeft: 6, background: tab === 'conflicts' && badge > 0 ? '#f59e0b' : '#e5e7eb', borderRadius: 10, padding: '1px 6px', fontSize: 11 }}>
                            {badge}
                          </span>
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
                        <p style={{ color: '#888', fontSize: 13, margin: 0 }}>No conflicts — everything is new.</p>
                      )}
                      {preview.source_conflicts.length > 0 && (
                        <div style={{ marginBottom: 16 }}>
                          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Source conflicts</div>
                          {preview.source_conflicts.map(c => (
                            <div key={c.backup_id} style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 13, marginBottom: 8, flexWrap: 'wrap' }}>
                              <span style={{ fontWeight: 500, minWidth: 140 }}>{c.name}</span>
                              <span style={{ color: '#888', fontSize: 12 }}>
                                import: priority {c.import_priority}, {c.import_enabled ? 'enabled' : 'disabled'} →
                                existing: priority {c.existing_priority}, {c.existing_enabled ? 'enabled' : 'disabled'}
                              </span>
                              <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                                <input type="radio" checked={sourceResolutions[c.backup_id] === 'overwrite'} onChange={() => setSourceResolutions(p => ({ ...p, [c.backup_id]: 'overwrite' }))} />
                                Overwrite
                              </label>
                              <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                                <input type="radio" checked={sourceResolutions[c.backup_id] === 'skip'} onChange={() => setSourceResolutions(p => ({ ...p, [c.backup_id]: 'skip' }))} />
                                Keep existing
                              </label>
                            </div>
                          ))}
                        </div>
                      )}
                      {preview.comic_conflicts.length > 0 && (
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Comic conflicts (same title already in library)</div>
                          {preview.comic_conflicts.map(c => {
                            const res = comicResolutions[c.backup_id] ?? { backup_id: c.backup_id, action: 'skip' }
                            return (
                              <div key={c.backup_id} style={{ marginBottom: 14, paddingBottom: 14, borderBottom: '1px solid #f0f0f0' }}>
                                <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 6 }}>
                                  {c.title}
                                  <span style={{ fontWeight: 400, color: '#888', marginLeft: 8, fontSize: 12 }}>
                                    import: {c.import_chapters} ch, {c.import_aliases} aliases, {c.import_pins} pins
                                    {c.import_has_cover ? ', has cover' : ''}
                                  </span>
                                </div>
                                <div style={{ display: 'flex', gap: 16, fontSize: 13, flexWrap: 'wrap' }}>
                                  {(['merge', 'create', 'skip'] as const).map(action => (
                                    <label key={action} style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                                      <input
                                        type="radio"
                                        checked={res.action === action}
                                        onChange={() => setComicResolutions(p => ({ ...p, [c.backup_id]: { ...res, action, target_id: action === 'merge' ? c.existing_id : undefined } }))}
                                      />
                                      {action === 'merge' ? `Merge into existing (id ${c.existing_id})` : action === 'create' ? 'Import as new' : 'Skip'}
                                    </label>
                                  ))}
                                </div>
                                {res.action === 'create' && (
                                  <div style={{ marginTop: 6 }}>
                                    <input
                                      type="text"
                                      placeholder={`Rename (optional, default: "${c.title}")`}
                                      value={res.title_override ?? ''}
                                      onChange={e => setComicResolutions(p => ({ ...p, [c.backup_id]: { ...res, title_override: e.target.value || undefined } }))}
                                      style={{ ...inputStyle, fontSize: 12 }}
                                    />
                                  </div>
                                )}
                                {res.action === 'merge' && c.import_has_cover && c.existing_has_cover && (
                                  <div style={{ marginTop: 6 }}>
                                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer' }}>
                                      <input
                                        type="checkbox"
                                        checked={res.replace_cover ?? false}
                                        onChange={e => setComicResolutions(p => ({ ...p, [c.backup_id]: { ...res, replace_cover: e.target.checked } }))}
                                      />
                                      Replace existing cover with imported cover
                                    </label>
                                  </div>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </>
                  )}

                  {/* New tab */}
                  {previewTab === 'new' && (
                    <>
                      {preview.new_sources.length === 0 && preview.new_comics.length === 0 && (
                        <p style={{ color: '#888', fontSize: 13, margin: 0 }}>No new records.</p>
                      )}
                      {preview.new_sources.length > 0 && (
                        <div style={{ marginBottom: 16 }}>
                          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>New sources</div>
                          {preview.new_sources.map(s => (
                            <div key={s.backup_id} style={{ fontSize: 13, color: '#444', marginBottom: 4 }}>{s.name} <span style={{ color: '#888', fontSize: 11 }}>{s.suwayomi_source_id}</span></div>
                          ))}
                        </div>
                      )}
                      {preview.new_comics.length > 0 && (
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>New comics</div>
                          {preview.new_comics.map(c => (
                            <div key={c.backup_id} style={{ fontSize: 13, color: '#444', marginBottom: 4 }}>
                              {c.title}
                              <span style={{ color: '#888', fontSize: 12, marginLeft: 8 }}>
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
                      <div style={{ fontSize: 13, color: '#666', marginBottom: 12 }}>
                        Backup contains: {preview.totals.sources} sources, {preview.totals.comics} comics, {preview.totals.chapters} chapter assignments, {preview.totals.covers} covers.
                      </div>
                      {[...preview.source_conflicts, ...preview.new_sources.map(s => ({ ...s, _new: true }))].length > 0 && (
                        <div style={{ marginBottom: 12 }}>
                          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Sources</div>
                          {preview.source_conflicts.map(s => (
                            <div key={s.backup_id} style={{ fontSize: 12, color: '#444', marginBottom: 2 }}>⚠ {s.name} (conflict)</div>
                          ))}
                          {preview.new_sources.map(s => (
                            <div key={s.backup_id} style={{ fontSize: 12, color: '#444', marginBottom: 2 }}>+ {s.name}</div>
                          ))}
                        </div>
                      )}
                      {[...preview.comic_conflicts, ...preview.new_comics].length > 0 && (
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Comics</div>
                          {preview.comic_conflicts.map(c => (
                            <div key={c.backup_id} style={{ fontSize: 12, color: '#444', marginBottom: 2 }}>⚠ {c.title} (conflict — {c.import_chapters} ch)</div>
                          ))}
                          {preview.new_comics.map(c => (
                            <div key={c.backup_id} style={{ fontSize: 12, color: '#444', marginBottom: 2 }}>+ {c.title} ({c.import_chapters} ch)</div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>

                {/* Apply footer */}
                <div style={{ padding: '12px 16px', borderTop: '1px solid #eee', display: 'flex', alignItems: 'center', gap: 12 }}>
                  <button onClick={handleApply} disabled={applying}>
                    {applying ? 'Importing…' : 'Import'}
                  </button>
                  <button onClick={() => setPreview(null)} style={{ background: 'none', border: 'none', color: '#888', cursor: 'pointer', fontSize: 13 }}>Cancel</button>
                  {applyError && <span style={{ color: 'red', fontSize: 13 }}>{applyError}</span>}
                </div>
              </div>
            )}

            {applyResult && (
              <div style={{ marginTop: 12, padding: '10px 14px', background: '#f0fdf4', border: '1px solid #86efac', borderRadius: 4, fontSize: 13 }}>
                Import complete: {applyResult.comics} comic(s), {applyResult.chapters} chapter(s), {applyResult.covers} cover(s) imported. {applyResult.skipped} record(s) skipped.
              </div>
            )}
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
