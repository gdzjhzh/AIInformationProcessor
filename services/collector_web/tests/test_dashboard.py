import json
import sqlite3
from datetime import datetime, timezone

from fastapi.testclient import TestClient

import collector_web.calibration_compare as calibration_compare_module
import collector_web.mainline_llm as mainline_llm_module
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
    n8n_database_path = tmp_path / "n8n" / "database.sqlite"
    mainline_env_path = tmp_path / ".env"
    poll_runs_dir.mkdir(parents=True, exist_ok=True)
    mainline_env_path.write_text(
        "LLM_MODEL=deepseek-v4-flash\n"
        "LLM_REASONING_EFFORT=max\n"
        "LLM_THINKING_TYPE=enabled\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("COLLECTOR_WEB_DB_PATH", str(db_path))
    monkeypatch.setenv("COLLECTOR_WEB_POLL_RUNS_DIR", str(poll_runs_dir))
    monkeypatch.setenv("COLLECTOR_WEB_N8N_DATABASE_PATH", str(n8n_database_path))
    monkeypatch.setenv("COLLECTOR_WEB_QDRANT_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("COLLECTOR_WEB_QDRANT_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("COLLECTOR_WEB_MAINLINE_LLM_ENV_PATH", str(mainline_env_path))
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
    assert "data-calibration-compare-history" in response.text
    assert "校对对比历史" in response.text
    assert "history" in response.text
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
                "items_selected_for_processing": 2,
                "poll_runs_version": 4,
                "sources": [
                    {
                        "source_name": "ruanyifeng-blog",
                        "source_type": "rss",
                        "feed_url": "https://www.ruanyifeng.com/blog/atom.xml",
                        "rss_status": "success",
                        "transcript_status": "not_requested",
                        "source_gate_status": "changed",
                        "is_new_since_last_poll": True,
                        "item_count": 4,
                        "new_item_count": 2,
                        "wrote_count": 2,
                        "qdrant_commit_count": 2,
                        "current_latest_title": "科技爱好者周刊",
                        "wrote_paths": ["/vault/00_Inbox/demo.md"],
                        "dedupe_actions": ["full_push"],
                        "vault_write_statuses": ["written"],
                    }
                ],
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
    assert "最新 RSS 摘要" in response.text
    assert "手动重跑 RSS" in response.text
    assert "RSS 源级解释" in response.text
    assert "ruanyifeng-blog" in response.text
    assert "data-mainline-llm-switch-form" in response.text
    assert 'data-target-model="deepseek-v4-flash"' in response.text
    assert 'data-target-model="deepseek-v4-pro"' in response.text
    assert "当前运行" in response.text
    assert "配置文件" in response.text
    assert "思考模式" in response.text
    assert "推理等级" in response.text
    assert "deepseek-v4-pro" in response.text
    assert "deepseek-v4-flash" in response.text
    assert "enabled" in response.text
    assert "max" in response.text
    assert "/static/js/status.js" in response.text


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
                "items_selected_for_processing": 2,
                "poll_runs_version": 4,
                "sources": [
                    {
                        "source_name": "ruanyifeng-blog",
                        "source_type": "rss",
                        "feed_url": "https://www.ruanyifeng.com/blog/atom.xml",
                        "rss_status": "success",
                        "transcript_status": "not_requested",
                        "source_gate_status": "changed",
                        "is_new_since_last_poll": True,
                        "item_count": 4,
                        "new_item_count": 2,
                        "wrote_count": 0,
                        "qdrant_commit_count": 0,
                        "dedupe_actions": ["silent"],
                        "vault_write_statuses": ["skipped"],
                    }
                ],
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
    assert payload["links"]["rss_poll_rerun"] == "/api/rss-poll/rerun"
    assert payload["links"]["mainline_llm_switch"] == "/api/mainline-llm/switch"
    assert payload["mainline_llm"]["configured_model"] == "deepseek-v4-flash"
    assert payload["mainline_llm"]["live_model"] == ""
    assert payload["mainline_llm"]["configured_reasoning_effort"] == "max"
    assert payload["mainline_llm"]["configured_thinking_type"] == "enabled"
    assert payload["mainline_llm"]["target_model"] == "deepseek-v4-pro"
    assert payload["rss_poll"]["items_selected_for_processing"] == 2
    assert payload["rss_poll"]["source_rows"][0]["source_name"] == "ruanyifeng-blog"
    assert payload["rss_poll"]["source_rows"][0]["dedupe_actions"] == ["silent"]
    assert "silent 去重" in payload["rss_poll"]["source_rows"][0]["explanation"]
    manual_submit_check = next(item for item in payload["checks"] if item["id"] == "manual_submit")
    assert manual_submit_check["status_label"] == "待处理"
    assert manual_submit_check["affects_overall"] is False


def test_rss_poll_latest_api_returns_item_audit(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)
    settings = get_settings()

    poll_run_dir = settings.poll_runs_dir / "2026" / "05"
    poll_run_dir.mkdir(parents=True, exist_ok=True)
    poll_run_path = poll_run_dir / "execution-11863_01_rss_to_obsidian_raw.json"
    poll_run_path.write_text(
        json.dumps(
            {
                "execution_id": "11863",
                "workflow": "01 RSS to Obsidian Raw Inbox",
                "workflow_id": "D3a7Kp9Lm4Qx2Rst",
                "run_started_at": "2026-05-05T01:25:14+00:00",
                "run_finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_count": 1,
                "success_source_count": 1,
                "failed_source_count": 0,
                "new_source_count": 1,
                "transcript_failed_source_count": 0,
                "items_seen": 1,
                "items_selected_for_processing": 1,
                "items_written": 1,
                "poll_runs_version": 6,
                "sources": [
                    {
                        "source_name": "Hacker News",
                        "source_type": "rss",
                        "feed_url": "http://rsshub:1200/hackernews?limit=5",
                        "rss_status": "success",
                        "transcript_status": "not_requested",
                        "source_gate_status": "changed",
                        "item_count": 1,
                        "new_item_count": 1,
                        "wrote_count": 1,
                        "qdrant_commit_count": 1,
                        "dedupe_actions": ["full_push"],
                        "vault_write_statuses": ["written"],
                        "wrote_paths": ["00_Inbox/demo.md"],
                        "items": [
                            {
                                "title": "How OpenAI delivers low-latency voice AI at scale",
                                "url": "https://openai.com/index/delivering-low-latency-voice-ai-at-scale/",
                                "published_at": "2026-05-05T01:00:00+00:00",
                                "item_id": "item-1",
                                "source_gate_status": "changed",
                                "llm_ran": True,
                                "skip_layer": "vault_writer",
                                "audit_status": "written",
                                "audit_reason": "vault_written",
                                "dedupe_action": "full_push",
                                "vault_write_status": "written",
                                "vault_path": "00_Inbox/demo.md",
                                "qdrant_operation": "written",
                                "score": 0.84,
                                "score_scale": 100,
                                "keep_score": 84,
                                "notify_score": 70,
                                "reference_score": 82,
                                "action_score": 15,
                                "confidence": 0.91,
                                "decision_hint": "keep_full",
                                "score_dimensions": {
                                    "personal_relevance": 22,
                                    "information_density": 18,
                                    "novelty": 17,
                                    "actionability": 9,
                                    "long_term_value": 14,
                                    "source_quality": 5,
                                    "penalty": -1,
                                },
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with TestClient(create_app()) as client:
        response = client.get("/api/rss-poll/latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["schema_has_item_details"] is True
    assert payload["poll"]["execution_id"] == "11863"
    assert payload["poll"]["poll_runs_version"] == 6
    assert payload["item_count"] == 1
    assert payload["written_item_count"] == 1
    assert payload["scored_item_count"] == 1
    assert payload["sources"][0]["source_name"] == "Hacker News"
    item = payload["items"][0]
    assert item["title"] == "How OpenAI delivers low-latency voice AI at scale"
    assert item["original_url"].startswith("https://openai.com/")
    assert item["audit_status_label"] == "已写入"
    assert item["audit_reason_label"] == "已写入 Obsidian"
    assert item["source_gate_status_label"] == "有新内容"
    assert item["llm_status_label"] == "LLM 已跑"
    assert item["skip_layer_label"] == "写入层"
    assert item["primary_score"] == 84
    assert item["score_dimensions"]["novelty"] == 17
    assert item["vault_path"] == "00_Inbox/demo.md"


def test_rss_poll_page_shows_audit_table(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)
    settings = get_settings()

    poll_run_dir = settings.poll_runs_dir / "2026" / "05"
    poll_run_dir.mkdir(parents=True, exist_ok=True)
    poll_run_path = poll_run_dir / "execution-11863_01_rss_to_obsidian_raw.json"
    poll_run_path.write_text(
        json.dumps(
            {
                "execution_id": "11863",
                "workflow": "01 RSS to Obsidian Raw Inbox",
                "workflow_id": "D3a7Kp9Lm4Qx2Rst",
                "run_started_at": "2026-05-05T01:25:14+00:00",
                "run_finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_count": 1,
                "success_source_count": 1,
                "failed_source_count": 0,
                "items_seen": 2,
                "items_selected_for_processing": 2,
                "items_written": 1,
                "poll_runs_version": 6,
                "sources": [
                    {
                        "source_name": "Hacker News",
                        "source_type": "rss",
                        "feed_url": "http://rsshub:1200/hackernews?limit=5",
                        "rss_status": "success",
                        "transcript_status": "not_requested",
                        "source_gate_status": "changed",
                        "item_count": 2,
                        "new_item_count": 2,
                        "wrote_count": 1,
                        "items": [
                            {
                                "title": "Agent Skills",
                                "url": "https://example.com/agent-skills",
                                "source_gate_status": "changed",
                                "llm_ran": True,
                                "skip_layer": "vault_writer",
                                "audit_status": "written",
                                "audit_reason": "vault_written",
                                "vault_path": "00_Inbox/agent-skills.md",
                                "keep_score": 88,
                                "score_dimensions": {"novelty": 18},
                            },
                            {
                                "title": "Holiday Video Promo",
                                "url": "https://example.com/holiday-video",
                                "source_gate_status": "changed",
                                "llm_ran": True,
                                "skip_layer": "action_policy",
                                "audit_status": "skipped",
                                "audit_reason": "action_policy_skipped",
                                "audit_detail": "Action policy decided not to write this scored item.",
                                "keep_score": 14,
                                "score_dimensions": {"information_density": 2},
                            },
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with TestClient(create_app()) as client:
        response = client.get("/rss-poll")

    assert response.status_code == 200
    assert "RSS 审计" in response.text
    assert 'href="/rss-poll"' in response.text
    assert "data-rss-search" in response.text
    assert "data-rss-item-row" in response.text
    assert "Agent Skills" in response.text
    assert 'href="https://example.com/agent-skills"' in response.text
    assert "00_Inbox/agent-skills.md" in response.text
    assert "Holiday Video Promo" in response.text
    assert "LLM 已跑" in response.text
    assert "策略层" in response.text
    assert "Source Gate 有新内容" in response.text
    assert "看到 2 条 / 新内容 2 条 / 写入 1 条 / 审计 2 条" in response.text
    assert "88" in response.text
    assert "/static/js/rss_poll.js" in response.text


def test_status_api_shows_n8n_execution_status_separately(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)
    settings = get_settings()

    poll_run_dir = settings.poll_runs_dir / "2026" / "05"
    poll_run_dir.mkdir(parents=True, exist_ok=True)
    poll_run_path = poll_run_dir / "execution-10982_01_rss_to_obsidian_raw.json"
    poll_run_path.write_text(
        json.dumps(
            {
                "run_finished_at": "2026-05-04T11:23:55+00:00",
                "source_count": 11,
                "success_source_count": 10,
                "failed_source_count": 1,
                "items_seen": 34,
                "items_written": 2,
                "items_selected_for_processing": 34,
                "poll_runs_version": 4,
                "sources": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    settings.n8n_database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.n8n_database_path) as conn:
        conn.executescript(
            """
            CREATE TABLE execution_entity (
                id INTEGER PRIMARY KEY,
                workflowId varchar(36) NOT NULL,
                finished boolean NOT NULL,
                mode varchar NOT NULL,
                retryOf varchar,
                retrySuccessId varchar,
                startedAt datetime,
                stoppedAt datetime,
                waitTill datetime,
                status varchar NOT NULL,
                deletedAt datetime,
                createdAt datetime NOT NULL,
                storedAt varchar(2) NOT NULL
            );
            CREATE TABLE execution_data (
                executionId INTEGER PRIMARY KEY,
                workflowData TEXT NOT NULL,
                data TEXT NOT NULL,
                workflowVersionId varchar(36)
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO execution_entity (
                id, workflowId, finished, mode, startedAt, stoppedAt, status, createdAt, storedAt
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'db')
            """,
            [
                (
                    11410,
                    "D3a7Kp9Lm4Qx2Rst",
                    0,
                    "trigger",
                    "2026-05-04 13:00:19.088",
                    None,
                    "running",
                    "2026-05-04 13:00:19.018",
                ),
                (
                    11241,
                    "D3a7Kp9Lm4Qx2Rst",
                    0,
                    "trigger",
                    "2026-05-04 12:00:19.015",
                    "2026-05-04 12:08:48.818",
                    "error",
                    "2026-05-04 12:00:19.002",
                ),
            ],
        )
        conn.execute(
            """
            INSERT INTO execution_data (executionId, workflowData, data, workflowVersionId)
            VALUES (?, '{}', ?, NULL)
            """,
            (
                11241,
                json.dumps(
                    {
                        "resultData": {
                            "lastNodeExecuted": "02 Enrich With LLM",
                            "error": {
                                "description": "LLM response did not include choices[0].message.content",
                                "message": "Error executing workflow with item at index 3",
                            },
                        }
                    }
                ),
            ),
        )

    with TestClient(create_app()) as client:
        response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    rss_check = next(item for item in payload["checks"] if item["id"] == "rss_poll")
    detail_text = "\n".join(rss_check["detail_lines"])
    assert "最新 poll_runs 摘要结束于" in detail_text
    assert "最近调度执行:" in detail_text
    assert "状态: 运行中" in detail_text
    assert "execution 11410" in detail_text
    assert "上一轮调度执行:" in detail_text
    assert "状态: 失败" in detail_text
    assert "最近失败位置: 02 Enrich With LLM；LLM response did not include choices[0].message.content" in detail_text
    assert payload["rss_poll"]["recent_executions"][0]["status"] == "running"


def test_rss_poll_rerun_api_dispatches_webhook(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)

    def fake_trigger(settings):
        assert settings.rss_poll_rerun_url.endswith(
            "/webhook/2f6d0f2b1e9a4c51/rss-poll-rerun-webhook/signal-to-obsidian/local/rss-poll-rerun"
        )
        return {
            "ok": True,
            "accepted": True,
            "status_code": 202,
            "response": {"stage": "01_rss_poll_rerun_dispatched"},
        }

    monkeypatch.setattr(app_module, "trigger_rss_poll_rerun", fake_trigger)

    with TestClient(create_app()) as client:
        response = client.post("/api/rss-poll/rerun")

    assert response.status_code == 202
    payload = response.json()
    assert payload["ok"] is True
    assert payload["accepted"] is True
    assert payload["response"]["stage"] == "01_rss_poll_rerun_dispatched"


def test_mainline_llm_switch_api_switches_allowed_model(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)

    def fake_switch(settings, model):
        assert model == "deepseek-v4-pro"
        return {
            "ok": True,
            "previous_model": "deepseek-v4-flash",
            "configured_model": "deepseek-v4-pro",
            "live_model": "deepseek-v4-pro",
            "target_model": "deepseek-v4-pro",
        }

    monkeypatch.setattr(app_module, "switch_mainline_llm_model", fake_switch)

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/mainline-llm/switch",
            json={"model": "deepseek-v4-pro"},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["ok"] is True
    assert payload["configured_model"] == "deepseek-v4-pro"
    assert payload["live_model"] == "deepseek-v4-pro"


def test_mainline_llm_switch_updates_env_and_restarts_n8n(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)
    settings = get_settings()

    def fake_missing_requirements(settings):
        return []

    def fake_recreate_container(settings, model):
        assert settings.mainline_llm_container_name == "signal-to-obsidian-n8n-1"
        assert model == "deepseek-v4-pro"
        return "deepseek-v4-pro"

    monkeypatch.setattr(mainline_llm_module, "_missing_requirements", fake_missing_requirements)
    monkeypatch.setattr(mainline_llm_module, "_recreate_container_with_model", fake_recreate_container)

    result = mainline_llm_module.switch_mainline_llm_model(settings, "deepseek-v4-pro")

    assert result["previous_model"] == "deepseek-v4-flash"
    assert result["configured_model"] == "deepseek-v4-pro"
    assert result["live_model"] == "deepseek-v4-pro"
    assert settings.mainline_llm_env_path.read_text(encoding="utf-8") == (
        "LLM_MODEL=deepseek-v4-pro\n"
        "LLM_REASONING_EFFORT=high\n"
        "LLM_THINKING_TYPE=enabled\n"
    )


def test_mainline_llm_switch_sets_flash_reasoning_to_max(monkeypatch, tmp_path):
    _prepare_env(monkeypatch, tmp_path)
    settings = get_settings()
    settings.mainline_llm_env_path.write_text(
        "LLM_MODEL=deepseek-v4-pro\n"
        "LLM_REASONING_EFFORT=high\n"
        "LLM_THINKING_TYPE=enabled\n",
        encoding="utf-8",
    )

    def fake_missing_requirements(settings):
        return []

    def fake_recreate_container(settings, model):
        assert settings.mainline_llm_container_name == "signal-to-obsidian-n8n-1"
        assert model == "deepseek-v4-flash"
        return "deepseek-v4-flash"

    monkeypatch.setattr(mainline_llm_module, "_missing_requirements", fake_missing_requirements)
    monkeypatch.setattr(mainline_llm_module, "_recreate_container_with_model", fake_recreate_container)

    result = mainline_llm_module.switch_mainline_llm_model(settings, "deepseek-v4-flash")

    assert result["previous_model"] == "deepseek-v4-pro"
    assert result["configured_model"] == "deepseek-v4-flash"
    assert result["configured_reasoning_effort"] == "max"
    assert result["live_model"] == "deepseek-v4-flash"
    assert settings.mainline_llm_env_path.read_text(encoding="utf-8") == (
        "LLM_MODEL=deepseek-v4-flash\n"
        "LLM_REASONING_EFFORT=max\n"
        "LLM_THINKING_TYPE=enabled\n"
    )


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
