import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, extractDetail } from '../api/client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Source {
  id: number
  suwayomi_source_id: string
  name: string
  priority: number
  enabled: boolean
  created_at: string
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Sources() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: sources, isLoading, error } = useQuery({
    queryKey: ['sources'],
    queryFn: () => apiFetch<Source[]>('/api/sources'),
  })

  const [localSources, setLocalSources] = useState<Source[]>([])
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [toggleError, setToggleError] = useState<string | null>(null)

  useEffect(() => {
    if (sources) setLocalSources(sources)
  }, [sources])

  const isDirty = localSources.some((s, i) => s.id !== (sources ?? [])[i]?.id)

  function moveUp(i: number) {
    setLocalSources(prev => {
      const next = [...prev]
      ;[next[i - 1], next[i]] = [next[i], next[i - 1]]
      return next
    })
  }

  function moveDown(i: number) {
    setLocalSources(prev => {
      const next = [...prev]
      ;[next[i], next[i + 1]] = [next[i + 1], next[i]]
      return next
    })
  }

  async function saveOrder() {
    setSaving(true)
    setSaveError(null)
    try {
      await Promise.all(
        localSources.map((source, i) =>
          apiFetch(`/api/sources/${source.id}`, {
            method: 'PATCH',
            body: JSON.stringify({ priority: i + 1 }),
          }),
        ),
      )
      await queryClient.invalidateQueries({ queryKey: ['sources'] })
    } catch (err) {
      setSaveError(extractDetail(err))
    } finally {
      setSaving(false)
    }
  }

  async function toggleEnabled(source: Source) {
    setToggleError(null)
    const newEnabled = !source.enabled
    setLocalSources(prev => prev.map(s => s.id === source.id ? { ...s, enabled: newEnabled } : s))
    try {
      await apiFetch(`/api/sources/${source.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ enabled: newEnabled }),
      })
    } catch (err) {
      setToggleError(extractDetail(err))
      setLocalSources(prev => prev.map(s => s.id === source.id ? { ...s, enabled: source.enabled } : s))
    }
  }

  const rowStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '5px 0',
    borderBottom: '1px solid #eee',
  }

  return (
    <div style={{ maxWidth: 600, margin: '0 auto', padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>Sources</h1>
        <button onClick={() => navigate('/library')} style={linkButtonStyle}>← Library</button>
      </div>

      {isLoading && <p>Loading…</p>}

      {error && <p style={{ color: 'red', fontSize: 13 }}>{extractDetail(error)}</p>}

      {!isLoading && !error && localSources.length === 0 && (
        <p style={{ color: '#666' }}>No sources configured.</p>
      )}

      {localSources.length > 0 && (
        <>
          <p style={{ fontSize: 13, color: '#555', marginBottom: 6 }}>
            Position 1 is highest priority
          </p>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {localSources.map((source, i) => (
              <li key={source.id} style={rowStyle}>
                <span style={{ minWidth: 20, color: '#999', fontSize: 13 }}>{i + 1}.</span>
                <span style={{ flex: 1 }}>{source.name}</span>
                <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={source.enabled}
                    onChange={() => toggleEnabled(source)}
                    aria-label={`Toggle ${source.name}`}
                  />
                  Enabled
                </label>
                <button
                  type="button"
                  onClick={() => moveUp(i)}
                  disabled={i === 0}
                  aria-label={`Move ${source.name} up`}
                >↑</button>
                <button
                  type="button"
                  onClick={() => moveDown(i)}
                  disabled={i === localSources.length - 1}
                  aria-label={`Move ${source.name} down`}
                >↓</button>
              </li>
            ))}
          </ul>

          {toggleError && <p style={{ color: 'red', fontSize: 13, marginTop: 8 }}>{toggleError}</p>}

          {isDirty && (
            <button
              type="button"
              onClick={saveOrder}
              disabled={saving}
              style={{ marginTop: 16 }}
            >
              {saving ? 'Saving…' : 'Save order'}
            </button>
          )}

          {saveError && <p style={{ color: 'red', fontSize: 13, marginTop: 8 }}>{saveError}</p>}
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
