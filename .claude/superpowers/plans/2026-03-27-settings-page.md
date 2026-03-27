# Settings Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Settings page at `/settings` with four independently-saveable sections: Suwayomi connection, paths, chapter naming format (with live preview), and polling interval.

**Architecture:** Single `GET /api/settings` fetch via TanStack Query. Each section has its own local state initialised from query data via `useEffect`, its own save handler calling `PATCH /api/settings` with only that section's fields, and its own saving/error state. A Settings nav button is added to the Library page. Role-based nav hiding is deferred (roles not yet implemented in `AuthContext`).

**Tech Stack:** React 18, TypeScript, TanStack Query v5, React Router v6, inline styles only, Playwright for e2e tests.

---

### Task 1: Scaffold `Settings.tsx`, wire `App.tsx` and `Library.tsx`, write navigation tests

**Files:**
- Create: `frontend/src/pages/Settings.tsx` (stub)
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/Library.tsx`
- Create: `frontend/e2e/settings.spec.ts` (navigation tests only)

- [ ] **Step 1: Create a stub `frontend/src/pages/Settings.tsx`**

```tsx
export default function Settings() {
  return <p>Settings</p>
}
```

- [ ] **Step 2: Wire `Settings` into `App.tsx`**

Add the import at the top with the other page imports:

```ts
import Settings from './pages/Settings'
```

Replace:
```tsx
<Route path="/settings" element={<Placeholder name="Settings" />} />
```
With:
```tsx
<Route path="/settings" element={<Settings />} />
```

- [ ] **Step 3: Add a Settings nav button to `Library.tsx`**

The Library header already has a `<div style={{ display: 'flex', gap: 16 }}>` containing Search and Sources buttons. Add a Settings button to that group:

```tsx
<div style={{ display: 'flex', gap: 16 }}>
  <button onClick={() => navigate('/search')} style={linkButtonStyle}>Search</button>
  <button onClick={() => navigate('/sources')} style={linkButtonStyle}>Sources</button>
  <button onClick={() => navigate('/settings')} style={linkButtonStyle}>Settings</button>
</div>
```

- [ ] **Step 4: Verify the app compiles**

```bash
cd frontend && npm run build
```

Expected: exits 0.

- [ ] **Step 5: Write navigation tests in `frontend/e2e/settings.spec.ts`**

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

const MOCK_SETTINGS = {
  suwayomi_url: 'http://suwayomi.example.com',
  suwayomi_username: 'admin',
  suwayomi_password: '**masked**',
  suwayomi_download_path: '/data/downloads',
  library_path: '/data/library',
  default_poll_days: 7,
  chapter_naming_format: '{title}/{title} - Ch.{chapter}.cbz',
  relocation_strategy: 'auto',
}

test('unauthenticated: navigating to /settings redirects to /login', async ({ page }) => {
  await page.goto('/settings')
  await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
})

test('authenticated: Library page has a Settings button', async ({ page }) => {
  await authenticate(page)
  await page.goto('/library')
  await expect(page.getByRole('button', { name: 'Settings' })).toBeVisible({ timeout: 5000 })
})

test('authenticated: Settings button on Library navigates to /settings', async ({ page }) => {
  await authenticate(page)
  await page.goto('/library')
  await page.getByRole('button', { name: 'Settings' }).click()
  await expect(page).toHaveURL(/\/settings/, { timeout: 5000 })
})

test('authenticated: ← Library button on Settings navigates back to /library', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.goto('/settings')
  await page.getByRole('button', { name: '← Library' }).click()
  await expect(page).toHaveURL(/\/library/, { timeout: 5000 })
})
```

- [ ] **Step 6: Run only the navigation tests**

```bash
cd frontend && npx playwright test e2e/settings.spec.ts --project=chromium 2>&1 | tail -20
```

Expected: the first three tests pass. The `← Library` button test will fail until Task 2 adds the button — that is expected at this stage.

---

### Task 2: Full `Settings.tsx` implementation with data display and interaction tests

**Files:**
- Modify: `frontend/src/pages/Settings.tsx` (full implementation)
- Modify: `frontend/e2e/settings.spec.ts` (add data display and interaction tests)

