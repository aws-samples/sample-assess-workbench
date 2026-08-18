"""Agent tools for Bedrock Knowledge Base retrieval.

Two tools backed by separate Bedrock Knowledge Bases:

- ``search_document`` — queries the Document Index KB for project
  document chunks, filtered by ``project_id`` metadata.
- ``lookup_standard`` — queries the Standards KB for compliance
  reference material, filtered by ``standard_id`` metadata with
  semantic search. ``section`` narrows the query text semantically;
  it is not a metadata filter (KB chunks carry no per-section metadata).

Both use the ``bedrock-agent-runtime`` Retrieve API with metadata
filtering + semantic search. Per-request context (KB IDs, project_id)
is passed via Strands ``invocation_state``.

Error handling: ``handle_tool_errors`` from ``errors.py`` catches
expected AWS API errors at the tool-to-LLM boundary.
"""

import logging
import re
from typing import Any

import boto3
from strands import tool
from strands.types.tools import ToolContext

from shared.tools.errors import handle_tool_errors

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 10

# Cache available standards for the container lifetime to avoid
# querying the KB on every tool call. Populated on first call to
# lookup_standard via _get_available_standards().
_available_standards_cache: list[str] | None = None


def _get_kb_runtime_client():
    """Create a bedrock-agent-runtime client per call.

    Same thread-safety rationale as ``_get_agentcore_client`` in
    ``memory_tools.py`` — AgentCore containers handle concurrent
    requests, and boto3 clients are not thread-safe.
    """
    return boto3.client("bedrock-agent-runtime")


def _retrieve_from_kb(
    kb_id: str,
    query: str,
    metadata_filter: dict[str, Any] | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """Retrieve chunks from a Bedrock Knowledge Base.

    Args:
        kb_id: The Bedrock Knowledge Base ID to query.
        query: Semantic search query.
        metadata_filter: Optional metadata filter dict for the Retrieve
            API. Structure follows the Bedrock KB RetrievalFilter spec.
        top_k: Maximum number of results to return.

    Returns:
        List of retrieval result dicts with ``content`` and ``score`` keys.

    Raises:
        ClientError: On AWS API failure.
        BotoCoreError: On SDK-level failure.
    """
    client = _get_kb_runtime_client()

    retrieval_config: dict[str, Any] = {
        "vectorSearchConfiguration": {
            "numberOfResults": top_k,
        }
    }
    if metadata_filter:
        retrieval_config["vectorSearchConfiguration"]["filter"] = metadata_filter

    response = client.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration=retrieval_config,
    )
    return response.get("retrievalResults", [])


def _format_kb_results(results: list[dict[str, Any]]) -> str:
    """Format KB retrieval results into a readable string for the LLM.

    Args:
        results: List of retrieval result dicts from ``_retrieve_from_kb``.

    Returns:
        Formatted string with each chunk separated by double newlines.
    """
    chunks = []
    for r in results:
        text = r.get("content", {}).get("text", "").strip()
        if text:
            chunks.append(text)
    return "\n\n---\n\n".join(chunks)


def _get_available_standards(kb_id: str) -> list[str]:
    """Query the Standards KB for distinct standard_id metadata values.

    Results are cached for the container lifetime. Returns an empty list
    if the query fails (the tool still works — it just won't list
    available standards in error messages).

    Args:
        kb_id: The Standards Knowledge Base ID.

    Returns:
        Sorted list of standard_id values found in the KB.
    """
    global _available_standards_cache
    if _available_standards_cache is not None:
        return _available_standards_cache

    try:
        # Query with a broad search to discover indexed standards.
        # We look at metadata from returned results to extract
        # distinct standard_id values.
        results = _retrieve_from_kb(kb_id, "list all standards", top_k=50)
        standard_ids = set()
        for r in results:
            metadata = r.get("metadata", {})
            sid = metadata.get("standard_id", "")
            if sid:
                standard_ids.add(sid)
        _available_standards_cache = sorted(standard_ids)
    except Exception:
        logger.warning("Failed to query available standards", exc_info=True)
        _available_standards_cache = []

    return _available_standards_cache


