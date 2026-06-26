import { test, expect } from '@playwright/test'
import { resetBackend, BACKEND_URL } from './reset-backend.js'

const ADMIN_USERNAME = 'admin'
const ADMIN_PASSWORD = 'adminpass'

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

test('unauthenticated: redirects to /login', async ({ page }) => {
  await page.goto('/library')
  await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
})

test('authenticated: Library page renders', async ({ page }) => {
  const token = await getToken()
  await page.goto('/login')
  await page.evaluate((t) => localStorage.setItem('otaki_token', t), token)

  await page.goto('/library')
  await expect(page.getByRole('heading', { name: 'Library' })).toBeVisible({ timeout: 5000 })
})

test('authenticated: comic card renders and navigates on click', async ({ page }) => {
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

test('catch-all: navigating to / redirects to /library', async ({ page }) => {
  const token = await getToken()
  await page.goto('/login')
  await page.evaluate((t) => localStorage.setItem('otaki_token', t), token)

  await page.goto('/')
  await expect(page).toHaveURL(/\/library/, { timeout: 5000 })
})

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

test('authenticated: pagination controls render and page 2 request fires', async ({ page }) => {
  const token = await getToken()
  await page.goto('/login')
  await page.evaluate((t) => localStorage.setItem('otaki_token', t), token)

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
