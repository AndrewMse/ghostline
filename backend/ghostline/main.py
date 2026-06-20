from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .db import Database
from .recorder import Recorder
from .service import Coach
from .sources import Source

log = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


async def _pump(source: Source, recorder: Recorder) -> None:
    """Feed the sim's events into the recorder, restarting the source if it dies."""
    while True:
        try:
            async for event in source.events():
                recorder.handle(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("%s source crashed; restarting", source.sim)
            source.connected = False
            await asyncio.sleep(2.0)


async def _ticker(recorder: Recorder) -> None:
    while True:
        await asyncio.sleep(1.0)
        try:
            recorder.tick()
        except Exception:
            log.exception("recorder tick failed")


def create_app(db_path: str = "ghostline.db", source: Source | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = []
        if source is not None:
            tasks = [asyncio.create_task(_pump(source, app.state.recorder)),
                     asyncio.create_task(_ticker(app.state.recorder))]
        yield
        for task in tasks:
            task.cancel()
        if app.state.recorder is not None:
            app.state.recorder.close_session()
        db.close()

    app = FastAPI(title="Ghostline", version="0.1.0", lifespan=lifespan)
    db = Database(db_path)
    app.state.db = db
    app.state.coach = Coach(db)
    app.state.source = source
    app.state.recorder = Recorder(db, app.state.coach, source.sim) if source else None

    # The Vite dev server runs on another port during development.
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)

    if FRONTEND_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            file = FRONTEND_DIST / path
            if path and file.is_file() and FRONTEND_DIST in file.resolve().parents:
                return FileResponse(file)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app
