# Playwright Test Updates — 1.2 UI Improvements

**Date:** 2026-04-13  
**Branch:** feat/1.2-ui-improvements  
**Scope:** Update all e2e tests to match the new app shell, page layout, SSE search, and cover all features added since #102.

---

## Context

The 1.2 UI update introduced:
- `AppShell` — persistent sidebar nav replaces per-page back/forward buttons
- `PageLayout` — shared title + action bar wrapper used by Library, Sources, Settings, Search, Comic
- Login reskin — new button text ("Sign in"), error rendered via CSS var not inline `color: red`
- Library defaults to **grid view** and uses a paginated `ComicListPage` response shape
- Search uses **SSE streaming** via `/api/search/stream?q=` with per-source chips
- Settings is now **tabbed** (Polling / Paths / Relocation / Suwayomi / Backup); fields only render when their tab is active
- Comic detail page fetches chapters **separately** via `/api/requests/{id}/chapters` (paginated); new panels for force upgrade, source overrides, pin management

No e2e files were touched since #102. All of the above breaks existing tests or leaves new features untested.

---

## Design

### Shared conventions

- **SSE mock helper**: all tests needing to mock a streaming endpoint use a shared `fulfillSSE(route, events)` helper defined at the top of each relevant spec. It calls `route.fulfill({ status: 200, contentType: 'text/event-stream', body: events.map(e => `data: ${e}`).join('\n') + '\n' })`.
- **Back button removal**: all "← Library button" tests are deleted. The sidebar is always present and one sidebar navigation test in `library.spec.ts` covers that concern.
- **Tab navigation**: settings tests click the relevant tab button before interacting with its fields.

---

### `login.spec.ts` — selector fixes only

| Old | New |
|---|---|
| `getByRole('heading', { name: 'Log in to Otaki' })` (×2) | `getByRole('button', { name: 'Sign in' })` to confirm page loaded |
| `getByRole('button', { name: 'Log in' })` | `getByRole('button', { name: 'Sign in' })` |
| `locator('p[style*="color: red"]')` | `locator('.card form p')` |

---

### `library.spec.ts` — fixes + new coverage

**Fixes:**
- Mock response for `/api/requests` changes from a plain array to `{ items: [...], total: N, page: 1, per_page: 25 }`
- `getByRole('row', { name: /One Piece/ }).click()` → `getByRole('button', { name: /View One Piece/ }).click()` (grid view default; `CoverCard` renders `aria-label="View {title}"`)

**New tests:**

1. **Sidebar navigation** — authenticated; go to `/library`; click "Search" nav button → URL is `/search`; click "Sources" → URL is `/sources`
2. **Search input filters** — mock `/api/requests*` to capture params; type in search box → after debounce, request contains `search=one+piece` (or similar)
3. **Status chip** — click "Tracking" chip → request contains `status=tracking`; click "All" → `status` param absent
4. **Pagination** — mock returns `{ total: 30, per_page: 25, page: 1 }`; pagination controls render; click Next → request contains `page=2`

---

### `settings.spec.ts` — tab fixes + backup tests

**Removed:** "← Library button navigates back to /library"

**Fixed tests (tab navigation):**

- `settings values render in form fields` — split into three tests:
  - *Suwayomi tab*: click "Suwayomi" tab → assert `getByLabel('Server URL')` and `getByLabel('Username')` values
  - *Paths tab*: click "Paths" tab → assert `getByLabel('Download path')` and `getByLabel('Library path')` values
  - *Paths tab (naming)*: click "Paths" tab → assert `getByLabel('Format')` value and preview text

- `Save & Test fires PATCH` — click "Suwayomi" tab first; `getByLabel('URL')` → `getByLabel('Server URL')`

- `Save & Test shows success message` — click "Suwayomi" tab first

- `connection save error shows error message` — click "Suwayomi" tab first

- `Paths Save fires PATCH` — click "Paths" tab first; `locator('section', ...)` scoped Save → `getByRole('button', { name: 'Save' })` (one Save visible per tab)

- `Poll days Save fires PATCH` — Polling is the default tab so no tab click needed; `locator('section', ...)` scoped Save → `getByRole('button', { name: 'Save' })`

- `Chapter naming Save fires PATCH` — click "Paths" tab first; scope Save to the naming form via `page.locator('form', { has: page.getByLabel('Format') }).getByRole('button', { name: 'Save' })`

**New — Backup tab:**

