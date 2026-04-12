import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, extractDetail } from '../api/client'
import PageLayout from '../components/PageLayout'

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
  const queryClient = useQueryClient()

  const { data: sources, isLoading, error } = useQuery({
    queryKey: ['sources'],
    queryFn: () => apiFetch<Source[]>('/api/sources'),
  })

  const [localSources, setLocalSources] = useState<Source[]>([])
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [toggleError, setToggleError] = useState<string | null>(null)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)
  const dragIndexRef = useRef<number | null>(null)

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

  function handleDragStart(i: number) {
    dragIndexRef.current = i
  }

  function handleDragOver(e: React.DragEvent, i: number) {
    e.preventDefault()
    if (dragIndexRef.current !== null && dragIndexRef.current !== i) {
      setDragOverIndex(i)
    }
  }

  function handleDrop(i: number) {
    const from = dragIndexRef.current
    if (from === null || from === i) return
    setLocalSources(prev => {
      const next = [...prev]
      const [item] = next.splice(from, 1)
      next.splice(i, 0, item)
      return next
    })
    dragIndexRef.current = null
    setDragOverIndex(null)
  }

  function handleDragEnd() {
    dragIndexRef.current = null
    setDragOverIndex(null)
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
      await queryClient.invalidateQueries({ queryKey: ['sources'] })
    } catch (err) {
      setToggleError(extractDetail(err))
      setLocalSources(prev => prev.map(s => s.id === source.id ? { ...s, enabled: source.enabled } : s))
    }
  }

  const sourcesHeaderActions = isDirty ? (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      {saveError && <span role="alert" style={{ color: 'var(--danger)', fontSize: 13 }}>{saveError}</span>}
      <button
        className="btn primary"
        type="button"
        onClick={saveOrder}
        disabled={saving}
        style={{ opacity: saving ? 0.6 : 1 }}
      >
        {saving ? 'Saving…' : 'Save order'}
      </button>
    </div>
  ) : undefined

  return (
    <PageLayout title="Sources" headerActions={sourcesHeaderActions}>
      {isLoading && <p style={{ color: 'var(--text-2)' }}>Loading…</p>}
      {error && <p role="alert" style={{ color: 'var(--danger)', fontSize: 13 }}>{extractDetail(error)}</p>}
      {!isLoading && !error && localSources.length === 0 && (
        <p style={{ color: 'var(--text-2)' }}>No sources configured.</p>
      )}

      {localSources.length > 0 && (
        <>
          <p style={{ fontSize: 13, color: 'var(--text-2)', marginBottom: 16 }}>
            Position 1 is highest priority. Drag rows or use arrows to reorder.
          </p>

          <div role="list" aria-label="Source priority order" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {localSources.map((source, i) => (
              <div
                key={source.id}
                role="listitem"
                className={`source-row${dragIndexRef.current === i ? ' dragging' : ''}${dragOverIndex === i ? ' drag-over' : ''}`}
                draggable
                onDragStart={() => handleDragStart(i)}
                onDragOver={e => handleDragOver(e, i)}
                onDrop={() => handleDrop(i)}
                onDragEnd={handleDragEnd}
              >
                {/* Drag handle */}
                <i className="bx bx-grid-vertical drag-handle" aria-hidden="true" />

                {/* Priority badge */}
                <span style={{
                  minWidth: 28, height: 28, borderRadius: '50%',
                  background: i === 0 ? 'var(--accent)' : 'var(--surface-2)',
                  color: i === 0 ? '#fff' : 'var(--text-2)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 12, fontWeight: 700, flexShrink: 0,
                }}>{i + 1}</span>

                {/* Name */}
                <span style={{ flex: 1, fontWeight: 500, color: 'var(--text)' }}>{source.name}</span>

                {/* Enabled toggle */}
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer', color: 'var(--text-2)' }}>
                  <input
                    type="checkbox"
                    checked={source.enabled}
                    onChange={() => toggleEnabled(source)}
                    aria-label={`Toggle ${source.name}`}
                  />
                  Enabled
                </label>

                {/* Arrow buttons */}
                <div style={{ display: 'flex', gap: 4 }}>
                  <button
                    className="btn icon"
                    type="button"
                    onClick={() => moveUp(i)}
                    disabled={i === 0}
                    style={{ opacity: i === 0 ? 0.3 : 1 }}
                    aria-label={`Move ${source.name} up`}
                  ><i className="bx bx-chevron-up" /></button>
                  <button
                    className="btn icon"
                    type="button"
                    onClick={() => moveDown(i)}
                    disabled={i === localSources.length - 1}
                    style={{ opacity: i === localSources.length - 1 ? 0.3 : 1 }}
                    aria-label={`Move ${source.name} down`}
                  ><i className="bx bx-chevron-down" /></button>
                </div>
              </div>
            ))}
          </div>

          {toggleError && <p role="alert" style={{ color: 'var(--danger)', fontSize: 13, marginTop: 12 }}>{toggleError}</p>}
        </>
      )}
    </PageLayout>
  )
}
