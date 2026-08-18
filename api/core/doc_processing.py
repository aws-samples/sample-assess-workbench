"""Pure document processing utilities.

Extracted from workflow/load_document.py for testability and reuse.
These functions have no AWS dependencies — they transform data in memory.
"""

import io
import logging
from pathlib import PurePosixPath
from typing import Iterable

logger = logging.getLogger(__name__)

# Image analysis constants
MAX_IMAGE_DIMENSION = 1568  # Claude's recommended max for optimal quality/cost
MIN_IMAGE_DIMENSION = 50  # Skip tiny images
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5MB — resize if larger
SUPPORTED_IMAGE_FORMATS = {"png", "jpeg", "jpg", "webp"}

# Canonical set of document formats the review pipeline can actually extract:
# PDF (text + embedded images via PyMuPDF) and the UTF-8 text family. This is the
# single source of truth shared by the upload API (rest_api.project_service) and
# the workflow loader (workflow.load_document). A format outside this set cannot
# be turned into reviewable text, so it must be rejected at upload rather than
# silently producing an empty review from a "[Binary file…]" placeholder.
TEXT_DOCUMENT_EXTENSIONS = frozenset(
    {".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".yaml", ".yml"}
)
SUPPORTED_DOCUMENT_EXTENSIONS = frozenset({".pdf"}) | TEXT_DOCUMENT_EXTENSIONS


def unsupported_filenames(filenames: Iterable[str]) -> list[str]:
    """Return the filenames the review pipeline cannot extract text from.

    A filename is supported when its lowercased extension is in
    SUPPORTED_DOCUMENT_EXTENSIONS. Files with no extension are treated as
    unsupported (the format can't be determined and binary content would
    otherwise be decoded into garbage).

    Args:
        filenames: Filenames or paths to check.

    Returns:
        The subset of filenames whose extension is not supported, in input
        order. An empty list means every filename is supported.
    """
    rejected: list[str] = []
    for name in filenames:
        ext = PurePosixPath(name).suffix.lower()
        if ext not in SUPPORTED_DOCUMENT_EXTENSIONS:
            rejected.append(name)
    return rejected


def extract_text_and_images_from_pdf(pdf_bytes: bytes) -> tuple[str, int, list[dict]]:
    """Extract text and images from PDF bytes using PyMuPDF.

    Args:
        pdf_bytes: Raw PDF file content.

    Returns:
        Tuple of (text_content, page_count, images_list) where images_list
        contains dicts with keys: image_bytes, page_num, image_index, format,
        width, height, raw_format.
    """
    import pymupdf

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    images = []
    page_count = len(doc)

    for page_num in range(page_count):
        page = doc[page_num]
        text = page.get_text("text")
        if text.strip():
            pages.append(text)

        image_list = page.get_images(full=True)
        for img_index, img_info in enumerate(image_list):
            xref = img_info[0]
            try:
                extracted = doc.extract_image(xref)
                if not extracted:
                    continue
                img_bytes = extracted["image"]
                img_ext = extracted.get("ext", "png").lower()
                width = extracted.get("width", 0)
                height = extracted.get("height", 0)

                if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
                    continue

                images.append(
                    {
                        "image_bytes": img_bytes,
                        "page_num": page_num + 1,
                        "image_index": img_index,
                        "format": img_ext if img_ext in SUPPORTED_IMAGE_FORMATS else "png",
                        "width": width,
                        "height": height,
                        "raw_format": img_ext,
                    }
                )
            except Exception as e:
                logger.warning(f" Failed to extract image xref={xref} on page {page_num + 1}: {e}")
                continue

    doc.close()
    return "\n\n".join(pages), page_count, images


def prepare_image_for_bedrock(image_info: dict) -> tuple[bytes | None, str | None]:
    """Resize and convert image for Bedrock Converse API.

    Args:
        image_info: Dict with keys: image_bytes, format, width, height, raw_format.

    Returns:
        Tuple of (image_bytes, format_str) ready for Bedrock, or (None, None)
        if the image can't be processed.
    """
    img_bytes = image_info["image_bytes"]
    img_format = image_info["format"]
    width = image_info["width"]
    height = image_info["height"]

    needs_resize = len(img_bytes) > MAX_IMAGE_BYTES or max(width, height) > MAX_IMAGE_DIMENSION
    needs_convert = image_info["raw_format"] not in SUPPORTED_IMAGE_FORMATS

    if needs_resize or needs_convert:
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(img_bytes))

            if max(img.width, img.height) > MAX_IMAGE_DIMENSION:
                ratio = MAX_IMAGE_DIMENSION / max(img.width, img.height)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)

            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue(), "png"
        except ImportError:
            if img_format in SUPPORTED_IMAGE_FORMATS:
                return img_bytes, img_format
            return None, None
        except Exception as e:
            logger.warning(f" Image processing failed: {e}")
            if img_format in SUPPORTED_IMAGE_FORMATS:
                return img_bytes, img_format
            return None, None

    if img_format == "jpg":
        img_format = "jpeg"
    return img_bytes, img_format


