# Comic Detail Page Design

**Date:** 2026-03-27
**Issue:** #24
**Branch:** feat/comic-detail-page

---

## Overview

A read-only comic detail page at `/comics/:id`. Shows comic metadata and a full chapter table. Consistent with the plain inline-style approach used in `Library.tsx` and `Search.tsx`. Quality data, rescan, and force-upgrade are deferred to issues #53–#58.

---

## Navigation

- Accessed from Library page by clicking any comic row (`navigate(\`/comics/${comic.id}\`)`).
- `← Library` button top-right of the heading area, navigates to `/library`.

---

## Layout

### Header

Flex row: cover image left, metadata right.

| Field | Source |
|---|---|
| Cover image | `GET /api/requests/{id}/cover` (48×64, hidden on error) |
| Title | `comic.title` |
| Status | `comic.status` |
| Next poll | `comic.next_poll_at` formatted relative (reuse `formatRelative` from Library) |
| Last upgrade check | `comic.last_upgrade_check_at` formatted relative |

### Chapter table

Columns: Chapter, Volume, Source, Status, Relocation, Library path.

| Column | Field |
|---|---|
| Chapter | `chapter_number` |
| Volume | `volume_number` (shown as `—` if null) |
| Source | `source_name` |
| Status | `download_status` |
| Relocation | `relocation_status` |
| Library path | `library_path` (shown as `—` if null, truncated with `overflow: hidden`) |

Ordered by `chapter_number` ascending (API guarantees this).

---

## Data

- **Single query:** `GET /api/requests/{id}` via TanStack Query (`queryKey: ['comic', id]`).
- `id` from `useParams<{ id: string }>()`, parsed to int.
- Loading: `<p>Loading…</p>`
- Error: `<p style={{ color: 'red' }}>{extractDetail(error)}</p>`
- 404 / not found: error state covers this.

---

## Files

### Creates
- `frontend/src/pages/Comic.tsx`
- `frontend/e2e/comic.spec.ts`

### Modifies
- `frontend/src/App.tsx` — replace `<Placeholder name="Comic" />` with `<Comic />`

---

## State

All state via TanStack Query. No local component state needed beyond what the query provides.

---

## Helpers

`formatRelative` is defined in `Library.tsx` — move it to `frontend/src/utils/format.ts` and import in both `Library.tsx` and `Comic.tsx`.

---

## Tests

`frontend/e2e/comic.spec.ts` — Playwright tests:
- Unauthenticated: navigating to `/comics/1` redirects to `/login`
- Authenticated: page renders the comic title as a heading
- Authenticated: chapter table rows are visible
- Library row click navigates to `/comics/{id}`
- `← Library` button navigates back to `/library`
