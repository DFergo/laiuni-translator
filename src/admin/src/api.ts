const API_BASE = '';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem('hrdd_admin_token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: 'Request failed' }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }

  return res.json();
}

async function downloadZip(path: string, filename: string): Promise<void> {
  const token = localStorage.getItem('hrdd_admin_token');
  const res = await fetch(`${API_BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new Error(`Export failed (HTTP ${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; document.body.appendChild(a); a.click();
  a.remove(); URL.revokeObjectURL(url);
}

async function uploadZip<T>(path: string, file: File): Promise<T> {
  const token = localStorage.getItem('hrdd_admin_token');
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({ detail: 'Import failed' }));
    throw new Error(b.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// --- Export / import (Sprint 24) ---
export const exportFrontend = (fid: string, name: string) => downloadZip(`/admin/export/frontend/${fid}`, `frontend-${name || fid}.zip`);
export const exportGlobalConfig = () => downloadZip('/admin/export/global', 'global-config.zip');
export const importFrontend = (fid: string, file: File) => uploadZip<{ imported: boolean }>(`/admin/import/frontend/${fid}`, file);
export const importFrontendFolder = (fid: string, path: string): Promise<{ imported: boolean }> =>
  request(`/admin/import/frontend/${fid}/from-folder`, { method: 'POST', body: JSON.stringify({ path }) });
export const importGlobalConfig = (file: File) => uploadZip<{ imported: boolean; note?: string }>('/admin/import/global', file);

// --- Glossary (Sprint 10) ---
export interface GlossaryCount { term_count: number; languages: string[]; per_language: Record<string, number> }
export interface GlossaryCoverage {
  base: GlossaryCount
  config?: { mode: 'append' | 'replace'; has_glossary: boolean }
  server?: GlossaryCount | null
  effective?: GlossaryCount
}
export const getGlossaryCoverage = (fid?: string): Promise<GlossaryCoverage> =>
  request(`/admin/knowledge/glossary/coverage${fid ? `?frontend_id=${fid}` : ''}`);
export const uploadGlossary = (file: File, fid?: string) =>
  uploadZip<{ terms: number; frontend_id: string | null }>(`/admin/knowledge/glossary/upload${fid ? `?frontend_id=${fid}` : ''}`, file);
export const setFrontendGlossaryMode = (fid: string, mode: 'append' | 'replace'): Promise<{ mode: string; has_glossary: boolean }> =>
  request(`/admin/knowledge/glossary/frontend/${fid}/config`, { method: 'PUT', body: JSON.stringify({ mode }) });
export const deleteFrontendGlossary = (fid: string): Promise<{ status: string }> =>
  request(`/admin/knowledge/glossary/frontend/${fid}`, { method: 'DELETE' });

// --- Admin settings (Sprint 12) ---
export interface AppSettings {
  retention_hours: number
  app_language: string
  schedule_window_start_hour: number
  schedule_window_duration_hours: number
  schedule_mode: 'scheduled' | 'immediate' | 'both'
  batch_max: number
}
export const getAppSettings = (): Promise<AppSettings> => request('/admin/settings');
export const updateAppSettings = (data: Partial<AppSettings>): Promise<AppSettings> =>
  request('/admin/settings', { method: 'PUT', body: JSON.stringify(data) });

export async function getAdminStatus(): Promise<{ setup_complete: boolean }> {
  return request('/admin/status');
}

export async function setupAdmin(password: string, confirmPassword: string): Promise<{ message: string }> {
  return request('/admin/setup', {
    method: 'POST',
    body: JSON.stringify({ password, confirm_password: confirmPassword }),
  });
}

export async function loginAdmin(password: string, rememberMe: boolean): Promise<{ token: string; expires_in: number }> {
  return request('/admin/login', {
    method: 'POST',
    body: JSON.stringify({ password, remember_me: rememberMe }),
  });
}

export async function verifyToken(): Promise<{ valid: boolean }> {
  return request('/admin/verify');
}

// --- Frontends API ---

export interface Frontend {
  id: string
  url: string
  name: string
  enabled: boolean
  status: string
  last_seen: string | null
  created_at: string
}

export async function listFrontends(): Promise<{ frontends: Frontend[] }> {
  return request('/admin/frontends');
}

export async function registerFrontend(url: string, name: string = ''): Promise<{ frontend: Frontend }> {
  return request('/admin/frontends', {
    method: 'POST',
    body: JSON.stringify({ url, name }),
  });
}

export async function updateFrontend(id: string, data: { enabled?: boolean; name?: string }): Promise<{ frontend: Frontend }> {
  return request(`/admin/frontends/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

// --- Per-frontend config (Sprint 22) ---

export interface FrontendConfig {
  configured: boolean
  app_language: string          // "" = use the global default
  auth_mode: 'token' | 'email-only'
  // Optional per-frontend scheduling overrides (null/undefined = use global Settings).
  schedule_window_start_hour?: number | null
  schedule_window_duration_hours?: number | null
  schedule_mode?: 'scheduled' | 'immediate' | 'both' | null
  batch_max?: number | null
}

export async function getFrontendConfig(id: string): Promise<{ frontend_id: string; config: FrontendConfig }> {
  return request(`/admin/frontends/${id}/config`);
}

export async function updateFrontendConfig(id: string, config: FrontendConfig): Promise<{ frontend_id: string; config: FrontendConfig }> {
  return request(`/admin/frontends/${id}/config`, { method: 'PUT', body: JSON.stringify(config) });
}

export async function listDeletedFrontends(): Promise<{ frontends: Frontend[] }> {
  return request('/admin/frontends/deleted');
}

export async function restoreFrontend(id: string): Promise<{ frontend: Frontend }> {
  return request(`/admin/frontends/${id}/restore`, { method: 'POST' });
}

export async function removeFrontend(id: string): Promise<void> {
  return request(`/admin/frontends/${id}`, { method: 'DELETE' });
}

// --- LLM API ---

export type ConnectionType = 'openai' | 'anthropic' | 'ollama'

export interface LLMConnection {
  id: string
  type: ConnectionType
  base_url: string
  api_key: string
  prefix_id: string
  model_ids: string[]
  enable: boolean
}

export interface ConnectionHealth {
  status: string
  models: string[]
  error?: string
}

export interface LLMHealth {
  connections: Record<string, ConnectionHealth>
  slot_health?: Record<string, string>
}

// Parameters are optional overrides — null/absent means "provider default".
export interface LLMSettings {
  inference_connection: string
  inference_model: string
  inference_temperature: number | null
  inference_max_tokens: number | null
  inference_num_ctx: number | null
  reporter_connection: string
  reporter_model: string
  reporter_temperature: number | null
  reporter_max_tokens: number | null
  reporter_num_ctx: number | null
  use_reporter_for_user_summary: boolean
  multimodal_enabled: boolean
  summariser_enabled: boolean
  summariser_connection: string
  summariser_model: string
  summariser_temperature: number | null
  summariser_max_tokens: number | null
  summariser_num_ctx: number | null
  translation_connection: string
  translation_model: string
  translation_temperature: number | null
  translation_max_tokens: number | null
  translation_num_ctx: number | null
  translation_glossary_enabled: boolean
  translation_enable_thinking: boolean
  compression_threshold: number
  compression_first_threshold: number
  compression_step_size: number
}

export async function getLLMHealth(): Promise<LLMHealth> {
  return request('/admin/llm/health');
}

export async function getLLMModels(): Promise<LLMHealth> {
  return request('/admin/llm/models');
}

// --- Provider connections ---

export async function listConnections(): Promise<{ connections: LLMConnection[] }> {
  return request('/admin/llm/connections');
}

export async function addConnection(data: Partial<LLMConnection>): Promise<LLMConnection> {
  return request('/admin/llm/connections', { method: 'POST', body: JSON.stringify(data) });
}

export async function updateConnection(id: string, data: Partial<LLMConnection>): Promise<LLMConnection> {
  return request(`/admin/llm/connections/${id}`, { method: 'PUT', body: JSON.stringify(data) });
}

export async function deleteConnection(id: string): Promise<{ deleted: string }> {
  return request(`/admin/llm/connections/${id}`, { method: 'DELETE' });
}

export async function getConnectionModels(id: string): Promise<{ connection_id: string } & ConnectionHealth> {
  return request(`/admin/llm/connections/${id}/models`);
}

// --- Translation prompt (Sprint 20) ---

export async function getTranslationPrompt(): Promise<{ prompt: string }> {
  return request('/admin/llm/translation-prompt');
}

export async function updateTranslationPrompt(prompt: string): Promise<{ prompt: string }> {
  return request('/admin/llm/translation-prompt', { method: 'PUT', body: JSON.stringify({ prompt }) });
}

export async function getLLMSettings(): Promise<LLMSettings> {
  return request('/admin/llm/settings');
}

export async function updateLLMSettings(data: Partial<LLMSettings>): Promise<LLMSettings> {
  return request('/admin/llm/settings', {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function resetLLMSettings(): Promise<LLMSettings> {
  return request('/admin/llm/settings/reset', { method: 'POST' });
}

// --- Per-frontend LLM overrides ---

export async function getFrontendLLMSettings(frontendId: string): Promise<{ frontend_id: string; override: Partial<LLMSettings> }> {
  return request(`/admin/frontends/${frontendId}/llm-settings`);
}

export async function updateFrontendLLMSettings(frontendId: string, data: Partial<LLMSettings>): Promise<{ frontend_id: string; override: Partial<LLMSettings> }> {
  return request(`/admin/frontends/${frontendId}/llm-settings`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteFrontendLLMSettings(frontendId: string): Promise<{ frontend_id: string; override: Record<string, never> }> {
  return request(`/admin/frontends/${frontendId}/llm-settings`, { method: 'DELETE' });
}

// --- Prompts API ---

export interface PromptFile {
  name: string
  size: number
  modified: number | null
}

export interface PromptsResponse {
  categories: Record<string, PromptFile[]>
}

export async function getPromptMode(): Promise<{ mode: string }> {
  return request('/admin/prompts/mode');
}

export async function setPromptMode(mode: string): Promise<{ mode: string }> {
  return request('/admin/prompts/mode', {
    method: 'PUT',
    body: JSON.stringify({ mode }),
  });
}

export async function copyPromptsToFrontend(frontendId: string): Promise<{ frontend_id: string; copied: number }> {
  return request(`/admin/prompts/copy-to-frontend/${frontendId}`, { method: 'POST' });
}

export async function deleteFrontendPrompts(frontendId: string): Promise<{ frontend_id: string; deleted: number }> {
  return request(`/admin/prompts/frontend/${frontendId}`, { method: 'DELETE' });
}

export async function listCustomPromptFrontends(): Promise<{ frontends: { id: string; name: string }[] }> {
  return request('/admin/prompts/custom-frontends');
}

export async function resetPrompt(name: string, frontendId?: string): Promise<{ name: string; content: string }> {
  const q = frontendId ? `?frontend_id=${frontendId}` : '';
  return request(`/admin/prompts/${encodeURIComponent(name)}/reset${q}`, { method: 'POST' });
}

export async function resetGlobalPrompts(): Promise<{ reset: number }> {
  return request('/admin/prompts/reset-global', { method: 'POST' });
}

export async function listPrompts(frontendId?: string): Promise<PromptsResponse> {
  const qs = frontendId ? `?frontend_id=${frontendId}` : '';
  return request(`/admin/prompts${qs}`);
}

export async function readPrompt(name: string, frontendId?: string): Promise<{ name: string; content: string }> {
  const qs = frontendId ? `?frontend_id=${frontendId}` : '';
  return request(`/admin/prompts/${name}${qs}`);
}

export async function savePrompt(name: string, content: string, frontendId?: string): Promise<PromptFile> {
  const qs = frontendId ? `?frontend_id=${frontendId}` : '';
  return request(`/admin/prompts/${name}${qs}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  });
}

// --- SMTP API ---

export interface SMTPConfig {
  host: string
  port: number
  username: string
  password: string
  use_tls: boolean
  from_address: string
  data_protection_email: string
  notification_emails: string[]
  notify_on_report: boolean
  send_summary_to_user: boolean
  send_report_to_user: boolean
}

export async function getSMTPConfig(): Promise<SMTPConfig> {
  return request('/admin/smtp');
}

export async function updateSMTPConfig(data: Partial<SMTPConfig>): Promise<SMTPConfig> {
  return request('/admin/smtp', {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function testSMTP(): Promise<{ status: string; message: string }> {
  return request('/admin/smtp/test', { method: 'POST' });
}

export async function getAuthorizedEmails(): Promise<{ emails: string[] }> {
  return request('/admin/smtp/authorized-emails');
}

export async function updateAuthorizedEmails(emails: string[]): Promise<{ emails: string[] }> {
  return request('/admin/smtp/authorized-emails', {
    method: 'PUT',
    body: JSON.stringify({ emails }),
  });
}

export async function getFrontendNotificationEmails(frontendId: string): Promise<{ emails: string[] }> {
  return request(`/admin/smtp/frontend-notifications/${frontendId}`);
}

// --- Branding API ---

export interface BrandingConfig {
  app_title: string
  logo_url: string
}

export async function getFrontendBranding(frontendId: string): Promise<BrandingConfig> {
  return request(`/admin/frontends/${frontendId}/branding`);
}

export async function updateFrontendBranding(frontendId: string, data: BrandingConfig): Promise<BrandingConfig> {
  return request(`/admin/frontends/${frontendId}/branding`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function updateFrontendNotificationEmails(frontendId: string, emails: string[]): Promise<{ emails: string[] }> {
  return request(`/admin/smtp/frontend-notifications/${frontendId}`, {
    method: 'PUT',
    body: JSON.stringify({ emails }),
  });
}

// --- Authorized Contacts API (Sprint 18) ---

export interface Contact {
  email: string
  first_name: string
  last_name: string
  organization: string
  country: string
  sector: string
  registered_by: string
  schedule_override: boolean  // §12.7 — may choose immediate/scheduled regardless of the global toggle
  priority: boolean           // §12.7 — jobs jump to the front of the queue
}

export interface FrontendContactsOverride {
  mode: 'replace' | 'append'
  contacts: Contact[]
}

export interface ContactsStore {
  global: Contact[]
  per_frontend: Record<string, FrontendContactsOverride>
}

export async function getContacts(): Promise<ContactsStore> {
  return request('/admin/contacts')
}

export async function updateGlobalContacts(contacts: Contact[]): Promise<{ global: Contact[] }> {
  return request('/admin/contacts/global', {
    method: 'PUT',
    body: JSON.stringify({ contacts }),
  })
}

export async function updateFrontendContacts(
  frontendId: string,
  mode: 'replace' | 'append',
  contacts: Contact[]
): Promise<{ frontend_id: string; override: FrontendContactsOverride }> {
  return request(`/admin/contacts/frontend/${frontendId}`, {
    method: 'PUT',
    body: JSON.stringify({ mode, contacts }),
  })
}

export async function deleteFrontendContacts(frontendId: string): Promise<{ frontend_id: string; removed: boolean }> {
  return request(`/admin/contacts/frontend/${frontendId}`, { method: 'DELETE' })
}

export async function copyContactsFromFrontend(
  frontendId: string,
  srcFrontendId: string,
  mode: 'replace' | 'append' = 'replace'
): Promise<{ frontend_id: string; override: FrontendContactsOverride }> {
  return request(`/admin/contacts/frontend/${frontendId}/copy-from/${srcFrontendId}?mode=${mode}`, {
    method: 'POST',
  })
}

export function exportContactsURL(scope: string): string {
  return `/admin/contacts/export?scope=${encodeURIComponent(scope)}`
}

export async function importContacts(
  file: File,
  scope: string
): Promise<{ added: number; updated: number; ignored_malformed: number; scope: string }> {
  const token = localStorage.getItem('hrdd_admin_token')
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`/admin/contacts/import?scope=${encodeURIComponent(scope)}`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: 'Import failed' }))
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

// --- Knowledge Base API ---

export interface GlossaryTerm {
  term: string
  definition?: string
  translations?: Record<string, string>
}

export interface Organization {
  name: string
  type: string
  country: string
  description?: string
}

export async function getGlossary(): Promise<{ terms: GlossaryTerm[] }> {
  return request('/admin/knowledge/glossary');
}

export async function updateGlossary(terms: GlossaryTerm[]): Promise<{ terms: GlossaryTerm[] }> {
  return request('/admin/knowledge/glossary', {
    method: 'PUT',
    body: JSON.stringify({ terms }),
  });
}

export async function getOrganizations(): Promise<{ organizations: Organization[] }> {
  return request('/admin/knowledge/organizations');
}

export async function updateOrganizations(organizations: Organization[]): Promise<{ organizations: Organization[] }> {
  return request('/admin/knowledge/organizations', {
    method: 'PUT',
    body: JSON.stringify({ organizations }),
  });
}
