import { createContext } from 'preact';
import { useContext, useState, useEffect, useCallback, useRef } from 'preact/hooks';
import { getConfig } from './config.js';

const TOKEN_KEYS = {
  idToken: 'app_id_token',
  accessToken: 'app_access_token',
  refreshToken: 'app_refresh_token',
  expiresAt: 'app_expires_at',
};

/** How far before expiry (ms) to proactively refresh tokens. */
const REFRESH_MARGIN_MS = 5 * 60 * 1000; // 5 minutes

const AuthContext = createContext(null);

/**
 * Return the current ID token, or null if expired / missing.
 * Every consumer that needs a token goes through here, so an expired
 * token is never silently handed out.
 */
export function getIdToken() {
  const expiresAt = sessionStorage.getItem(TOKEN_KEYS.expiresAt);
  if (!expiresAt || Date.now() >= parseInt(expiresAt, 10)) return null;
  return sessionStorage.getItem(TOKEN_KEYS.idToken);
}

function isAuthenticated() {
  return getIdToken() !== null;
}

/** Decode a JWT payload, handling base64url and unicode correctly. */
function decodeJwtPayload(token) {
  try {
    const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const json = decodeURIComponent(
      atob(base64).split('').map(c => '%' + c.charCodeAt(0).toString(16).padStart(2, '0')).join('')
    );
    return JSON.parse(json);
  } catch {
    return null;
  }
}

function getUserEmail() {
  const token = getIdToken();
  if (!token) return null;
  return decodeJwtPayload(token)?.email || null;
}

function getUserGroups() {
  const token = getIdToken();
  if (!token) return [];
  const payload = decodeJwtPayload(token);
  if (!payload) return [];
  const groups = payload['cognito:groups'];
  if (Array.isArray(groups)) return groups;
  if (typeof groups === 'string') return groups.split(' ').filter(Boolean);
  return [];
}

/**
 * Resolve the user's write capability from group membership.
 *
 * "viewer" is a full-read, zero-write role: a viewer sees everything an
 * admin sees but cannot mutate anything. Federated (e.g. demo) users are
 * auto-assigned to "viewers" via DEFAULT_GROUP in Terraform, which
 * is what makes them read-only — NOT the federated flag. We derive
 * read-only from the role (the effect) rather than from being federated
 * (one possible cause); this keeps the gate correct if a non-demo federated
 * IdP is ever added, and matches the backend's role-based enforcement.
 *
 * A user is read-only when they are neither an admin nor a member of the
 * "users" group. That covers explicit viewers and any unrecognised/empty
 * group membership (least-privilege default), mirroring the backend's
 * get_user_role fallback.
 */
function deriveReadOnly(groups) {
  return !groups.includes('admins') && !groups.includes('users');
}

/** Check if the current user authenticated via a federated identity provider. */
function isFederatedUser() {
  const token = getIdToken();
  if (!token) return false;
  const payload = decodeJwtPayload(token);
  if (!payload) return false;
  const identities = payload.identities;
  return Array.isArray(identities) && identities.length > 0;
}

export function storeTokens(idToken, accessToken, expiresIn, refreshToken) {
  const expiresAt = Date.now() + expiresIn * 1000;
  sessionStorage.setItem(TOKEN_KEYS.idToken, idToken);
  sessionStorage.setItem(TOKEN_KEYS.accessToken, accessToken);
  sessionStorage.setItem(TOKEN_KEYS.expiresAt, expiresAt.toString());
  // Refresh token is only returned on initial login, not on refresh grants
  if (refreshToken) {
    sessionStorage.setItem(TOKEN_KEYS.refreshToken, refreshToken);
  }
}

function clearTokens() {
  Object.values(TOKEN_KEYS).forEach((k) => sessionStorage.removeItem(k));
}

/**
 * Exchange the refresh token for new id/access tokens.
 * Returns true on success, false if the refresh token is expired or revoked.
 */
let _refreshInFlight = null;

export async function refreshTokens() {
  // Deduplicate concurrent refresh attempts (e.g. multiple 401s at once)
  if (_refreshInFlight) return _refreshInFlight;

  _refreshInFlight = _doRefresh();
  try {
    return await _refreshInFlight;
  } finally {
    _refreshInFlight = null;
  }
}

