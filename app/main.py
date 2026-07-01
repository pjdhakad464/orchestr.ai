import os
import sys
from pathlib import Path

# Add root folder to sys.path for Vercel import resolution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes import router
from app.api.v1.router import router as api_v1_router
from app.database import init_databases

BASE_DIR = Path(__file__).resolve().parent

# Initialize databases on import / startup
init_databases()

app = FastAPI(title="OrchestrAI DataOps Platform")
app.include_router(router)
app.include_router(api_v1_router, prefix="/api/v1")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
