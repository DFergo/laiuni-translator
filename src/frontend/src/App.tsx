// Copyright (c) 2026 UNI Global Union. All rights reserved. See LICENSE.
// LAIUNI Translator — user portal (Sprint 6 + 12 i18n): auth → upload → status → done.

import { useState, useEffect, useCallback } from 'react'
import type { JobState, Language, FormatTier, Branding, Step } from './types'
import { SUPPORTED_FORMATS } from './types'
import { getLanguages, getConfig, submitJob, getJob } from './api'
import type { SubmitOpts } from './api'
import { translator, TContext, LANGS_RTL, type Lang } from './i18n'
import { AuthCard } from './components/AuthCard'
import { PortalForm } from './components/PortalForm'
import { StatusView } from './components/StatusView'
import { DoneScreen } from './components/DoneScreen'
import { Banner } from './components/Banner'

function applyBranding(b: Branding) {
  if (b.app_title) document.title = b.app_title
  for (const [key, val] of Object.entries(b.colors ?? {})) {
    document.documentElement.style.setProperty(`--color-${key}`, val)
  }
}

export default function App() {
  const [step, setStep] = useState<Step>('auth')
  const [token, setToken] = useState('')
  const [languages, setLanguages] = useState<Language[]>([])
  const [formats] = useState<FormatTier[]>(SUPPORTED_FORMATS)  // fixed constant — no push needed
  const [branding, setBranding] = useState<Branding>({})
  const [lang, setLang] = useState<Lang>('en')
  const [authMode, setAuthMode] = useState('token')
  const [job, setJob] = useState<JobState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const t = translator(lang)

  // Load the offered languages + config (app language + branding). The sidecar
  // persists the languages catalogue (pushed by the backend only when the
  // glossary changes), so it's normally there immediately; on a first-ever cold
  // start the backend hasn't pushed yet, so retry until it's populated. Formats
  // are a fixed constant (above) — file acceptance never waits on a push.
  useEffect(() => {
    let alive = true
    let tries = 0
    const loadLanguages = async () => {
      try {
        const r = await getLanguages()
        if (!alive) return
        if (r.languages.length > 0) {
          setLanguages(r.languages)
          return
        }
      } catch { /* transient — retry */ }
      if (alive && tries++ < 40) setTimeout(loadLanguages, 1500)  // up to ~60s
    }
    loadLanguages()
    getConfig().then((c) => {
      setBranding(c.branding); applyBranding(c.branding)
      setLang(c.app_language as Lang)
      setAuthMode(c.auth_mode)
      document.documentElement.lang = c.app_language
      document.documentElement.dir = LANGS_RTL.includes(c.app_language as Lang) ? 'rtl' : 'ltr'
    }).catch(() => {})
    return () => { alive = false }
  }, [])

  // Poll job status while on the status screen.
  useEffect(() => {
    if (step !== 'status' || !job?.ref) return
    let alive = true
    const tick = async () => {
      try {
        const s = await getJob(token, job.ref)
        if (!alive) return
        setJob(s)
        if (s.status === 'done') setStep('done')
      } catch { /* transient — keep polling */ }
    }
    const id = setInterval(tick, 2000)
    tick()
    return () => { alive = false; clearInterval(id) }
  }, [step, job?.ref, token])

  const onSubmit = useCallback(async (o: SubmitOpts) => {
    setBusy(true); setError('')
    try {
      const s = await submitJob(token, o)
      if (s.status === 'rejected' || s.status === 'error') {
        setError(s.error || t('portal.errRejected'))
        return
      }
      setJob(s)
      setStep('status')
    } catch {
      setError(t('portal.errSubmit'))
    } finally {
      setBusy(false)
    }
  }, [token, t])

  function restart() {
    setJob(null); setError(''); setStep('portal')
  }

  return (
    <TContext.Provider value={t}>
      <div className="flex min-h-screen flex-col">
        <header className="flex items-center gap-3 border-b border-border bg-primary px-6 py-3 text-white">
          {branding.logo_url && <img src={branding.logo_url} alt="" className="h-8" />}
          <h1 className="text-lg font-semibold">{branding.app_title || 'LAIUNI Translator'}</h1>
        </header>

        <main className="flex flex-1 items-start justify-center px-4 py-10">
          <div className="w-full max-w-flow space-y-4">
            {step === 'auth' && (
              <AuthCard authMode={authMode} onVerified={(tok) => { setToken(tok); setStep('portal') }} />
            )}
            {step === 'portal' && (
              <>
                {error && <Banner kind="danger">{error}</Banner>}
                <PortalForm languages={languages} formats={formats} busy={busy} onSubmit={onSubmit} />
              </>
            )}
            {step === 'status' && job && <StatusView job={job} languages={languages} />}
            {step === 'done' && job && (
              <DoneScreen token={token} jobRef={job.ref} onRestart={restart} />
            )}
          </div>
        </main>

        <footer className="py-4 text-center text-[0.8125rem] text-text-secondary">
          {t('footer')}
        </footer>
      </div>
    </TContext.Provider>
  )
}
