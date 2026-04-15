# Playwright Test Updates — 1.2 UI Improvements

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update all six e2e spec files to pass against the 1.2 UI and add coverage for every feature shipped since #102.

**Architecture:** Test-only changes — no production code. Each task rewrites or extends one spec file. Tests use `page.route()` to mock API responses; streaming endpoints get SSE-formatted bodies. The suite runs against a real backend reset per spec via `resetBackend()`.

**Tech Stack:** Playwright (`@playwright/test`), React frontend at `http://localhost:5173`, FastAPI backend at `http://localhost:8000`.

---

## File map

| File | Change type |
|---|---|
| `frontend/e2e/login.spec.ts` | Selector fixes |
| `frontend/e2e/library.spec.ts` | Selector fixes + new tests |
| `frontend/e2e/sources.spec.ts` | Remove one test |
| `frontend/e2e/settings.spec.ts` | Tab-navigation fixes + backup tests |
| `frontend/e2e/search.spec.ts` | SSE mock rewrite + chip tests |
| `frontend/e2e/comic.spec.ts` | Mock shape fix + new panel tests |

---

## Task 1: Fix `login.spec.ts`

**Files:**
- Modify: `frontend/e2e/login.spec.ts`

Three things broke: the heading is gone, the button says "Sign in" not "Log in", and the error `<p>` no longer uses `color: red`.

- [ ] **Step 1: Replace heading assertions and fix button names**

In both tests that call `page.getByRole('heading', { name: 'Log in to Otaki' })`, remove that assertion and instead wait for `page.getByRole('button', { name: 'Sign in' })` to confirm the page loaded. Change every `'Log in'` button reference to `'Sign in'`.

After edits the two tests look like:

```ts
test('wrong credentials: shows inline error, stays on /login', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()

  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill('wrongpassword')
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page.locator('.card form p')).toBeVisible({ timeout: 5000 })
  await expect(page).toHaveURL(/\/login/)
})

test('correct credentials: redirects away from /login', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()

  await page.getByLabel('Username').fill(ADMIN_USERNAME)
  await page.getByLabel('Password').fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page).not.toHaveURL(/\/login/, { timeout: 5000 })
})
```

The third test (`already authenticated`) has no heading or button interaction — no change needed.

- [ ] **Step 2: Run the login tests**

```bash
cd "/home/momothebestest/Coding Workspace/Otaki/frontend"
npx playwright test e2e/login.spec.ts --project=chromium
```

Expected: all 3 tests pass.

- [ ] **Step 3: Commit**

```bash
cd "/home/momothebestest/Coding Workspace/Otaki"
git add frontend/e2e/login.spec.ts
git commit -m "test(login): fix selectors for 1.2 login reskin"
```

---

## Task 2: Fix and extend `library.spec.ts`

**Files:**
- Modify: `frontend/e2e/library.spec.ts`

Four things to fix/add: mock shape, grid-view click, sidebar navigation test, search/filter/pagination tests.

- [ ] **Step 1: Fix the mock shape and the row-click selector**

The library endpoint now returns `{ items, total, page, per_page }`. All route mocks for `**/api/requests*` must return that shape. The existing "Library row click" test uses `getByRole('row')` but Library now defaults to grid view — change it to the cover-card button.

Update the mock used by the comic-row-click test and add a `MOCK_LIBRARY` constant at the top of the file:

```ts
const MOCK_LIBRARY = {
  items: [
    {
      id: 1,
      title: 'One Piece',
      status: 'tracking',
      chapter_counts: { total: 2, done: 1, downloading: 0, queued: 1, failed: 0 },
      next_poll_at: new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString(),
    },
  ],
  total: 1,
  page: 1,
  per_page: 25,
}
```

Update the row-click test:

```ts
test('authenticated: Library row click navigates to /comics/{id}', async ({ page }) => {
  const token = await getToken()
  await page.goto('/login')
  await page.evaluate((t) => localStorage.setItem('otaki_token', t), token)

  await page.route('**/api/requests*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_LIBRARY) }),
  )
  await page.goto('/library')
  await expect(page.getByRole('button', { name: /View One Piece/i })).toBeVisible({ timeout: 5000 })
  await page.getByRole('button', { name: /View One Piece/i }).click()
  await expect(page).toHaveURL(/\/comics\/1/, { timeout: 5000 })
})
```

- [ ] **Step 2: Add sidebar navigation test**

