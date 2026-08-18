#!/usr/bin/env python3
"""Generate well-structured markdown standards for the Bedrock Knowledge Base.

This script generates standards content from source material (PDFs, markdown files,
or web pages) using the Bedrock Converse API. It produces one markdown file per
standard with clear ## headings for the hierarchical chunker, plus a metadata
sidecar for KB filtering.

Workflow:
    1. Add source material to standards/ (PDF or markdown) or note a URL
    2. Add a manifest entry in this script (see MANIFEST below)
    3. Generate:  python scripts/generate_standard.py cps-230
    4. Update cross-references:  python scripts/generate_standard.py --update-refs
    5. Deploy to KB:  task deploy:knowledge-bases

Source types:
    - Local PDF:      source="standards/some-file.pdf"  (extracted via PyMuPDF)
    - Local Markdown: source="standards/some-file.md"   (read directly)
    - URL:            source="https://..."              (fetch HTML, extract text)

Source type taxonomy (authority levels):
    - prudential_standard:    Binding APRA prudential standards (CPS 230, CPS 234)
    - regulatory_guidance:    APRA practice guides, response papers (CPG 230, CPG 234)
    - regulatory_commentary:  APRA speeches, supervisory insights
    - industry_framework:     OWASP, NIST CSF, AWS Well-Architected
    - legislation:            Privacy Act, statutes

License types:
    - cc-by-3.0-au:  Creative Commons Attribution 3.0 AU (APRA) — use directly
    - open-source:   Open-source content (OWASP, CWE) — use directly

Usage:
    python scripts/generate_standard.py cps-230          # Generate one standard
    python scripts/generate_standard.py --all            # Generate all with sources
    python scripts/generate_standard.py --list           # Show manifest status
    python scripts/generate_standard.py --update-refs    # Update cross-references
    python scripts/generate_standard.py --model us.anthropic.claude-sonnet-4-6 cps-230
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import textwrap
import time
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import boto3
from botocore.config import Config as BotocoreConfig
from botocore.exceptions import ClientError


# ── Logging ──────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

STANDARDS_DIR = Path(__file__).resolve().parent.parent / "standards"
DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds

SourceType = Literal[
    "prudential_standard",
    "regulatory_guidance",
    "regulatory_commentary",
    "industry_framework",
    "legislation",
]

LicenseType = Literal["cc-by-3.0-au", "open-source"]


# ── Manifest Entry ───────────────────────────────────────────────


@dataclass(frozen=True)
class ManifestEntry:
    """A single standard/source in the generation manifest.

    Attributes:
        standard_id: Unique identifier, used as directory name and metadata key.
            Convention: lowercase with hyphens (e.g. "cps-230", "owasp-top-10").
        display_name: Human-readable name for the standard.
        source_type: Authority level taxonomy — determines how agents frame findings.
        license: Copyright/license status — determines generation approach
            (direct structuring vs. paraphrasing).
        description: Generation hint — tells the model what to focus on.
            Be specific: "include CWE mappings" or "focus on paragraph-level requirements".
        source: Path to source material (PDF or markdown) or URL to fetch.
            If None, the standard cannot be generated (no source = no generation).
        related: List of related standard_ids for cross-referencing.
            Relationships are resolved bidirectionally by --update-refs.
        effective_date: When the standard took effect (for the authority header).
        enforcement: Brief enforcement context (for the authority header).
        pages: Optional page ranges to extract from a PDF source (e.g. "1-50,75-120").
            If None, all pages are extracted. Useful for large documents where only
            specific sections are relevant. Ignored for non-PDF sources.
    """

    standard_id: str
    display_name: str
    source_type: SourceType
    license: LicenseType
    description: str
    source: str | None = None
    related: list[str] = field(default_factory=list)
    effective_date: str | None = None
    enforcement: str | None = None
    pages: str | None = None


# ── Generation Manifest ──────────────────────────────────────────
# Add new standards here. If source is None, the entry is a placeholder
# and will be skipped during generation (no source = no generation).

MANIFEST: list[ManifestEntry] = [
    # ── Priority 1: APRA Prudential Standards + Practice Guides ──
    ManifestEntry(
        standard_id="cps-230",
        display_name="CPS 230 — Operational Risk Management",
        source_type="prudential_standard",
        license="cc-by-3.0-au",
        description=(
            "Binding APRA prudential standard. Focus on specific requirements: "
            "critical operations identification, material service provider management, "
            "tolerance levels, business continuity planning, notification obligations. "
            "Preserve paragraph-level detail for citation. "
            "Attribution: © APRA, licensed under CC BY 3.0 AU."
        ),
        source="standards/cps-230/Prudential Standard CPS 230 Operational Risk Management - clean.pdf",
        related=["cpg-230", "cps-230-response-paper"],
        effective_date="1 July 2025",
        enforcement="Non-compliance may result in APRA supervisory action",
    ),
    ManifestEntry(
        standard_id="cpg-230",
        display_name="CPG 230 — Operational Risk Management Practice Guide",
        source_type="regulatory_guidance",
        license="cc-by-3.0-au",
        description=(
            "APRA practice guide for CPS 230 implementation. Focus on: tolerance level "
            "setting guidance, critical operations assessment methodology, service provider "
            "management better practices, BCP testing expectations. Distinguish clearly "
            "between guidance ('APRA expects...') and binding requirements (which are in "
            "CPS 230, not this document). "
            "Attribution: © APRA, licensed under CC BY 3.0 AU."
        ),
        source="standards/cpg-230/Prudential Practice Guide CPG 230 Operational Risk Management.pdf",
        related=["cps-230", "cps-230-response-paper"],
        effective_date="1 July 2025",
        enforcement="Non-binding guidance — signals how APRA will assess CPS 230 compliance",
    ),
    ManifestEntry(
        standard_id="cps-234",
        display_name="CPS 234 — Information Security",
        source_type="prudential_standard",
        license="cc-by-3.0-au",
        description=(
            "Binding APRA prudential standard on information security. Focus on: "
            "information security capability requirements, policy framework, information "
            "asset identification and classification, control implementation, incident "
            "management and APRA notification, testing by qualified specialists. "
            "Preserve paragraph-level detail. "
            "Attribution: © APRA, licensed under CC BY 3.0 AU."
        ),
        source="standards/cps-234/cps_234_july_2019_for_public_release.pdf",
        related=["cpg-234", "apra-smith-speech-2025"],
        effective_date="1 July 2019",
        enforcement="Non-compliance may result in APRA supervisory action",
    ),
    ManifestEntry(
        standard_id="cpg-234",
        display_name="CPG 234 — Information Security Practice Guide",
        source_type="regulatory_guidance",
        license="cc-by-3.0-au",
        description=(
            "APRA practice guide for CPS 234 implementation. Focus on: information "
            "security capability assessment, control testing expectations, incident "
            "notification process, third-party security assurance. Distinguish guidance "
            "from binding requirements. "
            "Attribution: © APRA, licensed under CC BY 3.0 AU."
        ),
        source="standards/cpg-234/cpg_234_information_security_june_2019_1.pdf",
        related=["cps-234", "apra-smith-speech-2025"],
        effective_date="1 July 2019",
        enforcement="Non-binding guidance — signals how APRA will assess CPS 234 compliance",
    ),
    # ── Priority 2: Regulatory Guidance & Commentary ─────────────
    ManifestEntry(
        standard_id="cps-230-response-paper",
        display_name="CPS 230 Response Paper — Key Policy Decisions",
        source_type="regulatory_guidance",
        license="cc-by-3.0-au",
        description=(
            "APRA's response to CPS 230 consultation submissions (July 2023). Focus on: "
            "transition timelines, proportionality guidance, 'unless otherwise justified' "
            "flexibility on critical operations, notification expectations, material "
            "service provider thresholds. High-value for calibrating findings — shows "
            "how APRA interprets the standard. "
            "Attribution: © APRA, licensed under CC BY 3.0 AU."
        ),
        source="https://www.apra.gov.au/operational-risk-management-0",
        related=["cps-230", "cpg-230"],
        effective_date="July 2023",
        enforcement="Authoritative interpretation — signals how APRA will assess compliance",
    ),
    ManifestEntry(
        standard_id="apra-smith-speech-2025",
        display_name="APRA Member Suzanne Smith — Speech to FSA Forum 2025",
        source_type="regulatory_commentary",
        license="cc-by-3.0-au",
        description=(
            "Extract key regulatory signals: sector-wide CPS 234 tripartite assessment "
            "findings (incomplete asset classification, inadequate authentication, sporadic "
            "third-party assurance, irregular testing), APRA's focus on concentration risk, "
            "legacy systems, AI governance expectations. Include the six lines of inquiry "
            "for internal audit. "
            "Attribution: © APRA, licensed under CC BY 3.0 AU."
        ),
        source="https://www.apra.gov.au/news-and-publications/apra-member-suzanne-smith-speech-to-financial-services-and-asx-sector",
        related=["cps-234", "cpg-234"],
        effective_date="2025",
        enforcement="Non-binding — indicates current supervisory focus and emerging expectations",
    ),
    # ── Priority 3: Upgrade Existing Placeholders ────────────────
    ManifestEntry(
        standard_id="owasp-top-10",
        display_name="OWASP Top 10 — 2025",
        source_type="industry_framework",
        license="open-source",
        description=(
            "Full descriptions for each category (A01–A10, 2025 edition). Include: "
            "CWE mappings per category, detection guidance, prevention measures, "
            "example attack scenarios. This is open-source content — reproduce faithfully. "
            "Note: the 2025 edition replaces the 2021 edition with updated categories "
            "including Software Supply Chain Failures (A03) and Mishandling of "
            "Exceptional Conditions (A10)."
        ),
        source="standards/owasp-top-10/owasp-top-10-2025-source.md",
        related=[],
        effective_date="2025",
        enforcement="Advisory — widely adopted industry standard, not legally binding",
    ),
    # ── Priority 4: Additional Standards ─────────────────────────
    ManifestEntry(
        standard_id="australian-privacy-principles",
        display_name="Australian Privacy Principles (Privacy Act 1988)",
        source_type="legislation",
        license="cc-by-3.0-au",
        description=(
            "All 13 Australian Privacy Principles. Focus on: APP 11 (security of personal "
            "information), APP 8 (cross-border disclosure), APP 1 (open and transparent "
            "management), Notifiable Data Breaches scheme. Include specific obligations "
            "relevant to financial services. "
            "Attribution: Australian Government, licensed under CC BY 3.0 AU."
        ),
        source="standards/app-guidelines/Consolidated-APP-guidelines.pdf",
        related=[],
        effective_date="12 March 2014 (current APPs)",
        enforcement="Legal obligation — enforceable by the OAIC",
    ),
]

# Build lookup for fast access
MANIFEST_BY_ID: dict[str, ManifestEntry] = {e.standard_id: e for e in MANIFEST}


# ── Source Material Extraction ───────────────────────────────────


def _detect_source_type(source: str) -> Literal["pdf", "markdown", "url"]:
    """Detect the source material type from the source string.

    Args:
        source: Path to a local file or a URL.

    Returns:
        One of "pdf", "markdown", or "url".

    Raises:
        ValueError: If the source type cannot be determined.
    """
    if source.startswith("http://") or source.startswith("https://"):
        return "url"
    if source.endswith(".pdf"):
        return "pdf"
    if source.endswith(".md"):
        return "markdown"
    raise ValueError(
        f"Cannot determine source type for '{source}'. "
        "Expected a .pdf file, .md file, or http(s):// URL."
    )


def _parse_page_ranges(pages_str: str, total_pages: int) -> list[int]:
    """Parse a page range string into a list of 0-indexed page numbers.

    Supports comma-separated ranges and single pages. Page numbers in the
    string are 1-indexed (human-friendly); returned indices are 0-indexed.

    Args:
        pages_str: Page range string, e.g. "1-50,75-120" or "1,3,5-10".
        total_pages: Total number of pages in the document.

    Returns:
        Sorted list of unique 0-indexed page numbers.

    Raises:
        ValueError: If the page range string is malformed or out of bounds.
    """
    indices: set[int] = set()
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start_str, end_str = part.split("-", 1)
            start = int(start_str.strip())
            end = int(end_str.strip())
            if start < 1 or end > total_pages or start > end:
                raise ValueError(f"Invalid page range '{part}': must be 1-{total_pages}")
            indices.update(range(start - 1, end))
        else:
            page = int(part.strip())
            if page < 1 or page > total_pages:
                raise ValueError(f"Invalid page number '{part}': must be 1-{total_pages}")
            indices.add(page - 1)
    return sorted(indices)


def _extract_pdf_text(pdf_path: Path, pages: str | None = None) -> str:
    """Extract text from a PDF file using PyMuPDF with mechanical cleanup.

    Performs a light cleanup pass:
    - Removes lines that are just a page number
    - Removes repeated headers/footers (lines appearing on >50% of pages)
    - Collapses runs of blank lines

    Args:
        pdf_path: Path to the PDF file.
        pages: Optional page range string (e.g. "1-50,75-120"). If None,
            all pages are extracted.

    Returns:
        Cleaned extracted text.

    Raises:
        FileNotFoundError: If the PDF file does not exist.
        ImportError: If PyMuPDF is not installed.
        RuntimeError: If PDF extraction fails.
        ValueError: If page ranges are invalid.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise ImportError(
            "PyMuPDF is required for PDF extraction. Install it: uv pip install PyMuPDF"
        ) from exc

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        raise RuntimeError(f"Failed to open PDF '{pdf_path}': {exc}") from exc

    # Extract text per page for header/footer detection
    page_texts: list[str] = []
    total_pages = len(doc)

    if pages:
        page_indices = _parse_page_ranges(pages, total_pages)
        for idx in page_indices:
            page_texts.append(doc[idx].get_text())
        logger.info("Extracting %d of %d pages (ranges: %s)", len(page_indices), total_pages, pages)
    else:
        for page in doc:
            page_texts.append(page.get_text())

    doc.close()

    if not page_texts:
        raise RuntimeError(f"PDF '{pdf_path}' contains no extractable text")

    # Detect repeated headers/footers: lines appearing on >50% of pages
    num_pages = len(page_texts)
    line_counts: Counter[str] = Counter()
    for text in page_texts:
        # Count unique lines per page (deduplicate within a page)
        unique_lines = set(line.strip() for line in text.splitlines() if line.strip())
        for line in unique_lines:
            line_counts[line] += 1

    repeated_lines = {
        line
        for line, count in line_counts.items()
        if count > num_pages * 0.5 and len(line) < 200  # short repeated lines only
    }

    # Clean and combine
    cleaned_lines: list[str] = []
    prev_blank = False
    for text in page_texts:
        for line in text.splitlines():
            stripped = line.strip()

            # Skip page numbers (lines that are just a number)
            if stripped.isdigit():
                continue

            # Skip repeated headers/footers
            if stripped in repeated_lines:
                continue

            # Collapse blank lines
            if not stripped:
                if not prev_blank:
                    cleaned_lines.append("")
                    prev_blank = True
                continue

            cleaned_lines.append(line)
            prev_blank = False

    result = "\n".join(cleaned_lines).strip()
    if not result:
        raise RuntimeError(f"PDF '{pdf_path}' produced no text after cleanup")

    logger.info(
        "Extracted %d chars from PDF (%d pages, removed %d repeated line patterns)",
        len(result),
        num_pages,
        len(repeated_lines),
    )
    return result


