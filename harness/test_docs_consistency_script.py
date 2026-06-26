import subprocess
import sys
import re
from pathlib import Path


def test_docs_runtime_consistency_script_passes_without_traceback():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "verify_docs_runtime_consistency.py")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "Traceback" not in result.stderr
    assert result.returncode == 0, result.stdout + result.stderr


def test_api_docs_only_list_registered_backend_routes():
    from backend.main import app

    root = Path(__file__).resolve().parents[1]
    docs = (root / "docs" / "API.md").read_text(encoding="utf-8")
    actual_shapes = {
        re.sub(r"<[^>]+>", "<var>", str(rule))
        for rule in app.url_map.iter_rules()
    }
    documented = []
    for line in docs.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        method = cells[0].strip("`")
        path = cells[1].strip("`")
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "WS"} and path.startswith(("/api/", "/ws/")):
            documented.append(path.split("?")[0])
    missing = [
        path
        for path in documented
        if re.sub(r"<[^>]+>", "<var>", path) not in actual_shapes
    ]
    assert missing == []


def test_frontend_docs_match_navigation_routes():
    root = Path(__file__).resolve().parents[1]
    docs = (root / "docs" / "FRONTEND.md").read_text(encoding="utf-8")
    app = (root / "frontend" / "src" / "app" / "App.tsx").read_text(encoding="utf-8")
    nav_routes = re.findall(r'to:\s*"([^"]+)"', app)
    documented_routes = re.findall(r"\| `(/[^`]+)` \|", docs)
    assert documented_routes == nav_routes