```ts
test('authenticated: sidebar navigates to Search and Sources', async ({ page }) => {
  const token = await getToken()
  await page.goto('/login')
  await page.evaluate((t) => localStorage.setItem('otaki_token', t), token)

  await page.goto('/library')
  await page.getByRole('button', { name: 'Search' }).click()
  await expect(page).toHaveURL(/\/search/, { timeout: 5000 })

  await page.getByRole('button', { name: 'Sources' }).click()
  await expect(page).toHaveURL(/\/sources/, { timeout: 5000 })

  await page.getByRole('button', { name: 'Library' }).first().click()
  await expect(page).toHaveURL(/\/library/, { timeout: 5000 })
})
```

Note: `.first()` because the Library sidebar button comes before any in-page "Library" back links in DOM order.

- [ ] **Step 3: Add search-input filter test**

```ts
test('authenticated: search input adds search param to request', async ({ page }) => {
  const token = await getToken()
  await page.goto('/login')
  await page.evaluate((t) => localStorage.setItem('otaki_token', t), token)

  await page.route('**/api/requests*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...MOCK_LIBRARY, items: [] }) }),
  )
  await page.goto('/library')

  const reqPromise = page.waitForRequest(
    req => req.url().includes('/api/requests') && req.url().includes('search='),
  )
  await page.getByLabel('Search comics').fill('one piece')
  const req = await reqPromise
  expect(new URL(req.url()).searchParams.get('search')).toBe('one piece')
})
```

- [ ] **Step 4: Add status-chip filter test**

```ts
test('authenticated: Tracking chip adds status param to request', async ({ page }) => {
  const token = await getToken()
  await page.goto('/login')
  await page.evaluate((t) => localStorage.setItem('otaki_token', t), token)

  await page.route('**/api/requests*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_LIBRARY) }),
  )
  await page.goto('/library')
  await expect(page.getByRole('button', { name: 'All' })).toBeVisible({ timeout: 5000 })

  const reqPromise = page.waitForRequest(
    req => req.url().includes('/api/requests') && req.url().includes('status=tracking'),
  )
  await page.getByRole('button', { name: 'Tracking' }).click()
  await reqPromise
})
```

- [ ] **Step 5: Add pagination test**

```ts
test('authenticated: pagination controls render and page 2 request fires', async ({ page }) => {
  const token = await getToken()
  await page.goto('/login')
  await page.evaluate((t) => localStorage.setItem('otaki_token', t), token)

  // Return 30 total items with per_page 25 — triggers pagination controls
  await page.route('**/api/requests*', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...MOCK_LIBRARY, total: 30, per_page: 25 }),
    }),
  )
  await page.goto('/library')
  await expect(page.getByRole('button', { name: /Next/i })).toBeVisible({ timeout: 5000 })

  const reqPromise = page.waitForRequest(
    req => req.url().includes('/api/requests') && req.url().includes('page=2'),
  )
  await page.getByRole('button', { name: /Next/i }).click()
  await reqPromise
})
```

- [ ] **Step 6: Run the library tests**

```bash
cd "/home/momothebestest/Coding Workspace/Otaki/frontend"
npx playwright test e2e/library.spec.ts --project=chromium
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
cd "/home/momothebestest/Coding Workspace/Otaki"
git add frontend/e2e/library.spec.ts
git commit -m "test(library): fix grid-view selector, add sidebar nav, search/filter/pagination tests"
```

---

## Task 3: Fix `sources.spec.ts`

**Files:**
- Modify: `frontend/e2e/sources.spec.ts`

One test uses a "← Library" back button that no longer exists on the Sources page (navigation is via sidebar). Delete it — the sidebar navigation test in `library.spec.ts` covers this concern.

- [ ] **Step 1: Delete the back-button test**

Remove this test entirely:

```ts
test('authenticated: ← Library button on Sources navigates back to /library', ...)
```

- [ ] **Step 2: Run sources tests**

```bash
cd "/home/momothebestest/Coding Workspace/Otaki/frontend"
npx playwright test e2e/sources.spec.ts --project=chromium
```

Expected: all remaining tests pass.

- [ ] **Step 3: Commit**

```bash
cd "/home/momothebestest/Coding Workspace/Otaki"
git add frontend/e2e/sources.spec.ts
git commit -m "test(sources): remove back-button test — sidebar navigation now tested in library"
```

---

## Task 4: Fix and extend `settings.spec.ts`

**Files:**
- Modify: `frontend/e2e/settings.spec.ts`

Settings is now tabbed (Polling / Paths / Relocation / Suwayomi / Backup). Fields only render when their tab is active. The page has no "← Library" back button.

- [ ] **Step 1: Remove the back-button test**

Delete:

```ts
test('authenticated: ← Library button on Settings navigates back to /library', ...)
```

