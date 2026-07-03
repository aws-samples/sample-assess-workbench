// =============================================================================
// api() unit tests — error handling contract.
//
// Tests the core API helper's error classification: structured ApiError with
// HTTP status, backend message extraction, and content-type awareness.
// =============================================================================

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock dependencies before importing api.js
vi.mock('../../src/config.js', () => ({
  getConfig: () => ({ apiBaseUrl: 'https://test.example.com/v1' }),
}));

vi.mock('../../src/auth.jsx', () => ({
  getIdToken: () => 'test-token',
  refreshTokens: vi.fn(() => Promise.resolve(false)),
}));

import { ApiError, getProject } from '../../src/api.js';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockResponse(status, body, contentType = 'application/json') {
  const headers = new Map([['content-type', contentType]]);
  const isJsonContent = contentType.includes('application/json');
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: statusTextFor(status),
    headers: { get: (key) => headers.get(key.toLowerCase()) || '' },
    json: isJsonContent && typeof body === 'object'
      ? () => Promise.resolve(body)
      : () => Promise.reject(new SyntaxError('Unexpected token')),
  };
}

function statusTextFor(code) {
  const map = { 200: 'OK', 400: 'Bad Request', 404: 'Not Found', 500: 'Internal Server Error', 502: 'Bad Gateway' };
  return map[code] || 'Unknown';
}


// ---------------------------------------------------------------------------
// ApiError class
// ---------------------------------------------------------------------------

describe('ApiError class', () => {
  it('has correct name, status, message, and detail', () => {
    const err = new ApiError(404, 'Project not found', 'Not Found');
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe('ApiError');
    expect(err.status).toBe(404);
    expect(err.message).toBe('Project not found');
    expect(err.detail).toBe('Not Found');
  });

  it('defaults detail to empty string', () => {
    const err = new ApiError(500, 'Server error');
    expect(err.detail).toBe('');
  });
});

// ---------------------------------------------------------------------------
// api() error handling
// ---------------------------------------------------------------------------

describe('api() error handling', () => {
  let originalFetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('throws ApiError with backend message on JSON error response', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(mockResponse(400, { error: 'Document not uploaded' })),
    );

    try {
      await getProject('test-id');
      expect.unreachable('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect(err.status).toBe(400);
      expect(err.message).toBe('Document not uploaded');
      expect(err.detail).toBe('Bad Request');
    }
  });

  it('falls back to errorMsg with status code on non-JSON error response', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(mockResponse(502, '<html>Bad Gateway</html>', 'text/html')),
    );

    try {
      await getProject('test-id');
      expect.unreachable('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect(err.status).toBe(502);
      expect(err.message).toContain('502');
      expect(err.message).toContain('Failed to load project');
    }
  });

  it('propagates JSON parse error when content-type is JSON but body is malformed', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(mockResponse(400, 'not json', 'application/json')),
    );

    await expect(getProject('test-id')).rejects.toThrow(SyntaxError);
  });

  it('returns parsed JSON on success', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(mockResponse(200, { project_id: 'abc', name: 'Test' })),
    );

    const result = await getProject('abc');
    expect(result).toEqual({ project_id: 'abc', name: 'Test' });
  });

  it('prefers body.message over body.error when both present', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(mockResponse(400, { message: 'Specific message', error: 'Generic error' })),
    );

    try {
      await getProject('test-id');
      expect.unreachable('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect(err.message).toBe('Specific message');
    }
  });
});
