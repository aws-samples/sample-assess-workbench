import { useState, useEffect, useRef, useCallback } from 'preact/hooks';
import { getConfig } from '../config.js';

/**
 * Periodically pings the backend health endpoint and tracks reachability.
 *
 * Returns { healthy, checking, retryNow }:
 *  - healthy: true when the last check succeeded, false after a failure
 *  - checking: true while a check is in-flight (useful for retry button state)
 *  - retryNow: callback to trigger an immediate check
 *
 * The hook starts optimistic (healthy=true) so the banner doesn't flash on
 * initial load. On failure it switches to unhealthy and stays there until a
 * subsequent check succeeds.
 */
const INTERVAL_MS = 30_000; // 30 s between checks
const TIMEOUT_MS = 8_000;   // give up after 8 s

export function useHealthCheck() {
  const [healthy, setHealthy] = useState(true);
  const [checking, setChecking] = useState(false);
  const timerRef = useRef(null);

  const check = useCallback(async () => {
    setChecking(true);
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
      const res = await fetch(`${getConfig().apiBaseUrl}/health`, {
        signal: controller.signal,
      });
      clearTimeout(timeout);
      setHealthy(res.ok);
    } catch {
      // Network error or timeout — backend unreachable
      setHealthy(false);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    // Initial check after a short delay so we don't race the first render
    const initial = setTimeout(check, 2_000);
    timerRef.current = setInterval(check, INTERVAL_MS);
    return () => {
      clearTimeout(initial);
      clearInterval(timerRef.current);
    };
  }, [check]);

  const retryNow = useCallback(() => {
    // Reset the interval so the next automatic check is a full period away
    clearInterval(timerRef.current);
    check();
    timerRef.current = setInterval(check, INTERVAL_MS);
  }, [check]);

  return { healthy, checking, retryNow };
}