- [ ] **Step 2: Rewrite the "settings values render" test into per-tab tests**

Delete the existing `authenticated: settings values render in form fields` test. Replace with three separate tests that each navigate to the relevant tab first:

```ts
test('authenticated: Suwayomi tab renders connection fields', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Suwayomi' }).click()
  await expect(page.getByLabel('Server URL')).toHaveValue('http://suwayomi.example.com', { timeout: 5000 })
  await expect(page.getByLabel('Username')).toHaveValue('admin')
})

test('authenticated: Paths tab renders path and naming fields', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Paths' }).click()
  await expect(page.getByLabel('Download path')).toHaveValue('/data/downloads', { timeout: 5000 })
  await expect(page.getByLabel('Library path')).toHaveValue('/data/library')
  await expect(page.getByLabel('Format')).toHaveValue('{title}/{title} - Ch.{chapter}.cbz')
})

test('authenticated: Polling tab renders poll interval field', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.goto('/settings')
  // Polling is the default tab — no click needed
  await expect(page.getByLabel('Default poll interval (days)')).toHaveValue('7', { timeout: 5000 })
})
```

- [ ] **Step 3: Fix the Save & Test tests (Suwayomi tab)**

All three Suwayomi-related tests (`Save & Test fires PATCH`, `Save & Test shows success`, `connection save error`) need a tab click and `'URL'` → `'Server URL'`. Update them:

```ts
test('authenticated: Save & Test fires PATCH with connection fields', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) })
    } else {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) })
    }
  })
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Suwayomi' }).click()
  await expect(page.getByLabel('Server URL')).toHaveValue('http://suwayomi.example.com', { timeout: 5000 })
  const patchPromise = page.waitForRequest(req => req.method() === 'PATCH' && req.url().includes('/api/settings'))
  await page.getByRole('button', { name: 'Save & Test' }).click()
  const req = await patchPromise
  const body = req.postDataJSON() as Record<string, unknown>
  expect(body).toHaveProperty('suwayomi_url', 'http://suwayomi.example.com')
  expect(body).toHaveProperty('suwayomi_username', 'admin')
})

test('authenticated: Save & Test shows success message on save', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Suwayomi' }).click()
  await expect(page.getByLabel('Server URL')).toHaveValue('http://suwayomi.example.com', { timeout: 5000 })
  await page.getByRole('button', { name: 'Save & Test' }).click()
  await expect(page.getByText('Connected successfully.')).toBeVisible({ timeout: 5000 })
})

test('authenticated: connection save error shows error message', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) })
    } else {
      route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'Could not connect to Suwayomi' }) })
    }
  })
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Suwayomi' }).click()
  await expect(page.getByLabel('Server URL')).toHaveValue('http://suwayomi.example.com', { timeout: 5000 })
  await page.getByRole('button', { name: 'Save & Test' }).click()
  await expect(page.getByText('Could not connect to Suwayomi')).toBeVisible({ timeout: 5000 })
})
```

- [ ] **Step 4: Fix the Paths Save test**

The Paths tab has two forms (Paths and Chapter naming). The Paths form Save is the first button. Navigate to the tab and use `getByRole('button', { name: 'Save' }).first()`:

```ts
test('authenticated: Paths Save fires PATCH with path fields', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Paths' }).click()
  await expect(page.getByLabel('Download path')).toHaveValue('/data/downloads', { timeout: 5000 })
  const patchPromise = page.waitForRequest(req => req.method() === 'PATCH' && req.url().includes('/api/settings'))
  await page.getByLabel('Library path').fill('/data/library2')
  await page.getByRole('button', { name: 'Save' }).first().click()
  const req = await patchPromise
  const body = req.postDataJSON() as Record<string, unknown>
  expect(body).toHaveProperty('suwayomi_download_path', '/data/downloads')
  expect(body).toHaveProperty('library_path', '/data/library2')
})
```

- [ ] **Step 5: Fix the Poll days Save test**

Polling is the default tab. Remove the section locator; just use `getByRole('button', { name: 'Save' })`:

```ts
test('authenticated: Poll days Save fires PATCH with default_poll_days', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.goto('/settings')
  await expect(page.getByLabel('Default poll interval (days)')).toHaveValue('7', { timeout: 5000 })
  const patchPromise = page.waitForRequest(req => req.method() === 'PATCH' && req.url().includes('/api/settings'))
  await page.getByLabel('Default poll interval (days)').fill('14')
  await page.getByRole('button', { name: 'Save' }).click()
  const req = await patchPromise
  const body = req.postDataJSON() as Record<string, unknown>
  expect(body).toHaveProperty('default_poll_days', 14)
})
```

