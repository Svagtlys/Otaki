const TOKEN_KEY = 'otaki_token'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export function extractDetail(err: unknown): string {
  if (err instanceof ApiError) {
    try {
      return (JSON.parse(err.message) as { detail: string }).detail
    } catch {
      // Non-JSON response (e.g. raw HTML 504 from nginx proxy)
      if (err.status >= 500) {
        return 'Suwayomi is unreachable — check your connection and try again.'
      }
      return err.message
    }
  }
  return 'An unexpected error occurred'
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem(TOKEN_KEY)
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options?.headers as Record<string, string>),
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const response = await fetch(path, { ...options, headers })

  if (!response.ok) {
    if (response.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      window.location.href = '/login'
    }
    const text = await response.text().catch(() => response.statusText)
    throw new ApiError(response.status, text)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}
