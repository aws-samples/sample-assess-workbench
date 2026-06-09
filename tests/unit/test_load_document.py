"""Unit tests for pure logic in workflow/load_document.py.

Source: api/workflow/load_document.py
Tests the extractable pure functions — no AWS calls.
"""
from pathlib import PurePosixPath


class TestFileExtensionExtraction:
    """The Lambda inlines PurePosixPath(filename).suffix.lower() to get
    file extensions. These tests document the edge cases that matter
    for document processing."""

    @staticmethod
    def _ext(filename: str) -> str:
        return PurePosixPath(filename).suffix.lower()

    def test_pdf(self):
        assert self._ext('document.pdf') == '.pdf'

    def test_uppercase_normalized(self):
        assert self._ext('README.MD') == '.md'

    def test_compound_extension_returns_last(self):
        assert self._ext('archive.tar.gz') == '.gz'

    def test_no_extension(self):
        assert self._ext('Makefile') == ''

    def test_dotfile_returns_empty(self):
        """Dotfiles like .gitignore have no extension — the leading dot
        is part of the name, not a separator."""
        assert self._ext('.gitignore') == ''

    def test_dotfile_with_extension(self):
        assert self._ext('.env.local') == '.local'

    def test_empty_string(self):
        assert self._ext('') == ''
