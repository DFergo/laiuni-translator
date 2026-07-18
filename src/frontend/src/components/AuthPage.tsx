import { useState, useRef, useCallback } from 'react'
import { t } from '../i18n'
import type { LangCode } from '../types'

interface Props {
  lang: LangCode
  onVerified: (email: string) => void
  onBack: () => void
}

export default function AuthPage({ lang, onVerified, onBack }: Props) {
  const [email, setEmail] = useState('')
  const [codeSent, setCodeSent] = useState(false)
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [retries, setRetries] = useState(0)
  const sessionTokenRef = useRef(`auth-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`)

  const MAX_RETRIES = 3

  const pollAuthStatus = useCallback(async (expectedStatus: string[]): Promise<string> => {
    for (let i = 0; i < 30; i++) {
      await new Promise(r => setTimeout(r, 1000))
      try {
        const resp = await fetch(`/internal/auth/status/${sessionTokenRef.current}`)
        const data = await resp.json()
        if (expectedStatus.includes(data.status)) {
          return data.status
        }
        if (data.status !== 'pending' && data.status !== 'verifying') {
          return data.status
        }
      } catch {
        continue
      }
    }
    return 'timeout'
  }, [])

  const handleSendCode = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const resp = await fetch('/internal/auth/request-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_token: sessionTokenRef.current,
          email,
          language: lang,
        }),
      })
      if (!resp.ok) throw new Error('Request failed')

      const status = await pollAuthStatus(['code_sent', 'not_authorized', 'smtp_error', 'smtp_not_configured'])

      if (status === 'code_sent') {
        setCodeSent(true)
      } else if (status === 'not_authorized') {
        setError(t('auth_not_authorized', lang))
      } else if (status === 'smtp_error' || status === 'smtp_not_configured') {
        setError(t('auth_smtp_error', lang))
      } else {
        setError(t('auth_timeout', lang))
      }
    } catch {
      setError(t('auth_smtp_error', lang))
    } finally {
      setLoading(false)
    }
  }

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const resp = await fetch('/internal/auth/verify-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_token: sessionTokenRef.current,
          code,
          language: lang,
        }),
      })
      if (!resp.ok) throw new Error('Request failed')

      const status = await pollAuthStatus(['verified', 'invalid_code'])

      if (status === 'verified') {
        onVerified(email)
      } else if (status === 'invalid_code') {
        const newRetries = retries + 1
        setRetries(newRetries)
        if (newRetries >= MAX_RETRIES) {
          setError(t('auth_max_retries', lang))
        } else {
          setError(t('auth_invalid_code', lang))
        }
      } else {
        setError(t('auth_timeout', lang))
      }
    } catch {
      setError(t('auth_smtp_error', lang))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-4xl mx-auto mt-8 p-6">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h2 className="text-xl font-semibold text-gray-800 mb-6">{t('auth_title', lang)}</h2>

        {!codeSent ? (
          <form onSubmit={handleSendCode} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('auth_email_label', lang)}</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none transition-colors"
                required
              />
            </div>
            {error && <p className="text-uni-red text-sm">{error}</p>}
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-uni-blue text-white rounded-lg px-4 py-2.5 font-medium transition-colors hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? '...' : t('auth_send_code', lang)}
            </button>
          </form>
        ) : (
          <form onSubmit={handleVerify} className="space-y-4">
            <p className="text-sm text-gray-600 mb-2">{t('auth_code_sent_to', lang)} <strong>{email}</strong></p>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('auth_code_label', lang)}</label>
              <input
                type="text"
                value={code}
                onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder={t('auth_placeholder', lang)}
                className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-center text-2xl tracking-[0.5em] font-mono focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none transition-colors"
                maxLength={6}
                required
                autoFocus
                disabled={retries >= MAX_RETRIES}
              />
            </div>
            {error && <p className="text-uni-red text-sm">{error}</p>}
            <button
              type="submit"
              disabled={loading || retries >= MAX_RETRIES}
              className="w-full bg-uni-blue text-white rounded-lg px-4 py-2.5 font-medium transition-colors hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? '...' : t('auth_verify', lang)}
            </button>
            {retries >= MAX_RETRIES && (
              <p className="text-sm text-gray-500 text-center">{t('auth_contact_admin', lang)}</p>
            )}
          </form>
        )}
        {!codeSent && !loading && (
          <button
            onClick={onBack}
            className="w-full text-gray-500 text-sm hover:text-gray-700 mt-4"
          >
            &larr; {t('nav_back', lang)}
          </button>
        )}
      </div>
    </div>
  )
}
