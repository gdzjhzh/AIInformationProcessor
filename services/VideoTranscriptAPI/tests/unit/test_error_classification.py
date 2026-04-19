"""
Error classification system unit tests.

Covers:
- Error hierarchy and inheritance
- retryable flag on each error type
- TranscriptAPIError base class

All console output must be in English only (no emoji, no Chinese).
"""

import os
import sys

import pytest


from video_transcript_api.errors import (
    TranscriptAPIError,
    NetworkError,
    DownloadTimeoutError,
    HTTPForbiddenError,
    ASRConnectionError,
    EmptyTranscriptError,
    DownloadFailedError,
    InvalidMediaError,
)


class TestErrorHierarchy:
    """Verify error class inheritance chain."""

    def test_all_errors_inherit_from_base(self):
        """Every custom error should be a subclass of TranscriptAPIError."""
        error_classes = [
            NetworkError, DownloadTimeoutError, HTTPForbiddenError,
            ASRConnectionError, EmptyTranscriptError,
            DownloadFailedError, InvalidMediaError,
        ]
        for cls in error_classes:
            assert issubclass(cls, TranscriptAPIError), f"{cls.__name__} is not a TranscriptAPIError"

    def test_all_errors_inherit_from_exception(self):
        """Every custom error should also be a standard Exception."""
        error_classes = [
            TranscriptAPIError, NetworkError, DownloadTimeoutError,
            HTTPForbiddenError, ASRConnectionError, EmptyTranscriptError,
            DownloadFailedError, InvalidMediaError,
        ]
        for cls in error_classes:
            assert issubclass(cls, Exception), f"{cls.__name__} is not an Exception"

    def test_download_timeout_is_network_error(self):
        """DownloadTimeoutError should be a subclass of NetworkError."""
        assert issubclass(DownloadTimeoutError, NetworkError)

    def test_asr_connection_is_not_network_error(self):
        """ASRConnectionError is a TranscriptAPIError but not a NetworkError."""
        assert not issubclass(ASRConnectionError, NetworkError)


class TestRetryableFlag:
    """Verify retryable property on each error type."""

    def test_retryable_errors(self):
        """Network-related errors should be retryable."""
        retryable_errors = [
            NetworkError("test"),
            DownloadTimeoutError("test"),
            ASRConnectionError("test"),
            DownloadFailedError("test"),
        ]
        for err in retryable_errors:
            assert err.retryable is True, f"{err.__class__.__name__} should be retryable"

    def test_non_retryable_errors(self):
        """Permanent errors should not be retryable."""
        non_retryable_errors = [
            HTTPForbiddenError("test"),
            EmptyTranscriptError("test"),
            InvalidMediaError("test"),
        ]
        for err in non_retryable_errors:
            assert err.retryable is False, f"{err.__class__.__name__} should not be retryable"


class TestErrorMessages:
    """Verify error message handling."""

    def test_custom_message(self):
        """Custom message should be preserved."""
        err = NetworkError("custom network failure")
        assert str(err) == "custom network failure"
        assert err.message == "custom network failure"

    def test_default_message(self):
        """Default message should be set when no custom message is provided."""
        err = NetworkError()
        assert "Network error" in str(err)

    def test_error_can_be_caught_as_base(self):
        """TranscriptAPIError should catch all custom errors."""
        with pytest.raises(TranscriptAPIError):
            raise DownloadTimeoutError("timed out")

    def test_error_can_be_caught_as_exception(self):
        """Standard Exception catch should work."""
        with pytest.raises(Exception):
            raise InvalidMediaError("bad file")