1. **Export fires GET with format param** — click "Backup" tab; mock `**/api/settings/export*` to intercept; select "JSON" radio; click Export → request URL contains `format=json`
2. **Import preview renders totals** — click "Backup" tab; fill server path input; mock POST `/api/settings/import/preview` returning `{ new_comics: [{ backup_id: 1, title: 'One Piece', ... }], new_sources: [], source_conflicts: [], comic_conflicts: [], totals: { sources: 0, comics: 1, chapters: 5, covers: 0 } }`; click Preview → totals summary text visible
3. **Import apply shows success** — after preview mock, mock POST `/api/settings/import/apply` returning `{ comics: 1, chapters: 5, covers: 0, skipped: 0 }`; click Apply → success message visible

---

### `sources.spec.ts` — one removal only

Remove: "authenticated: ← Library button on Sources navigates back to /library"

All other tests pass without changes.

---

### `search.spec.ts` — SSE fix + chip tests

**Removed:** "Search page has a ← Library button", "← Library button navigates to /library"

**Fixed throughout:**
- Route pattern: `**/api/search*` → `**/api/search/stream*`
- `route.fulfill` body: SSE format with `Content-Type: text/event-stream`
  ```
  data: {"results": [{...}], "source_name": "MangaDex"}
  data: [DONE]
  ```
- Mock `SearchResult` objects gain `cover_display_url: null` and `suwayomi_manga_id: 'mock-id-1'`
- `locator('[role="button"]').filter({ hasText: '...' })` → `getByRole('button').filter({ hasText: '...' })`
- `getByRole('button', { name: '← Back to results' })` → `getByRole('button', { name: /back to results/i })`

**SSE mock helper** (`fulfillSSE`):
```ts
function fulfillSSE(route: Route, payloads: unknown[]) {
  const body = payloads.map(p => `data: ${typeof p === 'string' ? p : JSON.stringify(p)}`).join('\n') + '\n'
  route.fulfill({ status: 200, contentType: 'text/event-stream', body })
}
```

**New — source chip tests** (use the same mock setup as existing result tests):

1. **Chips render after search** — after mock search returns MangaDex results, a chip labelled "MangaDex" is visible
2. **Clicking a chip hides its results** — MangaDex and MangaPlus both return results; click MangaDex chip → "One Piece" cards not visible, "ワンピース" still visible
3. **Clicking chip again restores results** — click MangaDex chip again → "One Piece" visible again

---

### `comic.spec.ts` — mock fix + new coverage

**Removed:** "← Library button navigates back to /library"

**Fixed:**
- `MOCK_COMIC` response from `/api/requests/1`: remove `chapters` field, add `aliases: []` and `inferred_cadence_days: null`
- All tests that assert chapter cells: add `page.route('**/api/requests/1/chapters*', ...)` returning `{ items: [ch1, ch2], total: 2, page: 1, per_page: 50 }` before the page navigation
- `MOCK_CHAPTERS` constant extracted for reuse across chapter-related tests

**New tests:**

1. **Force upgrade (bulk)** — mock GET chapters + comic; mock POST `/api/requests/1/force-upgrade` with SSE: `{ type: 'chapter', chapter_number: 1, old_source: 'MangaPlus', new_source: 'MangaDex' }` then `{ type: 'done', queued: 1 }` then `[DONE]`; click "Force upgrade" button → chapter log entry visible → summary "1 upgrade(s) queued." visible

2. **Force upgrade (single chapter)** — mock chapters; mock POST `/api/requests/1/chapters/55/force-upgrade` SSE: `{ type: 'done', queued: 1 }` then `[DONE]`; click per-row upgrade button for ch1 → "Upgrade queued" message on that row

3. **Source overrides panel** — mock GET `/api/requests/1/source-overrides` returning two entries; click "Source overrides" button → source names visible; click Save → PUT `/api/requests/1/source-overrides` fires with `{ source_ids: [...] }`

4. **Pin management panel** — mock GET `/api/requests/1/pins` returning one pin; mock GET `/api/sources`; click "Manage pins" button → pin source name visible; click Remove on the pin → click Save → PUT `/api/requests/1/pins` fires with `{ pins: [] }`

---

## Files changed

| File | Type |
|---|---|
| `frontend/e2e/login.spec.ts` | fixes |
| `frontend/e2e/library.spec.ts` | fixes + new tests |
| `frontend/e2e/settings.spec.ts` | fixes + new tests |
| `frontend/e2e/sources.spec.ts` | fix (removal) |
| `frontend/e2e/search.spec.ts` | fixes + new tests |
| `frontend/e2e/comic.spec.ts` | fixes + new tests |

No new spec files. No production code changes.
