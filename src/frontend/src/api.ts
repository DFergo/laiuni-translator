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

export async function verify(email: string, code: string): Promise<string> {
  const r = await fetch('/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, code }),
  })
  if (!r.ok) throw new Error('invalid_code')
  const d = (await r.json()) as { token: string }
  return d.token
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
}

export async function submitJob(token: string, o: SubmitOpts): Promise<JobState> {
  const fd = new FormData()
  fd.append('file', o.file)
  fd.append('source_lang', o.sourceLang)
  fd.append('target_langs', JSON.stringify(o.targetLangs))
  fd.append('glossary', o.glossary)
  fd.append('mode', o.mode)
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
