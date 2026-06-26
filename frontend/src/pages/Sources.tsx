import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  DndContext, DragEndEvent, KeyboardSensor, PointerSensor,
  closestCenter, useSensor, useSensors,
} from '@dnd-kit/core'
import {
  SortableContext, arrayMove, sortableKeyboardCoordinates,
  useSortable, verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { CSS } from '@dnd-kit/utilities'
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
// SortableSourceRow
// ---------------------------------------------------------------------------

interface RowProps {
  source: Source
  index: number
  total: number
  onMoveUp: () => void
  onMoveDown: () => void
  onToggle: () => void
}

function SortableSourceRow({ source, index, total, onMoveUp, onMoveDown, onToggle }: RowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: source.id })

  return (
    <div
      ref={setNodeRef}
      className={`source-row${isDragging ? ' dragging' : ''}`}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      {...attributes}
    >
      {/* Drag handle — listeners only here so clicks elsewhere still work */}
      <i className="bx bx-grid-vertical drag-handle" aria-hidden="true" {...listeners} />

      {/* Priority badge */}
      <span style={{
        minWidth: 28, height: 28, borderRadius: '50%',
        background: index === 0 ? 'var(--accent)' : 'var(--surface-2)',
        color: index === 0 ? '#fff' : 'var(--text-2)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 12, fontWeight: 700, flexShrink: 0,
      }}>{index + 1}</span>

      {/* Name */}
      <span style={{ flex: 1, fontWeight: 500, color: 'var(--text)' }}>{source.name}</span>

      {/* Enabled toggle */}
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer', color: 'var(--text-2)' }}>
        <input
          type="checkbox"
          checked={source.enabled}
          onChange={onToggle}
          aria-label={`Toggle ${source.name}`}
        />
        Enabled
      </label>

      {/* Arrow buttons */}
      <div style={{ display: 'flex', gap: 4 }}>
        <button className="btn icon" type="button" onClick={onMoveUp}
          disabled={index === 0} style={{ opacity: index === 0 ? 0.3 : 1 }}
          aria-label={`Move ${source.name} up`}
        ><i className="bx bx-chevron-up" /></button>
        <button className="btn icon" type="button" onClick={onMoveDown}
          disabled={index === total - 1} style={{ opacity: index === total - 1 ? 0.3 : 1 }}
          aria-label={`Move ${source.name} down`}
        ><i className="bx bx-chevron-down" /></button>
      </div>
    </div>
  )
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

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

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

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (!over || active.id === over.id) return
    setLocalSources(prev => {
      const oldIndex = prev.findIndex(s => s.id === active.id)
      const newIndex = prev.findIndex(s => s.id === over.id)
      return arrayMove(prev, oldIndex, newIndex)
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
      await queryClient.invalidateQueries({ queryKey: ['sources'] })
    } catch (err) {
      setToggleError(extractDetail(err))
      setLocalSources(prev => prev.map(s => s.id === source.id ? { ...s, enabled: source.enabled } : s))
    }
  }

  const sourcesHeaderActions = isDirty ? (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      {saveError && <span role="alert" style={{ color: 'var(--danger)', fontSize: 13 }}>{saveError}</span>}
      <button className="btn primary" type="button" onClick={saveOrder} disabled={saving}
        style={{ opacity: saving ? 0.6 : 1 }}>
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

          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
            modifiers={[restrictToVerticalAxis, restrictToParentElement]}
          >
            <SortableContext items={localSources.map(s => s.id)} strategy={verticalListSortingStrategy}>
              <div role="list" aria-label="Source priority order" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {localSources.map((source, i) => (
                  <SortableSourceRow
                    key={source.id}
                    source={source}
                    index={i}
                    total={localSources.length}
                    onMoveUp={() => moveUp(i)}
                    onMoveDown={() => moveDown(i)}
                    onToggle={() => toggleEnabled(source)}
                  />
                ))}
              </div>
            </SortableContext>
          </DndContext>

          {toggleError && <p role="alert" style={{ color: 'var(--danger)', fontSize: 13, marginTop: 12 }}>{toggleError}</p>}
        </>
      )}
    </PageLayout>
  )
}
