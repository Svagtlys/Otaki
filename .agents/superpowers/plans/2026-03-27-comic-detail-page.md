# Comic Detail Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only comic detail page at `/comics/:id` showing metadata and full chapter table, navigable from the Library page.

**Architecture:** Single TanStack Query fetch from `GET /api/requests/{id}`, rendered as a flex header (cover + metadata) and a chapter table. `formatRelative` is extracted to a shared utility before the component is built, then imported by both `Library.tsx` and `Comic.tsx`.

**Tech Stack:** React 18, TypeScript, TanStack Query v5, React Router v6, inline styles only, Playwright for e2e tests.

---

### Task 1: Extract `formatRelative` to a shared utility

**Files:**
- Create: `frontend/src/utils/format.ts`
- Modify: `frontend/src/pages/Library.tsx`

- [ ] **Step 1: Create `frontend/src/utils/format.ts`**

```ts
export function formatRelative(isoString: string | null): string {
  if (!isoString) return '—'
  const diffMs = new Date(isoString).getTime() - Date.now()
  if (diffMs <= 0) return 'overdue'
  const diffHours = diffMs / (1000 * 60 * 60)
  if (diffHours < 1) return 'in < 1 hour'
  if (diffHours < 24) return `in ${Math.round(diffHours)} hours`
  return `in ${Math.round(diffHours / 24)} days`
}
```

- [ ] **Step 2: Update `frontend/src/pages/Library.tsx` to import from the new util**

Replace the inline `formatRelative` definition (lines 28–36) with an import:

```ts
import { formatRelative } from '../utils/format'
```

Remove the following block from Library.tsx:

```ts
function formatRelative(isoString: string | null): string {
  if (!isoString) return '—'
  const diffMs = new Date(isoString).getTime() - Date.now()
  if (diffMs <= 0) return 'overdue'
  const diffHours = diffMs / (1000 * 60 * 60)
  if (diffHours < 1) return 'in < 1 hour'
  if (diffHours < 24) return `in ${Math.round(diffHours)} hours`
  return `in ${Math.round(diffHours / 24)} days`
}
```

- [ ] **Step 3: Verify the app still compiles**

Run from `frontend/`:
```bash
npm run build
```

Expected: exits 0, no TypeScript errors.

---

### Task 2: Scaffold `Comic.tsx`, wire `App.tsx`, write navigation tests

**Files:**
- Create: `frontend/src/pages/Comic.tsx` (stub)
- Modify: `frontend/src/App.tsx`
- Create: `frontend/e2e/comic.spec.ts` (navigation tests only)

- [ ] **Step 1: Create a stub `frontend/src/pages/Comic.tsx`**

```tsx
export default function Comic() {
  return <p>Comic detail</p>
}
```

- [ ] **Step 2: Wire `Comic` into `App.tsx`**

In `frontend/src/App.tsx`, add the import at the top with the other page imports:

```ts
import Comic from './pages/Comic'
```

Replace:
```tsx
<Route path="/comics/:id" element={<Placeholder name="Comic" />} />
```
With:
```tsx
<Route path="/comics/:id" element={<Comic />} />
```

- [ ] **Step 3: Verify the app compiles**

```bash
npm run build
```

Expected: exits 0.

- [ ] **Step 4: Write navigation tests in `frontend/e2e/comic.spec.ts`**

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

const MOCK_COMIC = {
  id: 1,
  title: 'One Piece',
  library_title: 'One Piece',
  cover_url: null,
  status: 'tracking',
  poll_override_days: 7.0,
  upgrade_override_days: null,
  next_poll_at: new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString(),
  next_upgrade_check_at: new Date(Date.now() + 3 * 24 * 60 * 60 * 1000).toISOString(),
  last_upgrade_check_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
  created_at: '2025-03-15T09:00:00Z',
  chapters: [
    {
      assignment_id: 55,
      chapter_number: 1,
      volume_number: 1,
      source_id: 2,
      source_name: 'MangaDex',
      download_status: 'done',
      is_active: true,
      downloaded_at: '2025-03-15T09:30:00Z',
      library_path: '/library/One Piece/One Piece - Ch.0001.cbz',
      relocation_status: 'done',
    },
    {
      assignment_id: 56,
      chapter_number: 2,
      volume_number: null,
      source_id: 2,
      source_name: 'MangaDex',
      download_status: 'queued',
      is_active: true,
      downloaded_at: null,
      library_path: null,
      relocation_status: 'pending',
    },
  ],
}

test('unauthenticated: navigating to /comics/1 redirects to /login', async ({ page }) => {
  await page.goto('/comics/1')
  await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
})

test('authenticated: Library row click navigates to /comics/{id}', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 1,
          title: 'One Piece',
          chapter_counts: { total: 2, done: 1, downloading: 0, queued: 1, failed: 0 },
          next_poll_at: MOCK_COMIC.next_poll_at,
        },
      ]),
    }),
  )
  await page.goto('/library')
  await expect(page.getByText('One Piece')).toBeVisible({ timeout: 5000 })
  await page.getByRole('row', { name: /One Piece/ }).click()
  await expect(page).toHaveURL(/\/comics\/1/, { timeout: 5000 })
})

