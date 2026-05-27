from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from imdb_lookup_app.routes import router


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="IMDb Bulk Lookup")
app.include_router(router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
