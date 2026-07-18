import { useState, useEffect } from 'react'
import { getSMTPConfig, updateSMTPConfig, testSMTP, getFrontendNotificationEmails, updateFrontendNotificationEmails, listFrontends, type SMTPConfig, type Frontend } from './api'

export default function SMTPTab() {
  const [config, setConfig] = useState<SMTPConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [testResult, setTestResult] = useState<{ status: string; message: string } | null>(null)

  // Notification emails (global)
  const [newNotifyEmail, setNewNotifyEmail] = useState('')

  // Per-frontend notification emails
  const [frontends, setFrontends] = useState<Frontend[]>([])
  const [feNotifyEmails, setFeNotifyEmails] = useState<Record<string, string[]>>({})
  const [newFeEmail, setNewFeEmail] = useState<Record<string, string>>({})
  const [feSaving, setFeSaving] = useState<Record<string, boolean>>({})

  useEffect(() => {
    loadConfig()
    loadFrontends()
  }, [])

  const loadConfig = async () => {
    try {
      const cfg = await getSMTPConfig()
      setConfig(cfg)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load SMTP config')
    }
  }

  const loadFrontends = async () => {
    try {
      const data = await listFrontends()
      const fes = data.frontends || []
      setFrontends(fes)
      // Load per-frontend notification emails
      const emailMap: Record<string, string[]> = {}
      for (const fe of fes) {
        try {
          const feData = await getFrontendNotificationEmails(fe.id)
          emailMap[fe.id] = feData.emails || []
        } catch {
          emailMap[fe.id] = []
        }
      }
      setFeNotifyEmails(emailMap)
    } catch {
      // Frontends may not exist yet
    }
  }

  const handleAddNotifyEmail = () => {
    if (!config) return
    const trimmed = newNotifyEmail.trim().toLowerCase()
    if (!trimmed || config.notification_emails.includes(trimmed)) return
    setConfig({ ...config, notification_emails: [...config.notification_emails, trimmed] })
    setNewNotifyEmail('')
  }

  const handleRemoveNotifyEmail = (email: string) => {
    if (!config) return
    setConfig({ ...config, notification_emails: config.notification_emails.filter(e => e !== email) })
  }

  const handleAddFeEmail = async (feId: string) => {
    const trimmed = (newFeEmail[feId] || '').trim().toLowerCase()
    if (!trimmed) return
    const current = feNotifyEmails[feId] || []
    if (current.includes(trimmed)) return
    setFeSaving(prev => ({ ...prev, [feId]: true }))
    try {
      const updated = await updateFrontendNotificationEmails(feId, [...current, trimmed])
      setFeNotifyEmails(prev => ({ ...prev, [feId]: updated.emails }))
      setNewFeEmail(prev => ({ ...prev, [feId]: '' }))
    } catch {
      // ignore
    } finally {
      setFeSaving(prev => ({ ...prev, [feId]: false }))
    }
  }

  const handleRemoveFeEmail = async (feId: string, email: string) => {
    const current = feNotifyEmails[feId] || []
    setFeSaving(prev => ({ ...prev, [feId]: true }))
    try {
      const updated = await updateFrontendNotificationEmails(feId, current.filter(e => e !== email))
      setFeNotifyEmails(prev => ({ ...prev, [feId]: updated.emails }))
    } catch {
      // ignore
    } finally {
      setFeSaving(prev => ({ ...prev, [feId]: false }))
    }
  }

  const updateField = <K extends keyof SMTPConfig>(key: K, value: SMTPConfig[K]) => {
    if (!config) return
    setConfig({ ...config, [key]: value })
  }

  const handleSave = async () => {
    if (!config) return
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const updated = await updateSMTPConfig(config)
      setConfig(updated)
      setSuccess('SMTP settings saved')
      setTimeout(() => setSuccess(''), 3000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    setError('')
    try {
      const result = await testSMTP()
      setTestResult(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Test failed')
    } finally {
      setTesting(false)
    }
  }

  if (!config) return <p className="text-gray-400 text-sm">Loading...</p>

  return (
    <div className="space-y-6">
      {/* SMTP Server Configuration */}
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-1">SMTP Configuration</h3>
        <p className="text-xs text-gray-400 mb-4">
          Used for email verification (organizer auth), report delivery, and admin notifications.
        </p>

        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">SMTP Host</label>
            <input
              type="text"
              value={config.host}
              onChange={e => updateField('host', e.target.value)}
              placeholder="smtp.example.com"
              className="w-full border border-gray-300 rounded-lg px-4 py-2 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Port</label>
            <input
              type="number"
              value={config.port}
              onChange={e => updateField('port', parseInt(e.target.value) || 587)}
              className="w-full border border-gray-300 rounded-lg px-4 py-2 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
            />
            <p className="text-xs text-gray-400 mt-1">587 for TLS, 465 for SSL, 25 for unencrypted</p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
            <input
              type="text"
              value={config.username}
              onChange={e => updateField('username', e.target.value)}
              placeholder="user@example.com"
              className="w-full border border-gray-300 rounded-lg px-4 py-2 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              type="password"
              value={config.password}
              onChange={e => updateField('password', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-4 py-2 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">From Address</label>
            <input
              type="email"
              value={config.from_address}
              onChange={e => updateField('from_address', e.target.value)}
              placeholder="hrdd@example.com"
              className="w-full border border-gray-300 rounded-lg px-4 py-2 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Data Protection Email</label>
            <input
              type="email"
              value={config.data_protection_email}
              onChange={e => updateField('data_protection_email', e.target.value)}
              placeholder="blank = use From Address"
              className="w-full border border-gray-300 rounded-lg px-4 py-2 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
            />
            <p className="text-xs text-gray-400 mt-1">GDPR contact shown on the disclaimer. A frontend can override it in its config panel.</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Notification Recipients</label>
            <div className="flex gap-2 mb-2">
              <input
                type="email"
                value={newNotifyEmail}
                onChange={e => setNewNotifyEmail(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), handleAddNotifyEmail())}
                placeholder="admin@example.com"
                className="flex-1 border border-gray-300 rounded-lg px-4 py-2 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
              />
              <button
                onClick={handleAddNotifyEmail}
                disabled={!newNotifyEmail.trim()}
                className="bg-uni-blue text-white rounded-lg px-3 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50"
              >
                Add
              </button>
            </div>
            {config.notification_emails.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-1">
                {config.notification_emails.map(email => (
                  <span key={email} className="inline-flex items-center gap-1 px-2.5 py-1 bg-blue-50 border border-blue-200 rounded-full text-xs text-gray-700">
                    {email}
                    <button onClick={() => handleRemoveNotifyEmail(email)} className="text-gray-400 hover:text-uni-red">&times;</button>
                  </span>
                ))}
              </div>
            )}
            <p className="text-xs text-gray-400 mt-1">Receive alerts for completed/flagged sessions. Save to apply changes.</p>
          </div>
        </div>

        <div className="mb-6">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={config.use_tls}
              onChange={e => updateField('use_tls', e.target.checked)}
              className="rounded border-gray-300 text-uni-blue focus:ring-uni-blue"
            />
            <span className="text-sm text-gray-700">Use TLS encryption</span>
          </label>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="bg-uni-blue text-white rounded-lg px-5 py-2 text-sm font-medium transition-colors hover:opacity-90 disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
          <button
            onClick={handleTest}
            disabled={testing || !config.host}
            className="border border-gray-300 text-gray-600 rounded-lg px-4 py-2 text-sm font-medium transition-colors hover:bg-gray-50 disabled:opacity-50"
          >
            {testing ? 'Testing...' : 'Test Connection'}
          </button>
          {success && <span className="text-sm text-green-600">{success}</span>}
          {error && <span className="text-sm text-uni-red">{error}</span>}
        </div>

        {testResult && (
          <div className={`mt-4 p-3 rounded-lg text-sm ${
            testResult.status === 'ok' ? 'bg-green-50 text-green-700' :
            testResult.status === 'warning' ? 'bg-yellow-50 text-yellow-700' :
            'bg-red-50 text-red-700'
          }`}>
            {testResult.message}
          </div>
        )}
      </div>

      {/* Notification Toggles */}
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-1">Email Notifications</h3>
        <p className="text-xs text-gray-400 mb-4">
          Control which emails the system sends automatically after sessions complete. All notifications are best-effort — failures are logged but never block the system.
        </p>

        <div className="space-y-3">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={config.notify_on_report}
              onChange={e => updateField('notify_on_report', e.target.checked)}
              className="rounded border-gray-300 text-uni-blue focus:ring-uni-blue"
            />
            <div>
              <span className="text-sm font-medium text-gray-700">Notify admin on report generation</span>
              <p className="text-xs text-gray-400">Sends report content to the admin notification address when a session generates a report.</p>
            </div>
          </label>

          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={config.send_summary_to_user}
              onChange={e => updateField('send_summary_to_user', e.target.checked)}
              className="rounded border-gray-300 text-uni-blue focus:ring-uni-blue"
            />
            <div>
              <span className="text-sm font-medium text-gray-700">Send session summary to user</span>
              <p className="text-xs text-gray-400">Emails the session summary to the user after their session ends (requires authorized email).</p>
            </div>
          </label>

          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={config.send_report_to_user}
              onChange={e => updateField('send_report_to_user', e.target.checked)}
              className="rounded border-gray-300 text-uni-blue focus:ring-uni-blue"
            />
            <div>
              <span className="text-sm font-medium text-gray-700">Send report to user</span>
              <p className="text-xs text-gray-400">Emails the generated report to the user (requires authorized email).</p>
            </div>
          </label>
        </div>

        <div className="mt-4">
          <button
            onClick={handleSave}
            disabled={saving}
            className="bg-uni-blue text-white rounded-lg px-5 py-2 text-sm font-medium transition-colors hover:opacity-90 disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save Notification Settings'}
          </button>
        </div>
      </div>

      {/* Authorized users moved to Registered Users tab (Sprint 18) */}
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-1">Authorized Users</h3>
        <p className="text-xs text-gray-500">
          The whitelist of authorised emails is now managed in the{' '}
          <span className="font-medium text-uni-blue">Registered Users</span> tab, where you can also store
          extended contact details (name, organisation, country, sector) and configure per-frontend overrides.
        </p>
      </div>

      {/* Per-frontend notification emails */}
      {frontends.length > 0 && (
        <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-1">Per-Frontend Notifications</h3>
          <p className="text-xs text-gray-400 mb-4">
            Additional notification recipients per frontend. These receive notifications alongside the global recipients above.
          </p>

          <div className="space-y-4">
            {frontends.map(fe => (
              <div key={fe.id} className="border border-gray-200 rounded-lg p-4">
                <h4 className="text-sm font-medium text-gray-700 mb-2">
                  {fe.name || fe.url}
                </h4>
                <div className="flex gap-2 mb-2">
                  <input
                    type="email"
                    value={newFeEmail[fe.id] || ''}
                    onChange={e => setNewFeEmail(prev => ({ ...prev, [fe.id]: e.target.value }))}
                    onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), handleAddFeEmail(fe.id))}
                    placeholder="recipient@example.com"
                    className="flex-1 border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
                  />
                  <button
                    onClick={() => handleAddFeEmail(fe.id)}
                    disabled={feSaving[fe.id] || !(newFeEmail[fe.id] || '').trim()}
                    className="bg-uni-blue text-white rounded-lg px-3 py-1.5 text-xs font-medium hover:opacity-90 disabled:opacity-50"
                  >
                    Add
                  </button>
                </div>
                {(feNotifyEmails[fe.id] || []).length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {(feNotifyEmails[fe.id] || []).map(email => (
                      <span key={email} className="inline-flex items-center gap-1 px-2.5 py-1 bg-blue-50 border border-blue-200 rounded-full text-xs text-gray-700">
                        {email}
                        <button
                          onClick={() => handleRemoveFeEmail(fe.id, email)}
                          disabled={feSaving[fe.id]}
                          className="text-gray-400 hover:text-uni-red"
                        >
                          &times;
                        </button>
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-gray-400 italic">No additional recipients — using global only.</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
