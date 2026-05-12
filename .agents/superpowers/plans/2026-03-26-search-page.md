# Search Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the search page at `/search` — a two-step UI for finding manga across sources, selecting result cards, and submitting a download request.

**Architecture:** A single `Search.tsx` page component using local React state and TanStack Query. Step 1 is a debounced search input with result card selection; Step 2 replaces the results area with a request form. Navigation links are inline in each page, consistent with the existing `Library.tsx` style.

**Tech Stack:** React 18, TypeScript 5.5, TanStack Query v5, React Router v6, Playwright for e2e tests.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `frontend/src/pages/Search.tsx` | Create | Entire search page (both steps, all state, all styles) |
| `frontend/src/App.tsx` | Modify | Replace `<Placeholder name="Search" />` with `<Search />` |
| `frontend/src/pages/Library.tsx` | Modify | Add "Search" link next to `<h1>` |
| `frontend/e2e/search.spec.ts` | Create | Playwright e2e tests for all search page behaviour |

---

### Task 1: Scaffold Search.tsx, wire into App.tsx, add navigation links

**Files:**
- Create: `frontend/src/pages/Search.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/Library.tsx`
- Test: `frontend/e2e/search.spec.ts`

- [ ] **Step 1: Write the failing navigation tests**

Create `frontend/e2e/search.spec.ts`:

```typescript
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

test('Library page has a Search button', async ({ page }) => {
  await authenticate(page)
  await page.goto('/library')
  await expect(page.getByRole('button', { name: 'Search' })).toBeVisible({ timeout: 5000 })
})

test('Search button on Library navigates to /search', async ({ page }) => {
  await authenticate(page)
  await page.goto('/library')
  await page.getByRole('button', { name: 'Search' }).click()
  await expect(page).toHaveURL(/\/search/, { timeout: 5000 })
})

test('Search page renders heading', async ({ page }) => {
  await authenticate(page)
  await page.goto('/search')
  await expect(page.getByRole('heading', { name: 'Search' })).toBeVisible({ timeout: 5000 })
})

test('Search page has a ← Library button', async ({ page }) => {
  await authenticate(page)
  await page.goto('/search')
  await expect(page.getByRole('button', { name: '← Library' })).toBeVisible({ timeout: 5000 })
})

test('← Library button navigates to /library', async ({ page }) => {
  await authenticate(page)
  await page.goto('/search')
  await page.getByRole('button', { name: '← Library' }).click()
  await expect(page).toHaveURL(/\/library/, { timeout: 5000 })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && npm run test:e2e -- --grep "Library page has a Search|Search button|Search page renders|← Library"
```

Expected: FAIL — Search page is still a `<Placeholder>`.

- [ ] **Step 3: Scaffold Search.tsx**

Create `frontend/src/pages/Search.tsx`:

```tsx
import { useNavigate } from 'react-router-dom'

export default function Search() {
  const navigate = useNavigate()

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>Search</h1>
        <button onClick={() => navigate('/library')} style={linkButtonStyle}>← Library</button>
      </div>
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

- [ ] **Step 4: Wire Search into App.tsx**

In `frontend/src/App.tsx`, add the import after the `Setup` import:

```tsx
import Search from './pages/Search'
```

Replace:

```tsx
<Route path="/search" element={<Placeholder name="Search" />} />
```

with:

```tsx
<Route path="/search" element={<Search />} />
```

- [ ] **Step 5: Add Search link to Library.tsx**

In `frontend/src/pages/Library.tsx`, add the `useNavigate` import is already there. Replace:

```tsx
  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24 }}>
      <h1 style={{ marginTop: 0 }}>Library</h1>
```

with:

```tsx
  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>Library</h1>
        <button onClick={() => navigate('/search')} style={linkButtonStyle}>Search</button>
      </div>
```

Then add `linkButtonStyle` at the bottom of `Library.tsx` (after the existing style constants):

```tsx
const linkButtonStyle: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#0070f3',
  cursor: 'pointer',
  fontSize: 14,
  padding: 0,
}
```

- [ ] **Step 6: Run the navigation tests to verify they pass**

```bash
cd frontend && npm run test:e2e -- --grep "Library page has a Search|Search button|Search page renders|← Library"
```

Expected: PASS — 5 tests green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Search.tsx frontend/src/App.tsx frontend/src/pages/Library.tsx frontend/e2e/search.spec.ts
git commit -m "feat(search): scaffold search page with navigation links"
```

---

### Task 2: Step 1 — debounced search, result cards, card selection

