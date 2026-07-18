// Copyright (c) 2026 UNI Global Union. All rights reserved. See LICENSE.

import { useState, useEffect, useCallback } from 'react'
import { t } from './i18n'
import type { Phase, LangCode, Role, DeploymentConfig, SurveyData, RecoveryData, BrandingConfig } from './types'
import LanguageSelector from './components/LanguageSelector'
import DisclaimerPage from './components/DisclaimerPage'
import SessionPage from './components/SessionPage'
import RoleSelectPage from './components/RoleSelectPage'
import AuthPage from './components/AuthPage'
import InstructionsPage from './components/InstructionsPage'
import SurveyPage from './components/SurveyPage'
import ChatShell from './components/ChatShell'

function App() {
  const [phase, setPhase] = useState<Phase>('loading')
  const [lang, setLang] = useState<LangCode>('en')
  const [config, setConfig] = useState<DeploymentConfig | null>(null)
  const [sessionToken, setSessionToken] = useState('')
  const [selectedRole, setSelectedRole] = useState<Role | null>(null)
  const [survey, setSurvey] = useState<SurveyData | null>(null)
  const [recoveryData, setRecoveryData] = useState<RecoveryData | null>(null)
  const [verifiedEmail, setVerifiedEmail] = useState('')
  const [brandingText, setBrandingText] = useState<BrandingConfig | null>(null)

  useEffect(() => {
    fetchConfig()
  }, [])

  // Push browser history entry on phase change (so browser back works)
  const navigateTo = useCallback((next: Phase) => {
    window.history.pushState({ phase: next }, '', '')
    setPhase(next)
  }, [])

  // Handle browser back button
  useEffect(() => {
    const onPopState = (e: PopStateEvent) => {
      if (e.state?.phase) {
        setPhase(e.state.phase)
      } else {
        // No state — go to language selector
        setPhase('language')
      }
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  // Warn before reload/close during active session
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (phase === 'chat' || phase === 'survey') {
        e.preventDefault()
      }
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [phase])

  async function fetchConfig() {
    try {
      const res = await fetch('/internal/config')
      if (res.ok) {
        const data: DeploymentConfig = await res.json()
        setConfig(data)
        // A generic frontend that hasn't been configured from the backend yet
        if (data.configured === false) {
          setPhase('unconfigured')
          return
        }
      }
    } catch {
      // Config fetch failed — use defaults
    }
    setPhase('language')
  }

  // Back handlers for each phase
  const goBackFrom: Partial<Record<Phase, () => void>> = {
    disclaimer: () => navigateTo('language'),
    session: () => navigateTo(config?.disclaimer_enabled === false ? 'language' : 'disclaimer'),
    role_select: () => navigateTo('session'),
    auth: () => navigateTo('role_select'),
    instructions: () => navigateTo(selectedRole && config?.auth?.[selectedRole] ? 'auth' : 'role_select'),
    survey: () => navigateTo('instructions'),
  }

  // Fetch translated branding text for the selected language
  async function fetchBrandingText(langCode: LangCode) {
    try {
      const res = await fetch(`/internal/branding/${langCode}`)
      if (res.ok) {
        const data = await res.json()
        setBrandingText(data)
      }
    } catch {
      // Fallback: no translated text, components use i18n defaults
    }
  }

  // language → disclaimer (or skip) → session
  const handleLanguage = (selected: LangCode) => {
    setLang(selected)
    // Fetch translated branding if this frontend has custom text
    if (config?.branding?.custom) {
      fetchBrandingText(selected)
    }
    if (config?.disclaimer_enabled === false) {
      navigateTo('session')
    } else {
      navigateTo('disclaimer')
    }
  }

  const handleDisclaimer = () => {
    navigateTo('session')
  }

  // session → role_select
  const handleNewSession = (token: string) => {
    setSessionToken(token)
    navigateTo('role_select')
  }

  const handleRecover = async (token: string): Promise<string | null> => {
    setSessionToken(token)

    // Step 1: Request recovery via sidecar
    try {
      const res = await fetch('/internal/session/recover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token }),
      })
      if (!res.ok) return 'Invalid token format'
    } catch {
      return 'Connection error. Please try again.'
    }

    // Step 2: Poll sidecar for recovery result (backend resolves via pull-inverse)
    const maxAttempts = 10
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise(r => setTimeout(r, 1000))
      try {
        const res = await fetch(`/internal/session/${token}/recover`)
        if (!res.ok) continue
        const result = await res.json()

        if (result.status === 'pending') continue

        if (result.status === 'found' && result.data) {
          const data = result.data as RecoveryData
          setLang(data.language || lang)
          setSelectedRole(data.role as Role)
          setSurvey(data.survey)
          setRecoveryData(data)
          navigateTo('chat')
          return null // success
        }

        if (result.status === 'expired') {
          return 'Session expired. Please start a new session.'
        }

        return 'Session not found.'
      } catch {
        continue
      }
    }

    return 'Recovery timed out. Please try again.'
  }

  // role_select → auth (if this profile requires it) → instructions
  const handleRoleSelect = (role: Role) => {
    setSelectedRole(role)
    if (config?.auth?.[role]) {
      navigateTo('auth')
    } else {
      navigateTo('instructions')
    }
  }

  const handleAuth = (email: string) => {
    setVerifiedEmail(email)
    navigateTo('instructions')
  }

  // instructions → survey
  const handleInstructions = () => {
    navigateTo('survey')
  }

  // survey → chat
  const handleSurvey = (data: SurveyData) => {
    // Inject verified email from auth phase (if present)
    if (verifiedEmail && !data.email) {
      data.email = verifiedEmail
    }
    setSurvey(data)
    navigateTo('chat')
  }

  // Merge base branding (app_title, logo_url) with translated text (disclaimer_text, instructions_text)
  const mergedBranding: BrandingConfig | undefined = config?.branding
    ? { ...config.branding, ...brandingText }
    : undefined

  const showFooter = phase !== 'chat' && phase !== 'loading'

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <header className="bg-uni-blue text-white px-6 py-3 shadow-md flex items-center justify-between">
        <div className="flex items-center gap-3">
          <img src={mergedBranding?.logo_url || '/uni-logo.png'} alt="UNI" className="h-8 brightness-0 invert" />
          <h1 className="text-xl font-semibold">{mergedBranding?.app_title || 'HRDD Helper'}</h1>
        </div>
        <span className="text-sm opacity-75">UNI Global Union</span>
      </header>

      <main className="flex-1">
        {phase === 'loading' && (
          <div className="flex items-center justify-center mt-20">
            <p className="text-gray-400">Loading...</p>
          </div>
        )}
        {phase === 'unconfigured' && (
          <div className="max-w-lg mx-auto mt-20 text-center px-6">
            <div className="bg-white rounded-xl shadow-md border border-gray-200 p-8">
              <h2 className="text-xl font-semibold text-gray-800 mb-2">Not configured yet</h2>
              <p className="text-sm text-gray-500">
                This frontend has been deployed but is not configured. An administrator needs to register and configure it from the backend before it can be used.
              </p>
            </div>
          </div>
        )}
        {phase === 'language' && <LanguageSelector onSelect={handleLanguage} branding={mergedBranding} languages={config?.languages} />}
        {phase === 'disclaimer' && <DisclaimerPage lang={lang} onAccept={handleDisclaimer} onBack={goBackFrom.disclaimer!} branding={mergedBranding} dataProtectionEmail={config?.data_protection_email} />}
        {phase === 'session' && <SessionPage lang={lang} onNewSession={handleNewSession} onRecover={handleRecover} onBack={goBackFrom.session!} />}
        {phase === 'role_select' && config && <RoleSelectPage lang={lang} config={config} onSelect={handleRoleSelect} onBack={goBackFrom.role_select!} />}
        {phase === 'auth' && <AuthPage lang={lang} onVerified={handleAuth} onBack={goBackFrom.auth!} />}
        {phase === 'instructions' && selectedRole && <InstructionsPage lang={lang} role={selectedRole} onContinue={handleInstructions} onBack={goBackFrom.instructions!} branding={mergedBranding} />}
        {phase === 'survey' && config && selectedRole && <SurveyPage lang={lang} config={config} role={selectedRole} onSubmit={handleSurvey} onBack={goBackFrom.survey!} />}
        {phase === 'chat' && survey && (
          <ChatShell
            lang={lang}
            sessionToken={sessionToken}
            survey={survey}
            recoveryData={recoveryData}
          />
        )}
      </main>

      {showFooter && (
        <footer className="text-center text-xs text-gray-400 py-3 space-y-1">
          <p>{t('footer_disclaimer', lang)}</p>
          <p>© 2026 UNI Global Union</p>
        </footer>
      )}
    </div>
  )
}

export default App
