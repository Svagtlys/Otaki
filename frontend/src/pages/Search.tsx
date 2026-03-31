import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiFetch, extractDetail } from '../api/client'

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
}

interface SourceError {
  source_name: string
  reason: string
}

interface SearchResponse {
  results: SearchResult[]
  source_errors: SourceError[]
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Search() {
  const navigate = useNavigate()

  // Step 1 state
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())

  // Step 2 state
  const [step, setStep] = useState<1 | 2>(1)
  const [displayName, setDisplayName] = useState('')
  const [libraryTitle, setLibraryTitle] = useState('')
  const [libraryTitleTouched, setLibraryTitleTouched] = useState(false)
  const [chosenCoverUrl, setChosenCoverUrl] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Debounce query; clear selection on new search
  useEffect(() => {
    const id = setTimeout(() => {
      setDebouncedQuery(query)
      setSelected(new Set())
    }, 400)
    return () => clearTimeout(id)
  }, [query])

  const { data, isLoading, error } = useQuery({
    queryKey: ['search', debouncedQuery],
    queryFn: () => apiFetch<SearchResponse>(`/api/search?q=${encodeURIComponent(debouncedQuery)}`),
    enabled: debouncedQuery.length > 0,
  })

  const results = data?.results ?? []
  const sourceErrors = data?.source_errors ?? []

