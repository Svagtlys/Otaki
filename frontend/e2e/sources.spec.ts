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