@tool(context=True)
@handle_tool_errors
def search_document(
    query: str,
    section_hint: str = "",
    tool_context: ToolContext = None,
) -> str:
    """Search the document under review for sections relevant to a query.

    Use this to find specific parts of the document rather than scanning
    the entire content. Especially useful for large documents.

    Args:
        query: What you're looking for (e.g., "authentication mechanism",
            "database schema", "deployment pipeline").
        section_hint: Optional heading or section name to narrow the search.
    """
    document_kb_id = tool_context.invocation_state.get("document_kb_id")
    project_id = tool_context.invocation_state.get("project_id")

    if not document_kb_id:
        raise ValueError("search_document missing required invocation_state: ['document_kb_id']")
    if not project_id:
        raise ValueError("search_document missing required invocation_state: ['project_id']")

    # Append section_hint to query for semantic narrowing — not a metadata
    # filter since document chunks don't have section-level metadata tags.
    search_query = f"{query} {section_hint}".strip() if section_hint else query

    # Filter by project_id metadata for project isolation.
    metadata_filter = {
        "equals": {
            "key": "project_id",
            "value": project_id,
        }
    }

    results = _retrieve_from_kb(document_kb_id, search_query, metadata_filter)
    if not results:
        return "No matching sections found in the document."
    return _format_kb_results(results)


def _normalize_standard_id(standard: str) -> str:
    """Normalize a free-form standard name to the kebab-case ``standard_id``.

    The Standards KB filters ``standard_id`` by exact match, but models pass the
    human form ("CPS 234") rather than the metadata value ("cps-234"). Lowercase
    and collapse whitespace/underscore runs to single hyphens so common variants
    resolve. This cannot fix a genuinely different name (e.g. "APP 11" vs
    "australian-privacy-principles") — the not-found path lists the available ids
    for that case.

    Args:
        standard: Free-form standard identifier from the model.

    Returns:
        Kebab-case standard id (lowercase, hyphen-separated, trimmed).
    """
    normalized = re.sub(r"[\s_]+", "-", standard.strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized.strip("-")


@tool(context=True)
@handle_tool_errors
def lookup_standard(
    standard: str,
    section: str = "",
    query: str = "",
    tool_context: ToolContext = None,
) -> str:
    """Look up a compliance standard, framework, or regulation.

    Use to cite accurate, current text from standards rather than relying on
    training data. Returns the most relevant chunks for the standard.

    Retrieval filters by ``standard_id`` only and semantically searches that
    standard's chunks. ``section`` narrows the search *semantically* — it is
    added to the query text, not applied as a metadata filter. Standards KB
    chunks carry no per-section metadata, so a section metadata filter would
    match nothing.

    Args:
        standard: Standard identifier; matched case-insensitively against the
            kebab-case id (e.g. "CPS 234" resolves to "cps-234", "owasp-top-10",
            "gdpr").
        section: Specific section, paragraph, or article to bias the search
            toward (e.g. "paragraph 35", "Art.32", "APP 11"). Optional.
        query: Free-text search within the standard. At least one of section or
            query must be provided.
    """
    standards_kb_id = tool_context.invocation_state.get("standards_kb_id")

    if not standards_kb_id:
        raise ValueError("lookup_standard missing required invocation_state: ['standards_kb_id']")

    if not section and not query:
        return (
            "Please provide either a section identifier (e.g., 'paragraph 35', "
            "'Art.32') or a free-text query to search within the standard."
        )

    standard_id = _normalize_standard_id(standard)

    # Filter by standard_id only. Section is folded into the semantic query
    # rather than applied as a metadata filter: KB chunks have no per-section
    # metadata (see StandardsService._build_sidecar), so a section filter would
    # match nothing.
    metadata_filter = {"equals": {"key": "standard_id", "value": standard_id}}
    search_query = " ".join(part for part in (query, section) if part).strip() or standard_id

    results = _retrieve_from_kb(standards_kb_id, search_query, metadata_filter)
    if not results:
        available = _get_available_standards(standards_kb_id)
        available_str = ", ".join(available) if available else "unknown"
        return (
            f"Standard '{standard}' (looked up as '{standard_id}') not found in "
            f"the corpus. Currently indexed standards: {available_str}. "
            f"Cite from your training knowledge and note the citation is unverified."
        )
    return _format_kb_results(results)
