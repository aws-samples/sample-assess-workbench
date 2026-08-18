// =============================================================================
// useEventStream unit tests — error propagation contract.
//
// Tests that fetch failures and review-not-found conditions are surfaced
// via the onError callback instead of being silently swallowed.
// =============================================================================

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ---------------------------------------------------------------------------
// Mocks — must be set up before importing the module under test.
// ---------------------------------------------------------------------------

vi.mock('../../src/api.js', () => ({
  getReviewEvents: vi.fn(),
}));

vi.mock('../../src/ws-context.jsx', () => ({
  useWs: () => null,
}));

// Minimal preact/hooks stubs — we call the hook function directly by
// extracting the fetchEvents logic. Since useEventStream uses hooks
// internally, we provide just enough for it to initialise.
const effectCallbacks = [];
const callbackFns = [];

vi.mock('preact/hooks', () => ({
  useEffect: (fn) => { effectCallbacks.push(fn); },
  useRef: (val) => ({ current: val }),
  useCallback: (fn) => { callbackFns.push(fn); return fn; },
}));

import { getReviewEvents } from '../../src/api.js';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Instantiate the hook and return the onEvents/onError spies plus a way
 * to trigger the internal fetchEvents. We import fresh each time to reset
 * hook state.
 */
async function setupAndFetch(mockResponse, { projectId = 'proj-1', initialReviewId = null } = {}) {
  effectCallbacks.length = 0;
  callbackFns.length = 0;

  getReviewEvents.mockReset();
  if (mockResponse instanceof Error) {
    getReviewEvents.mockRejectedValue(mockResponse);
  } else {
    getReviewEvents.mockResolvedValue(mockResponse);
  }

  const onEvents = vi.fn();
  const onError = vi.fn();

  // Re-import to get a fresh module instance
  const { useEventStream } = await import('../../src/hooks/useEventStream.js');
  useEventStream({ projectId, initialReviewId, phase: 'loading', onEvents, onError });

  // The first useCallback registered is fetchEvents
  const fetchEvents = callbackFns[0];
  await fetchEvents();

  return { onEvents, onError };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useEventStream error propagation', () => {
  it('calls onError when fetch throws', async () => {
    const err = new Error('Network failure');
    const { onEvents, onError } = await setupAndFetch(err);

    expect(onError).toHaveBeenCalledWith(err);
    expect(onEvents).not.toHaveBeenCalled();
  });

  it('calls onError when initial fetch returns review_id: null with no events', async () => {
    const { onEvents, onError } = await setupAndFetch({
      review_id: null,
      events: [],
    });

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0].message).toBe('Review not found');
    expect(onEvents).not.toHaveBeenCalled();
  });

  it('calls onEvents (not onError) on successful fetch with events', async () => {
    const { onEvents, onError } = await setupAndFetch({
      review_id: 'rev-123',
      events: [{ event: 'plan_created', detail: {}, ts: '2025-01-01T00:00:00Z' }],
    });

    expect(onEvents).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();
  });

  it('throws when onError is not provided and fetch fails', async () => {
    effectCallbacks.length = 0;
    callbackFns.length = 0;

    getReviewEvents.mockReset();
    getReviewEvents.mockRejectedValue(new Error('Network failure'));

    const onEvents = vi.fn();

    const { useEventStream } = await import('../../src/hooks/useEventStream.js');
    // No onError — calling fetchEvents should throw because onError is required
    useEventStream({ projectId: 'proj-1', initialReviewId: null, phase: 'loading', onEvents });

    const fetchEvents = callbackFns[0];
    await expect(fetchEvents()).rejects.toThrow();
  });

  it('does not treat review_id: null as error on subsequent poll (cursor set)', async () => {
    effectCallbacks.length = 0;
    callbackFns.length = 0;

    getReviewEvents.mockReset();

    const onEvents = vi.fn();
    const onError = vi.fn();

    const { useEventStream } = await import('../../src/hooks/useEventStream.js');
    useEventStream({ projectId: 'proj-1', initialReviewId: null, phase: 'executing', onEvents, onError });

    const fetchEvents = callbackFns[0];

    // First fetch returns real events — sets the cursor
    getReviewEvents.mockResolvedValue({
      review_id: 'rev-1',
      events: [{ event: 'plan_created', detail: {}, ts: '2025-01-01T00:00:01Z' }],
    });
    await fetchEvents();
    expect(onEvents).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();

    // Subsequent poll returns empty — this is "no new events", not an error,
    // because the cursor is already set (we're past the initial fetch).
    getReviewEvents.mockResolvedValue({ review_id: null, events: [] });
    await fetchEvents();
    expect(onError).not.toHaveBeenCalled();
  });
});