**Files:**
- Modify: `frontend/src/pages/Search.tsx`
- Modify: `frontend/e2e/search.spec.ts`

- [ ] **Step 1: Add Step 1 tests to search.spec.ts**

Append to `frontend/e2e/search.spec.ts`:

```typescript
const MOCK_RESULTS = [
  {
    title: 'One Piece',
    cover_url: null,
    synopsis: 'Pirates and adventure.',
    source_id: 1,
    source_name: 'MangaDex',
    url: 'https://mangadex.org/manga/one-piece',
  },
  {
    title: 'ワンピース',
    cover_url: null,
    synopsis: 'Pirates in Japanese.',
    source_id: 2,
    source_name: 'MangaPlus',
    url: 'https://mangaplus.com/manga/wan-piisu',
  },
]

test('typing in search input shows results', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/search*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_RESULTS) }),
  )
  await page.goto('/search')
  await page.getByRole('textbox', { name: 'Search' }).fill('one piece')
  await expect(page.getByText('One Piece')).toBeVisible({ timeout: 2000 })
  await expect(page.getByText('MangaDex')).toBeVisible()
  await expect(page.getByText('ワンピース')).toBeVisible()
  await expect(page.getByText('MangaPlus')).toBeVisible()
})

test('empty query shows no results area', async ({ page }) => {
  await authenticate(page)
  await page.goto('/search')
  await expect(page.getByText('Loading')).not.toBeVisible()
  await expect(page.getByText('No results')).not.toBeVisible()
})

test('search with no results shows No results message', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/search*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  )
  await page.goto('/search')
  await page.getByRole('textbox', { name: 'Search' }).fill('xyzzy')
  await expect(page.getByText('No results.')).toBeVisible({ timeout: 2000 })
})

test('search API error shows error message', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/search*', route =>
    route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'Search failed' }) }),
  )
  await page.goto('/search')
  await page.getByRole('textbox', { name: 'Search' }).fill('one piece')
  await expect(page.getByText('Search failed')).toBeVisible({ timeout: 2000 })
})

test('clicking a result card highlights it and shows Review button', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/search*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_RESULTS) }),
  )
  await page.goto('/search')
  await page.getByRole('textbox', { name: 'Search' }).fill('one piece')
  await expect(page.getByText('One Piece')).toBeVisible({ timeout: 2000 })
  await page.locator('[role="button"]').filter({ hasText: 'One Piece' }).click()
  await expect(page.getByRole('button', { name: 'Review request (1)' })).toBeVisible()
})

test('clicking two cards shows correct basket count', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/search*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_RESULTS) }),
  )
  await page.goto('/search')
  await page.getByRole('textbox', { name: 'Search' }).fill('one piece')
  await expect(page.getByText('One Piece')).toBeVisible({ timeout: 2000 })
  await page.locator('[role="button"]').filter({ hasText: 'One Piece' }).click()
  await page.locator('[role="button"]').filter({ hasText: 'ワンピース' }).click()
  await expect(page.getByRole('button', { name: 'Review request (2)' })).toBeVisible()
})

test('clicking a selected card deselects it', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/search*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_RESULTS) }),
  )
  await page.goto('/search')
  await page.getByRole('textbox', { name: 'Search' }).fill('one piece')
  await expect(page.getByText('One Piece')).toBeVisible({ timeout: 2000 })
  await page.locator('[role="button"]').filter({ hasText: 'One Piece' }).click()
  await expect(page.getByRole('button', { name: 'Review request (1)' })).toBeVisible()
  await page.locator('[role="button"]').filter({ hasText: 'One Piece' }).click()
  await expect(page.getByRole('button', { name: /Review request/ })).not.toBeVisible()
})
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
cd frontend && npm run test:e2e -- --grep "typing in search|empty query|no results|search API error|clicking a result|clicking two|clicking a selected"
```

Expected: FAIL — no search input, no result cards yet.

- [ ] **Step 3: Implement Step 1 in Search.tsx**

Replace the entire contents of `frontend/src/pages/Search.tsx` with:

