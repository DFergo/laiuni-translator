// LAIUNI Translator — client for the sidecar routes (Sprint 5 contracts).
// Same-origin relative paths; nginx routes these to the frontend sidecar.

import type { JobState, LanguagesResponse, Branding } from './types'

async function asJson<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error((await r.text().catch(() => '')) || r.statusText)
  return r.json() as Promise<T>
}

export async function requestToken(email: string): Promise<void> {
  await fetch('/request-token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  // Always generic — no enumeration (SPEC §8). Nothing to read.
}

// Email-only mode (§12.5): a whitelisted email is sufficient — the sidecar waits
// for the backend and returns the bearer token directly (no code step).
export async function requestTokenEmailOnly(email: string): Promise<AuthResult> {
  const r = await fetch('/request-token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (!r.ok) throw new Error('not_authorized')
  const d = (await r.json()) as { token?: string; scheduling?: SchedulingPolicy | null }
  if (!d.token) throw new Error('not_authorized')
  return { token: d.token, scheduling: d.scheduling ?? null }
}

// Per-user scheduling policy returned on sign-in (§12.6/§12.7): a single mode
// that drives exactly the buttons shown — 'both' shows the toggle, 'immediate'
// and 'scheduled' force that mode with no toggle.
export interface SchedulingPolicy { mode: 'scheduled' | 'immediate' | 'both'; batch_max?: number }
export interface AuthResult { token: string; scheduling: SchedulingPolicy | null }

export async function verify(email: string, code: string): Promise<AuthResult> {
  const r = await fetch('/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, code }),
  })
  if (!r.ok) throw new Error('invalid_code')
  const d = (await r.json()) as { token: string; scheduling?: SchedulingPolicy | null }
  return { token: d.token, scheduling: d.scheduling ?? null }
}

export async function getLanguages(): Promise<LanguagesResponse> {
  return asJson<LanguagesResponse>(await fetch('/languages'))
}

export async function getBranding(): Promise<Branding> {
  try {
    const d = (await asJson<{ branding?: Branding }>(await fetch('/internal/config')))
    return d.branding ?? {}
  } catch {
    return {}
  }
}

export interface PortalConfig { app_language: string; auth_mode: string; branding: Branding }

export async function getConfig(): Promise<PortalConfig> {
  try {
    const d = await asJson<{ app_language?: string; auth_mode?: string; branding?: Branding }>(await fetch('/internal/config'))
    return { app_language: d.app_language || 'en', auth_mode: d.auth_mode || 'token', branding: d.branding ?? {} }
  } catch {
    return { app_language: 'en', auth_mode: 'token', branding: {} }
  }
}

export interface SubmitOpts {
  file: File
  sourceLang: string
  targetLangs: string[]
  glossary: string
  mode: 'immediate' | 'scheduled'
  options?: Record<string, boolean>   // §13.2 per-job document options
}

export async function submitJob(token: string, o: SubmitOpts): Promise<JobState> {
  const fd = new FormData()
  fd.append('file', o.file)
  fd.append('source_lang', o.sourceLang)
  fd.append('target_langs', JSON.stringify(o.targetLangs))
  fd.append('glossary', o.glossary)
  fd.append('mode', o.mode)
  fd.append('options', JSON.stringify(o.options || {}))
  return asJson<JobState>(
    await fetch('/jobs', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd }),
  )
}

export async function getJob(token: string, ref: string): Promise<JobState> {
  return asJson<JobState>(
    await fetch(`/jobs/${ref}`, { headers: { Authorization: `Bearer ${token}` } }),
  )
}

export async function downloadJob(token: string, ref: string): Promise<Blob> {
  const r = await fetch(`/jobs/${ref}/download`, { headers: { Authorization: `Bearer ${token}` } })
  if (!r.ok) throw new Error('download failed')
  return r.blob()
}
