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

function fulfillSSE(route: import('@playwright/test').Route, payloads: unknown[]) {
  const body = payloads
    .map(p => `data: ${typeof p === 'string' ? p : JSON.stringify(p)}`)
    .join('\n') + '\n'
  route.fulfill({ status: 200, contentType: 'text/event-stream', body })
}

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

test('typing in search input shows results', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/search/stream*', route =>
    fulfillSSE(route, [
      { results: [MOCK_RESULTS[0]], source_name: 'MangaDex' },
      { results: [MOCK_RESULTS[1]], source_name: 'MangaPlus' },
      '[DONE]',
    ]),
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
  await page.route('**/api/search/stream*', route =>
    fulfillSSE(route, ['[DONE]']),
  )
  await page.goto('/search')
  await page.getByRole('textbox', { name: 'Search' }).fill('xyzzy')
  await expect(page.getByText('No results.')).toBeVisible({ timeout: 2000 })
})

test('search API error marks source chip as errored', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/sources', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{ id: 1, name: 'MangaDex', enabled: true }]),
    }),
  )
  await page.route('**/api/search/stream*', route =>
    fulfillSSE(route, [
      { error: 'Search failed', source_name: 'MangaDex' },
      '[DONE]',
    ]),
  )
  await page.goto('/search')
  await page.getByRole('textbox', { name: 'Search' }).fill('one piece')
  // The chip gets title="Search failed" when the source errors
  await expect(page.locator('button.chip[title="Search failed"]')).toBeVisible({ timeout: 2000 })
})

test('clicking a result card highlights it and shows Review button', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/search/stream*', route =>
    fulfillSSE(route, [
      { results: [MOCK_RESULTS[0]], source_name: 'MangaDex' },
      { results: [MOCK_RESULTS[1]], source_name: 'MangaPlus' },
      '[DONE]',
    ]),
  )
  await page.goto('/search')
  await page.getByRole('textbox', { name: 'Search' }).fill('one piece')
  await expect(page.getByText('One Piece')).toBeVisible({ timeout: 2000 })
  await page.getByRole('button').filter({ hasText: 'One Piece' }).click()
  await expect(page.getByRole('button', { name: 'Review request (1)' })).toBeVisible()
})

test('clicking two cards shows correct basket count', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/search/stream*', route =>
    fulfillSSE(route, [
      { results: [MOCK_RESULTS[0]], source_name: 'MangaDex' },
      { results: [MOCK_RESULTS[1]], source_name: 'MangaPlus' },
      '[DONE]',
    ]),
  )
  await page.goto('/search')
  await page.getByRole('textbox', { name: 'Search' }).fill('one piece')
  await expect(page.getByText('One Piece')).toBeVisible({ timeout: 2000 })
  await page.getByRole('button').filter({ hasText: 'One Piece' }).click()
  await page.getByRole('button').filter({ hasText: 'ワンピース' }).click()
  await expect(page.getByRole('button', { name: 'Review request (2)' })).toBeVisible()
})

test('clicking a selected card deselects it', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/search/stream*', route =>
    fulfillSSE(route, [
      { results: [MOCK_RESULTS[0]], source_name: 'MangaDex' },
      { results: [MOCK_RESULTS[1]], source_name: 'MangaPlus' },
      '[DONE]',
    ]),
  )
  await page.goto('/search')
  await page.getByRole('textbox', { name: 'Search' }).fill('one piece')
  await expect(page.getByText('One Piece')).toBeVisible({ timeout: 2000 })
  await page.getByRole('button').filter({ hasText: 'One Piece' }).click()
  await expect(page.getByRole('button', { name: 'Review request (1)' })).toBeVisible()
  await page.getByRole('button').filter({ hasText: 'One Piece' }).click()
  await expect(page.getByRole('button', { name: /Review request/ })).not.toBeVisible()
})

async function goToStep2(page: import('@playwright/test').Page) {
  await authenticate(page)
  await page.route('**/api/search/stream*', route =>
    fulfillSSE(route, [
      { results: [MOCK_RESULTS[0]], source_name: 'MangaDex' },
      { results: [MOCK_RESULTS[1]], source_name: 'MangaPlus' },
      '[DONE]',
    ]),
  )
  await page.goto('/search')
  await page.getByRole('textbox', { name: 'Search' }).fill('one piece')
  await expect(page.getByText('One Piece')).toBeVisible({ timeout: 2000 })
  await page.getByRole('button').filter({ hasText: 'One Piece' }).click()
  await page.getByRole('button', { name: 'Review request (1)' }).click()
}

test('Review button advances to Step 2 and shows selected summary', async ({ page }) => {
  await goToStep2(page)
  await expect(page.getByText(/One Piece/)).toBeVisible({ timeout: 2000 })
  await expect(page.getByText(/MangaDex/)).toBeVisible()
  await expect(page.getByRole('button', { name: /back to results/i })).toBeVisible()
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
  await page.getByRole('button', { name: /back to results/i }).click()
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
  await expect(page.getByRole('button', { name: 'MangaDex' }).first()).toBeVisible({ timeout: 5000 })
  await expect(page.getByRole('button', { name: 'MangaPlus' }).first()).toBeVisible()
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

  await page.getByRole('button', { name: 'MangaDex' }).first().click()
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
  await page.getByRole('button', { name: 'MangaDex' }).first().click()
  await expect(page.getByRole('button').filter({ hasText: 'One Piece' })).not.toBeVisible()
  await page.getByRole('button', { name: 'MangaDex' }).first().click()
  await expect(page.getByRole('button').filter({ hasText: 'One Piece' })).toBeVisible()
})
