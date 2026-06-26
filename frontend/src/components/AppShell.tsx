import { useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../api/client'
import { useTheme } from '../context/ThemeContext'

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

// ---------------------------------------------------------------------------
// HealthBadge (moved from Library.tsx)
// ---------------------------------------------------------------------------

const STATUS_COLOR: Record<string, string> = {
  healthy: '#34c759',
  degraded: '#ff9f0a',
  unhealthy: '#ff3b30',
}

function fmt(s: number | null | undefined) {
  if (s == null) return '—'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

function HealthRow({ label, value, ok, indent }: { label: string; value: string; ok: boolean; indent?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4, paddingLeft: indent ? 8 : 0 }}>
      <span style={{ color: 'rgba(255,255,255,0.5)' }}>{label}</span>
      <span style={{ color: ok ? '#34c759' : '#ff3b30', fontWeight: 500 }}>{value}</span>
    </div>
  )
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
  const color = status ? (STATUS_COLOR[status] ?? '#98989f') : '#98989f'
  const dotStyle: React.CSSProperties = {
    width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0,
    ...(status === 'healthy' ? { boxShadow: `0 0 6px ${color}` } : {}),
  }

  return (
    <div style={{ position: 'relative' }}>
      <button
        className="nav-item"
        onClick={() => setExpanded(v => !v)}
        title={status ? `System: ${status}` : 'Checking status…'}
        aria-label={status ? `System status: ${status}` : 'System status: checking…'}
        aria-expanded={expanded}
        aria-controls="health-panel"
      >
        <span style={dotStyle} />
        <span style={{ fontSize: 12 }}>{status ?? '…'}</span>
      </button>
      <div
        id="health-panel"
        aria-live="polite"
        style={{
          display: expanded ? 'block' : 'none',
          position: 'absolute',
          bottom: '100%',
          left: 10,
          marginBottom: 6,
          background: '#1c1c1e',
          border: '1px solid #38383a',
          borderRadius: 8,
          padding: '12px 14px',
          minWidth: 220,
          boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
          zIndex: 200,
        }}>
        <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13, color: '#f5f5f7' }}>System status</div>
        {error || !data ? (
          <div style={{ fontSize: 12, color: '#ff3b30' }}>Health check unreachable</div>
        ) : (
          <>
            <HealthRow label="Database" value={data.database} ok={data.database === 'ok'} />
            <HealthRow label="Suwayomi" value={data.suwayomi.status} ok={data.suwayomi.status === 'ok'} />
            {data.suwayomi.sources.map(s => (
              <HealthRow key={s.name} label={`  ${s.name}`} value={s.reachable ? 'reachable' : 'unreachable'} ok={s.reachable} indent />
            ))}
            <HealthRow
              label="Download listener"
              value={data.workers.download_listener.running ? `up ${fmt(data.workers.download_listener.uptime_seconds)}` : 'down'}
              ok={data.workers.download_listener.running}
            />
            <HealthRow
              label="Scheduler"
              value={data.workers.scheduler.running ? `up ${fmt(data.workers.scheduler.uptime_seconds)}` : 'down'}
              ok={data.workers.scheduler.running}
            />
          </>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Nav structure
// ---------------------------------------------------------------------------

const NAV_ITEMS = [
  { section: 'Library',  items: [{ path: '/library',  icon: 'bx-book-open',  label: 'Library' }] },
  { section: 'Discover', items: [{ path: '/search',   icon: 'bx-search',     label: 'Search'  }] },
  { section: 'Manage',   items: [
    { path: '/sources',  icon: 'bx-plug',             label: 'Sources'  },
    { path: '/settings', icon: 'bx-cog',              label: 'Settings' },
  ]},
]

// ---------------------------------------------------------------------------
// AppShell
// ---------------------------------------------------------------------------

export default function AppShell() {
  const navigate = useNavigate()
  const location = useLocation()
  const { dark, toggle } = useTheme()

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <a href="#main-content" className="skip-link">Skip to main content</a>
      {/* ---------------------------------------------------------------- */}
      {/* Sidebar                                                           */}
      {/* ---------------------------------------------------------------- */}
      <nav className="sidebar" aria-label="Site navigation">
        {/* Logo */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '20px 18px 16px',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
        }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8, flexShrink: 0,
            background: 'linear-gradient(135deg, #007aff 0%, #5856d6 100%)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 16, fontWeight: 700, color: '#fff',
          }}>O</div>
          <span style={{ fontSize: 16, fontWeight: 700, color: '#fff', letterSpacing: '-0.3px' }}>Otaki</span>
          <span style={{
            fontSize: 10, fontWeight: 500, color: 'rgba(255,255,255,0.4)',
            background: 'rgba(255,255,255,0.08)', padding: '1px 5px', borderRadius: 4, marginLeft: 'auto',
          }}>1.2</span>
        </div>

        {/* Nav sections */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 10px' }}>
          {NAV_ITEMS.map(({ section, items }) => (
            <div key={section} style={{ marginBottom: 4 }}>
              <div style={{
                fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase',
                color: 'rgba(255,255,255,0.28)', padding: '10px 8px 4px',
              }}>{section}</div>
              {items.map(({ path, icon, label }) => {
                const active = location.pathname === path || (path !== '/library' && location.pathname.startsWith(path))
                return (
                  <button
                    key={path}
                    className={`nav-item${active ? ' active' : ''}`}
                    onClick={() => navigate(path)}
                  >
                    <i className={`bx ${icon} nav-icon`} />
                    <span>{label}</span>
                  </button>
                )
              })}
            </div>
          ))}
        </div>

        {/* Bottom: health + dark mode toggle */}
        <div style={{ padding: '10px 10px 16px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          <HealthBadge />
          <button
            className="nav-item"
            onClick={toggle}
            style={{ marginTop: 2 }}
            aria-pressed={dark}
          >
            <i className={`bx ${dark ? 'bx-sun' : 'bx-moon'} nav-icon`} />
            <span style={{ fontSize: 12 }}>{dark ? 'Light mode' : 'Dark mode'}</span>
            <div className={`toggle-track${dark ? ' on' : ''}`} style={{ marginLeft: 'auto' }}>
              <div className="toggle-thumb" />
            </div>
          </button>
        </div>
      </nav>

      {/* ---------------------------------------------------------------- */}
      {/* Main content                                                      */}
      {/* ---------------------------------------------------------------- */}
      <main id="main-content" className="main">
        <Outlet />
      </main>
    </div>
  )
}