- [ ] **Step 6: Fix the Chapter naming Save test**

Scope Save to the form that contains the Format label:

```ts
test('authenticated: Chapter naming Save fires PATCH with chapter_naming_format', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Paths' }).click()
  await expect(page.getByLabel('Format')).toHaveValue('{title}/{title} - Ch.{chapter}.cbz', { timeout: 5000 })
  const patchPromise = page.waitForRequest(req => req.method() === 'PATCH' && req.url().includes('/api/settings'))
  await page.getByLabel('Format').fill('{title} - Vol.{chapter}')
  await page.locator('form', { has: page.getByLabel('Format') }).getByRole('button', { name: 'Save' }).click()
  const req = await patchPromise
  const body = req.postDataJSON() as Record<string, unknown>
  expect(body).toHaveProperty('chapter_naming_format', '{title} - Vol.{chapter}')
})
```

- [ ] **Step 7: Fix the naming-format preview test**

Navigate to Paths tab first:

```ts
test('authenticated: naming format preview updates as user types', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Paths' }).click()
  await expect(page.getByLabel('Format')).toHaveValue('{title}/{title} - Ch.{chapter}.cbz', { timeout: 5000 })
  // initial preview (Settings appends .cbz to the preview value)
  await expect(page.getByText('One Piece/One Piece - Ch.0001.cbz')).toBeVisible()
  await page.getByLabel('Format').fill('{title} - Ch.{chapter}')
  await expect(page.getByText('One Piece - Ch.0001.cbz')).toBeVisible()
})
```

- [ ] **Step 8: Add Backup tab export test**

```ts
test('authenticated: Export fires GET with chosen format', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  // Mock the export endpoint so no actual download is triggered
  await page.route('**/api/settings/export*', route =>
    route.fulfill({ status: 200, contentType: 'application/zip', body: '' }),
  )
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Backup' }).click()

  const reqPromise = page.waitForRequest(req => req.url().includes('/api/settings/export'))
  // Select JSON format radio
  await page.getByLabel(/JSON \(no assets\)/).check()
  await page.getByRole('button', { name: 'Download backup' }).click()
  const req = await reqPromise
  expect(new URL(req.url()).searchParams.get('format')).toBe('json')
})
```

- [ ] **Step 9: Add Backup tab import preview test**

```ts
const MOCK_PREVIEW = {
  source_conflicts: [],
  comic_conflicts: [],
  new_sources: [],
  new_comics: [
    {
      backup_id: 1,
      title: 'One Piece',
      import_chapters: 5,
      import_aliases: 0,
      import_pins: 0,
      import_has_cover: false,
    },
  ],
  totals: { sources: 0, comics: 1, chapters: 5, covers: 0 },
}

test('authenticated: Import preview renders new comics', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.route('**/api/settings/import/preview', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_PREVIEW) }),
  )
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Backup' }).click()
  await page.getByLabel('Or load from server path').fill('/data/backup.zip')
  await page.getByRole('button', { name: 'Preview import' }).click()
  // Preview panel renders — switch to New tab to see the new comic
  await page.getByRole('button', { name: /New/i }).click()
  await expect(page.getByText('One Piece')).toBeVisible({ timeout: 5000 })
})
```

- [ ] **Step 10: Add Backup tab import apply test**

```ts
test('authenticated: Import apply shows success message', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.route('**/api/settings/import/preview', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_PREVIEW) }),
  )
  await page.route('**/api/settings/import/apply', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ comics: 1, chapters: 5, covers: 0, skipped: 0 }),
    }),
  )
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Backup' }).click()
  await page.getByLabel('Or load from server path').fill('/data/backup.zip')
  await page.getByRole('button', { name: 'Preview import' }).click()
  await expect(page.getByRole('button', { name: 'Import' })).toBeVisible({ timeout: 5000 })
  await page.getByRole('button', { name: 'Import' }).click()
  await expect(page.getByText(/Import complete/)).toBeVisible({ timeout: 5000 })
})
```

- [ ] **Step 11: Run the settings tests**

```bash
cd "/home/momothebestest/Coding Workspace/Otaki/frontend"
npx playwright test e2e/settings.spec.ts --project=chromium
```

Expected: all tests pass.

- [ ] **Step 12: Commit**

```bash
cd "/home/momothebestest/Coding Workspace/Otaki"
git add frontend/e2e/settings.spec.ts
git commit -m "test(settings): fix tab navigation, add backup export/import/apply tests"
```

---

## Task 5: Rewrite and extend `search.spec.ts`