def format_analysis_for_injection(result: dict) -> str:
    """Format an image analysis result as text for inline injection into document content.

    Args:
        result: Dict with 'type' key ('analyzed', 'skipped', 'analysis_failed',
                'timeout') and type-specific fields.

    Returns:
        Formatted string, or empty string for unknown types.
    """
    if result["type"] == "skipped":
        return (
            f"[Image skipped: {result.get('brief_description', result['category'])} "
            f"— Page {result['page_num']}, Image {result['image_index'] + 1}]"
        )

    if result["type"] == "analysis_failed":
        return f"[Diagram on Page {result['page_num']} — analysis failed]"

    if result["type"] == "timeout":
        return result["message"]

    if result["type"] != "analyzed":
        return ""

    a = result["analysis"]
    lines = []
    diagram_type = a.get("diagram_type", result["category"]).replace("_", " ").title()
    lines.append(
        f"--- [Diagram: {diagram_type} — Page {result['page_num']}, Image {result['image_index'] + 1}] ---"
    )
    lines.append(f"Type: {result['category']}")

    if a.get("summary"):
        lines.append(f"Summary: {a['summary']}")

    if a.get("components"):
        lines.append("\nComponents:")
        for c in a["components"]:
            detail = f" ({c['type']})" if c.get("type") else ""
            desc = f": {c['details']}" if c.get("details") else ""
            lines.append(f"- {c.get('name', 'Unknown')}{detail}{desc}")

    if a.get("connections"):
        lines.append("\nConnections:")
        for c in a["connections"]:
            label = f": {c['label']}" if c.get("label") else ""
            direction = "↔" if c.get("direction") == "bidirectional" else "→"
            lines.append(f"- {c.get('from', '?')} {direction} {c.get('to', '?')}{label}")

    if a.get("groupings"):
        lines.append("\nGroupings:")
        for g in a["groupings"]:
            contains = ", ".join(g.get("contains", []))
            lines.append(f"- {g.get('name', '?')} ({g.get('type', '')}): {contains}")

    if a.get("sequence_steps"):
        lines.append("\nSequence:")
        for i, step in enumerate(a["sequence_steps"], 1):
            lines.append(f"  {i}. {step}")

    if a.get("technologies"):
        lines.append(f"\nTechnologies: {', '.join(a['technologies'])}")

    if a.get("security_elements"):
        lines.append(f"\nSecurity: {', '.join(a['security_elements'])}")

    if a.get("description"):
        lines.append(f"\nFull Description: {a['description']}")

    lines.append("--- [End Diagram] ---")
    return "\n".join(lines)


def inject_image_analyses(
    text_content: str,
    analysis_results: list[dict],
    filename: str | None = None,
) -> str:
    """Inject image analysis descriptions into document text.

    Appends all image analyses for a file at the end of that file's text section.

    Args:
        text_content: The document text to append analyses to.
        analysis_results: List of analysis result dicts from analyze_images().
        filename: If provided, only include results matching this filename.

    Returns:
        The text_content with analysis descriptions appended.
    """
    if not analysis_results:
        return text_content

    file_results = [
        r for r in analysis_results if not filename or r.get("filename", "") == filename
    ]
    if not file_results:
        return text_content

    file_results.sort(key=lambda r: (r.get("page_num", 0), r.get("image_index", 0)))

    injections = []
    for result in file_results:
        formatted = format_analysis_for_injection(result)
        if formatted:
            injections.append(formatted)

    if injections:
        text_content += "\n\n" + "\n\n".join(injections)

    return text_content
