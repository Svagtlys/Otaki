"""Tests for CHAPTER_FILE_NAME_REGEX parsing and validation in config."""

import json

import pytest
from pydantic import ValidationError

from app.config import Settings


class TestChapterFileNameRegexValidation:
    def test_accepts_valid_pattern_with_chapter_placeholder(self, monkeypatch):
        """Pattern containing {chapter_number} validates after replacement."""
        monkeypatch.setenv(
            "CHAPTER_FILE_NAME_REGEX",
            json.dumps(["Chapter {chapter_number}"]),
        )
        # Must not raise
        s = Settings()
        assert s.CHAPTER_FILE_NAME_REGEX == ["Chapter {chapter_number}"]

    def test_rejects_invalid_regex_pattern(self, monkeypatch):
        """Validator raises ValidationError on malformed regex."""
        monkeypatch.setenv(
            "CHAPTER_FILE_NAME_REGEX",
            json.dumps(["[invalid"]),
        )
        with pytest.raises(ValidationError):
            Settings()

    def test_none_when_not_set(self, monkeypatch):
        """Field is None when env var is absent."""
        monkeypatch.delenv("CHAPTER_FILE_NAME_REGEX", raising=False)
        s = Settings()
        assert s.CHAPTER_FILE_NAME_REGEX is None

    def test_parses_multiple_patterns(self, monkeypatch):
        """Multiple patterns parse correctly from JSON array."""
        monkeypatch.setenv(
            "CHAPTER_FILE_NAME_REGEX",
            json.dumps(["Chapter {chapter_number}", "(ch. {chapter_number})"]),
        )
        s = Settings()
        assert len(s.CHAPTER_FILE_NAME_REGEX) == 2
        assert "Chapter {chapter_number}" in s.CHAPTER_FILE_NAME_REGEX
        assert "(ch. {chapter_number})" in s.CHAPTER_FILE_NAME_REGEX