**Files:**
- Modify: `frontend/e2e/search.spec.ts`

The search endpoint changed to SSE streaming (`/api/search/stream?q=`). All route mocks must be rewritten. The `SearchResult` type gained `cover_display_url` and `suwayomi_manga_id`. Search cards are now native `<button>` elements. Two "← Library" tests are deleted.

- [ ] **Step 1: Add the `fulfillSSE` helper and update `MOCK_RESULTS`**

At the top of the file, after the imports, add:

```ts
function fulfillSSE(route: import('@playwright/test').Route, payloads: unknown[]) {
  const body = payloads
    .map(p => `data: ${typeof p === 'string' ? p : JSON.stringify(p)}`)
    .join('\n') + '\n'
  route.fulfill({ status: 200, contentType: 'text/event-stream', body })
}
```

Update `MOCK_RESULTS`:

```ts
const MOCK_RESULTS = [
  {
    title: 'One Piece',
    cover_url: null,
    cover_display_url: null,
    synopsis: 'Pirates and adventure.',
    source_id: 1,
    source_name: 'MangaDex',
    url: 'https://mangadex.org/manga/one-piece',
    suwayomi_manga_id: '1001',
  },
  {
    title: 'ワンピース',
    cover_url: null,
    cover_display_url: null,
    synopsis: 'Pirates in Japanese.',
    source_id: 2,
    source_name: 'MangaPlus',
    url: 'https://mangaplus.com/manga/wan-piisu',
    suwayomi_manga_id: '2001',
  },
]
```

- [ ] **Step 2: Delete the two "← Library" tests**

Remove:
- `test('Search page has a ← Library button', ...)`
- `test('← Library button navigates to /library', ...)`

- [ ] **Step 3: Rewrite all route mocks to SSE format**

For every test that mocks `**/api/search*`, change the route pattern to `**/api/search/stream*` and replace `route.fulfill({ body: JSON.stringify(MOCK_RESULTS) })` with `fulfillSSE(...)`.

The tests that show results use:
```ts
await page.route('**/api/search/stream*', route =>
  fulfillSSE(route, [
    { results: [MOCK_RESULTS[0]], source_name: 'MangaDex' },
    { results: [MOCK_RESULTS[1]], source_name: 'MangaPlus' },
    '[DONE]',
  ]),
)
```

The empty-results test uses:
```ts
await page.route('**/api/search/stream*', route =>
  fulfillSSE(route, ['[DONE]']),
)
```

The error test uses:
```ts
await page.route('**/api/search/stream*', route =>
  fulfillSSE(route, [
    { error: 'Search failed', source_name: 'MangaDex' },
    '[DONE]',
  ]),
)
```

- [ ] **Step 4: Fix the search-card selector in all tests that click cards**

Replace every `page.locator('[role="button"]').filter({ hasText: '...' })` with `page.getByRole('button').filter({ hasText: '...' })`.

The `goToStep2` helper and the basket-count tests all need this change. For example:

```ts
await page.getByRole('button').filter({ hasText: 'One Piece' }).click()
```

Note: this matches any button containing "One Piece" text. The only such button in the result grid is the `One Piece` search card. The "Review request (1)" button does not contain "One Piece".

- [ ] **Step 5: Fix the "Back to results" button selector**

The button renders as `<i className="bx bx-chevron-left" /> Back to results`. The icon contributes no text content, so accessible name is `" Back to results"`. Two tests reference this button — update both:

`test('Review button advances to Step 2 and shows selected summary')`:
```ts
await expect(page.getByRole('button', { name: /back to results/i })).toBeVisible()
```

`test('Step 2: ← Back to results restores Step 1 with selections intact')`:
```ts
await page.getByRole('button', { name: /back to results/i }).click()
await expect(page.getByRole('button', { name: 'Review request (1)' })).toBeVisible({ timeout: 2000 })
```

- [ ] **Step 6: Add source chip tests**

Append at the end of the file:

