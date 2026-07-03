// =============================================================================
// parseRiskFindings unit tests — parse contract.
//
// Tests that valid data returns findings, malformed JSON throws (not []),
// and projects without reviews return genuinely empty arrays.
// =============================================================================

import { describe, it, expect } from 'vitest';

// parseRiskFindings is not exported, so we re-implement the same logic here
// to test the contract. The real function lives in risk-heatmap.jsx as a
// module-scoped function. We extract the pure logic for testability.
//
// TODO: Extract parseRiskFindings to a shared module and import directly.

function parseRiskFindings(project) {
  if (project.status !== 'completed' || !project.review?.result) return [];
  const result =
    typeof project.review.result === 'string'
      ? JSON.parse(project.review.result)
      : project.review.result;
  const risk = (result.reviews || {}).risk;
  if (!risk) return [];
  return (risk.findings || []).filter((f) => f.likelihood && f.consequence);
}

describe('parseRiskFindings', () => {
  it('returns findings from valid completed project', () => {
    const project = {
      status: 'completed',
      review: {
        result: JSON.stringify({
          reviews: {
            risk: {
              findings: [
                { id: 'R-1', title: 'Test', likelihood: 'likely', consequence: 'major', severity: 'high' },
                { id: 'R-2', title: 'Test 2', likelihood: 'rare', consequence: 'minor', severity: 'low' },
              ],
            },
          },
        }),
      },
    };
    const findings = parseRiskFindings(project);
    expect(findings).toHaveLength(2);
    expect(findings[0].id).toBe('R-1');
  });

  it('throws on malformed review JSON', () => {
    const project = {
      status: 'completed',
      review: { result: '{not valid json' },
    };
    expect(() => parseRiskFindings(project)).toThrow();
  });

  it('returns empty array for project with no review', () => {
    expect(parseRiskFindings({ status: 'pending' })).toEqual([]);
    expect(parseRiskFindings({ status: 'completed', review: null })).toEqual([]);
    expect(parseRiskFindings({ status: 'completed', review: {} })).toEqual([]);
  });

  it('returns empty array when review has no risk agent', () => {
    const project = {
      status: 'completed',
      review: {
        result: { reviews: { architecture: { findings: [{ id: 'A-1' }] } } },
      },
    };
    expect(parseRiskFindings(project)).toEqual([]);
  });

  it('filters out findings missing likelihood or consequence', () => {
    const project = {
      status: 'completed',
      review: {
        result: {
          reviews: {
            risk: {
              findings: [
                { id: 'R-1', likelihood: 'likely', consequence: 'major' },
                { id: 'R-2', likelihood: 'likely' },
                { id: 'R-3', consequence: 'minor' },
              ],
            },
          },
        },
      },
    };
    const findings = parseRiskFindings(project);
    expect(findings).toHaveLength(1);
    expect(findings[0].id).toBe('R-1');
  });
});
