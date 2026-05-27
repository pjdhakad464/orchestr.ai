from __future__ import annotations

import argparse
import os
import socket
import sys
from contextlib import closing
from pathlib import Path

import uvicorn


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Playground validator engine without a console window.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--app", default="app.main:app")
    parser.add_argument("--stdout-log", default="")
    parser.add_argument("--stderr-log", default="")
    return parser.parse_args()


def port_is_in_use(host: str, port: int) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.settimeout(1)
        return sock.connect_ex((host, port)) == 0


def configure_streams(stdout_log: Path | None, stderr_log: Path | None) -> None:
    if stdout_log is not None:
        stdout_log.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = stdout_log.open("a", encoding="utf-8", buffering=1)

    if stderr_log is not None:
        stderr_log.parent.mkdir(parents=True, exist_ok=True)
        sys.stderr = stderr_log.open("a", encoding="utf-8", buffering=1)


def main() -> int:
    args = parse_args()

    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent
    os.chdir(project_root)

    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    stdout_log = Path(args.stdout_log) if args.stdout_log else None
    stderr_log = Path(args.stderr_log) if args.stderr_log else None
    configure_streams(stdout_log, stderr_log)

    if port_is_in_use("127.0.0.1", args.port):
        print(f"Validator engine already running on port {args.port}.")
        return 0

    print(f"Starting engine {args.app} on http://{args.host}:{args.port}")
    uvicorn.run(args.app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
