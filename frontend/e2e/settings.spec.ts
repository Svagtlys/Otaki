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
  suwayomi_password: '',
  suwayomi_download_path: '/data/downloads',
  library_path: '/data/library',
  default_poll_days: 7,
  chapter_naming_format: '{title}/{title} - Ch.{chapter}',
  relocation_strategy: 'auto',
}

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
  await expect(page.getByLabel('Format')).toHaveValue('{title}/{title} - Ch.{chapter}')
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

test('authenticated: naming format preview updates as user types', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Paths' }).click()
  await expect(page.getByLabel('Format')).toHaveValue('{title}/{title} - Ch.{chapter}', { timeout: 5000 })
  // initial preview (Settings appends .cbz to the preview value)
  await expect(page.getByText('One Piece/One Piece - Ch.0001.cbz')).toBeVisible()
  await page.getByLabel('Format').fill('{title} - Ch.{chapter}')
  await expect(page.getByText('One Piece - Ch.0001.cbz')).toBeVisible()
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

test('authenticated: Chapter naming Save fires PATCH with chapter_naming_format', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/settings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SETTINGS) }),
  )
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Paths' }).click()
  await expect(page.getByLabel('Format')).toHaveValue('{title}/{title} - Ch.{chapter}', { timeout: 5000 })
  const patchPromise = page.waitForRequest(req => req.method() === 'PATCH' && req.url().includes('/api/settings'))
  await page.getByLabel('Format').fill('{title} - Vol.{chapter}')
  await page.locator('form', { has: page.getByLabel('Format') }).getByRole('button', { name: 'Save' }).click()
  const req = await patchPromise
  const body = req.postDataJSON() as Record<string, unknown>
  expect(body).toHaveProperty('chapter_naming_format', '{title} - Vol.{chapter}')
})

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
  // Preview panel renders — New tab is auto-selected when there are no conflicts
  // Wait for the Import button to confirm the panel is visible, then check for the comic
  await expect(page.getByRole('button', { name: 'Import', exact: true })).toBeVisible({ timeout: 5000 })
  await expect(page.getByText('One Piece')).toBeVisible({ timeout: 5000 })
})

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
  await expect(page.getByRole('button', { name: 'Import', exact: true })).toBeVisible({ timeout: 5000 })
  await page.getByRole('button', { name: 'Import', exact: true }).click()
  await expect(page.getByText(/Import complete/)).toBeVisible({ timeout: 5000 })
})
