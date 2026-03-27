# Sources Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a sources management page at `/sources` with a priority-ordered list (↑↓ reorder + Save) and per-source enabled toggles.

**Architecture:** `GET /api/sources` via TanStack Query populates local state; ↑↓ buttons reorder local state only; a "Save order" button appears when the order differs from the server and fires `PATCH /api/sources/{id}` for each source with its new priority index; enabled toggles fire `PATCH /api/sources/{id}` immediately. Styled as a plain numbered list matching Setup Step 3's selected-sources panel.

**Tech Stack:** React 18, TypeScript, TanStack Query v5, React Router v6, inline styles only, Playwright for e2e tests.

---

### Task 1: Scaffold `Sources.tsx`, wire `App.tsx`, add Library nav button, navigation tests

**Files:**
- Create: `frontend/src/pages/Sources.tsx` (stub)
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/Library.tsx`
- Create: `frontend/e2e/sources.spec.ts` (navigation tests only)

- [ ] **Step 1: Create stub `frontend/src/pages/Sources.tsx`**

```tsx
export default function Sources() {
  return <p>Sources</p>
}
```

- [ ] **Step 2: Wire `Sources` into `frontend/src/App.tsx`**

Add import alongside other page imports:
```ts
import Sources from './pages/Sources'
```

Replace:
```tsx
<Route path="/sources" element={<Placeholder name="Sources" />} />
```
With:
```tsx
<Route path="/sources" element={<Sources />} />
```

- [ ] **Step 3: Add Sources nav button to `frontend/src/pages/Library.tsx`**

The Library header already has a Search button top-right. The heading area is a flex row with `justifyContent: 'space-between'`. Add a Sources button next to Search in a small button group:

Current header JSX:
```tsx
<div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
  <h1 style={{ margin: 0 }}>Library</h1>
  <button onClick={() => navigate('/search')} style={linkButtonStyle}>Search</button>
</div>
```

Replace with:
```tsx
<div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
  <h1 style={{ margin: 0 }}>Library</h1>
  <div style={{ display: 'flex', gap: 16 }}>
    <button onClick={() => navigate('/search')} style={linkButtonStyle}>Search</button>
    <button onClick={() => navigate('/sources')} style={linkButtonStyle}>Sources</button>
  </div>
</div>
```

- [ ] **Step 4: Verify build**

```bash
cd frontend && npm run build
```
Expected: exits 0.

- [ ] **Step 5: Write navigation tests in `frontend/e2e/sources.spec.ts`**

```ts
import { test, expect } from '@playwright/test'
import { resetBackend, BACKEND_URL } from './reset-backend.js'

const ADMIN_USERNAME = 'admin'
const ADMIN_PASSWORD = 'adminpass'

test.beforeAll(async () => {
  await resetBackend()

  await fetch(`${BACKEND_URL}/api/setup/user`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: ADMIN_USERNAME, password: ADMIN_PASSWORD }),
  })

  await fetch(`${BACKEND_URL}/api/setup/paths`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ download_path: '/tmp', library_path: '/tmp', create: true }),
  })
})

async function getToken(): Promise<string> {
  const res = await fetch(`${BACKEND_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: ADMIN_USERNAME, password: ADMIN_PASSWORD }),
  })
  const { access_token } = (await res.json()) as { access_token: string }
  return access_token
}

async function authenticate(page: import('@playwright/test').Page) {
  const token = await getToken()
  await page.goto('/login')
  await page.evaluate((t) => localStorage.setItem('otaki_token', t), token)
}

test('unauthenticated: navigating to /sources redirects to /login', async ({ page }) => {
  await page.goto('/sources')
  await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
})

test('authenticated: Library page has a Sources button', async ({ page }) => {
  await authenticate(page)
  await page.goto('/library')
  await expect(page.getByRole('button', { name: 'Sources' })).toBeVisible({ timeout: 5000 })
})

test('authenticated: Sources button on Library navigates to /sources', async ({ page }) => {
  await authenticate(page)
  await page.goto('/library')
  await page.getByRole('button', { name: 'Sources' }).click()
  await expect(page).toHaveURL(/\/sources/, { timeout: 5000 })
})

test('authenticated: ← Library button on Sources navigates back to /library', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/sources', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  )
  await page.goto('/sources')
  await page.getByRole('button', { name: '← Library' }).click()
  await expect(page).toHaveURL(/\/library/, { timeout: 5000 })
})
```

- [ ] **Step 6: Run navigation tests**

```bash
cd frontend && npx playwright test e2e/sources.spec.ts --project=chromium 2>&1 | tail -20
```

Expected: unauthenticated redirect, Library Sources button, Library→Sources navigation all pass. `← Library` button test fails (expected — stub has no button).

---

### Task 2: Full `Sources.tsx` implementation + interaction tests + ARCHITECTURE.md update

**Files:**
- Modify: `frontend/src/pages/Sources.tsx` (full implementation)
- Modify: `frontend/e2e/sources.spec.ts` (append interaction tests)
- Modify: `docs/ARCHITECTURE.md` (update Sources.tsx entry)

- [ ] **Step 1: Replace stub with full `frontend/src/pages/Sources.tsx`**

```tsx
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
    try {
      await apiFetch(`/api/sources/${source.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ enabled: !source.enabled }),
      })
      await queryClient.invalidateQueries({ queryKey: ['sources'] })
    } catch (err) {
      setToggleError(extractDetail(err))
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
```

- [ ] **Step 2: Verify build**

```bash
cd frontend && npm run build
```
Expected: exits 0.

- [ ] **Step 3: Append interaction tests to `frontend/e2e/sources.spec.ts`**

Add these tests after the existing 4 navigation tests. Do NOT redefine `authenticate`, `getToken`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, or `test.beforeAll` — they are already in the file.

```ts
const MOCK_SOURCES = [
  {
    id: 1,
    suwayomi_source_id: '1998944621602222888',
    name: 'MangaDex',
    priority: 1,
    enabled: true,
    created_at: '2025-03-01T00:00:00Z',
  },
  {
    id: 2,
    suwayomi_source_id: '2674952972886652325',
    name: 'MangaPlus',
    priority: 2,
    enabled: true,
    created_at: '2025-03-01T00:00:00Z',
  },
]

test('authenticated: sources list renders source names', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/sources', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SOURCES) }),
  )
  await page.goto('/sources')
  await expect(page.getByText('MangaDex')).toBeVisible({ timeout: 5000 })
  await expect(page.getByText('MangaPlus')).toBeVisible()
})

