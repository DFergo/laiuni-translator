import { useState } from 'react'
import { requestToken, verify } from '../api'
import { Button, Card, Field, inputClass } from './ui'
import { Banner } from './Banner'

export function AuthCard({ onVerified }: { onVerified: (token: string, email: string) => void }) {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function send() {
    if (!email.trim()) return
    setBusy(true); setError('')
    try {
      await requestToken(email.trim())
      setSent(true)
    } catch {
      setError('Could not reach the server. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  async function submit() {
    if (!code.trim()) return
    setBusy(true); setError('')
    try {
      const token = await verify(email.trim(), code.trim())
      onVerified(token, email.trim())
    } catch {
      setError('That code is invalid or has expired.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <h1 className="mb-1 text-[1.5rem] font-semibold text-primary">Sign in</h1>
      <p className="mb-5 text-sm text-text-secondary">
        Access is limited to approved addresses. Enter your email to receive a one-time code.
      </p>

      {!sent ? (
        <div className="space-y-4">
          <Field label="Email">
            <input
              className={inputClass}
              type="email"
              value={email}
              autoFocus
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && send()}
              placeholder="you@organization.org"
            />
          </Field>
          <Button onClick={send} disabled={busy || !email.trim()}>
            {busy ? 'Sending…' : 'Send code'}
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          <Banner kind="info">If your address is approved, a 6-digit code is on its way. Check your email.</Banner>
          <Field label="Verification code">
            <input
              className={inputClass}
              inputMode="numeric"
              value={code}
              autoFocus
              onChange={(e) => setCode(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
              placeholder="123456"
            />
          </Field>
          <Button onClick={submit} disabled={busy || !code.trim()}>
            {busy ? 'Verifying…' : 'Verify'}
          </Button>
          <button
            className="w-full text-center text-[0.8125rem] text-text-secondary hover:underline"
            onClick={() => { setSent(false); setCode(''); setError('') }}
          >
            Use a different email
          </button>
        </div>
      )}

      {error && <div className="mt-4"><Banner kind="danger">{error}</Banner></div>}
    </Card>
  )
}
