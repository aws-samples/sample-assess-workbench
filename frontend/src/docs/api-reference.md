# API Reference

**Assess Workbench API** v2.0.0

## Authentication

All endpoints require a Bearer token (Cognito JWT) in the Authorization header:

```
Authorization: Bearer <id_token>
```

Tokens expire after 1 hour. The `/health` endpoint is the only exception (no auth required).

## Admin

### `GET /admin/guardrail-events`
**List guardrail intervention events**

Returns guardrail intervention events from the audit log. Supports date range and project filtering. Requires admin group membership.

**Parameters:**

- `start_date` (query) *(optional)* — ISO-8601 start date (inclusive). Defaults to 30 days ago.
- `end_date` (query) *(optional)* — ISO-8601 end date (inclusive). Defaults to now.
- `project_id` (query) *(optional)* — Filter events by project ID.
- `limit` (query) *(optional)* — Maximum number of events to return.

**Response (200):** Guardrail intervention events

- `events` (array)
  *Array items:*
    - `timestamp` (string)
    - `project_id` (string)
    - `agent_type` (string)
    - `agent_role` (string)
    - `action_taken` (string)
    - `user_sub` (string)
    - `user_email` (string)
    - `policy_triggered` (string)
- `count` (integer)
- `configured` (boolean) — Whether the guardrail events table is configured.

---

### `GET /admin/registry`
**List agent registry**

Returns all agent registry entries with full configuration. Requires admin group membership.

**Response (200):** Agent registry entries

- `agents` (array)

---

### `PUT /admin/registry/{agent_type}`
**Update agent registry entry**

Update an agent's registry configuration. Requires admin group membership.

**Parameters:**

- `agent_type` (path) *(required)*

**Request body:**

- `display_name` (string)
- `icon` (string)
- `color` (string)
- `sort_order` (integer)
- `enabled` (boolean)
- `finding_schema` (string)
- `judge_defaults` (string)
- `default_depth` (string) — Overrides the AI planner's depth for this agent. Users can still customize per-review.

**Response (200):** Updated agent entry

---

### `GET /admin/standards`
**List standards corpus**

Returns all documents in the standards S3 bucket with their metadata sidecars. Requires admin group membership.

**Response (200):** Standards corpus listing

- `standards` (array)
  *Array items:*
    - `key` (string) — S3 object key
    - `standard_id` (string) — Standard identifier derived from directory name
    - `source_type` (string) — Standard source type from metadata sidecar
    - `size_bytes` (integer) — File size in bytes
    - `last_modified` (string) — Last modified timestamp
    - `has_metadata` (boolean) — Whether a metadata sidecar exists
- `count` (integer)
- `bucket` (string) — Standards S3 bucket name

---

### `POST /admin/standards`
**Upload a new standard**