- [ ] **Step 1: Replace stub with full `Settings.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, extractDetail } from '../api/client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Settings {
  suwayomi_url: string | null
  suwayomi_username: string | null
  suwayomi_password: string | null
  suwayomi_download_path: string | null
  library_path: string | null
  default_poll_days: number
  chapter_naming_format: string
  relocation_strategy: 'auto' | 'hardlink' | 'copy' | 'move'
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Settings() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: settings, isLoading, error } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiFetch<Settings>('/api/settings'),
  })

  // Suwayomi connection
  const [connUrl, setConnUrl] = useState('')
  const [connUsername, setConnUsername] = useState('')
  const [connPassword, setConnPassword] = useState('')
  const [connSaving, setConnSaving] = useState(false)
  const [connError, setConnError] = useState<string | null>(null)
  const [connSuccess, setConnSuccess] = useState(false)

  // Paths
  const [downloadPath, setDownloadPath] = useState('')
  const [libraryPath, setLibraryPath] = useState('')
  const [pathsSaving, setPathsSaving] = useState(false)
  const [pathsError, setPathsError] = useState<string | null>(null)

  // Naming format
  const [namingFormat, setNamingFormat] = useState('')
  const [namingSaving, setNamingSaving] = useState(false)
  const [namingError, setNamingError] = useState<string | null>(null)

  // Polling
  const [pollDays, setPollDays] = useState(7)
  const [pollSaving, setPollSaving] = useState(false)
  const [pollError, setPollError] = useState<string | null>(null)

  useEffect(() => {
    if (!settings) return
    setConnUrl(settings.suwayomi_url ?? '')
    setConnUsername(settings.suwayomi_username ?? '')
    setDownloadPath(settings.suwayomi_download_path ?? '')
    setLibraryPath(settings.library_path ?? '')
    setNamingFormat(settings.chapter_naming_format)
    setPollDays(settings.default_poll_days)
  }, [settings])

  async function saveConnection(e: React.FormEvent) {
    e.preventDefault()
    setConnSaving(true)
    setConnError(null)
    setConnSuccess(false)
    try {
      const body: Record<string, string | null> = {
        suwayomi_url: connUrl,
        suwayomi_username: connUsername || null,
      }
      if (connPassword) body.suwayomi_password = connPassword
      await apiFetch('/api/settings', { method: 'PATCH', body: JSON.stringify(body) })
      setConnPassword('')
      setConnSuccess(true)
      await queryClient.invalidateQueries({ queryKey: ['settings'] })
    } catch (err) {
      setConnError(extractDetail(err))
    } finally {
      setConnSaving(false)
    }
  }

  async function savePaths(e: React.FormEvent) {
    e.preventDefault()
    setPathsSaving(true)
    setPathsError(null)
    try {
      await apiFetch('/api/settings', {
        method: 'PATCH',
        body: JSON.stringify({ suwayomi_download_path: downloadPath, library_path: libraryPath }),
      })
      await queryClient.invalidateQueries({ queryKey: ['settings'] })
    } catch (err) {
      setPathsError(extractDetail(err))
    } finally {
      setPathsSaving(false)
    }
  }

  async function saveNaming(e: React.FormEvent) {
    e.preventDefault()
    setNamingSaving(true)
    setNamingError(null)
    try {
      await apiFetch('/api/settings', {
        method: 'PATCH',
        body: JSON.stringify({ chapter_naming_format: namingFormat }),
      })
      await queryClient.invalidateQueries({ queryKey: ['settings'] })
    } catch (err) {
      setNamingError(extractDetail(err))
    } finally {
      setNamingSaving(false)
    }
  }

  async function savePoll(e: React.FormEvent) {
    e.preventDefault()
    setPollSaving(true)
    setPollError(null)
    try {
      await apiFetch('/api/settings', {
        method: 'PATCH',
        body: JSON.stringify({ default_poll_days: pollDays }),
      })
      await queryClient.invalidateQueries({ queryKey: ['settings'] })
    } catch (err) {
      setPollError(extractDetail(err))
    } finally {
      setPollSaving(false)
    }
  }

  const namingPreview = namingFormat
    .replace(/\{title\}/g, 'One Piece')
    .replace(/\{chapter\}/g, '0001')

  return (
    <div style={{ maxWidth: 640, margin: '0 auto', padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 32 }}>
        <h1 style={{ margin: 0 }}>Settings</h1>
        <button onClick={() => navigate('/library')} style={linkButtonStyle}>← Library</button>
      </div>

      {isLoading && <p>Loading…</p>}
      {error && <p style={{ color: 'red' }}>{extractDetail(error)}</p>}

      {settings && (
        <>
          {/* Suwayomi connection */}
          <section style={sectionStyle}>
            <h2 style={sectionHeadingStyle}>Suwayomi connection</h2>
            <form onSubmit={saveConnection}>
              <div style={fieldStyle}>
                <label style={labelStyle} htmlFor="conn-url">URL</label>
                <input
                  id="conn-url"
                  type="url"
                  value={connUrl}
                  onChange={e => setConnUrl(e.target.value)}
                  required
                  style={inputStyle}
                />
              </div>
              <div style={fieldStyle}>
                <label style={labelStyle} htmlFor="conn-username">Username</label>
                <input
                  id="conn-username"
                  type="text"
                  value={connUsername}
                  onChange={e => setConnUsername(e.target.value)}
                  style={inputStyle}
                />
              </div>
              <div style={fieldStyle}>
                <label style={labelStyle} htmlFor="conn-password">Password</label>
                <input
                  id="conn-password"
                  type="password"
                  value={connPassword}
                  onChange={e => setConnPassword(e.target.value)}
                  placeholder={settings.suwayomi_password ? '(leave blank to keep current)' : ''}
                  style={inputStyle}
                />
              </div>
              {connError && <p style={errorStyle}>{connError}</p>}
              {connSuccess && <p style={{ color: 'green', fontSize: 13, margin: '4px 0' }}>Connected successfully.</p>}
              <button type="submit" disabled={connSaving}>
                {connSaving ? 'Saving…' : 'Save & Test'}
              </button>
            </form>
          </section>

          {/* Paths */}
          <section style={sectionStyle}>
            <h2 style={sectionHeadingStyle}>Paths</h2>
            <form onSubmit={savePaths}>
              <div style={fieldStyle}>
                <label style={labelStyle} htmlFor="download-path">Download path</label>
                <input
                  id="download-path"
                  type="text"
                  value={downloadPath}
                  onChange={e => setDownloadPath(e.target.value)}
                  style={inputStyle}
                />
              </div>
              <div style={fieldStyle}>
                <label style={labelStyle} htmlFor="library-path">Library path</label>
                <input
                  id="library-path"
                  type="text"
                  value={libraryPath}
                  onChange={e => setLibraryPath(e.target.value)}
                  style={inputStyle}
                />
              </div>
              {pathsError && <p style={errorStyle}>{pathsError}</p>}
              <button type="submit" disabled={pathsSaving}>
                {pathsSaving ? 'Saving…' : 'Save'}
              </button>
            </form>
          </section>

          {/* Chapter naming */}
          <section style={sectionStyle}>
            <h2 style={sectionHeadingStyle}>Chapter naming</h2>
            <form onSubmit={saveNaming}>
              <div style={fieldStyle}>
                <label style={labelStyle} htmlFor="naming-format">Format</label>
                <input
                  id="naming-format"
                  type="text"
                  value={namingFormat}
                  onChange={e => setNamingFormat(e.target.value)}
                  style={inputStyle}
                />
                <p style={{ fontSize: 12, color: '#888', margin: '4px 0 0' }}>
                  Tokens: <code>{'{title}'}</code>, <code>{'{chapter}'}</code>
                </p>
              </div>
              <div style={fieldStyle}>
                <label style={labelStyle}>Preview</label>
                <code style={{ fontSize: 12, color: '#444' }}>{namingPreview}</code>
              </div>
              {namingError && <p style={errorStyle}>{namingError}</p>}
              <button type="submit" disabled={namingSaving}>
                {namingSaving ? 'Saving…' : 'Save'}
              </button>
            </form>
          </section>

          {/* Polling */}
          <section style={{ marginBottom: 0 }}>
            <h2 style={sectionHeadingStyle}>Polling</h2>
            <form onSubmit={savePoll}>
              <div style={fieldStyle}>
                <label style={labelStyle} htmlFor="poll-days">Default poll interval (days)</label>
                <input
                  id="poll-days"
                  type="number"
                  min={1}
                  value={pollDays}
                  onChange={e => setPollDays(parseInt(e.target.value, 10))}
                  style={{ ...inputStyle, width: 80 }}
                />
              </div>
              {pollError && <p style={errorStyle}>{pollError}</p>}
              <button type="submit" disabled={pollSaving}>
                {pollSaving ? 'Saving…' : 'Save'}
              </button>
            </form>
          </section>
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

const sectionStyle: React.CSSProperties = {
  marginBottom: 32,
  paddingBottom: 32,
  borderBottom: '1px solid #eee',
}

const sectionHeadingStyle: React.CSSProperties = {
  fontSize: 16,
  fontWeight: 600,
  margin: '0 0 16px',
}

const fieldStyle: React.CSSProperties = {
  marginBottom: 12,
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 13,
  fontWeight: 500,
  marginBottom: 4,
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '6px 8px',
  fontSize: 13,
  boxSizing: 'border-box',
}

const errorStyle: React.CSSProperties = {
  color: 'red',
  fontSize: 13,
  margin: '4px 0',
}
```

