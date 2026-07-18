import { useState } from 'react'
import { requestToken, requestTokenEmailOnly, verify, type SchedulingPolicy } from '../api'
import { useT } from '../i18n'
import { Button, Card, Field, inputClass } from './ui'
import { Banner } from './Banner'

export function AuthCard({ authMode = 'token', onVerified }: { authMode?: string; onVerified: (token: string, email: string, scheduling: SchedulingPolicy | null) => void }) {
  const t = useT()
  const emailOnly = authMode === 'email-only'
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function send() {
    if (!email.trim()) return
    setBusy(true); setError('')
    try {
      if (emailOnly) {
        // §12.5 — a whitelisted email is sufficient; sign in without a code.
        const res = await requestTokenEmailOnly(email.trim())
        onVerified(res.token, email.trim(), res.scheduling)
        return
      }
      await requestToken(email.trim())
      setSent(true)
    } catch {
      setError(emailOnly ? t('auth.errNotAuthorized') : t('auth.errServer'))
    } finally {
      setBusy(false)
    }
  }

  async function submit() {
    if (!code.trim()) return
    setBusy(true); setError('')
    try {
      const res = await verify(email.trim(), code.trim())
      onVerified(res.token, email.trim(), res.scheduling)
    } catch {
      setError(t('auth.errCode'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <h1 className="mb-1 text-[1.5rem] font-semibold text-primary">{t('auth.title')}</h1>
      <p className="mb-5 text-sm text-text-secondary">{t('auth.intro')}</p>

      {!sent ? (
        <div className="space-y-4">
          <Field label={t('auth.email')}>
            <input
              className={inputClass}
              type="email"
              dir="ltr"
              value={email}
              autoFocus
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && send()}
              placeholder={t('auth.emailPlaceholder')}
            />
          </Field>
          <Button onClick={send} disabled={busy || !email.trim()}>
            {busy ? (emailOnly ? t('auth.verifying') : t('auth.sending')) : (emailOnly ? t('auth.title') : t('auth.sendCode'))}
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          <Banner kind="info">{t('auth.codeSent')}</Banner>
          <Field label={t('auth.code')}>
            <input
              className={inputClass}
              inputMode="numeric"
              dir="ltr"
              value={code}
              autoFocus
              onChange={(e) => setCode(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
              placeholder="123456"
            />
          </Field>
          <Button onClick={submit} disabled={busy || !code.trim()}>
            {busy ? t('auth.verifying') : t('auth.verify')}
          </Button>
          <button
            className="w-full text-center text-[0.8125rem] text-text-secondary hover:underline"
            onClick={() => { setSent(false); setCode(''); setError('') }}
          >
            {t('auth.differentEmail')}
          </button>
        </div>
      )}

      {error && <div className="mt-4"><Banner kind="danger">{error}</Banner></div>}
    </Card>
  )
}
