import { test, expect } from '@playwright/test'
import { resetBackend } from './reset-backend.js'

test.beforeAll(async () => {
  await resetBackend()
})

// ---------------------------------------------------------------------------
// Config from .env.test (loaded by playwright.config.ts via dotenv)
// ---------------------------------------------------------------------------

const SUWAYOMI_URL = process.env.SUWAYOMI_URL ?? ''
const SUWAYOMI_USERNAME = process.env.SUWAYOMI_USERNAME ?? ''
const SUWAYOMI_PASSWORD = process.env.SUWAYOMI_PASSWORD ?? ''
const DOWNLOAD_PATH = process.env.SUWAYOMI_DOWNLOAD_PATH ?? '/tmp'
const LIBRARY_PATH_ENV = process.env.LIBRARY_PATH ?? '/tmp'

const hasSuwayomi = Boolean(SUWAYOMI_URL)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Navigate to /setup and complete step 1 (creates admin or auto-logins via 409).
 * After success, step 2 is visible.
 */
async function doStep1(page: import('@playwright/test').Page) {
  await page.goto('/setup')
  await expect(page.getByRole('heading', { name: 'Create admin account' })).toBeVisible()
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill('adminpass')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByRole('heading', { name: 'Connect to Suwayomi' })).toBeVisible({
    timeout: 10000,
  })
}

/**
 * Complete step 2 using real Suwayomi credentials from .env.test.
 *
 * Both normal and confirm mode share the same click flow:
 *   1. Click "Connect" (fields are pre-filled and disabled in confirm mode)
 *   2. Wait for the success message
 *   3. Click "Continue" (normal) or "Confirm" (confirm mode)
 */
async function doStep2(page: import('@playwright/test').Page) {
  await expect(page.getByRole('heading', { name: 'Connect to Suwayomi' })).toBeVisible()

  const urlInput = page.getByLabel('Suwayomi URL')
  // If the URL is already pre-filled (confirm mode), don't overwrite it.
  const currentUrl = await urlInput.inputValue()
  if (!currentUrl) {
    await urlInput.fill(SUWAYOMI_URL)
    if (SUWAYOMI_USERNAME) await page.getByLabel('Username (optional)').fill(SUWAYOMI_USERNAME)
  }
  // Always fill password — it is never pre-filled (even in confirm mode).
  if (SUWAYOMI_PASSWORD) await page.getByLabel('Password (optional)').fill(SUWAYOMI_PASSWORD)

  await page.getByRole('button', { name: 'Connect' }).click()
  await expect(page.getByText(/connected.*suwayomi/i)).toBeVisible({ timeout: 15000 })
  // After success: "Confirm" in confirm mode (url was pre-filled), "Continue" otherwise.
  const advanceButton = page.getByRole('button', { name: /^(Continue|Confirm)$/ })
  await advanceButton.click()

  await expect(page.getByRole('heading', { name: 'Select sources' })).toBeVisible({
    timeout: 15000,
  })
}

// ---------------------------------------------------------------------------
// Tests are ordered intentionally — workers: 1 ensures sequential execution.
//
// DB state flow (fresh DB from globalSetup):
//   1. step 2 bad URL      → admin created + logged in, Suwayomi NOT connected
//   2. step 1 skip         → admin exists → 409 → auto-login → silent advance
//   3. step 4 non-existent* → connects Suwayomi, sources saved, confirmation shown →
//                              Go back → paths NOT written
//   4. happy path*          → step1 login, step2 confirm, step3, step4 → /login
//   5. setup already done*  → /setup redirects to /login
//
// * skipped when SUWAYOMI_URL not set in .env.test
// ---------------------------------------------------------------------------