```ts
test('source chips render after search returns results', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/sources', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { id: 1, name: 'MangaDex', enabled: true },
        { id: 2, name: 'MangaPlus', enabled: true },
      ]),
    }),
  )
  await page.route('**/api/search/stream*', route =>
    fulfillSSE(route, [
      { results: [MOCK_RESULTS[0]], source_name: 'MangaDex' },
      { results: [MOCK_RESULTS[1]], source_name: 'MangaPlus' },
      '[DONE]',
    ]),
  )
  await page.goto('/search')
  await page.getByRole('textbox', { name: 'Search' }).fill('one piece')
  await expect(page.getByRole('button', { name: 'MangaDex' })).toBeVisible({ timeout: 5000 })
  await expect(page.getByRole('button', { name: 'MangaPlus' })).toBeVisible()
})

test('clicking a source chip hides its results', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/sources', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { id: 1, name: 'MangaDex', enabled: true },
        { id: 2, name: 'MangaPlus', enabled: true },
      ]),
    }),
  )
  await page.route('**/api/search/stream*', route =>
    fulfillSSE(route, [
      { results: [MOCK_RESULTS[0]], source_name: 'MangaDex' },
      { results: [MOCK_RESULTS[1]], source_name: 'MangaPlus' },
      '[DONE]',
    ]),
  )
  await page.goto('/search')
  await page.getByRole('textbox', { name: 'Search' }).fill('one piece')
  await expect(page.getByRole('button').filter({ hasText: 'One Piece' })).toBeVisible({ timeout: 5000 })

  await page.getByRole('button', { name: 'MangaDex' }).click()
  await expect(page.getByRole('button').filter({ hasText: 'One Piece' })).not.toBeVisible()
  await expect(page.getByRole('button').filter({ hasText: 'ワンピース' })).toBeVisible()
})

test('clicking a hidden chip restores its results', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/sources', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { id: 1, name: 'MangaDex', enabled: true },
        { id: 2, name: 'MangaPlus', enabled: true },
      ]),
    }),
  )
  await page.route('**/api/search/stream*', route =>
    fulfillSSE(route, [
      { results: [MOCK_RESULTS[0]], source_name: 'MangaDex' },
      { results: [MOCK_RESULTS[1]], source_name: 'MangaPlus' },
      '[DONE]',
    ]),
  )
  await page.goto('/search')
  await page.getByRole('textbox', { name: 'Search' }).fill('one piece')
  await expect(page.getByRole('button').filter({ hasText: 'One Piece' })).toBeVisible({ timeout: 5000 })
  await page.getByRole('button', { name: 'MangaDex' }).click()
  await expect(page.getByRole('button').filter({ hasText: 'One Piece' })).not.toBeVisible()
  await page.getByRole('button', { name: 'MangaDex' }).click()
  await expect(page.getByRole('button').filter({ hasText: 'One Piece' })).toBeVisible()
})
```

- [ ] **Step 7: Run the search tests**

```bash
cd "/home/momothebestest/Coding Workspace/Otaki/frontend"
npx playwright test e2e/search.spec.ts --project=chromium
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
cd "/home/momothebestest/Coding Workspace/Otaki"
git add frontend/e2e/search.spec.ts
git commit -m "test(search): rewrite mocks for SSE stream, add source chip tests"
```

---

## Task 6: Fix and extend `comic.spec.ts`

**Files:**
- Modify: `frontend/e2e/comic.spec.ts`

The Comic page now fetches chapters separately (paginated). `MOCK_COMIC` lost its `chapters` field. The page has a "Library" back button (icon + text, not "← Library"). New tests for force upgrade, source overrides, and pin management.

- [ ] **Step 1: Add the `fulfillSSE` helper and `MOCK_CHAPTERS` constant; update `MOCK_COMIC`**

Add at the top of the file, after imports:

```ts
function fulfillSSE(route: import('@playwright/test').Route, payloads: unknown[]) {
  const body = payloads
    .map(p => `data: ${typeof p === 'string' ? p : JSON.stringify(p)}`)
    .join('\n') + '\n'
  route.fulfill({ status: 200, contentType: 'text/event-stream', body })
}
```

Update `MOCK_COMIC` — remove the `chapters` array, add `aliases` and `inferred_cadence_days`:

```ts
const MOCK_COMIC = {
  id: 1,
  title: 'One Piece',
  library_title: 'One Piece',
  status: 'tracking',
  poll_override_days: 7.0,
  upgrade_override_days: null,
  inferred_cadence_days: null,
  next_poll_at: new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString(),
  next_upgrade_check_at: new Date(Date.now() + 3 * 24 * 60 * 60 * 1000).toISOString(),
  last_upgrade_check_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
  created_at: '2025-03-15T09:00:00Z',
  aliases: [],
}
```

Add a `MOCK_CHAPTERS` constant:

```ts
const MOCK_CHAPTERS = {
  items: [
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
  total: 2,
  page: 1,
  per_page: 50,
}
```

- [ ] **Step 2: Add the chapters mock to every test that visits `/comics/1`**

Every `page.route('**/api/requests/1', ...)` block must be accompanied by a chapters mock. Add to each such test:

```ts
await page.route('**/api/requests/1/chapters*', route =>
  route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_CHAPTERS) }),
)
```

