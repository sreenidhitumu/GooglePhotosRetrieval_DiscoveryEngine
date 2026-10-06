from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from discover.config import project_root
from discover.api.routes.clusters import router as clusters_router
from discover.api.routes.export import router as export_router
from discover.api.routes.opportunities import router as opportunities_router
from discover.api.routes.records import router as records_router
from discover.api.routes.stats import router as stats_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Google Photos Discovery Research API",
        description="Read-only research API for visual retrieval problem discovery",
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # Enable CORS for local UI dev (Phase 6)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_no_cache_header(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    # Include API v1 routers
    app.include_router(stats_router, prefix="/api/v1")
    app.include_router(records_router, prefix="/api/v1")
    app.include_router(clusters_router, prefix="/api/v1")
    app.include_router(opportunities_router, prefix="/api/v1")
    app.include_router(export_router, prefix="/api/v1")

    @app.get("/healthz", tags=["Health"])
    def health_check():
        return {"status": "ok", "service": "google-photos-discovery-api"}

    ui_dir = project_root() / "ui"
    if ui_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")

    return app


app = create_app()
