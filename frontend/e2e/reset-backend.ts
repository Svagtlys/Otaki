/**
 * Kills the backend, wipes the DB and setup .env keys, then starts a fresh
 * instance and waits for it to be ready.
 *
 * Used by both global-setup.ts (first run) and the per-project beforeAll hook
 * (between browser projects so each starts with a clean state).
 */

import { execSync, spawn } from 'child_process'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export const BACKEND_DIR = path.resolve(__dirname, '../../backend')
const DB_PATH = path.join(BACKEND_DIR, 'otaki.db')
const ENV_PATH = path.join(BACKEND_DIR, '.env')
export const BACKEND_URL = 'http://localhost:8000'

const SETUP_KEYS = [
  'SETUP_COMPLETE',
  'SUWAYOMI_URL',
  'SUWAYOMI_USERNAME',
  'SUWAYOMI_PASSWORD',
  'SUWAYOMI_DOWNLOAD_PATH',
  'LIBRARY_PATH',
]

export async function resetBackend() {
  // Kill any running backend
  try {
    execSync('pkill -f "uvicorn app.main:app"', { stdio: 'ignore' })
  } catch {
    // nothing was running — fine
  }

  // Wait until port 8000 stops responding (old process fully released it)
  const killDeadline = Date.now() + 10_000
  while (Date.now() < killDeadline) {
    try {
      await fetch(`${BACKEND_URL}/health`, { signal: AbortSignal.timeout(300) })
      await sleep(200) // still up — wait more
    } catch {
      break // ECONNREFUSED or timeout — port is free
    }
  }

  // Delete DB so the backend starts with a clean schema
  if (fs.existsSync(DB_PATH)) {
    fs.unlinkSync(DB_PATH)
  }

  // Clear setup-wizard keys from .env (leave SECRET_KEY etc. intact)
  if (fs.existsSync(ENV_PATH)) {
    let content = fs.readFileSync(ENV_PATH, 'utf-8')
    for (const key of SETUP_KEYS) {
      content = content.replace(new RegExp(`^${key}=.*$`, 'gm'), '')
    }
    fs.writeFileSync(ENV_PATH, content.replace(/\n{3,}/g, '\n\n').trimEnd() + '\n')
  }

  // Start a fresh backend — strip .env.test vars so setup guard sees a blank slate
  const childEnv = { ...process.env }
  for (const key of [...SETUP_KEYS, 'SUWAYOMI_USERNAME', 'SUWAYOMI_PASSWORD']) {
    delete childEnv[key]
  }

  const venv = path.join(BACKEND_DIR, '.venv', 'bin', 'uvicorn')
  const logFile = fs.openSync('/tmp/otaki-backend-test.log', 'w')
  const proc = spawn(venv, ['app.main:app', '--port', '8000'], {
    cwd: BACKEND_DIR,
    env: childEnv,
    detached: true,
    stdio: ['ignore', logFile, logFile],
  })
  proc.unref()

  // Wait for the new backend to accept connections
  const startDeadline = Date.now() + 15_000
  while (Date.now() < startDeadline) {
    try {
      const res = await fetch(`${BACKEND_URL}/api/setup/user`, {
        method: 'POST',
        body: '{}',
        headers: { 'Content-Type': 'application/json' },
        signal: AbortSignal.timeout(500),
      })
      if (res.status !== 500) break
    } catch {
      // not yet ready
    }
    await sleep(300)
  }
}

function sleep(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms))
}
