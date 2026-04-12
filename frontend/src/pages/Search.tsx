import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiFetch, streamFetch, extractDetail } from '../api/client'
import PageLayout from '../components/PageLayout'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SearchResult {
  title: string
  cover_url: string | null        // absolute Suwayomi URL — submitted to POST /api/requests
  cover_display_url: string | null // proxied URL — used for <img> src
  synopsis: string | null
  source_id: number
  source_name: string
  url: string
  suwayomi_manga_id: string
}

interface SourceError {
  source_name: string
  reason: string
}

interface Source {
  id: number
  name: string
  enabled: boolean
}

type SourceStatus = { status: 'loading' | 'success' | 'error'; error?: string }

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Search() {
  const navigate = useNavigate()

  // Sources
  const [sources, setSources] = useState<Source[]>([])
  const sourcesRef = useRef<Source[]>([])

  // Step 1 state
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())

  // Stream state
  const [results, setResults] = useState<SearchResult[]>([])
  const [sourceErrors, setSourceErrors] = useState<SourceError[]>([])
  const [streamDone, setStreamDone] = useState(false)
  const [streamError, setStreamError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Source chip state
  const [sourceStatuses, setSourceStatuses] = useState<Record<string, SourceStatus>>({})
  const [hiddenSources, setHiddenSources] = useState<Set<number>>(new Set())

  // Step 2 state
  const [step, setStep] = useState<1 | 2>(1)
  const [displayName, setDisplayName] = useState('')
  const [libraryTitle, setLibraryTitle] = useState('')
  const [libraryTitleTouched, setLibraryTitleTouched] = useState(false)
  const [chosenCoverUrl, setChosenCoverUrl] = useState<string | null>(null)
  const [pinResults, setPinResults] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Fetch enabled sources once on mount
  useEffect(() => {
    apiFetch<Source[]>('/api/sources')
      .then(data => {
        const enabled = data.filter(s => s.enabled)
        setSources(enabled)
        sourcesRef.current = enabled
      })
      .catch(() => {})
  }, [])

  // Debounce query; clear selection on new search
  useEffect(() => {
    const id = setTimeout(() => {
      setDebouncedQuery(query)
      setSelected(new Set())
    }, 400)
    return () => clearTimeout(id)
  }, [query])

  // Stream search results per-source as query changes
  useEffect(() => {
    if (!debouncedQuery) {
      setResults([])
      setSourceErrors([])
      setStreamDone(false)
      setStreamError(null)
      setSourceStatuses({})
      setHiddenSources(new Set())
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setResults([])
    setSourceErrors([])
    setStreamDone(false)
    setStreamError(null)
    setHiddenSources(new Set())

    // Mark all known sources as loading
    const initialStatuses: Record<string, SourceStatus> = {}
    for (const s of sourcesRef.current) {
      initialStatuses[s.name] = { status: 'loading' }
    }
    setSourceStatuses(initialStatuses)

    streamFetch(
      `/api/search/stream?q=${encodeURIComponent(debouncedQuery)}`,
      { method: 'GET' },
      (data) => {
        if (data === '[DONE]') {
          setStreamDone(true)
          // Any source still loading returned no results — treat as success (empty)
          setSourceStatuses(prev => {
            const next = { ...prev }
            for (const name of Object.keys(next)) {
              if (next[name].status === 'loading') next[name] = { status: 'success' }
            }
            return next
          })
          return
        }
        try {
          const payload = JSON.parse(data)
          if (payload.error) {
            setSourceErrors(prev => [...prev, { source_name: payload.source_name, reason: payload.error }])
            setSourceStatuses(prev => ({ ...prev, [payload.source_name]: { status: 'error', error: payload.error } }))
          } else {
            const newResults = payload.results as SearchResult[]
            setResults(prev => [...prev, ...newResults])
            if (newResults.length > 0) {
              setSourceStatuses(prev => ({ ...prev, [newResults[0].source_name]: { status: 'success' } }))
            }
          }
        } catch {
          // ignore malformed SSE line
        }
      },
      controller.signal,
    ).catch((err) => {
      if ((err as Error).name !== 'AbortError') {
        setStreamError(extractDetail(err))
        setStreamDone(true)
      }
    })

    return () => controller.abort()
  }, [debouncedQuery])

  function toggleSelect(url: string) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(url)) next.delete(url)
      else next.add(url)
      return next
    })
  }

  function toggleSourceHidden(sourceId: number) {
    setHiddenSources(prev => {
      const next = new Set(prev)
      if (next.has(sourceId)) next.delete(sourceId)
      else next.add(sourceId)
      return next
    })
  }

  function handleReview() {
    const firstSelected = results.find(r => selected.has(r.url))
    setDisplayName(firstSelected?.title ?? '')
    setLibraryTitle(firstSelected?.title ?? '')
    setLibraryTitleTouched(false)
    setChosenCoverUrl(firstSelected?.cover_url ?? null)
    setPinResults(false)
    setSubmitError(null)
    setStep(2)
  }

  function handleDisplayNameChange(v: string) {
    setDisplayName(v)
    if (!libraryTitleTouched) setLibraryTitle(v)
  }

  function handleLibraryTitleChange(v: string) {
    setLibraryTitle(v)
    setLibraryTitleTouched(true)
  }

  async function handleSubmit() {
    setSubmitError(null)
    setSubmitting(true)
    try {
      await apiFetch<unknown>('/api/requests', {
        method: 'POST',
        body: JSON.stringify({
          primary_title: displayName,
          library_title: libraryTitle,
          cover_url: chosenCoverUrl,
          aliases: aliasTitles,
          ...(pinResults && {
            source_pins: selectedResults.map(r => ({
              source_id: r.source_id,
              suwayomi_manga_id: r.suwayomi_manga_id,
            })),
          }),
        }),
      })
      navigate('/library')
    } catch (err) {
      setSubmitError(extractDetail(err))
    } finally {
      setSubmitting(false)
    }
  }

  const selectedResults = results.filter(r => selected.has(r.url))
  const visibleResults = results.filter(r => !hiddenSources.has(r.source_id))
  const aliasTitles = [...new Set(
    selectedResults.map(r => r.title).filter(t => t !== displayName)
  )]

  const isLoading = debouncedQuery.length > 0 && !streamDone && results.length === 0 && sourceErrors.length === 0 && !streamError
  const isLoadingMore = debouncedQuery.length > 0 && !streamDone && (results.length > 0 || sourceErrors.length > 0)

  const searchHeaderActions = step === 2 ? (
    <button onClick={() => setStep(1)} style={linkButtonStyle}><i className="bx bx-chevron-left" /> Back to results</button>
  ) : undefined

  const searchActionBar = step === 1 ? (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, width: '100%' }}>
      <input
        className="input"
        type="text"
        placeholder="Search for a manga title…"
        value={query}
        onChange={e => setQuery(e.target.value)}
        style={{ fontSize: 15, width: '100%' }}
        aria-label="Search"
      />
      {sources.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {sources.map(source => {
            const st = sourceStatuses[source.name]
            const hidden = hiddenSources.has(source.id)
            let extra: React.CSSProperties = {}
            let title: string | undefined
            if (hidden) {
              extra = { opacity: 0.4 }
            } else if (st?.status === 'success') {
              extra = { background: 'var(--accent)', borderColor: 'var(--accent)', color: '#fff' }
            } else if (st?.status === 'error') {
              extra = { background: 'var(--accent-complement)', borderColor: 'var(--accent-complement)', color: '#fff' }
              title = st.error
            }
            return (
              <button
                key={source.id}
                className="chip"
                style={extra}
                title={title}
                onClick={() => toggleSourceHidden(source.id)}
              >
                {source.name}
              </button>
            )
          })}
        </div>
      )}
    </div>
  ) : undefined

  return (
    <PageLayout title={step === 2 ? 'Review request' : 'Search'} headerActions={searchHeaderActions} actionBar={searchActionBar}>

      {step === 1 && (
        <>
          {/* States */}
          <div aria-live="polite" aria-atomic="false">
            {isLoading && <p style={{ color: 'var(--text-2)' }}>Loading…</p>}
            {isLoadingMore && (
              <div style={{
                display: 'inline-block', marginBottom: 8, padding: '3px 10px',
                fontSize: 12, background: 'var(--accent-soft)', border: `1px solid var(--accent)`,
                borderRadius: 12, color: 'var(--accent)',
              }}>Loading more sources…</div>
            )}
            {streamError && <p style={{ color: 'var(--danger)', fontSize: 13 }}>{streamError}</p>}
            {debouncedQuery && streamDone && results.length === 0 && sourceErrors.length === 0 && !streamError && (
              <p style={{ color: 'var(--text-2)' }}>No results.</p>
            )}
          </div>

          {/* Result grid */}
          {visibleResults.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 20 }}>
              {visibleResults.map(r => (
                <div
                  key={r.url}
                  className={`search-card${selected.has(r.url) ? ' selected' : ''}`}
                  style={{ flexDirection: 'column', alignItems: 'flex-start' }}
                  role="button"
                  tabIndex={0}
                  aria-pressed={selected.has(r.url)}
                  onClick={() => toggleSelect(r.url)}
                  onKeyDown={e => e.key === 'Enter' && toggleSelect(r.url)}
                >
                  {r.cover_display_url ? (
                    <img
                      src={r.cover_display_url}
                      alt=""
                      style={{ width: '100%', height: 200, objectFit: 'cover', borderRadius: 4, display: 'block', marginBottom: 8 }}
                      onError={e => { e.currentTarget.style.display = 'none' }}
                    />
                  ) : (
                    <div style={{ width: '100%', height: 200, background: 'var(--surface-2)', borderRadius: 4, marginBottom: 8 }} />
                  )}
                  <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 2, color: 'var(--text)' }}>{r.title}</div>
                  <div style={{ fontSize: 12, color: 'var(--accent)', marginBottom: 4 }}>{r.source_name}</div>
                  {r.synopsis && (
                    <div style={{
                      fontSize: 11, color: 'var(--text-2)',
                      display: '-webkit-box', WebkitLineClamp: 3,
                      WebkitBoxOrient: 'vertical', overflow: 'hidden',
                    }}>
                      {r.synopsis}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Review button */}
          {selected.size > 0 && (
            <button className="btn primary" onClick={handleReview}>
              Review request ({selected.size})
            </button>
          )}
        </>
      )}

      {step === 2 && (
        <>
          {/* Selected sources */}
          <div className="card" style={{ padding: 16, marginBottom: 20 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: 'var(--text-2)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Selected sources
            </div>
            {selectedResults.map(r => (
              <div key={r.url} style={{ fontSize: 13, color: 'var(--text)', marginBottom: 4 }}>
                {r.title}
                <span style={{ color: 'var(--text-2)', marginLeft: 6 }}>— {r.source_name}</span>
              </div>
            ))}
          </div>

          {/* Display name */}
          <div style={{ marginBottom: 14 }}>
            <label htmlFor="display-name" style={labelStyle}>
              Display name
              <input
                id="display-name"
                type="text"
                value={displayName}
                onChange={e => handleDisplayNameChange(e.target.value)}
                className="input"
                style={{ marginTop: 4 }}
              />
            </label>
          </div>

          {/* Library title */}
          <div style={{ marginBottom: 14 }}>
            <label htmlFor="library-title" style={labelStyle}>
              Library title
              <input
                id="library-title"
                type="text"
                value={libraryTitle}
                onChange={e => handleLibraryTitleChange(e.target.value)}
                className="input"
                style={{ marginTop: 4 }}
              />
            </label>
          </div>

          {/* Aliases */}
          {aliasTitles.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: 'var(--text)' }}>Other titles (aliases)</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {aliasTitles.map(t => (
                  <span key={t} className="chip" style={{ cursor: 'default', fontSize: 12, padding: '2px 8px' }}>{t}</span>
                ))}
              </div>
            </div>
          )}

          {/* Cover picker */}
          {selectedResults.some(r => r.cover_display_url) && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: 'var(--text)' }}>Cover</div>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                {selectedResults.filter(r => r.cover_display_url).map(r => (
                  <button
                    key={r.url}
                    onClick={() => setChosenCoverUrl(r.cover_url)}
                    aria-label={`Select cover from ${r.source_name}`}
                    aria-pressed={chosenCoverUrl === r.cover_url}
                    style={{
                      appearance: 'none', WebkitAppearance: 'none',
                      background: 'none', border: 'none', padding: 0,
                      cursor: 'pointer', font: 'inherit', color: 'inherit',
                    }}
                  >
                    <img
                      src={r.cover_display_url!}
                      alt=""
                      style={{
                        width: 100, height: 140, objectFit: 'cover', borderRadius: 6, display: 'block',
                        border: `3px solid ${chosenCoverUrl === r.cover_url ? 'var(--accent)' : 'transparent'}`,
                        boxShadow: chosenCoverUrl === r.cover_url ? 'var(--shadow-md)' : 'var(--shadow)',
                      }}
                      onError={e => { e.currentTarget.style.display = 'none' }}
                    />
                    <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 4, textAlign: 'center' }}>{r.source_name}</div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Pin checkbox */}
          <div style={{ marginBottom: 20 }}>
            <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={pinResults}
                onChange={e => setPinResults(e.target.checked)}
                style={{ marginTop: 3, flexShrink: 0 }}
              />
              <span>
                <strong style={{ color: 'var(--text)' }}>Pin these source-manga IDs</strong>
                <span style={{ color: 'var(--text-2)', display: 'block', marginTop: 2 }}>
                  Otaki will fetch chapters directly using the selected manga IDs instead of searching by title.
                  Useful when different comics have the same title.
                </span>
              </span>
            </label>
          </div>

          {/* Submit */}
          <button
            className="btn primary"
            onClick={handleSubmit}
            disabled={submitting || !displayName}
            style={{ opacity: submitting || !displayName ? 0.6 : 1 }}
          >
            {submitting ? 'Submitting…' : 'Submit request'}
          </button>
          {submitError && <p style={{ color: 'var(--danger)', fontSize: 13, marginTop: 8 }}>{submitError}</p>}
        </>
      )}
    </PageLayout>
  )
}

const linkButtonStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: 'var(--accent)',
  cursor: 'pointer',
  fontSize: 13,
  padding: 0,
  fontFamily: 'inherit',
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 13,
  fontWeight: 600,
  color: 'var(--text)',
}
