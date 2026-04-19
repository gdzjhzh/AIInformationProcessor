"""
Health check endpoint unit tests.

Covers:
- SQLite health check
- Disk space check
- TCP port check (fallback)
- Overall health status aggregation

All console output must be in English only (no emoji, no Chinese).
"""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest


from video_transcript_api.api.routes.health import (
    _check_sqlite,
    _check_disk_space,
    _check_tcp_port,
)


class TestSQLiteHealthCheck:
    """Verify SQLite health check."""

    @patch("video_transcript_api.api.routes.health.get_cache_manager")
    def test_sqlite_healthy(self, mock_cm):
        """SQLite check should return healthy when DB is accessible."""
        mock_instance = MagicMock()
        mock_instance.db_path = ":memory:"
        mock_cm.return_value = mock_instance

        result = _check_sqlite()
        assert result["healthy"] is True

    @patch("video_transcript_api.api.routes.health.get_cache_manager")
    def test_sqlite_unhealthy(self, mock_cm):
        """SQLite check should return unhealthy on error."""
        mock_cm.side_effect = Exception("db locked")

        result = _check_sqlite()
        assert result["healthy"] is False
        assert "error" in result


class TestDiskSpaceCheck:
    """Verify disk space check."""

    def test_disk_space_returns_result(self):
        """Disk space check should return a valid result."""
        result = _check_disk_space()
        assert "healthy" in result
        assert "free_gb" in result
        assert isinstance(result["free_gb"], float)

    @patch("video_transcript_api.api.routes.health.os.statvfs")
    def test_disk_space_low(self, mock_statvfs):
        """Low disk space should return unhealthy."""
        mock_stat = MagicMock()
        mock_stat.f_bavail = 100  # Very low
        mock_stat.f_frsize = 4096
        mock_statvfs.return_value = mock_stat

        result = _check_disk_space()
        assert result["healthy"] is False
        assert "low disk space" in result.get("error", "")


class TestTCPPortCheck:
    """Verify TCP port fallback check."""

    @patch("socket.socket")
    def test_port_reachable(self, mock_socket_cls):
        """Reachable port should return healthy."""
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0
        mock_socket_cls.return_value = mock_sock

        result = _check_tcp_port("ws://localhost:6016", "CapsWriter")
        assert result["healthy"] is True

    @patch("socket.socket")
    def test_port_unreachable(self, mock_socket_cls):
        """Unreachable port should return unhealthy."""
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 111  # Connection refused
        mock_socket_cls.return_value = mock_sock

        result = _check_tcp_port("ws://localhost:9999", "FunASR")
        assert result["healthy"] is False
        assert "unreachable" in result.get("error", "")
