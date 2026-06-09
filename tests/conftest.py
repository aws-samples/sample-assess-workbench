"""Root test configuration.

Registers markers and provides fixtures shared across all test categories.
"""
import sys
import pytest
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Make api/ packages importable locally.
#
# In Lambda, api/core/ is deployed as a layer under the package name "core".
# Adding api/ to sys.path lets tests use the same import paths as Lambda code
# (e.g. from core.coach_logic import build_org_context).
# ---------------------------------------------------------------------------
_api_path = Path(__file__).parent.parent / 'api'
if str(_api_path) not in sys.path:
    sys.path.insert(0, str(_api_path))


def pytest_configure(config):
    """Register custom markers so --strict-markers doesn't reject them."""
    config.addinivalue_line("markers", "unit: pure logic tests — no AWS, no mocks of AWS")
    config.addinivalue_line("markers", "live: tests against real deployed AWS infrastructure")


# ---------------------------------------------------------------------------
# Shared fixtures (available to both unit and live tests)
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_document_path():
    """Path to sample test document."""
    return Path(__file__).parent.parent / "test-docs" / "sample-design.txt"


@pytest.fixture
def sample_document_content(sample_document_path):
    """Content of sample test document."""
    if sample_document_path.exists():
        return sample_document_path.read_text()
    return "Sample design document content for testing."