async function _doRefresh() {
  const refreshToken = sessionStorage.getItem(TOKEN_KEYS.refreshToken);
  if (!refreshToken) return false;

  try {
    const cfg = getConfig();
    const body = new URLSearchParams({
      grant_type: 'refresh_token',
      client_id: cfg.clientId,
      refresh_token: refreshToken,
    });

    const res = await fetch(cfg.cognitoHostedUiUrl + '/oauth2/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    });

    if (!res.ok) return false;

    const tokens = await res.json();
    // Cognito refresh grants return id_token + access_token but NOT a new refresh_token
    storeTokens(tokens.id_token, tokens.access_token, tokens.expires_in);
    return true;
  } catch {
    return false;
  }
}

/**
 * Build the Cognito authorize URL. When OIDC federation is configured,
 * includes the identity_provider hint so Cognito skips its own form and goes
 * straight to the external provider. Otherwise, no hint — Cognito shows its
 * login form. The hint is skipped if ?admin is in the current URL (escape
 * hatch for admins who need email/password login).
 */
function getLoginUrl() {
  const cfg = getConfig();
  const params = new URLSearchParams({
    response_type: 'code',
    client_id: cfg.clientId,
    redirect_uri: window.location.origin + '/callback',
    scope: 'openid email profile',
  });
  const currentParams = new URLSearchParams(window.location.search);
  if (cfg.federationEnabled && cfg.identityProviderName && !currentParams.has('admin')) {
    params.set('identity_provider', cfg.identityProviderName);
  }
  return `${cfg.cognitoHostedUiUrl}/authorize?${params}`;
}

function getLogoutUrl() {
  const cfg = getConfig();
  const params = new URLSearchParams({
    client_id: cfg.clientId,
    logout_uri: window.location.origin,
  });
  return `${cfg.cognitoHostedUiUrl}/logout?${params}`;
}

const SIGNED_OUT_KEY = 'app_signed_out';

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    if (!isAuthenticated()) return null;
    const federated = isFederatedUser();
    const groups = getUserGroups();
    return {
      email: getUserEmail(),
      groups,
      federated,
      // Read-only is role-derived (viewer = full read, zero write), not
      // federated-derived. federated retained for diagnostics only.
      readOnly: deriveReadOnly(groups),
    };
  });
  const refreshTimerRef = useRef(null);

  const [signedOut, setSignedOut] = useState(() => !!sessionStorage.getItem(SIGNED_OUT_KEY));

  const login = useCallback(() => {
    sessionStorage.removeItem(SIGNED_OUT_KEY);
    setSignedOut(false);
    window.location.href = getLoginUrl();
  }, []);

  const logout = useCallback(() => {
    clearTokens();
    sessionStorage.setItem(SIGNED_OUT_KEY, '1');
    setSignedOut(true);
    setUser(null);
    window.location.href = getLogoutUrl();
  }, []);

  /**
   * Schedule a silent token refresh to fire REFRESH_MARGIN_MS before expiry.
   * On success, updates state so downstream consumers (WsProvider, etc.)
   * re-render with the fresh token. On failure, clears auth and redirects.
   */
  const scheduleRefresh = useCallback(() => {
    clearTimeout(refreshTimerRef.current);

    const expiresAt = sessionStorage.getItem(TOKEN_KEYS.expiresAt);
    if (!expiresAt) return;

    const delay = Math.max(0, parseInt(expiresAt, 10) - Date.now() - REFRESH_MARGIN_MS);

    refreshTimerRef.current = setTimeout(async () => {
      const ok = await refreshTokens();
      if (ok) {
        const federated = isFederatedUser();
        const groups = getUserGroups();
        setUser({ email: getUserEmail(), groups, federated, readOnly: deriveReadOnly(groups) });
        scheduleRefresh(); // schedule the next refresh cycle
      } else {
        clearTokens();
        setUser(null);
        // Refresh token expired/revoked — full re-login required.
        window.location.href = getLoginUrl();
      }
    }, delay);
  }, []);

  useEffect(() => {
    if (!isAuthenticated()) {
      // If user explicitly signed out, don't auto-redirect — show signed-out screen.
      if (signedOut) return;
      login();
      return;
    }
    // Start the proactive refresh cycle
    scheduleRefresh();
    return () => clearTimeout(refreshTimerRef.current);
  }, [login, scheduleRefresh, signedOut]);

  // Signed-out state: user explicitly logged out, show thank-you screen.
  if (!user && signedOut) {
    return (
      <div class="signed-out-page">
        <div class="signed-out-card">
          <h1>Assess Workbench</h1>
          <p>Thanks for visiting. See you next time.</p>
          <button class="btn btn-primary" onClick={login}>
            Sign in
          </button>
        </div>
      </div>
    );
  }

  // Not authenticated and no signed-out flag — login() already triggered a redirect.
  if (!user) return null;

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
