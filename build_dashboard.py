#!/usr/bin/env python3
"""Compile the local interactive dashboard to a single offline HTML file."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build_dashboard() -> Path:
    data_path = ROOT / "outputs" / "dashboard_data.json"
    if not data_path.exists():
        raise SystemExit("Run python analysis.py first.")
    data = json.loads(data_path.read_text(encoding="utf-8"))
    safe_json = json.dumps(data, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
    for token in ("__DATA_JSON__", "__CORE_JS__", "__UI_JS__"):
        if template.count(token) != 1:
            raise ValueError(f"Dashboard template must contain exactly one {token} placeholder")
    core_js = (ROOT / "templates" / "dashboard_core.js").read_text(encoding="utf-8")
    ui_js = (ROOT / "templates" / "dashboard_ui.js").read_text(encoding="utf-8")
    output = ROOT / "dist" / "index.html"
    output.parent.mkdir(exist_ok=True)
    output.write_text(template.replace("__DATA_JSON__", safe_json).replace("__CORE_JS__", core_js).replace("__UI_JS__", ui_js), encoding="utf-8")
    print(f"Built {output}")
    return output


if __name__ == "__main__":
    build_dashboard()
