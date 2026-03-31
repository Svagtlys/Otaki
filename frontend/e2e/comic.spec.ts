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

test('authenticated: change cover via URL closes form on success', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_COMIC) }),
  )
  await page.route('**/api/requests/1/cover', async route => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ cover_url: '/api/requests/1/cover' }),
      })
    } else {
      await route.continue()
    }
  })

  await page.goto('/comics/1')
  await page.getByRole('button', { name: 'Change cover' }).click()
  await page.getByRole('button', { name: 'URL' }).click()
  await page.getByPlaceholder('https://...').fill('https://example.com/cover.jpg')
  await page.getByRole('button', { name: 'Save' }).click()

  // Form closes on success — Cancel button gone, Change cover button visible again
  await expect(page.getByPlaceholder('https://...')).not.toBeVisible({ timeout: 5000 })
  await expect(page.getByRole('button', { name: 'Change cover' })).toBeVisible()
})
