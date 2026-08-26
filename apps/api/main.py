from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from apps.api.routes import health
from booruradar.core.config import Settings, get_settings
from booruradar.core.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    application = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        debug=resolved_settings.debug,
    )
    application.state.settings = resolved_settings
    application.include_router(health.router)
    return application


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "apps.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    run()
