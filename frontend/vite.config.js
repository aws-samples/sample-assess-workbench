import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';
import { readFileSync } from 'fs';

/**
 * Read the dev-proxy values emitted by `task frontend:config`.
 *
 * The Vite process cannot source with-env.sh, so it never resolves the
 * environment or calls terraform itself. `task frontend:config` is the single
 * env-resolved point that reads terraform and writes these values to a
 * gitignored file for us to consume here.
 *
 * @returns {{apiEndpoint: string, originVerifySecret: string}|null}
 */
function readDevProxyConfig() {
  try {
    return JSON.parse(readFileSync('.dev-proxy.json', 'utf-8'));
  } catch {
    return null;
  }
}

/**
 * When config.json uses a relative "/api" base (CloudFront proxy mode),
 * local dev needs a proxy to forward those requests to the real API Gateway.
 *
 * Reads the Terraform-generated config to detect this, then reads the API
 * Gateway endpoint and origin-lockdown secret from the dev-proxy file written
 * by `task frontend:config`, and configures Vite's dev proxy to impersonate
 * CloudFront.
 */
function loadDevProxy() {
  try {
    const config = JSON.parse(readFileSync('public/config.json', 'utf-8'));
    if (config.apiBaseUrl !== '/api') return {};

    // CloudFront proxy mode — need a local proxy to API Gateway.
    const devProxy = readDevProxyConfig();
    const target = devProxy?.apiEndpoint;
    if (!target) {
      console.warn(
        '\n⚠️  Could not read API endpoint from frontend/.dev-proxy.json.\n' +
        '   Local /api proxy will not work. Either:\n' +
        '   1. Run "task dev" (or "task frontend:config") so the dev-proxy\n' +
        '      file is regenerated from terraform outputs, or\n' +
        '   2. Set the direct API Gateway URL in frontend/public/config.json\n'
      );
      return {};
    }

    // Origin lockdown: CloudFront injects X-Origin-Verify; we do the same.
    const originSecret = devProxy?.originVerifySecret || '';
    const customHeaders = originSecret
      ? { 'X-Origin-Verify': originSecret }
      : {};

    // API Gateway URL includes the stage path (e.g. /v1).
    // Rewrite /api/projects → https://xxx.execute-api.../v1/projects
    const baseTarget = target.replace(/\/v1$/, '');
    console.log(`  ➜  Proxying /api → ${target}`);
    if (originSecret) console.log('  ➜  Injecting X-Origin-Verify header');

    return {
      '/api': {
        target: baseTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '/v1'),
        secure: true,
        headers: customHeaders,
      },
    };
  } catch {
    // config.json not found or not JSON — no proxy needed
    return {};
  }
}

export default defineConfig({
  plugins: [preact()],
  server: {
    port: 5173,
    proxy: loadDevProxy(),
  },
});
