"""Gunicorn configuration for OrchestrAI production deployment.

Usage:
    gunicorn --config gunicorn.conf.py --bind 127.0.0.1:8000 app.main:app

Each systemd service overrides --bind with its own port.
Environment variables:
    WORKERS   — number of worker processes (default: 2)
    LOG_LEVEL — Python log level name       (default: info)
"""
from __future__ import annotations

import multiprocessing
import os

# ---------------------------------------------------------------------------
# Bind — overridden per-service via the systemd ExecStart --bind flag
# ---------------------------------------------------------------------------
bind = f"127.0.0.1:{os.getenv('PORT', '8000')}"

# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------
workers = int(os.getenv("WORKERS", min(2, multiprocessing.cpu_count())))
worker_class = "uvicorn.workers.UvicornWorker"

# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------
timeout = 120           # Allow long scraping / IMDb index operations
graceful_timeout = 30   # Grace period for in-flight requests on restart
keepalive = 5           # Keep-alive seconds between requests

# ---------------------------------------------------------------------------
# Logging — stdout/stderr captured by systemd journal
# ---------------------------------------------------------------------------
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")

# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------
proc_name = "orchestrai"
preload_app = True      # Preload for faster forks and shared memory

# Recycle workers periodically to prevent memory leaks
max_requests = 1000
max_requests_jitter = 50
