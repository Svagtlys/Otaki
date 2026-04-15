import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { apiFetch, extractDetail } from '../api/client'
import { formatRelative } from '../utils/format'
import PageLayout from '../components/PageLayout'
import Pagination from '../components/Pagination'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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
// ListCoverCell — fixed-size cover cell for table rows
// ---------------------------------------------------------------------------

function ListCoverCell({ comicId }: { comicId: number }) {
  const [imgState, setImgState] = useState<'idle' | 'ok' | 'missing' | 'error'>('idle')

  function handleError() {
    const token = localStorage.getItem('otaki_token')
    fetch(`/api/requests/${comicId}/cover`, {
      method: 'HEAD',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(r => setImgState(r.status === 404 ? 'missing' : 'error'))
      .catch(() => setImgState('error'))
  }

  return (
    <div style={{
      width: 48, height: 64, flexShrink: 0, position: 'relative',
      background: 'var(--surface-2)', borderRadius: 4,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: 'var(--text-3)', fontSize: 20,
    }}>
      {imgState !== 'ok' && <i className={`bx ${imgState === 'error' ? 'bx-image-alt' : 'bx-book-open'}`} />}
      <img
        src={`/api/requests/${comicId}/cover`}
        alt=""
        onLoad={() => setImgState('ok')}
        onError={handleError}
        style={{
          position: 'absolute', inset: 0, width: '100%', height: '100%',
          objectFit: 'cover', borderRadius: 4,
          display: imgState === 'ok' ? 'block' : 'none',
        }}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// CoverCard
// ---------------------------------------------------------------------------

function CoverCard({ comic, onClick }: { comic: ComicListItem; onClick: () => void }) {
  // 'idle' = not yet tried, 'ok' = loaded, 'missing' = 404 (no cover set), 'error' = other failure
  const [imgState, setImgState] = useState<'idle' | 'ok' | 'missing' | 'error'>('idle')

  function handleError() {
    const token = localStorage.getItem('otaki_token')
    fetch(`/api/requests/${comic.id}/cover`, {
      method: 'HEAD',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(r => setImgState(r.status === 404 ? 'missing' : 'error'))
      .catch(() => setImgState('error'))
  }

  const placeholder = imgState === 'error' ? 'bx-image-alt' : 'bx-book-open'

  return (
    <button
      className="cover-card"
      onClick={onClick}
      aria-label={`View ${comic.title}`}
      style={{
        appearance: 'none',
        WebkitAppearance: 'none',
        background: 'none',
        border: 'none',
        padding: 0,
        margin: 0,
        font: 'inherit',
        cursor: 'pointer',
        textAlign: 'left',
        color: 'inherit',
        display: 'block',
      }}
    >
      <div className="cover-image">
        {imgState !== 'ok' && <i className={`bx ${placeholder}`} />}
        <img
          src={`/api/requests/${comic.id}/cover`}
          alt=""
          onLoad={() => setImgState('ok')}
          onError={handleError}
          style={{ display: imgState === 'ok' ? 'block' : 'none' }}
        />
      </div>
      <div className="cover-title">{comic.title}</div>
      <div className="cover-sub">{comic.chapter_counts.done} / {comic.chapter_counts.total} ch</div>
    </button>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function Library() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [gridView, setGridView] = useState(true)
  const [searchInput, setSearchInput] = useState(searchParams.get('search') ?? '')

  const page     = Number(searchParams.get('page') ?? '1')
  const perPage  = Number(searchParams.get('per_page') ?? '25')
  const search   = searchParams.get('search') ?? ''
  const status   = searchParams.get('status') ?? ''
  const sourceId = searchParams.get('source_id') ?? ''
  const sortBy   = searchParams.get('sort_by') ?? 'id'
  const sortDir  = searchParams.get('sort_dir') ?? 'asc'

  function set(updates: Record<string, string>) {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      for (const [k, v] of Object.entries(updates)) {
        if (v) next.set(k, v); else next.delete(k)
      }
      return next
    })
  }

  // Debounce search input
  useEffect(() => {
    const t = setTimeout(() => {
      set({ search: searchInput, page: '1' })
    }, 300)
    return () => clearTimeout(t)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput])

  // Sources for filter dropdown
  const { data: sources } = useQuery<Source[]>({
    queryKey: ['sources'],
    queryFn: () => apiFetch<Source[]>('/api/sources'),
  })

  // Comics
  const params = new URLSearchParams({
    page: String(page), per_page: String(perPage),
    ...(search     && { search }),
    ...(status     && { status }),
    ...(sourceId   && { source_id: sourceId }),
    ...(sortBy     && { sort_by: sortBy }),
    ...(sortDir    && { sort_dir: sortDir }),
  })

  const { data, isLoading, error } = useQuery<ComicListPage>({
    queryKey: ['comics', page, perPage, search, status, sourceId, sortBy, sortDir],
    queryFn: () => apiFetch<ComicListPage>(`/api/requests?${params}`),
  })

  const comics = data?.items ?? []
  const total  = data?.total ?? 0

  const STATUS_OPTIONS = [
    { value: '',         label: 'All' },
    { value: 'tracking', label: 'Tracking' },
    { value: 'complete', label: 'Complete' },
  ]

  const SORT_OPTIONS = [
    { value: 'id',            label: 'ID' },
    { value: 'title',         label: 'Title' },
    { value: 'library_title', label: 'Sort title' },
    { value: 'status',        label: 'Status' },
    { value: 'source',        label: 'Source' },
  ]

  const libraryActionBar = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, width: '100%' }}>
      {/* Row 1: search */}
      <input
        className="input"
        placeholder="Search comics…"
        value={searchInput}
        onChange={e => setSearchInput(e.target.value)}
        style={{ fontSize: 15, width: '100%' }}
        aria-label="Search comics"
      />

      {/* Row 2: filters + navigation + view */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {/* Status chips */}
        <div style={{ display: 'flex', gap: 4 }}>
          {STATUS_OPTIONS.map(o => (
            <button
              key={o.value}
              className={`chip${status === o.value ? ' active' : ''}`}
              onClick={() => set({ status: o.value, page: '1' })}
            >{o.label}</button>
          ))}
        </div>

        {/* Source select */}
        {sources && sources.length > 0 && (
          <select
            className="select"
            value={sourceId}
            onChange={e => set({ source_id: e.target.value, page: '1' })}
            aria-label="Filter by source"
          >
            <option value="">All sources</option>
            {sources.map(s => (
              <option key={s.id} value={String(s.id)}>{s.name}</option>
            ))}
          </select>
        )}

        {/* Sort */}
        <div style={{ display: 'flex', gap: 4 }}>
          <select
            className="select"
            value={sortBy}
            onChange={e => set({ sort_by: e.target.value, page: '1' })}
            aria-label="Sort by"
          >
            {SORT_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <button
            className="btn"
            onClick={() => set({ sort_dir: sortDir === 'asc' ? 'desc' : 'asc', page: '1' })}
            title="Toggle sort direction"
            aria-label="Toggle sort direction"
          ><i className={`bx bx-${sortDir === 'asc' ? 'up' : 'down'}-arrow-alt`} /></button>
        </div>

        {/* Divider */}
        <div style={{ width: 1, height: 16, background: 'var(--border)', margin: '0 2px' }} />

        {/* Pagination + per-page */}
        {total > 0 && (
          <>
            <Pagination page={page} total={total} perPage={perPage} onChange={p => set({ page: String(p) })} />
            <div style={{ display: 'flex', gap: 4 }}>
              {[25, 50, 100].map(n => (
                <button key={n} className={`btn${perPage === n ? ' primary' : ''}`}
                  style={{ padding: '4px 8px', fontSize: 12 }}
                  onClick={() => set({ per_page: String(n), page: '1' })}>{n}</button>
              ))}
            </div>
            <div style={{ width: 1, height: 16, background: 'var(--border)', margin: '0 2px' }} />
          </>
        )}

        {/* View toggle */}
        <button className={`btn icon${gridView ? ' primary' : ''}`} onClick={() => setGridView(true)} title="Grid view" aria-label="Grid view">
          <i className="bx bx-grid-alt" />
        </button>
        <button className={`btn icon${!gridView ? ' primary' : ''}`} onClick={() => setGridView(false)} title="List view" aria-label="List view">
          <i className="bx bx-list-ul" />
        </button>

        {/* Comic count */}
        {total > 0 && (
          <span style={{ fontSize: 12, color: 'var(--text-3)', marginLeft: 'auto' }}>
            {total} comic{total !== 1 ? 's' : ''}
          </span>
        )}
      </div>
    </div>
  )

  return (
    <PageLayout title="Library" actionBar={libraryActionBar}>
      {/* States */}
      {isLoading && <p style={{ color: 'var(--text-2)' }}>Loading…</p>}
      {error && <p style={{ color: 'var(--danger)', fontSize: 13 }}>{extractDetail(error)}</p>}
      {!isLoading && !error && comics.length === 0 && (
        <p style={{ color: 'var(--text-2)' }}>
          {search || status || sourceId
            ? 'No comics match the current filters.'
            : 'No comics yet. Use Search to add your first.'}
        </p>
      )}

      {/* Grid view */}
      {comics.length > 0 && gridView && (
        <div className="cover-grid">
          {comics.map(comic => (
            <CoverCard key={comic.id} comic={comic} onClick={() => navigate(`/comics/${comic.id}`)} />
          ))}
        </div>
      )}

      {/* List view */}
      {comics.length > 0 && !gridView && (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ textAlign: 'left', borderBottom: `2px solid var(--border)` }}>
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
                onKeyDown={e => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    navigate(`/comics/${comic.id}`)
                  }
                }}
                tabIndex={0}
                aria-label={comic.title}
                style={{ cursor: 'pointer', borderBottom: `1px solid var(--border)` }}
                onMouseEnter={e => { (e.currentTarget as HTMLTableRowElement).style.background = 'var(--surface-2)' }}
                onMouseLeave={e => { (e.currentTarget as HTMLTableRowElement).style.background = '' }}
              >
                <td style={tdStyle}><ListCoverCell comicId={comic.id} /></td>
                <td style={tdStyle}>{comic.title}</td>
                <td style={{ ...tdStyle, color: 'var(--text-2)' }}>
                  {comic.chapter_counts.done} / {comic.chapter_counts.total} chapters
                </td>
                <td style={{ ...tdStyle, color: 'var(--text-2)' }}>
                  {formatRelative(comic.next_poll_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </PageLayout>
  )
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------



const thStyle: React.CSSProperties = {
  padding: '8px 12px',
  fontSize: 13,
  fontWeight: 600,
  color: 'var(--text-2)',
}

const tdStyle: React.CSSProperties = {
  padding: '10px 12px',
  verticalAlign: 'middle',
}
