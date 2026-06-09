import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';
import { readFileSync } from 'fs';
import { execSync } from 'child_process';

/**
 * Read a terraform output value. Returns empty string on failure.
 */
function tfOutput(name) {
  try {
    return execSync(`terraform output -raw ${name}`, {
      cwd: '../terraform',
      encoding: 'utf-8',
      timeout: 10_000,
    }).trim();
  } catch {
    return '';
  }
}

/**
 * When config.json uses a relative "/api" base (CloudFront proxy mode),
 * local dev needs a proxy to forward those requests to the real API Gateway.
 *
 * Reads the Terraform-generated config to detect this, resolves the API
 * Gateway endpoint and origin-lockdown secret from terraform output, and
 * configures Vite's dev proxy to impersonate CloudFront.
 */
function loadDevProxy() {
  try {
    const config = JSON.parse(readFileSync('public/config.json', 'utf-8'));
    if (config.apiBaseUrl !== '/api') return {};

    // CloudFront proxy mode — need a local proxy to API Gateway.
    const target = tfOutput('api_endpoint');
    if (!target) {
      console.warn(
        '\n⚠️  Could not read API endpoint from terraform output.\n' +
        '   Local /api proxy will not work. Either:\n' +
        '   1. Run "task deploy:infra" so terraform state is available, or\n' +
        '   2. Set the direct API Gateway URL in frontend/public/config.json\n'
      );
      return {};
    }

    // Origin lockdown: CloudFront injects X-Origin-Verify; we do the same.
    const originSecret = tfOutput('origin_verify_secret');
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
