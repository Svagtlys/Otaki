import { execSync } from 'child_process'

export default async function globalTeardown() {
  try {
    execSync('pkill -f "uvicorn app.main:app"', { stdio: 'ignore' })
    console.log('[global-teardown] Backend stopped')
  } catch {
    // nothing was running — fine
  }
}
