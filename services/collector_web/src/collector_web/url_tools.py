from __future__ import annotations

import urllib.error
import urllib.request
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

SHORT_URL_HOSTS = {
    "b23.tv",
    "d.dedao.cn",
    "youtu.be",
}


def normalize_url_for_match(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""

    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)), doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def resolve_short_url(url: str, timeout_seconds: int) -> str:
    normalized = normalize_url_for_match(url)
    if not normalized:
        return ""

    parsed = urlsplit(normalized)
    if parsed.netloc.lower() not in SHORT_URL_HOSTS:
        return normalized

    request = urllib.request.Request(normalized, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            resolved_url = response.geturl()
    except urllib.error.HTTPError:
        resolved_url = normalized
    except Exception:
        resolved_url = normalized

    if resolved_url == normalized:
        fallback_request = urllib.request.Request(normalized, method="GET")
        try:
            with urllib.request.urlopen(fallback_request, timeout=timeout_seconds) as response:
                resolved_url = response.geturl()
        except Exception:
            resolved_url = normalized

    return normalize_url_for_match(resolved_url or normalized)


def canonicalize_manual_media_url(url: str, timeout_seconds: int) -> dict[str, str]:
    normalized_url = normalize_url_for_match(url)
    if not normalized_url:
        return {
            "normalized_url": "",
            "resolved_url": "",
            "canonical_url": "",
        }

    resolved_url = resolve_short_url(normalized_url, timeout_seconds)
    canonical_url = _canonicalize_known_platform_url(resolved_url or normalized_url)
    return {
        "normalized_url": normalized_url,
        "resolved_url": resolved_url,
        "canonical_url": canonical_url,
    }


def _canonicalize_known_platform_url(url: str) -> str:
    normalized = normalize_url_for_match(url)
    if not normalized:
        return ""

    parsed = urlsplit(normalized)
    host = parsed.netloc.lower()
    path = parsed.path or "/"
    query = parse_qs(parsed.query)

    if host in {"d.dedao.cn"}:
        return normalized

    if host in {"dedao.cn", "www.dedao.cn"} and path.startswith("/share/course/article"):
        share_id = _first_non_empty(query.get("id", []))
        if share_id:
            return f"https://www.dedao.cn/share/course/article?id={share_id}"
        return normalize_url_for_match(f"https://www.dedao.cn{path}")

    if host in {"youtu.be"}:
        video_id = path.strip("/")
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"

    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if path == "/watch":
            video_id = _first_non_empty(query.get("v", []))
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"
        if path.startswith("/shorts/") or path.startswith("/live/"):
            video_id = path.strip("/").split("/", 1)[1]
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"

    if host in {"bilibili.com", "www.bilibili.com"} and path.startswith("/video/"):
        video_id = path.strip("/").split("/", 1)[1]
        if video_id:
            return f"https://www.bilibili.com/video/{video_id}"

    if host in {"xiaoyuzhoufm.com", "www.xiaoyuzhoufm.com"}:
        segments = [segment for segment in path.split("/") if segment]
        if len(segments) >= 2 and segments[0] in {"episode", "podcast"}:
            return f"https://www.xiaoyuzhoufm.com/{segments[0]}/{segments[1]}"

    return normalized


def _first_non_empty(values: list[str]) -> str:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""
