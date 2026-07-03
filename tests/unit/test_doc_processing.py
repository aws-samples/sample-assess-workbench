"""Unit tests for document processing utilities.

Source: api/core/doc_processing.py
Tests the pure functions extracted from workflow/load_document.py:
  - format_analysis_for_injection: formats image analysis results as text
  - inject_image_analyses: appends formatted analyses to document text
  - prepare_image_for_bedrock: resizes/converts images for Bedrock API
  - extract_text_and_images_from_pdf: PDF text + image extraction
"""

import io
import pytest
from pathlib import Path
from core.doc_processing import (
    format_analysis_for_injection,
    inject_image_analyses,
    prepare_image_for_bedrock,
    extract_text_and_images_from_pdf,
    unsupported_filenames,
    SUPPORTED_DOCUMENT_EXTENSIONS,
    TEXT_DOCUMENT_EXTENSIONS,
    MAX_IMAGE_DIMENSION,
    MIN_IMAGE_DIMENSION,
    SUPPORTED_IMAGE_FORMATS,
)


# ═══════════════════════════════════════════════════════════════════════════
# format_analysis_for_injection
#
# This formats analysis results into text that gets injected into the
# document content fed to review agents. Bugs here mean agents get
# garbled or missing context about diagrams.
# ═══════════════════════════════════════════════════════════════════════════


class TestFormatAnalysisSkipped:
    """Skipped images should produce a concise one-liner with page/image info."""

    def test_skipped_with_description(self):
        result = {
            "type": "skipped",
            "category": "logo",
            "brief_description": "Company logo",
            "page_num": 3,
            "image_index": 0,
        }
        text = format_analysis_for_injection(result)
        assert text == "[Image skipped: Company logo — Page 3, Image 1]"

    def test_skipped_falls_back_to_category(self):
        result = {
            "type": "skipped",
            "category": "decorative",
            "page_num": 1,
            "image_index": 2,
        }
        text = format_analysis_for_injection(result)
        assert "decorative" in text
        assert "Page 1" in text
        assert "Image 3" in text


class TestFormatAnalysisFailedAndTimeout:
    def test_analysis_failed(self):
        result = {
            "type": "analysis_failed",
            "page_num": 5,
            "image_index": 0,
            "filename": "doc.pdf",
            "category": "architecture_diagram",
        }
        text = format_analysis_for_injection(result)
        assert text == "[Diagram on Page 5 — analysis failed]"

    def test_timeout_passes_through_message(self):
        msg = "[Remaining 12 images not analyzed — timeout]"
        result = {"type": "timeout", "message": msg}
        assert format_analysis_for_injection(result) == msg

    def test_unknown_type_returns_empty(self):
        result = {"type": "something_new"}
        assert format_analysis_for_injection(result) == ""


