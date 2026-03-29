import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { apiFetch, extractDetail } from '../api/client'
import { formatRelative } from '../utils/format'

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

interface ComicDetail {
  id: number
  title: string
  status: string
  next_poll_at: string | null
  next_upgrade_check_at: string | null
  last_upgrade_check_at: string | null
  chapters: Chapter[]
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

  const { data: comic, isLoading, error } = useQuery({
    queryKey: ['comic', comicId],
    queryFn: () => apiFetch<ComicDetail>(`/api/requests/${comicId}`),
    enabled: comicId > 0,
  })

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
            <img
              src={`/api/requests/${comic.id}/cover`}
              alt=""
              width={48}
              height={64}
              style={{ objectFit: 'cover', borderRadius: 4, flexShrink: 0 }}
              onError={e => { e.currentTarget.style.display = 'none' }}
            />
            <div>
              <p style={metaRowStyle}><span style={metaLabelStyle}>Status</span>{comic.status}</p>
              <p style={metaRowStyle}><span style={metaLabelStyle}>Next poll</span>{formatRelative(comic.next_poll_at)}</p>
              <p style={metaRowStyle}><span style={metaLabelStyle}>Last upgrade check</span>{formatRelative(comic.last_upgrade_check_at)}</p>
            </div>
          </div>

          {/* Re-discover */}
          {comic.chapters.length === 0 && (
            <div style={{ marginBottom: 24 }}>
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
