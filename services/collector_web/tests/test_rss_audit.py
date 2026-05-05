from collector_web.rss_audit import _normalize_source


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
