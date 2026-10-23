from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import settings
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: make sure the data folders exist
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    yield
    # Shutdown: anything after `yield` runs when the server stops


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        debug=settings.debug,
        lifespan=lifespan,
    )
    

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()