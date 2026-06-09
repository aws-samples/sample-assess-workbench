"""Live E2E tests for the review flow.

All tests consume the session-scoped ``review_lifecycle`` fixture from
conftest.py, which creates a project, runs a 2-agent review to completion,
and cleans up on teardown. No test drives the lifecycle itself — they
assert against the completed result.

Test groups:
  - TestReviewValidation: edge cases that don't need a completed review.
  - TestReviewFindings: verify the completed review has findings and structure.
  - TestReviewEvents: API contract tests for event, document, report,
    coverage, and feedback endpoints.
"""
import pytest

pytestmark = pytest.mark.live


# ═══════════════════════════════════════════════════════════════════════════
# Validation — independent, fast, no lifecycle dependency
# ═══════════════════════════════════════════════════════════════════════════

class TestReviewValidation:
    """Validation edge cases (independent, fast)."""

    def test_trigger_without_document_returns_400(self, api_endpoint, http):
        """Triggering a review before uploading should fail."""
        pid = None
        try:
            resp = http.post(f"{api_endpoint}/projects",
                             payload={"name": "E2E no upload",
                                      "files": [{"filename": "not-uploaded.txt"}]})
            assert resp.status_code == 201
            pid = resp.json()["project_id"]
            r = http.post(f"{api_endpoint}/projects/{pid}/review")
            assert r.status_code == 400
        finally:
            if pid:
                http.delete(f"{api_endpoint}/projects/{pid}")

    def test_trigger_nonexistent_project_returns_404(self, api_endpoint, http):
        resp = http.post(f"{api_endpoint}/projects/nonexistent-id/review")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# Findings — verify the completed review has data
# ═══════════════════════════════════════════════════════════════════════════

class TestReviewFindings:
    """Verify the completed review contains findings and expected structure."""

    def test_status_is_completed(self, review_lifecycle):
        project = review_lifecycle["completed_project"]
        assert project["status"] == "completed", f"Got {project['status']}"

    def test_review_has_result(self, review_lifecycle):
        review = review_lifecycle["completed_project"].get("review", {})
        assert review, "No review data in project response"
        result = review.get("result", {})
        assert result, "No review result data"

    def test_has_findings(self, review_lifecycle):
        review = review_lifecycle["completed_project"]["review"]
        result = review["result"]
        summary = result.get("summary", {})
        total = summary.get("total_findings", 0)
        by_agent = summary.get("by_agent", {})
        print(f"   Total findings: {total}")
        print(f"   By agent: {by_agent}")
        assert total > 0, "Expected at least one finding"

    def test_review_has_duration(self, review_lifecycle):
        review = review_lifecycle["completed_project"]["review"]
        duration = review.get("duration_ms", 0)
        print(f"   Duration: {duration}ms")
        assert duration > 0, "Expected non-zero duration"


# ═══════════════════════════════════════════════════════════════════════════
# Post-lifecycle API contract tests
# ═══════════════════════════════════════════════════════════════════════════

