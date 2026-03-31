import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { apiFetch, extractDetail } from '../api/client'
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

  const [coverFormOpen, setCoverFormOpen] = useState(false)
  const [coverTab, setCoverTab] = useState<'url' | 'file'>('url')
  const [coverUrl, setCoverUrl] = useState('')
  const [coverFile, setCoverFile] = useState<File | null>(null)
  const [coverSubmitting, setCoverSubmitting] = useState(false)
  const [coverError, setCoverError] = useState<string | null>(null)

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
