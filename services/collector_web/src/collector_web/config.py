import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_MANUAL_MEDIA_SUBMIT_WEBHOOK_PATH = (
    "6b8eaf7c41d2439a/manual-media-submit-webhook/aip/local/manual-media-submit"
)


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    db_path: Path
    templates_dir: Path
    static_dir: Path
    poll_runs_dir: Path
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    package_dir = Path(__file__).resolve().parent
    repo_root = next(
        (candidate for candidate in [package_dir, *package_dir.parents] if (candidate / "deploy").exists()),
        None,
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

    return Settings(
        host=os.getenv("COLLECTOR_WEB_HOST", "0.0.0.0"),
        port=int(os.getenv("COLLECTOR_WEB_PORT", "8300")),
        db_path=db_path,
        templates_dir=package_dir / "web" / "templates",
        static_dir=package_dir / "web" / "static",
        poll_runs_dir=poll_runs_dir,
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
    )