  function toggleSelect(url: string) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(url)) next.delete(url)
      else next.add(url)
      return next
    })
  }

  function handleReview() {
    const firstSelected = results.find(r => selected.has(r.url))
    setDisplayName(firstSelected?.title ?? '')
    setLibraryTitle(firstSelected?.title ?? '')
    setLibraryTitleTouched(false)
    setChosenCoverUrl(firstSelected?.cover_url ?? null)
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
  const aliasTitles = [...new Set(
    selectedResults.map(r => r.title).filter(t => t !== displayName)
  )]

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>Search</h1>
        <button onClick={() => navigate('/library')} style={linkButtonStyle}>← Library</button>
      </div>

      {step === 1 && (
        <>
          {/* Search input */}
          <input
            type="text"
            placeholder="Search for a manga title…"
            value={query}
            onChange={e => setQuery(e.target.value)}
            style={inputStyle}
            aria-label="Search"
          />

          {/* States */}
          {debouncedQuery && isLoading && <p>Loading…</p>}
          {debouncedQuery && error && (
            <p style={{ color: 'red', fontSize: 13 }}>{extractDetail(error)}</p>
          )}
          {debouncedQuery && !isLoading && !error && results.length === 0 && sourceErrors.length === 0 && (
            <p style={{ color: '#666' }}>No results.</p>
          )}

          {/* Source error banner */}
          {sourceErrors.length > 0 && (
            <div style={sourceErrorBannerStyle}>
              <strong>Some sources could not be reached:</strong>{' '}
              {sourceErrors.map(e => `${e.source_name} (${e.reason})`).join(', ')}.
              Results may be incomplete.
            </div>
          )}

          {/* Result cards */}
          {results.length > 0 && (
            <div style={gridStyle}>
              {results.map(r => (
                <div
                  key={r.url}
                  role="button"
                  tabIndex={0}
                  aria-pressed={selected.has(r.url)}
                  onClick={() => toggleSelect(r.url)}
                  onKeyDown={e => e.key === 'Enter' && toggleSelect(r.url)}
                  style={{
                    ...cardStyle,
                    border: selected.has(r.url) ? '2px solid #0070f3' : '2px solid #eee',
                  }}
                >
                  {r.cover_display_url ? (
                    <img
                      src={r.cover_display_url}
                      alt=""
                      width={160}
                      height={220}
                      style={{ objectFit: 'cover', borderRadius: 4, display: 'block' }}
                      onError={e => { e.currentTarget.style.display = 'none' }}
                    />
                  ) : (
                    <div style={{ width: 160, height: 220, background: '#eee', borderRadius: 4 }} />
                  )}
                  <div style={{ marginTop: 8 }}>
                    <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2 }}>{r.title}</div>
                    <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>{r.source_name}</div>
                    {r.synopsis && (
                      <div style={{
                        fontSize: 12,
                        color: '#444',
                        display: '-webkit-box',
                        WebkitLineClamp: 3,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}>
                        {r.synopsis}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Review button */}
          {selected.size > 0 && (
            <div style={{ marginTop: 16 }}>
              <button onClick={handleReview} style={primaryButtonStyle}>
                Review request ({selected.size})
              </button>
            </div>
          )}
        </>
      )}

      {step === 2 && (
        <>
          {/* Back link */}
          <button
            onClick={() => setStep(1)}
            style={{ ...linkButtonStyle, marginBottom: 16, display: 'block' }}
          >
            ← Back to results
          </button>

          {/* Selected cards summary */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: '#444' }}>Selected sources</div>
            {selectedResults.map(r => (
              <div key={r.url} style={{ fontSize: 13, color: '#555', marginBottom: 2 }}>
                {r.title} — <span style={{ color: '#888' }}>{r.source_name}</span>
              </div>
            ))}
          </div>

          {/* Display name */}
          <div style={{ marginBottom: 12 }}>
            <label style={labelStyle}>
              Display name
              <input
                type="text"
                value={displayName}
                onChange={e => handleDisplayNameChange(e.target.value)}
                style={{ ...inputStyle, marginTop: 4 }}
              />
            </label>
          </div>

          {/* Library title */}
          <div style={{ marginBottom: 16 }}>
            <label style={labelStyle}>
              Library title
              <input
                type="text"
                value={libraryTitle}
                onChange={e => handleLibraryTitleChange(e.target.value)}
                style={{ ...inputStyle, marginTop: 4 }}
              />
            </label>
          </div>

          {/* Aliases (read-only) */}
          {aliasTitles.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: '#444' }}>Other titles (aliases)</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {aliasTitles.map(t => (
                  <span key={t} style={aliasChipStyle}>{t}</span>
                ))}
              </div>
            </div>
          )}

          {/* Cover picker */}
          {selectedResults.some(r => r.cover_display_url) && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: '#444' }}>Cover</div>
              <div style={{ display: 'flex', gap: 8 }}>
                {selectedResults
                  .filter(r => r.cover_display_url)
                  .map(r => (
                    <img
                      key={r.url}
                      src={r.cover_display_url!}
                      alt={r.source_name}
                      width={160}
                      height={220}
                      onClick={() => setChosenCoverUrl(r.cover_url)}
                      style={{
                        objectFit: 'cover',
                        borderRadius: 4,
                        cursor: 'pointer',
                        border: chosenCoverUrl === r.cover_url ? '2px solid #0070f3' : '2px solid transparent',
                      }}
                      onError={e => { e.currentTarget.style.display = 'none' }}
                    />
                  ))}
              </div>
            </div>
          )}

          {/* Submit */}
          <button
            onClick={handleSubmit}
            disabled={submitting || !displayName}
            style={{ ...primaryButtonStyle, opacity: submitting || !displayName ? 0.6 : 1 }}
          >
            {submitting ? 'Submitting…' : 'Submit request'}
          </button>
          {submitError && (
            <p style={{ color: 'red', fontSize: 13, marginTop: 8 }}>{submitError}</p>
          )}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const linkButtonStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#0070f3',
  cursor: 'pointer',
  fontSize: 14,
  padding: 0,
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '8px 10px',
  fontSize: 14,
  border: '1px solid #ddd',
  borderRadius: 4,
  boxSizing: 'border-box',
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

const gridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(184px, 1fr))',
  gap: 12,
  marginTop: 16,
}

const cardStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  padding: 12,
  borderRadius: 6,
  cursor: 'pointer',
  background: '#fff',
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 13,
  fontWeight: 600,
  color: '#444',
}

const aliasChipStyle: React.CSSProperties = {
  display: 'inline-block',
  padding: '2px 8px',
  fontSize: 12,
  background: '#f0f0f0',
  border: '1px solid #ddd',
  borderRadius: 12,
  color: '#555',
}

const sourceErrorBannerStyle: React.CSSProperties = {
  marginTop: 8,
  marginBottom: 8,
  padding: '8px 12px',
  background: '#fff8e1',
  border: '1px solid #ffe082',
  borderRadius: 4,
  fontSize: 13,
  color: '#5d4037',
}
