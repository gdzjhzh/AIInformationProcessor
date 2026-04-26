import json
import sqlite3
from datetime import datetime, timezone

from fastapi.testclient import TestClient

import collector_web.calibration_compare as calibration_compare_module
import collector_web.db as db_module
import collector_web.precheck as precheck_module
import collector_web.status as status_module
from collector_web.api import app as app_module
from collector_web.api.app import create_app
from collector_web.config import get_settings
from collector_web.repository import (
    complete_manual_submission,
    create_manual_submission,
    get_manual_submission,
    mark_manual_submission_running,
)

RSS_SOURCE_URLS_JSON = """
[
  {
    "feedUrl": "http://rsshub:1200/bilibili/user/dynamic/946974?limit=1",
    "sourceName": "movie-storm",
    "sourceType": "bilibili-dynamic"
  },
  {
    "feedUrl": "http://rsshub:1200/xiaoyuzhou/podcast/648b0b641c48983391a63f98?limit=1",
    "sourceName": "podcast-42",
    "sourceType": "podcast"
  }
]
""".strip()

UPDATED_RSS_SOURCE_URLS_JSON = """
[
  {
    "feedUrl": "http://rsshub:1200/bilibili/user/dynamic/946974?limit=1",
    "sourceName": "movie-storm",
    "sourceType": "bilibili-dynamic"
  },
  {
    "feedUrl": "http://rsshub:1200/xiaoyuzhou/podcast/648b0b641c48983391a63f98?limit=1",
    "sourceName": "podcast-42",
    "sourceType": "podcast"
  },
  {
    "feedUrl": "https://www.ruanyifeng.com/blog/atom.xml",
    "sourceName": "ruanyifeng-blog",
    "sourceType": "rss"
  }
]
""".strip()


