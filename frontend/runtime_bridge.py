"""HTTP bridge from Streamlit presentation to the Flask backend."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import requests


API_URL = os.getenv("API_URL", "http://127.0.0.1:5000").rstrip("/")
TIMEOUT = 2.0

_CHANNEL = {
    "ingest.seed": ("INGEST", "info"), "ingest.queued": ("QUEUE", "warn"),
    "bus.malformed": ("BUS ERROR", "crash"), "triage": ("TRIAGE", "info"),
    "dedup.drop": ("DEDUP", "dim"), "signal.created": ("SIGNAL", "accent"),
    "signal.reinforced": ("SIGNAL", "info"), "signal.absorbed": ("SIGNAL", "dim"),
    "threshold.cross": ("THRESHOLD", "accent"), "engine.start": ("ENGINE", "info"),
    "engine.families": ("FAMILIES", "dim"), "engine.tokens": ("TOKENS", "code"),
    "engine.degraded": ("EVIDENCE GAP", "warn"), "engine.error": ("ENGINE ERROR", "crash"),
    "stage.1.temporal": ("TEMPORAL", "info"), "stage.1.deploy": ("DEPLOY", "accent"),
    "stage.2.logs": ("LOGS", "info"), "stage.2.join": ("TELEMETRY JOIN", "ok"),
    "stage.2.mode": ("MODE", "accent"), "stage.3.callgraph": ("CALLGRAPH", "code"),
    "stage.3.review": ("REVIEW JOIN", "accent"), "stage.3.corroborate": ("CORROBORATE", "ok"),
    "stage.4.fusion": ("FUSION", "cause"), "mode.degradation": ("DEGRADATION", "warn"),
    "evidence.prior_review": ("PRIOR REVIEW", "accent"), "contradiction": ("CONTRADICTION", "warn"),
    "fix.target": ("PATCH TARGET", "cause"), "fix.ready": ("FIX READY", "ok"),
    "diagnosis.ready": ("DIAGNOSIS", "cause"), "schema.invalid": ("SCHEMA ERROR", "crash"),
    "greptile.live": ("GREPTILE LIVE", "ok"), "greptile.failure": ("GREPTILE FAILURE", "crash"),
    "greptile.cache": ("GREPTILE CACHE", "warn"), "stage.3.semantic": ("CODE INTEL", "code"),
    "actor.fixture": ("FIX AGENT", "accent"), "actor.handoff": ("FIX AGENT", "accent"),
    "actor.queued": ("FIX AGENT", "warn"), "actor.branch": ("FIX AGENT", "code"),
    "actor.verify": ("FIX AGENT", "ok"), "actor.completed": ("FIX AGENT", "ok"),
    "actor.failure": ("FIX AGENT", "crash"),
}


def _request(method: str, path: str, **kwargs: Any) -> dict:
    try:
        response = requests.request(method, f"{API_URL}{path}", timeout=TIMEOUT, **kwargs)
        response.raise_for_status()
        value = response.json()
        return value if isinstance(value, dict) else {}
    except (requests.RequestException, ValueError):
        return {}


def is_live() -> bool:
    return _request("GET", "/api/health").get("status") == "ok" and bool(read_state())


def read_complaints() -> list[dict]:
    return list(_request("GET", "/api/complaints").get("complaints", []))


def read_events(limit: int = 400) -> list[dict]:
    return list(_request("GET", f"/api/events?limit={limit}").get("events", []))


def read_state() -> dict:
    return _request("GET", "/api/state")


def signal_for(feature: str) -> dict | None:
    return next((signal for signal in read_state().get("signals", []) if signal.get("feature") == feature), None)


def control() -> dict:
    return _request("GET", "/api/control")


def is_manual() -> bool:
    return control().get("mode") == "manual"


def queued_count() -> int:
    return int(control().get("queued", 0) or 0)


def run_pending() -> bool:
    return bool(control().get("run_requested", False))


def request_run() -> bool:
    return bool(_request("POST", "/api/run").get("requested"))


def work_in_flight() -> bool:
    return bool(_request("GET", "/api/work").get("in_flight", False))


def all_diagnoses() -> list[dict]:
    return list(_request("GET", "/api/diagnoses").get("diagnoses", []))


def latest_diagnosis() -> dict | None:
    diagnoses = all_diagnoses()
    return diagnoses[-1] if diagnoses else None


def post_complaint(text: str, persona: tuple[str, str, str] | None = None) -> dict:
    payload: dict[str, Any] = {"text": text}
    if persona:
        payload["persona"] = list(persona)
    return _request("POST", "/api/complaints", json=payload)


def classify_text(text: str) -> dict:
    return _request("POST", "/api/classify", json={"text": text})


def request_fix(signal_id: str) -> dict:
    return _request("POST", f"/api/fix/{signal_id}")


def fix_status(signal_id: str) -> dict:
    return _request("GET", f"/api/fix/{signal_id}/status")


def events_to_rows(events: list[dict]) -> list[tuple[str, str, str, str]]:
    rows = []
    for event in events:
        kind = str(event.get("type", "unknown"))
        channel, tone = _CHANNEL.get(kind, (kind, "dim"))
        raw_at = str(event.get("at", ""))
        try:
            stamp = datetime.fromisoformat(raw_at.replace("Z", "+00:00")).strftime("%H:%M:%S")
        except ValueError:
            stamp = raw_at[-8:] or "--:--:--"
        rows.append((stamp, channel, str(event.get("detail", "")), tone))
    return rows