```tsx
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ApiError, apiFetch } from '../api/client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SearchResult {
  title: string
  cover_url: string | null
  synopsis: string | null
  source_id: number
  source_name: string
  url: string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractDetail(err: unknown): string {
  if (err instanceof ApiError) {
    try {
      return (JSON.parse(err.message) as { detail: string }).detail
    } catch {
      return err.message
    }
  }
  return 'An unexpected error occurred'
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Search() {
  const navigate = useNavigate()

  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())

  // Debounce: wait 400ms after last keystroke; clear selection on new search
  useEffect(() => {
    const id = setTimeout(() => {
      setDebouncedQuery(query)
      setSelected(new Set())
    }, 400)
    return () => clearTimeout(id)
  }, [query])

  const { data: results, isLoading, error } = useQuery({
    queryKey: ['search', debouncedQuery],
    queryFn: () => apiFetch<SearchResult[]>(`/api/search?q=${encodeURIComponent(debouncedQuery)}`),
    enabled: debouncedQuery.length > 0,
  })

  function toggleSelect(url: string) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(url)) next.delete(url)
      else next.add(url)
      return next
    })
  }

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>Search</h1>
        <button onClick={() => navigate('/library')} style={linkButtonStyle}>← Library</button>
      </div>

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
      {debouncedQuery && !isLoading && !error && results?.length === 0 && (
        <p style={{ color: '#666' }}>No results.</p>
      )}

      {/* Result cards */}
      {results && results.length > 0 && (
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
              {r.cover_url ? (
                <img
                  src={r.cover_url}
                  alt=""
                  width={48}
                  height={64}
                  style={{ objectFit: 'cover', borderRadius: 4, flexShrink: 0 }}
                  onError={e => { e.currentTarget.style.display = 'none' }}
                />
              ) : (
                <div style={{ width: 48, height: 64, background: '#eee', borderRadius: 4, flexShrink: 0 }} />
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2 }}>{r.title}</div>
                <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>{r.source_name}</div>
                {r.synopsis && (
                  <div style={{
                    fontSize: 12,
                    color: '#444',
                    display: '-webkit-box',
                    WebkitLineClamp: 2,
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
          <button style={primaryButtonStyle}>
            Review request ({selected.size})
          </button>
        </div>
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
  gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
  gap: 12,
  marginTop: 16,
}

const cardStyle: React.CSSProperties = {
  display: 'flex',
  gap: 12,
  padding: 12,
  borderRadius: 6,
  cursor: 'pointer',
  background: '#fff',
}
```

- [ ] **Step 4: Run Step 1 tests to verify they pass**

```bash
cd frontend && npm run test:e2e -- --grep "typing in search|empty query|no results|search API error|clicking a result|clicking two|clicking a selected"
```

Expected: PASS — 7 tests green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Search.tsx frontend/e2e/search.spec.ts
git commit -m "feat(search): step 1 — debounced search, result cards, card selection"
```

---

### Task 3: Step 2 — request form, cover picker, submit

**Files:**
- Modify: `frontend/src/pages/Search.tsx`
- Modify: `frontend/e2e/search.spec.ts`

- [ ] **Step 1: Add Step 2 tests to search.spec.ts**

Append to `frontend/e2e/search.spec.ts`:

```typescript
async function goToStep2(page: import('@playwright/test').Page) {
  await authenticate(page)
  await page.route('**/api/search*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_RESULTS) }),
  )
  await page.goto('/search')
  await page.getByRole('textbox', { name: 'Search' }).fill('one piece')
  await expect(page.getByText('One Piece')).toBeVisible({ timeout: 2000 })
  await page.locator('[role="button"]').filter({ hasText: 'One Piece' }).click()
  await page.getByRole('button', { name: 'Review request (1)' }).click()
}

test('Review button advances to Step 2 and shows selected summary', async ({ page }) => {
  await goToStep2(page)
  await expect(page.getByText('One Piece — MangaDex')).toBeVisible({ timeout: 2000 })
  await expect(page.getByRole('button', { name: '← Back to results' })).toBeVisible()
})

test('Step 2: display name pre-filled from first selected card', async ({ page }) => {
  await goToStep2(page)
  await expect(page.getByLabel('Display name')).toHaveValue('One Piece')
})

test('Step 2: library title pre-filled from display name', async ({ page }) => {
  await goToStep2(page)
  await expect(page.getByLabel('Library title')).toHaveValue('One Piece')
})

test('Step 2: library title syncs when display name changes', async ({ page }) => {
  await goToStep2(page)
  await page.getByLabel('Display name').fill('One Piece (2024)')
  await expect(page.getByLabel('Library title')).toHaveValue('One Piece (2024)')
})

test('Step 2: library title does not sync after manual edit', async ({ page }) => {
  await goToStep2(page)
  await page.getByLabel('Library title').fill('One Piece Custom')
  await page.getByLabel('Display name').fill('Something Else')
  await expect(page.getByLabel('Library title')).toHaveValue('One Piece Custom')
})