class TestReviewEvents:
    """API contract tests for review event and related endpoints."""

    _all_events = None

    @property
    def project_id(self):
        return self._lifecycle["project_id"]

    @property
    def review_id(self):
        return self._lifecycle["review_id"]

    @pytest.fixture(autouse=True)
    def _inject_lifecycle(self, review_lifecycle):
        self._lifecycle = review_lifecycle

    def test_events_endpoint(self, api_endpoint, http):
        """GET /reviews/{id}/events should return a chronological event log."""
        url = (f"{api_endpoint}/projects/{self.project_id}"
               f"/reviews/{self.review_id}/events")

        resp = http.get(url)
        assert resp.status_code == 200, f"Events: {resp.status_code} {resp.text}"
        data = resp.json()
        assert data["review_id"] == self.review_id

        events = data["events"]
        assert len(events) > 0, "Expected at least one event"

        timestamps = [e["ts"] for e in events]
        assert timestamps == sorted(timestamps), "Events not in chronological order"

        event_types = [e["event"] for e in events]
        assert "review_complete" in event_types, (
            f"Missing review_complete. Got: {event_types}"
        )
        print(f"   Events: {len(events)}, types: {event_types}")
        TestReviewEvents._all_events = events

    def test_events_cursor(self, api_endpoint, http):
        """GET /reviews/{id}/events?after= should filter to newer events only."""
        events = self._all_events
        if not events or len(events) < 3:
            pytest.skip("Not enough events to test cursor")

        mid = len(events) // 2
        cursor_ts = events[mid]["ts"]

        url = (f"{api_endpoint}/projects/{self.project_id}"
               f"/reviews/{self.review_id}/events")
        resp = http.get(url, params={"after": cursor_ts})
        assert resp.status_code == 200, f"Cursor: {resp.status_code} {resp.text}"
        filtered = resp.json()["events"]

        for e in filtered:
            assert e["ts"] >= cursor_ts
        assert len(filtered) < len(events), "Cursor filter returned all events"
        print(f"   Cursor at mid-point: {len(events)} total → {len(filtered)} after")

    def test_project_has_latest_review_id(self, api_endpoint, http):
        """Completed project should carry latest_review_id."""
        resp = http.get(f"{api_endpoint}/projects/{self.project_id}")
        assert resp.status_code == 200
        project = resp.json()
        assert project.get("latest_review_id") == self.review_id

    def test_resolve_latest_events(self, api_endpoint, http):
        """GET /reviews/latest/events should resolve to the correct review."""
        url = (f"{api_endpoint}/projects/{self.project_id}"
               f"/reviews/latest/events")
        resp = http.get(url)
        assert resp.status_code == 200, f"Latest events: {resp.status_code} {resp.text}"
        data = resp.json()
        assert data["review_id"] == self.review_id
        assert len(data["events"]) > 0

    def test_document_endpoint(self, api_endpoint, http):
        """GET /projects/{id}/document should return the uploaded document content."""
        resp = http.get(f"{api_endpoint}/projects/{self.project_id}/document")
        assert resp.status_code == 200, f"Document: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body["project_id"] == self.project_id
        files = body.get("files", [])
        assert len(files) > 0, "No files in document response"
        assert files[0].get("content"), "File content is empty"

    def test_report_endpoint(self, api_endpoint, http):
        """GET /projects/{id}/report should return a markdown report."""
        resp = http.get(f"{api_endpoint}/projects/{self.project_id}/report")
        assert resp.status_code == 200, f"Report: {resp.status_code} {resp.text}"
        body = resp.json()
        assert "report" in body
        assert len(body["report"]) > 0, "Report is empty"
        assert "#" in body["report"], "Report doesn't appear to be markdown"

    def test_coverage_endpoint(self, api_endpoint, http):
        """GET /analytics/coverage/{id} should return a coverage matrix."""
        resp = http.get(f"{api_endpoint}/analytics/coverage/{self.project_id}")
        assert resp.status_code == 200, f"Coverage: {resp.status_code} {resp.text}"
        body = resp.json()
        assert "matrix" in body
        assert "sections" in body
        assert "agents" in body

    def test_feedback_submit_and_read(self, api_endpoint, http):
        """POST then GET /projects/{id}/feedback should round-trip."""
        submit_resp = http.post(f"{api_endpoint}/projects/{self.project_id}/feedback", payload={
            "finding_id": "TEST-001",
            "agent_type": "architecture",
            "value": "up",
        })
        assert submit_resp.status_code == 201, (
            f"Feedback submit: {submit_resp.status_code} {submit_resp.text}"
        )
        submitted = submit_resp.json()
        assert submitted["finding_id"] == "TEST-001"
        assert submitted["value"] == "up"

        get_resp = http.get(f"{api_endpoint}/projects/{self.project_id}/feedback")
        assert get_resp.status_code == 200, (
            f"Feedback get: {get_resp.status_code} {get_resp.text}"
        )
        body = get_resp.json()
        assert "feedback" in body
        our_feedback = [f for f in body["feedback"] if f["finding_id"] == "TEST-001"]
        assert len(our_feedback) > 0, "Submitted feedback not found in GET response"
        assert our_feedback[0]["value"] == "up"