test('authenticated: Save order button hidden when order unchanged', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/sources', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SOURCES) }),
  )
  await page.goto('/sources')
  await expect(page.getByText('MangaDex')).toBeVisible({ timeout: 5000 })
  await expect(page.getByRole('button', { name: 'Save order' })).not.toBeVisible()
})

test('authenticated: ↑ button moves source up and shows Save order', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/sources', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SOURCES) }),
  )
  await page.goto('/sources')
  await expect(page.getByText('MangaDex')).toBeVisible({ timeout: 5000 })
  // MangaPlus is at index 1 (priority 2) — click its ↑ button
  await page.getByRole('button', { name: 'Move MangaPlus up' }).click()
  await expect(page.getByRole('button', { name: 'Save order' })).toBeVisible()
})

test('authenticated: enabled toggle fires PATCH immediately', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/sources', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SOURCES) }),
  )

  let patchBody: unknown = null
  await page.route('**/api/sources/1', route => {
    if (route.request().method() === 'PATCH') {
      patchBody = JSON.parse(route.request().postData() ?? '{}')
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...MOCK_SOURCES[0], enabled: false }) })
    } else {
      route.continue()
    }
  })

  await page.goto('/sources')
  await expect(page.getByText('MangaDex')).toBeVisible({ timeout: 5000 })
  await page.getByRole('checkbox', { name: 'Toggle MangaDex' }).uncheck()
  await expect.poll(() => patchBody).toEqual({ enabled: false })
})

test('authenticated: Save order fires PATCH for each source with new priorities', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/sources', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SOURCES) }),
  )

  const patches: Record<number, unknown> = {}
  await page.route('**/api/sources/1', route => {
    if (route.request().method() === 'PATCH') {
      patches[1] = JSON.parse(route.request().postData() ?? '{}')
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SOURCES[0]) })
    } else {
      route.continue()
    }
  })
  await page.route('**/api/sources/2', route => {
    if (route.request().method() === 'PATCH') {
      patches[2] = JSON.parse(route.request().postData() ?? '{}')
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SOURCES[1]) })
    } else {
      route.continue()
    }
  })

  await page.goto('/sources')
  await expect(page.getByText('MangaDex')).toBeVisible({ timeout: 5000 })
  // Move MangaPlus up → MangaPlus becomes priority 1, MangaDex becomes priority 2
  await page.getByRole('button', { name: 'Move MangaPlus up' }).click()
  await page.getByRole('button', { name: 'Save order' }).click()
  // After save, PATCH /api/sources/1 should have priority 2, /api/sources/2 should have priority 1
  await expect.poll(() => patches[2]).toEqual({ priority: 1 })
  await expect.poll(() => patches[1]).toEqual({ priority: 2 })
})

test('authenticated: API error shows error message', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/sources', route =>
    route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Database error' }),
    }),
  )
  await page.goto('/sources')
  await expect(page.getByText('Database error')).toBeVisible({ timeout: 5000 })
})
```

- [ ] **Step 4: Run all sources tests**

```bash
cd frontend && npx playwright test e2e/sources.spec.ts --project=chromium 2>&1 | tail -30
```

Expected: all 10 tests pass.

- [ ] **Step 5: Run full test suite to confirm no regressions**

```bash
cd frontend && npx playwright test --project=chromium 2>&1 | tail -30
```

Expected: all tests pass (pre-existing `setup.spec.ts` failures on `develop` are not regressions).

- [ ] **Step 6: Update `docs/ARCHITECTURE.md` Sources.tsx entry**

Find the current `Sources.tsx` entry (around line 491):

```
#### `frontend/src/pages/Sources.tsx`
Two panels:
- **Source priority** — drag-to-reorder list of sources. Each row: source name, priority number, enabled toggle, aggregate quality stats (% clean chapters from this source).
- **Watermark templates** — list with name, source, threshold. "Add template": image upload + canvas crop selector to define the watermark region.
```

Replace with:

```
#### `frontend/src/pages/Sources.tsx`
Priority management page at `/sources`. Single list of configured sources ordered by priority. Each row: position number, source name, enabled checkbox (immediate `PATCH /api/sources/{id}`), ↑/↓ buttons for reordering. "Save order" button appears when local order differs from server order; clicking it fires `PATCH /api/sources/{id}` for each source with its new priority index. Data from `GET /api/sources` via TanStack Query (`queryKey: ['sources']`). Quality stats and watermark templates deferred to 1.4.
```
