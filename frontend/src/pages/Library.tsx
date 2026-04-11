import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { apiFetch, extractDetail } from '../api/client'
import { formatRelative } from '../utils/format'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface HealthResponse {
  status: 'healthy' | 'degraded' | 'unhealthy'
  database: string
  suwayomi: {
    status: string
    url: string | null
    sources: { name: string; enabled: boolean; reachable: boolean }[]
  }
  workers: {
    download_listener: { running: boolean; uptime_seconds: number | null }
    scheduler: {
      running: boolean
      uptime_seconds: number | null
      jobs: { comic_id: number; title: string; next_poll_at: string | null; next_upgrade_at: string | null }[]
    }
  }
}

interface ChapterCounts {
  total: number
  done: number
  downloading: number
  queued: number
  failed: number
}

interface ComicListItem {
  id: number
  title: string
  status: string
  chapter_counts: ChapterCounts
  next_poll_at: string | null
}

interface ComicListPage {
  items: ComicListItem[]
  total: number
  page: number
  per_page: number
}

interface Source {
  id: number
  name: string
  enabled: boolean
}

// ---------------------------------------------------------------------------
// HealthBadge (unchanged)
// ---------------------------------------------------------------------------

const STATUS_DOT: Record<string, string> = {
  healthy: '#22c55e',
  degraded: '#f59e0b',
  unhealthy: '#ef4444',
}

function HealthBadge() {
  const [expanded, setExpanded] = useState(false)
  const { data, error } = useQuery<HealthResponse>({
    queryKey: ['health'],
    queryFn: () => apiFetch<HealthResponse>('/api/health'),
    refetchInterval: 30_000,
    retry: false,
  })

  const status = error ? 'unhealthy' : (data?.status ?? null)
  const color = status ? (STATUS_DOT[status] ?? '#94a3b8') : '#94a3b8'

  function fmt(s: number | null | undefined) {
    if (s == null) return '—'
    const h = Math.floor(s / 3600)
    const m = Math.floor((s % 3600) / 60)
    return h > 0 ? `${h}h ${m}m` : `${m}m`
  }

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={() => setExpanded(v => !v)}
        title={status ? `System status: ${status}` : 'Checking system status…'}
        style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, padding: '4px 0' }}
      >
        <span style={{ width: 10, height: 10, borderRadius: '50%', background: color, display: 'inline-block' }} />
        <span style={{ fontSize: 13, color: '#555' }}>{status ?? '…'}</span>
      </button>
      {expanded && (
        <div style={healthPanelStyle}>
          <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13 }}>System status</div>
          {error || !data ? (
            <div style={{ fontSize: 12, color: '#ef4444' }}>Health check unreachable</div>
          ) : (
            <>
              <Row label="Database" value={data.database} ok={data.database === 'ok'} />
              <Row label="Suwayomi" value={data.suwayomi.status} ok={data.suwayomi.status === 'ok'} />
              {data.suwayomi.sources.map(s => (
                <Row key={s.name} label={`  ${s.name}`} value={s.reachable ? 'reachable' : 'unreachable'} ok={s.reachable} indent />
              ))}
              <Row label="Download listener" value={data.workers.download_listener.running ? `up ${fmt(data.workers.download_listener.uptime_seconds)}` : 'down'} ok={data.workers.download_listener.running} />
              <Row label="Scheduler" value={data.workers.scheduler.running ? `up ${fmt(data.workers.scheduler.uptime_seconds)}` : 'down'} ok={data.workers.scheduler.running} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

function Row({ label, value, ok, indent }: { label: string; value: string; ok: boolean; indent?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4, paddingLeft: indent ? 8 : 0 }}>
      <span style={{ color: '#555' }}>{label}</span>
      <span style={{ color: ok ? '#22c55e' : '#ef4444', fontWeight: 500 }}>{value}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Pagination control
// ---------------------------------------------------------------------------

function Pagination({ page, total, perPage, onChange }: { page: number; total: number; perPage: number; onChange: (p: number) => void }) {
  const totalPages = Math.max(1, Math.ceil(total / perPage))
  if (totalPages <= 1) return null

  const pages: (number | '…')[] = []
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pages.push(i)
  } else {
    pages.push(1)
    if (page > 3) pages.push('…')
    for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) pages.push(i)
    if (page < totalPages - 2) pages.push('…')
    pages.push(totalPages)
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 16 }}>
      <button disabled={page <= 1} onClick={() => onChange(page - 1)} style={pgBtnStyle(false)}>← Prev</button>
      {pages.map((p, i) =>
        p === '…'
          ? <span key={`e${i}`} style={{ padding: '4px 6px', fontSize: 13, color: '#888' }}>…</span>
          : <button key={p} onClick={() => onChange(p as number)} style={pgBtnStyle(p === page)}>{p}</button>
      )}
      <button disabled={page >= totalPages} onClick={() => onChange(page + 1)} style={pgBtnStyle(false)}>Next →</button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const SORT_OPTIONS = [
  { value: 'id', label: 'ID' },
  { value: 'title', label: 'Title' },
  { value: 'library_title', label: 'Sort Title' },
  { value: 'status', label: 'Status' },
  { value: 'source', label: 'Source' },
]

