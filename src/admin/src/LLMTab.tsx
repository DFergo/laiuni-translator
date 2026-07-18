import { useState, useEffect, useRef } from 'react'
import {
  getLLMHealth, getLLMSettings, updateLLMSettings, resetLLMSettings,
  listFrontends, getFrontendLLMSettings, updateFrontendLLMSettings, deleteFrontendLLMSettings,
  listConnections, addConnection, updateConnection, deleteConnection, getConnectionModels,
  getTranslationPrompt, updateTranslationPrompt,
  type LLMHealth, type LLMSettings, type LLMConnection, type ConnectionType, type Frontend,
} from './api'

type SlotKey = 'inference' | 'reporter' | 'summariser' | 'translation'

const CONNECTION_TYPES: { value: ConnectionType; label: string }[] = [
  { value: 'openai', label: 'OpenAI-compatible' },
  { value: 'anthropic', label: 'Anthropic (native)' },
  { value: 'ollama', label: 'Ollama (native)' },
]

const inputCls = 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none'

// ---------------------------------------------------------------------------
// Reusable slot editor: connection → model (with manual entry) + optional params
// ---------------------------------------------------------------------------

function SlotConfig({
  slot, connections, health, settings, override, onSet,
}: {
  slot: SlotKey
  connections: LLMConnection[]
  health: LLMHealth | null
  settings: LLMSettings
  override?: Partial<LLMSettings>          // present → per-frontend override mode
  onSet: (key: keyof LLMSettings, val: string | number | null) => void
}) {
  const isOverride = override !== undefined
  const [manualModel, setManualModel] = useState(false)  // user forced manual model entry
  const connKey = `${slot}_connection` as keyof LLMSettings
  const modelKey = `${slot}_model` as keyof LLMSettings
  const tempKey = `${slot}_temperature` as keyof LLMSettings
  const maxKey = `${slot}_max_tokens` as keyof LLMSettings
  const ctxKey = `${slot}_num_ctx` as keyof LLMSettings

  const eff = (key: keyof LLMSettings): unknown =>
    isOverride ? (override![key] ?? settings[key]) : settings[key]
  const has = (key: keyof LLMSettings) => isOverride && override![key] != null

  const connId = (eff(connKey) as string) || ''
  const conn = connections.find(c => c.id === connId)
  const allow = conn?.model_ids || []
  const discovered = health?.connections?.[connId]?.models || []
  const models = allow.length ? allow : discovered
  const currentModel = (eff(modelKey) as string) || ''
  const modelInList = models.includes(currentModel)
  // Manual text entry: forced by the user, or unavoidable (no models discovered,
  // or the current value isn't in the discovered list).
  const useManual = models.length === 0 || manualModel || (currentModel !== '' && !modelInList)
  const isAnthropic = conn?.type === 'anthropic'
  const isOllama = conn?.type === 'ollama'

  const resetLink = (key: keyof LLMSettings, globalLabel: string) =>
    isOverride ? (
      has(key)
        ? <button onClick={() => onSet(key, null)} className="ml-2 text-xs text-gray-400 hover:text-uni-red">reset</button>
        : <span className="ml-2 text-xs text-gray-400">(global: {globalLabel})</span>
    ) : null

  const numField = (key: keyof LLMSettings, label: string, help: string) => {
    const raw = isOverride ? override![key] : settings[key]
    const globalVal = settings[key]
    return (
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">
          {label}
          {resetLink(key, globalVal == null ? 'default' : String(globalVal))}
        </label>
        <input
          type="number"
          value={raw == null ? '' : (raw as number)}
          placeholder={isOverride ? String(globalVal ?? 'default') : 'provider default'}
          onChange={e => onSet(key, e.target.value === '' ? null : Number(e.target.value))}
          className={inputCls}
        />
        <p className="text-xs text-gray-400 mt-1">{help}</p>
      </div>
    )
  }

  const maxTokensHelp = isAnthropic
    ? 'Anthropic requires a value — leave blank to apply the default (4096).'
    : 'Leave blank for the provider/model default.'

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Connection{resetLink(connKey, String(settings[connKey]))}
          </label>
          <select
            value={connId}
            onChange={e => onSet(connKey, e.target.value)}
            className={inputCls}
          >
            {!connections.some(c => c.id === connId) && connId && (
              <option value={connId}>{connId} (missing)</option>
            )}
            {connections.map(c => (
              <option key={c.id} value={c.id} disabled={!c.enable}>
                {c.id} ({c.type}){c.enable ? '' : ' — disabled'}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Model{resetLink(modelKey, String(settings[modelKey]))}
          </label>
          {models.length > 0 && (
            <select
              value={modelInList && !useManual ? currentModel : '__manual__'}
              onChange={e => {
                if (e.target.value === '__manual__') setManualModel(true)
                else { setManualModel(false); onSet(modelKey, e.target.value) }
              }}
              className={inputCls}
            >
              {models.map(m => <option key={m} value={m}>{m}</option>)}
              <option value="__manual__">✏️ Enter manually…</option>
            </select>
          )}
          {useManual && (
            <input
              type="text"
              value={currentModel}
              onChange={e => onSet(modelKey, e.target.value)}
              placeholder="model ID"
              className={`${inputCls} ${models.length > 0 ? 'mt-2' : ''}`}
            />
          )}
          {models.length === 0 && (
            <p className="text-xs text-gray-400 mt-1">No models discovered — enter the ID manually.</p>
          )}
        </div>
      </div>
      <div className={`grid ${isOllama ? 'grid-cols-3' : 'grid-cols-2'} gap-3`}>
        {numField(tempKey, 'Temperature', '0 = deterministic, ~0.7 = balanced, >1 = creative.')}
        {numField(maxKey, 'Max Tokens', maxTokensHelp)}
        {isOllama && numField(ctxKey, 'Context Window (num_ctx)', 'Ollama only. Blank = model default.')}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Connections management
// ---------------------------------------------------------------------------

const blankConn: Partial<LLMConnection> = {
  id: '', type: 'openai', base_url: '', api_key: '', prefix_id: '', model_ids: [], enable: true,
}

function ConnectionsCard({
  connections, health, reload, refreshHealth,
}: {
  connections: LLMConnection[]
  health: LLMHealth | null
  reload: () => Promise<void>
  refreshHealth: () => Promise<void>
}) {
  const [editing, setEditing] = useState<string | null>(null)  // connection id, or '__new__'
  const [draft, setDraft] = useState<Partial<LLMConnection>>(blankConn)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const startNew = () => { setEditing('__new__'); setDraft({ ...blankConn }); setErr('') }
  const startEdit = (c: LLMConnection) => { setEditing(c.id); setDraft({ ...c }); setErr('') }
  const cancel = () => { setEditing(null); setErr('') }

  const save = async () => {
    setBusy(true); setErr('')
    try {
      if (editing === '__new__') await addConnection(draft)
      else await updateConnection(editing!, draft)
      setEditing(null)
      await reload(); await refreshHealth()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Save failed')
    } finally { setBusy(false) }
  }

  const remove = async (id: string) => {
    if (!confirm(`Delete connection "${id}"? Slots still pointing at it will stop working until reassigned.`)) return
    await deleteConnection(id)
    await reload(); await refreshHealth()
  }

  const dot = (status?: string) => status === 'online' ? 'bg-green-500' : status === 'offline' ? 'bg-red-500' : 'bg-gray-300'

  return (
    <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-800">Provider Connections</h3>
          <p className="text-xs text-gray-400">OpenAI-compatible, Anthropic, or Ollama endpoints. Slots below pick a (connection, model) pair.</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={refreshHealth} className="text-xs px-3 py-1 rounded-lg border border-gray-300 text-gray-500 hover:bg-gray-50 font-medium">Refresh</button>
          <button onClick={startNew} className="text-xs px-3 py-1 rounded-lg bg-uni-blue text-white font-medium hover:opacity-90">Add connection</button>
        </div>
      </div>

      <div className="space-y-2">
        {connections.map(c => {
          const h = health?.connections?.[c.id]
          return (
            <div key={c.id} className="border border-gray-200 rounded-lg px-4 py-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`w-2.5 h-2.5 rounded-full ${dot(h?.status)}`} />
                  <div>
                    <span className="text-sm font-medium text-gray-800">{c.id}</span>
                    <span className="text-xs text-gray-400 ml-2">{c.type} · {c.base_url}</span>
                    {!c.enable && <span className="text-xs text-uni-red ml-2">disabled</span>}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-400">
                    {h ? (h.status === 'online' ? `${h.models.length} model(s)` : (h.error ? 'offline' : 'offline')) : ''}
                  </span>
                  <button onClick={() => startEdit(c)} className="text-xs px-2 py-1 rounded border border-gray-300 text-gray-600 hover:bg-gray-50">Edit</button>
                  <button onClick={() => remove(c.id)} className="text-xs px-2 py-1 rounded border border-gray-300 text-gray-400 hover:text-uni-red">Delete</button>
                </div>
              </div>

              {editing === c.id && (
                <ConnForm draft={draft} setDraft={setDraft} onSave={save} onCancel={cancel} busy={busy} err={err} isNew={false}
                  onRefreshModels={async () => { await getConnectionModels(c.id); await refreshHealth() }} />
              )}
            </div>
          )
        })}
      </div>

      {editing === '__new__' && (
        <div className="border border-uni-blue/40 rounded-lg px-4 py-3 mt-2">
          <ConnForm draft={draft} setDraft={setDraft} onSave={save} onCancel={cancel} busy={busy} err={err} isNew />
        </div>
      )}
    </div>
  )
}

function ConnForm({
  draft, setDraft, onSave, onCancel, busy, err, isNew, onRefreshModels,
}: {
  draft: Partial<LLMConnection>
  setDraft: (d: Partial<LLMConnection>) => void
  onSave: () => void
  onCancel: () => void
  busy: boolean
  err: string
  isNew: boolean
  onRefreshModels?: () => void
}) {
  const set = (k: keyof LLMConnection, v: unknown) => setDraft({ ...draft, [k]: v })
  return (
    <div className="mt-3 pt-3 border-t border-gray-200 space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">ID</label>
          <input value={draft.id || ''} disabled={!isNew}
            onChange={e => set('id', e.target.value)}
            placeholder="e.g. openrouter, claude-prod"
            className={`${inputCls} ${!isNew ? 'bg-gray-50 text-gray-400' : ''}`} />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Type</label>
          <select value={draft.type} onChange={e => set('type', e.target.value)} className={inputCls}>
            {CONNECTION_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Base URL</label>
        <input value={draft.base_url || ''} onChange={e => set('base_url', e.target.value)}
          placeholder={draft.type === 'anthropic' ? 'https://api.anthropic.com' : draft.type === 'ollama' ? 'http://host.docker.internal:11434' : 'http://host.docker.internal:1234/v1'}
          className={inputCls} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">API Key</label>
          <input type="password" value={draft.api_key || ''} onChange={e => set('api_key', e.target.value)}
            placeholder={draft.type === 'ollama' ? '(usually none)' : 'sk-...'} className={inputCls} />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Prefix ID (optional)</label>
          <input value={draft.prefix_id || ''} onChange={e => set('prefix_id', e.target.value)} className={inputCls} />
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Model allowlist (optional, comma-separated)</label>
        <input value={(draft.model_ids || []).join(', ')}
          onChange={e => set('model_ids', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
          placeholder="blank = auto-discover all models" className={inputCls} />
      </div>
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 cursor-pointer">
          <div className={`relative w-10 h-5 rounded-full transition-colors ${draft.enable ? 'bg-uni-blue' : 'bg-gray-300'}`}
            onClick={() => set('enable', !draft.enable)}>
            <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${draft.enable ? 'translate-x-5' : 'translate-x-0.5'}`} />
          </div>
          <span className="text-xs text-gray-600">Enabled</span>
        </label>
        <div className="flex-1" />
        {onRefreshModels && <button onClick={onRefreshModels} className="text-xs text-gray-400 hover:text-uni-blue">Test / fetch models</button>}
        <button onClick={onSave} disabled={busy} className="bg-uni-blue text-white rounded-lg px-4 py-1.5 text-sm font-medium hover:opacity-90 disabled:opacity-50">
          {busy ? 'Saving...' : 'Save'}
        </button>
        <button onClick={onCancel} className="text-xs text-gray-400 hover:text-gray-600 px-2">Cancel</button>
      </div>
      {err && <p className="text-xs text-uni-red">{err}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main tab
// ---------------------------------------------------------------------------

export default function LLMTab() {
  const [health, setHealth] = useState<LLMHealth | null>(null)
  const [settings, setSettings] = useState<LLMSettings | null>(null)
  const [savedSettings, setSavedSettings] = useState<LLMSettings | null>(null)
  const [connections, setConnections] = useState<LLMConnection[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const dirty = useRef(false)

  // Translation prompt (Sprint 20; editable, disk source-of-truth)
  const [translatePrompt, setTranslatePrompt] = useState('')
  const [translatePromptSaved, setTranslatePromptSaved] = useState('')
  const [translatePromptMsg, setTranslatePromptMsg] = useState('')

  const refreshHealth = async () => {
    try { setHealth(await getLLMHealth()) }
    catch (err) { setError(err instanceof Error ? err.message : 'Failed to load health') }
  }

  const reloadConnections = async () => {
    try { setConnections((await listConnections()).connections) } catch { /* ignore */ }
  }

  const loadAll = async () => {
    try {
      const [h, s, c, tp] = await Promise.all([getLLMHealth(), getLLMSettings(), listConnections(), getTranslationPrompt()])
      setHealth(h); setSettings(s); setSavedSettings(s); setConnections(c.connections)
      setTranslatePrompt(tp.prompt); setTranslatePromptSaved(tp.prompt)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load')
    }
  }

  const handleSaveTranslatePrompt = async () => {
    try {
      const { prompt } = await updateTranslationPrompt(translatePrompt)
      setTranslatePromptSaved(prompt)
      setTranslatePromptMsg('Prompt saved'); setTimeout(() => setTranslatePromptMsg(''), 3000)
    } catch (err) {
      setTranslatePromptMsg(err instanceof Error ? err.message : 'Save failed')
    }
  }

  const handleReloadTranslatePrompt = async () => {
    if (translatePrompt !== translatePromptSaved && !confirm('Reload from disk and discard unsaved changes?')) return
    try {
      const { prompt } = await getTranslationPrompt()
      setTranslatePrompt(prompt); setTranslatePromptSaved(prompt)
      setTranslatePromptMsg('Reloaded from disk'); setTimeout(() => setTranslatePromptMsg(''), 3000)
    } catch (err) {
      setTranslatePromptMsg(err instanceof Error ? err.message : 'Reload failed')
    }
  }

  useEffect(() => {
    loadAll()
    const interval = setInterval(refreshHealth, 15000)
    return () => clearInterval(interval)
  }, [])

  const handleSave = async () => {
    if (!settings) return
    setSaving(true); setError(''); setSuccess('')
    try {
      const updated = await updateLLMSettings(settings)
      setSettings(updated); setSavedSettings(updated); dirty.current = false
      setSuccess('Settings saved'); setTimeout(() => setSuccess(''), 3000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally { setSaving(false) }
  }

  const handleReset = async () => {
    setError(''); setSuccess('')
    try {
      const defaults = await resetLLMSettings()
      setSettings(defaults); setSavedSettings(defaults); dirty.current = false
      setSuccess('Settings reset to defaults'); setTimeout(() => setSuccess(''), 3000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reset failed')
    }
  }

  const handleDiscard = () => {
    if (savedSettings) { setSettings({ ...savedSettings }); dirty.current = false }
  }

  const setField = (key: keyof LLMSettings, value: string | number | null | boolean) => {
    if (!settings) return
    dirty.current = true
    setSettings({ ...settings, [key]: value })
  }

  // Per-slot circuit-breaker badge (keyed connection:model)
  const slotBadge = (slot: SlotKey) => {
    if (!health?.slot_health || !settings) return null
    const key = `${settings[`${slot}_connection`]}:${settings[`${slot}_model`]}`
    const status = health.slot_health[key]
    if (status === 'down') return <span className="ml-2 text-xs font-medium text-red-600 bg-red-50 px-2 py-0.5 rounded-full">Down</span>
    if (status === 'degraded') return <span className="ml-2 text-xs font-medium text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full">Degraded</span>
    return null
  }

  // Per-frontend overrides
  const [frontends, setFrontends] = useState<Frontend[]>([])
  const [feOverrides, setFeOverrides] = useState<Record<string, Partial<LLMSettings>>>({})
  const [feOpen, setFeOpen] = useState<string | null>(null)
  const [feSaving, setFeSaving] = useState(false)
  const [feSuccess, setFeSuccess] = useState('')

  useEffect(() => {
    listFrontends().then(({ frontends: list }) => setFrontends(list)).catch(() => {})
  }, [])

  const toggleFeOverride = async (fid: string) => {
    if (feOpen === fid) { setFeOpen(null); return }
    try {
      const { override } = await getFrontendLLMSettings(fid)
      setFeOverrides(prev => ({ ...prev, [fid]: override }))
      setFeOpen(fid)
    } catch { /* ignore */ }
  }

  const setFeField = (fid: string, key: keyof LLMSettings, value: string | number | null) => {
    setFeOverrides(prev => {
      const copy = { ...prev[fid] }
      if (value === null) delete copy[key]
      else (copy as Record<string, unknown>)[key] = value
      return { ...prev, [fid]: copy }
    })
  }

  const handleFeSave = async (fid: string) => {
    setFeSaving(true)
    try {
      await updateFrontendLLMSettings(fid, feOverrides[fid] || {})
      setFeSuccess('Saved'); setTimeout(() => setFeSuccess(''), 3000)
    } catch { /* ignore */ } finally { setFeSaving(false) }
  }

  const handleFeReset = async (fid: string) => {
    try {
      await deleteFrontendLLMSettings(fid)
      setFeOverrides(prev => ({ ...prev, [fid]: {} }))
      setFeSuccess('Reset to global'); setTimeout(() => setFeSuccess(''), 3000)
    } catch { /* ignore */ }
  }

  const statusDot = (status: string) => status === 'online' ? 'bg-green-500' : 'bg-red-500'

  const toggle = (on: boolean, onClick: () => void) => (
    <div className={`relative w-10 h-5 rounded-full transition-colors flex-shrink-0 ${on ? 'bg-uni-blue' : 'bg-gray-300'}`} onClick={onClick}>
      <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${on ? 'translate-x-5' : 'translate-x-0.5'}`} />
    </div>
  )

  return (
    <div className="space-y-6">
      <ConnectionsCard connections={connections} health={health} reload={reloadConnections} refreshHealth={refreshHealth} />

      {settings && (
        <>
          {/* Inference */}
          <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-1">Inference{slotBadge('inference')}</h3>
            <p className="text-xs text-gray-400 mb-4">Main LLM that responds to users in chat conversations.</p>
            <SlotConfig slot="inference" connections={connections} health={health} settings={settings} onSet={setField} />
            <div className="border-t border-gray-200 pt-4 mt-4">
              <label className="flex items-start gap-3 cursor-pointer">
                {toggle(settings.multimodal_enabled, () => setField('multimodal_enabled', !settings.multimodal_enabled))}
                <div>
                  <span className="text-sm font-medium text-gray-700">Analyse uploaded images with the inference model</span>
                  <p className="text-xs text-gray-400">
                    Only enable if the selected inference model supports vision (e.g. Gemma 3/4, Qwen2.5-VL, llava).
                    When on, every uploaded JPG/PNG is described by the inference model at upload time and added to the case evidence.
                    When off (default), images are stored without analysis.
                  </p>
                </div>
              </label>
            </div>
          </div>

          {/* Reporter */}
          <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-1">Reporter{slotBadge('reporter')}</h3>
            <p className="text-xs text-gray-400 mb-4">
              Dedicated LLM for structured internal documents (case file + UNI summary). Use a model specialised for long, factual output.
            </p>
            <SlotConfig slot="reporter" connections={connections} health={health} settings={settings} onSet={setField} />
            <div className="border-t border-gray-200 pt-4 mt-4">
              <label className="flex items-center gap-3 cursor-pointer">
                {toggle(settings.use_reporter_for_user_summary, () => setField('use_reporter_for_user_summary', !settings.use_reporter_for_user_summary))}
                <div>
                  <span className="text-sm font-medium text-gray-700">Use reporter for user-facing summary</span>
                  <p className="text-xs text-gray-400">
                    When off (default), the user summary is generated by the inference model — faster and more conversational.
                    Internal documents always use the reporter model regardless of this toggle.
                  </p>
                </div>
              </label>
            </div>
          </div>

          {/* Context Compression (summariser) */}
          <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-lg font-semibold text-gray-800">Context Compression{slotBadge('summariser')}</h3>
              <label className="flex items-center gap-2 cursor-pointer">
                <span className="text-xs text-gray-500">{settings.summariser_enabled ? 'Enabled' : 'Disabled'}</span>
                {toggle(settings.summariser_enabled, () => setField('summariser_enabled', !settings.summariser_enabled))}
              </label>
            </div>
            <p className="text-xs text-gray-400 mb-4">
              Incrementally compresses conversation history to prevent context overflow. Uses a separate, smaller LLM to summarise older messages.
              {!settings.summariser_enabled && ' When disabled, long conversations may be truncated by the inference model.'}
            </p>
            {settings.summariser_enabled && (
              <div className="space-y-4">
                <SlotConfig slot="summariser" connections={connections} health={health} settings={settings} onSet={setField} />
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      First Compression ({(settings.compression_first_threshold ?? 20000).toLocaleString()} tokens)
                    </label>
                    <input type="range" min="10000" max="50000" step="5000"
                      value={settings.compression_first_threshold ?? 20000}
                      onChange={e => setField('compression_first_threshold', parseInt(e.target.value))}
                      className="w-full" />
                    <p className="text-xs text-gray-400 mt-1">First compression triggers when context reaches this token count.</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Compression Step ({(settings.compression_step_size ?? 15000).toLocaleString()} tokens)
                    </label>
                    <input type="range" min="10000" max="50000" step="5000"
                      value={settings.compression_step_size ?? 15000}
                      onChange={e => setField('compression_step_size', parseInt(e.target.value))}
                      className="w-full" />
                    <p className="text-xs text-gray-400 mt-1">After the first, compress again every {((settings.compression_step_size ?? 15000) / 1000).toFixed(0)}k tokens.</p>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Translation (Sprint 20) */}
          <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-1">Translation{slotBadge('translation')}</h3>
            <p className="text-xs text-gray-400 mb-4">
              Translates per-frontend <span className="font-medium">disclaimer</span> and <span className="font-medium">instructions</span> into the app languages. Edit the English source in the Frontends tab; this slot generates the translations.
            </p>
            <SlotConfig slot="translation" connections={connections} health={health} settings={settings} onSet={setField} />

            <div className="border-t border-gray-200 pt-4 mt-4">
              <label className="flex items-start gap-3 cursor-pointer">
                {toggle(settings.translation_glossary_enabled, () => setField('translation_glossary_enabled', !settings.translation_glossary_enabled))}
                <div>
                  <span className="text-sm font-medium text-gray-700">Inject glossary (filtered to the target language)</span>
                  <p className="text-xs text-gray-400">
                    When on, canonical term translations from the Knowledge glossary are added to the prompt for each language, so domain terms use the union's preferred wording.
                  </p>
                </div>
              </label>
            </div>

            <div className="border-t border-gray-200 pt-4 mt-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">Translation prompt</label>
              <p className="text-xs text-gray-400 mb-2">
                Guides the model's tone and terminology. Source of truth is on disk (<code>/app/data/prompts/translate.md</code>); editable here or directly on the server.
              </p>
              <textarea
                value={translatePrompt}
                onChange={e => setTranslatePrompt(e.target.value)}
                rows={12}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none"
              />
              <div className="flex items-center gap-3 mt-2">
                <button
                  onClick={handleSaveTranslatePrompt}
                  disabled={translatePrompt === translatePromptSaved}
                  className="bg-uni-blue text-white rounded-lg px-4 py-1.5 text-sm font-medium hover:opacity-90 disabled:opacity-50"
                >
                  Save Prompt
                </button>
                <button onClick={handleReloadTranslatePrompt} className="text-xs text-gray-500 hover:text-uni-blue" title="Re-read from disk (picks up edits made on the server)">Reload from disk</button>
                {translatePrompt !== translatePromptSaved && (
                  <button onClick={() => setTranslatePrompt(translatePromptSaved)} className="text-xs text-gray-400 hover:text-gray-600">Discard</button>
                )}
                {translatePromptMsg && <span className="text-xs text-green-600">{translatePromptMsg}</span>}
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3">
            <button onClick={handleSave} disabled={saving}
              className="bg-uni-blue text-white rounded-lg px-5 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50">
              {saving ? 'Saving...' : 'Save Settings'}
            </button>
            <button onClick={handleDiscard} className="border border-gray-300 text-gray-600 rounded-lg px-4 py-2 text-sm font-medium hover:bg-gray-50">
              Discard Changes
            </button>
            <button onClick={handleReset} className="text-xs text-gray-400 hover:text-uni-red px-2 py-2">Reset to Defaults</button>
            {success && <span className="text-sm text-green-600">{success}</span>}
            {error && <span className="text-sm text-uni-red">{error}</span>}
          </div>

          {/* Per-Frontend LLM overrides */}
          {frontends.length > 0 && (
            <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
              <h3 className="text-lg font-semibold text-gray-800 mb-1">Per-Frontend LLM</h3>
              <p className="text-xs text-gray-400 mb-4">
                Override slots for specific frontends. Frontends without overrides use the global settings above.
              </p>
              <div className="space-y-3">
                {frontends.map(f => {
                  const override = feOverrides[f.id] || {}
                  const hasOverride = Object.keys(override).length > 0
                  return (
                    <div key={f.id} className="border border-gray-200 rounded-lg px-4 py-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <div className={`w-2.5 h-2.5 rounded-full ${statusDot(f.status)}`} />
                          <div>
                            <span className="text-sm font-medium text-gray-800">{f.name}</span>
                            <span className="text-xs text-gray-400 ml-2">{f.url}</span>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          {feOpen !== f.id && (hasOverride
                            ? <span className="text-xs text-uni-blue font-medium">Custom LLM</span>
                            : <span className="text-xs text-gray-400">Using global</span>)}
                          <button onClick={() => toggleFeOverride(f.id)}
                            className="text-xs px-3 py-1 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 font-medium">
                            {feOpen === f.id ? 'Close' : 'Configure'}
                          </button>
                        </div>
                      </div>

                      {feOpen === f.id && settings && (
                        <div className="mt-4 pt-4 border-t border-gray-200 space-y-4">
                          <div>
                            <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Inference</div>
                            <SlotConfig slot="inference" connections={connections} health={health} settings={settings}
                              override={override} onSet={(k, v) => setFeField(f.id, k, v as string | number | null)} />
                          </div>
                          <div className="pt-3 border-t border-gray-100">
                            <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Reporter</div>
                            <SlotConfig slot="reporter" connections={connections} health={health} settings={settings}
                              override={override} onSet={(k, v) => setFeField(f.id, k, v as string | number | null)} />
                          </div>
                          <div className="flex items-center gap-3">
                            <button onClick={() => handleFeSave(f.id)} disabled={feSaving}
                              className="bg-uni-blue text-white rounded-lg px-4 py-1.5 text-sm font-medium hover:opacity-90 disabled:opacity-50">
                              {feSaving ? 'Saving...' : 'Save Override'}
                            </button>
                            <button onClick={() => handleFeReset(f.id)} className="text-xs text-gray-400 hover:text-uni-red px-2">
                              Remove Override (use global)
                            </button>
                            {feSuccess && feOpen === f.id && <span className="text-xs text-green-600">{feSuccess}</span>}
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
