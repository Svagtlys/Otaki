import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiFetch, extractDetail } from '../api/client'

interface UnmatchedEntry {
  source_name: string
  manga_dir: string
  chapter_count: number
}

interface MatchedEntry extends UnmatchedEntry {
  comic_id: number
  comic_title: string
}

interface ScanAllResult {
  matched: MatchedEntry[]
  unmatched: UnmatchedEntry[]
}

interface ReconcileFileResult {
  comic_title: string | null
  chapter_number: number
  source_name: string
  chapter_name: string
  status: 'relocated' | 'failed'
}

interface ReconcileResult {
  scanned: number
  found: number
  relocated: number
  failed: number
  results: ReconcileFileResult[]
}

export default function ScanDownloads() {
  const navigate = useNavigate()

  const [tab, setTab] = useState<'unmatched' | 'all'>('unmatched')
  const [allData, setAllData] = useState<ScanAllResult | null>(null)
  const [loadingAll, setLoadingAll] = useState(false)
  const [allError, setAllError] = useState<string | null>(null)

  const [reconciling, setReconciling] = useState(false)
  const [reconcileResult, setReconcileResult] = useState<ReconcileResult | null>(null)
  const [reconcileError, setReconcileError] = useState<string | null>(null)

  useEffect(() => {
    loadAll()
  }, [])

  async function loadAll() {
    setLoadingAll(true)
    setAllError(null)
    try {
      const data = await apiFetch<ScanAllResult>('/api/requests/scan-downloads/all')
      setAllData(data)
    } catch (err) {
      setAllError(extractDetail(err))
    } finally {
      setLoadingAll(false)
    }
  }

  async function handleReconcile() {
    setReconciling(true)
    setReconcileResult(null)
    setReconcileError(null)
    try {
      const data = await apiFetch<ReconcileResult>('/api/requests/scan-downloads', { method: 'POST' })
      setReconcileResult(data)
      // Refresh directory listing after reconcile
      await loadAll()
    } catch (err) {
      setReconcileError(extractDetail(err))
    } finally {
      setReconciling(false)
    }
  }

  const unmatched = allData?.unmatched ?? []
  const matched = allData?.matched ?? []
  const allEntries: (UnmatchedEntry & { comic_title?: string; comic_id?: number })[] = [
    ...matched,
    ...unmatched,
  ].sort((a, b) => a.source_name.localeCompare(b.source_name) || a.manga_dir.localeCompare(b.manga_dir))

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '32px 24px', fontFamily: 'sans-serif' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24 }}>
        <button onClick={() => navigate('/settings')} style={backButtonStyle}>← Settings</button>
        <h1 style={{ margin: 0, fontSize: 22 }}>Suwayomi Downloads</h1>
        <button onClick={loadAll} disabled={loadingAll} style={{ marginLeft: 'auto' }}>
          {loadingAll ? 'Scanning…' : 'Refresh'}
        </button>
      </div>

      {/* Reconcile section */}
      <section style={{ marginBottom: 28, padding: '14px 18px', background: '#f8f8f8', borderRadius: 6, border: '1px solid #e5e5e5' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div>
            <strong style={{ fontSize: 15 }}>Reconcile pending assignments</strong>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: '#555' }}>
              Match pending chapter assignments against files already in Suwayomi's download directory and relocate them to the library.
            </p>
          </div>
          <button onClick={handleReconcile} disabled={reconciling} style={{ marginLeft: 'auto', whiteSpace: 'nowrap' }}>
            {reconciling ? 'Reconciling…' : 'Reconcile now'}
          </button>
        </div>
        {reconcileError && <p style={{ color: 'red', fontSize: 13, marginTop: 8 }}>{reconcileError}</p>}
        {reconcileResult && (
          <div style={{ marginTop: 12 }}>
            <div style={{ padding: '8px 12px', background: '#f0fdf4', border: '1px solid #86efac', borderRadius: 4, fontSize: 13, marginBottom: 8 }}>
              {reconcileResult.found} found · {reconcileResult.relocated} relocated · {reconcileResult.failed} failed out of {reconcileResult.scanned} scanned
            </div>
            {reconcileResult.results.length > 0 && (
              <div style={{ maxHeight: 160, overflowY: 'auto', fontSize: 12, fontFamily: 'monospace', background: '#fafafa', border: '1px solid #eee', borderRadius: 4, padding: '6px 10px' }}>
                {reconcileResult.results.map((r, i) => (
                  <div key={i} style={{ color: r.status === 'failed' ? '#dc2626' : '#16a34a' }}>
                    {r.status === 'relocated' ? '✓' : '✗'} {r.comic_title ?? '?'} · Ch {r.chapter_number} · {r.chapter_name}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      {/* Directory listing */}
      {allError && <p style={{ color: 'red', fontSize: 14 }}>{allError}</p>}

      {allData && (
        <>
          <div style={{ display: 'flex', gap: 0, marginBottom: 16, borderBottom: '1px solid #e5e5e5' }}>
            <button
              onClick={() => setTab('unmatched')}
              style={tab === 'unmatched' ? activeTabStyle : tabStyle}
            >
              Unmatched ({unmatched.length})
            </button>
            <button
              onClick={() => setTab('all')}
              style={tab === 'all' ? activeTabStyle : tabStyle}
            >
              All downloads ({matched.length + unmatched.length})
            </button>
          </div>

          {tab === 'unmatched' && (
            unmatched.length === 0 ? (
              <p style={{ color: '#555', fontSize: 14 }}>No unmatched downloads found.</p>
            ) : (
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <th style={thStyle}>Source</th>
                    <th style={thStyle}>Manga directory</th>
                    <th style={{ ...thStyle, textAlign: 'right' }}>Chapters</th>
                    <th style={thStyle}></th>
                  </tr>
                </thead>
                <tbody>
                  {unmatched.map((e, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid #f0f0f0' }}>
                      <td style={tdStyle}>{e.source_name}</td>
                      <td style={tdStyle}>{e.manga_dir}</td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>{e.chapter_count}</td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>
                        <button
                          onClick={() => navigate(`/search?q=${encodeURIComponent(e.manga_dir)}`)}
                          style={addButtonStyle}
                        >
                          Add request
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          )}

          {tab === 'all' && (
            allEntries.length === 0 ? (
              <p style={{ color: '#555', fontSize: 14 }}>No downloads found in Suwayomi's download directory.</p>
            ) : (
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <th style={thStyle}>Source</th>
                    <th style={thStyle}>Manga directory</th>
                    <th style={{ ...thStyle, textAlign: 'right' }}>Chapters</th>
                    <th style={thStyle}>Matched comic</th>
                    <th style={thStyle}></th>
                  </tr>
                </thead>
                <tbody>
                  {allEntries.map((e, i) => {
                    const isMatched = 'comic_id' in e && e.comic_id !== undefined
                    return (
                      <tr key={i} style={{ borderBottom: '1px solid #f0f0f0' }}>
                        <td style={tdStyle}>{e.source_name}</td>
                        <td style={tdStyle}>{e.manga_dir}</td>
                        <td style={{ ...tdStyle, textAlign: 'right' }}>{e.chapter_count}</td>
                        <td style={tdStyle}>
                          {isMatched ? (
                            <button
                              onClick={() => navigate(`/comics/${(e as MatchedEntry).comic_id}`)}
                              style={{ background: 'none', border: 'none', color: '#0070f3', cursor: 'pointer', padding: 0, fontSize: 13 }}
                            >
                              {(e as MatchedEntry).comic_title}
                            </button>
                          ) : (
                            <span style={{ color: '#aaa' }}>—</span>
                          )}
                        </td>
                        <td style={{ ...tdStyle, textAlign: 'right' }}>
                          {!isMatched && (
                            <button
                              onClick={() => navigate(`/search?q=${encodeURIComponent(e.manga_dir)}`)}
                              style={addButtonStyle}
                            >
                              Add request
                            </button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )
          )}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const backButtonStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#0070f3',
  cursor: 'pointer',
  fontSize: 14,
  padding: 0,
}

const tabStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  borderBottom: '2px solid transparent',
  cursor: 'pointer',
  fontSize: 14,
  padding: '8px 16px',
  color: '#555',
}

const activeTabStyle: React.CSSProperties = {
  ...tabStyle,
  borderBottom: '2px solid #0070f3',
  color: '#0070f3',
  fontWeight: 600,
}

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: 13,
}

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '6px 10px',
  borderBottom: '2px solid #e5e5e5',
  fontWeight: 600,
  color: '#444',
}

const tdStyle: React.CSSProperties = {
  padding: '7px 10px',
  verticalAlign: 'middle',
}

const addButtonStyle: React.CSSProperties = {
  background: '#0070f3',
  border: 'none',
  borderRadius: 4,
  color: '#fff',
  cursor: 'pointer',
  fontSize: 12,
  padding: '4px 10px',
}
