import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
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
  chapter_counts: ChapterCounts
  next_poll_at: string | null
}

// ---------------------------------------------------------------------------
// Component
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

  const status = error ? 'unhealthy' : (data?.status ?? 'degraded')
  const color = STATUS_DOT[status] ?? '#94a3b8'

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
        title={`System status: ${status}`}
        style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, padding: '4px 0' }}
      >
        <span style={{ width: 10, height: 10, borderRadius: '50%', background: color, display: 'inline-block' }} />
        <span style={{ fontSize: 13, color: '#555' }}>{status}</span>
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

export default function Library() {
  const navigate = useNavigate()
  const { data: comics, isLoading, error } = useQuery({
    queryKey: ['comics'],
    queryFn: () => apiFetch<ComicListItem[]>('/api/requests'),
  })

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>Library</h1>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <HealthBadge />
          <button onClick={() => navigate('/search')} style={linkButtonStyle}>Search</button>
          <button onClick={() => navigate('/sources')} style={linkButtonStyle}>Sources</button>
          <button onClick={() => navigate('/settings')} style={linkButtonStyle}>Settings</button>
        </div>
      </div>

      {isLoading && <p>Loading…</p>}

      {error && (
        <p style={{ color: 'red', fontSize: 13 }}>{extractDetail(error)}</p>
      )}

      {!isLoading && !error && comics?.length === 0 && (
        <p style={{ color: '#666' }}>
          No comics yet. Use Search to add your first.
        </p>
      )}

      {comics && comics.length > 0 && (
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
                onMouseEnter={e => {
                  ;(e.currentTarget as HTMLTableRowElement).style.background = '#f5f5f5'
                }}
                onMouseLeave={e => {
                  ;(e.currentTarget as HTMLTableRowElement).style.background = ''
                }}
              >
                <td style={tdStyle}>
                  <img
                    src={`/api/requests/${comic.id}/cover`}
                    alt=""
                    width={48}
                    height={64}
                    style={{ objectFit: 'cover', borderRadius: 4, display: 'block' }}
                    onError={e => {
                      e.currentTarget.style.display = 'none'
                    }}
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
      )}
    </div>
  )
}

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
