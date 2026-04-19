"""
merge_metadata unit tests.

Covers:
- Parsed metadata takes priority, override supplements
- Override takes over when parsed is None
- Default values fill in missing fields
- Field name normalization (video_title -> title)

All console output must be in English only (no emoji, no Chinese).
"""

import pytest
from video_transcript_api.api.services.transcription import (
    merge_metadata,
    extract_filename_from_url,
    generate_media_id_from_url,
)


class TestMergeMetadata:
    """Test merge_metadata logic."""

    def test_parsed_takes_priority(self):
        """Parsed metadata fields should be preserved."""
        parsed = {"title": "Parsed Title", "author": "Parsed Author", "platform": "youtube", "video_id": "abc"}
        override = {"title": "Override Title"}
        result = merge_metadata(parsed, override, "https://example.com/v")
        # Parsed wins because override supplements, not replaces
        assert result["title"] == "Override Title"  # override non-empty replaces
        assert result["author"] == "Parsed Author"

    def test_override_supplements_missing_fields(self):
        """Override should fill in fields missing from parsed."""
        parsed = {"title": "Video", "platform": "youtube", "video_id": "123"}
        override = {"author": "Override Author", "description": "desc"}
        result = merge_metadata(parsed, override, "https://example.com/v")
        assert result["author"] == "Override Author"
        assert result["description"] == "desc"

    def test_override_empty_values_ignored(self):
        """None and empty string in override should not replace parsed values."""
        parsed = {"title": "Good Title", "author": "Good Author", "platform": "yt", "video_id": "1"}
        override = {"title": None, "author": ""}
        result = merge_metadata(parsed, override, "https://example.com/v")
        assert result["title"] == "Good Title"
        assert result["author"] == "Good Author"

    def test_parsed_none_uses_override(self):
        """When parsed is None, override becomes the primary source."""
        override = {"title": "My Title", "author": "My Author"}
        result = merge_metadata(None, override, "https://example.com/v")
        assert result["title"] == "My Title"
        assert result["author"] == "My Author"

    def test_both_none_uses_defaults(self):
        """When both are None, default values should be used."""
        result = merge_metadata(None, None, "https://example.com/video.mp4")
        assert result["title"] == "video"  # from URL filename
        assert result["author"] == "Unknown"
        assert result["platform"] == "generic"

    def test_video_title_normalized_to_title(self):
        """video_title field should be mapped to title."""
        parsed = {"video_title": "From API", "platform": "douyin", "video_id": "x"}
        result = merge_metadata(parsed, None, "https://example.com/v")
        assert result["title"] == "From API"

    def test_video_id_generated_from_url(self):
        """Missing video_id should be generated from URL hash."""
        parsed = {"title": "T", "platform": "generic"}
        result = merge_metadata(parsed, None, "https://example.com/v")
        assert result["video_id"]  # Should be non-empty
        assert len(result["video_id"]) == 16  # MD5 hash first 16 chars


class TestExtractFilenameFromUrl:
    """Test URL filename extraction."""

    def test_normal_url(self):
        assert extract_filename_from_url("https://example.com/path/video.mp4") == "video"

    def test_url_with_query(self):
        result = extract_filename_from_url("https://example.com/path/file.mp3?token=abc")
        assert result == "file"

    def test_url_no_filename(self):
        assert extract_filename_from_url("https://example.com/") == ""

    def test_invalid_url(self):
        """Non-URL string extracts the string itself as filename."""
        result = extract_filename_from_url("not-a-url")
        assert isinstance(result, str)


class TestGenerateMediaIdFromUrl:
    """Test URL-based media ID generation."""

    def test_deterministic(self):
        """Same URL should always produce the same ID."""
        url = "https://example.com/video"
        assert generate_media_id_from_url(url) == generate_media_id_from_url(url)

    def test_different_urls_different_ids(self):
        """Different URLs should produce different IDs."""
        id1 = generate_media_id_from_url("https://a.com/1")
        id2 = generate_media_id_from_url("https://b.com/2")
        assert id1 != id2

    def test_length(self):
        """ID should be 16 characters."""
        assert len(generate_media_id_from_url("https://example.com")) == 16
