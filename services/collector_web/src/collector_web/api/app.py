from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import get_settings
from ..db import init_database
from ..repository import get_dashboard_data


def create_app() -> FastAPI:
    settings = get_settings()
    templates = Jinja2Templates(directory=str(settings.templates_dir))

    app = FastAPI(
        title="Collector Web",
        description="Subscription dashboard for AI Information Processor",
        version="0.1.0",
    )

    if settings.static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

    @app.on_event("startup")
    async def startup_event() -> None:
        init_database(settings)

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "ok": True,
            "db_path": str(settings.db_path),
            "db_exists": settings.db_path.exists(),
        }

    @app.get("/api/collections")
    async def collections_api() -> dict[str, object]:
        return get_dashboard_data(settings)

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        dashboard = get_dashboard_data(settings)
        context = {
            "request": request,
            "summary": dashboard["summary"],
            "collections": dashboard["collections"],
            "platform_groups": dashboard["platform_groups"],
        }
        return templates.TemplateResponse("home.html", context)

    return app
