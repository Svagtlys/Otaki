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

function fulfillSSE(route: import('@playwright/test').Route, payloads: unknown[]): Promise<void> {
  const body = payloads
    .map(p => `data: ${typeof p === 'string' ? p : JSON.stringify(p)}`)
    .join('\n') + '\n'
  return route.fulfill({ status: 200, contentType: 'text/event-stream', body })
}

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

const MOCK_OVERRIDES = [
  { source_id: 1, source_name: 'MangaDex', global_priority: 1, effective_priority: 2, is_overridden: true },
  { source_id: 2, source_name: 'MangaPlus', global_priority: 2, effective_priority: 1, is_overridden: true },
]

const MOCK_PINS = [
  { id: 10, source_id: 1, source_name: 'MangaDex', suwayomi_manga_id: 'md-1001', pinned_at: '2025-03-15T09:00:00Z' },
]

test('unauthenticated: navigating to /comics/1 redirects to /login', async ({ page }) => {
  await page.goto('/comics/1')
  await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
})

test('authenticated: Library row click navigates to /comics/{id}', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests*', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          {
            id: 1,
            title: 'One Piece',
            status: 'tracking',
            chapter_counts: { total: 2, done: 1, downloading: 0, queued: 1, failed: 0 },
            next_poll_at: MOCK_COMIC.next_poll_at,
          },
        ],
        total: 1,
        page: 1,
        per_page: 25,
      }),
    }),
  )
  await page.goto('/library')
  await expect(page.getByRole('button', { name: /View One Piece/i })).toBeVisible({ timeout: 5000 })
  await page.getByRole('button', { name: /View One Piece/i }).click()
  await expect(page).toHaveURL(/\/comics\/1/, { timeout: 5000 })
})


test('authenticated: page renders comic title as heading', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_COMIC) }),
  )
  await page.route('**/api/requests/1/chapters*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_CHAPTERS) }),
  )
  await page.goto('/comics/1')
  await expect(page.getByRole('heading', { name: 'One Piece' })).toBeVisible({ timeout: 5000 })
})

test('authenticated: metadata fields are visible', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_COMIC) }),
  )
  await page.route('**/api/requests/1/chapters*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_CHAPTERS) }),
  )
  await page.goto('/comics/1')
  await expect(page.getByText('tracking')).toBeVisible({ timeout: 5000 })
  // next_poll_at is ~2 days away → "in 2 days"
  await expect(page.getByText(/in \d+ days/)).toBeVisible()
})

test('authenticated: info cards are visible', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_COMIC) }),
  )
  await page.route('**/api/requests/1/chapters*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_CHAPTERS) }),
  )
  await page.route('**/api/requests/1/pins', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  await page.goto('/comics/1')
  await expect(page.getByText('Poll interval')).toBeVisible({ timeout: 5000 })
  await expect(page.getByText('Upgrade interval')).toBeVisible()
  await expect(page.getByText('Last upgrade check')).toBeVisible()
  await expect(page.getByText('Aliases')).toBeVisible()
  await expect(page.getByText('Source pins')).toBeVisible()
})

test('authenticated: chapter filter chips show counts', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_COMIC) }),
  )
  await page.route('**/api/requests/1/chapters*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_CHAPTERS) }),
  )
  await page.route('**/api/requests/1/pins', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  await page.goto('/comics/1')
  // Each chip shows a parenthetical count
  await expect(page.getByRole('button', { name: /^All \(\d+\)$/ })).toBeVisible({ timeout: 5000 })
  await expect(page.getByRole('button', { name: /^Queued \(\d+\)$/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Downloading \(\d+\)$/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Available \(\d+\)$/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Failed \(\d+\)$/ })).toBeVisible()
})

test('authenticated: chapter table rows are visible', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_COMIC) }),
  )
  await page.route('**/api/requests/1/chapters*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_CHAPTERS) }),
  )
  await page.goto('/comics/1')
  // Chapter 1 row — chapter cell now renders "Ch. 1", download now shows "Done"
  await expect(page.getByRole('cell', { name: /Ch\. 1/ }).first()).toBeVisible({ timeout: 5000 })
  await expect(page.getByRole('cell', { name: /MangaDex/i }).first()).toBeVisible()
  await expect(page.getByRole('cell', { name: /Done/i }).first()).toBeVisible()
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
  await page.route('**/api/requests/1/chapters*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_CHAPTERS) }),
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
  // Log entry format from Comic.tsx: "Ch {chapter_number}: {old_source} → {new_source}"
  await expect(page.getByText(/Ch 1: MangaPlus → MangaDex/)).toBeVisible({ timeout: 5000 })
  await expect(page.getByText('1 upgrade(s) queued.')).toBeVisible({ timeout: 5000 })
})

test('authenticated: per-chapter Upgrade button queues upgrade for that chapter', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/requests/1', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_COMIC) }),
  )
  await page.route('**/api/requests/1/chapters**', async route => {
    if (route.request().url().includes('/chapters/55/')) {
      await fulfillSSE(route, [{ type: 'done', queued: 1 }, '[DONE]'])
    } else {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_CHAPTERS) })
    }
  })
  await page.goto('/comics/1')
  await expect(page.getByRole('cell', { name: '1' }).first()).toBeVisible({ timeout: 5000 })
  // Chapter 1 is the first data row (assignment_id 55) — click its Upgrade button
  await page.locator('tbody tr').first().getByRole('button', { name: 'Upgrade' }).click()
  await expect(page.getByText('Upgrade queued')).toBeVisible({ timeout: 5000 })
})

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
  // Scope to the overrides panel to avoid matching chapter table cells
  const overridesPanel = page.locator('main').locator('.card').filter({ hasText: 'Drag to reorder' })
  await expect(overridesPanel.getByText('MangaDex')).toBeVisible({ timeout: 5000 })
  await expect(overridesPanel.getByText('MangaPlus')).toBeVisible()

  const putPromise = page.waitForRequest(req => req.method() === 'PUT' && req.url().includes('/source-overrides'))
  await expect(page.getByRole('button', { name: 'Save order' })).toBeEnabled({ timeout: 5000 })
  await page.getByRole('button', { name: 'Save order' }).click()
  const req = await putPromise
  const body = req.postDataJSON() as { source_ids: number[] }
  expect(body.source_ids).toEqual([1, 2])
})

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
  // Scope to the pins panel to avoid matching chapter table cells
  const pinsPanel = page.locator('main').locator('.card').filter({ hasText: 'Pins tell Otaki' })
  // The pin chip shows source_name in a <span> — use first() to avoid the <option> in the search <select>
  await expect(pinsPanel.locator('span').filter({ hasText: 'MangaDex' }).first()).toBeVisible({ timeout: 5000 })
  await expect(pinsPanel.getByText('md-1001')).toBeVisible()

  await page.getByRole('button', { name: 'Remove pin' }).click()
  const putPromise = page.waitForRequest(req => req.method() === 'PUT' && req.url().includes('/pins'))
  await page.getByRole('button', { name: 'Save pins' }).click()
  const req = await putPromise
  const body = req.postDataJSON() as { pins: unknown[] }
  expect(body.pins).toHaveLength(0)
})
