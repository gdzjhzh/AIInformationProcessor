"""
LLMConfig unit tests.

Covers:
- Default values
- from_dict parsing from config dictionary
- select_models_for_task (normal vs risk)
- Edge cases (missing keys, partial config)

All console output must be in English only (no emoji, no Chinese).
"""

import pytest
from video_transcript_api.llm.core.config import LLMConfig


class TestLLMConfigDefaults:
    """Test LLMConfig default values."""

    def test_required_fields(self):
        """Should require api_key, base_url, calibrate_model, summary_model."""
        config = LLMConfig(
            api_key="key",
            base_url="https://api.test.com",
            calibrate_model="model-a",
            summary_model="model-b",
        )
        assert config.api_key == "key"
        assert config.calibrate_model == "model-a"

    def test_default_retry_values(self):
        """Default retry config should be sensible."""
        config = LLMConfig(
            api_key="k", base_url="u",
            calibrate_model="m", summary_model="s",
        )
        assert config.max_retries == 3
        assert config.retry_delay == 5

    def test_default_segment_sizes(self):
        """Default segmentation config should be set."""
        config = LLMConfig(
            api_key="k", base_url="u",
            calibrate_model="m", summary_model="s",
        )
        assert config.segment_size == 2000
        assert config.max_segment_size == 3000
        assert config.enable_threshold == 5000

    def test_default_quality_weights(self):
        """Default quality score weights should sum to 1.0."""
        config = LLMConfig(
            api_key="k", base_url="u",
            calibrate_model="m", summary_model="s",
        )
        total = sum(config.quality_score_weights.values())
        assert abs(total - 1.0) < 0.01


class TestLLMConfigFromDict:
    """Test from_dict parsing."""

    def test_basic_config(self):
        """Should parse basic config dict."""
        config_dict = {
            "llm": {
                "api_key": "test-key",
                "base_url": "https://api.test.com",
                "calibrate_model": "deepseek-chat",
                "summary_model": "deepseek-reasoner",
            }
        }
        config = LLMConfig.from_dict(config_dict)
        assert config.api_key == "test-key"
        assert config.calibrate_model == "deepseek-chat"
        assert config.summary_model == "deepseek-reasoner"

    def test_with_risk_models(self):
        """Should parse risk model configuration."""
        config_dict = {
            "llm": {
                "api_key": "k",
                "base_url": "u",
                "calibrate_model": "normal",
                "summary_model": "normal-summary",
                "risk_calibrate_model": "risk-model",
                "risk_summary_model": "risk-summary",
            }
        }
        config = LLMConfig.from_dict(config_dict)
        assert config.risk_calibrate_model == "risk-model"
        assert config.risk_summary_model == "risk-summary"

    def test_segmentation_config(self):
        """Should parse segmentation config."""
        config_dict = {
            "llm": {
                "api_key": "k", "base_url": "u",
                "calibrate_model": "m", "summary_model": "s",
                "segmentation": {
                    "segment_size": 1500,
                    "max_segment_size": 2500,
                },
            }
        }
        config = LLMConfig.from_dict(config_dict)
        assert config.segment_size == 1500
        assert config.max_segment_size == 2500

    def test_missing_optional_fields_use_defaults(self):
        """Missing optional fields should use defaults."""
        config_dict = {
            "llm": {
                "api_key": "k", "base_url": "u",
                "calibrate_model": "m", "summary_model": "s",
            }
        }
        config = LLMConfig.from_dict(config_dict)
        assert config.max_retries == 3
        assert config.concurrent_workers == 10


class TestLLMConfigSelectModels:
    """Test select_models_for_task method."""

    @pytest.fixture
    def config_with_risk(self):
        return LLMConfig(
            api_key="k", base_url="u",
            calibrate_model="normal-cal",
            summary_model="normal-sum",
            risk_calibrate_model="risk-cal",
            risk_summary_model="risk-sum",
            enable_risk_model_selection=True,
        )

    def test_normal_mode(self, config_with_risk):
        """Without risk, should use normal models."""
        models = config_with_risk.select_models_for_task(has_risk=False)
        assert models["calibrate_model"] == "normal-cal"
        assert models["summary_model"] == "normal-sum"

    def test_risk_mode(self, config_with_risk):
        """With risk, should use risk models."""
        models = config_with_risk.select_models_for_task(has_risk=True)
        assert models["calibrate_model"] == "risk-cal"
        assert models["summary_model"] == "risk-sum"

    def test_risk_disabled_ignores_flag(self):
        """When risk selection disabled, always use normal models."""
        config = LLMConfig(
            api_key="k", base_url="u",
            calibrate_model="normal",
            summary_model="normal-s",
            risk_calibrate_model="risk",
            enable_risk_model_selection=False,
        )
        models = config.select_models_for_task(has_risk=True)
        assert models["calibrate_model"] == "normal"
