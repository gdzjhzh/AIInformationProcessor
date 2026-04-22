import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    db_path: Path
    templates_dir: Path
    static_dir: Path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    package_dir = Path(__file__).resolve().parent
    db_path_override = os.getenv("COLLECTOR_WEB_DB_PATH")
    if db_path_override:
        db_path = Path(db_path_override)
    else:
        repo_root = next(
            (candidate for candidate in [package_dir, *package_dir.parents] if (candidate / "deploy").exists()),
            None,
        )
        if repo_root is not None:
            db_path = repo_root / "deploy" / "data" / "collector_web" / "collector_web.sqlite"
        else:
            db_path = Path("/data/collector_web.sqlite")

    return Settings(
        host=os.getenv("COLLECTOR_WEB_HOST", "0.0.0.0"),
        port=int(os.getenv("COLLECTOR_WEB_PORT", "8300")),
        db_path=db_path,
        templates_dir=package_dir / "web" / "templates",
        static_dir=package_dir / "web" / "static",
    )
