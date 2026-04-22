import uvicorn

from ..config import get_settings
from .app import create_app


app = create_app()


def start_server() -> None:
    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port)
