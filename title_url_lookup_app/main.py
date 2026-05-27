import os
import sys
from pathlib import Path

# Add root folder to sys.path for Vercel import resolution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from title_url_lookup_app.routes import router


BASE_DIR = Path(__file__).resolve().parent

root_path = "/title-lookup" if os.environ.get("VERCEL") == "1" else ""

app = FastAPI(title="Title URL Finder", root_path=root_path)
app.include_router(router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
