import datetime
import json
import os
import re
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from .base import BaseDownloader
from .models import DownloadInfo, VideoMetadata
from ..utils.logging import setup_logger

logger = setup_logger("dedao_downloader")

_INITIAL_STATE_RE = re.compile(
    r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;</script>",
    re.S,
)
_SHARE_PATH_RE = re.compile(r"^/share/course/article(?:/|$)", re.I)
_ARTICLE_ID_PATH_RE = re.compile(r"/article/article_id/(\d+)", re.I)
_SHORT_TOKEN_RE = re.compile(r"^/([A-Za-z0-9]+)$")
_DIRECT_MEDIA_EXTENSIONS = {
    ".mp3",
    ".m4a",
    ".aac",
    ".wav",
    ".ogg",
    ".flac",
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".mkv",
}


def _first_non_empty(*values: Any) -> str:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _safe_filename_component(value: str) -> str:
    sanitized = re.sub(r"[\\/*?:\"<>|]+", "_", str(value or "").strip())
    return sanitized[:80] if sanitized else "dedao"


class DedaoDownloader(BaseDownloader):
    """Downloader for Dedao share pages that expose direct media files."""

    def __init__(self):
        super().__init__()
        self._cached_video_info: dict[str, dict] = {}

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(str(url or "").strip())
        host = parsed.netloc.lower().replace("www.", "")
        path = parsed.path or "/"
        if host == "d.dedao.cn":
            return True
        return host == "dedao.cn" and bool(_SHARE_PATH_RE.search(path))

    def extract_video_id(self, url: str) -> str:
        normalized = str(url or "").strip()
        parsed = urlparse(normalized)
        host = parsed.netloc.lower().replace("www.", "")

        if host == "d.dedao.cn":
            match = _SHORT_TOKEN_RE.match(parsed.path or "")
            if match:
                return match.group(1)

        if host == "dedao.cn":
            query = parse_qs(parsed.query)
            share_id = _first_non_empty(*(query.get("id") or []))
            if share_id:
                return share_id

            article_id_match = _ARTICLE_ID_PATH_RE.search(parsed.path or "")
            if article_id_match:
                return article_id_match.group(1)

        raise ValueError(f"Failed to extract Dedao media identifier from URL: {url}")

    def get_subtitle(self, url: str):
        return None

    def get_video_info(self, url: str) -> dict:
        cache_key = self.extract_video_id(url)
        if cache_key in self._cached_video_info:
            logger.debug(f"[cache hit] Returning cached Dedao info: {cache_key}")
            return self._cached_video_info[cache_key]

        resolved_url = self._resolve_share_url(url)
        canonical_url = self._canonicalize_share_url(resolved_url)
        initial_state = self._fetch_initial_state(canonical_url)
        packet_info = initial_state.get("packetInfo") or {}
        article_info = self._extract_article_info(initial_state)
        media_info = initial_state.get("mediaInfo") or {}

        video_id = _first_non_empty(
            packet_info.get("article_id"),
            article_info.get("article_id"),
            article_info.get("id"),
            cache_key,
        )
        if not video_id:
            raise ValueError(f"Unable to determine Dedao article ID: {url}")

        title = _first_non_empty(
            article_info.get("title"),
            packet_info.get("article_title"),
            article_info.get("share_title"),
            packet_info.get("share_title"),
        )
        if not title:
            title = f"dedao_{video_id}"

        author = self._extract_author(packet_info)
        description = self._extract_description(article_info, packet_info, title)
        published_at = self._extract_published_at(article_info)
        selected_media = self._select_media(article_info, media_info, video_id, title)

        result = {
            "video_id": str(video_id),
            "video_title": title,
            "author": author,
            "description": description,
            "download_url": selected_media["download_url"],
            "filename": selected_media["filename"],
            "platform": "dedao",
            "canonical_url": canonical_url,
            "media_type": selected_media["media_type"],
        }
        if published_at:
            result["published_at"] = published_at

        self._cached_video_info[cache_key] = result
        if str(video_id) != cache_key:
            self._cached_video_info[str(video_id)] = result
        logger.info(
            f"Parsed Dedao share page successfully: video_id={video_id}, "
            f"media_type={selected_media['media_type']}, canonical_url={canonical_url}"
        )
        return result

    def _fetch_metadata(self, url: str, video_id: str) -> VideoMetadata:
        info = self.get_video_info(url)
        extra = {
            "canonical_url": info.get("canonical_url", ""),
            "media_type": info.get("media_type", ""),
        }
        if info.get("published_at"):
            extra["published_at"] = info["published_at"]
        return VideoMetadata(
            video_id=info.get("video_id", video_id),
            platform=info.get("platform", "dedao"),
            title=info.get("video_title", ""),
            author=info.get("author", ""),
            description=info.get("description", ""),
            extra=extra,
        )

    def _fetch_download_info(self, url: str, video_id: str) -> DownloadInfo:
        info = self.get_video_info(url)
        filename = info.get("filename")
        file_ext = None
        if filename and "." in filename:
            file_ext = filename.rsplit(".", 1)[-1]
        return DownloadInfo(
            download_url=info.get("download_url"),
            file_ext=file_ext,
            filename=filename,
        )

    def _resolve_share_url(self, url: str) -> str:
        resolved = str(url or "").strip()
        parsed = urlparse(resolved)
        if parsed.netloc.lower().replace("www.", "") == "d.dedao.cn":
            resolved = self.resolve_short_url(resolved)
        return resolved

    def _canonicalize_share_url(self, url: str) -> str:
        parsed = urlparse(str(url or "").strip())
        host = parsed.netloc.lower().replace("www.", "")
        if host == "dedao.cn" and _SHARE_PATH_RE.search(parsed.path or ""):
            share_id = _first_non_empty(*(parse_qs(parsed.query).get("id") or []))
            if share_id:
                return f"https://www.dedao.cn/share/course/article?id={share_id}"
        return str(url or "").split("#", 1)[0]

    def _fetch_initial_state(self, url: str) -> dict:
        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/135.0.0.0 Safari/537.36"
                )
            },
            timeout=30,
        )
        response.raise_for_status()
        response.encoding = "utf-8"
        match = _INITIAL_STATE_RE.search(response.text)
        if not match:
            raise ValueError("Dedao share page is missing window.__INITIAL_STATE__")
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to decode Dedao __INITIAL_STATE__: {exc}") from exc

    def _extract_article_info(self, initial_state: dict) -> dict:
        new_article_info = initial_state.get("newArticleInfo")
        if isinstance(new_article_info, dict):
            article_info = new_article_info.get("article_info")
            if isinstance(article_info, dict):
                return article_info

        article_info = initial_state.get("articleInfo")
        if isinstance(article_info, dict):
            nested = article_info.get("article_info")
            if isinstance(nested, dict):
                return nested
            return article_info

        raise ValueError("Dedao share page did not expose article_info")

    def _extract_author(self, packet_info: dict) -> str:
        lecturers = packet_info.get("lecturer_list")
        names: list[str] = []
        if isinstance(lecturers, list):
            for lecturer in lecturers:
                if not isinstance(lecturer, dict):
                    continue
                names.extend(
                    _dedupe_strings(
                        [
                            lecturer.get("name", ""),
                            lecturer.get("nick", ""),
                            lecturer.get("title", ""),
                        ]
                    )
                )
        names = _dedupe_strings(names)
        if names:
            return " / ".join(names)
        return _first_non_empty(packet_info.get("nickname"), "得到")

    def _extract_description(
        self,
        article_info: dict,
        packet_info: dict,
        title: str,
    ) -> str:
        candidates = [
            article_info.get("summary"),
            packet_info.get("intro"),
            article_info.get("push_content"),
            article_info.get("share_content"),
            packet_info.get("share_summary"),
        ]
        for value in candidates:
            normalized = _first_non_empty(value)
            if not normalized:
                continue
            if normalized == title:
                continue
            return normalized
        return ""

    def _extract_published_at(self, article_info: dict) -> str:
        for field in ("publish_time", "create_time", "update_time"):
            raw_value = article_info.get(field)
            if raw_value is None or raw_value == "":
                continue
            try:
                timestamp = int(raw_value)
            except (TypeError, ValueError):
                continue
            if timestamp <= 0:
                continue
            return datetime.datetime.fromtimestamp(
                timestamp,
                tz=datetime.timezone.utc,
            ).isoformat()
        return ""

    def _select_media(
        self,
        article_info: dict,
        media_info: dict,
        video_id: str,
        title: str,
    ) -> dict:
        candidates: list[tuple[str, str, str]] = []
        seen: set[str] = set()

        def add_candidate(url: Any, media_type: str, fallback_ext: str) -> None:
            normalized_url = str(url or "").strip()
            if not normalized_url or normalized_url in seen:
                return
            ext = os.path.splitext(urlparse(normalized_url).path)[1].lower()
            if ext:
                if ext in _DIRECT_MEDIA_EXTENSIONS:
                    candidates.append((normalized_url, media_type, ext))
                    seen.add(normalized_url)
                return
            if fallback_ext in _DIRECT_MEDIA_EXTENSIONS:
                candidates.append((normalized_url, media_type, fallback_ext))
                seen.add(normalized_url)

        videos = article_info.get("video")
        if isinstance(videos, list):
            for video in videos:
                if not isinstance(video, dict):
                    continue
                for key in (
                    "bitrate_1080_audio",
                    "bitrate_720_audio",
                    "bitrate_480_audio",
                    "bitrate_360_audio",
                ):
                    add_candidate(video.get(key), "audio", ".m4a")
                for key in (
                    "bitrate_1080",
                    "bitrate_720",
                    "bitrate_480",
                    "bitrate_360",
                ):
                    add_candidate(video.get(key), "video", ".mp4")
                add_candidate(video.get("url"), "video", ".mp4")

        audio_info = article_info.get("audio")
        if isinstance(audio_info, dict):
            for key in ("mp3_play_url", "play_url", "url"):
                add_candidate(audio_info.get(key), "audio", ".m4a")

        tracks = media_info.get("tracks")
        if isinstance(tracks, list):
            for track in tracks:
                if not isinstance(track, dict):
                    continue
                formats = track.get("formats")
                if not isinstance(formats, list):
                    continue
                for fmt in formats:
                    if not isinstance(fmt, dict):
                        continue
                    add_candidate(fmt.get("url"), "audio", ".m4a")

        if not candidates:
            raise ValueError("Dedao share page did not expose a direct media file URL")

        selected_url, media_type, ext = candidates[0]
        filename = (
            f"{_safe_filename_component('dedao')}_"
            f"{_safe_filename_component(video_id)}_"
            f"{int(time.time())}{ext or '.m4a'}"
        )
        logger.info(
            f"Selected Dedao media candidate for '{title[:50]}': "
            f"{selected_url[:120]}..."
        )
        return {
            "download_url": selected_url,
            "filename": filename,
            "media_type": media_type,
        }