class TestFormatAnalysisAnalyzed:
    """The 'analyzed' type is the complex one — it builds a multi-section
    text block from the analysis dict. Each optional section should appear
    only when present, and missing fields should degrade gracefully."""

    @pytest.fixture
    def full_analysis_result(self):
        """A realistic analyzed result with all optional sections populated."""
        return {
            "type": "analyzed",
            "page_num": 2,
            "image_index": 0,
            "filename": "arch.pdf",
            "category": "architecture_diagram",
            "analysis": {
                "diagram_type": "architecture_diagram",
                "summary": "Three-tier web application on AWS.",
                "components": [
                    {"name": "ALB", "type": "Load Balancer", "details": "Internet-facing"},
                    {"name": "ECS Cluster", "type": "Container Service", "details": ""},
                ],
                "connections": [
                    {
                        "from": "ALB",
                        "to": "ECS Cluster",
                        "label": "HTTPS",
                        "direction": "unidirectional",
                    },
                    {"from": "ECS Cluster", "to": "RDS", "label": "", "direction": "bidirectional"},
                ],
                "groupings": [
                    {
                        "name": "Production VPC",
                        "type": "VPC",
                        "contains": ["ALB", "ECS Cluster", "RDS"],
                    },
                ],
                "sequence_steps": ["User request hits ALB", "ALB routes to ECS", "ECS queries RDS"],
                "technologies": ["AWS ECS", "PostgreSQL", "ALB"],
                "security_elements": ["WAF", "TLS termination"],
                "description": "A standard three-tier architecture with load balancing.",
            },
        }

    def test_header_contains_diagram_type_and_position(self, full_analysis_result):
        text = format_analysis_for_injection(full_analysis_result)
        assert "--- [Diagram: Architecture Diagram — Page 2, Image 1] ---" in text

    def test_components_listed(self, full_analysis_result):
        text = format_analysis_for_injection(full_analysis_result)
        assert "- ALB (Load Balancer): Internet-facing" in text
        assert "- ECS Cluster (Container Service)" in text

    def test_connections_with_direction(self, full_analysis_result):
        text = format_analysis_for_injection(full_analysis_result)
        assert "ALB → ECS Cluster: HTTPS" in text
        assert "ECS Cluster ↔ RDS" in text

    def test_groupings_listed(self, full_analysis_result):
        text = format_analysis_for_injection(full_analysis_result)
        assert "Production VPC (VPC): ALB, ECS Cluster, RDS" in text

    def test_sequence_steps_numbered(self, full_analysis_result):
        text = format_analysis_for_injection(full_analysis_result)
        assert "1. User request hits ALB" in text
        assert "3. ECS queries RDS" in text

    def test_technologies_and_security(self, full_analysis_result):
        text = format_analysis_for_injection(full_analysis_result)
        assert "Technologies: AWS ECS, PostgreSQL, ALB" in text
        assert "Security: WAF, TLS termination" in text

    def test_ends_with_end_marker(self, full_analysis_result):
        text = format_analysis_for_injection(full_analysis_result)
        assert text.endswith("--- [End Diagram] ---")

    def test_minimal_analysis_only_required_fields(self):
        """An analyzed result with empty optional sections should still
        produce a valid header + type + end marker."""
        result = {
            "type": "analyzed",
            "page_num": 1,
            "image_index": 0,
            "category": "flowchart",
            "analysis": {},
        }
        text = format_analysis_for_injection(result)
        assert "--- [Diagram: Flowchart" in text
        assert "Type: flowchart" in text
        assert "--- [End Diagram] ---" in text
        # Optional sections should be absent
        assert "Components:" not in text
        assert "Connections:" not in text

    def test_diagram_type_falls_back_to_category(self):
        """When analysis has no diagram_type, category is used and formatted."""
        result = {
            "type": "analyzed",
            "page_num": 1,
            "image_index": 0,
            "category": "sequence_diagram",
            "analysis": {"summary": "Auth flow"},
        }
        text = format_analysis_for_injection(result)
        assert "Sequence Diagram" in text

    def test_component_with_missing_name_shows_unknown(self):
        result = {
            "type": "analyzed",
            "page_num": 1,
            "image_index": 0,
            "category": "uml",
            "analysis": {
                "components": [{"type": "Service"}],
            },
        }
        text = format_analysis_for_injection(result)
        assert "- Unknown (Service)" in text


# ═══════════════════════════════════════════════════════════════════════════
# inject_image_analyses
#
# Appends formatted analyses to document text, filtered by filename and
# sorted by position. Bugs here mean wrong images attached to wrong files
# in multi-file reviews.
# ═══════════════════════════════════════════════════════════════════════════


class TestInjectImageAnalyses:
    def test_empty_results_returns_text_unchanged(self):
        assert inject_image_analyses("Hello", []) == "Hello"
        assert inject_image_analyses("Hello", None) == "Hello"

    def test_single_result_appended(self):
        results = [{"type": "timeout", "message": "[timeout]", "page_num": 1, "image_index": 0}]
        text = inject_image_analyses("Doc text", results)
        assert text.startswith("Doc text\n\n")
        assert "[timeout]" in text

    def test_filename_filtering(self):
        """Results for other files should not leak into this file's section."""
        results = [
            {
                "type": "timeout",
                "message": "[img from A]",
                "filename": "a.pdf",
                "page_num": 1,
                "image_index": 0,
            },
            {
                "type": "timeout",
                "message": "[img from B]",
                "filename": "b.pdf",
                "page_num": 1,
                "image_index": 0,
            },
        ]
        text = inject_image_analyses("File A content", results, filename="a.pdf")
        assert "[img from A]" in text
        assert "[img from B]" not in text

    def test_no_filename_includes_all(self):
        """When filename is None, all results are included."""
        results = [
            {
                "type": "timeout",
                "message": "[A]",
                "filename": "a.pdf",
                "page_num": 1,
                "image_index": 0,
            },
            {
                "type": "timeout",
                "message": "[B]",
                "filename": "b.pdf",
                "page_num": 2,
                "image_index": 0,
            },
        ]
        text = inject_image_analyses("Content", results, filename=None)
        assert "[A]" in text
        assert "[B]" in text

    def test_results_sorted_by_page_then_image(self):
        """Results should appear in document order regardless of input order."""
        results = [
            {"type": "timeout", "message": "[p3]", "page_num": 3, "image_index": 0},
            {"type": "timeout", "message": "[p1]", "page_num": 1, "image_index": 1},
            {"type": "timeout", "message": "[p1-first]", "page_num": 1, "image_index": 0},
        ]
        text = inject_image_analyses("Doc", results)
        p1_first = text.index("[p1-first]")
        p1 = text.index("[p1]")
        p3 = text.index("[p3]")
        assert p1_first < p1 < p3

    def test_no_matching_filename_returns_unchanged(self):
        results = [
            {
                "type": "timeout",
                "message": "[x]",
                "filename": "other.pdf",
                "page_num": 1,
                "image_index": 0,
            },
        ]
        assert inject_image_analyses("Original", results, filename="mine.pdf") == "Original"