test('authenticated: ← Library button navigates back to /library', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_COMIC) }),
  )
  await page.goto('/comics/1')
  await page.getByRole('button', { name: '← Library' }).click()
  await expect(page).toHaveURL(/\/library/, { timeout: 5000 })
})
```

- [ ] **Step 5: Run only the navigation tests to verify they pass (or fail for the right reason)**

```bash
cd frontend && npx playwright test e2e/comic.spec.ts --project=chromium 2>&1 | tail -20
```

The unauthenticated redirect and library nav tests should pass. The `← Library` button test will fail until Task 3 adds the button — that is expected at this stage.

---

### Task 3: Full `Comic.tsx` implementation with header, chapter table, and data tests

**Files:**
- Modify: `frontend/src/pages/Comic.tsx` (full implementation)
- Modify: `frontend/e2e/comic.spec.ts` (add data display tests)

- [ ] **Step 1: Replace stub with full `Comic.tsx`**

```tsx
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { apiFetch, extractDetail } from '../api/client'
import { formatRelative } from '../utils/format'

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

interface ComicDetail {
  id: number
  title: string
  status: string
  next_poll_at: string | null
  last_upgrade_check_at: string | null
  chapters: Chapter[]
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Comic() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const comicId = parseInt(id ?? '0', 10)

  const { data: comic, isLoading, error } = useQuery({
    queryKey: ['comic', comicId],
    queryFn: () => apiFetch<ComicDetail>(`/api/requests/${comicId}`),
    enabled: comicId > 0,
  })

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>{comic?.title ?? 'Comic'}</h1>
        <button onClick={() => navigate('/library')} style={linkButtonStyle}>← Library</button>
      </div>

      {isLoading && <p>Loading…</p>}

      {error && <p style={{ color: 'red' }}>{extractDetail(error)}</p>}

      {comic && (
        <>
          {/* Header: cover + metadata */}
          <div style={{ display: 'flex', gap: 24, marginBottom: 32 }}>
            <img
              src={`/api/requests/${comic.id}/cover`}
              alt=""
              width={48}
              height={64}
              style={{ objectFit: 'cover', borderRadius: 4, flexShrink: 0 }}
              onError={e => { e.currentTarget.style.display = 'none' }}
            />
            <div>
              <p style={metaRowStyle}><span style={metaLabelStyle}>Status</span>{comic.status}</p>
              <p style={metaRowStyle}><span style={metaLabelStyle}>Next poll</span>{formatRelative(comic.next_poll_at)}</p>
              <p style={metaRowStyle}><span style={metaLabelStyle}>Last upgrade check</span>{formatRelative(comic.last_upgrade_check_at)}</p>
            </div>
          </div>

          {/* Chapter table */}
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ textAlign: 'left', borderBottom: '2px solid #ddd' }}>
                <th style={thStyle}>Chapter</th>
                <th style={thStyle}>Volume</th>
                <th style={thStyle}>Source</th>
                <th style={thStyle}>Status</th>
                <th style={thStyle}>Relocation</th>
                <th style={thStyle}>Library path</th>
              </tr>
            </thead>
            <tbody>
              {comic.chapters.map(ch => (
                <tr key={ch.assignment_id} style={{ borderBottom: '1px solid #eee' }}>
                  <td style={tdStyle}>{ch.chapter_number}</td>
                  <td style={tdStyle}>{ch.volume_number ?? '—'}</td>
                  <td style={tdStyle}>{ch.source_name}</td>
                  <td style={tdStyle}>{ch.download_status}</td>
                  <td style={tdStyle}>{ch.relocation_status}</td>
                  <td style={{ ...tdStyle, maxWidth: 280, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
                    {ch.library_path ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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

const metaRowStyle: React.CSSProperties = {
  margin: '0 0 6px 0',
  fontSize: 14,
}

const metaLabelStyle: React.CSSProperties = {
  fontWeight: 600,
  marginRight: 8,
  color: '#444',
}

const thStyle: React.CSSProperties = {
  padding: '8px 12px',
  fontSize: 13,
  fontWeight: 600,
  color: '#444',
}

const tdStyle: React.CSSProperties = {
  padding: '10px 12px',
  verticalAlign: 'middle',
  fontSize: 13,
}
```

- [ ] **Step 2: Append data display tests to `frontend/e2e/comic.spec.ts`**

Add these tests after the navigation tests already in the file (keep the existing `MOCK_COMIC` and `authenticate` helpers defined in Task 2 — do not redefine them):

```ts
test('authenticated: page renders comic title as heading', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_COMIC) }),
  )
  await page.goto('/comics/1')
  await expect(page.getByRole('heading', { name: 'One Piece' })).toBeVisible({ timeout: 5000 })
})

test('authenticated: metadata fields are visible', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_COMIC) }),
  )
  await page.goto('/comics/1')
  await expect(page.getByText('tracking')).toBeVisible({ timeout: 5000 })
  // next_poll_at is ~2 days away → "in 2 days"
  await expect(page.getByText(/in \d+ days/)).toBeVisible()
})

test('authenticated: chapter table rows are visible', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_COMIC) }),
  )
  await page.goto('/comics/1')
  // Chapter 1 row
  await expect(page.getByRole('cell', { name: '1' }).first()).toBeVisible({ timeout: 5000 })
  await expect(page.getByRole('cell', { name: 'MangaDex' }).first()).toBeVisible()
  await expect(page.getByRole('cell', { name: 'done' }).first()).toBeVisible()
  // Chapter 2: volume null → '—'
  await expect(page.getByRole('cell', { name: '—' }).first()).toBeVisible()
})

test('authenticated: API error shows error message', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Comic not found' }),
    }),
  )
  await page.goto('/comics/1')
  await expect(page.getByText('Comic not found')).toBeVisible({ timeout: 5000 })
})
```

- [ ] **Step 3: Run all comic tests**

```bash
cd frontend && npx playwright test e2e/comic.spec.ts --project=chromium 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 4: Run the full test suite to confirm no regressions**

```bash
cd frontend && npx playwright test --project=chromium 2>&1 | tail -30
```

Expected: all tests pass (setup.spec.ts may have 4 pre-existing failures on develop — those are not regressions from this branch).