test('step 2 bad URL: unreachable host shows inline error', async ({ page }) => {
  // First test on a fresh DB — creates the admin user in step 1.
  await page.goto('/setup')
  await expect(page.getByRole('heading', { name: 'Create admin account' })).toBeVisible()
  await expect(page.getByText('Step 1 of 4')).toBeVisible()
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill('adminpass')
  await page.getByRole('button', { name: 'Create account' }).click()

  await expect(page.getByRole('heading', { name: 'Connect to Suwayomi' })).toBeVisible({
    timeout: 10000,
  })
  await expect(page.getByText('Step 2 of 4')).toBeVisible()
  await page.getByLabel('Suwayomi URL').fill('http://localhost:9999')
  await page.getByRole('button', { name: 'Connect' }).click()

  // Stays on step 2 with an error
  await expect(page.getByText('Step 2 of 4')).toBeVisible({ timeout: 15000 })
  await expect(page.getByRole('heading', { name: 'Connect to Suwayomi' })).toBeVisible()
  await expect(page.getByText('Could not connect to Suwayomi')).toBeVisible()
})

test('step 1 skip: existing admin advances silently to step 2', async ({ page }) => {
  // Admin was created in the previous test → step 1 returns 409 → auto-login → advance.
  await page.goto('/setup')
  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill('adminpass')
  await page.getByRole('button', { name: 'Create account' }).click()

  // Advances to step 2 with no error shown
  await expect(page.getByRole('heading', { name: 'Connect to Suwayomi' })).toBeVisible({
    timeout: 10000,
  })
  await expect(page.locator('p[style*="color: red"]')).toHaveCount(0)
})

test('step 4 non-existent paths: shows creation confirmation, go back stays on step 4', async ({ page }) => {
  test.skip(!hasSuwayomi, 'SUWAYOMI_URL not set in .env.test')

  await doStep1(page)
  await doStep2(page)

  // Step 3 — add the first available source, then save
  await expect(page.getByText('+ Add').first()).toBeVisible({ timeout: 10000 })
  await page.getByText('+ Add').first().click()
  await page.getByRole('button', { name: 'Save order' }).click()
  await expect(page.getByRole('heading', { name: 'Set paths' })).toBeVisible()
  await expect(page.getByText('Step 4 of 4')).toBeVisible()

  // Submit non-existent paths → confirmation screen (not an error)
  await page.getByLabel('Suwayomi download path').fill('/nonexistent/downloads')
  await page.getByLabel('Library path').fill('/nonexistent/library')
  await page.getByRole('button', { name: 'Save paths' }).click()

  await expect(page.getByText(/do not exist yet/i)).toBeVisible({ timeout: 10000 })

  // Go back — paths NOT written, still on step 4, setup still incomplete
  await page.getByRole('button', { name: 'Go back' }).click()
  await expect(page.getByText('Step 4 of 4')).toBeVisible()
})

test('happy path: all 4 steps → redirects to /login', async ({ page }) => {
  test.skip(!hasSuwayomi, 'SUWAYOMI_URL not set in .env.test')

  // Step 1 (admin exists → 409 → auto-login)
  await doStep1(page)
  await expect(page.getByText('Step 2 of 4')).toBeVisible()

  // Step 2 (Suwayomi already connected from step 4 bad path test → confirm mode)
  await doStep2(page)
  await expect(page.getByText('Step 3 of 4')).toBeVisible()

  // Step 3 — add the first available source, then save
  await expect(page.getByText('+ Add').first()).toBeVisible({ timeout: 10000 })
  await page.getByText('+ Add').first().click()
  await page.getByRole('button', { name: 'Save order' }).click()
  await expect(page.getByRole('heading', { name: 'Set paths' })).toBeVisible()
  await expect(page.getByText('Step 4 of 4')).toBeVisible()

  // Step 4 with valid paths from .env.test
  await page.getByLabel('Suwayomi download path').fill(DOWNLOAD_PATH)
  await page.getByLabel('Library path').fill(LIBRARY_PATH_ENV)
  await page.getByRole('button', { name: 'Save paths' }).click()

  await expect(page).toHaveURL(/\/login/, { timeout: 10000 })
})

test('setup already complete: /setup redirects to /login', async ({ page }) => {
  test.skip(!hasSuwayomi, 'SUWAYOMI_URL not set in .env.test')

  // After the happy path, SETUP_COMPLETE=True is written to .env.
  // App.tsx fetches /api/setup/complete → { complete: true } → routes /setup to /login.
  await page.goto('/setup')
  await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
})