# ═══════════════════════════════════════════════════════════════════════════
# prepare_image_for_bedrock
#
# Handles resize thresholds, format conversion, jpg→jpeg mapping, and
# Pillow fallback paths. Bugs here cause silent image corruption or
# Bedrock API errors that are hard to trace.
# ═══════════════════════════════════════════════════════════════════════════


def _make_png_bytes(width: int, height: int) -> bytes:
    """Create a minimal valid PNG image of the given dimensions."""
    from PIL import Image

    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_image_info(width=100, height=100, fmt="png", raw_fmt=None, img_bytes=None):
    """Build an image_info dict matching what extract_text_and_images_from_pdf produces."""
    if img_bytes is None:
        img_bytes = _make_png_bytes(width, height)
    return {
        "image_bytes": img_bytes,
        "format": fmt,
        "width": width,
        "height": height,
        "raw_format": raw_fmt or fmt,
    }


class TestPrepareImagePassthrough:
    """Small images in supported formats should pass through unchanged."""

    def test_small_png_passes_through(self):
        info = _make_image_info(200, 200, "png")
        result_bytes, result_fmt = prepare_image_for_bedrock(info)
        assert result_bytes == info["image_bytes"]
        assert result_fmt == "png"

    def test_jpg_mapped_to_jpeg(self):
        """Bedrock requires 'jpeg' not 'jpg' — this mapping is critical."""
        info = _make_image_info(200, 200, "jpg", raw_fmt="jpg")
        result_bytes, result_fmt = prepare_image_for_bedrock(info)
        assert result_bytes == info["image_bytes"]
        assert result_fmt == "jpeg"

    def test_jpeg_stays_jpeg(self):
        info = _make_image_info(200, 200, "jpeg", raw_fmt="jpeg")
        _, result_fmt = prepare_image_for_bedrock(info)
        assert result_fmt == "jpeg"


class TestPrepareImageResize:
    """Images exceeding MAX_IMAGE_DIMENSION should be resized."""

    def test_oversized_image_gets_resized(self):
        big = _make_png_bytes(3000, 2000)
        info = _make_image_info(3000, 2000, "png", img_bytes=big)
        result_bytes, result_fmt = prepare_image_for_bedrock(info)
        assert result_fmt == "png"
        # Result should be different (resized) bytes
        assert result_bytes != big
        # Verify the output is a valid image with reduced dimensions
        from PIL import Image

        img = Image.open(io.BytesIO(result_bytes))
        assert max(img.width, img.height) <= MAX_IMAGE_DIMENSION

    def test_exactly_at_max_dimension_no_resize(self):
        """Image exactly at the limit should pass through."""
        exact = _make_png_bytes(MAX_IMAGE_DIMENSION, 100)
        info = _make_image_info(MAX_IMAGE_DIMENSION, 100, "png", img_bytes=exact)
        result_bytes, _ = prepare_image_for_bedrock(info)
        assert result_bytes == exact


class TestPrepareImageFormatConversion:
    """Unsupported raw formats should trigger conversion."""

    def test_unsupported_raw_format_converted_to_png(self):
        """A BMP image (not in SUPPORTED_IMAGE_FORMATS) should be converted."""
        from PIL import Image

        img = Image.new("RGB", (100, 100), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="BMP")
        bmp_bytes = buf.getvalue()

        info = _make_image_info(100, 100, "bmp", raw_fmt="bmp", img_bytes=bmp_bytes)
        result_bytes, result_fmt = prepare_image_for_bedrock(info)
        assert result_fmt == "png"
        # Verify it's valid PNG
        result_img = Image.open(io.BytesIO(result_bytes))
        assert result_img.format == "PNG"

    def test_cmyk_image_converted_to_rgb(self):
        """CMYK images (common in print PDFs) must be converted to RGB."""
        from PIL import Image

        img = Image.new("CMYK", (100, 100))
        buf = io.BytesIO()
        img.save(buf, format="TIFF")
        tiff_bytes = buf.getvalue()

        info = _make_image_info(100, 100, "tiff", raw_fmt="tiff", img_bytes=tiff_bytes)
        result_bytes, result_fmt = prepare_image_for_bedrock(info)
        assert result_fmt == "png"
        result_img = Image.open(io.BytesIO(result_bytes))
        assert result_img.mode in ("RGB", "RGBA")


