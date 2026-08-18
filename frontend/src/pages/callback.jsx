import { useEffect, useState } from 'preact/hooks';
import { route } from 'preact-router';
import { getConfig } from '../config.js';
import { storeTokens } from '../auth.jsx';

export function CallbackPage() {
  const [status, setStatus] = useState('Signing you in...');

  useEffect(() => {
    handleCallback();
  }, []);

  async function handleCallback() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const error = params.get('error');

    if (error) {
      setStatus('Sign in failed: ' + error);
      return;
    }
    if (!code) {
      setStatus('No authorization code received.');
      return;
    }

    try {
      const cfg = getConfig();
      const tokenUrl = cfg.cognitoHostedUiUrl + '/oauth2/token';
      const body = new URLSearchParams({
        grant_type: 'authorization_code',
        client_id: cfg.clientId,
        code,
        redirect_uri: window.location.origin + '/callback',
      });

      const res = await fetch(tokenUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString(),
        credentials: 'include',
      });

      if (!res.ok) throw new Error('Token exchange failed');
      const tokens = await res.json();
      storeTokens(tokens.id_token, tokens.access_token, tokens.expires_in, tokens.refresh_token);
      route('/', true);
    } catch (err) {
      setStatus('Sign in error: ' + err.message);
    }
  }

  return (
    <div class="container">
      <header>
        <h1>Assess Workbench</h1>
        <p class="subtitle">{status}</p>
      </header>
    </div>
  );
}
