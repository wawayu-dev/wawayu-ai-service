from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name)
    application.include_router(router)
    application.mount(
        "/demo",
        StaticFiles(directory=Path(__file__).with_name("demo"), html=True),
        name="demo",
    )
    return application


app = create_app()