# ═══════════════════════════════════════════════════════════════════════════
# extract_text_and_images_from_pdf
#
# Tests use the real demo PDF from tests/fixtures/ — the same document used
# in live E2E tests. This catches regressions in the actual extraction
# pipeline against a real-world document.
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractTextAndImagesFromPdf:
    PDF_PATH = Path(__file__).parent.parent / "fixtures" / "mortgage-processing-hld-demo.pdf"

    @pytest.fixture(scope="class")
    def pdf_bytes(self):
        if not self.PDF_PATH.exists():
            pytest.skip(f"Test PDF not found: {self.PDF_PATH}")
        return self.PDF_PATH.read_bytes()

    @pytest.fixture(scope="class")
    def extracted(self, pdf_bytes):
        return extract_text_and_images_from_pdf(pdf_bytes)

    def test_page_count(self, extracted):
        _, page_count, _ = extracted
        assert page_count == 17

    def test_text_contains_expected_content(self, extracted):
        text, _, _ = extracted
        assert "Mortgage Processing" in text
        assert "Network Architecture" in text
        assert "Security Groups" in text

    def test_text_spans_all_pages(self, extracted):
        """Text from early and late pages should both be present."""
        text, _, _ = extracted
        assert "Mortgage Processing" in text  # page 1
        assert "Alert Thresholds" in text  # page 17

    def test_extracts_architecture_diagram(self, extracted):
        """Page 2 has an embedded architecture diagram image."""
        _, _, images = extracted
        assert len(images) >= 1
        img = images[0]
        assert img["page_num"] == 2
        assert img["width"] >= MIN_IMAGE_DIMENSION
        assert img["height"] >= MIN_IMAGE_DIMENSION
        assert img["format"] in SUPPORTED_IMAGE_FORMATS
        assert len(img["image_bytes"]) > 0

    def test_image_has_required_fields(self, extracted):
        _, _, images = extracted
        assert len(images) >= 1
        required_keys = {
            "image_bytes",
            "page_num",
            "image_index",
            "format",
            "width",
            "height",
            "raw_format",
        }
        assert required_keys.issubset(images[0].keys())


# ═══════════════════════════════════════════════════════════════════════════
# unsupported_filenames / SUPPORTED_DOCUMENT_EXTENSIONS
#
# Single source of truth for which uploads the pipeline can extract. The upload
# API rejects unsupported files with 400 and the workflow loader fails the
# review loudly — both rely on this helper, so a bug here either lets an
# unreviewable file through (empty review) or blocks a valid one.
# ═══════════════════════════════════════════════════════════════════════════


class TestSupportedDocumentExtensions:
    """The canonical set must cover PDF + the text family and nothing binary."""

    def test_includes_pdf_and_text_family(self):
        assert ".pdf" in SUPPORTED_DOCUMENT_EXTENSIONS
        assert TEXT_DOCUMENT_EXTENSIONS <= SUPPORTED_DOCUMENT_EXTENSIONS

    def test_excludes_word_and_image_formats(self):
        for ext in (".doc", ".docx", ".png", ".jpg", ".jpeg", ".svg", ".zip"):
            assert ext not in SUPPORTED_DOCUMENT_EXTENSIONS


class TestUnsupportedFilenames:
    """Contract: returns exactly the unsupported names, in input order."""

    def test_all_supported_returns_empty(self):
        names = [
            "a.pdf",
            "b.md",
            "c.txt",
            "d.csv",
            "e.json",
            "f.yaml",
            "g.yml",
            "h.rst",
            "i.markdown",
        ]
        assert unsupported_filenames(names) == []

    def test_extension_match_is_case_insensitive(self):
        assert unsupported_filenames(["REPORT.PDF", "Notes.Md", "DATA.CSV"]) == []

    def test_word_and_images_are_rejected(self):
        names = ["a.doc", "b.docx", "c.png", "d.jpg", "e.jpeg", "f.svg"]
        assert unsupported_filenames(names) == names

    def test_returns_only_unsupported_preserving_order(self):
        names = ["good.pdf", "bad.png", "ok.md", "nope.docx"]
        assert unsupported_filenames(names) == ["bad.png", "nope.docx"]

    def test_extensionless_is_unsupported(self):
        # Format can't be determined; binary would decode to garbage.
        assert unsupported_filenames(["README", "Makefile"]) == ["README", "Makefile"]

    def test_path_like_names_use_final_segment_extension(self):
        assert unsupported_filenames(["dir/sub/report.pdf"]) == []
        assert unsupported_filenames(["dir/sub/photo.png"]) == ["dir/sub/photo.png"]

    def test_empty_input_returns_empty(self):
        assert unsupported_filenames([]) == []

    def test_accepts_a_generator(self):
        gen = (n for n in ["a.pdf", "b.png"])
        assert unsupported_filenames(gen) == ["b.png"]
