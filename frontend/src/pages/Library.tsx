import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { apiFetch, extractDetail } from '../api/client'
import { formatRelative } from '../utils/format'

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
  chapter_counts: ChapterCounts
  next_poll_at: string | null
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

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
        <button onClick={() => navigate('/search')} style={linkButtonStyle}>Search</button>
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
