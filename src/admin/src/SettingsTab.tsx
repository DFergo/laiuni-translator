import { useState, useEffect } from 'react'
import {
  getSMTPConfig, updateSMTPConfig, testSMTP,
  getAppSettings, updateAppSettings,
  type SMTPConfig, type AppSettings,
} from './api'

// The 17 app/UI languages (matches core/languages.py).
const LANGS: [string, string][] = [
  ['en', 'English'], ['ar', 'Arabic'], ['de', 'German'], ['es', 'Spanish'], ['fr', 'French'],
  ['hi', 'Hindi'], ['hr', 'Croatian'], ['id', 'Indonesian'], ['it', 'Italian'], ['ja', 'Japanese'],
  ['ne', 'Nepali'], ['nl', 'Dutch'], ['pl', 'Polish'], ['pt', 'Portuguese'], ['sv', 'Swedish'],
  ['th', 'Thai'], ['ur', 'Urdu'],
]

const inputCls = 'w-full border border-gray-300 rounded-lg px-4 py-2 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none'

export default function SettingsTab() {
  const [smtp, setSmtp] = useState<SMTPConfig | null>(null)
  const [app, setApp] = useState<AppSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [testResult, setTestResult] = useState<{ status: string; message: string } | null>(null)

  useEffect(() => {
    getSMTPConfig().then(setSmtp).catch(e => setError(e instanceof Error ? e.message : 'Failed to load SMTP'))
    getAppSettings().then(setApp).catch(() => {})
  }, [])

  const flash = (m: string) => { setSuccess(m); setTimeout(() => setSuccess(''), 3000) }
  const smtpField = <K extends keyof SMTPConfig>(k: K, v: SMTPConfig[K]) => smtp && setSmtp({ ...smtp, [k]: v })

  const saveSmtp = async () => {
    if (!smtp) return
    setSaving(true); setError('')
    try { setSmtp(await updateSMTPConfig(smtp)); flash('Email settings saved') }
    catch (e) { setError(e instanceof Error ? e.message : 'Save failed') }
    finally { setSaving(false) }
  }

  const saveApp = async () => {
    if (!app) return
    setSaving(true); setError('')
    try { setApp(await updateAppSettings(app)); flash('App settings saved') }
    catch (e) { setError(e instanceof Error ? e.message : 'Save failed') }
    finally { setSaving(false) }
  }

  const test = async () => {
    setTesting(true); setTestResult(null); setError('')
    try { setTestResult(await testSMTP()) }
    catch (e) { setError(e instanceof Error ? e.message : 'Test failed') }
    finally { setTesting(false) }
  }

  return (
    <div className="space-y-6">
      {/* App settings */}
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-1">App settings</h3>
        <p className="text-xs text-gray-400 mb-4">Global operational settings. A frontend can override the app language in its own config.</p>
        {app && (
          <>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Retention (hours)</label>
                <input type="number" min={1} value={app.retention_hours}
                  onChange={e => setApp({ ...app, retention_hours: parseInt(e.target.value) || 1 })} className={inputCls} />
                <p className="text-xs text-gray-400 mt-1">Translations + download link expire and are hard-deleted after this.</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Default app language</label>
                <select value={app.app_language} onChange={e => setApp({ ...app, app_language: e.target.value })} className={inputCls}>
                  {LANGS.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
                </select>
                <p className="text-xs text-gray-400 mt-1">Portal UI language (hardcoded i18n); per-frontend override in the Frontends tab.</p>
              </div>
            </div>
            <button onClick={saveApp} disabled={saving} className="mt-4 bg-uni-blue text-white rounded-lg px-5 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50">
              {saving ? 'Saving…' : 'Save app settings'}
            </button>
          </>
        )}
      </div>

      {/* Scheduling window */}
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-1">Scheduling window</h3>
        <p className="text-xs text-gray-400 mb-4">Scheduled jobs run one at a time inside a nightly window, ordered by request time (priority users first). Whatever doesn't finish carries over to the next night.</p>
        {app && (
          <>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Window start hour (local, 0–23)</label>
                <input type="number" min={0} max={23} value={app.schedule_window_start_hour}
                  onChange={e => setApp({ ...app, schedule_window_start_hour: Math.min(23, Math.max(0, parseInt(e.target.value) || 0)) })} className={inputCls} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Window duration (hours)</label>
                <input type="number" min={1} max={24} value={app.schedule_window_duration_hours}
                  onChange={e => setApp({ ...app, schedule_window_duration_hours: Math.min(24, Math.max(1, parseInt(e.target.value) || 1)) })} className={inputCls} />
              </div>
            </div>
            <div className="mt-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">Mode</label>
              <select value={app.schedule_mode} onChange={e => setApp({ ...app, schedule_mode: e.target.value as AppSettings['schedule_mode'] })} className={inputCls}>
                <option value="both">Both — the user chooses immediate or scheduled</option>
                <option value="scheduled">Scheduled only — every job runs in the window</option>
                <option value="immediate">Immediate only — every job runs now</option>
              </select>
              <p className="text-xs text-gray-400 mt-1">Drives exactly the buttons the user sees in the portal. Per-frontend override in the Frontends tab.</p>
            </div>
            <button onClick={saveApp} disabled={saving} className="mt-4 bg-uni-blue text-white rounded-lg px-5 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50">
              {saving ? 'Saving…' : 'Save scheduling settings'}
            </button>
          </>
        )}
      </div>

      {/* Email / SMTP */}
      <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-800 mb-1">Email server (SMTP)</h3>
        <p className="text-xs text-gray-400 mb-4">Sends the access code and the translation-ready email (with the download link). No notifications are configured — the admin isn't emailed and the user always receives their result.</p>
        {smtp && (
          <>
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">SMTP Host</label>
                <input value={smtp.host} onChange={e => smtpField('host', e.target.value)} placeholder="smtp.example.com" className={inputCls} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Port</label>
                <input type="number" value={smtp.port} onChange={e => smtpField('port', parseInt(e.target.value) || 587)} className={inputCls} />
                <p className="text-xs text-gray-400 mt-1">587 for TLS, 465 for SSL, 25 unencrypted</p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                <input value={smtp.username} onChange={e => smtpField('username', e.target.value)} placeholder="user@example.com" className={inputCls} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                <input type="password" value={smtp.password} onChange={e => smtpField('password', e.target.value)} className={inputCls} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">From Address</label>
                <input type="email" value={smtp.from_address} onChange={e => smtpField('from_address', e.target.value)} placeholder="translator@example.com" className={inputCls} />
              </div>
            </div>
            <label className="flex items-center gap-2 cursor-pointer mb-6">
              <input type="checkbox" checked={smtp.use_tls} onChange={e => smtpField('use_tls', e.target.checked)} className="rounded border-gray-300 text-uni-blue focus:ring-uni-blue" />
              <span className="text-sm text-gray-700">Use TLS encryption</span>
            </label>
            <div className="flex items-center gap-3">
              <button onClick={saveSmtp} disabled={saving} className="bg-uni-blue text-white rounded-lg px-5 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50">
                {saving ? 'Saving…' : 'Save email settings'}
              </button>
              <button onClick={test} disabled={testing || !smtp.host} className="border border-gray-300 text-gray-600 rounded-lg px-4 py-2 text-sm font-medium hover:bg-gray-50 disabled:opacity-50">
                {testing ? 'Testing…' : 'Test connection'}
              </button>
              {success && <span className="text-sm text-green-600">{success}</span>}
              {error && <span className="text-sm text-uni-red">{error}</span>}
            </div>
            {testResult && (
              <div className={`mt-4 p-3 rounded-lg text-sm ${testResult.status === 'ok' ? 'bg-green-50 text-green-700' : testResult.status === 'warning' ? 'bg-yellow-50 text-yellow-700' : 'bg-red-50 text-red-700'}`}>
                {testResult.message}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
