"""Unit tests for DedaoDownloader."""

import json
from unittest.mock import patch

import pytest

from video_transcript_api.downloaders.dedao import DedaoDownloader


def _build_html(initial_state: dict) -> str:
    return (
        "<html><head></head><body><script>"
        f"window.__INITIAL_STATE__= {json.dumps(initial_state, ensure_ascii=False)};</script>"
        "</body></html>"
    )


@pytest.fixture
def downloader():
    with patch(
        "video_transcript_api.downloaders.base.load_config",
        return_value={"storage": {"temp_dir": "./data/temp"}},
    ):
        return DedaoDownloader()


class MockResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _sample_state(video_overrides=None, audio_overrides=None):
    video_payload = {
        "bitrate_720_audio": "https://cdn.example.com/dedao/video_audio.m4a",
        "bitrate_720": "https://cdn.example.com/dedao/video.mp4",
        "caption": "",
        "vtt_caption": "",
    }
    if video_overrides:
        video_payload.update(video_overrides)

    audio_payload = {
        "mp3_play_url": "https://cdn.example.com/dedao/audio.m4a",
    }
    if audio_overrides:
        audio_payload.update(audio_overrides)

    return {
        "packetInfo": {
            "article_id": 117219,
            "article_title": "18｜耿伟 × 脱不花：重新认识你的第二大脑",
            "intro": "深度对谈栏目，每周六更新。",
            "lecturer_list": [
                {"name": "脱不花"},
                {"name": "耿伟"},
            ],
        },
        "newArticleInfo": {
            "article_info": {
                "title": "18｜耿伟 × 脱不花：重新认识你的第二大脑",
                "publish_time": 1759507200,
                "summary": "",
                "audio": audio_payload,
                "video": [video_payload],
            }
        },
        "mediaInfo": {
            "tracks": [
                {
                    "formats": [
                        {"url": "https://cdn.example.com/dedao/stream.m3u8"},
                    ]
                }
            ]
        },
    }


class TestDedaoDownloaderBasic:
    def test_can_handle(self, downloader):
        assert downloader.can_handle("https://d.dedao.cn/GCTnMYcf1f6tUyxd")
        assert downloader.can_handle(
            "https://www.dedao.cn/share/course/article?id=7NqeGmE2w4bnK4ENvnVP31lv5WZ9rj"
        )
        assert not downloader.can_handle("https://www.youtube.com/watch?v=test123")

    def test_extract_video_id(self, downloader):
        assert (
            downloader.extract_video_id(
                "https://www.dedao.cn/share/course/article?id=7NqeGmE2w4bnK4ENvnVP31lv5WZ9rj"
            )
            == "7NqeGmE2w4bnK4ENvnVP31lv5WZ9rj"
        )
        assert downloader.extract_video_id("https://d.dedao.cn/GCTnMYcf1f6tUyxd") == "GCTnMYcf1f6tUyxd"


class TestDedaoDownloaderParsing:
    @patch.object(DedaoDownloader, "resolve_short_url", return_value="https://www.dedao.cn/share/course/article?id=token123&trace=abc")
    @patch("video_transcript_api.downloaders.dedao.requests.get")
    def test_prefers_video_companion_audio(self, mock_get, _mock_resolve_short_url, downloader):
        mock_get.return_value = MockResponse(_build_html(_sample_state()))

        result = downloader.get_video_info("https://d.dedao.cn/GCTnMYcf1f6tUyxd")

        assert result["platform"] == "dedao"
        assert result["video_id"] == "117219"
        assert result["download_url"] == "https://cdn.example.com/dedao/video_audio.m4a"
        assert result["filename"].endswith(".m4a")
        assert result["canonical_url"] == "https://www.dedao.cn/share/course/article?id=token123"
        assert result["author"] == "脱不花 / 耿伟"
        assert result["published_at"].startswith("2025-10-03")

    @patch("video_transcript_api.downloaders.dedao.requests.get")
    def test_falls_back_to_article_audio(self, mock_get, downloader):
        state = _sample_state(
            video_overrides={
                "bitrate_720_audio": "",
                "bitrate_720": "",
            }
        )
        mock_get.return_value = MockResponse(_build_html(state))

        result = downloader.get_video_info(
            "https://www.dedao.cn/share/course/article?id=token123&trace=ignored"
        )

        assert result["download_url"] == "https://cdn.example.com/dedao/audio.m4a"
        assert result["media_type"] == "audio"
        assert result["canonical_url"] == "https://www.dedao.cn/share/course/article?id=token123"

    @patch("video_transcript_api.downloaders.dedao.requests.get")
    def test_get_metadata_includes_extra_fields(self, mock_get, downloader):
        mock_get.return_value = MockResponse(_build_html(_sample_state()))

        metadata = downloader.get_metadata(
            "https://www.dedao.cn/share/course/article?id=token123"
        )

        assert metadata.platform == "dedao"
        assert metadata.video_id == "117219"
        assert metadata.extra["canonical_url"] == "https://www.dedao.cn/share/course/article?id=token123"
        assert metadata.extra["media_type"] == "audio"

    @patch("video_transcript_api.downloaders.dedao.requests.get")
    def test_rejects_pages_without_direct_media_files(self, mock_get, downloader):
        state = _sample_state(
            video_overrides={
                "bitrate_720_audio": "",
                "bitrate_720": "",
            },
            audio_overrides={"mp3_play_url": ""},
        )
        mock_get.return_value = MockResponse(_build_html(state))

        with pytest.raises(ValueError, match="direct media file URL"):
            downloader.get_video_info(
                "https://www.dedao.cn/share/course/article?id=token123"
            )
