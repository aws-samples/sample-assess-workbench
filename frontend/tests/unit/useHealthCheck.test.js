// =============================================================================
// useHealthCheck unit tests — backend reachability contract.
//
// Verifies that the hook correctly transitions between healthy/unhealthy
// based on fetch outcomes, starts optimistic, and supports manual retry.
// =============================================================================

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('../../src/config.js', () => ({
  getConfig: () => ({ apiBaseUrl: 'https://api.test' }),
}));

// Capture hook state updates
let latestState = {};
const effectCleanups = [];

vi.mock('preact/hooks', () => {
  const refs = [];
  return {
    useState: (init) => {
      const key = refs.length;
      refs.push(init);
      // Return [currentValue, setter] — setter updates latestState for assertions
      const setter = (val) => {
        const resolved = typeof val === 'function' ? val(refs[key]) : val;
        refs[key] = resolved;
        // Map by position: 0=healthy, 1=checking
        if (key % 2 === 0) latestState.healthy = resolved;
        else latestState.checking = resolved;
      };
      return [refs[key], setter];
    },
    useEffect: (fn) => {
      const cleanup = fn();
      if (cleanup) effectCleanups.push(cleanup);
    },
    useRef: (val) => ({ current: val }),
    useCallback: (fn) => fn,
  };
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resetState() {
  latestState = { healthy: true, checking: false };
  effectCleanups.length = 0;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useHealthCheck', () => {
  beforeEach(() => {
    resetState();
    vi.useFakeTimers();
    global.fetch = vi.fn();
    global.AbortController = class {
      constructor() { this.signal = 'signal'; }
      abort() {}
    };
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.resetModules();
    effectCleanups.forEach((fn) => fn());
  });

  it('starts optimistic — healthy is true before any check', async () => {
    global.fetch.mockResolvedValue({ ok: true });
    const { useHealthCheck } = await import('../../src/hooks/useHealthCheck.js');
    useHealthCheck();
    // Before the initial delayed check fires, state should be healthy
    expect(latestState.healthy).toBe(true);
  });

  it('stays healthy when fetch returns ok', async () => {
    global.fetch.mockResolvedValue({ ok: true });
    const { useHealthCheck } = await import('../../src/hooks/useHealthCheck.js');
    const { retryNow } = useHealthCheck();

    await retryNow();
    expect(latestState.healthy).toBe(true);
  });

  it('transitions to unhealthy when fetch returns non-ok', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 503 });
    const { useHealthCheck } = await import('../../src/hooks/useHealthCheck.js');
    const { retryNow } = useHealthCheck();

    await retryNow();
    expect(latestState.healthy).toBe(false);
  });

  it('transitions to unhealthy on network error', async () => {
    global.fetch.mockRejectedValue(new TypeError('Failed to fetch'));
    const { useHealthCheck } = await import('../../src/hooks/useHealthCheck.js');
    const { retryNow } = useHealthCheck();

    await retryNow();
    expect(latestState.healthy).toBe(false);
  });

  it('recovers to healthy after a failed check succeeds', async () => {
    global.fetch.mockRejectedValue(new TypeError('Failed to fetch'));
    const { useHealthCheck } = await import('../../src/hooks/useHealthCheck.js');
    const { retryNow } = useHealthCheck();

    await retryNow();
    expect(latestState.healthy).toBe(false);

    // Backend comes back
    global.fetch.mockResolvedValue({ ok: true });
    await retryNow();
    expect(latestState.healthy).toBe(true);
  });

  it('calls the correct health endpoint URL', async () => {
    global.fetch.mockResolvedValue({ ok: true });
    const { useHealthCheck } = await import('../../src/hooks/useHealthCheck.js');
    const { retryNow } = useHealthCheck();

    await retryNow();
    expect(global.fetch).toHaveBeenCalledWith(
      'https://api.test/health',
      expect.objectContaining({ signal: 'signal' }),
    );
  });
});
