from video_transcript_api.api.services.model_compare import (
    ModelCompareConfigError,
    _build_candidate_config,
    get_required_model_candidates,
)


def test_model_compare_uses_env_deepseek_v4_and_env_doubao(monkeypatch):
    monkeypatch.setenv("MODEL_COMPARE_MODEL_KEYS", "deepseek,doubao")
    monkeypatch.setenv("MODEL_COMPARE_DEEPSEEK_API_KEY", "deepseek-v4-key")
    monkeypatch.setenv(
        "MODEL_COMPARE_DEEPSEEK_BASE_URL",
        "https://api.deepseek.com/chat/completions",
    )
    monkeypatch.setenv("MODEL_COMPARE_DEEPSEEK_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("MODEL_COMPARE_DEEPSEEK_REASONING_EFFORT", "high")
    monkeypatch.setenv("MODEL_COMPARE_DEEPSEEK_THINKING_TYPE", "enabled")
    monkeypatch.setenv("MODEL_COMPARE_DOUBAO_API_KEY", "doubao-key")
    monkeypatch.setenv(
        "MODEL_COMPARE_DOUBAO_BASE_URL",
        "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
    )
    monkeypatch.setenv("MODEL_COMPARE_DOUBAO_MODEL", "ep-demo")

    config = {
        "llm": {
            "api_key": "deepseek-key",
            "base_url": "https://api.deepseek.com/chat/completions",
            "calibrate_model": "deepseek-chat",
            "calibrate_reasoning_effort": "high",
            "summary_model": "deepseek-chat",
            "summary_reasoning_effort": "high",
            "request_options": {"thinking": {"type": "enabled"}},
            "max_retries": 1,
            "retry_delay": 1,
        }
    }

    candidates = get_required_model_candidates(config)

    assert [candidate.key for candidate in candidates] == ["deepseek", "doubao"]
    assert candidates[0].model == "deepseek-v4-flash"
    assert candidates[0].reasoning_effort is None
    assert candidates[0].thinking_type is None
    assert candidates[1].model == "ep-demo"
    assert candidates[1].reasoning_effort == "minimal"
    assert candidates[1].thinking_type is None

    candidate_config = _build_candidate_config(config, candidates[0])
    assert candidate_config["llm"]["calibrate_model"] == "deepseek-v4-flash"
    assert "calibrate_reasoning_effort" not in candidate_config["llm"]
    assert "request_options" not in candidate_config["llm"]


def test_model_compare_enable_thinking_applies_provider_specific_params(monkeypatch):
    monkeypatch.setenv("MODEL_COMPARE_MODEL_KEYS", "deepseek,doubao")
    monkeypatch.setenv("MODEL_COMPARE_DEEPSEEK_API_KEY", "deepseek-v4-key")
    monkeypatch.setenv(
        "MODEL_COMPARE_DEEPSEEK_BASE_URL",
        "https://api.deepseek.com/chat/completions",
    )
    monkeypatch.setenv("MODEL_COMPARE_DEEPSEEK_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("MODEL_COMPARE_DOUBAO_API_KEY", "doubao-key")
    monkeypatch.setenv(
        "MODEL_COMPARE_DOUBAO_BASE_URL",
        "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
    )
    monkeypatch.setenv("MODEL_COMPARE_DOUBAO_MODEL", "doubao-seed-2-0-lite-260215")

    config = {
        "llm": {
            "api_key": "deepseek-key",
            "base_url": "https://api.deepseek.com/chat/completions",
            "calibrate_model": "deepseek-chat",
            "summary_model": "deepseek-chat",
        }
    }

    candidates = get_required_model_candidates(config, enable_thinking=True)

    assert candidates[0].key == "deepseek"
    assert candidates[0].reasoning_effort == "high"
    assert candidates[0].thinking_type == "enabled"
    assert candidates[1].key == "doubao"
    assert candidates[1].reasoning_effort == "medium"
    assert candidates[1].thinking_type is None

    deepseek_config = _build_candidate_config(config, candidates[0])
    assert deepseek_config["llm"]["calibrate_reasoning_effort"] == "high"
    assert deepseek_config["llm"]["request_options"]["thinking"] == {"type": "enabled"}

    doubao_config = _build_candidate_config(config, candidates[1])
    assert doubao_config["llm"]["calibrate_reasoning_effort"] == "medium"
    assert "request_options" not in doubao_config["llm"]


def test_model_compare_reports_missing_required_model(monkeypatch):
    monkeypatch.setenv("MODEL_COMPARE_MODEL_KEYS", "deepseek,doubao")
    monkeypatch.delenv("MODEL_COMPARE_DOUBAO_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_COMPARE_DOUBAO_BASE_URL", raising=False)
    monkeypatch.delenv("MODEL_COMPARE_DOUBAO_MODEL", raising=False)

    config = {
        "llm": {
            "api_key": "deepseek-key",
            "base_url": "https://api.deepseek.com/chat/completions",
            "calibrate_model": "deepseek-chat",
            "summary_model": "deepseek-chat",
        }
    }

    try:
        get_required_model_candidates(config)
    except ModelCompareConfigError as exc:
        assert "missing doubao" in str(exc)
    else:
        raise AssertionError("expected missing doubao config error")