The tests that need this added: `← Library button`, `page renders comic title`, `metadata fields`, `chapter table rows`, `API error`, `change cover`.

- [ ] **Step 3: Fix the "← Library button" test selector**

The back button renders as `<button><i className="bx bx-chevron-left" /> Library</button>`. Accessible name is `"Library"` — the boxicon contributes no text. Scope to `<main>` so it doesn't match the sidebar "Library" nav button:

```ts
test('authenticated: ← Library button navigates back to /library', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_COMIC) }),
  )
  await page.route('**/api/requests/1/chapters*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_CHAPTERS) }),
  )
  await page.goto('/comics/1')
  await page.locator('main').getByRole('button', { name: /library/i }).click()
  await expect(page).toHaveURL(/\/library/, { timeout: 5000 })
})
```

- [ ] **Step 4: Add force upgrade (bulk) test**

```ts
test('authenticated: Force upgrade queues upgrades and shows summary', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_COMIC) }),
  )
  await page.route('**/api/requests/1/chapters*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_CHAPTERS) }),
  )
  await page.route('**/api/requests/1/force-upgrade', route =>
    fulfillSSE(route, [
      { type: 'chapter', chapter_number: 1, old_source: 'MangaPlus', new_source: 'MangaDex' },
      { type: 'done', queued: 1 },
      '[DONE]',
    ]),
  )
  await page.goto('/comics/1')
  await expect(page.getByRole('button', { name: 'Force upgrade' })).toBeVisible({ timeout: 5000 })
  await page.getByRole('button', { name: 'Force upgrade' }).click()
  // Log entry appears
  await expect(page.getByText(/Ch 1:.*MangaPlus.*MangaDex/)).toBeVisible({ timeout: 5000 })
  // Summary result
  await expect(page.getByText('1 upgrade(s) queued.')).toBeVisible({ timeout: 5000 })
})
```

- [ ] **Step 5: Add single-chapter upgrade test**

```ts
test('authenticated: per-chapter Upgrade button queues upgrade for that chapter', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_COMIC) }),
  )
  await page.route('**/api/requests/1/chapters*', route => {
    if (route.request().url().includes('/chapters/55/')) {
      // Single-chapter force-upgrade
      fulfillSSE(route, [{ type: 'done', queued: 1 }, '[DONE]'])
    } else {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_CHAPTERS) })
    }
  })
  await page.goto('/comics/1')
  // Chapter 1 row is visible; click its Upgrade button
  await expect(page.getByRole('cell', { name: '1' }).first()).toBeVisible({ timeout: 5000 })
  await page.getByRole('row').filter({ hasText: /^1\b/ }).getByRole('button', { name: 'Upgrade' }).click()
  await expect(page.getByText('Upgrade queued')).toBeVisible({ timeout: 5000 })
})
```

- [ ] **Step 6: Add source overrides panel test**

```ts
const MOCK_OVERRIDES = [
  { source_id: 1, source_name: 'MangaDex', global_priority: 1, effective_priority: 2, is_overridden: true },
  { source_id: 2, source_name: 'MangaPlus', global_priority: 2, effective_priority: 1, is_overridden: true },
]

test('authenticated: source overrides panel shows entries and saves order', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_COMIC) }),
  )
  await page.route('**/api/requests/1/chapters*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_CHAPTERS) }),
  )
  await page.route('**/api/requests/1/source-overrides', route => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_OVERRIDES) })
    } else {
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    }
  })
  await page.route('**/api/sources', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([
      { id: 1, name: 'MangaDex', enabled: true },
      { id: 2, name: 'MangaPlus', enabled: true },
    ]) }),
  )
  await page.goto('/comics/1')
  await page.getByRole('button', { name: 'Manage source priorities' }).click()
  await expect(page.getByText('MangaDex')).toBeVisible({ timeout: 5000 })
  await expect(page.getByText('MangaPlus')).toBeVisible()

  const putPromise = page.waitForRequest(req => req.method() === 'PUT' && req.url().includes('/source-overrides'))
  await page.getByRole('button', { name: 'Save order' }).click()
  const req = await putPromise
  const body = req.postDataJSON() as { source_ids: number[] }
  expect(body.source_ids).toEqual([1, 2])
})
```

- [ ] **Step 7: Add pin management panel test**

