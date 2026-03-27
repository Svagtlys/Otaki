import { test, expect } from '@playwright/test'
import { resetBackend, BACKEND_URL } from './reset-backend.js'

const ADMIN_USERNAME = 'admin'
const ADMIN_PASSWORD = 'adminpass'

test.beforeAll(async () => {
  await resetBackend()

  // Create the admin user (step 1 of setup)
  await fetch(`${BACKEND_URL}/api/setup/user`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: ADMIN_USERNAME, password: ADMIN_PASSWORD }),
  })

  // Mark setup as complete via the API — this calls write_env() which updates
  // both the .env file and the in-memory settings object.
  await fetch(`${BACKEND_URL}/api/setup/paths`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ download_path: '/tmp', library_path: '/tmp', create: true }),
  })
})

test('wrong credentials: shows inline error, stays on /login', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Log in to Otaki' })).toBeVisible()

  await page.getByLabel('Username').fill('admin')
  await page.getByLabel('Password').fill('wrongpassword')
  await page.getByRole('button', { name: 'Log in' }).click()

  await expect(page.locator('p[style*="color: red"]')).toBeVisible({ timeout: 5000 })
  await expect(page).toHaveURL(/\/login/)
})

test('correct credentials: redirects away from /login', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Log in to Otaki' })).toBeVisible()

  await page.getByLabel('Username').fill(ADMIN_USERNAME)
  await page.getByLabel('Password').fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Log in' }).click()

  await expect(page).not.toHaveURL(/\/login/, { timeout: 5000 })
})

test('already authenticated: redirects away from /login immediately', async ({ page }) => {
  // Obtain a valid token via direct API call
  const res = await fetch(`${BACKEND_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: ADMIN_USERNAME, password: ADMIN_PASSWORD }),
  })
  const { access_token } = (await res.json()) as { access_token: string }

  // Pre-load the token so the app considers the user authenticated
  await page.goto('/login')
  await page.evaluate((token) => localStorage.setItem('otaki_token', token), access_token)
  await page.goto('/login')

  await expect(page).not.toHaveURL(/\/login/, { timeout: 5000 })
})