def _read_markdown_source(md_path: Path) -> str:
    """Read a local markdown file as source material.

    Args:
        md_path: Path to the markdown file.

    Returns:
        File contents as a string.

    Raises:
        FileNotFoundError: If the file does not exist.
        RuntimeError: If the file is empty.
    """
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown source not found: {md_path}")

    text = md_path.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError(f"Markdown source '{md_path}' is empty")

    logger.info("Read %d chars from markdown source", len(text))
    return text


class _HTMLTextExtractor(HTMLParser):
    """Extract visible text from HTML, skipping script and style content.

    A real parser handles the cases a tag-stripping regex cannot: unclosed
    tags, ``>`` characters inside attribute values, comments, and otherwise
    malformed markup. With ``convert_charrefs=True`` (the default), character
    and entity references in text are decoded automatically.
    """

    _SKIP_TAGS = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Enter a skipped region for script/style; else emit a separator.

        The separator prevents text in adjacent elements from being mashed
        together (e.g. ``<p>world</p><p>After</p>`` -> ``world After``).
        Redundant whitespace is collapsed by the caller.
        """
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif self._skip_depth == 0:
            self._chunks.append(" ")

    def handle_endtag(self, tag: str) -> None:
        """Leave a skipped region for script/style; else emit a separator."""
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif self._skip_depth == 0:
            self._chunks.append(" ")

    def handle_data(self, data: str) -> None:
        """Collect text content unless inside a skipped region."""
        if self._skip_depth == 0:
            self._chunks.append(data)

    def get_text(self) -> str:
        """Return the concatenated extracted text."""
        return "".join(self._chunks)


def _fetch_url_text(url: str) -> str:
    """Fetch an HTML page and extract its text content.

    Fetches the page and extracts visible text with a stdlib HTML parser
    (``_HTMLTextExtractor``), then collapses whitespace. No external
    dependencies beyond stdlib.

    Args:
        url: The URL to fetch.

    Returns:
        Extracted text content.

    Raises:
        ValueError: If the URL scheme is not http or https.
        RuntimeError: If the fetch fails or produces no content.
    """
    # Constrain the scheme to http(s). urlopen also accepts file:// and custom
    # schemes, which could turn a "fetch" into a local file read or SSRF. The
    # only caller routes here via _detect_source_type (http(s) only), but this
    # guard keeps the function safe for any future caller.
    scheme = urlsplit(url).scheme
    if scheme not in ("http", "https"):
        raise ValueError(f"Refusing to fetch non-HTTP(S) URL '{url}' (scheme: {scheme or 'none'})")

    logger.info("Fetching URL: %s", url)
    try:
        req = Request(url, headers={"User-Agent": "generate-standard/1.0"})
        with urlopen(req, timeout=30) as resp:  # nosec B310 — scheme validated above  # noqa: S310
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch URL '{url}': {exc}") from exc

    # Extract visible text with a real HTML parser. Regex-based tag stripping
    # is bypassable (unclosed tags, '>' inside attributes, malformed markup)
    # and can leave raw script/style content in the result.
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    extractor.close()
    text = extractor.get_text()
    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    text = text.strip()

    if not text:
        raise RuntimeError(f"URL '{url}' produced no text content after HTML stripping")

    logger.info("Extracted %d chars from URL", len(text))
    return text


def extract_source_material(entry: ManifestEntry) -> str:
    """Extract source material for a manifest entry.

    Detects the source type (PDF, markdown, URL) and extracts text accordingly.

    Args:
        entry: The manifest entry with a non-None source field.

    Returns:
        Extracted text content.

    Raises:
        ValueError: If source is None or type cannot be determined.
        FileNotFoundError: If a local file doesn't exist.
        RuntimeError: If extraction fails.
    """
    if entry.source is None:
        raise ValueError(f"No source material for '{entry.standard_id}'")

    source_kind = _detect_source_type(entry.source)

    if source_kind == "pdf":
        pdf_path = STANDARDS_DIR.parent / entry.source
        return _extract_pdf_text(pdf_path, pages=entry.pages)
    elif source_kind == "markdown":
        md_path = STANDARDS_DIR.parent / entry.source
        return _read_markdown_source(md_path)
    else:
        return _fetch_url_text(entry.source)


# ── Prompt Building ──────────────────────────────────────────────

SOURCE_TYPE_LABELS: dict[SourceType, str] = {
    "prudential_standard": "Prudential Standard (mandatory for APRA-regulated entities)",
    "regulatory_guidance": "Regulatory Guidance (non-binding, signals supervisory expectations)",
    "regulatory_commentary": "Regulatory Commentary (non-binding, signals supervisory focus)",
    "industry_framework": "Industry Framework (advisory, widely adopted)",
    "legislation": "Legislation (legal obligation)",
}

LICENSE_INSTRUCTIONS: dict[LicenseType, str] = {
    "cc-by-3.0-au": (
        "This content is licensed under Creative Commons Attribution 3.0 Australia. "
        "You may structure and organise the source material faithfully. Preserve "
        "specific requirement wording, paragraph references, and obligation language. "
        "Do not water down or over-generalise the requirements."
    ),
    "open-source": (
        "This is open-source content. Reproduce faithfully — preserve specific "
        "details, mappings, examples, and technical guidance."
    ),
}


def build_generation_prompt(entry: ManifestEntry, source_text: str) -> str:
    """Build the generation prompt for a standard.

    Args:
        entry: The manifest entry describing the standard.
        source_text: Extracted source material text.

    Returns:
        The complete prompt string for Bedrock Converse.
    """
    source_type_label = SOURCE_TYPE_LABELS[entry.source_type]
    license_instruction = LICENSE_INSTRUCTIONS[entry.license]

    effective_line = f"**Effective:** {entry.effective_date}" if entry.effective_date else ""
    enforcement_line = f"**Enforcement:** {entry.enforcement}" if entry.enforcement else ""

    prompt = textwrap.dedent(f"""\
        You are a regulatory and standards documentation specialist. Your task is to
        produce a well-structured markdown document for a compliance knowledge base.

        The document will be chunked by a hierarchical text splitter (1500/300 tokens)
        that splits on ## headings. Structure your output so each ## section is a
        coherent, self-contained unit that makes sense when retrieved independently
        via semantic search.

        ## Output Requirements

        1. Start with a level-1 heading and authority header:

        ```
        # {entry.display_name}
        **Source type:** {source_type_label}
        {effective_line}
        {enforcement_line}
        ```

        2. Use ## headings for major sections. Each section should be:
           - Self-contained (makes sense without reading other sections)
           - 200-600 words (fits well in the chunker's 1500-token parent window)
           - Focused on actionable requirements, not just summaries

        3. Target 2000-4000 words total. Be substantive — this replaces placeholder
           content that was too thin to be useful.

        4. Include specific requirements, control objectives, and guidance that
           compliance agents can cite in findings. Generic summaries are not useful.

        ## Content Approach

        {license_instruction}

        ## Specific Instructions

        {entry.description}

        ## Source Material Handling

        The source text below was extracted from a document and may contain minor
        formatting artifacts (footnote markers, orphaned references, table of contents
        fragments). Incorporate footnote content inline where substantive. Ignore any
        remaining formatting artifacts.

        Do NOT include any preamble, explanation, or commentary outside the markdown
        document itself. Output ONLY the markdown content.

        ## Source Material

        {source_text}
    """)

    return prompt


# ── Bedrock Converse ─────────────────────────────────────────────


def call_bedrock_converse(prompt: str, model_id: str) -> str:
    """Call Bedrock Converse API to generate standard content.

    Retries on throttling with exponential backoff.

    Args:
        prompt: The generation prompt.
        model_id: Bedrock model ID to use.

    Returns:
        Generated markdown content.

    Raises:
        RuntimeError: If the API call fails after retries.
    """
    region = os.environ.get("AWS_REGION")
    if not region:
        raise RuntimeError(
            "AWS_REGION environment variable is not set. "
            "Set it in .env or export it: export AWS_REGION=us-west-2"
        )

    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        config=BotocoreConfig(read_timeout=300, connect_timeout=10),
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                "Calling Bedrock Converse (model=%s, attempt=%d, prompt_len=%d)",
                model_id,
                attempt,
                len(prompt),
            )
            response = client.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 8192, "temperature": 0.2},
            )

            # Extract text from response
            output = response["output"]["message"]["content"]
            text_parts = [block["text"] for block in output if "text" in block]
            if not text_parts:
                raise RuntimeError("Bedrock Converse returned no text content")

            result = "\n".join(text_parts).strip()

            usage = response.get("usage", {})
            logger.info(
                "Generation complete: %d chars, input_tokens=%s, output_tokens=%s",
                len(result),
                usage.get("inputTokens", "?"),
                usage.get("outputTokens", "?"),
            )
            return result

        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code == "ThrottlingException" and attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_BASE**attempt
                logger.warning(
                    "Throttled, retrying in %ds (attempt %d/%d)", wait, attempt, MAX_RETRIES
                )
                time.sleep(wait)
                continue
            raise RuntimeError(f"Bedrock Converse failed for model '{model_id}': {exc}") from exc

    raise RuntimeError(f"Bedrock Converse failed after {MAX_RETRIES} attempts")


# ── File Output ──────────────────────────────────────────────────


def write_standard(standard_id: str, content: str) -> Path:
    """Write the generated markdown file for a standard.

    Creates the directory if it doesn't exist.

    Args:
        standard_id: The standard identifier (used as directory name).
        content: The markdown content to write.

    Returns:
        Path to the written file.
    """
    output_dir = STANDARDS_DIR / standard_id
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{standard_id}.md"
    output_path.write_text(content + "\n", encoding="utf-8")
    logger.info("Wrote %s (%d chars)", output_path, len(content))
    return output_path


def write_metadata_sidecar(entry: ManifestEntry) -> Path:
    """Write the metadata sidecar JSON for a standard.

    The sidecar follows the Bedrock KB metadata format with standard_id
    and source_type attributes for filtering.

    Args:
        entry: The manifest entry.

    Returns:
        Path to the written metadata file.
    """
    output_dir = STANDARDS_DIR / entry.standard_id
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "metadataAttributes": {
            "standard_id": {
                "value": {
                    "type": "STRING",
                    "stringValue": entry.standard_id,
                },
            },
            "source_type": {
                "value": {
                    "type": "STRING",
                    "stringValue": entry.source_type,
                },
            },
        }
    }

    output_path = output_dir / f"{entry.standard_id}.md.metadata.json"
    output_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote %s", output_path)
    return output_path


# ── Cross-Reference Management ───────────────────────────────────

# Markers used to identify the cross-reference block in generated files
XREF_START = "<!-- CROSS-REFERENCES:START -->"
XREF_END = "<!-- CROSS-REFERENCES:END -->"

RELATIONSHIP_LABELS: dict[SourceType, dict[SourceType, str]] = {
    # How to describe the relationship FROM source_type TO target source_type
    "prudential_standard": {
        "regulatory_guidance": "See {name} for APRA's guidance on implementing these requirements.",
        "regulatory_commentary": "See {name} for current APRA supervisory focus related to this standard.",
    },
    "regulatory_guidance": {
        "prudential_standard": (
            "This guidance supports {name}. Requirements referenced below are from "
            "{name} — this document provides implementation guidance, not additional "
            "binding requirements."
        ),
        "regulatory_commentary": "See {name} for current APRA supervisory focus related to this area.",
    },
    "regulatory_commentary": {
        "prudential_standard": "This commentary relates to requirements in {name}.",
        "regulatory_guidance": "See also {name} for implementation guidance.",
    },
}

DEFAULT_RELATIONSHIP_LABEL = "See also: {name}."


def _build_xref_block(entry: ManifestEntry) -> str | None:
    """Build the cross-reference block for a standard.

    Resolves all bidirectional relationships from the manifest and generates
    appropriately worded cross-reference text based on source type pairs.

    Args:
        entry: The manifest entry to build cross-references for.

    Returns:
        The cross-reference block as a string, or None if no related standards exist.
    """
    # Collect all related standard_ids (bidirectional resolution)
    related_ids: set[str] = set(entry.related)
    for other in MANIFEST:
        if other.standard_id != entry.standard_id and entry.standard_id in other.related:
            related_ids.add(other.standard_id)

    if not related_ids:
        return None

    lines = [XREF_START, ""]
    for related_id in sorted(related_ids):
        related_entry = MANIFEST_BY_ID.get(related_id)
        if related_entry is None:
            logger.warning(
                "Related standard '%s' referenced by '%s' not found in manifest",
                related_id,
                entry.standard_id,
            )
            continue

        # Find the appropriate relationship label
        type_labels = RELATIONSHIP_LABELS.get(entry.source_type, {})
        template = type_labels.get(related_entry.source_type, DEFAULT_RELATIONSHIP_LABEL)
        label = template.format(name=related_entry.display_name)
        lines.append(f"> **Related:** {label}")
        lines.append(">")

    # Remove trailing empty blockquote line
    if lines[-1] == ">":
        lines.pop()

    lines.extend(["", XREF_END])
    return "\n".join(lines)


def _inject_xref_block(content: str, xref_block: str | None) -> str:
    """Inject or replace the cross-reference block in a markdown file.

    The block is inserted after the authority header (the first blank line
    after the level-1 heading). If an existing block is present, it's replaced.

    Args:
        content: The current file content.
        xref_block: The new cross-reference block, or None to remove it.

    Returns:
        Updated file content.
    """
    # Remove existing block if present
    if XREF_START in content:
        pattern = re.compile(
            rf"^{re.escape(XREF_START)}.*?{re.escape(XREF_END)}\n?",
            re.MULTILINE | re.DOTALL,
        )
        content = pattern.sub("", content).strip() + "\n"

    if xref_block is None:
        return content

    # Find insertion point: after the authority header block.
    # The authority header is the lines between the # heading and the first ## heading
    # or the first blank line followed by content.
    lines = content.split("\n")
    insert_idx = 0

    # Find end of authority header: first blank line after the # heading
    in_header = False
    for i, line in enumerate(lines):
        if line.startswith("# ") and not line.startswith("## "):
            in_header = True
            continue
        if in_header and line.strip() == "":
            # Check if next non-blank line starts a section
            for j in range(i + 1, len(lines)):
                if lines[j].strip():
                    insert_idx = i + 1
                    break
            break

    if insert_idx == 0:
        # Fallback: insert after first line
        insert_idx = 1

    # Insert the block
    lines.insert(insert_idx, "")
    lines.insert(insert_idx + 1, xref_block)
    lines.insert(insert_idx + 2, "")

    return "\n".join(lines)


def update_cross_references() -> int:
    """Update cross-reference blocks in all generated standard files.

    Walks the manifest, resolves bidirectional relationships, and injects
    or updates the cross-reference block in each file that exists on disk.

    Returns:
        Number of files updated.
    """
    updated = 0
    for entry in MANIFEST:
        md_path = STANDARDS_DIR / entry.standard_id / f"{entry.standard_id}.md"
        if not md_path.exists():
            continue

        content = md_path.read_text(encoding="utf-8")
        xref_block = _build_xref_block(entry)
        new_content = _inject_xref_block(content, xref_block)

        if new_content != content:
            md_path.write_text(new_content, encoding="utf-8")
            logger.info("Updated cross-references in %s", md_path)
            updated += 1
        else:
            logger.debug("No cross-reference changes for %s", entry.standard_id)

    return updated


# ── Generation Orchestration ─────────────────────────────────────


def generate_standard(entry: ManifestEntry, model_id: str) -> Path:
    """Generate a single standard: extract source, call Bedrock, write files.

    Args:
        entry: The manifest entry to generate.
        model_id: Bedrock model ID to use.

    Returns:
        Path to the generated markdown file.

    Raises:
        ValueError: If the entry has no source material.
        RuntimeError: If extraction or generation fails.
    """
    if entry.source is None:
        raise ValueError(
            f"Cannot generate '{entry.standard_id}': no source material. "
            f"Add a PDF, markdown file, or URL to the manifest entry's 'source' field."
        )

    logger.info("Generating %s (%s)", entry.standard_id, entry.display_name)

    # 1. Extract source material
    source_text = extract_source_material(entry)

    # 2. Build prompt
    prompt = build_generation_prompt(entry, source_text)

    # 3. Call Bedrock
    content = call_bedrock_converse(prompt, model_id)

    # 4. Write output files
    md_path = write_standard(entry.standard_id, content)
    write_metadata_sidecar(entry)

    return md_path


# ── List Command ─────────────────────────────────────────────────


def list_manifest() -> None:
    """Print the manifest with status information for each entry."""
    print("\nStandards Generation Manifest")
    print("=" * 72)
    print()

    for entry in MANIFEST:
        # Check if source exists
        has_source = False
        source_status = "❌ no source"
        if entry.source is not None:
            source_kind = _detect_source_type(entry.source)
            if source_kind == "url":
                has_source = True
                source_status = f"🌐 {entry.source[:60]}"
            else:
                local_path = STANDARDS_DIR.parent / entry.source
                if local_path.exists():
                    has_source = True
                    source_status = f"📄 {entry.source}"
                else:
                    source_status = f"❌ missing: {entry.source}"

        # Check if already generated
        md_path = STANDARDS_DIR / entry.standard_id / f"{entry.standard_id}.md"
        if md_path.exists():
            size = md_path.stat().st_size
            mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(md_path.stat().st_mtime))
            gen_status = f"✅ generated ({size:,} bytes, {mtime})"
        else:
            gen_status = "⬜ not generated"

        # Related standards
        related_ids = set(entry.related)
        for other in MANIFEST:
            if other.standard_id != entry.standard_id and entry.standard_id in other.related:
                related_ids.add(other.standard_id)
        related_str = ", ".join(sorted(related_ids)) if related_ids else "none"

        # Print
        ready = "✅" if has_source else "⬜"
        print(f"  {ready} {entry.standard_id}")
        print(f"     {entry.display_name}")
        print(f"     Type: {entry.source_type} | License: {entry.license}")
        print(f"     Source: {source_status}")
        print(f"     Output: {gen_status}")
        print(f"     Related: {related_str}")
        print()

    # Summary
    total = len(MANIFEST)
    with_source = sum(1 for e in MANIFEST if e.source is not None)
    generated = sum(
        1 for e in MANIFEST if (STANDARDS_DIR / e.standard_id / f"{e.standard_id}.md").exists()
    )
    print(f"  Total: {total} | With source: {with_source} | Generated: {generated}")
    print()


# ── CLI ──────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        prog="generate_standard",
        description="Generate well-structured markdown standards for the Bedrock Knowledge Base.",
        epilog=textwrap.dedent("""\
            examples:
              %(prog)s cps-230                  Generate a single standard
              %(prog)s --all                    Generate all standards with sources
              %(prog)s --list                   Show manifest with status
              %(prog)s --update-refs            Update cross-references in all files
              %(prog)s --model us.anthropic.claude-sonnet-4-6 cps-230

            workflow:
              1. Add source material (PDF/markdown) to standards/ or note a URL
              2. Add/update the manifest entry in this script
              3. Generate:     %(prog)s <standard_id>
              4. Update refs:  %(prog)s --update-refs
              5. Deploy to KB: task deploy:knowledge-bases
        """),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Mutually exclusive: generate one, generate all, list, or update refs
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "standard_id",
        nargs="?",
        default=None,
        help="Standard ID to generate (e.g. cps-230). See --list for available IDs.",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Generate all standards that have source material.",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="Show the manifest with source and generation status.",
    )
    group.add_argument(
        "--update-refs",
        action="store_true",
        help="Update cross-reference blocks in all generated files.",
    )

    parser.add_argument(
        "--model",
        default=None,
        help=(
            f"Bedrock model ID to use. Overrides GENERATOR_MODEL_ID env var. "
            f"Default: {DEFAULT_MODEL_ID}"
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if output already exists on disk.",
    )

    return parser


def resolve_model_id(cli_model: str | None) -> str:
    """Resolve the model ID from CLI flag, env var, or default.

    Precedence: --model flag > GENERATOR_MODEL_ID env var > hardcoded default.

    Args:
        cli_model: Value from --model flag, or None.

    Returns:
        The resolved model ID.
    """
    if cli_model:
        return cli_model
    return os.environ.get("GENERATOR_MODEL_ID", DEFAULT_MODEL_ID)


def main() -> int:
    """Main entry point.

    Returns:
        Exit code: 0 for success, 1 for failure.
    """
    # Load .env file if python-dotenv is available (same vars as Taskfile dotenv)
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass  # dotenv is optional — env vars can be set directly

    parser = build_parser()
    args = parser.parse_args()

    # ── List ─────────────────────────────────────────────────────
    if args.list:
        list_manifest()
        return 0

    # ── Update cross-references ──────────────────────────────────
    if args.update_refs:
        updated = update_cross_references()
        print(f"\n✓ Updated cross-references in {updated} file(s)")
        return 0

    # ── Resolve model ────────────────────────────────────────────
    model_id = resolve_model_id(args.model)

    # ── Generate all ─────────────────────────────────────────────
    if args.all:
        entries_with_source = [e for e in MANIFEST if e.source is not None]
        if not entries_with_source:
            print("No manifest entries have source material. See --list for status.")
            return 1

        # Skip already-generated entries unless --force
        if not args.force:
            before = len(entries_with_source)
            entries_with_source = [
                e
                for e in entries_with_source
                if not (STANDARDS_DIR / e.standard_id / f"{e.standard_id}.md").exists()
            ]
            skipped = before - len(entries_with_source)
            if skipped:
                print(
                    f"Skipping {skipped} already-generated standard(s). Use --force to regenerate.\n"
                )
            if not entries_with_source:
                print(
                    "All standards with sources are already generated. Use --force to regenerate."
                )
                return 0

        print(f"\nGenerating {len(entries_with_source)} standard(s) with model {model_id}...\n")

        succeeded = 0
        failed = 0
        for entry in entries_with_source:
            try:
                md_path = generate_standard(entry, model_id)
                print(f"  ✓ {entry.standard_id} → {md_path}")
                succeeded += 1
            except Exception as exc:
                print(f"  ✗ {entry.standard_id}: {exc}")
                logger.error("Failed to generate %s", entry.standard_id, exc_info=True)
                failed += 1

        # Update cross-references after all generations
        if succeeded > 0:
            ref_count = update_cross_references()
            print(f"\n  Updated cross-references in {ref_count} file(s)")

        print(f"\nDone: {succeeded} succeeded, {failed} failed")
        return 1 if failed > 0 else 0

    # ── Generate single ──────────────────────────────────────────
    standard_id = args.standard_id
    entry = MANIFEST_BY_ID.get(standard_id)
    if entry is None:
        print(f"Unknown standard_id: '{standard_id}'")
        print(f"Available: {', '.join(MANIFEST_BY_ID.keys())}")
        return 1

    if entry.source is None:
        print(f"Cannot generate '{standard_id}': no source material.")
        print("Add a PDF, markdown file, or URL to the manifest entry's 'source' field.")
        print("\nRun --list to see all entries and their source status.")
        return 1

    print(f"\nGenerating {standard_id} with model {model_id}...\n")

    # Skip if already generated unless --force
    md_path_check = STANDARDS_DIR / standard_id / f"{standard_id}.md"
    if md_path_check.exists() and not args.force:
        print(f"Already generated: {md_path_check}")
        print("Use --force to regenerate.")
        return 0

    try:
        md_path = generate_standard(entry, model_id)
    except Exception as exc:
        print(f"\n✗ Failed: {exc}")
        logger.error("Generation failed", exc_info=True)
        return 1

    # Update cross-references
    ref_count = update_cross_references()
    if ref_count > 0:
        print(f"  Updated cross-references in {ref_count} file(s)")

    print(f"\n✓ Generated {md_path}")
    print("  Deploy to KB: task deploy:knowledge-bases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