Validates inputs, writes the metadata sidecar to S3, and returns a pre-signed URL for the caller to upload the content file. Supports any format accepted by Bedrock KB (md, pdf, txt, html, doc, docx, ...

**Request body:**

- `standard_id` (string) *(required)* — Kebab-case identifier (e.g. cps-230)
- `source_type` (string) *(required)* — Standard source type
- `jurisdiction` (string) — Geographic/regulatory scope
- `industry` (string) — Sector applicability
- `filename` (string) *(required)* — Original filename (extension determines S3 key suffix)
- `content_type` (string) — MIME type for the upload

**Response (201):** Standard metadata written, upload URL returned

- `upload_url` (string) — Pre-signed S3 URL for uploading the .md file
- `s3_key` (string) — S3 key where the file will be stored
- `metadata_written` (boolean) — Whether the metadata sidecar was written

---

### `POST /admin/standards/sync`
**Trigger KB ingestion job**

Starts a Bedrock Knowledge Base ingestion job to sync the standards S3 bucket with the KB index. Requires admin group membership.

**Response (200):** Ingestion job started

- `ingestion_job_id` (string)
- `status` (string)

---

### `GET /admin/standards/sync-status`
**Poll KB ingestion job status**

Returns the status of the most recent Bedrock KB ingestion job, including statistics when complete. Requires admin group membership.

**Response (200):** Latest ingestion job status

- `status` (string)
- `ingestion_job_id` (string)
- `started_at` (string)
- `completed_at` (string)
- `statistics` (object)
  - `documents_scanned` (integer)
  - `documents_indexed` (integer)
  - `documents_failed` (integer)

---

### `DELETE /admin/standards/{standard_id}`
**Delete a standard**

Deletes all objects under the standard's S3 prefix (the .md file and its metadata sidecar). The document is removed from the KB on the next sync. Requires admin group membership.

**Parameters:**

- `standard_id` (path) *(required)* — Kebab-case standard identifier

**Response (200):** Standard deleted

- `standard_id` (string)
- `objects_deleted` (integer)

---

### `PUT /admin/standards/{standard_id}/metadata`
**Edit standard metadata**

Rewrites the metadata sidecar without touching the content file. Use to correct source_type, add jurisdiction/industry tags, or update metadata after initial upload. Discovers the actual content file ...

**Parameters:**

- `standard_id` (path) *(required)* — Kebab-case standard identifier

**Request body:**

- `source_type` (string) *(required)*
- `jurisdiction` (string) — Geographic/regulatory scope
- `industry` (string) — Sector applicability

**Response (200):** Metadata updated

- `standard_id` (string)
- `metadata_written` (boolean)

---

## Agents

### `GET /agents`
**List available review agents**

Returns the agent registry — all available review agent types with their display metadata (name, icon, color, description) and capabilities. Used by the frontend to dynamically render agent tabs, chat...

**Response (200):** List of available agents

- `agents` (array)
  *Array items:*
    - `agent_type` (string)
    - `display_name` (string)
    - `icon` (string)
    - `color` (string)
    - `description` (string)
    - `category` (string)
    - `has_review_agent` (boolean)
    - `has_chat_agent` (boolean)
    - `has_judge_agent` (boolean)
    - `enabled` (boolean)
    - `sort_order` (integer)

---

## Analytics

### `GET /analytics/coverage/{project_id}`
**Get coverage matrix**

Coverage matrix showing findings by document section per agent for a specific review.

**Parameters:**

- `project_id` (path) *(required)* — Unique project identifier

**Response (200):** Coverage matrix data

- `matrix` (object)
- `sections` (array)
- `agents` (array)

---

### `GET /analytics/summary`
**Get analytics summary**

Aggregated quality scores, feedback rates, and recent review stats across all completed reviews.

**Response (200):** Analytics summary

- `agent_scores` (object)
- `feedback_summary` (object)
- `review_count` (integer)
- `recent_reviews` (array)

---

### `GET /analytics/trends`
**Get quality trends**

Time series quality data filterable by agent and date range.

**Parameters:**

- `agent` (query) *(optional)* — Filter by agent type
- `limit` (query) *(optional)* — Max data points

**Response (200):** Trend data points

- `data_points` (array)
- `count` (integer)

---

## Contexts

### `POST /contexts`
**Create a new context document**

Creates a new organizational context document and returns a pre-signed S3 URL for upload. Context documents describe business environment, regulatory requirements, and technology standards. They are a...

**Request body:**

- `name` (string) *(required)* — Context document name
- `description` (string) — Brief description

**Response (201):** Context created successfully

- `context_id` (string)
- `name` (string)
- `upload_url` (string)
- `upload_expires_at` (string)
- `created_at` (string)

---

### `GET /contexts`
**List all context documents**

Returns all organizational context documents

**Response (200):** List of context documents

- `contexts` (array)
  *Array items:*
    - `context_id` (string)
    - `name` (string)
    - `description` (string)
    - `created_at` (string)
- `count` (integer)

---

### `GET /contexts/{context_id}`
**Get context document details**

**Parameters:**

- `context_id` (path) *(required)*

**Response (200):** Context document details

- `context_id` (string)
- `name` (string)
- `description` (string)
- `created_at` (string)

---

### `DELETE /contexts/{context_id}`
**Delete a context document**

Deletes the context document and its S3 file. Projects referencing it will lose their context.

**Parameters:**

- `context_id` (path) *(required)*

**Response (200):** Context deleted successfully

- `context_id` (string)
- `deleted` (boolean)

---

### `GET /contexts/{context_id}/content`
**Get context document content**

Returns the full text content of the context document from S3.

**Parameters:**

- `context_id` (path) *(required)*

**Response (200):** Context document content

- `context_id` (string)
- `content` (string)

---

### `PUT /contexts/{context_id}/content`
**Update context document content**

Replaces the context document content in S3.

**Parameters:**

- `context_id` (path) *(required)*

**Request body:**

- `content` (string) *(required)* — Updated markdown content

**Response (200):** Content updated successfully

- `context_id` (string)
- `updated` (boolean)

---

## Health

### `GET /health`
**Health check**

Returns API health status

**Response (200):** API is healthy

- `status` (string)
- `timestamp` (string)

---

## Projects

### `POST /projects`
**Create a new project**

Creates a new project and returns a pre-signed S3 URL for document upload. The pre-signed URL is valid for 15 minutes.

**Request body:**

- `name` (string) *(required)* — Project name
- `description` (string) — Project description (optional)
- `context_id` (string) — Organizational context document ID (optional). Links the project to a context for tailored reviews.
- `files` (array) *(required)* — List of files to upload. At least one file is required.
  *Array items:*
    - `filename` (string) *(required)* — Original filename

**Response (201):** Project created successfully

---

### `GET /projects`
**List all projects**

Returns a list of all projects, sorted by creation date (newest first)

**Parameters:**

- `status` (query) *(optional)* — Filter by project status
- `limit` (query) *(optional)* — Maximum number of results

**Response (200):** List of projects

---

### `GET /projects/{project_id}`
**Get project details**

Returns project metadata, latest review results, and chat history

**Parameters:**

- `project_id` (path) *(required)* — Unique project identifier

**Response (200):** Project details

---

### `DELETE /projects/{project_id}`
**Delete a project**

Deletes a project and all associated data including reviews, chat history, and the uploaded design document from S3.

**Parameters:**

- `project_id` (path) *(required)* — Unique project identifier

**Response (200):** Project deleted successfully

- `project_id` (string)
- `items_deleted` (integer)
- `document_deleted` (boolean)

---

### `GET /projects/{project_id}/document`
**Get uploaded document content**

Returns the text content of the design document uploaded for this project.

**Parameters:**

- `project_id` (path) *(required)* — Unique project identifier

**Response (200):** Document content

- `project_id` (string)
- `content` (string)
- `s3_key` (string)

---

### `POST /projects/{project_id}/feedback`
**Submit feedback on a finding**

Submit thumbs up/down feedback on an individual finding. Per-user — each user can rate each finding independently.

**Parameters:**

- `project_id` (path) *(required)* — Unique project identifier

**Request body:**

- `finding_id` (string) *(required)* — Finding identifier
- `agent_type` (string) *(required)* — Agent type
- `value` (string) *(required)* — Feedback value

**Response (201):** Feedback submitted

- `finding_id` (string)
- `agent_type` (string)
- `value` (string)
- `timestamp` (string)

---

### `GET /projects/{project_id}/feedback`
**Get all feedback for a project**

Returns all user feedback for a project's findings.

**Parameters:**

- `project_id` (path) *(required)* — Unique project identifier

**Response (200):** Project feedback

- `feedback` (array)
  *Array items:*
    - `finding_id` (string)
    - `agent_type` (string)
    - `value` (string)
    - `user` (string)
    - `timestamp` (string)
- `count` (integer)

---

## Reviews

### `GET /projects/{project_id}/report`
**Generate markdown report**

Generates a markdown report from the latest completed review's findings. The report is rendered on-demand from the post quality-merge findings payload in S3, so it always reflects the latest data. Inc...

**Parameters:**

- `project_id` (path) *(required)* — Unique project identifier

**Response (200):** Markdown report generated

- `report` (string) — Complete markdown report
- `content_type` (string)

---

### `POST /projects/{project_id}/review`
**Trigger document review**

Initiates a comprehensive review of the uploaded document. The AI planner analyzes the document and produces a review plan, which is then executed by specialized agents.

**Parameters:**

- `project_id` (path) *(required)* — Unique project identifier

**Response (200):** Review completed successfully

---

### `POST /projects/{project_id}/reviews/{review_id}/abort`
**Abort a running review**

Stops a running review by terminating the Step Functions execution. The project status is set to failed. Only works when the project status is in_progress.

**Parameters:**

- `project_id` (path) *(required)* — Unique project identifier
- `review_id` (path) *(required)* — Review identifier (or 'latest' for most recent)

**Request body:**

- `reason` (string) — Optional abort reason

**Response (200):** Review aborted

- `status` (string)
- `review_id` (string)
- `project_id` (string)

---

### `POST /projects/{project_id}/reviews/{review_id}/approve`
**Approve review plan**

Approves a pending review plan, resuming the Step Functions execution. Optionally accepts a modified plan in the request body.

**Parameters:**

- `project_id` (path) *(required)* — Unique project identifier
- `review_id` (path) *(required)* — Review identifier (or 'latest' for most recent)

**Request body:**

- `plan` (object)
  - `plan_id` (string)
  - `document_type` (string)
  - `complexity` (string)
  - `rationale` (string)
  - `status` (string)
  - `groups` (array)
    *Array items:*
      - `group_id` (string)
      - `label` (string)
      - `execution` (string)
      - `agents` (array)
        *Array items:*
          - `agent_type` (string)
          - `depth` (string)
          - `focus_areas` (array)
          - `prompt_addendum` (string)

**Response (200):** Plan approved

- `status` (string)
- `review_id` (string)

---

### `GET /projects/{project_id}/reviews/{review_id}/events`
**Get review event log**

Returns the persisted progress events for a review. Events are recorded during workflow execution and can be replayed to reconstruct the full UI state (flow graph, event timeline, agent metrics) after...

**Parameters:**

- `project_id` (path) *(required)* — Unique project identifier
- `review_id` (path) *(required)* — Review identifier (or 'latest' for most recent)

**Response (200):** Review event log

- `review_id` (string)
- `events` (array)
  *Array items:*
    - `event` (string) — Event type (e.g. agent_started, plan_created)
    - `detail` (object) — Event-specific payload
    - `ts` (string) — ISO 8601 timestamp

---

### `GET /projects/{project_id}/reviews/{review_id}/plan`
**Get review plan**

Returns the stored review plan for a given review. Use review_id='latest' to get the most recent plan. Used for page refresh recovery during the plan approval window.

**Parameters:**

- `project_id` (path) *(required)* — Unique project identifier
- `review_id` (path) *(required)* — Review identifier (or 'latest' for most recent)

**Response (200):** Review plan

---

### `POST /projects/{project_id}/reviews/{review_id}/reject`
**Reject review plan**

Rejects a pending review plan, failing the Step Functions execution. The project status returns to its pre-review state.

**Parameters:**

- `project_id` (path) *(required)* — Unique project identifier
- `review_id` (path) *(required)* — Review identifier (or 'latest' for most recent)

**Request body:**

- `reason` (string) — Optional rejection reason

**Response (200):** Plan rejected

- `status` (string)
- `review_id` (string)

---
