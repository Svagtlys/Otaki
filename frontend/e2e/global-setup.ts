import { resetBackend } from './reset-backend.js'

export default async function globalSetup() {
  console.log('[global-setup] Resetting backend…')
  await resetBackend()
  console.log('[global-setup] Backend ready')
}