def _prepare_env(monkeypatch, tmp_path, rss_source_urls_json=RSS_SOURCE_URLS_JSON):
    db_path = tmp_path / "collector_web.sqlite"
    poll_runs_dir = tmp_path / "poll_runs"
    poll_runs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("COLLECTOR_WEB_DB_PATH", str(db_path))
    monkeypatch.setenv("COLLECTOR_WEB_POLL_RUNS_DIR", str(poll_runs_dir))
    monkeypatch.setenv("COLLECTOR_WEB_QDRANT_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("COLLECTOR_WEB_QDRANT_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("RSS_SOURCE_URLS_JSON", rss_source_urls_json)
    get_settings.cache_clear()
    return db_path


def test_home_page_shows_subscription_overview_only(monkeypatch, tmp_path):
    db_path = _prepare_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'href="/status"' in response.text
    assert "服务状态" in response.text
    assert 'href="/api/collections"' not in response.text
    assert "当前订阅概览" in response.text
    assert "订阅总览" in response.text
    assert "进入手动提交页" in response.text
    assert "B站" in response.text
    assert "小宇宙" in response.text
    assert "放一个链接，直接开始处理" not in response.text
    assert "手动提交历史" not in response.text
    assert db_path.exists()


def test_manual_media_submit_page_shows_submit_tools_and_history(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        response = client.get("/manual-media-submit")

    assert response.status_code == 200
    assert 'href="/status"' in response.text
    assert "服务状态" in response.text
    assert 'href="/api/collections"' not in response.text
    assert "放一个链接，直接开始处理" in response.text
    assert "手动提交历史" in response.text
    assert "按平台查看订阅" not in response.text


def test_calibration_compare_page_shows_url_submit_tool(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        response = client.get("/calibration-compare")

    assert response.status_code == 200
    assert 'href="/calibration-compare"' in response.text
    assert "校对对比" in response.text
    assert "XIAOYUZHOU URL" in response.text
    assert "开始对比" in response.text
    assert "data-calibration-compare-thinking" in response.text
    assert "open-dir" in response.text
    assert "/static/js/calibration_compare.js" in response.text


def test_calibration_compare_api_publicizes_backend_links(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "COLLECTOR_WEB_CALIBRATION_COMPARE_PUBLIC_BASE_URL",
        "http://127.0.0.1:18080",
    )
    get_settings.cache_clear()

    def fake_submit(settings, url, *, enable_thinking=False):
        assert url == "https://www.xiaoyuzhoufm.com/episode/abc"
        assert enable_thinking is True
        return {
            "ok": True,
            "job": {
                "job_id": "job-1",
                "status": "queued",
                "enable_thinking": True,
                "directory_url": "/model-compare/job-1",
                "file_links": [
                    {
                        "label": "DeepSeek 校对稿",
                        "filename": "2026-04-25_deepseek.md",
                        "url": "/model-compare/job-1/2026-04-25_deepseek.md",
                    }
                ],
            },
        }

    monkeypatch.setattr(app_module, "submit_calibration_compare", fake_submit)

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/calibration-compare",
            json={"url": "https://www.xiaoyuzhoufm.com/episode/abc", "enable_thinking": True},
        )

    assert response.status_code == 202
    job = response.json()["job"]
    assert job["enable_thinking"] is True
    assert job["directory_url"] == "http://127.0.0.1:18080/model-compare/job-1"
    assert job["file_links"][0]["url"] == (
        "http://127.0.0.1:18080/model-compare/job-1/2026-04-25_deepseek.md"
    )


def test_calibration_compare_open_directory_api(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)

    def fake_open_directory(settings, job_id):
        assert job_id == "job-1"
        return {
            "ok": True,
            "job_id": job_id,
            "path": str(tmp_path / "model_compare" / "job-1"),
        }

    monkeypatch.setattr(app_module, "open_calibration_compare_directory", fake_open_directory)

    with TestClient(create_app()) as client:
        response = client.post("/api/calibration-compare/job-1/open-directory")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["job_id"] == "job-1"
    assert payload["path"].endswith("job-1")


def test_open_calibration_compare_directory_maps_container_path(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)
    local_root = tmp_path / "model_compare"
    result_dir = local_root / "2026-04-25_demo_job-1"
    result_dir.mkdir(parents=True)
    monkeypatch.setenv("COLLECTOR_WEB_CALIBRATION_COMPARE_LOCAL_OUTPUT_DIR", str(local_root))
    monkeypatch.setenv("COLLECTOR_WEB_CALIBRATION_COMPARE_CONTAINER_OUTPUT_DIR", "/app/data/model_compare")
    get_settings.cache_clear()

    def fake_get_job(settings, job_id):
        return {
            "ok": True,
            "job": {
                "job_id": job_id,
                "output_dir": "/app/data/model_compare/2026-04-25_demo_job-1",
            },
        }

    opened = []
    monkeypatch.setattr(calibration_compare_module, "get_calibration_compare_job", fake_get_job)
    monkeypatch.setattr(calibration_compare_module, "_open_directory", lambda path: opened.append(path))

    result = calibration_compare_module.open_calibration_compare_directory(get_settings(), "job-1")

    assert result["ok"] is True
    assert result["job_id"] == "job-1"
    assert result["path"] == str(result_dir.resolve())
    assert opened == [result_dir.resolve()]


def test_manual_media_submit_page_shows_cancel_action_for_active_submission(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)
    settings = get_settings()

    with TestClient(create_app()) as client:
        submission = create_manual_submission(
            settings,
            {"url": "https://www.xiaoyuzhoufm.com/episode/abc"},
        )

        response = client.get(f"/manual-media-submit?submission_id={submission['id']}")

    assert response.status_code == 200
    assert "取消提交" in response.text


def test_status_page_shows_human_readable_runtime_summary(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)
    settings = get_settings()

    poll_run_dir = settings.poll_runs_dir / "2026" / "04"
    poll_run_dir.mkdir(parents=True, exist_ok=True)
    poll_run_path = poll_run_dir / "2026-04-23T02-00-31+00-00_01_rss_to_obsidian_raw.json"
    poll_run_path.write_text(
        json.dumps(
            {
                "run_finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_count": 3,
                "success_source_count": 3,
                "failed_source_count": 0,
                "items_seen": 4,
                "items_written": 2,
                "sources": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with TestClient(create_app()) as client:
        response = client.get("/status")

    assert response.status_code == 200
    assert 'href="/health"' in response.text
    assert 'href="/api/status"' in response.text
    assert "服务状态" in response.text
    assert "运行状态总览" in response.text
    assert "查看探活详情" in response.text
    assert "查看状态明细" in response.text
    assert "最近 RSS 轮询" in response.text


def test_status_api_returns_runtime_summary(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)
    settings = get_settings()

    poll_run_dir = settings.poll_runs_dir / "2026" / "04"
    poll_run_dir.mkdir(parents=True, exist_ok=True)
    poll_run_path = poll_run_dir / "2026-04-23T02-00-31+00-00_01_rss_to_obsidian_raw.json"
    poll_run_path.write_text(
        json.dumps(
            {
                "run_finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_count": 3,
                "success_source_count": 3,
                "failed_source_count": 0,
                "items_seen": 4,
                "items_written": 2,
                "sources": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        status_module,
        "get_collection_snapshot",
        lambda settings: {
            "qdrant_base_url": settings.qdrant_base_url,
            "qdrant_collection": settings.qdrant_collection,
            "status": "green",
            "optimizer_status": "ok",
            "points_count": 6,
            "vector_size": 1536,
            "distance": "Cosine",
        },
    )

    with TestClient(create_app()) as client:
        submission = create_manual_submission(
            settings,
            {"url": "https://d.dedao.cn/GCTnMYcf1f6tUyxd"},
        )
        complete_manual_submission(
            settings,
            submission["id"],
            {
                "ok": True,
                "stage": "manual_media_submit",
                "title": "测试得到",
                "item_id": "item-6",
                "canonical_url": "https://www.dedao.cn/share/course/article?id=demo",
                "dedupe_action": "silent",
                "vault_write_status": "skipped",
                "qdrant_operation": "skipped",
            },
        )

        response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall"]["status_label"] == "运行正常"
    assert payload["metrics"]["rss_poll_items_written"] == 2
    assert payload["links"]["health_json"] == "/health"
    assert payload["links"]["status_api"] == "/api/status"
    manual_submit_check = next(item for item in payload["checks"] if item["id"] == "manual_submit")
    assert manual_submit_check["status_label"] == "待处理"
    assert manual_submit_check["affects_overall"] is False


def test_collections_api_returns_platform_summary(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        response = client.get("/api/collections")

    payload = response.json()
    assert response.status_code == 200
    assert payload["summary"]["collection_count"] == 1
    assert payload["summary"]["platform_count"] == 2
    assert payload["summary"]["subscription_count"] == 2
    assert payload["summary"]["active_subscription_count"] == 2
    assert payload["collections"][0]["name"] == "默认订阅合集"
    assert [group["label"] for group in payload["platform_groups"]] == ["B站", "小宇宙"]
    assert payload["manual_submission_summary"]["recent_count"] == 0


def test_manual_media_submit_api_enqueues_background_job(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)

    def fake_enqueue(settings, payload, **kwargs):
        assert settings.manual_media_submit_url
        assert kwargs == {}
        return {
            "id": 7,
            "request_url": payload["url"],
            "status": "queued",
            "status_label": "已排队",
            "status_tone": "muted",
            "is_active": True,
            "request_payload": payload,
            "response_payload": {},
            "qdrant_delete_detail": None,
            "created_at": "2026-04-22T00:00:00+00:00",
            "started_at": None,
            "finished_at": None,
            "updated_at": "2026-04-22T00:00:00+00:00",
            "stage": "collector_web_queue",
            "error": None,
            "rerun_of_submission_id": None,
            "duration_seconds": None,
            "duration_label": "",
            "title": "",
            "item_id": "",
            "canonical_url": "",
            "dedupe_action": "",
            "vault_write_status": "",
            "vault_path": "",
            "summary": "",
            "source_name": "",
            "source_type": "",
            "media_type": "",
            "qdrant_operation": "",
            "workflow_label": "",
            "can_delete_vector_and_rerun": False,
        }

    monkeypatch.setattr(app_module, "enqueue_manual_submission", fake_enqueue)

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/manual-media-submit",
            json={"url": "https://d.dedao.cn/GCTnMYcf1f6tUyxd"},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["ok"] is True
    assert payload["submission"]["id"] == 7
    assert payload["submission"]["request_url"] == "https://d.dedao.cn/GCTnMYcf1f6tUyxd"


def test_cancel_manual_submission_api_marks_queued_request_cancelled(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)
    settings = get_settings()

    with TestClient(create_app()) as client:
        submission = create_manual_submission(
            settings,
            {"url": "https://www.xiaoyuzhoufm.com/episode/queued"},
        )

        response = client.post(f"/api/manual-media-submit/{submission['id']}/cancel")

    assert response.status_code == 202
    payload = response.json()
    assert payload["cancel_mode"] == "cancelled_before_dispatch"
    assert payload["submission"]["status"] == "cancelled"
    assert payload["submission"]["is_active"] is False
    assert payload["submission"]["cancellation_note"]


def test_cancel_manual_submission_api_keeps_cancelled_state_after_running_result(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)
    settings = get_settings()

    with TestClient(create_app()) as client:
        submission = create_manual_submission(
            settings,
            {"url": "https://www.xiaoyuzhoufm.com/episode/running"},
        )
        assert mark_manual_submission_running(settings, submission["id"]) is True

        response = client.post(f"/api/manual-media-submit/{submission['id']}/cancel")
        assert response.status_code == 202
        payload = response.json()
        assert payload["cancel_mode"] == "detached_running_request"
        assert payload["submission"]["status"] == "cancelled"

        completed = complete_manual_submission(
            settings,
            submission["id"],
            {
                "ok": True,
                "stage": "vault_write",
                "title": "不会覆盖已取消状态",
                "item_id": "item-cancelled",
                "canonical_url": "https://www.xiaoyuzhoufm.com/episode/running",
                "dedupe_action": "full_push",
                "vault_write_status": "written",
                "qdrant_operation": "upserted",
            },
        )

    final_submission = get_manual_submission(settings, submission["id"])
    assert completed["status"] == "cancelled"
    assert final_submission["status"] == "cancelled"


def test_manual_media_submit_callback_api_completes_running_submission(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)
    settings = get_settings()

    with TestClient(create_app()) as client:
        submission = create_manual_submission(
            settings,
            {"url": "https://www.xiaoyuzhoufm.com/episode/callback"},
        )
        assert mark_manual_submission_running(settings, submission["id"]) is True

        response = client.post(
            "/api/internal/manual-media-submit-callback",
            json={
                "submission_id": submission["id"],
                "result": {
                    "ok": True,
                    "stage": "vault_write",
                    "title": "鍥炶皟瀹屾垚",
                    "item_id": "item-callback",
                    "canonical_url": "https://www.xiaoyuzhoufm.com/episode/callback",
                    "dedupe_action": "full_push",
                    "vault_write_status": "written",
                    "qdrant_operation": "upserted",
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()["submission"]
    assert payload["status"] == "completed"
    assert payload["stage"] == "vault_write"
    assert payload["item_id"] == "item-callback"
    assert payload["is_active"] is False


def test_manual_submission_detail_api_reads_persisted_history(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)
    settings = get_settings()

    with TestClient(create_app()) as client:
        submission = create_manual_submission(
            settings,
            {"url": "https://www.xiaoyuzhoufm.com/episode/abc"},
        )
        complete_manual_submission(
            settings,
            submission["id"],
            {
                "ok": True,
                "stage": "manual_media_submit",
                "title": "测试播客",
                "item_id": "item-1",
                "canonical_url": "https://www.xiaoyuzhoufm.com/episode/abc",
                "dedupe_action": "silent",
                "vault_write_status": "skipped",
                "qdrant_operation": "skipped",
            },
        )

        response = client.get(f"/api/manual-media-submit/{submission['id']}")

    assert response.status_code == 200
    payload = response.json()["submission"]
    assert payload["status"] == "needs_confirmation"
    assert payload["title"] == "测试播客"
    assert payload["item_id"] == "item-1"
    assert payload["can_delete_vector_and_rerun"] is True


def test_delete_vector_and_rerun_api_returns_new_submission(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)

    def fake_delete_and_rerun(settings, submission_id):
        assert settings.qdrant_collection == "article_embeddings"
        assert submission_id == 11
        return (
            {
                "id": 12,
                "request_url": "https://d.dedao.cn/GCTnMYcf1f6tUyxd",
                "status": "queued",
                "status_label": "已排队",
                "status_tone": "muted",
                "is_active": True,
                "request_payload": {"url": "https://d.dedao.cn/GCTnMYcf1f6tUyxd"},
                "response_payload": {},
                "qdrant_delete_detail": {
                    "count_before": 1,
                    "count_after": 0,
                    "deleted_count": 1,
                },
                "created_at": "2026-04-22T00:00:00+00:00",
                "started_at": None,
                "finished_at": None,
                "updated_at": "2026-04-22T00:00:00+00:00",
                "stage": "collector_web_queue",
                "error": None,
                "rerun_of_submission_id": 11,
                "duration_seconds": None,
                "duration_label": "",
                "title": "",
                "item_id": "",
                "canonical_url": "",
                "dedupe_action": "",
                "vault_write_status": "",
                "vault_path": "",
                "summary": "",
                "source_name": "",
                "source_type": "",
                "media_type": "",
                "qdrant_operation": "",
                "workflow_label": "",
                "can_delete_vector_and_rerun": False,
            },
            {
                "count_before": 1,
                "count_after": 0,
                "deleted_count": 1,
            },
        )

    monkeypatch.setattr(app_module, "delete_vector_and_rerun_submission", fake_delete_and_rerun)

    with TestClient(create_app()) as client:
        response = client.post("/api/manual-media-submit/11/delete-vector-and-rerun")

    assert response.status_code == 202
    payload = response.json()
    assert payload["ok"] is True
    assert payload["submission"]["id"] == 12
    assert payload["deleted_vector"]["deleted_count"] == 1


def test_manual_media_submit_precheck_api_detects_existing_submission(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)
    settings = get_settings()

    with TestClient(create_app()) as client:
        submission = create_manual_submission(
            settings,
            {"url": "https://d.dedao.cn/GCTnMYcf1f6tUyxd"},
        )
        complete_manual_submission(
            settings,
            submission["id"],
            {
                "ok": True,
                "stage": "manual_media_submit",
                "title": "测试得到",
                "item_id": "item-2",
                "canonical_url": "https://www.dedao.cn/share/course/article?id=7NqeGmE2w4bnK4ENvnVP31lv5WZ9rj",
                "dedupe_action": "silent",
                "vault_write_status": "skipped",
                "qdrant_operation": "skipped",
            },
        )

        response = client.post(
            "/api/manual-media-submit/precheck",
            json={"url": "https://d.dedao.cn/GCTnMYcf1f6tUyxd"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["duplicate_found"] is True
    assert payload["match_reason"] == "request_url"
    assert payload["matched_submission"]["id"] == submission["id"]


def test_manual_media_submit_precheck_api_detects_existing_canonical_match(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)
    settings = get_settings()

    with TestClient(create_app()) as client:
        submission = create_manual_submission(
            settings,
            {"url": "https://www.dedao.cn/share/course/article?id=7NqeGmE2w4bnK4ENvnVP31lv5WZ9rj"},
        )
        complete_manual_submission(
            settings,
            submission["id"],
            {
                "ok": True,
                "stage": "manual_media_submit",
                "title": "测试得到",
                "item_id": "item-3",
                "canonical_url": "https://www.dedao.cn/share/course/article?id=7NqeGmE2w4bnK4ENvnVP31lv5WZ9rj",
                "dedupe_action": "silent",
                "vault_write_status": "skipped",
                "qdrant_operation": "skipped",
            },
        )

        monkeypatch.setattr(
            precheck_module,
            "canonicalize_manual_media_url",
            lambda url, timeout_seconds: {
                "normalized_url": "https://d.dedao.cn/GCTnMYcf1f6tUyxd",
                "resolved_url": "https://www.dedao.cn/share/course/article?id=7NqeGmE2w4bnK4ENvnVP31lv5WZ9rj&trace=demo",
                "canonical_url": "https://www.dedao.cn/share/course/article?id=7NqeGmE2w4bnK4ENvnVP31lv5WZ9rj",
            },
        )

        response = client.post(
            "/api/manual-media-submit/precheck",
            json={"url": "https://d.dedao.cn/GCTnMYcf1f6tUyxd"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["duplicate_found"] is True
    assert payload["match_reason"] == "canonical_url"
    assert payload["matched_submission"]["id"] == submission["id"]


def test_collections_api_syncs_new_env_subscription_into_existing_db(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path, RSS_SOURCE_URLS_JSON)

    with TestClient(create_app()) as client:
        first_response = client.get("/api/collections")

    assert first_response.status_code == 200
    assert first_response.json()["summary"]["subscription_count"] == 2

    _prepare_env(monkeypatch, tmp_path, UPDATED_RSS_SOURCE_URLS_JSON)

    with TestClient(create_app()) as client:
        response = client.get("/api/collections")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["subscription_count"] == 3
    assert payload["summary"]["platform_count"] == 3

    rss_group = next(group for group in payload["platform_groups"] if group["platform"] == "rss")
    assert rss_group["subscription_count"] == 1
    assert rss_group["subscriptions"][0]["display_name"] == "ruanyifeng-blog"
    assert rss_group["subscriptions"][0]["source_url"] == "https://www.ruanyifeng.com/blog/atom.xml"


def test_connect_falls_back_to_delete_journal_mode_when_wal_fails(monkeypatch, tmp_path):
    executed = []

    class FakeConnection:
        def __init__(self):
            self.row_factory = None

        def execute(self, sql):
            executed.append(sql)
            if sql == "PRAGMA journal_mode = WAL":
                raise sqlite3.OperationalError("disk I/O error")
            return None

        def commit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(db_module.sqlite3, "connect", lambda *args, **kwargs: FakeConnection())

    with db_module.connect(tmp_path / "collector_web.sqlite"):
        pass

    assert executed == [
        "PRAGMA foreign_keys = ON",
        "PRAGMA busy_timeout = 30000",
        "PRAGMA journal_mode = WAL",
        "PRAGMA journal_mode = DELETE",
    ]
