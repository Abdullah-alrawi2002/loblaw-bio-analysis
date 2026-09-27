#!/usr/bin/env python3
"""Serve the interactive dashboard built from the SQLite database created by the pipeline.

Run `make pipeline` (or `python load_data.py && python analysis.py`) first.
HOST and PORT environment variables override the default 127.0.0.1:8501.
"""
import json
import os
import sqlite3
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from load_data import ROOT, DB_PATH
from build_dashboard import build_dashboard

PAYLOAD = ROOT / "outputs" / "dashboard_data.json"


def database_sha() -> str:
    with sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        return conn.execute("SELECT value FROM load_metadata WHERE key = 'source_sha256'").fetchone()[0]


def payload_matches_database() -> bool:
    if not PAYLOAD.exists():
        return False
    audit = json.loads(PAYLOAD.read_text(encoding="utf-8")).get("audit", {})
    return audit.get("source_sha256") == database_sha()


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH.name} not found. Run `make pipeline` first.")
    if not payload_matches_database():
        from analysis import run_analysis
        run_analysis()
    build_dashboard()
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8501"))
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT / "dist"))
    try:
        server = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise SystemExit(f"Could not open port {port}. Stop the previous dashboard, set PORT, or open dist/index.html directly.") from exc
    print(f"\nDashboard ready: http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}\nPress Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
