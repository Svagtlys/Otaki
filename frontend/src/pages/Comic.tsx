import { useState, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { apiFetch, streamFetch, extractDetail } from '../api/client'
import { formatRelative } from '../utils/format'

const TOKEN_KEY = 'otaki_token'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Chapter {
  assignment_id: number
  chapter_number: number
  volume_number: number | null
  source_id: number
  source_name: string
  download_status: string
  is_active: boolean
  downloaded_at: string | null
  library_path: string | null
  relocation_status: string
}

interface Alias {
  id: number
  title: string
}

interface ComicDetail {
  id: number
  title: string
  library_title: string
  status: string
  poll_override_days: number | null
  upgrade_override_days: number | null
  inferred_cadence_days: number | null
  next_poll_at: string | null
  next_upgrade_check_at: string | null
  last_upgrade_check_at: string | null
  aliases: Alias[]
  chapters: Chapter[]
}

interface SourcePin {
  id: number
  source_id: number
  source_name: string
  suwayomi_manga_id: string
  pinned_at: string
}

interface Source {
  id: number
  name: string
  enabled: boolean
}

interface PinSearchResult {
  title: string
  source_id: number
  source_name: string
  suwayomi_manga_id: string
  url: string
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Comic() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const comicId = parseInt(id ?? '0', 10)

  const [discovering, setDiscovering] = useState(false)
  const [discoverError, setDiscoverError] = useState<string | null>(null)
  const [discoverResult, setDiscoverResult] = useState<string | null>(null)

  const [reprocessing, setReprocessing] = useState(false)
  const [reprocessError, setReprocessError] = useState<string | null>(null)
  const [reprocessResult, setReprocessResult] = useState<string | null>(null)
  const [reprocessLog, setReprocessLog] = useState<{ chapter_number: number; action: string }[]>([])

  // Pin management state
  const [pinsOpen, setPinsOpen] = useState(false)
  const [removedPinIds, setRemovedPinIds] = useState<Set<number>>(new Set())
  const [pendingPins, setPendingPins] = useState<{ source_id: number; source_name: string; suwayomi_manga_id: string }[]>([])
  const [pinSaving, setPinSaving] = useState(false)
  const [pinError, setPinError] = useState<string | null>(null)
  const [pinResult, setPinResult] = useState<string | null>(null)
  // Add-pin search sub-state
  const [pinSearchSourceId, setPinSearchSourceId] = useState<number | ''>('')
  const [pinSearchQuery, setPinSearchQuery] = useState('')
  const [pinSearchResults, setPinSearchResults] = useState<PinSearchResult[]>([])
  const [pinSearching, setPinSearching] = useState(false)
  const pinAbortRef = useRef<AbortController | null>(null)

  const [coverFormOpen, setCoverFormOpen] = useState(false)
  const [coverTab, setCoverTab] = useState<'url' | 'file'>('url')
  const [coverUrl, setCoverUrl] = useState('')
  const [coverFile, setCoverFile] = useState<File | null>(null)
  const [coverSubmitting, setCoverSubmitting] = useState(false)
  const [coverError, setCoverError] = useState<string | null>(null)

  const [editOpen, setEditOpen] = useState(false)
  const [editLibraryTitle, setEditLibraryTitle] = useState('')
  const [editPollDays, setEditPollDays] = useState('')
  const [editPollClear, setEditPollClear] = useState(false)
  const [editUpgradeDays, setEditUpgradeDays] = useState('')
  const [editUpgradeClear, setEditUpgradeClear] = useState(false)
  const [editSubmitting, setEditSubmitting] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)

  const [newAlias, setNewAlias] = useState('')
  const [pendingAliasAdds, setPendingAliasAdds] = useState<string[]>([])
  const [pendingAliasDeletes, setPendingAliasDeletes] = useState<Set<number>>(new Set())
  const [aliasError, setAliasError] = useState<string | null>(null)

  const { data: comic, isLoading, error } = useQuery({
    queryKey: ['comic', comicId],
    queryFn: () => apiFetch<ComicDetail>(`/api/requests/${comicId}`),
    enabled: comicId > 0,
  })

  const { data: pins = [] } = useQuery<SourcePin[]>({
    queryKey: ['comic-pins', comicId],
    queryFn: () => apiFetch<SourcePin[]>(`/api/requests/${comicId}/pins`),
    enabled: comicId > 0 && pinsOpen,
  })

  const { data: sources = [] } = useQuery<Source[]>({
    queryKey: ['sources'],
    queryFn: () => apiFetch<Source[]>('/api/sources'),
    enabled: pinsOpen,
  })

  async function handleReprocess() {
    setReprocessing(true)
    setReprocessError(null)
    setReprocessResult(null)
    setReprocessLog([])
    try {
      let queued = 0, processed = 0, skipped = 0
      await streamFetch(
        `/api/requests/${comicId}/reprocess`,
        { method: 'POST' },
        (data) => {
          if (data === '[DONE]') return
          try {
            const ev = JSON.parse(data)
            if (ev.type === 'error') {
              setReprocessError(ev.detail)
            } else if (ev.type === 'chapter') {
              setReprocessLog(prev => [...prev, { chapter_number: ev.chapter_number, action: ev.action }])
            } else if (ev.type === 'done') {
              queued = ev.queued
              processed = ev.processed
              skipped = ev.skipped
            }
          } catch {
            // ignore malformed SSE line
          }
        },
      )
      const parts = []
      if (processed > 0) parts.push(`${processed} processed`)
      if (queued > 0) parts.push(`${queued} queued for download`)
      if (skipped > 0) parts.push(`${skipped} already in progress`)
      setReprocessResult(parts.length > 0 ? parts.join(', ') + '.' : 'Nothing to do.')
      await queryClient.invalidateQueries({ queryKey: ['comic', comicId] })
    } catch (err) {
      setReprocessError(extractDetail(err))
    } finally {
      setReprocessing(false)
    }
  }

  async function handleDiscover() {
    setDiscovering(true)
    setDiscoverError(null)
    setDiscoverResult(null)
    try {
      const res = await apiFetch<{ new_chapters: number }>(`/api/requests/${comicId}/discover`, { method: 'POST' })
      setDiscoverResult(res.new_chapters > 0 ? `Found ${res.new_chapters} new chapter(s) — downloads queued.` : 'No new chapters found.')
      await queryClient.invalidateQueries({ queryKey: ['comic', comicId] })
      await queryClient.invalidateQueries({ queryKey: ['comics'] })
    } catch (err) {
      setDiscoverError(extractDetail(err))
    } finally {
      setDiscovering(false)
    }
  }

  function openPins() {
    setPinsOpen(true)
    setRemovedPinIds(new Set())
    setPendingPins([])
    setPinError(null)
    setPinResult(null)
    setPinSearchSourceId('')
    setPinSearchQuery('')
    setPinSearchResults([])
  }

  function removeSavedPin(pinId: number) {
    setRemovedPinIds(prev => new Set([...prev, pinId]))
  }

  function removePendingPin(idx: number) {
    setPendingPins(prev => prev.filter((_, i) => i !== idx))
  }

  async function handlePinSearch() {
    if (!pinSearchSourceId || !pinSearchQuery.trim()) return
    pinAbortRef.current?.abort()
    const controller = new AbortController()
    pinAbortRef.current = controller
    setPinSearching(true)
    setPinSearchResults([])
    const results: PinSearchResult[] = []
    try {
      await streamFetch(
        `/api/search/stream?q=${encodeURIComponent(pinSearchQuery.trim())}`,
        { method: 'GET' },
        (data) => {
          if (data === '[DONE]') return
          try {
            const payload = JSON.parse(data)
            if (payload.results) {
              for (const r of payload.results) {
                if (r.source_id === pinSearchSourceId) results.push(r)
              }
              setPinSearchResults([...results])
            }
          } catch { /* ignore */ }
        },
        controller.signal,
      )
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setPinError(extractDetail(err))
    } finally {
      setPinSearching(false)
    }
  }

  function stagePinFromResult(r: PinSearchResult) {
    const alreadyPinned = pins
      .filter(p => !removedPinIds.has(p.id))
      .some(p => p.source_id === r.source_id && p.suwayomi_manga_id === r.suwayomi_manga_id)
    const alreadyPending = pendingPins.some(
      p => p.source_id === r.source_id && p.suwayomi_manga_id === r.suwayomi_manga_id
    )
    if (!alreadyPinned && !alreadyPending) {
      setPendingPins(prev => [...prev, {
        source_id: r.source_id,
        source_name: r.source_name,
        suwayomi_manga_id: r.suwayomi_manga_id,
      }])
    }
    setPinSearchResults([])
    setPinSearchQuery('')
  }

  async function handleSavePins() {
    setPinSaving(true)
    setPinError(null)
    setPinResult(null)
    const kept = pins.filter(p => !removedPinIds.has(p.id)).map(p => ({
      source_id: p.source_id,
      suwayomi_manga_id: p.suwayomi_manga_id,
    }))
    const newPins = pendingPins.map(p => ({
      source_id: p.source_id,
      suwayomi_manga_id: p.suwayomi_manga_id,
    }))
    try {
      await apiFetch(`/api/requests/${comicId}/pins`, {
        method: 'PUT',
        body: JSON.stringify({ pins: [...kept, ...newPins] }),
      })
      await queryClient.invalidateQueries({ queryKey: ['comic-pins', comicId] })
      setRemovedPinIds(new Set())
      setPendingPins([])
      setPinResult('Pins saved. Run Re-discover to pick up any newly available chapters.')
    } catch (err) {
      setPinError(extractDetail(err))
    } finally {
      setPinSaving(false)
    }
  }

  async function handleCoverSubmit() {
    setCoverSubmitting(true)
    setCoverError(null)
    try {
      if (coverTab === 'url') {
        await apiFetch(`/api/requests/${comicId}/cover`, {
          method: 'POST',
          body: JSON.stringify({ url: coverUrl }),
        })
      } else if (coverFile) {
        const formData = new FormData()
        formData.append('file', coverFile)
        const token = localStorage.getItem(TOKEN_KEY)
        const headers: Record<string, string> = {}
        if (token) headers['Authorization'] = `Bearer ${token}`
        const res = await fetch(`/api/requests/${comicId}/cover`, { method: 'POST', headers, body: formData })
        if (!res.ok) {
          const text = await res.text().catch(() => res.statusText)
          throw new Error(text)
        }
      }
      setCoverFormOpen(false)
      setCoverUrl('')
      setCoverFile(null)
      await queryClient.invalidateQueries({ queryKey: ['comic', comicId] })
    } catch (err) {
      setCoverError(extractDetail(err))
    } finally {
      setCoverSubmitting(false)
    }
  }

  function openEdit() {
    if (!comic) return
    setEditLibraryTitle(comic.library_title)
    setEditPollDays(comic.poll_override_days != null ? String(comic.poll_override_days) : '')
    setEditPollClear(comic.poll_override_days == null)
    setEditUpgradeDays(comic.upgrade_override_days != null ? String(comic.upgrade_override_days) : '')
    setEditUpgradeClear(comic.upgrade_override_days == null)
    setEditError(null)
    setAliasError(null)
    setPendingAliasAdds([])
    setPendingAliasDeletes(new Set())
    setNewAlias('')
    setEditOpen(true)
  }

  async function handleEditSubmit() {
    if (!comic) return
    setEditSubmitting(true)
    setEditError(null)
    const patch: Record<string, unknown> = {}
    if (editLibraryTitle !== comic.library_title) patch.library_title = editLibraryTitle
    if (editPollClear && comic.poll_override_days != null) {
      patch.poll_override_days = null
    } else if (!editPollClear) {
      const pollNum = parseFloat(editPollDays)
      if (!isNaN(pollNum) && pollNum !== comic.poll_override_days) patch.poll_override_days = pollNum
    }
    if (editUpgradeClear && comic.upgrade_override_days != null) {
      patch.upgrade_override_days = null
    } else if (!editUpgradeClear) {
      const upgradeNum = parseFloat(editUpgradeDays)
      if (!isNaN(upgradeNum) && upgradeNum !== comic.upgrade_override_days) patch.upgrade_override_days = upgradeNum
    }
    try {
      await apiFetch(`/api/requests/${comicId}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      })
      await Promise.all([
        ...Array.from(pendingAliasDeletes).map(id =>
          apiFetch(`/api/requests/${comicId}/aliases/${id}`, { method: 'DELETE' })
        ),
        ...(newAlias.trim()
          ? [apiFetch(`/api/requests/${comicId}/aliases`, { method: 'POST', body: JSON.stringify({ title: newAlias.trim() }) })]
          : []
        ),
        ...pendingAliasAdds.map(title =>
          apiFetch(`/api/requests/${comicId}/aliases`, { method: 'POST', body: JSON.stringify({ title }) })
        ),
      ])
      setEditOpen(false)
      await queryClient.invalidateQueries({ queryKey: ['comic', comicId] })
    } catch (err) {
      setEditError(extractDetail(err))
    } finally {
      setEditSubmitting(false)
    }
  }

  async function handleStatusToggle() {
    if (!comic) return
    const newStatus = comic.status === 'tracking' ? 'complete' : 'tracking'
    try {
      await apiFetch(`/api/requests/${comicId}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: newStatus }),
      })
      await queryClient.invalidateQueries({ queryKey: ['comic', comicId] })
    } catch (err) {
      setEditError(extractDetail(err))
    }
  }

  function handleStagedAddAlias() {
    const title = newAlias.trim()
    if (!title) return
    setPendingAliasAdds(prev => [...prev, title])
    setNewAlias('')
  }

  function handleStagedDeleteAlias(aliasId: number) {
    setPendingAliasDeletes(prev => new Set([...prev, aliasId]))
  }

  function handleRemoveStagedAdd(title: string) {
    setPendingAliasAdds(prev => prev.filter(t => t !== title))
  }

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>{comic?.title ?? 'Comic'}</h1>
        <button onClick={() => navigate('/library')} style={linkButtonStyle}>← Library</button>
      </div>

      {isLoading && <p>Loading…</p>}

      {error && <p style={{ color: 'red' }}>{extractDetail(error)}</p>}

      {comic && (
        <>
          {/* Header: cover + metadata */}
          <div style={{ display: 'flex', gap: 24, marginBottom: 32 }}>
            <div style={{ flexShrink: 0 }}>
              <img
                src={`/api/requests/${comic.id}/cover`}
                alt=""
                width={160}
                height={220}
                style={{ objectFit: 'cover', borderRadius: 4, display: 'block' }}
                onError={e => { e.currentTarget.style.display = 'none' }}
              />
              <button onClick={() => { setCoverFormOpen(v => !v); setCoverError(null) }} style={{ ...linkButtonStyle, marginTop: 4, fontSize: 12 }}>
                {coverFormOpen ? 'Cancel' : 'Change cover'}
              </button>
              {coverFormOpen && (
                <div style={{ marginTop: 8, minWidth: 260 }}>
                  <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
                    <button onClick={() => setCoverTab('url')} style={coverTab === 'url' ? primaryButtonStyle : secondaryButtonStyle}>URL</button>
                    <button onClick={() => setCoverTab('file')} style={coverTab === 'file' ? primaryButtonStyle : secondaryButtonStyle}>Upload</button>
                  </div>
                  {coverTab === 'url' && (
                    <div style={{ display: 'flex', gap: 6 }}>
                      <input
                        type="url"
                        value={coverUrl}
                        onChange={e => setCoverUrl(e.target.value)}
                        placeholder="https://..."
                        style={{ flex: 1, padding: '6px 10px', fontSize: 13, border: '1px solid #ccc', borderRadius: 4 }}
                      />
                      <button onClick={handleCoverSubmit} disabled={coverSubmitting || !coverUrl} style={{ ...primaryButtonStyle, opacity: (coverSubmitting || !coverUrl) ? 0.6 : 1 }}>
                        {coverSubmitting ? 'Saving…' : 'Save'}
                      </button>
                    </div>
                  )}
                  {coverTab === 'file' && (
                    <div style={{ display: 'flex', gap: 6 }}>
                      <input
                        type="file"
                        accept="image/*"
                        onChange={e => setCoverFile(e.target.files?.[0] ?? null)}
                        style={{ flex: 1, fontSize: 13 }}
                      />
                      <button onClick={handleCoverSubmit} disabled={coverSubmitting || !coverFile} style={{ ...primaryButtonStyle, opacity: (coverSubmitting || !coverFile) ? 0.6 : 1 }}>
                        {coverSubmitting ? 'Saving…' : 'Save'}
                      </button>
                    </div>
                  )}
                  {coverError && <p style={{ fontSize: 13, color: 'red', marginTop: 6 }}>{coverError}</p>}
                </div>
              )}
            </div>
            <div>
              <p style={metaRowStyle}><span style={metaLabelStyle}>Library title</span>{comic.library_title}</p>
              <p style={metaRowStyle}><span style={metaLabelStyle}>Status</span>
                {comic.status}
                <button onClick={handleStatusToggle} style={{ ...linkButtonStyle, marginLeft: 8, fontSize: 12 }}>
                  {comic.status === 'tracking' ? 'Mark complete' : 'Resume tracking'}
                </button>
              </p>
              <p style={metaRowStyle}>
                <span style={metaLabelStyle}>Poll interval</span>
                {comic.poll_override_days != null
                  ? `${comic.poll_override_days}d`
                  : comic.inferred_cadence_days != null
                    ? `${comic.inferred_cadence_days.toFixed(1)}d (inferred)`
                    : '7d (default)'}
              </p>
              <p style={metaRowStyle}><span style={metaLabelStyle}>Upgrade interval</span>{comic.upgrade_override_days != null ? `${comic.upgrade_override_days}d` : '(use poll interval)'}</p>
              <p style={metaRowStyle}><span style={metaLabelStyle}>Next poll</span>{formatRelative(comic.next_poll_at)}</p>
              <p style={metaRowStyle}><span style={metaLabelStyle}>Last upgrade check</span>{formatRelative(comic.last_upgrade_check_at)}</p>
              <button onClick={openEdit} style={{ ...linkButtonStyle, fontSize: 12, marginTop: 4 }}>Edit settings</button>
            </div>
          </div>

          {/* Edit form */}
          {editOpen && (
            <div style={{ marginBottom: 24, padding: 16, border: '1px solid #ddd', borderRadius: 6, background: '#fafafa' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <strong style={{ fontSize: 14 }}>Edit settings</strong>
                <button onClick={() => setEditOpen(false)} style={linkButtonStyle}>Cancel</button>
              </div>

              <div style={{ marginBottom: 10 }}>
                <label style={editLabelStyle}>
                  Library title
                  <input
                    type="text"
                    value={editLibraryTitle}
                    onChange={e => setEditLibraryTitle(e.target.value)}
                    style={editInputStyle}
                  />
                </label>
                <p style={{ fontSize: 11, color: '#888', margin: '2px 0 0' }}>
                  Changing this will not rename existing library files.
                </p>
              </div>

              <div style={{ marginBottom: 10 }}>
                <label style={editLabelStyle}>
                  Poll interval (days)
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                    <input
                      type="number"
                      min="0.1"
                      step="0.5"
                      value={editPollClear ? '' : editPollDays}
                      disabled={editPollClear}
                      onChange={e => setEditPollDays(e.target.value)}
                      style={{ ...editInputStyle, width: 100, marginTop: 0, opacity: editPollClear ? 0.5 : 1 }}
                    />
                    <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                      <input
                        type="checkbox"
                        checked={editPollClear}
                        onChange={e => setEditPollClear(e.target.checked)}
                      />
                      Use inferred cadence
                    </label>
                  </div>
                </label>
              </div>

              <div style={{ marginBottom: 12 }}>
                <label style={editLabelStyle}>
                  Upgrade interval (days)
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                    <input
                      type="number"
                      min="0.1"
                      step="0.5"
                      value={editUpgradeClear ? '' : editUpgradeDays}
                      disabled={editUpgradeClear}
                      onChange={e => setEditUpgradeDays(e.target.value)}
                      style={{ ...editInputStyle, width: 100, marginTop: 0, opacity: editUpgradeClear ? 0.5 : 1 }}
                    />
                    <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                      <input
                        type="checkbox"
                        checked={editUpgradeClear}
                        onChange={e => setEditUpgradeClear(e.target.checked)}
                      />
                      Use poll interval
                    </label>
                  </div>
                </label>
              </div>

              {/* Aliases */}
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#444', marginBottom: 6 }}>Aliases</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
                  {(comic.aliases ?? [])
                    .filter(a => !pendingAliasDeletes.has(a.id))
                    .map(a => (
                      <span key={a.id} style={aliasChipStyle}>
                        {a.title}
                        <button
                          onClick={() => handleStagedDeleteAlias(a.id)}
                          style={{ background: 'none', border: 'none', cursor: 'pointer', marginLeft: 4, color: '#888', fontSize: 12, padding: 0 }}
                          aria-label={`Remove alias ${a.title}`}
                        >×</button>
                      </span>
                    ))}
                  {pendingAliasAdds.map(title => (
                    <span key={title} style={{ ...aliasChipStyle, borderStyle: 'dashed', color: '#0070f3' }}>
                      {title}
                      <button
                        onClick={() => handleRemoveStagedAdd(title)}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', marginLeft: 4, color: '#888', fontSize: 12, padding: 0 }}
                        aria-label={`Remove pending alias ${title}`}
                      >×</button>
                    </span>
                  ))}
                  {(comic.aliases ?? []).filter(a => !pendingAliasDeletes.has(a.id)).length === 0 &&
                    pendingAliasAdds.length === 0 && (
                      <span style={{ fontSize: 12, color: '#888' }}>None</span>
                    )}
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <input
                    type="text"
                    placeholder="Add alias…"
                    value={newAlias}
                    onChange={e => setNewAlias(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleStagedAddAlias()}
                    style={{ ...editInputStyle, marginTop: 0, flex: 1 }}
                  />
                  <button
                    onClick={handleStagedAddAlias}
                    disabled={!newAlias.trim()}
                    style={{ ...secondaryButtonStyle, opacity: !newAlias.trim() ? 0.6 : 1 }}
                  >
                    Add
                  </button>
                </div>
                {aliasError && <p style={{ fontSize: 12, color: 'red', marginTop: 4 }}>{aliasError}</p>}
              </div>

              <button
                onClick={handleEditSubmit}
                disabled={editSubmitting}
                style={{ ...primaryButtonStyle, opacity: editSubmitting ? 0.6 : 1 }}
              >
                {editSubmitting ? 'Saving…' : 'Save changes'}
              </button>
              {editError && <p style={{ fontSize: 13, color: 'red', marginTop: 8 }}>{editError}</p>}
            </div>
          )}

          {/* Source pins */}
          <div style={{ marginBottom: 24 }}>
            <button
              onClick={() => pinsOpen ? setPinsOpen(false) : openPins()}
              style={{ ...linkButtonStyle, fontSize: 12 }}
            >
              {pinsOpen ? 'Close pin manager' : 'Manage source pins'}
            </button>
            {pinsOpen && (
              <div style={{ marginTop: 12, padding: 16, border: '1px solid #ddd', borderRadius: 6, background: '#fafafa' }}>
                <div style={{ fontSize: 13, color: '#666', marginBottom: 12 }}>
                  Pins tell Otaki to fetch chapters directly by manga ID instead of searching by title.
                  Useful when a title has an unusual name on a source.
                </div>

                {/* Current pins */}
                <div style={{ marginBottom: 12 }}>
                  {pins.filter(p => !removedPinIds.has(p.id)).length === 0 && pendingPins.length === 0 ? (
                    <div style={{ fontSize: 12, color: '#888' }}>No pins set.</div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      {pins.filter(p => !removedPinIds.has(p.id)).map(p => (
                        <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                          <span style={pinChipStyle}>{p.source_name}</span>
                          <span style={{ fontFamily: 'monospace', color: '#444' }}>{p.suwayomi_manga_id}</span>
                          <button onClick={() => removeSavedPin(p.id)} style={removeBtnStyle} aria-label="Remove pin">✕</button>
                        </div>
                      ))}
                      {pendingPins.map((p, i) => (
                        <div key={`pending-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                          <span style={{ ...pinChipStyle, borderStyle: 'dashed', color: '#0070f3' }}>{p.source_name}</span>
                          <span style={{ fontFamily: 'monospace', color: '#444' }}>{p.suwayomi_manga_id}</span>
                          <button onClick={() => removePendingPin(i)} style={removeBtnStyle} aria-label="Remove pending pin">✕</button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Add pin search */}
                <div style={{ marginBottom: 12, borderTop: '1px solid #eee', paddingTop: 12 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: '#444', marginBottom: 6 }}>Add a pin</div>
                  <div style={{ display: 'flex', gap: 6, marginBottom: 6, flexWrap: 'wrap' }}>
                    <select
                      value={pinSearchSourceId}
                      onChange={e => setPinSearchSourceId(e.target.value ? Number(e.target.value) : '')}
                      style={{ padding: '5px 8px', fontSize: 12, border: '1px solid #ccc', borderRadius: 4 }}
                    >
                      <option value="">Select source…</option>
                      {sources.filter(s => s.enabled).map(s => (
                        <option key={s.id} value={s.id}>{s.name}</option>
                      ))}
                    </select>
                    <input
                      type="text"
                      placeholder="Search title…"
                      value={pinSearchQuery}
                      onChange={e => setPinSearchQuery(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && handlePinSearch()}
                      style={{ flex: 1, minWidth: 140, padding: '5px 8px', fontSize: 12, border: '1px solid #ccc', borderRadius: 4 }}
                    />
                    <button
                      onClick={handlePinSearch}
                      disabled={!pinSearchSourceId || !pinSearchQuery.trim() || pinSearching}
                      style={{ ...secondaryButtonStyle, fontSize: 12, padding: '5px 10px', opacity: (!pinSearchSourceId || !pinSearchQuery.trim() || pinSearching) ? 0.6 : 1 }}
                    >
                      {pinSearching ? 'Searching…' : 'Search'}
                    </button>
                  </div>
                  {pinSearchResults.length > 0 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 180, overflowY: 'auto', border: '1px solid #eee', borderRadius: 4, padding: 6 }}>
                      {pinSearchResults.map(r => (
                        <button
                          key={r.url}
                          onClick={() => stagePinFromResult(r)}
                          style={{ background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', padding: '4px 6px', borderRadius: 4, fontSize: 12, display: 'flex', flexDirection: 'column' }}
                          onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = '#f0f4ff' }}
                          onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = 'none' }}
                        >
                          <span style={{ fontWeight: 500 }}>{r.title}</span>
                          <span style={{ color: '#888', fontSize: 11 }}>ID: {r.suwayomi_manga_id}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Save */}
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <button
                    onClick={handleSavePins}
                    disabled={pinSaving}
                    style={{ ...primaryButtonStyle, fontSize: 12, padding: '6px 12px', opacity: pinSaving ? 0.6 : 1 }}
                  >
                    {pinSaving ? 'Saving…' : 'Save pins'}
                  </button>
                  <button onClick={() => setPinsOpen(false)} style={{ ...linkButtonStyle, fontSize: 12 }}>Cancel</button>
                </div>
                {pinResult && <p style={{ fontSize: 12, color: '#555', marginTop: 8 }}>{pinResult}</p>}
                {pinError && <p style={{ fontSize: 12, color: 'red', marginTop: 8 }}>{pinError}</p>}
              </div>
            )}
          </div>

          {/* Re-discover / Reprocess */}
          <div style={{ display: 'flex', gap: 12, marginBottom: 24, flexWrap: 'wrap', alignItems: 'flex-start' }}>
            {comic.chapters.length === 0 && (
              <div>
                <button
                  onClick={handleDiscover}
                  disabled={discovering}
                  style={{ ...primaryButtonStyle, opacity: discovering ? 0.6 : 1 }}
                >
                  {discovering ? 'Searching sources…' : 'Re-discover chapters'}
                </button>
                {discoverResult && <p style={{ fontSize: 13, color: '#555', marginTop: 8 }}>{discoverResult}</p>}
                {discoverError && <p style={{ fontSize: 13, color: 'red', marginTop: 8 }}>{discoverError}</p>}
              </div>
            )}
            {comic.chapters.length > 0 && (
              <div>
                <button
                  onClick={handleReprocess}
                  disabled={reprocessing}
                  style={{ ...secondaryButtonStyle, opacity: reprocessing ? 0.6 : 1 }}
                >
                  {reprocessing ? 'Reprocessing…' : 'Reprocess chapters'}
                </button>
                {(reprocessing || reprocessLog.length > 0) && (
                  <div style={reprocessLogStyle}>
                    {reprocessLog.map((entry, i) => (
                      <div key={i}>
                        {entry.action === 'processed' ? '✓' : entry.action === 'queued' ? '⟳' : '—'}
                        {' '}Ch {entry.chapter_number} — {entry.action}
                      </div>
                    ))}
                    {reprocessing && <div style={{ color: '#999' }}>…</div>}
                  </div>
                )}
                {reprocessResult && <p style={{ fontSize: 13, color: '#555', marginTop: 8 }}>{reprocessResult}</p>}
                {reprocessError && <p style={{ fontSize: 13, color: 'red', marginTop: 8 }}>{reprocessError}</p>}
              </div>
            )}
          </div>

          {/* Chapter table */}
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ textAlign: 'left', borderBottom: '2px solid #ddd' }}>
                <th style={thStyle}>Chapter</th>
                <th style={thStyle}>Volume</th>
                <th style={thStyle}>Source</th>
                <th style={thStyle}>Status</th>
                <th style={thStyle}>Relocation</th>
                <th style={thStyle}>Library path</th>
              </tr>
            </thead>
            <tbody>
              {comic.chapters.map(ch => (
                <tr key={ch.assignment_id} style={{ borderBottom: '1px solid #eee' }}>
                  <td style={tdStyle}>{ch.chapter_number}</td>
                  <td style={tdStyle}>{ch.volume_number ?? '—'}</td>
                  <td style={tdStyle}>{ch.source_name}</td>
                  <td style={tdStyle}>{ch.download_status}</td>
                  <td style={tdStyle}>{ch.relocation_status}</td>
                  <td style={{ ...tdStyle, maxWidth: 280, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
                    {ch.library_path ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}

const linkButtonStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#0070f3',
  cursor: 'pointer',
  fontSize: 14,
  padding: 0,
}

const metaRowStyle: React.CSSProperties = {
  margin: '0 0 6px 0',
  fontSize: 14,
}

const metaLabelStyle: React.CSSProperties = {
  fontWeight: 600,
  marginRight: 8,
  color: '#444',
}

const primaryButtonStyle: React.CSSProperties = {
  padding: '8px 16px',
  fontSize: 14,
  background: '#0070f3',
  color: '#fff',
  border: 'none',
  borderRadius: 4,
  cursor: 'pointer',
}

const secondaryButtonStyle: React.CSSProperties = {
  padding: '8px 16px',
  fontSize: 14,
  background: '#f0f0f0',
  color: '#333',
  border: '1px solid #ccc',
  borderRadius: 4,
  cursor: 'pointer',
}

const thStyle: React.CSSProperties = {
  padding: '8px 12px',
  fontSize: 13,
  fontWeight: 600,
  color: '#444',
}

const tdStyle: React.CSSProperties = {
  padding: '10px 12px',
  verticalAlign: 'middle',
  fontSize: 13,
}

const editLabelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 13,
  fontWeight: 600,
  color: '#444',
}

const editInputStyle: React.CSSProperties = {
  display: 'block',
  marginTop: 4,
  padding: '6px 10px',
  fontSize: 13,
  border: '1px solid #ccc',
  borderRadius: 4,
  width: '100%',
  boxSizing: 'border-box',
}

const aliasChipStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  padding: '2px 8px',
  fontSize: 12,
  background: '#f0f0f0',
  border: '1px solid #ddd',
  borderRadius: 12,
  color: '#555',
}

const pinChipStyle: React.CSSProperties = {
  display: 'inline-block',
  padding: '1px 6px',
  fontSize: 11,
  background: '#f0f0f0',
  border: '1px solid #ddd',
  borderRadius: 10,
  color: '#555',
  flexShrink: 0,
}

const removeBtnStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  color: '#aaa',
  fontSize: 12,
  padding: 0,
  lineHeight: 1,
}

const reprocessLogStyle: React.CSSProperties = {
  maxHeight: 120,
  overflowY: 'auto',
  fontSize: 12,
  fontFamily: 'monospace',
  background: '#f8f8f8',
  border: '1px solid #eee',
  borderRadius: 4,
  padding: '6px 10px',
  marginTop: 6,
}
