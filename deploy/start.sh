#!/usr/bin/env bash
set -e

echo "Starting database sync download..."
python sync_db.py --download

echo "Starting FastAPI apps..."
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 &
uvicorn title_url_lookup_app.main:app --host 127.0.0.1 --port 8001 --workers 1 &
uvicorn metacritic_calendar_app.main:app --host 127.0.0.1 --port 8002 --workers 1 &
uvicorn imdb_lookup_app.main:app --host 127.0.0.1 --port 8003 --workers 1 &

echo "Starting database monitor daemon..."
python sync_db.py --monitor &

echo "Starting Nginx reverse proxy on port 7860..."
nginx -c /home/user/app/deploy/nginx/hf_nginx.conf -g "daemon off;"
