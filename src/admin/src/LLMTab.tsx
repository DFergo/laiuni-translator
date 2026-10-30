import { useState, useEffect, useRef } from 'react'
import {
  getLLMHealth, getLLMSettings, updateLLMSettings, resetLLMSettings,
  listFrontends, getFrontendLLMSettings, updateFrontendLLMSettings, deleteFrontendLLMSettings,
  listConnections, addConnection, updateConnection, deleteConnection, getConnectionModels,
  getSlotCapabilities, getLLMUsage, resetLLMUsage,
  type LLMHealth, type LLMSettings, type LLMConnection, type ConnectionType, type Frontend,
  type SlotCapabilities, type ControlStatus, type ReasoningLevel, type ReasoningSetting, type LLMUsageRow,
} from './api'
import ModelCombobox from './ModelCombobox'

type SlotKey = 'inference' | 'reporter' | 'summariser' | 'translation'

const CONNECTION_TYPES: { value: ConnectionType; label: string }[] = [
  { value: 'openai', label: 'OpenAI-compatible' },
  { value: 'anthropic', label: 'Anthropic (native)' },
  { value: 'ollama', label: 'Ollama (native)' },
]

const inputCls = 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-uni-blue focus:border-transparent outline-none'

// ---------------------------------------------------------------------------
// Reusable slot editor: connection → model (searchable, free ID allowed) + optional params
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
  const connKey = `${slot}_connection` as keyof LLMSettings
  const modelKey = `${slot}_model` as keyof LLMSettings
  const tempKey = `${slot}_temperature` as keyof LLMSettings
  const maxKey = `${slot}_max_tokens` as keyof LLMSettings
  const ctxKey = `${slot}_num_ctx` as keyof LLMSettings
  const reasonKey = `${slot}_reasoning` as keyof LLMSettings

  const eff = (key: keyof LLMSettings): unknown =>
    isOverride ? (override![key] ?? settings[key]) : settings[key]
  const has = (key: keyof LLMSettings) => isOverride && override![key] != null

  const connId = (eff(connKey) as string) || ''
  const conn = connections.find(c => c.id === connId)
  const allow = conn?.model_ids || []
  const discovered = health?.connections?.[connId]?.models || []
  const models = allow.length ? allow : discovered
  const currentModel = (eff(modelKey) as string) || ''
  // With an allow-list, the endpoint's other models stay selectable by exact ID
  const extraModels = allow.length ? discovered.filter(m => !allow.includes(m)) : []
  const isAnthropic = conn?.type === 'anthropic'
  const isOllama = conn?.type === 'ollama'

  // Sprint 21: ask the backend which controls apply to this connection + model,
  // with the values being edited, so no setting is a silent no-op.
  const [caps, setCaps] = useState<SlotCapabilities | null>(null)
  const capsInput = JSON.stringify({
    connection: connId, model: currentModel,
    temperature: (eff(tempKey) as number | null) ?? null, max_tokens: (eff(maxKey) as number | null) ?? null,
    num_ctx: (eff(ctxKey) as number | null) ?? null, reasoning: (eff(reasonKey) as ReasoningSetting | null) ?? null,
  })
  useEffect(() => {
    if (!connId) { setCaps(null); return }
    const t = setTimeout(() => {
      getSlotCapabilities(JSON.parse(capsInput)).then(setCaps).catch(() => setCaps(null))
    }, 400)
    return () => clearTimeout(t)
  }, [capsInput, connId])

  const statusLine = (st?: ControlStatus) => {
    if (!st || (st.status === 'sent' && !st.note) || st.status === 'not sent (default)') return null
    const color = st.status === 'ignored' ? 'text-amber-600' : 'text-gray-500'
    return <p className={`text-xs mt-1 ${color}`}>{st.status === 'ignored' ? 'Ignored: ' : ''}{st.note}</p>
  }

  const resetLink = (key: keyof LLMSettings, globalLabel: string) =>
    isOverride ? (
      has(key)
        ? <button onClick={() => onSet(key, null)} className="ml-2 text-xs text-gray-400 hover:text-uni-red">reset</button>
        : <span className="ml-2 text-xs text-gray-400">(global: {globalLabel})</span>
    ) : null

  const numField = (key: keyof LLMSettings, label: string, help: string, status?: ControlStatus, placeholder?: string) => {
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
          placeholder={isOverride ? String(globalVal ?? 'default') : (placeholder ?? 'provider default')}
          onChange={e => onSet(key, e.target.value === '' ? null : Number(e.target.value))}
          className={inputCls}
        />
        <p className="text-xs text-gray-400 mt-1">{help}</p>
        {statusLine(status)}
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
            <option value="">— select a connection —</option>
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
          <ModelCombobox
            key={connId}
            value={currentModel}
            models={models}
            extra={extraModels}
            onChange={id => onSet(modelKey, id)}
            emptyHint="No models discovered on this connection — type the model ID, or use “Test / fetch models” on the connection."
          />
        </div>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {numField(tempKey, 'Temperature', '0 = deterministic; 0.1 recommended for translation.', caps?.controls.temperature)}
        {numField(maxKey, 'Max Tokens', maxTokensHelp, caps?.controls.max_tokens)}
        {isOllama
          ? numField(ctxKey, 'Context Window (num_ctx)', 'Sent to Ollama. Blank = model default.')
          : (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Context window</label>
              <p className="text-sm text-gray-700 py-2">{caps?.context_length ? caps.context_length.toLocaleString() + ' tokens' : '—'}</p>
              <p className="text-xs text-gray-400 mt-1">Declared by the provider for this model. Not a request parameter here.</p>
            </div>
          )}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Reasoning{resetLink(reasonKey, String(settings[reasonKey] ?? 'off'))}
          </label>
          <select
            value={(eff(reasonKey) as string | null) ?? 'off'}
            onChange={e => onSet(reasonKey, e.target.value)}
            className={inputCls}
          >
            <option value="default">Provider default</option>
            {(['off', 'low', 'medium', 'high'] as ReasoningLevel[]).map(lv => (
              <option key={lv} value={lv} disabled={!!caps && !(caps.controls.reasoning.options ?? []).includes(lv)}>
                {lv}{lv === 'off' ? ' (recommended)' : ''}{caps && !(caps.controls.reasoning.options ?? []).includes(lv) ? ' (not available)' : ''}
              </option>
            ))}
          </select>
          <p className="text-xs text-gray-400 mt-1">
            {caps ? `${caps.provider_label}. ` : ''}Reasoning tokens are billed and count against Max Tokens; a reasoning pass can leave a chunk empty.
          </p>
          {statusLine(caps?.controls.reasoning)}
        </div>
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
    if (!confirm(`Delete connection "${id}"? The engine will stop working until reassigned.`)) return
    await deleteConnection(id)
    await reload(); await refreshHealth()
  }

  const dot = (status?: string) => status === 'online' ? 'bg-green-500' : status === 'offline' ? 'bg-red-500' : 'bg-gray-300'

  return (
    <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-800">Provider Connections</h3>
          <p className="text-xs text-gray-400">OpenAI-compatible, Anthropic, or Ollama endpoints. Models are auto-discovered on save; the engine below picks one.</p>
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
                    {h ? (h.status === 'online' ? `${h.models.length} model(s)` : 'offline') : `${(c.model_ids || []).length || ''} ${(c.model_ids || []).length ? 'model(s)' : ''}`}
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
            placeholder="e.g. omlx, openrouter, claude-prod"
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
          placeholder="blank = auto-discover all models on save" className={inputCls} />
      </div>
      {draft.type === 'openai' && (
        <details className="text-sm" open={!!(draft.provider || draft.prompt_cache_key || Object.keys(draft.routing || {}).length)}>
          <summary className="cursor-pointer text-xs text-gray-500 select-none">Provider options (optional)</summary>
          <div className="grid grid-cols-2 gap-3 mt-2">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Provider profile</label>
              <select value={draft.provider || ''} onChange={e => set('provider', e.target.value)} className={inputCls}>
                <option value="">Auto (from the address)</option>
                <option value="mistral">Mistral API</option>
                <option value="openrouter">OpenRouter</option>
                <option value="openai">OpenAI</option>
                <option value="openai_compatible">Other OpenAI-compatible (oMLX, LM Studio, vLLM…)</option>
              </select>
              <p className="text-xs text-gray-400 mt-1">Decides which request fields are sent and how reasoning is controlled.</p>
            </div>
            <div>
              <label className="flex items-center gap-2 text-xs text-gray-600 mt-5">
                <input type="checkbox" checked={!!draft.prompt_cache_key} onChange={e => set('prompt_cache_key', e.target.checked)} />
                Send a per-job prompt cache key
              </label>
              <p className="text-xs text-gray-400 mt-1">A hash of the job, never the job id. For providers that use it to keep a job on one cache.</p>
            </div>
          </div>
          <RoutingField value={draft.routing || {}} onChange={v => set('routing', v)} />
        </details>
      )}
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

// OpenRouter `provider` routing object, edited as JSON (applied on blur when valid).
function RoutingField({ value, onChange }: { value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void }) {
  const [text, setText] = useState(Object.keys(value).length ? JSON.stringify(value) : '')
  const [bad, setBad] = useState(false)
  const apply = () => {
    if (!text.trim()) { setBad(false); onChange({}); return }
    try {
      const parsed = JSON.parse(text)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) { setBad(false); onChange(parsed) } else setBad(true)
    } catch { setBad(true) }
  }
  return (
    <div className="mt-3">
      <label className="block text-xs font-medium text-gray-600 mb-1">OpenRouter routing (JSON)</label>
      <input value={text} onChange={e => setText(e.target.value)} onBlur={apply} spellCheck={false}
        placeholder='{"order": ["alibaba"], "allow_fallbacks": false}' className={`${inputCls} font-mono`} />
      <p className={`text-xs mt-1 ${bad ? 'text-uni-red' : 'text-gray-400'}`}>
        {bad ? 'Not a valid JSON object — not applied.'
          : 'Sent as OpenRouter\u2019s "provider" object, e.g. to keep every call of a job on one endpoint.'}
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Token and prompt-cache usage (Sprint 21)
// ---------------------------------------------------------------------------

function UsageCard() {
  const [rows, setRows] = useState<LLMUsageRow[] | null>(null)
  const load = () => getLLMUsage().then(r => setRows(r.rows)).catch(() => setRows([]))
  useEffect(() => { load() }, [])
  const fmt = (n: number) => n.toLocaleString()
  return (
    <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-lg font-semibold text-gray-800">Usage and prompt cache</h3>
        <div className="flex gap-2">
          <button onClick={load} className="text-xs px-3 py-1 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50">Refresh</button>
          <button onClick={() => { if (confirm('Reset the usage counters?')) resetLLMUsage().then(r => setRows(r.rows)) }}
            className="text-xs px-3 py-1 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50">Reset</button>
        </div>
      </div>
      <p className="text-xs text-gray-400 mb-4">
        Tokens reported by the provider for every translation call, since the last reset. Cache hit rate = cached prompt
        tokens / prompt tokens (the translation instructions repeat on every unit, so they can be cached on providers that
        cache automatically). "—" means the provider reports no usage (or no cache figure, e.g. Ollama). Per-job figures
        are logged when each job finishes.
      </p>
      {!rows ? <p className="text-sm text-gray-400">Loading…</p> : rows.length === 0 ? (
        <p className="text-sm text-gray-400">No calls recorded yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-200">
                <th className="py-1 pr-3">Slot</th><th className="py-1 pr-3">Connection / model</th>
                <th className="py-1 pr-3 text-right">Calls</th><th className="py-1 pr-3 text-right">Prompt</th>
                <th className="py-1 pr-3 text-right">Cached</th><th className="py-1 pr-3 text-right">Hit rate</th>
                <th className="py-1 pr-3 text-right">Completion</th><th className="py-1 text-right">Reasoning</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={`${r.slot}|${r.connection}|${r.model}`} className="border-b border-gray-100">
                  <td className="py-1 pr-3">{r.slot}</td>
                  <td className="py-1 pr-3 font-mono">{r.connection} / {r.model}</td>
                  <td className="py-1 pr-3 text-right">{fmt(r.calls)}</td>
                  <td className="py-1 pr-3 text-right">{r.calls_with_usage ? fmt(r.prompt_tokens) : '—'}</td>
                  <td className="py-1 pr-3 text-right">{r.calls_with_usage ? fmt(r.cached_tokens) : '—'}</td>
                  <td className="py-1 pr-3 text-right font-medium">{r.hit_rate == null ? '—' : `${(r.hit_rate * 100).toFixed(1)} %`}</td>
                  <td className="py-1 pr-3 text-right">{r.calls_with_usage ? fmt(r.completion_tokens) : '—'}</td>
                  <td className="py-1 text-right">{r.calls_with_usage ? fmt(r.reasoning_tokens) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main tab — single translation engine (Sprint 9 / ADR-010)
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

  const refreshHealth = async () => {
    try { setHealth(await getLLMHealth()) }
    catch (err) { setError(err instanceof Error ? err.message : 'Failed to load health') }
  }
  const reloadConnections = async () => {
    try { setConnections((await listConnections()).connections) } catch { /* ignore */ }
  }
  const loadAll = async () => {
    try {
      const [h, s, c] = await Promise.all([getLLMHealth(), getLLMSettings(), listConnections()])
      setHealth(h); setSettings(s); setSavedSettings(s); setConnections(c.connections)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load')
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

  // Engine circuit-breaker badge (keyed connection:model)
  const engineBadge = () => {
    if (!health?.slot_health || !settings) return null
    const key = `${settings.translation_connection}:${settings.translation_model}`
    const status = health.slot_health[key]
    if (status === 'down') return <span className="ml-2 text-xs font-medium text-red-600 bg-red-50 px-2 py-0.5 rounded-full">Down</span>
    if (status === 'degraded') return <span className="ml-2 text-xs font-medium text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full">Degraded</span>
    return null
  }

  // Per-frontend engine overrides
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

  return (
    <div className="space-y-6">
      <ConnectionsCard connections={connections} health={health} reload={reloadConnections} refreshHealth={refreshHealth} />

      {settings && (
        <>
          {/* Translation engine (single) */}
          <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-1">Translation engine{engineBadge()}</h3>
            <p className="text-xs text-gray-400 mb-4">
              The single model used for every translation. Pick a connection, then search its discovered models or type an exact model ID.
            </p>
            <SlotConfig slot="translation" connections={connections} health={health} settings={settings} onSet={setField} />

            <p className="text-xs text-gray-400 mt-4 border-t border-gray-100 pt-4">
              Editable prompts live on the <span className="font-medium">Prompts</span> tab: the translation <span className="font-medium">flavour</span> (persona, per-frontend) and the UI strings. The translation <span className="font-medium">procedure</span> is fixed and not editable.
            </p>
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

          <UsageCard />

          {/* Per-frontend engine override */}
          {frontends.length > 0 && (
            <div className="bg-white rounded-xl shadow-md border border-gray-200 p-6">
              <h3 className="text-lg font-semibold text-gray-800 mb-1">Per-Frontend engine</h3>
              <p className="text-xs text-gray-400 mb-4">
                Override the engine (usually the model) for a specific frontend. Frontends without an override use the global engine above.
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
                            ? <span className="text-xs text-uni-blue font-medium">Custom engine</span>
                            : <span className="text-xs text-gray-400">Using global</span>)}
                          <button onClick={() => toggleFeOverride(f.id)}
                            className="text-xs px-3 py-1 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 font-medium">
                            {feOpen === f.id ? 'Close' : 'Configure'}
                          </button>
                        </div>
                      </div>

                      {feOpen === f.id && settings && (
                        <div className="mt-4 pt-4 border-t border-gray-200 space-y-4">
                          <SlotConfig slot="translation" connections={connections} health={health} settings={settings}
                            override={override} onSet={(k, v) => setFeField(f.id, k, v as string | number | null)} />
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