- [ ] **Step 2: Append data display and interaction tests to `frontend/e2e/settings.spec.ts`**

Add these tests after the navigation tests already in the file (keep the existing `MOCK_SETTINGS` and `authenticate` helpers — do not redefine them):

```ts
test('authenticated: settings values render in form fields', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.goto('/settings')
  await expect(page.getByLabel('URL')).toHaveValue('http://suwayomi.example.com', { timeout: 5000 })
  await expect(page.getByLabel('Username')).toHaveValue('admin')
  await expect(page.getByLabel('Download path')).toHaveValue('/data/downloads')
  await expect(page.getByLabel('Library path')).toHaveValue('/data/library')
  await expect(page.getByLabel('Format')).toHaveValue('{title}/{title} - Ch.{chapter}.cbz')
  await expect(page.getByLabel('Default poll interval (days)')).toHaveValue('7')
})

test('authenticated: naming format preview updates as user types', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.goto('/settings')
  await expect(page.getByLabel('Format')).toHaveValue('{title}/{title} - Ch.{chapter}.cbz', { timeout: 5000 })
  // initial preview
  await expect(page.getByText('One Piece/One Piece - Ch.0001.cbz')).toBeVisible()
  // change format, preview updates
  await page.getByLabel('Format').fill('{title} - Ch.{chapter}')
  await expect(page.getByText('One Piece - Ch.0001')).toBeVisible()
})

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
  await expect(page.getByLabel('URL')).toHaveValue('http://suwayomi.example.com', { timeout: 5000 })
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
  await expect(page.getByLabel('URL')).toHaveValue('http://suwayomi.example.com', { timeout: 5000 })
  await page.getByRole('button', { name: 'Save & Test' }).click()
  await expect(page.getByText('Connected successfully.')).toBeVisible({ timeout: 5000 })
})

test('authenticated: connection save error shows error message', async ({ page }) => {
  await authenticate(page)
  let callCount = 0
  await page.route('**/api/settings', route => {
    callCount++
    if (route.request().method() === 'GET' || callCount === 1) {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) })
    } else {
      route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'Could not connect to Suwayomi' }) })
    }
  })
  await page.goto('/settings')
  await expect(page.getByLabel('URL')).toHaveValue('http://suwayomi.example.com', { timeout: 5000 })
  await page.getByRole('button', { name: 'Save & Test' }).click()
  await expect(page.getByText('Could not connect to Suwayomi')).toBeVisible({ timeout: 5000 })
})

test('authenticated: Paths Save fires PATCH with path fields', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.goto('/settings')
  await expect(page.getByLabel('Download path')).toHaveValue('/data/downloads', { timeout: 5000 })
  const patchPromise = page.waitForRequest(req => req.method() === 'PATCH' && req.url().includes('/api/settings'))
  await page.getByLabel('Library path').fill('/data/library2')
  await page.getByRole('button', { name: 'Save' }).first().click()
  const req = await patchPromise
  const body = req.postDataJSON() as Record<string, unknown>
  expect(body).toHaveProperty('suwayomi_download_path', '/data/downloads')
  expect(body).toHaveProperty('library_path', '/data/library2')
})

test('authenticated: Poll days Save fires PATCH with default_poll_days', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.goto('/settings')
  await expect(page.getByLabel('Default poll interval (days)')).toHaveValue('7', { timeout: 5000 })
  const patchPromise = page.waitForRequest(req => req.method() === 'PATCH' && req.url().includes('/api/settings'))
  await page.getByLabel('Default poll interval (days)').fill('14')
  await page.getByRole('button', { name: 'Save' }).last().click()
  const req = await patchPromise
  const body = req.postDataJSON() as Record<string, unknown>
  expect(body).toHaveProperty('default_poll_days', 14)
})
```

- [ ] **Step 3: Run all settings tests**

```bash
cd frontend && npx playwright test e2e/settings.spec.ts --project=chromium 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 4: Run the full test suite to confirm no regressions**

```bash
cd frontend && npx playwright test --project=chromium 2>&1 | tail -30
```

Expected: all tests pass (any pre-existing setup.spec.ts failures are not regressions from this branch).
