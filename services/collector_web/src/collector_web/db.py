import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from .config import Settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_env_subscription_sources() -> list[dict[str, str]]:
    raw = os.getenv("RSS_SOURCE_URLS_JSON", "").strip()
    if not raw:
        return []

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if not isinstance(payload, list):
        return []

    sources: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        feed_url = str(item.get("feedUrl", "")).strip()
        if not feed_url:
            continue
        sources.append(
            {
                "feed_url": feed_url,
                "source_name": str(item.get("sourceName", "")).strip() or feed_url,
                "source_type": str(item.get("sourceType", "")).strip() or "rss",
            }
        )
    return sources


def _guess_platform(source_type: str, feed_url: str) -> str:
    source_type = source_type.lower()
    feed_url = feed_url.lower()

    if "bilibili" in source_type or "/bilibili/" in feed_url:
        return "bilibili"
    if "xiaoyuzhou" in source_type or "/xiaoyuzhou/" in feed_url:
        return "xiaoyuzhou"
    if "youtube" in source_type or "youtube" in feed_url:
        return "youtube"
    return "rss"


def _derive_source_identity(source_type: str, feed_url: str) -> tuple[str, str]:
    parsed = urlparse(feed_url)
    parts = [part for part in parsed.path.split("/") if part]
    platform = _guess_platform(source_type, feed_url)

    if platform == "bilibili" and parts[:3] == ["bilibili", "user", "dynamic"] and len(parts) >= 4:
        uid = parts[3]
        return (
            f"bilibili:uid:{uid}:dynamic",
            f"https://space.bilibili.com/{uid}",
        )

    if platform == "xiaoyuzhou" and parts[:2] == ["xiaoyuzhou", "podcast"] and len(parts) >= 3:
        podcast_id = parts[2]
        return (
            f"xiaoyuzhou:podcast:{podcast_id}",
            f"https://www.xiaoyuzhoufm.com/podcast/{podcast_id}",
        )

    if platform == "youtube":
        return (f"rss:{feed_url}", feed_url)

    return (f"rss:{feed_url}", feed_url)


def _sync_env_subscriptions(conn: sqlite3.Connection, collection_id: int) -> None:
    sources = _load_env_subscription_sources()
    if not sources:
        return

    now = utc_now()
    changed = False
    for source in sources:
        source_key, resolved_url = _derive_source_identity(
            source["source_type"], source["feed_url"]
        )
        platform = _guess_platform(source["source_type"], source["feed_url"])
        existing = conn.execute(
            """
            SELECT
                id,
                collection_id,
                display_name,
                platform,
                source_type,
                source_url,
                resolved_url,
                ingest_url,
                status
            FROM subscriptions
            WHERE source_key = ?
            LIMIT 1
            """,
            (source_key,),
        ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO subscriptions (
                    collection_id,
                    display_name,
                    platform,
                    source_type,
                    source_key,
                    source_url,
                    resolved_url,
                    ingest_url,
                    status,
                    notes,
                    tags_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    collection_id,
                    source["source_name"],
                    platform,
                    source["source_type"],
                    source_key,
                    source["feed_url"],
                    resolved_url,
                    source["feed_url"],
                    "active",
                    None,
                    "[]",
                    now,
                    now,
                ),
            )
            changed = True
            continue

        next_status = "active" if existing["status"] == "archived" else existing["status"]
        should_update = any(
            [
                existing["collection_id"] != collection_id,
                existing["display_name"] != source["source_name"],
                existing["platform"] != platform,
                existing["source_type"] != source["source_type"],
                existing["source_url"] != source["feed_url"],
                (existing["resolved_url"] or "") != resolved_url,
                existing["ingest_url"] != source["feed_url"],
                existing["status"] != next_status,
            ]
        )
        if not should_update:
            continue

        conn.execute(
            """
            UPDATE subscriptions
            SET collection_id = ?,
                display_name = ?,
                platform = ?,
                source_type = ?,
                source_url = ?,
                resolved_url = ?,
                ingest_url = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                collection_id,
                source["source_name"],
                platform,
                source["source_type"],
                source["feed_url"],
                resolved_url,
                source["feed_url"],
                next_status,
                now,
                existing["id"],
            ),
        )
        changed = True

    if changed:
        conn.execute(
            "UPDATE collections SET updated_at = ? WHERE id = ?",
            (now, collection_id),
        )


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    try:
        connection.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        connection.execute("PRAGMA journal_mode = DELETE")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_database(settings: Settings) -> None:
    with connect(settings.db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'archived')),
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL REFERENCES collections(id),
                display_name TEXT NOT NULL,
                platform TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_key TEXT NOT NULL UNIQUE,
                source_url TEXT NOT NULL,
                resolved_url TEXT,
                ingest_url TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'disabled', 'archived')),
                notes TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS subscription_runtime_state (
                subscription_id INTEGER PRIMARY KEY REFERENCES subscriptions(id),
                last_checked_at TEXT,
                last_success_at TEXT,
                last_error TEXT,
                last_item_guid TEXT,
                last_item_title TEXT,
                last_item_published_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS manual_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_url TEXT NOT NULL,
                request_payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'running', 'completed', 'needs_confirmation', 'error')),
                stage TEXT NOT NULL DEFAULT 'collector_web_queue',
                error TEXT,
                response_json TEXT,
                rerun_of_submission_id INTEGER REFERENCES manual_submissions(id),
                qdrant_delete_detail TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_manual_submissions_created_at
                ON manual_submissions(created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_manual_submissions_status
                ON manual_submissions(status, created_at DESC, id DESC);
            """
        )

        has_collections = conn.execute("SELECT COUNT(*) FROM collections").fetchone()[0]
        if has_collections == 0:
            now = utc_now()
            conn.execute(
                """
                INSERT INTO collections (
                    name,
                    slug,
                    description,
                    status,
                    sort_order,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "默认订阅合集",
                    "default",
                    "先把首页和基础信息跑起来，后面再加新增、停用和重跑交互。",
                    "active",
                    0,
                    now,
                    now,
                ),
            )

        default_collection = conn.execute(
            "SELECT id FROM collections WHERE slug = 'default' LIMIT 1"
        ).fetchone()
        if default_collection is not None:
            _sync_env_subscriptions(conn, default_collection["id"])