test('Step 2: ← Back to results restores Step 1 with selections intact', async ({ page }) => {
  await goToStep2(page)
  await page.getByRole('button', { name: '← Back to results' }).click()
  await expect(page.getByRole('button', { name: 'Review request (1)' })).toBeVisible({ timeout: 2000 })
})

test('Step 2: successful submit navigates to /library', async ({ page }) => {
  await goToStep2(page)
  await page.route('**/api/requests', route =>
    route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({ id: 1, title: 'One Piece', library_title: 'One Piece' }),
    }),
  )
  await page.getByRole('button', { name: 'Submit request' }).click()
  await expect(page).toHaveURL(/\/library/, { timeout: 5000 })
})

test('Step 2: failed submit shows error message', async ({ page }) => {
  await goToStep2(page)
  await page.route('**/api/requests', route =>
    route.fulfill({
      status: 422,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Title already exists' }),
    }),
  )
  await page.getByRole('button', { name: 'Submit request' }).click()
  await expect(page.getByText('Title already exists')).toBeVisible({ timeout: 2000 })
})
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
cd frontend && npm run test:e2e -- --grep "Review button advances|display name pre-filled|library title pre-filled|library title syncs|library title does not|Back to results|successful submit|failed submit"
```

Expected: FAIL — Review button does nothing yet.

- [ ] **Step 3: Implement Step 2 in Search.tsx**

Replace the entire contents of `frontend/src/pages/Search.tsx` with the full two-step implementation:

```tsx
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ApiError, apiFetch } from '../api/client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SearchResult {
  title: string
  cover_url: string | null
  synopsis: string | null
  source_id: number
  source_name: string
  url: string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractDetail(err: unknown): string {
  if (err instanceof ApiError) {
    try {
      return (JSON.parse(err.message) as { detail: string }).detail
    } catch {
      return err.message
    }
  }
  return 'An unexpected error occurred'
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

  const { data: results, isLoading, error } = useQuery({
    queryKey: ['search', debouncedQuery],
    queryFn: () => apiFetch<SearchResult[]>(`/api/search?q=${encodeURIComponent(debouncedQuery)}`),
    enabled: debouncedQuery.length > 0,
  })

  function toggleSelect(url: string) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(url)) next.delete(url)
      else next.add(url)
      return next
    })
  }

  function handleReview() {
    const firstSelected = results?.find(r => selected.has(r.url))
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
        }),
      })
      navigate('/library')
    } catch (err) {
      setSubmitError(extractDetail(err))
    } finally {
      setSubmitting(false)
    }
  }

  const selectedResults = results?.filter(r => selected.has(r.url)) ?? []

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
          {debouncedQuery && !isLoading && !error && results?.length === 0 && (
            <p style={{ color: '#666' }}>No results.</p>
          )}

          {/* Result cards */}
          {results && results.length > 0 && (
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
                  {r.cover_url ? (
                    <img
                      src={r.cover_url}
                      alt=""
                      width={48}
                      height={64}
                      style={{ objectFit: 'cover', borderRadius: 4, flexShrink: 0 }}
                      onError={e => { e.currentTarget.style.display = 'none' }}
                    />
                  ) : (
                    <div style={{ width: 48, height: 64, background: '#eee', borderRadius: 4, flexShrink: 0 }} />
                  )}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2 }}>{r.title}</div>
                    <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>{r.source_name}</div>
                    {r.synopsis && (
                      <div style={{
                        fontSize: 12,
                        color: '#444',
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
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

          {/* Cover picker */}
          {selectedResults.some(r => r.cover_url) && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: '#444' }}>Cover</div>
              <div style={{ display: 'flex', gap: 8 }}>
                {selectedResults
                  .filter(r => r.cover_url)
                  .map(r => (
                    <img
                      key={r.url}
                      src={r.cover_url!}
                      alt={r.source_name}
                      width={48}
                      height={64}
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
  gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
  gap: 12,
  marginTop: 16,
}

const cardStyle: React.CSSProperties = {
  display: 'flex',
  gap: 12,
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
```

- [ ] **Step 4: Run Step 2 tests to verify they pass**

```bash
cd frontend && npm run test:e2e -- --grep "Review button advances|display name pre-filled|library title pre-filled|library title syncs|library title does not|Back to results|successful submit|failed submit"
```

Expected: PASS — 8 tests green.

- [ ] **Step 5: Run full test suite to verify nothing regressed**

```bash
cd frontend && npm run test:e2e
```

Expected: all tests pass (navigation + step 1 + step 2 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Search.tsx frontend/e2e/search.spec.ts
git commit -m "feat(search): step 2 — request form, cover picker, submit"
```
