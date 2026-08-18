import { getConfig } from './config.js';
import { getIdToken, refreshTokens } from './auth.jsx';

export class ApiError extends Error {
  constructor(status, message, detail = '') {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

function authHeaders() {
  return {
    'Content-Type': 'application/json',
    Authorization: 'Bearer ' + getIdToken(),
  };
}

/**
 * Core API call helper. Handles auth headers, ok-check, JSON parsing,
 * and session expiry redirect. On 401, attempts a single token refresh
 * and retries before giving up.
 *
 * @param {string} path - API path (e.g. '/projects')
 * @param {object} [options] - fetch options (method, body, etc.)
 * @param {string} [errorMsg] - error message prefix on failure
 * @returns {Promise<any>} parsed JSON response
 */
async function api(path, options = {}, errorMsg = 'API request failed') {
  const url = `${getConfig().apiBaseUrl}${path}`;

  let res = await fetch(url, { headers: authHeaders(), ...options });

  // On 401 (token expired), try refreshing once and retry.
  // 403 is NOT a session issue — it means "authenticated but not authorized".
  if (res.status === 401) {
    const refreshed = await refreshTokens();
    if (refreshed) {
      res = await fetch(url, { headers: authHeaders(), ...options });
    }
    if (!refreshed || res.status === 401) {
      sessionStorage.clear();
      window.location.href = '/';
      throw new Error('Session expired');
    }
  }

  if (!res.ok) {
    let backendMessage = '';
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      const body = await res.json();
      backendMessage = body.message || body.error || '';
    }
    throw new ApiError(res.status, backendMessage || `${errorMsg} (${res.status})`, res.statusText);
  }
  return res.json();
}

/** Build a query string from an object, omitting falsy values. */
function qs(params) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v != null && v !== '') p.set(k, String(v));
  }
  const s = p.toString();
  return s ? '?' + s : '';
}

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------

export function listProjects(status, limit) {
  return api(`/projects${qs({ status, limit })}`, {}, 'Failed to list projects');
}

export function getProject(projectId) {
  return api(`/projects/${projectId}`, {}, 'Failed to load project');
}

export function createProject(name, description, contextId, files) {
  const body = { name, description: description || undefined };
  if (contextId) body.context_id = contextId;
  if (files && files.length > 0) body.files = files.map((f) => ({ filename: f.name }));
  return api('/projects', { method: 'POST', body: JSON.stringify(body) }, 'Failed to create project');
}

/** Upload files to their pre-signed URLs. */
export async function uploadProjectFiles(project, files) {
  await Promise.all(
    project.upload_urls.map((urlInfo, i) =>
      fetch(urlInfo.upload_url, {
        method: 'PUT',
        body: files[i],
        headers: { 'Content-Type': 'application/octet-stream' },
      }).then((res) => {
        if (!res.ok) throw new Error(`Upload failed for ${files[i].name}`);
      }),
    ),
  );
}

export function triggerReview(projectId) {
  return api(`/projects/${projectId}/review`, { method: 'POST' }, 'Failed to trigger review');
}

export function getReviewPlan(projectId, reviewId = 'latest') {
  return api(`/projects/${projectId}/reviews/${reviewId}/plan`, {}, 'Failed to get review plan');
}

export function approveReviewPlan(projectId, reviewId, plan) {
  const body = plan ? { plan } : {};
  return api(
    `/projects/${projectId}/reviews/${reviewId}/approve`,
    { method: 'POST', body: JSON.stringify(body) },
    'Failed to approve plan',
  );
}

export function rejectReviewPlan(projectId, reviewId, reason) {
  return api(
    `/projects/${projectId}/reviews/${reviewId}/reject`,
    { method: 'POST', body: JSON.stringify({ reason: reason || '' }) },
    'Failed to reject plan',
  );
}

export function abortReview(projectId, reviewId, reason) {
  return api(
    `/projects/${projectId}/reviews/${reviewId}/abort`,
    { method: 'POST', body: JSON.stringify({ reason: reason || '' }) },
    'Failed to abort review',
  );
}

export function getReviewEvents(projectId, reviewId = 'latest', after = null) {
  const params = after ? `?after=${encodeURIComponent(after)}` : '';
  return api(`/projects/${projectId}/reviews/${reviewId}/events${params}`, {}, 'Failed to get review events');
}

