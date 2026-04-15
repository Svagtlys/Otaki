import { useState, useRef, useEffect } from 'react'
import { useQuery, useQueries, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
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
import { apiFetch, streamFetch, extractDetail } from '../api/client'
import { formatRelative } from '../utils/format'
import PageLayout from '../components/PageLayout'
import Pagination from '../components/Pagination'

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

interface Alias {
  id: number
  title: string
}

interface ComicDetail {
  id: number
  title: string
  library_title: string
  status: string
  poll_override_days: number | null
  upgrade_override_days: number | null
  inferred_cadence_days: number | null
  next_poll_at: string | null
  next_upgrade_check_at: string | null
  last_upgrade_check_at: string | null
  aliases: Alias[]
}

interface ChapterPage {
  items: Chapter[]
  total: number
  page: number
  per_page: number
}

interface SourceOverrideEntry {
  source_id: number
  source_name: string
  global_priority: number
  effective_priority: number
  is_overridden: boolean
}

interface SourcePin {
  id: number
  source_id: number
  source_name: string
  suwayomi_manga_id: string
  pinned_at: string
}

interface Source {
  id: number
  name: string
  enabled: boolean
}

interface PinSearchResult {
  title: string
  source_id: number
  source_name: string
  suwayomi_manga_id: string
  url: string
}

// ---------------------------------------------------------------------------
// SortableOverrideRow
// ---------------------------------------------------------------------------

interface OverrideRowProps {
  entry: SourceOverrideEntry
  index: number
  total: number
  showOverrideBadge: boolean
  onMoveUp: () => void
  onMoveDown: () => void
}

function SortableOverrideRow({ entry, index, total, showOverrideBadge, onMoveUp, onMoveDown }: OverrideRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: entry.source_id })
  return (
    <div
      ref={setNodeRef}
      className={`source-row${isDragging ? ' dragging' : ''}`}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      {...attributes}
    >
      <i className="bx bx-grid-vertical drag-handle" aria-hidden="true" {...listeners} />
      <span style={{
        minWidth: 28, height: 28, borderRadius: '50%',
        background: index === 0 ? 'var(--accent)' : 'var(--surface-2)',
        color: index === 0 ? '#fff' : 'var(--text-2)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 12, fontWeight: 700, flexShrink: 0,
      }}>{index + 1}</span>
      <span style={{ flex: 1, fontWeight: 500 }}>{entry.source_name}</span>
      {showOverrideBadge && entry.is_overridden && (
        <span style={{ fontSize: 11, color: 'var(--accent)' }}>overridden</span>
      )}
      <div style={{ display: 'flex', gap: 4 }}>
        <button className="btn icon" type="button" onClick={onMoveUp}
          disabled={index === 0} style={{ opacity: index === 0 ? 0.3 : 1 }}
          aria-label={`Move ${entry.source_name} up`}
        ><i className="bx bx-chevron-up" /></button>
        <button className="btn icon" type="button" onClick={onMoveDown}
          disabled={index === total - 1} style={{ opacity: index === total - 1 ? 0.3 : 1 }}
          aria-label={`Move ${entry.source_name} down`}
        ><i className="bx bx-chevron-down" /></button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const STATUS_LIST = ['queued', 'downloading', 'relocating', 'available', 'failed'] as const
type ChapterStatus = typeof STATUS_LIST[number]

export default function Comic() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const comicId = parseInt(id ?? '0', 10)

  const [discovering, setDiscovering] = useState(false)
  const [discoverError, setDiscoverError] = useState<string | null>(null)
  const [discoverResult, setDiscoverResult] = useState<string | null>(null)

  const [reprocessing, setReprocessing] = useState(false)
  const [reprocessError, setReprocessError] = useState<string | null>(null)
  const [reprocessResult, setReprocessResult] = useState<string | null>(null)
  const [reprocessLog, setReprocessLog] = useState<{ chapter_number: number; action: string }[]>([])

  const [forceUpgrading, setForceUpgrading] = useState(false)
  const [forceUpgradeError, setForceUpgradeError] = useState<string | null>(null)
  const [forceUpgradeResult, setForceUpgradeResult] = useState<string | null>(null)
  const [forceUpgradeLog, setForceUpgradeLog] = useState<{ chapter_number: number; old_source: string; new_source: string }[]>([])
  const [upgradingChapterId, setUpgradingChapterId] = useState<number | null>(null)
  const [chapterUpgradeMsgs, setChapterUpgradeMsgs] = useState<Record<number, string>>({})

  // Tab state
  type ComicTab = 'details' | 'settings'
  const [activeTab, setActiveTab] = useState<ComicTab>('details')

  // Chapter pagination / filter state
  const [chapterPage, setChapterPage] = useState(1)
  const [chapterPerPage, setChapterPerPage] = useState(25)
  const [chapterStatus, setChapterStatus] = useState('')

  // Source overrides state
  const [overrideDraft, setOverrideDraft] = useState<SourceOverrideEntry[] | null>(null)
  const [overrideSaving, setOverrideSaving] = useState(false)
  const [overrideError, setOverrideError] = useState<string | null>(null)
  const [overrideResult, setOverrideResult] = useState<string | null>(null)
  const logScrollRef = useRef<HTMLDivElement>(null)

  const overrideSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  // Pin management state
  const [removedPinIds, setRemovedPinIds] = useState<Set<number>>(new Set())
  const [pendingPins, setPendingPins] = useState<{ source_id: number; source_name: string; suwayomi_manga_id: string }[]>([])
  const [pinSaving, setPinSaving] = useState(false)
  const [pinError, setPinError] = useState<string | null>(null)
  const [pinResult, setPinResult] = useState<string | null>(null)
  // Add-pin search sub-state
  const [pinSearchSourceId, setPinSearchSourceId] = useState<number | ''>('')
  const [pinSearchQuery, setPinSearchQuery] = useState('')
  const [pinSearchResults, setPinSearchResults] = useState<PinSearchResult[]>([])
  const [pinSearching, setPinSearching] = useState(false)
  const [pinSearchDone, setPinSearchDone] = useState(false)
  const pinAbortRef = useRef<AbortController | null>(null)

  const [coverTab, setCoverTab] = useState<'url' | 'file'>('url')
  const [coverUrl, setCoverUrl] = useState('')
  const [coverFile, setCoverFile] = useState<File | null>(null)
  const [coverSubmitting, setCoverSubmitting] = useState(false)
  const [coverError, setCoverError] = useState<string | null>(null)

  const [editLibraryTitle, setEditLibraryTitle] = useState('')
  const [editPollDays, setEditPollDays] = useState('')
  const [editPollClear, setEditPollClear] = useState(false)
  const [editUpgradeDays, setEditUpgradeDays] = useState('')
  const [editUpgradeClear, setEditUpgradeClear] = useState(false)
  const [editSubmitting, setEditSubmitting] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)

  const [newAlias, setNewAlias] = useState('')
  const [pendingAliasAdds, setPendingAliasAdds] = useState<string[]>([])
  const [pendingAliasDeletes, setPendingAliasDeletes] = useState<Set<number>>(new Set())
  const [aliasError, setAliasError] = useState<string | null>(null)

  const { data: comic, isLoading, error } = useQuery({
    queryKey: ['comic', comicId],
    queryFn: () => apiFetch<ComicDetail>(`/api/requests/${comicId}`),
    enabled: comicId > 0,
  })

  const { data: pins = [] } = useQuery<SourcePin[]>({
    queryKey: ['comic-pins', comicId],
    queryFn: () => apiFetch<SourcePin[]>(`/api/requests/${comicId}/pins`),
    enabled: comicId > 0,
  })

  const { data: sources = [] } = useQuery<Source[]>({
    queryKey: ['sources'],
    queryFn: () => apiFetch<Source[]>('/api/sources'),
    enabled: activeTab === 'settings',
  })

  const { data: sourceOverrides = [] } = useQuery<SourceOverrideEntry[]>({
    queryKey: ['comic-source-overrides', comicId],
    queryFn: () => apiFetch<SourceOverrideEntry[]>(`/api/requests/${comicId}/source-overrides`),
    enabled: comicId > 0 && activeTab === 'settings',
  })

  // Initialise Settings tab state when switching to it
  useEffect(() => {
    if (activeTab !== 'settings' || !comic) return
    setEditLibraryTitle(comic.library_title)
    setEditPollDays(comic.poll_override_days != null ? String(comic.poll_override_days) : '')
    setEditPollClear(comic.poll_override_days == null)
    setEditUpgradeDays(comic.upgrade_override_days != null ? String(comic.upgrade_override_days) : '')
    setEditUpgradeClear(comic.upgrade_override_days == null)
    setEditError(null)
    setAliasError(null)
    setPendingAliasAdds([])
    setPendingAliasDeletes(new Set())
    setNewAlias('')
    setRemovedPinIds(new Set())
    setPendingPins([])
    setPinError(null)
    setPinResult(null)
    setPinSearchSourceId('')
    setPinSearchQuery('')
    setPinSearchResults([])
    setPinSearchDone(false)
    setOverrideDraft(null)
    setOverrideError(null)
    setOverrideResult(null)
    setCoverUrl('')
    setCoverFile(null)
    setCoverError(null)
  }, [activeTab])

  // Auto-scroll operation log as new entries arrive
  useEffect(() => {
    if (logScrollRef.current) {
      logScrollRef.current.scrollTop = logScrollRef.current.scrollHeight
    }
  }, [reprocessLog, forceUpgradeLog, discoverResult])

  const chapterQueryUrl = (() => {
    const u = new URL(`/api/requests/${comicId}/chapters`, window.location.origin)
    u.searchParams.set('page', String(chapterPage))
    u.searchParams.set('per_page', String(chapterPerPage))
    if (chapterStatus) u.searchParams.set('status', chapterStatus)
    return u.pathname + u.search
  })()

  const { data: chaptersData } = useQuery<ChapterPage>({
    queryKey: ['comic-chapters', comicId, chapterPage, chapterPerPage, chapterStatus],
    queryFn: () => apiFetch<ChapterPage>(chapterQueryUrl),
    enabled: comicId > 0,
  })

  const chapters = chaptersData?.items ?? []
  const chaptersTotal = chaptersData?.total ?? 0
  const chapterTotalPages = Math.max(1, Math.ceil(chaptersTotal / chapterPerPage))

  const statusCounts = useQueries({
    queries: STATUS_LIST.map(status => ({
      queryKey: ['comic-chapter-count', comicId, status],
      queryFn: () =>
        apiFetch<ChapterPage>(
          `/api/requests/${comicId}/chapters?status=${status}&per_page=1&page=1`,
        ).then(d => d.total),
      enabled: comicId > 0,
    })),
    combine: (results) => ({
      queued:      results[0].data ?? 0,
      downloading: results[1].data ?? 0,
      relocating:  results[2].data ?? 0,
      available:   results[3].data ?? 0,
      failed:      results[4].data ?? 0,
    }),
  })

  async function handleReprocess() {
    setReprocessing(true)
    setReprocessError(null)
    setReprocessResult(null)
    setReprocessLog([])
    try {
      let queued = 0, processed = 0, skipped = 0
      await streamFetch(
        `/api/requests/${comicId}/reprocess`,
        { method: 'POST' },
        (data) => {
          if (data === '[DONE]') return
          try {
            const ev = JSON.parse(data)
            if (ev.type === 'error') {
              setReprocessError(ev.detail)
            } else if (ev.type === 'chapter') {
              setReprocessLog(prev => [...prev, { chapter_number: ev.chapter_number, action: ev.action }])
            } else if (ev.type === 'done') {
              queued = ev.queued
              processed = ev.processed
              skipped = ev.skipped
            }
          } catch {
            // ignore malformed SSE line
          }
        },
      )
      const parts = []
      if (processed > 0) parts.push(`${processed} processed`)
      if (queued > 0) parts.push(`${queued} queued for download`)
      if (skipped > 0) parts.push(`${skipped} already in progress`)
      setReprocessResult(parts.length > 0 ? parts.join(', ') + '.' : 'Nothing to do.')
      await queryClient.invalidateQueries({ queryKey: ['comic', comicId] })
    } catch (err) {
      setReprocessError(extractDetail(err))
    } finally {
      setReprocessing(false)
    }
  }

  // Called once sourceOverrides loads — initialise draft from server data
  function initOverrideDraft(entries: SourceOverrideEntry[]) {
    if (overrideDraft === null) setOverrideDraft([...entries])
  }

  function handleOverrideDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (!over || active.id === over.id) return
    setOverrideDraft(prev => {
      const list = prev ?? sourceOverrides
      const oldIndex = list.findIndex(e => e.source_id === active.id)
      const newIndex = list.findIndex(e => e.source_id === over.id)
      return arrayMove([...list], oldIndex, newIndex)
    })
  }

  function overrideMoveUp(index: number) {
    setOverrideDraft(prev => {
      const list = [...(prev ?? sourceOverrides)]
      if (index === 0) return list
      ;[list[index - 1], list[index]] = [list[index], list[index - 1]]
      return list
    })
  }

  function overrideMoveDown(index: number) {
    setOverrideDraft(prev => {
      const list = [...(prev ?? sourceOverrides)]
      if (index === list.length - 1) return list
      ;[list[index], list[index + 1]] = [list[index + 1], list[index]]
      return list
    })
  }

  async function handleSaveOverrides() {
    if (!overrideDraft) return
    setOverrideSaving(true)
    setOverrideError(null)
    setOverrideResult(null)
    try {
      await apiFetch(`/api/requests/${comicId}/source-overrides`, {
        method: 'PUT',
        body: JSON.stringify({ source_ids: overrideDraft.map(e => e.source_id) }),
      })
      await queryClient.invalidateQueries({ queryKey: ['comic-source-overrides', comicId] })
      setOverrideDraft(null)
      setOverrideResult('Source order saved.')
    } catch (err) {
      setOverrideError(extractDetail(err))
    } finally {
      setOverrideSaving(false)
    }
  }

  async function handleResetOverrides() {
    setOverrideSaving(true)
    setOverrideError(null)
    setOverrideResult(null)
    try {
      await apiFetch(`/api/requests/${comicId}/source-overrides`, { method: 'DELETE' })
      await queryClient.invalidateQueries({ queryKey: ['comic-source-overrides', comicId] })
      setOverrideDraft(null)
      setOverrideResult('Overrides removed — global priorities restored.')
    } catch (err) {
      setOverrideError(extractDetail(err))
    } finally {
      setOverrideSaving(false)
    }
  }

  async function handleForceUpgrade() {
    setForceUpgrading(true)
    setForceUpgradeError(null)
    setForceUpgradeResult(null)
    setForceUpgradeLog([])
    try {
      let queued = 0
      await streamFetch(
        `/api/requests/${comicId}/force-upgrade`,
        { method: 'POST' },
        (data) => {
          if (data === '[DONE]') return
          try {
            const ev = JSON.parse(data)
            if (ev.type === 'error') {
              setForceUpgradeError(ev.detail)
            } else if (ev.type === 'chapter') {
              setForceUpgradeLog(prev => [...prev, { chapter_number: ev.chapter_number, old_source: ev.old_source, new_source: ev.new_source }])
            } else if (ev.type === 'done') {
              queued = ev.queued
            }
          } catch {
            // ignore malformed SSE line
          }
        },
      )
      setForceUpgradeResult(queued > 0 ? `${queued} upgrade(s) queued.` : 'No upgrades available.')
      await queryClient.invalidateQueries({ queryKey: ['comic', comicId] })
    } catch (err) {
      setForceUpgradeError(extractDetail(err))
    } finally {
      setForceUpgrading(false)
    }
  }

  async function handleForceUpgradeChapter(assignmentId: number) {
    setUpgradingChapterId(assignmentId)
    setChapterUpgradeMsgs(prev => ({ ...prev, [assignmentId]: '' }))
    try {
      let queued = 0
      await streamFetch(
        `/api/requests/${comicId}/chapters/${assignmentId}/force-upgrade`,
        { method: 'POST' },
        (data) => {
          if (data === '[DONE]') return
          try {
            const ev = JSON.parse(data)
            if (ev.type === 'done') queued = ev.queued
          } catch { /* ignore */ }
        },
      )
      setChapterUpgradeMsgs(prev => ({ ...prev, [assignmentId]: queued > 0 ? 'Upgrade queued' : 'No upgrade available' }))
      await queryClient.invalidateQueries({ queryKey: ['comic', comicId] })
    } catch (err) {
      setChapterUpgradeMsgs(prev => ({ ...prev, [assignmentId]: extractDetail(err) }))
    } finally {
      setUpgradingChapterId(null)
    }
  }

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

  function removeSavedPin(pinId: number) {
    setRemovedPinIds(prev => new Set([...prev, pinId]))
  }

  function removePendingPin(idx: number) {
    setPendingPins(prev => prev.filter((_, i) => i !== idx))
  }

  async function handlePinSearch() {
    if (!pinSearchSourceId || !pinSearchQuery.trim()) return
    pinAbortRef.current?.abort()
    const controller = new AbortController()
    pinAbortRef.current = controller
    setPinSearching(true)
    setPinSearchDone(false)
    setPinSearchResults([])
    const results: PinSearchResult[] = []
    try {
      await streamFetch(
        `/api/search/stream?q=${encodeURIComponent(pinSearchQuery.trim())}`,
        { method: 'GET' },
        (data) => {
          if (data === '[DONE]') return
          try {
            const payload = JSON.parse(data)
            if (payload.results) {
              for (const r of payload.results) {
                if (r.source_id === pinSearchSourceId) results.push(r)
              }
              setPinSearchResults([...results])
            }
          } catch { /* ignore */ }
        },
        controller.signal,
      )
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setPinError(extractDetail(err))
    } finally {
      setPinSearching(false)
      setPinSearchDone(true)
    }
  }

  function stagePinFromResult(r: PinSearchResult) {
    const alreadyPinned = pins
      .filter(p => !removedPinIds.has(p.id))
      .some(p => p.source_id === r.source_id && p.suwayomi_manga_id === r.suwayomi_manga_id)
    const alreadyPending = pendingPins.some(
      p => p.source_id === r.source_id && p.suwayomi_manga_id === r.suwayomi_manga_id
    )
    if (!alreadyPinned && !alreadyPending) {
      setPendingPins(prev => [...prev, {
        source_id: r.source_id,
        source_name: r.source_name,
        suwayomi_manga_id: r.suwayomi_manga_id,
      }])
    }
    setPinSearchResults([])
    setPinSearchQuery('')
  }

  async function handleSavePins() {
    setPinSaving(true)
    setPinError(null)
    setPinResult(null)
    const kept = pins.filter(p => !removedPinIds.has(p.id)).map(p => ({
      source_id: p.source_id,
      suwayomi_manga_id: p.suwayomi_manga_id,
    }))
    const newPins = pendingPins.map(p => ({
      source_id: p.source_id,
      suwayomi_manga_id: p.suwayomi_manga_id,
    }))
    try {
      await apiFetch(`/api/requests/${comicId}/pins`, {
        method: 'PUT',
        body: JSON.stringify({ pins: [...kept, ...newPins] }),
      })
      await queryClient.invalidateQueries({ queryKey: ['comic-pins', comicId] })
      setRemovedPinIds(new Set())
      setPendingPins([])
      setPinResult('Pins saved. Run Re-discover to pick up any newly available chapters.')
    } catch (err) {
      setPinError(extractDetail(err))
    } finally {
      setPinSaving(false)
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
      setCoverUrl('')
      setCoverFile(null)
      await queryClient.invalidateQueries({ queryKey: ['comic', comicId] })
    } catch (err) {
      setCoverError(extractDetail(err))
    } finally {
      setCoverSubmitting(false)
    }
  }

  async function handleEditSubmit() {
    if (!comic) return
    setEditSubmitting(true)
    setEditError(null)
    const patch: Record<string, unknown> = {}
    if (editLibraryTitle !== comic.library_title) patch.library_title = editLibraryTitle
    if (editPollClear && comic.poll_override_days != null) {
      patch.poll_override_days = null
    } else if (!editPollClear) {
      const pollNum = parseFloat(editPollDays)
      if (!isNaN(pollNum) && pollNum !== comic.poll_override_days) patch.poll_override_days = pollNum
    }
    if (editUpgradeClear && comic.upgrade_override_days != null) {
      patch.upgrade_override_days = null
    } else if (!editUpgradeClear) {
      const upgradeNum = parseFloat(editUpgradeDays)
      if (!isNaN(upgradeNum) && upgradeNum !== comic.upgrade_override_days) patch.upgrade_override_days = upgradeNum
    }
    try {
      await apiFetch(`/api/requests/${comicId}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      })
      await Promise.all([
        ...Array.from(pendingAliasDeletes).map(id =>
          apiFetch(`/api/requests/${comicId}/aliases/${id}`, { method: 'DELETE' })
        ),
        ...(newAlias.trim()
          ? [apiFetch(`/api/requests/${comicId}/aliases`, { method: 'POST', body: JSON.stringify({ title: newAlias.trim() }) })]
          : []
        ),
        ...pendingAliasAdds.map(title =>
          apiFetch(`/api/requests/${comicId}/aliases`, { method: 'POST', body: JSON.stringify({ title }) })
        ),
      ])
      await queryClient.invalidateQueries({ queryKey: ['comic', comicId] })
    } catch (err) {
      setEditError(extractDetail(err))
    } finally {
      setEditSubmitting(false)
    }
  }

  async function handleStatusToggle() {
    if (!comic) return
    const newStatus = comic.status === 'tracking' ? 'complete' : 'tracking'
    try {
      await apiFetch(`/api/requests/${comicId}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: newStatus }),
      })
      await queryClient.invalidateQueries({ queryKey: ['comic', comicId] })
    } catch (err) {
      setEditError(extractDetail(err))
    }
  }

  function handleStagedAddAlias() {
    const title = newAlias.trim()
    if (!title) return
    setPendingAliasAdds(prev => [...prev, title])
    setNewAlias('')
  }

  function handleStagedDeleteAlias(aliasId: number) {
    setPendingAliasDeletes(prev => new Set([...prev, aliasId]))
  }

  function handleRemoveStagedAdd(title: string) {
    setPendingAliasAdds(prev => prev.filter(t => t !== title))
  }

  function downloadStatusCell(status: string) {
    switch (status) {
      case 'done':
        return <span style={{ color: 'var(--success)', fontSize: 12, fontWeight: 600 }}><i className="bx bx-check" /> Done</span>
      case 'downloading':
        return <span style={{ color: 'var(--accent)', fontSize: 12, fontWeight: 600 }}><i className="bx bx-download" /> Downloading</span>
      case 'queued':
        return <span style={{ color: 'var(--warning)', fontSize: 12, fontWeight: 600 }}><i className="bx bx-time" /> Queued</span>
      case 'relocating':
        return <span style={{ color: 'var(--text-2)', fontSize: 12, fontWeight: 600 }}><i className="bx bx-transfer-alt" /> Relocating</span>
      case 'failed':
        return <span style={{ color: 'var(--danger)', fontSize: 12, fontWeight: 600 }}><i className="bx bx-error-circle" /> Failed</span>
      default:
        return <span style={{ fontSize: 12, color: 'var(--text-3)' }}>{status}</span>
    }
  }

  function relocationStatusCell(status: string) {
    switch (status) {
      case 'done':
        return <span style={{ color: 'var(--success)', fontSize: 12, fontWeight: 600 }}><i className="bx bx-check" /> Done</span>
      case 'relocating':
        return <span style={{ color: 'var(--accent)', fontSize: 12, fontWeight: 600 }}><i className="bx bx-transfer-alt" /> Relocating</span>
      case 'pending':
        return <span style={{ color: 'var(--warning)', fontSize: 12, fontWeight: 600 }}><i className="bx bx-time" /> Pending</span>
      case 'failed':
        return <span style={{ color: 'var(--danger)', fontSize: 12, fontWeight: 600 }}><i className="bx bx-error-circle" /> Failed</span>
      default:
        return <span style={{ fontSize: 12, color: 'var(--text-3)' }}>{status}</span>
    }
  }

  const TABS = ['details', 'settings'] as const
  const actionBar = (
    <div role="tablist" aria-label="Comic sections" style={{ display: 'contents' }}>
      {TABS.map(tab => (
        <button
          key={tab}
          id={`comic-tab-${tab}`}
          role="tab"
          aria-selected={activeTab === tab}
          aria-controls={`comic-panel-${tab}`}
          tabIndex={activeTab === tab ? 0 : -1}
          className={`settings-nav-item${activeTab === tab ? ' active' : ''}`}
          onClick={() => setActiveTab(tab)}
          onKeyDown={e => {
            if (e.key === 'ArrowRight') { e.preventDefault(); setActiveTab('settings') }
            else if (e.key === 'ArrowLeft') { e.preventDefault(); setActiveTab('details') }
          }}
        >
          {tab === 'details'
            ? <><i className="bx bx-book-content" style={{ marginRight: 8, fontSize: 15 }} aria-hidden="true" />Details</>
            : <><i className="bx bx-cog" style={{ marginRight: 8, fontSize: 15 }} aria-hidden="true" />Settings</>}
        </button>
      ))}
    </div>
  )

  return (
    <PageLayout
      title={comic?.title ?? 'Comic'}
      headerActions={
        <button className="btn" onClick={() => navigate('/library')}>
          <i className="bx bx-chevron-left" /> Library
        </button>
      }
      actionBar={actionBar}
    >
      {isLoading && <p style={{ color: 'var(--text-2)' }}>Loading…</p>}

      {error && (
        <p role="alert" style={{ color: 'var(--danger)', fontSize: 13 }}>
          {extractDetail(error)}
        </p>
      )}

      {comic && (
        <>
          {/* =========================================================== */}
          {/* DETAILS TAB                                                   */}
          {/* =========================================================== */}
          {activeTab === 'details' && (
            <div id="comic-panel-details" role="tabpanel" aria-labelledby="comic-tab-details">
              <div className="detail-hero">
                <div style={{ flexShrink: 0, alignSelf: 'flex-start' }}>
                  <div className="detail-cover">
                    <img src={`/api/requests/${comic.id}/cover`} alt={`Cover art for ${comic.title}`}
                      onError={e => { e.currentTarget.style.display = 'none' }} />
                    <i className="bx bx-book-open" style={{ fontSize: 36 }} aria-hidden="true" />
                  </div>
                </div>

                <div className="detail-meta" style={{ alignSelf: 'flex-start' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span className={`status-badge ${comic.status}`} aria-label={`Status: ${comic.status}`}>
                      {comic.status}
                    </span>
                    <button className="btn" onClick={handleStatusToggle} style={{ fontSize: 12 }}>
                      {comic.status === 'tracking' ? 'Mark complete' : 'Resume tracking'}
                    </button>
                  </div>

                  <h1 className="detail-title">{comic.title}</h1>
                  {comic.library_title !== comic.title && (
                    <div className="detail-subtitle">Library title: {comic.library_title}</div>
                  )}

                  <dl className="detail-stats">
                    <div className="stat-block">
                      <dt className="stat-label">Downloaded</dt>
                      <dd className="stat-value">{statusCounts.available}</dd>
                    </div>
                    <div className="stat-divider" aria-hidden="true" role="presentation" />
                    <div className="stat-block">
                      <dt className="stat-label">Total chapters</dt>
                      <dd className="stat-value">{chaptersTotal}</dd>
                    </div>
                    <div className="stat-divider" aria-hidden="true" role="presentation" />
                    <div className="stat-block">
                      <dt className="stat-label">Poll cadence</dt>
                      <dd className="stat-value">
                        {comic.poll_override_days != null
                          ? `${comic.poll_override_days}d`
                          : comic.inferred_cadence_days != null
                            ? `${comic.inferred_cadence_days.toFixed(1)}d`
                            : '7d'}
                      </dd>
                    </div>
                    <div className="stat-divider" aria-hidden="true" role="presentation" />
                    <div className="stat-block">
                      <dt className="stat-label">Next poll</dt>
                      <dd className="stat-value" style={{ fontSize: 15, color: 'var(--text-2)' }}>
                        {formatRelative(comic.next_poll_at)}
                      </dd>
                    </div>
                  </dl>

                  <div className="detail-actions">
                    <button className="btn primary" onClick={handleDiscover} disabled={discovering} aria-busy={discovering}>
                      {discovering ? 'Searching sources…' : 'Re-discover chapters'}
                    </button>
                    <button className="btn" onClick={handleReprocess} disabled={reprocessing} aria-busy={reprocessing}>
                      {reprocessing ? 'Reprocessing…' : 'Reprocess'}
                    </button>
                    <button className="btn" onClick={handleForceUpgrade} disabled={forceUpgrading} aria-busy={forceUpgrading}>
                      {forceUpgrading ? 'Checking upgrades…' : 'Force upgrade'}
                    </button>
                  </div>

                </div>

                {/* Operation log column — only shown when there is something to display */}
                {(discovering || reprocessing || forceUpgrading ||
                  discoverResult || discoverError ||
                  reprocessLog.length > 0 || reprocessResult || reprocessError ||
                  forceUpgradeLog.length > 0 || forceUpgradeResult || forceUpgradeError) && (
                  <div style={{ position: 'relative', flex: 1, minWidth: 0 }}>
                  <div
                    ref={logScrollRef}
                    aria-live="polite"
                    aria-atomic="false"
                    aria-label="Operation log"
                    role="log"
                    style={{
                      position: 'absolute',
                      inset: 0,
                      overflowY: 'auto',
                      background: 'var(--surface-2)',
                      borderRadius: 8,
                      padding: '10px 14px',
                      fontSize: 12,
                      fontFamily: 'monospace',
                      color: 'var(--text-2)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 3,
                    }}
                  >
                    {/* Discover */}
                    {(discovering || discoverResult || discoverError) && (
                      <div style={{ marginBottom: discoverResult || discoverError ? 4 : 0 }}>
                        <div style={{ fontWeight: 600, color: 'var(--text)', marginBottom: 2, fontFamily: 'inherit' }}>Re-discover</div>
                        {discovering && <div style={{ color: 'var(--text-3)' }}><i className="bx bx-loader-alt" style={{ marginRight: 4 }} aria-hidden="true" />Searching sources…</div>}
                        {discoverResult && <div role="status" style={{ color: 'var(--text-2)' }}>{discoverResult}</div>}
                        {discoverError && <div role="alert" style={{ color: 'var(--danger)' }}>{discoverError}</div>}
                      </div>
                    )}

                    {/* Reprocess */}
                    {(reprocessing || reprocessLog.length > 0 || reprocessResult || reprocessError) && (
                      <div style={{ marginBottom: reprocessResult || reprocessError ? 4 : 0 }}>
                        <div style={{ fontWeight: 600, color: 'var(--text)', marginBottom: 2, fontFamily: 'inherit' }}>Reprocess</div>
                        {reprocessLog.map((entry, i) => (
                          <div key={i}>
                            {entry.action === 'processed'
                              ? <i className="bx bx-check" style={{ color: 'var(--success)' }} />
                              : entry.action === 'queued' ? <i className="bx bx-refresh" /> : '—'}
                            {' '}Ch {entry.chapter_number} — {entry.action}
                          </div>
                        ))}
                        {reprocessing && <div style={{ color: 'var(--text-3)' }}>…</div>}
                        {reprocessResult && <div role="status" style={{ color: 'var(--text-2)' }}>{reprocessResult}</div>}
                        {reprocessError && <div role="alert" style={{ color: 'var(--danger)' }}>{reprocessError}</div>}
                      </div>
                    )}

                    {/* Force upgrade */}
                    {(forceUpgrading || forceUpgradeLog.length > 0 || forceUpgradeResult || forceUpgradeError) && (
                      <div>
                        <div style={{ fontWeight: 600, color: 'var(--text)', marginBottom: 2, fontFamily: 'inherit' }}>Force upgrade</div>
                        {forceUpgradeLog.map((entry, i) => (
                          <div key={i}><i className="bx bx-refresh" /> Ch {entry.chapter_number}: {entry.old_source} → {entry.new_source}</div>
                        ))}
                        {forceUpgrading && <div style={{ color: 'var(--text-3)' }}>…</div>}
                        {forceUpgradeResult && <div role="status" style={{ color: 'var(--text-2)' }}>{forceUpgradeResult}</div>}
                        {forceUpgradeError && <div role="alert" style={{ color: 'var(--danger)' }}>{forceUpgradeError}</div>}
                      </div>
                    )}
                  </div>
                  </div>
                )}
              </div>

              <dl className="info-cards" aria-label="Comic details">
                <div className="info-card">
                  <dt className="info-card-label">Poll interval</dt>
                  <dd className="info-card-value">
                    {comic.poll_override_days != null
                      ? `${comic.poll_override_days} days`
                      : comic.inferred_cadence_days != null
                        ? `${comic.inferred_cadence_days.toFixed(1)} days`
                        : '7 days'}
                  </dd>
                  <dd className="info-card-sub">
                    {comic.poll_override_days != null
                      ? comic.inferred_cadence_days != null
                        ? `Override (inferred: ${comic.inferred_cadence_days.toFixed(1)}d)`
                        : 'Override'
                      : comic.inferred_cadence_days != null ? 'Inferred' : 'Default'}
                  </dd>
                </div>
                <div className="info-card">
                  <dt className="info-card-label">Upgrade interval</dt>
                  <dd className="info-card-value">{comic.upgrade_override_days != null ? `${comic.upgrade_override_days} days` : '—'}</dd>
                  <dd className="info-card-sub">{comic.upgrade_override_days != null ? 'Override' : 'Uses poll interval'}</dd>
                </div>
                <div className="info-card">
                  <dt className="info-card-label">Last upgrade check</dt>
                  <dd className="info-card-value">{comic.last_upgrade_check_at ? formatRelative(comic.last_upgrade_check_at) : 'Never'}</dd>
                  <dd className="info-card-sub">
                    {comic.last_upgrade_check_at
                      ? new Date(comic.last_upgrade_check_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
                      : '—'}
                  </dd>
                </div>
                <div className="info-card">
                  <dt className="info-card-label">Aliases</dt>
                  <dd className="info-card-value">{comic.aliases.length}</dd>
                  <dd className="info-card-sub">{comic.aliases.length > 0 ? comic.aliases.map(a => a.title).join(', ') : 'None'}</dd>
                </div>
                <div className="info-card">
                  <dt className="info-card-label">Source pins</dt>
                  <dd className="info-card-value">{pins.length}</dd>
                  <dd className="info-card-sub">{pins.length > 0 ? pins.map(p => p.source_name).join(', ') : 'None'}</dd>
                </div>
              </dl>

              <div className="section-header">
                <span className="section-title" id="chapters-heading">Chapters</span>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
                <div className="chapter-filters" role="group" aria-label="Filter chapters by status" style={{ marginBottom: 0 }}>
                  {(['', 'queued', 'downloading', 'relocating', 'available', 'failed'] as const).map(s => {
                    const label = s === '' ? 'All' : s.charAt(0).toUpperCase() + s.slice(1)
                    const count = s === '' ? chaptersTotal : statusCounts[s as ChapterStatus]
                    return (
                      <button key={s} className={`chip${chapterStatus === s ? ' active' : ''}`}
                        aria-pressed={chapterStatus === s}
                        onClick={() => { setChapterStatus(s); setChapterPage(1) }}>
                        {label} ({count})
                      </button>
                    )
                  })}
                </div>
                <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexShrink: 0, height: 32, minHeight: 32 }}>
                  <Pagination page={chapterPage} total={chaptersTotal} perPage={chapterPerPage} onChange={p => setChapterPage(p)} />
                  {chapterTotalPages > 1 && <div style={{ width: 1, height: 16, background: 'var(--border)', margin: '0 2px' }} />}
                  {[25, 50, 100].map(n => (
                    <button key={n} className={`btn${chapterPerPage === n ? ' primary' : ''}`}
                      style={{ padding: '4px 8px', fontSize: 12 }}
                      onClick={() => { setChapterPerPage(n); setChapterPage(1) }}>{n}</button>
                  ))}
                </div>
              </div>

              <div className="table-card">
                <table aria-labelledby="chapters-heading">
                  <thead>
                    <tr style={{ borderBottom: `2px solid var(--border)` }}>
                      <th scope="col" style={thStyle}>Chapter</th>
                      <th scope="col" style={thStyle}>Volume</th>
                      <th scope="col" style={thStyle}>Source</th>
                      <th scope="col" style={thStyle}>Download</th>
                      <th scope="col" style={thStyle}>Relocation</th>
                      <th scope="col" style={thStyle}>Library path</th>
                      <th scope="col" style={thStyle}><span className="sr-only">Actions</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {chapters.map(ch => (
                      <tr key={ch.assignment_id} style={{ borderBottom: `1px solid var(--border)` }}>
                        <td style={tdStyle}><strong>Ch. {ch.chapter_number}</strong></td>
                        <td style={{ ...tdStyle, color: 'var(--text-2)' }}>{ch.volume_number != null ? `Vol. ${ch.volume_number}` : '—'}</td>
                        <td style={tdStyle}><span className="tag">{ch.source_name}</span></td>
                        <td style={tdStyle}>{downloadStatusCell(ch.download_status)}</td>
                        <td style={tdStyle}>{relocationStatusCell(ch.relocation_status)}</td>
                        <td style={{ ...tdStyle, maxWidth: 280, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis', fontSize: '11.5px', color: 'var(--text-2)' }}>
                          {ch.library_path ?? '—'}
                        </td>
                        <td style={{ ...tdStyle, whiteSpace: 'nowrap' }}>
                          {chapterUpgradeMsgs[ch.assignment_id] ? (
                            <span style={{ fontSize: 11, color: chapterUpgradeMsgs[ch.assignment_id] === 'Upgrade queued' ? 'var(--success)' : 'var(--text-3)' }}>
                              {chapterUpgradeMsgs[ch.assignment_id]}
                            </span>
                          ) : (
                            <button className="btn" style={{ fontSize: 11, padding: '3px 8px' }}
                              onClick={() => handleForceUpgradeChapter(ch.assignment_id)}
                              disabled={upgradingChapterId === ch.assignment_id}
                              aria-busy={upgradingChapterId === ch.assignment_id}
                              aria-label={`Upgrade chapter ${ch.chapter_number}`}>
                              {upgradingChapterId === ch.assignment_id ? '…' : 'Upgrade'}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* =========================================================== */}
          {/* SETTINGS TAB                                                  */}
          {/* =========================================================== */}
          {activeTab === 'settings' && (
            <div id="comic-panel-settings" role="tabpanel" aria-labelledby="comic-tab-settings" style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>

              {/* Cover */}
              <div className="card" style={{ padding: 20 }}>
                <h2 style={panelHeadingStyle}>Cover</h2>
                <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
                  <button onClick={() => setCoverTab('url')} className={`btn${coverTab === 'url' ? ' primary' : ''}`} style={{ fontSize: 12, padding: '5px 10px' }}>URL</button>
                  <button onClick={() => setCoverTab('file')} className={`btn${coverTab === 'file' ? ' primary' : ''}`} style={{ fontSize: 12, padding: '5px 10px' }}>Upload</button>
                </div>
                {coverTab === 'url' && (
                  <div style={{ display: 'flex', gap: 6, maxWidth: 480 }}>
                    <input type="url" value={coverUrl} onChange={e => setCoverUrl(e.target.value)}
                      placeholder="https://…" className="input" style={{ flex: 1, fontSize: 13 }}
                      aria-label="Cover image URL" />
                    <button onClick={handleCoverSubmit} disabled={coverSubmitting || !coverUrl} className="btn primary"
                      style={{ fontSize: 12, opacity: (coverSubmitting || !coverUrl) ? 0.6 : 1 }}>
                      {coverSubmitting ? 'Saving…' : 'Save'}
                    </button>
                  </div>
                )}
                {coverTab === 'file' && (
                  <div style={{ display: 'flex', gap: 6, maxWidth: 480 }}>
                    <input type="file" accept="image/*" onChange={e => setCoverFile(e.target.files?.[0] ?? null)} style={{ flex: 1, fontSize: 13 }}
                      aria-label="Upload cover image" />
                    <button onClick={handleCoverSubmit} disabled={coverSubmitting || !coverFile} className="btn primary"
                      style={{ fontSize: 12, opacity: (coverSubmitting || !coverFile) ? 0.6 : 1 }}>
                      {coverSubmitting ? 'Saving…' : 'Save'}
                    </button>
                  </div>
                )}
                {coverError && <p role="alert" style={{ fontSize: 13, color: 'var(--danger)', marginTop: 6 }}>{coverError}</p>}
              </div>

              {/* Comic settings */}
              <div className="card" style={{ padding: 20 }}>
                <h2 style={panelHeadingStyle}>Comic settings</h2>

                <div style={{ marginBottom: 10 }}>
                  <label style={editLabelStyle}>
                    Library title
                    <input type="text" value={editLibraryTitle} onChange={e => setEditLibraryTitle(e.target.value)} style={editInputStyle} />
                  </label>
                  <p style={{ fontSize: 11, color: 'var(--text-3)', margin: '2px 0 0' }}>Changing this will not rename existing library files.</p>
                </div>

                <div style={{ marginBottom: 10 }}>
                  <label htmlFor="edit-poll-days" style={editLabelStyle}>Poll interval (days)</label>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                    <input id="edit-poll-days" className="input" style={{ width: 80 }} type="number" min="1" step="1"
                      value={editPollClear ? '' : editPollDays} disabled={editPollClear}
                      onChange={e => setEditPollDays(e.target.value)} />
                    <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                      <input type="checkbox" checked={editPollClear} onChange={e => setEditPollClear(e.target.checked)} />
                      Use inferred cadence
                    </label>
                  </div>
                </div>

                <div style={{ marginBottom: 12 }}>
                  <label htmlFor="edit-upgrade-days" style={editLabelStyle}>Upgrade interval (days)</label>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                    <input id="edit-upgrade-days" type="number" className="input" min="1" step="1"
                      value={editUpgradeClear ? '' : editUpgradeDays} disabled={editUpgradeClear}
                      onChange={e => setEditUpgradeDays(e.target.value)} style={{ width: 80 }} />
                    <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                      <input type="checkbox" checked={editUpgradeClear} onChange={e => setEditUpgradeClear(e.target.checked)} />
                      Use poll interval
                    </label>
                  </div>
                </div>

                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>Aliases</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
                    {(comic.aliases ?? []).filter(a => !pendingAliasDeletes.has(a.id)).map(a => (
                      <span key={a.id} style={aliasChipStyle}>
                        {a.title}
                        <button onClick={() => handleStagedDeleteAlias(a.id)}
                          style={{ background: 'none', border: 'none', cursor: 'pointer', marginLeft: 4, color: 'var(--text-3)', fontSize: 12, padding: 0 }}
                          aria-label={`Remove alias ${a.title}`}><i className="bx bx-x" /></button>
                      </span>
                    ))}
                    {pendingAliasAdds.map(title => (
                      <span key={title} style={{ ...aliasChipStyle, borderStyle: 'dashed', color: 'var(--accent)' }}>
                        {title}
                        <button onClick={() => handleRemoveStagedAdd(title)}
                          style={{ background: 'none', border: 'none', cursor: 'pointer', marginLeft: 4, color: 'var(--text-3)', fontSize: 12, padding: 0 }}
                          aria-label={`Remove pending alias ${title}`}><i className="bx bx-x" /></button>
                      </span>
                    ))}
                    {(comic.aliases ?? []).filter(a => !pendingAliasDeletes.has(a.id)).length === 0 && pendingAliasAdds.length === 0 && (
                      <span style={{ fontSize: 12, color: 'var(--text-3)' }}>None</span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <input type="text" placeholder="Add alias…" value={newAlias}
                      onChange={e => setNewAlias(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && handleStagedAddAlias()}
                      style={{ ...editInputStyle, marginTop: 0, flex: 1 }}
                      aria-label="New alias" />
                    <button onClick={handleStagedAddAlias} disabled={!newAlias.trim()} className="btn"
                      style={{ fontSize: 12, opacity: !newAlias.trim() ? 0.6 : 1 }}>Add</button>
                  </div>
                  {aliasError && <p role="alert" style={{ fontSize: 12, color: 'var(--danger)', marginTop: 4 }}>{aliasError}</p>}
                </div>

                <button onClick={handleEditSubmit} disabled={editSubmitting} className="btn primary"
                  style={{ opacity: editSubmitting ? 0.6 : 1 }}>
                  {editSubmitting ? 'Saving…' : 'Save changes'}
                </button>
                {editError && <p role="alert" style={{ fontSize: 13, color: 'var(--danger)', marginTop: 8 }}>{editError}</p>}
              </div>

              {/* Source pins */}
              <div className="card" style={{ padding: 20 }}>
                <h2 style={panelHeadingStyle}>Source pins</h2>
                <p style={{ fontSize: 13, color: 'var(--text-2)', marginBottom: 12 }}>
                  Pins tell Otaki to fetch chapters directly by manga ID instead of searching by title.
                  Useful when different comics share the same title.
                </p>
                <div style={{ marginBottom: 12 }}>
                  {pins.filter(p => !removedPinIds.has(p.id)).length === 0 && pendingPins.length === 0 ? (
                    <div style={{ fontSize: 12, color: 'var(--text-3)' }}>No pins set.</div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      {pins.filter(p => !removedPinIds.has(p.id)).map(p => (
                        <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                          <span style={pinChipStyle}>{p.source_name}</span>
                          <span style={{ fontFamily: 'monospace', color: 'var(--text)' }}>{p.suwayomi_manga_id}</span>
                          <button onClick={() => removeSavedPin(p.id)} style={removeBtnStyle} aria-label="Remove pin"><i className="bx bx-x" /></button>
                        </div>
                      ))}
                      {pendingPins.map((p, i) => (
                        <div key={`pending-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                          <span style={{ ...pinChipStyle, borderStyle: 'dashed', color: 'var(--accent)' }}>{p.source_name}</span>
                          <span style={{ fontFamily: 'monospace', color: 'var(--text)' }}>{p.suwayomi_manga_id}</span>
                          <button onClick={() => removePendingPin(i)} style={removeBtnStyle} aria-label="Remove pending pin"><i className="bx bx-x" /></button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div style={{ marginBottom: 12, borderTop: `1px solid var(--border)`, paddingTop: 12 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>Add a pin</div>
                  <div style={{ display: 'flex', gap: 6, marginBottom: 6, flexWrap: 'wrap' }}>
                    <select value={pinSearchSourceId} onChange={e => setPinSearchSourceId(e.target.value ? Number(e.target.value) : '')}
                      className="select" style={{ fontSize: 12 }} aria-label="Source to search">
                      <option value="">Select source…</option>
                      {sources.filter(s => s.enabled).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                    <input type="text" placeholder="Search title…" value={pinSearchQuery}
                      onChange={e => setPinSearchQuery(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && handlePinSearch()}
                      className="input" style={{ flex: 1, minWidth: 140, fontSize: 12 }}
                      aria-label="Search title on selected source" />
                    <button onClick={handlePinSearch} disabled={!pinSearchSourceId || !pinSearchQuery.trim() || pinSearching}
                      className="btn" style={{ fontSize: 12, padding: '5px 10px', opacity: (!pinSearchSourceId || !pinSearchQuery.trim() || pinSearching) ? 0.6 : 1 }}>
                      {pinSearching ? 'Searching…' : 'Search'}
                    </button>
                  </div>
                  {pinSearching && pinSearchResults.length === 0 && (
                    <p style={{ fontSize: 12, color: 'var(--text-3)', margin: '4px 0 0' }}>
                      <i className="bx bx-loader-alt" style={{ marginRight: 4 }} aria-hidden="true" />Searching…
                    </p>
                  )}
                  {!pinSearching && pinSearchDone && pinSearchResults.length === 0 && (
                    <p style={{ fontSize: 12, color: 'var(--text-3)', margin: '4px 0 0' }}>No results on this source.</p>
                  )}
                  {pinSearchResults.length > 0 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 180, overflowY: 'auto', border: `1px solid var(--border)`, borderRadius: 4, padding: 6, background: 'var(--surface)' }}>
                      {pinSearchResults.map(r => (
                        <button key={r.url} onClick={() => stagePinFromResult(r)}
                          className="pin-result-btn"
                          aria-label={`Add pin: ${r.title}`}>
                          <span style={{ fontWeight: 500 }}>{r.title}</span>
                          <span style={{ color: 'var(--text-2)', fontSize: 11 }}>ID: {r.suwayomi_manga_id}</span>
                        </button>
                      ))}
                      {pinSearching && (
                        <p style={{ fontSize: 11, color: 'var(--text-3)', margin: '4px 0 0', padding: '2px 6px' }}>
                          <i className="bx bx-loader-alt" style={{ marginRight: 4 }} aria-hidden="true" />Still searching…
                        </p>
                      )}
                    </div>
                  )}
                </div>
                <button onClick={handleSavePins} disabled={pinSaving} className="btn primary"
                  style={{ fontSize: 12, padding: '6px 12px', opacity: pinSaving ? 0.6 : 1 }}>
                  {pinSaving ? 'Saving…' : 'Save pins'}
                </button>
                {pinResult && <p role="status" style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 8 }}>{pinResult}</p>}
                {pinError && <p role="alert" style={{ fontSize: 12, color: 'var(--danger)', marginTop: 8 }}>{pinError}</p>}
              </div>

              {/* Source priorities */}
              {(() => {
                if (overrideDraft === null && sourceOverrides.length > 0) initOverrideDraft(sourceOverrides)
                const display = overrideDraft ?? sourceOverrides
                return (
                  <div className="card" style={{ padding: 20 }}>
                    <h2 style={panelHeadingStyle}>Source priorities</h2>
                    <p style={{ fontSize: 13, color: 'var(--text-2)', marginBottom: 12 }}>
                      Drag to reorder sources for this comic. Overridden positions are highlighted.
                      Changes take effect on the next upgrade check — use Force upgrade to apply immediately.
                    </p>
                    <DndContext
                      sensors={overrideSensors}
                      collisionDetection={closestCenter}
                      onDragEnd={handleOverrideDragEnd}
                      modifiers={[restrictToVerticalAxis, restrictToParentElement]}
                    >
                      <SortableContext items={display.map(e => e.source_id)} strategy={verticalListSortingStrategy}>
                        <div role="list" aria-label="Source priority order" style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
                          {display.map((entry, index) => (
                            <SortableOverrideRow
                              key={entry.source_id}
                              entry={entry}
                              index={index}
                              total={display.length}
                              showOverrideBadge={overrideDraft === null}
                              onMoveUp={() => overrideMoveUp(index)}
                              onMoveDown={() => overrideMoveDown(index)}
                            />
                          ))}
                        </div>
                      </SortableContext>
                    </DndContext>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <button onClick={handleSaveOverrides} disabled={overrideSaving || overrideDraft === null}
                        className="btn primary" style={{ fontSize: 12, padding: '6px 12px', opacity: (overrideSaving || overrideDraft === null) ? 0.6 : 1 }}>
                        {overrideSaving ? 'Saving…' : 'Save order'}
                      </button>
                      <button onClick={handleResetOverrides} disabled={overrideSaving} className="btn" style={{ fontSize: 12 }}>
                        Reset to global defaults
                      </button>
                    </div>
                    {overrideResult && <p role="status" style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 8 }}>{overrideResult}</p>}
                    {overrideError && <p role="alert" style={{ fontSize: 12, color: 'var(--danger)', marginTop: 8 }}>{overrideError}</p>}
                  </div>
                )
              })()}

            </div>
          )}
        </>
      )}
    </PageLayout>
  )
}

const thStyle: React.CSSProperties = {
  padding: '8px 12px',
  fontSize: 13,
  fontWeight: 600,
  color: 'var(--text-2)',
}

const tdStyle: React.CSSProperties = {
  padding: '10px 12px',
  verticalAlign: 'middle',
  fontSize: 13,
  color: 'var(--text)',
  textAlign: 'center'
}

const editLabelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 13,
  fontWeight: 600,
  color: 'var(--text)',
}

const editInputStyle: React.CSSProperties = {
  display: 'block',
  marginTop: 4,
  padding: '6px 10px',
  fontSize: 13,
  border: `1px solid var(--border)`,
  borderRadius: 'var(--radius-sm)',
  width: '100%',
  boxSizing: 'border-box',
  background: 'var(--surface)',
  color: 'var(--text)',
  fontFamily: 'inherit',
}

const aliasChipStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  padding: '2px 8px',
  fontSize: 12,
  background: 'var(--surface-2)',
  border: `1px solid var(--border)`,
  borderRadius: 12,
  color: 'var(--text)',
}

const pinChipStyle: React.CSSProperties = {
  display: 'inline-block',
  padding: '1px 6px',
  fontSize: 11,
  background: 'var(--surface-2)',
  border: `1px solid var(--border)`,
  borderRadius: 10,
  color: 'var(--text)',
  flexShrink: 0,
}

const panelHeadingStyle: React.CSSProperties = {
  fontSize: 16,
  fontWeight: 700,
  color: 'var(--text)',
  margin: '0 0 16px',
}

const removeBtnStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  color: 'var(--text-3)',
  fontSize: 12,
  padding: 0,
  lineHeight: 1,
}


