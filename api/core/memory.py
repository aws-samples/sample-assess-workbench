"""Shared memory record building for AgentCore Memory.

Single source of truth for the record format used when storing review
findings in AgentCore Memory. Both ``invoke_review_agent.py`` (per-agent
write immediately after completion) and ``aggregate_results.py`` (batch
write at aggregation) import from here.

The content template, namespace pattern, and ``requestIdentifier``
convention are defined once — changes here propagate to both write paths.
AgentCore deduplicates on ``requestIdentifier``, so the per-agent write
and the aggregation batch write are idempotent.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# AgentCore batch_create_memory_records accepts up to 100 records per call.
BATCH_SIZE = 100


def build_finding_record(
    finding: dict,
    agent_type: str,
    project_id: str,
    project_name: str = "",
) -> dict:
    """Build a single AgentCore Memory record from a finding.

    Args:
        finding: Finding dict with at minimum ``id``, ``title``,
            ``severity``, ``description``, ``recommendation``.
            Optional: ``references`` (list of strings).
        agent_type: The agent type that produced this finding
            (e.g. ``"security"``, ``"risk"``).
        project_id: Project identifier for namespace scoping.
        project_name: Human-readable project name for context in
            the stored text. Defaults to empty string (omitted
            from content when empty).

    Returns:
        Dict ready for ``batch_create_memory_records`` with keys:
        ``content``, ``namespaces``, ``requestIdentifier``, ``timestamp``.

    Raises:
        KeyError: If required finding fields (``id``, ``title``,
            ``severity``, ``description``, ``recommendation``) are missing.
    """
    references = ", ".join(finding.get("references", []))

    # Build content text — the semantic payload that gets embedded and
    # searched. Includes enough context for the LLM to use the finding
    # without needing a follow-up lookup.
    content_parts = [
        f"Finding: {finding['title']}",
        "",
        f"Severity: {finding['severity']}",
        f"Agent: {agent_type}",
        "",
        "Description:",
        finding["description"],
        "",
        "Recommendation:",
        finding["recommendation"],
        "",
        f"References: {references}",
    ]
    if project_name:
        content_parts.extend(["", f"Project: {project_name}"])
    content_parts.extend(["", f"Project ID: {project_id}"])

    return {
        "content": {"text": "\n".join(content_parts) + "\n"},
        "namespaces": [f"/findings/{project_id}/{agent_type}"],
        "requestIdentifier": f"{project_id}-{finding['id']}",
        "timestamp": datetime.now(tz=timezone.utc),
    }


def build_finding_records(
    findings: list[dict],
    agent_type: str,
    project_id: str,
    project_name: str = "",
) -> list[dict]:
    """Build AgentCore Memory records for a list of findings.

    Convenience wrapper over :func:`build_finding_record` for building
    records from a single agent's findings list.

    Args:
        findings: List of finding dicts from the agent's structured output.
        agent_type: The agent type that produced these findings.
        project_id: Project identifier for namespace scoping.
        project_name: Human-readable project name (optional).

    Returns:
        List of record dicts ready for ``batch_create_memory_records``.
    """
    return [
        build_finding_record(finding, agent_type, project_id, project_name)
        for finding in findings
    ]


def store_records_in_memory(
    client,
    memory_id: str,
    records: list[dict],
) -> int:
    """Write memory records in batches, returning the count of successes.

    Handles the 100-record batch limit and logs failures per-record.
    This is the shared write path — callers handle their own error
    policy (invoke_review_agent lets failures propagate as warnings,
    aggregate_results catches at a higher level).

    Args:
        client: A ``bedrock-agentcore`` boto3 client.
        memory_id: The AgentCore Memory resource ID.
        records: List of record dicts from :func:`build_finding_records`.

    Returns:
        Number of successfully stored records.

    Raises:
        ClientError: On AWS API failure (callers decide whether to
            catch or propagate).
    """
    stored_count = 0
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        resp = client.batch_create_memory_records(
            memoryId=memory_id, records=batch,
        )
        stored_count += len(resp.get("successfulRecords", []))
        failed = resp.get("failedRecords", [])
        if failed:
            for f in failed:
                logger.warning(
                    "Failed to store %s: %s",
                    f.get("requestIdentifier"),
                    f.get("errorMessage"),
                )

    logger.info("Stored %d/%d records in memory %s", stored_count, len(records), memory_id)
    return stored_count