export function getProjectDocument(projectId) {
  return api(`/projects/${projectId}/document`, {}, 'Failed to load document');
}

export function deleteProject(projectId) {
  return api(`/projects/${projectId}`, { method: 'DELETE' }, 'Failed to delete project');
}

export function getProjectReport(projectId) {
  return api(`/projects/${projectId}/report`, {}, 'Failed to get report');
}

// ---------------------------------------------------------------------------
// Contexts
// ---------------------------------------------------------------------------

export function listContexts() {
  return api('/contexts', {}, 'Failed to list contexts');
}

export function createContext(name, description) {
  return api(
    '/contexts',
    { method: 'POST', body: JSON.stringify({ name, description: description || undefined }) },
    'Failed to create context',
  );
}

export function deleteContext(contextId) {
  return api(`/contexts/${contextId}`, { method: 'DELETE' }, 'Failed to delete context');
}

export function getContextContent(contextId) {
  return api(`/contexts/${contextId}/content`, {}, 'Failed to get context content');
}

export function updateContextContent(contextId, content) {
  return api(
    `/contexts/${contextId}/content`,
    { method: 'PUT', body: JSON.stringify({ content }) },
    'Failed to update context',
  );
}

// ---------------------------------------------------------------------------
// Reference data
// ---------------------------------------------------------------------------

export function fetchAgents() {
  return api('/agents', {}, 'Failed to fetch agents');
}

// ---------------------------------------------------------------------------
// Feedback
// ---------------------------------------------------------------------------

export function submitFeedback(projectId, findingId, agentType, value) {
  return api(
    `/projects/${projectId}/feedback`,
    { method: 'POST', body: JSON.stringify({ finding_id: findingId, agent_type: agentType, value }) },
    'Failed to submit feedback',
  );
}

export function getProjectFeedback(projectId) {
  return api(`/projects/${projectId}/feedback`, {}, 'Failed to get feedback');
}

// ---------------------------------------------------------------------------
// Analytics
// ---------------------------------------------------------------------------

export function getAnalyticsSummary() {
  return api('/analytics/summary', {}, 'Failed to get analytics summary');
}

export function getAnalyticsTrends(agent, limit) {
  return api(`/analytics/trends${qs({ agent, limit })}`, {}, 'Failed to get analytics trends');
}

export function getAnalyticsCoverage(projectId) {
  return api(`/analytics/coverage/${projectId}`, {}, 'Failed to get coverage');
}

// ---------------------------------------------------------------------------
// Admin
// ---------------------------------------------------------------------------

export function getAdminRegistry() {
  return api('/admin/registry', {}, 'Failed to get admin registry');
}

export function updateAdminRegistry(agentType, updates) {
  return api(
    `/admin/registry/${agentType}`,
    { method: 'PUT', body: JSON.stringify(updates) },
    'Failed to update registry',
  );
}

export function getAdminStandards() {
  return api('/admin/standards', {}, 'Failed to list standards');
}

export function getGuardrailEvents(projectId, startDate, endDate, limit) {
  return api(
    `/admin/guardrail-events${qs({ project_id: projectId, start_date: startDate, end_date: endDate, limit })}`,
    {},
    'Failed to list guardrail events',
  );
}

export function uploadAdminStandard(standardId, sourceType, filename, jurisdiction = '', industry = '', contentType = 'application/octet-stream') {
  return api(
    '/admin/standards',
    { method: 'POST', body: JSON.stringify({ standard_id: standardId, source_type: sourceType, filename, jurisdiction, industry, content_type: contentType }) },
    'Failed to upload standard',
  );
}

export function updateAdminStandardMetadata(standardId, sourceType, jurisdiction = '', industry = '') {
  return api(
    `/admin/standards/${standardId}/metadata`,
    { method: 'PUT', body: JSON.stringify({ source_type: sourceType, jurisdiction, industry }) },
    'Failed to update standard metadata',
  );
}

export function deleteAdminStandard(standardId) {
  return api(`/admin/standards/${standardId}`, { method: 'DELETE' }, 'Failed to delete standard');
}

export function syncAdminStandards() {
  return api('/admin/standards/sync', { method: 'POST' }, 'Failed to start KB sync');
}

export function getAdminStandardsSyncStatus() {
  return api('/admin/standards/sync-status', {}, 'Failed to get sync status');
}
