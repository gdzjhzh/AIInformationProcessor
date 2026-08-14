import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_MANUAL_MEDIA_SUBMIT_WEBHOOK_PATH = (
    "6b8eaf7c41d2439a/manual-media-submit-webhook/signal-to-obsidian/local/manual-media-submit"
)
DEFAULT_RSS_POLL_RERUN_WEBHOOK_PATH = (
    "2f6d0f2b1e9a4c51/rss-poll-rerun-webhook/signal-to-obsidian/local/rss-poll-rerun"
)


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    db_path: Path
    templates_dir: Path
    static_dir: Path
    poll_runs_dir: Path
    n8n_database_path: Path
    rss_poll_rerun_url: str
    rss_poll_rerun_timeout_seconds: int
    manual_media_submit_url: str
    manual_media_submit_timeout_seconds: int
    manual_media_submit_dispatch_timeout_seconds: int
    manual_media_submit_callback_url: str
    manual_media_precheck_timeout_seconds: int
    calibration_compare_api_base_url: str
    calibration_compare_api_key: str
    calibration_compare_public_base_url: str
    calibration_compare_container_output_dir: Path
    calibration_compare_local_output_dir: Path
    calibration_compare_timeout_seconds: int
    qdrant_base_url: str
    qdrant_collection: str
    qdrant_timeout_seconds: int
    rss_poll_stale_minutes: int
    manual_submission_history_limit: int
    mainline_llm_env_path: Path
    mainline_llm_target_model: str
    mainline_llm_allowed_models: tuple[str, ...]
    mainline_llm_reasoning_effort: str
    mainline_llm_thinking_type: str
    mainline_llm_container_name: str
    mainline_llm_docker_socket_path: Path
    feishu_notify_mode: str
    feishu_app_id: str
    feishu_app_secret: str
    feishu_target_chat_id: str
    feishu_callback_verification_token: str
    feishu_callback_encrypt_key: str
    feishu_api_base_url: str
    feishu_request_timeout_seconds: int
    internal_token: str
    ui_password: str
    session_secret: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    package_dir = Path(__file__).resolve().parent
    repo_root_override = os.getenv("COLLECTOR_WEB_REPO_ROOT", "").strip()
    repo_root = Path(repo_root_override) if repo_root_override else next(
        (candidate for candidate in [package_dir, *package_dir.parents] if (candidate / "deploy").exists()),
        None,
    )
    deploy_dir = Path(
        os.getenv(
            "COLLECTOR_WEB_DEPLOY_DIR",
            str((repo_root / "deploy") if repo_root is not None else Path("/workspace/deploy")),
        ).strip()
    )
    mainline_allowed_models = tuple(
        model.strip()
        for model in os.getenv(
            "COLLECTOR_WEB_MAINLINE_LLM_ALLOWED_MODELS",
            "deepseek-v4-flash,deepseek-v4-pro",
        ).split(",")
        if model.strip()
    )
    db_path_override = os.getenv("COLLECTOR_WEB_DB_PATH")
    if db_path_override:
        db_path = Path(db_path_override)
    else:
        if repo_root is not None:
            db_path = repo_root / "deploy" / "data" / "collector_web" / "collector_web.sqlite"
        else:
            db_path = Path("/data/collector_web.sqlite")

    poll_runs_dir_override = os.getenv("COLLECTOR_WEB_POLL_RUNS_DIR", "").strip()
    if poll_runs_dir_override:
        poll_runs_dir = Path(poll_runs_dir_override)
    elif repo_root is not None:
        poll_runs_dir = repo_root / "deploy" / "data" / "n8n" / "storage" / "poll_runs"
    else:
        poll_runs_dir = Path("/data/n8n_poll_runs")

    n8n_database_path_override = os.getenv("COLLECTOR_WEB_N8N_DATABASE_PATH", "").strip()
    if n8n_database_path_override:
        n8n_database_path = Path(n8n_database_path_override)
    elif repo_root is not None:
        n8n_database_path = repo_root / "deploy" / "data" / "n8n" / "database.sqlite"
    else:
        n8n_database_path = Path("/data/n8n/database.sqlite")

    return Settings(
        host=os.getenv("COLLECTOR_WEB_HOST", "0.0.0.0"),
        port=int(os.getenv("COLLECTOR_WEB_PORT", "8300")),
        db_path=db_path,
        templates_dir=package_dir / "web" / "templates",
        static_dir=package_dir / "web" / "static",
        poll_runs_dir=poll_runs_dir,
        n8n_database_path=n8n_database_path,
        rss_poll_rerun_url=os.getenv(
            "COLLECTOR_WEB_RSS_POLL_RERUN_URL",
            f"http://127.0.0.1:5678/webhook/{DEFAULT_RSS_POLL_RERUN_WEBHOOK_PATH}",
        ).strip(),
        rss_poll_rerun_timeout_seconds=int(
            os.getenv("COLLECTOR_WEB_RSS_POLL_RERUN_TIMEOUT_SECONDS", "30")
        ),
        manual_media_submit_url=os.getenv(
            "COLLECTOR_WEB_MANUAL_MEDIA_SUBMIT_URL",
            f"http://127.0.0.1:5780/webhook/{DEFAULT_MANUAL_MEDIA_SUBMIT_WEBHOOK_PATH}",
        ).strip(),
        manual_media_submit_timeout_seconds=int(
            os.getenv("COLLECTOR_WEB_MANUAL_MEDIA_SUBMIT_TIMEOUT_SECONDS", "1800")
        ),
        manual_media_submit_dispatch_timeout_seconds=int(
            os.getenv("COLLECTOR_WEB_MANUAL_MEDIA_SUBMIT_DISPATCH_TIMEOUT_SECONDS", "30")
        ),
        manual_media_submit_callback_url=(
            os.getenv("COLLECTOR_WEB_MANUAL_MEDIA_SUBMIT_CALLBACK_URL", "").strip()
            or (
                os.getenv("COLLECTOR_WEB_CALLBACK_BASE_URL", "http://127.0.0.1:8300").strip().rstrip("/")
                + "/api/internal/manual-media-submit-callback"
            )
        ),
        manual_media_precheck_timeout_seconds=int(
            os.getenv("COLLECTOR_WEB_MANUAL_MEDIA_PRECHECK_TIMEOUT_SECONDS", "10")
        ),
        calibration_compare_api_base_url=os.getenv(
            "COLLECTOR_WEB_CALIBRATION_COMPARE_API_BASE_URL",
            "http://127.0.0.1:18080/api/model-compare",
        ).strip().rstrip("/"),
        calibration_compare_api_key=os.getenv(
            "COLLECTOR_WEB_CALIBRATION_COMPARE_API_KEY",
            "",
        ).strip(),
        calibration_compare_public_base_url=os.getenv(
            "COLLECTOR_WEB_CALIBRATION_COMPARE_PUBLIC_BASE_URL",
            "http://127.0.0.1:18080",
        ).strip().rstrip("/"),
        calibration_compare_container_output_dir=Path(
            os.getenv(
                "COLLECTOR_WEB_CALIBRATION_COMPARE_CONTAINER_OUTPUT_DIR",
                "/app/data/model_compare",
            ).strip()
        ),
        calibration_compare_local_output_dir=Path(
            os.getenv(
                "COLLECTOR_WEB_CALIBRATION_COMPARE_LOCAL_OUTPUT_DIR",
                str(
                    (repo_root / "deploy" / "data" / "video-transcript-api" / "model_compare")
                    if repo_root is not None
                    else Path("data") / "model_compare"
                ),
            ).strip()
        ),
        calibration_compare_timeout_seconds=int(
            os.getenv("COLLECTOR_WEB_CALIBRATION_COMPARE_TIMEOUT_SECONDS", "30")
        ),
        qdrant_base_url=os.getenv(
            "COLLECTOR_WEB_QDRANT_BASE_URL",
            "http://127.0.0.1:6333",
        ).strip(),
        qdrant_collection=os.getenv(
            "COLLECTOR_WEB_QDRANT_COLLECTION",
            os.getenv("QDRANT_COLLECTION", "article_embeddings"),
        ).strip()
        or "article_embeddings",
        qdrant_timeout_seconds=int(
            os.getenv("COLLECTOR_WEB_QDRANT_TIMEOUT_SECONDS", "30")
        ),
        rss_poll_stale_minutes=int(
            os.getenv("COLLECTOR_WEB_RSS_POLL_STALE_MINUTES", "90")
        ),
        manual_submission_history_limit=int(
            os.getenv("COLLECTOR_WEB_MANUAL_SUBMISSION_HISTORY_LIMIT", "12")
        ),
        mainline_llm_env_path=Path(
            os.getenv(
                "COLLECTOR_WEB_MAINLINE_LLM_ENV_PATH",
                str(deploy_dir / ".env"),
            ).strip()
        ),
        mainline_llm_target_model=os.getenv(
            "COLLECTOR_WEB_MAINLINE_LLM_TARGET_MODEL",
            "deepseek-v4-pro",
        ).strip(),
        mainline_llm_allowed_models=mainline_allowed_models,
        mainline_llm_reasoning_effort=os.getenv(
            "COLLECTOR_WEB_MAINLINE_LLM_REASONING_EFFORT",
            "high",
        ).strip()
        or "high",
        mainline_llm_thinking_type=os.getenv(
            "COLLECTOR_WEB_MAINLINE_LLM_THINKING_TYPE",
            "enabled",
        ).strip()
        or "enabled",
        mainline_llm_container_name=os.getenv(
            "COLLECTOR_WEB_MAINLINE_LLM_CONTAINER_NAME",
            "signal-to-obsidian-n8n-1",
        ).strip(),
        mainline_llm_docker_socket_path=Path(
            os.getenv(
                "COLLECTOR_WEB_MAINLINE_LLM_DOCKER_SOCKET_PATH",
                "/var/run/docker.sock",
            ).strip()
        ),
        feishu_notify_mode=os.getenv("FEISHU_NOTIFY_MODE", "webhook").strip().lower()
        or "webhook",
        feishu_app_id=os.getenv("FEISHU_APP_ID", "").strip(),
        feishu_app_secret=os.getenv("FEISHU_APP_SECRET", "").strip(),
        feishu_target_chat_id=os.getenv("FEISHU_TARGET_CHAT_ID", "").strip(),
        feishu_callback_verification_token=os.getenv(
            "FEISHU_VERIFICATION_TOKEN",
            "",
        ).strip(),
        feishu_callback_encrypt_key=os.getenv("FEISHU_ENCRYPT_KEY", "").strip(),
        feishu_api_base_url=os.getenv(
            "FEISHU_API_BASE_URL",
            "https://open.feishu.cn",
        ).strip().rstrip("/"),
        feishu_request_timeout_seconds=int(
            os.getenv("FEISHU_REQUEST_TIMEOUT_SECONDS", "20")
        ),
        internal_token=os.getenv("COLLECTOR_WEB_INTERNAL_TOKEN", "").strip(),
        ui_password=os.getenv("COLLECTOR_WEB_UI_PASSWORD", "").strip(),
        session_secret=os.getenv("COLLECTOR_WEB_SESSION_SECRET", "").strip(),
    )
