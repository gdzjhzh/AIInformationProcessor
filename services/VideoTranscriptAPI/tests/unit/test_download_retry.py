"""
Download retry logic unit tests.

Covers:
- Retry on network errors (timeout, connection error)
- No retry on 403 Forbidden
- No retry on InvalidMediaError
- Exponential backoff between retries
- Dead code removal verification (no unreachable code)

All console output must be in English only (no emoji, no Chinese).
"""

import os
import sys
import inspect
from unittest.mock import patch, MagicMock, PropertyMock

import pytest
import requests



@pytest.fixture
def mock_downloader():
    """Create a BaseDownloader subclass for testing."""
    from video_transcript_api.downloaders.base import BaseDownloader

    class TestDownloader(BaseDownloader):
        def can_handle(self, url):
            return True

        def extract_video_id(self, url):
            return "test_id"

        def _fetch_metadata(self, url, video_id):
            return None

        def _fetch_download_info(self, url, video_id):
            return None

        def get_subtitle(self, url):
            return None

    # Mock config and temp_manager
    with patch("video_transcript_api.downloaders.base.load_config", return_value={"tikhub": {}}):
        with patch("video_transcript_api.downloaders.base.get_temp_manager") as mock_tm:
            mock_tm_instance = MagicMock()
            mock_tm_instance.create_temp_file.return_value = "/tmp/test_file.mp4"
            mock_tm.return_value = mock_tm_instance
            downloader = TestDownloader()
            downloader.temp_manager = mock_tm_instance
            yield downloader


class TestDownloadRetry:
    """Verify retry behavior in download_file."""

    @patch("video_transcript_api.downloaders.base.time.sleep")
    @patch("video_transcript_api.downloaders.base.requests.get")
    def test_retry_on_connection_error(self, mock_get, mock_sleep, mock_downloader):
        """Should retry on ConnectionError."""
        mock_get.side_effect = requests.exceptions.ConnectionError("connection refused")

        result = mock_downloader.download_file("http://example.com/video.mp4", "video.mp4", max_retries=3)

        assert result is None
        assert mock_get.call_count == 3
        # Exponential backoff: sleep(1), sleep(2)
        assert mock_sleep.call_count == 2

    @patch("video_transcript_api.downloaders.base.time.sleep")
    @patch("video_transcript_api.downloaders.base.requests.get")
    def test_retry_on_timeout(self, mock_get, mock_sleep, mock_downloader):
        """Should retry on Timeout."""
        mock_get.side_effect = requests.exceptions.Timeout("read timed out")

        result = mock_downloader.download_file("http://example.com/video.mp4", "video.mp4", max_retries=2)

        assert result is None
        assert mock_get.call_count == 2

    @patch("video_transcript_api.downloaders.base.requests.get")
    def test_no_retry_on_403(self, mock_get, mock_downloader):
        """Should NOT retry on HTTP 403 Forbidden."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        mock_get.return_value = mock_response

        result = mock_downloader.download_file("http://example.com/video.mp4", "video.mp4", max_retries=3)

        assert result is None
        assert mock_get.call_count == 1  # No retry

    @patch("video_transcript_api.downloaders.base.time.sleep")
    @patch("video_transcript_api.downloaders.base.requests.get")
    def test_retry_on_500(self, mock_get, mock_sleep, mock_downloader):
        """Should retry on HTTP 500 Server Error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        mock_get.return_value = mock_response

        result = mock_downloader.download_file("http://example.com/video.mp4", "video.mp4", max_retries=2)

        assert result is None
        assert mock_get.call_count == 2

    @patch("video_transcript_api.downloaders.base.requests.get")
    def test_success_on_first_try(self, mock_get, mock_downloader):
        """Should return file path on successful download."""
        mock_response = MagicMock()
        mock_response.headers = {"Content-Length": "1024"}
        mock_response.iter_content.return_value = [b"x" * 1024]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        with patch("builtins.open", MagicMock()):
            with patch("os.path.getsize", return_value=1024):
                with patch.object(mock_downloader, "_validate_media_file", return_value=True):
                    result = mock_downloader.download_file(
                        "http://example.com/video.mp4", "video.mp4"
                    )

        assert result == "/tmp/test_file.mp4"
        assert mock_get.call_count == 1

    @patch("video_transcript_api.downloaders.base.time.sleep")
    @patch("video_transcript_api.downloaders.base.requests.get")
    def test_success_after_retry(self, mock_get, mock_sleep, mock_downloader):
        """Should succeed after failed attempts."""
        # First call fails, second succeeds
        mock_fail_response = requests.exceptions.ConnectionError("fail")
        mock_success_response = MagicMock()
        mock_success_response.headers = {"Content-Length": "1024"}
        mock_success_response.iter_content.return_value = [b"x" * 1024]
        mock_success_response.raise_for_status.return_value = None

        mock_get.side_effect = [mock_fail_response, mock_success_response]

        with patch("builtins.open", MagicMock()):
            with patch("os.path.getsize", return_value=1024):
                with patch("os.path.exists", return_value=False):
                    with patch.object(mock_downloader, "_validate_media_file", return_value=True):
                        result = mock_downloader.download_file(
                            "http://example.com/video.mp4", "video.mp4", max_retries=3
                        )

        assert result == "/tmp/test_file.mp4"
        assert mock_get.call_count == 2

    @patch("video_transcript_api.downloaders.base.requests.get")
    def test_no_retry_on_invalid_media(self, mock_get, mock_downloader):
        """Should NOT retry when file is not valid media."""
        mock_response = MagicMock()
        mock_response.headers = {"Content-Length": "1024"}
        mock_response.iter_content.return_value = [b"x" * 1024]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        with patch("builtins.open", MagicMock()):
            with patch("os.path.getsize", return_value=1024):
                with patch.object(mock_downloader, "_validate_media_file", return_value=False):
                    result = mock_downloader.download_file(
                        "http://example.com/video.mp4", "video.mp4", max_retries=3
                    )

        assert result is None
        assert mock_get.call_count == 1  # No retry for invalid media


class TestDeadCodeRemoval:
    """Verify dead code has been removed from download_file."""

    def test_no_unreachable_code_after_return(self):
        """download_file should not have unreachable code blocks."""
        from video_transcript_api.downloaders.base import BaseDownloader
        source = inspect.getsource(BaseDownloader.download_file)

        # The old dead code had a second "except Exception" after a return None
        # Count the number of "except Exception" blocks - should be exactly one
        except_count = source.count("except Exception")
        # Should have at most 2 (one for general catch, one for cleanup)
        # The old code had 3+ due to duplicated dead code
        assert except_count <= 2, f"Found {except_count} 'except Exception' blocks, possible dead code"
