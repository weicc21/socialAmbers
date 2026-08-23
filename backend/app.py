"""Thin Flask transport over the inspectable runtime-file contract."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from flask import Flask, jsonify, request

from backend.triage import classify
from ingest import CONTROL, EVENTS, RUNTIME, STATE, random_persona, request_run


ROOT = Path(__file__).resolve().parent.parent
BUS = RUNTIME / "complaints.jsonl"
_SIGNAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")


def _json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _jsonl(path: Path, limit: int | None = None) -> list[dict]:
    rows = []
    try:
        for line in path.read_text().splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return rows[-limit:] if limit else rows


def _diagnoses() -> list[dict]:
    diagnoses = []
    for path in sorted(RUNTIME.glob("diagnosis-*.json"), key=lambda item: item.stat().st_mtime):
        value = _json(path, {})
        diagnosis = value.get("diagnosis", value) if isinstance(value, dict) else {}
        if isinstance(diagnosis, dict) and diagnosis:
            diagnoses.append(diagnosis)
    return diagnoses


def _work_in_flight() -> bool:
    control = _json(CONTROL, {})
    if control.get("run_requested") or int(control.get("queued", 0) or 0) > 0:
        return True
    state = _json(STATE, {})
    if any(signal.get("status") == "investigating" for signal in state.get("signals", [])):
        return True
    try:
        return datetime.now().timestamp() - EVENTS.stat().st_mtime < 3.0
    except OSError:
        return False


def create_app() -> Flask:
    app = Flask(__name__)
    bus_lock = Lock()

    @app.get("/api/health")
    def health() -> tuple[Any, int]:
        return jsonify({"status": "ok", "service": "socialclues-backend"}), 200

    @app.post("/api/classify")
    def classify_text() -> tuple[Any, int]:
        payload = request.get_json(silent=True) or {}
        return jsonify(asdict(classify(str(payload.get("text", ""))))), 200

    @app.get("/api/complaints")
    def complaints() -> tuple[Any, int]:
        return jsonify({"complaints": list(reversed(_jsonl(BUS)))}), 200

    @app.post("/api/complaints")
    def post_complaint() -> tuple[Any, int]:
        payload = request.get_json(silent=True) or {}
        text = str(payload.get("text", "")).strip()
        if not text:
            return jsonify({"error": "text is required"}), 400
        persona = payload.get("persona")
        if not isinstance(persona, (list, tuple)) or len(persona) != 3:
            persona = random_persona()
        name, handle, avatar = (str(value) for value in persona)
        import secrets

        complaint = {
            "id": f"live-{secrets.token_hex(3)}",
            "name": name,
            "handle": handle,
            "avatar": avatar,
            "time": "0m",
            "source": "customer report",
            "text": text,
        }
        RUNTIME.mkdir(parents=True, exist_ok=True)
        with bus_lock, BUS.open("a") as stream:
            stream.write(json.dumps(complaint) + "\n")
        return jsonify(complaint), 201

    @app.get("/api/state")
    def state() -> tuple[Any, int]:
        return jsonify(_json(STATE, {})), 200

    @app.get("/api/events")
    def events() -> tuple[Any, int]:
        limit = min(max(int(request.args.get("limit", 400)), 1), 2000)
        return jsonify({"events": _jsonl(EVENTS, limit)}), 200

    @app.get("/api/control")
    def control() -> tuple[Any, int]:
        return jsonify(_json(CONTROL, {})), 200

    @app.post("/api/run")
    def run_pipeline() -> tuple[Any, int]:
        request_run()
        return jsonify({"requested": True}), 202

    @app.get("/api/diagnoses")
    def diagnoses() -> tuple[Any, int]:
        return jsonify({"diagnoses": _diagnoses()}), 200

    @app.get("/api/work")
    def work() -> tuple[Any, int]:
        return jsonify({"in_flight": _work_in_flight()}), 200

    @app.get("/api/fix/<signal_id>/status")
    def fix_status(signal_id: str) -> tuple[Any, int]:
        if not _SIGNAL_ID.fullmatch(signal_id):
            return jsonify({"error": "invalid signal id"}), 400
        return jsonify(_json(RUNTIME / f"fix-status-{signal_id}.json", {})), 200

    @app.post("/api/fix/<signal_id>")
    def fix(signal_id: str) -> tuple[Any, int]:
        if not _SIGNAL_ID.fullmatch(signal_id):
            return jsonify({"error": "invalid signal id"}), 400
        instruction = RUNTIME / f"fix-{signal_id}.md"
        fixture = ROOT / "engine" / "fixtures" / "agent_fixes" / f"{signal_id}.json"
        if not instruction.is_file() or not fixture.is_file():
            return jsonify({"error": "instruction or verified fixture missing"}), 404
        status = _json(RUNTIME / f"fix-status-{signal_id}.json", {})
        if status.get("status") in {"requested", "running", "completed"}:
            return jsonify(status), 409
        status_path = RUNTIME / f"fix-status-{signal_id}.json"
        temporary = status_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"status": "requested", "signal_id": signal_id, "mode": "fixture"}) + "\n")
        temporary.replace(status_path)
        subprocess.Popen(
            [sys.executable, str(ROOT / "agent.py"), signal_id, "--fixture-replay"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return jsonify({"status": "requested", "signal_id": signal_id, "mode": "fixture"}), 202

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
