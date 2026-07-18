import { useState } from 'react'
import { t } from '../i18n'
import { generateToken } from '../token'
import type { LangCode } from '../types'

interface Props {
  lang: LangCode
  onNewSession: (token: string) => void
  onRecover: (token: string) => Promise<string | null>  // returns error message or null on success
  onBack: () => void
}

export default function SessionPage({ lang, onNewSession, onRecover, onBack }: Props) {
  const [mode, setMode] = useState<'choose' | 'new' | 'recover'>('choose')
  const [newToken, setNewToken] = useState('')
  const [recoverToken, setRecoverToken] = useState('')
  const [recoverError, setRecoverError] = useState('')
  const [recovering, setRecovering] = useState(false)

  const handleNew = () => {
    const token = generateToken()
    setNewToken(token)
    setMode('new')
  }

  const handleRecover = async () => {
    const trimmed = recoverToken.trim().toUpperCase()
    if (!trimmed || !trimmed.includes('-')) {
      setRecoverError('Invalid token format')
      return
    }
    setRecoverError('')
    setRecovering(true)
    const error = await onRecover(trimmed)
    setRecovering(false)
    if (error) {
      setRecoverError(error)
    }
  }

  return (
    <div className="max-w-4xl mx-auto mt-8 p-6">
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h2 className="text-xl font-semibold text-gray-800 mb-6">{t('session_title', lang)}</h2>

        {mode === 'choose' && (
          <div className="space-y-3">
            <button
              onClick={handleNew}
              className="w-full bg-uni-blue text-white rounded-lg px-4 py-3 font-medium transition-colors hover:opacity-90"
            >
              {t('session_new', lang)}
            </button>
            <button
              onClick={() => setMode('recover')}
              className="w-full border border-gray-300 text-gray-700 rounded-lg px-4 py-3 font-medium transition-colors hover:bg-gray-50"
            >
              {t('session_recover', lang)}
            </button>
            <button
              onClick={onBack}
              className="w-full text-gray-500 text-sm hover:text-gray-700"
            >
              &larr; {t('nav_back', lang)}
            </button>
          </div>
        )}

        {mode === 'new' && (
          <div className="text-center space-y-4">
            <p className="text-sm text-gray-500">{t('session_token_label', lang)}</p>
            <div className="bg-gray-50 rounded-lg px-6 py-4 border border-gray-200">
              <span className="text-2xl font-mono font-bold text-uni-blue tracking-wider">{newToken}</span>
            </div>
            <p className="text-sm text-gray-400">{t('session_token_save', lang)}</p>
            <button
              onClick={() => onNewSession(newToken)}
              className="w-full bg-uni-blue text-white rounded-lg px-4 py-2.5 font-medium transition-colors hover:opacity-90"
            >
              {t('session_continue', lang)}
            </button>
          </div>
        )}

        {mode === 'recover' && (
          <div className="space-y-4">
            <div>
              <input
                type="text"
                value={recoverToken}
                onChange={e => setRecoverToken(e.target.value)}
                placeholder={t('session_recover_placeholder', lang)}
                disabled={recovering}
                className="w-full border border-gray-300 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none font-mono uppercase disabled:opacity-50"
              />
              {recoverError && <p className="text-uni-red text-sm mt-1">{recoverError}</p>}
            </div>
            <button
              onClick={handleRecover}
              disabled={recovering}
              className="w-full bg-uni-blue text-white rounded-lg px-4 py-2.5 font-medium transition-colors hover:opacity-90 disabled:opacity-50"
            >
              {recovering ? 'Recovering...' : t('session_recover_button', lang)}
            </button>
            {!recovering && (
              <button
                onClick={() => setMode('choose')}
                className="w-full text-gray-500 text-sm hover:text-gray-700"
              >
                &larr; Back
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
