// =============================================================================
// useEventStream — single source of truth for review events.
//
// Fetches events from the API on mount (full history), on WebSocket
// "events_available" notification (cursor-based), and on a poll interval
// during the executing phase (fallback for missed notifications).
//
// Deduplicates by timestamp so the same event is never dispatched twice.
// =============================================================================

import { useEffect, useRef, useCallback } from 'preact/hooks';
import { getReviewEvents } from '../api.js';
import { useWs } from '../ws-context.jsx';

const POLL_INTERVAL_MS = 4000;

/**
 * Streams review events into the provided dispatch function.
 *
 * @param {object} opts
 * @param {string} opts.projectId - Project ID
 * @param {string|null} opts.initialReviewId - Known review ID (from URL).
 *   When provided, events are fetched by this ID directly instead of
 *   resolving via 'latest'. When absent, falls back to 'latest' resolution
 *   (requires a PLAN# record to exist in DynamoDB).
 * @param {string} opts.phase - Current review phase (controls polling)
 * @param {Function} opts.onEvents - Called with (newEvents, reviewId) when
 *   new events arrive. The caller is responsible for dispatching them.
 * @param {Function} opts.onError - Called with an Error when a fetch fails
 *   or when the initial fetch resolves with review_id: null (review not found).
 */
export function useEventStream({ projectId, initialReviewId, phase, onEvents, onError }) {
  const ws = useWs();
  const cursorRef = useRef(null);
  const reviewIdRef = useRef(initialReviewId || null);
  const seenTimestamps = useRef(new Set());
  const fetchingRef = useRef(false);

  // Tracks whether a fetch was requested while one was already in-flight.
  // When set, the completing fetch will immediately start another to pick
  // up any events that arrived during the previous request. This is a
  // boolean (not a counter) because the cursor-based fetch is naturally
  // coalescing — one follow-up fetch retrieves everything since the last
  // cursor regardless of how many notifications were missed.
  const pendingRef = useRef(false);

  const fetchEvents = useCallback(async () => {
    if (!projectId) return;

    // If a fetch is already in-flight, don't start a concurrent one —
    // just record that we need to re-fetch when the current one finishes.
    if (fetchingRef.current) {
      pendingRef.current = true;
      return;
    }

    fetchingRef.current = true;
    pendingRef.current = false;
    try {
      const rid = reviewIdRef.current || 'latest';
      const { events, review_id } = await getReviewEvents(
        projectId, rid, cursorRef.current,
      );
      if (review_id && !reviewIdRef.current) {
        reviewIdRef.current = review_id;
      }

      // Initial fetch returned null review_id with no events — the review
      // doesn't exist (resolution failed). Distinguish from "no events yet
      // during a live review" by checking that we have no cursor (initial).
      if (!review_id && events.length === 0 && !cursorRef.current) {
        onError(new Error('Review not found'));
        return;
      }

      // Deduplicate — skip events we've already seen
      const fresh = events.filter(e => !seenTimestamps.current.has(e.ts));
      if (fresh.length === 0) return;
      for (const e of fresh) seenTimestamps.current.add(e.ts);
      // Advance cursor to the latest timestamp
      cursorRef.current = fresh[fresh.length - 1].ts;
      onEvents(fresh, reviewIdRef.current);
    } catch (err) {
      onError(err);
    } finally {
      fetchingRef.current = false;

      // A notification arrived while we were fetching. Fetch again to
      // pick up events that were persisted after our query ran. The
      // cursor ensures we only get new events, and deduplication handles
      // any overlap at the boundary.
      if (pendingRef.current) {
        pendingRef.current = false;
        fetchEvents();
      }
    }
  }, [projectId, onEvents, onError]);

  // Initial fetch on mount (full history, no cursor)
  useEffect(() => {
    if (!projectId) return;
    cursorRef.current = null;
    seenTimestamps.current.clear();
    // Use the known review ID if provided (fresh review start), otherwise
    // fall back to 'latest' resolution (page refresh, View Timeline, etc.)
    reviewIdRef.current = initialReviewId || null;
    fetchEvents();
  }, [projectId, fetchEvents]);

  // WebSocket — fetch on "events_available" notification
  useEffect(() => {
    if (!ws) return;
    return ws.subscribe((msg) => {
      if (msg.type === 'events_available') fetchEvents();
    });
  }, [ws, fetchEvents]);

  // Poll during loading and executing phases as a fallback for missed
  // WebSocket notifications. Loading covers the planning stage (document
  // processing, planner invocation, plan creation) where failures must
  // surface even if the WebSocket notification is lost.
  useEffect(() => {
    if (phase !== 'executing' && phase !== 'loading') return;
    const id = setInterval(fetchEvents, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [phase, fetchEvents]);

  return { reviewId: reviewIdRef.current };
}