export default function Library() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const page = parseInt(searchParams.get('page') ?? '1', 10) || 1
  const perPage = parseInt(searchParams.get('per_page') ?? '25', 10) || 25
  const status = searchParams.get('status') ?? ''
  const sourceId = searchParams.get('source_id') ? parseInt(searchParams.get('source_id')!, 10) : null
  const sortBy = searchParams.get('sort_by') ?? 'id'
  const sortDir = searchParams.get('sort_dir') ?? 'asc'

  // Debounced search
  const [searchInput, setSearchInput] = useState(searchParams.get('search') ?? '')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const search = searchParams.get('search') ?? ''

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setSearchParams(prev => {
        const next = new URLSearchParams(prev)
        if (searchInput) next.set('search', searchInput); else next.delete('search')
        next.set('page', '1')
        return next
      })
    }, 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [searchInput])

  function set(key: string, value: string | null) {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (value) next.set(key, value); else next.delete(key)
      if (key !== 'page') next.set('page', '1')
      return next
    })
  }

  const url = new URL('/api/requests', window.location.origin)
  url.searchParams.set('page', String(page))
  url.searchParams.set('per_page', String(perPage))
  if (search) url.searchParams.set('search', search)
  if (status) url.searchParams.set('status', status)
  if (sourceId != null) url.searchParams.set('source_id', String(sourceId))
  url.searchParams.set('sort_by', sortBy)
  url.searchParams.set('sort_dir', sortDir)

  const { data, isLoading, error } = useQuery<ComicListPage>({
    queryKey: ['comics', page, perPage, search, status, sourceId, sortBy, sortDir],
    queryFn: () => apiFetch<ComicListPage>(url.pathname + url.search),
  })

  const { data: sources = [] } = useQuery<Source[]>({
    queryKey: ['sources'],
    queryFn: () => apiFetch<Source[]>('/api/sources'),
  })

  const comics = data?.items ?? []
  const total = data?.total ?? 0

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>Library</h1>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <HealthBadge />
          <button onClick={() => navigate('/search')} style={linkButtonStyle}>Search</button>
          <button onClick={() => navigate('/sources')} style={linkButtonStyle}>Sources</button>
          <button onClick={() => navigate('/settings')} style={linkButtonStyle}>Settings</button>
        </div>
      </div>

      {/* Filter / sort bar */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 16, alignItems: 'center' }}>
        <input
          type="search"
          placeholder="Search titles…"
          value={searchInput}
          onChange={e => setSearchInput(e.target.value)}
          style={inputStyle}
        />

        <div style={{ display: 'flex', gap: 4 }}>
          {(['', 'tracking', 'complete'] as const).map(s => (
            <button
              key={s}
              onClick={() => set('status', s || null)}
              style={filterBtnStyle(status === s)}
            >
              {s === '' ? 'All' : s.charAt(0).toUpperCase() + s.slice(1)}
            </button>
          ))}
        </div>

        <select
          value={sourceId ?? ''}
          onChange={e => set('source_id', e.target.value || null)}
          style={selectStyle}
        >
          <option value="">All sources</option>
          {sources.map(s => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>

        <select
          value={sortBy}
          onChange={e => set('sort_by', e.target.value)}
          style={selectStyle}
        >
          {SORT_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        <button
          onClick={() => set('sort_dir', sortDir === 'asc' ? 'desc' : 'asc')}
          style={filterBtnStyle(false)}
          title="Toggle sort direction"
        >
          {sortDir === 'asc' ? '↑ Asc' : '↓ Desc'}
        </button>

        <select
          value={perPage}
          onChange={e => { set('per_page', e.target.value); set('page', '1') }}
          style={selectStyle}
        >
          {[25, 50, 100].map(n => <option key={n} value={n}>{n} / page</option>)}
        </select>
      </div>

      {isLoading && <p>Loading…</p>}

      {error && (
        <p style={{ color: 'red', fontSize: 13 }}>{extractDetail(error)}</p>
      )}

      {!isLoading && !error && comics.length === 0 && (
        <p style={{ color: '#666' }}>
          {search || status || sourceId ? 'No comics match your filters.' : 'No comics yet. Use Search to add your first.'}
        </p>
      )}

      {comics.length > 0 && (
        <>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ textAlign: 'left', borderBottom: '2px solid #ddd' }}>
                <th style={thStyle}>Cover</th>
                <th style={thStyle}>Title</th>
                <th style={thStyle}>Progress</th>
                <th style={thStyle}>Next poll</th>
              </tr>
            </thead>
            <tbody>
              {comics.map(comic => (
                <tr
                  key={comic.id}
                  onClick={() => navigate(`/comics/${comic.id}`)}
                  style={rowStyle}
                  onMouseEnter={e => { (e.currentTarget as HTMLTableRowElement).style.background = '#f5f5f5' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLTableRowElement).style.background = '' }}
                >
                  <td style={tdStyle}>
                    <img
                      src={`/api/requests/${comic.id}/cover`}
                      alt=""
                      width={48}
                      height={64}
                      style={{ objectFit: 'cover', borderRadius: 4, display: 'block' }}
                      onError={e => { e.currentTarget.style.display = 'none' }}
                    />
                  </td>
                  <td style={tdStyle}>{comic.title}</td>
                  <td style={{ ...tdStyle, color: '#555' }}>
                    {comic.chapter_counts.done} / {comic.chapter_counts.total} chapters
                  </td>
                  <td style={{ ...tdStyle, color: '#555' }}>
                    {formatRelative(comic.next_poll_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
            <span style={{ fontSize: 13, color: '#888' }}>{total} comic{total !== 1 ? 's' : ''}</span>
            <Pagination
              page={page}
              total={total}
              perPage={perPage}
              onChange={p => set('page', String(p))}
            />
          </div>
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const thStyle: React.CSSProperties = {
  padding: '8px 12px',
  fontSize: 13,
  fontWeight: 600,
  color: '#444',
}

const tdStyle: React.CSSProperties = {
  padding: '10px 12px',
  borderBottom: '1px solid #eee',
  verticalAlign: 'middle',
}

const rowStyle: React.CSSProperties = {
  cursor: 'pointer',
}

const linkButtonStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#0070f3',
  cursor: 'pointer',
  fontSize: 14,
  padding: 0,
}

const healthPanelStyle: React.CSSProperties = {
  position: 'absolute',
  top: '100%',
  right: 0,
  marginTop: 6,
  background: '#fff',
  border: '1px solid #e5e7eb',
  borderRadius: 6,
  padding: '12px 14px',
  minWidth: 240,
  boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
  zIndex: 100,
}

const inputStyle: React.CSSProperties = {
  padding: '5px 10px',
  border: '1px solid #ddd',
  borderRadius: 4,
  fontSize: 13,
  width: 180,
}

const selectStyle: React.CSSProperties = {
  padding: '5px 8px',
  border: '1px solid #ddd',
  borderRadius: 4,
  fontSize: 13,
  background: '#fff',
}

function filterBtnStyle(active: boolean): React.CSSProperties {
  return {
    padding: '5px 10px',
    border: `1px solid ${active ? '#0070f3' : '#ddd'}`,
    borderRadius: 4,
    background: active ? '#eff6ff' : '#fff',
    color: active ? '#0070f3' : '#444',
    cursor: 'pointer',
    fontSize: 13,
    fontWeight: active ? 600 : 400,
  }
}

function pgBtnStyle(active: boolean): React.CSSProperties {
  return {
    padding: '4px 8px',
    border: `1px solid ${active ? '#0070f3' : '#ddd'}`,
    borderRadius: 4,
    background: active ? '#0070f3' : '#fff',
    color: active ? '#fff' : '#444',
    cursor: 'pointer',
    fontSize: 13,
  }
}