```ts
const MOCK_PINS = [
  { id: 10, source_id: 1, source_name: 'MangaDex', suwayomi_manga_id: 'md-1001', pinned_at: '2025-03-15T09:00:00Z' },
]

test('authenticated: pin management panel shows pins and saves after remove', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_COMIC) }),
  )
  await page.route('**/api/requests/1/chapters*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_CHAPTERS) }),
  )
  await page.route('**/api/requests/1/pins', route => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_PINS) })
    } else {
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    }
  })
  await page.route('**/api/sources', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([
      { id: 1, name: 'MangaDex', enabled: true },
    ]) }),
  )
  await page.goto('/comics/1')
  await page.getByRole('button', { name: 'Manage source pins' }).click()
  await expect(page.getByText('MangaDex')).toBeVisible({ timeout: 5000 })
  await expect(page.getByText('md-1001')).toBeVisible()

  // Remove the pin, then save
  await page.getByRole('button', { name: 'Remove pin' }).click()
  const putPromise = page.waitForRequest(req => req.method() === 'PUT' && req.url().includes('/pins'))
  await page.getByRole('button', { name: 'Save pins' }).click()
  const req = await putPromise
  const body = req.postDataJSON() as { pins: unknown[] }
  expect(body.pins).toHaveLength(0)
})
```

- [ ] **Step 8: Run the comic tests**

```bash
cd "/home/momothebestest/Coding Workspace/Otaki/frontend"
npx playwright test e2e/comic.spec.ts --project=chromium
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
cd "/home/momothebestest/Coding Workspace/Otaki"
git add frontend/e2e/comic.spec.ts
git commit -m "test(comic): fix chapter mock, add force-upgrade, overrides, and pins tests"
```

---

## Task 7: Fix `setup.spec.ts`

**Files:**
- Modify: `frontend/e2e/setup.spec.ts`

The "Step X of 4" progress text is gone — the new Setup.tsx shows step dots labelled `Account / Suwayomi / Sources / Paths`. The `getByText('Step X of 4')` assertions in `step 2 bad URL` will time out. Remove them; the heading assertions already confirm which step is active.

- [ ] **Step 1: Remove `getByText('Step X of 4')` assertions**

In `test('step 2 bad URL: ...')`, remove every `await expect(page.getByText('Step 1 of 4')).toBeVisible()` and `await expect(page.getByText('Step 2 of 4')).toBeVisible()` line. The heading checks (`getByRole('heading', { name: 'Create admin account' })` and `getByRole('heading', { name: 'Connect to Suwayomi' })`) are sufficient.

Also remove in the Suwayomi-dependent tests: every `getByText('Step 2 of 4')`, `getByText('Step 3 of 4')`, `getByText('Step 4 of 4')` assertion.

After edits, `step 2 bad URL` looks like:

```ts
test('step 2 bad URL: unreachable host shows inline error', async ({ page }) => {
  await page.goto('/setup')
  await expect(page.getByRole('heading', { name: 'Create admin account' })).toBeVisible()
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill('adminpass')
  await page.getByRole('button', { name: 'Create account' }).click()

  await expect(page.getByRole('heading', { name: 'Connect to Suwayomi' })).toBeVisible({
    timeout: 10000,
  })
  await page.getByLabel('Suwayomi URL').fill('http://localhost:9999')
  await page.getByRole('button', { name: 'Connect' }).click()

  await expect(page.getByRole('heading', { name: 'Connect to Suwayomi' })).toBeVisible({ timeout: 15000 })
  await expect(page.getByText('Could not connect to Suwayomi')).toBeVisible()
})
```

- [ ] **Step 2: Run the setup tests**

```bash
cd "/home/momothebestest/Coding Workspace/Otaki/frontend"
npx playwright test e2e/setup.spec.ts --project=chromium
```

Expected: `step 2 bad URL` and `step 1 skip` pass; the three Suwayomi-dependent tests are skipped (no `SUWAYOMI_URL` in env).

- [ ] **Step 3: Commit**

```bash
cd "/home/momothebestest/Coding Workspace/Otaki"
git add frontend/e2e/setup.spec.ts
git commit -m "test(setup): remove step-number text assertions replaced by step dots in 1.2 reskin"
```

---

## Task 8: Full suite smoke run

- [ ] **Step 1: Run all spec files on Chromium**

```bash
cd "/home/momothebestest/Coding Workspace/Otaki/frontend"
npx playwright test --project=chromium
```

Expected: all tests pass.

- [ ] **Step 2: Run on Firefox**

```bash
npx playwright test --project=firefox
```

Expected: all tests pass.

- [ ] **Step 3: If any test fails, fix it before continuing**

Check the HTML report:

```bash
npx playwright show-report
```

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
cd "/home/momothebestest/Coding Workspace/Otaki"
git add frontend/e2e/
git commit -m "test(e2e): fix cross-browser issues from full suite run"
```
