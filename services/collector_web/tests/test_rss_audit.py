import json

from collector_web.rss_audit import _build_token_history, _normalize_source


def test_normalize_source_exposes_llm_token_usage_totals():
    source = {
        "source_name": "AI News",
        "source_type": "rss",
        "llm_usage": {
            "calls": 3,
            "usage_missing": 1,
            "prompt_tokens": 1200,
            "completion_tokens": 340,
            "total_tokens": 1540,
        },
        "items": [],
    }

    normalized_source = _normalize_source(source)

    assert normalized_source["llm_usage"] == {
        "calls": 3,
        "usage_missing": 1,
        "prompt_tokens": 1200,
        "completion_tokens": 340,
        "total_tokens": 1540,
        "cached_prompt_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "reasoning_tokens": 0,
    }
    assert normalized_source["llm_calls"] == 3
    assert normalized_source["llm_prompt_tokens"] == 1200
    assert normalized_source["llm_completion_tokens"] == 340
    assert normalized_source["llm_total_tokens"] == 1540


def test_build_token_history_groups_poll_runs_by_day(tmp_path):
    poll_runs_dir = tmp_path / "poll_runs"
    month_dir = poll_runs_dir / "2026" / "05"
    month_dir.mkdir(parents=True)
    first_run = {
        "run_finished_at": "2026-05-04T10:00:00Z",
        "llm_usage": {
            "calls": 2,
            "prompt_tokens": 100,
            "completion_tokens": 40,
            "total_tokens": 140,
        },
    }
    second_run = {
        "run_finished_at": "2026-05-04T14:00:00Z",
        "llm_total_tokens": 60,
        "llm_prompt_tokens": 50,
        "llm_completion_tokens": 10,
    }
    third_run = {
        "run_finished_at": "2026-05-05T10:00:00Z",
        "llm_usage": {
            "calls": 1,
            "prompt_tokens": 30,
            "completion_tokens": 20,
            "total_tokens": 50,
        },
    }

    (month_dir / "execution-1_01_rss_to_obsidian_raw.json").write_text(
        json.dumps(first_run),
        encoding="utf-8",
    )
    (month_dir / "execution-2_01_rss_to_obsidian_raw.json").write_text(
        json.dumps(second_run),
        encoding="utf-8",
    )
    (month_dir / "execution-3_01_rss_to_obsidian_raw.json").write_text(
        json.dumps(third_run),
        encoding="utf-8",
    )

    history = _build_token_history(poll_runs_dir)

    assert history == [
        {
            "date": "2026-05-04",
            "label": "05-04",
            "execution_count": 2,
            "llm_calls": 2,
            "llm_usage_missing": 0,
            "llm_prompt_tokens": 150,
            "llm_completion_tokens": 50,
            "llm_total_tokens": 200,
            "llm_cached_prompt_tokens": 0,
            "llm_prompt_cache_hit_tokens": 0,
            "llm_prompt_cache_miss_tokens": 0,
            "llm_reasoning_tokens": 0,
        },
        {
            "date": "2026-05-05",
            "label": "05-05",
            "execution_count": 1,
            "llm_calls": 1,
            "llm_usage_missing": 0,
            "llm_prompt_tokens": 30,
            "llm_completion_tokens": 20,
            "llm_total_tokens": 50,
            "llm_cached_prompt_tokens": 0,
            "llm_prompt_cache_hit_tokens": 0,
            "llm_prompt_cache_miss_tokens": 0,
            "llm_reasoning_tokens": 0,
        },
    ]


def test_normalize_source_dedupes_same_item_audit_states():
    episode_url = "https://www.xiaoyuzhoufm.com/episode/69e999241e94ae6921f2901d"
    source = {
        "source_name": "42章经",
        "source_type": "podcast",
        "feed_url": (
            "http://rsshub:1200/xiaoyuzhou/podcast/"
            "648b0b641c48983391a63f98?limit=1"
        ),
        "rss_status": "success",
        "transcript_status": "success",
        "source_gate_status": "changed",
        "item_count": 1,
        "new_item_count": 1,
        "wrote_count": 0,
        "items": [
            {
                "title": "用 Agent 动力学，和 40 个 Agents 一起为「人 + AI」做产品",
                "url": episode_url,
                "published_at": "2026-04-23T13:30:00+00:00",
                "audit_key": episode_url,
                "audit_status": "not_scored",
                "audit_reason": "score_not_available",
                "skip_layer": "pre_llm",
                "llm_ran": False,
            },
            {
                "title": "用 Agent 动力学，和 40 个 Agents 一起为「人 + AI」做产品",
                "url": episode_url,
                "item_id": (
                    "0003981e750732c2225bb4ba06182b25703c6b27cc"
                    "078eb54e4fcf0633026268"
                ),
                "original_id": episode_url,
                "audit_key": (
                    "0003981e750732c2225bb4ba06182b25703c6b27cc"
                    "078eb54e4fcf0633026268"
                ),
                "audit_status": "skipped",
                "audit_reason": "silent_dedupe",
                "audit_detail": (
                    "Qdrant gate treated this item as duplicate or already covered."
                ),
                "dedupe_action": "silent",
                "vault_write_status": "skipped",
                "skip_layer": "qdrant_gate",
                "llm_ran": False,
            },
        ],
    }

    normalized_source = _normalize_source(source)

    assert normalized_source["audit_item_count"] == 1
    assert normalized_source["scored_item_count"] == 0
    assert normalized_source["written_item_count"] == 0
    item = normalized_source["items"][0]
    assert item["original_url"] == episode_url
    assert item["item_id"].startswith("0003981e")
    assert item["published_at"] == "2026-04-23T13:30:00+00:00"
    assert item["audit_status_label"] == "未写入"
    assert item["audit_reason_label"] == "去重跳过"
    assert item["skip_layer_label"] == "去重门禁"
