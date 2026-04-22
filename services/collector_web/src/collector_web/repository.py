from typing import Any

from .config import Settings
from .db import connect

PLATFORM_LABELS = {
    "bilibili": "B站",
    "xiaoyuzhou": "小宇宙",
    "youtube": "YouTube",
    "rss": "RSS",
}


def get_dashboard_data(settings: Settings) -> dict[str, Any]:
    with connect(settings.db_path) as conn:
        summary = conn.execute(
            """
            SELECT
                COUNT(*) AS collection_count,
                COALESCE((
                    SELECT COUNT(*)
                    FROM subscriptions
                    WHERE status != 'archived'
                ), 0) AS subscription_count,
                COALESCE((
                    SELECT COUNT(*)
                    FROM subscriptions
                    WHERE status = 'active'
                ), 0) AS active_subscription_count,
                COALESCE((
                    SELECT COUNT(DISTINCT platform)
                    FROM subscriptions
                    WHERE status != 'archived'
                ), 0) AS platform_count
            FROM collections
            WHERE status != 'archived'
            """
        ).fetchone()

        collection_rows = conn.execute(
            """
            SELECT
                c.id,
                c.name,
                c.slug,
                c.description,
                c.status,
                c.sort_order,
                c.created_at,
                c.updated_at,
                COUNT(s.id) AS subscription_count,
                COALESCE(SUM(CASE WHEN s.status = 'active' THEN 1 ELSE 0 END), 0)
                    AS active_subscription_count
            FROM collections AS c
            LEFT JOIN subscriptions AS s
                ON s.collection_id = c.id
                AND s.status != 'archived'
            WHERE c.status != 'archived'
            GROUP BY c.id
            ORDER BY c.sort_order ASC, c.id ASC
            """
        ).fetchall()

        collections: list[dict[str, Any]] = []
        for row in collection_rows:
            subscriptions = conn.execute(
                """
                SELECT
                    id,
                    display_name,
                    platform,
                    source_type,
                    source_url,
                    resolved_url,
                    ingest_url,
                    status,
                    updated_at
                FROM subscriptions
                WHERE collection_id = ?
                  AND status != 'archived'
                ORDER BY
                    CASE status
                        WHEN 'active' THEN 0
                        WHEN 'disabled' THEN 1
                        ELSE 2
                    END,
                    updated_at DESC,
                    id DESC
                LIMIT 20
                """,
                (row["id"],),
            ).fetchall()

            collections.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "slug": row["slug"],
                    "description": row["description"],
                    "status": row["status"],
                    "subscription_count": row["subscription_count"],
                    "active_subscription_count": row["active_subscription_count"],
                    "updated_at": row["updated_at"],
                    "subscriptions": [dict(subscription) for subscription in subscriptions],
                }
            )

        platform_rows = conn.execute(
            """
            SELECT
                s.id,
                s.display_name,
                s.platform,
                s.source_type,
                s.source_url,
                s.resolved_url,
                s.ingest_url,
                s.status,
                s.updated_at,
                c.name AS collection_name
            FROM subscriptions AS s
            JOIN collections AS c
              ON c.id = s.collection_id
            WHERE s.status != 'archived'
              AND c.status != 'archived'
            ORDER BY
                s.platform ASC,
                CASE s.status
                    WHEN 'active' THEN 0
                    WHEN 'disabled' THEN 1
                    ELSE 2
                END,
                s.updated_at DESC,
                s.id DESC
            """
        ).fetchall()

        platform_groups_map: dict[str, dict[str, Any]] = {}
        for row in platform_rows:
            platform = row["platform"]
            group = platform_groups_map.setdefault(
                platform,
                {
                    "platform": platform,
                    "label": PLATFORM_LABELS.get(platform, platform),
                    "subscription_count": 0,
                    "active_subscription_count": 0,
                    "subscriptions": [],
                },
            )
            group["subscription_count"] += 1
            if row["status"] == "active":
                group["active_subscription_count"] += 1
            subscription = dict(row)
            subscription["platform_label"] = PLATFORM_LABELS.get(platform, platform)
            group["subscriptions"].append(subscription)

        platform_groups = sorted(
            platform_groups_map.values(),
            key=lambda item: item["label"],
        )

        return {
            "summary": {
                "collection_count": summary["collection_count"],
                "subscription_count": summary["subscription_count"],
                "active_subscription_count": summary["active_subscription_count"],
                "platform_count": summary["platform_count"],
            },
            "collections": collections,
            "platform_groups": platform_groups,
        }
