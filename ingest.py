"""Tail the complaint bus, qualify signals, and dispatch deterministic diagnosis."""

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.signals import Signal, SignalStore
from backend.triage import classify
from engine.telemetry import TelemetryClient


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
BUS = RUNTIME / "complaints.jsonl"
STATE = RUNTIME / "state.json"
EVENTS = RUNTIME / "events.jsonl"
CONTROL = RUNTIME / "control.json"

_HANDLES = [
    ("Avery Kim", "@averyk", "🟣"), ("Mina Park", "@minap", "🟢"),
    ("Noah Jones", "@noahj", "🔵"), ("Priya Shah", "@priyas", "🟠"),
    ("Leo Martin", "@leom", "🟡"), ("Sofia Reed", "@sofiareed", "🔴"),
    ("Eli Brooks", "@elib", "🟤"), ("Nora Chen", "@norac", "⚪"),
    ("Omar Diaz", "@omard", "🟧"), ("Ivy Stone", "@ivys", "🟪"),
    ("Theo Bell", "@theob", "🟦"), ("Lina Wong", "@linaw", "🟩"),
    ("Kai Patel", "@kaip", "🟥"), ("Zoe Miller", "@zoem", "🟨"),
    ("Maya Singh", "@mayas", "🔷"), ("Ben Ortiz", "@beno", "🔶"),
    ("Aya Lewis", "@ayal", "💠"), ("Max Young", "@maxy", "🔸"),
    ("Rae Davis", "@raed", "🔹"), ("Sam Fox", "@samf", "◻️"),
]

_SEED_COMPLAINTS = [
    {"id":"c01","name":"Avery Kim","handle":"@averyk","avatar":"🟣","time":"20m","source":"campaign reply","text":"SAVE20 promo code throws an error page at checkout"},
    {"id":"c02","name":"Mina Park","handle":"@minap","avatar":"🟢","time":"19m","source":"support ticket","text":"Our 40k subscriber send used SAVE20 and the discount code crashed with a 500"},
    {"id":"c03","name":"Noah Jones","handle":"@noahj","avatar":"🔵","time":"18m","source":"community","text":"free money glitch: SAVE20 promo applied it twice and it doubled"},
    {"id":"c04","name":"Priya Shah","handle":"@priyas","avatar":"🟠","time":"17m","source":"social post","text":"SAVE20 coupon stacks infinitely, best bug before they patch it"},
    {"id":"c05","name":"Leo Martin","handle":"@leom","avatar":"🟡","time":"16m","source":"support chat","text":"keep hitting apply on the SAVE20 promo for free money"},
    {"id":"c06","name":"Sofia Reed","handle":"@sofiareed","avatar":"🔴","time":"15m","source":"app review","text":"chatbot says a 30-day return window but final sale has no refund, those policies contradict"},
    {"id":"c07","name":"Eli Brooks","handle":"@elib","avatar":"🟤","time":"14m","source":"session feedback","text":"support bot quoted the 30-day return window, then final sale refused a refund"},
    {"id":"c08","name":"Nora Chen","handle":"@norac","avatar":"⚪","time":"13m","source":"idea portal","text":"assistant claims 30-day returns while the final sale rule says no refund"},
    {"id":"c09","name":"Omar Diaz","handle":"@omard","avatar":"🟧","time":"12m","source":"survey","text":"ai chat made up a 30-day return window that contradicts final sale no refund"},
    {"id":"c10","name":"Ivy Stone","handle":"@ivys","avatar":"🟪","time":"11m","source":"support ticket","text":"payment keeps loading and never finishes"},
    {"id":"c11","name":"Theo Bell","handle":"@theob","avatar":"🟦","time":"10m","source":"community","text":"pay button is spinning during card payment"},
    {"id":"c12","name":"Lina Wong","handle":"@linaw","avatar":"🟩","time":"9m","source":"app review","text":"account login loop is broken"},
    {"id":"c13","name":"Kai Patel","handle":"@kaip","avatar":"🟥","time":"8m","source":"support chat","text":"sign in keeps loading on my account"},
    {"id":"c14","name":"Zoe Miller","handle":"@zoem","avatar":"🟨","time":"7m","source":"session feedback","text":"shipping tracking link is broken"},
    {"id":"c15","name":"Maya Singh","handle":"@mayas","avatar":"🔷","time":"6m","source":"social post","text":"checkout is great"},
    {"id":"c16","name":"Ben Ortiz","handle":"@beno","avatar":"🔶","time":"5m","source":"idea portal","text":"please add dark mode"},
    {"id":"c17","name":"Aya Lewis","handle":"@ayal","avatar":"💠","time":"4m","source":"survey","text":"wish the account had passkeys"},
    {"id":"c18","name":"Max Young","handle":"@maxy","avatar":"🔸","time":"3m","source":"community","text":"@everyone 100x link in bio"},
    {"id":"c19","name":"Rae Davis","handle":"@raed","avatar":"🔹","time":"2m","source":"app review","text":"the price display could be prettier"},
    {"id":"c20","name":"Sam Fox","handle":"@samf","avatar":"◻️","time":"0m","source":"campaign reply","text":"my cart has emotional baggage but checkout is great"},
]


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(path)


def log(kind: str, detail: str, **extra: Any) -> None:
    event = {
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "type": kind,
        "detail": detail,
        **extra,
    }
    rendered = json.dumps(event)
    print(rendered, flush=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a") as handle:
        handle.write(rendered + "\n")


def _control() -> dict[str, Any]:
    try:
        value = json.loads(CONTROL.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def request_run() -> None:
    control = _control()
    control.update({"run_requested": True})
    control.setdefault("mode", "manual")
    control.setdefault("queued", 0)
    _atomic_json(CONTROL, control)


def random_persona() -> tuple[str, str, str]:
    used = set()
    try:
        with BUS.open() as handle:
            for line in handle:
                try:
                    used.add(str(json.loads(line).get("handle", "")))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    available = [persona for persona in _HANDLES if persona[1] not in used]
    if available:
        return random.choice(available)
    name, handle, avatar = random.choice(_HANDLES)
    suffix = 2
    while f"{handle}{suffix}" in used:
        suffix += 1
    return f"{name} {suffix}", f"{handle}{suffix}", avatar


class Ingestor:
    def __init__(
        self,
        threshold: int = 3,
        pace: float = 0.0,
        engine_pace: float = 0.3,
        manual: bool = False,
    ):
        RUNTIME.mkdir(parents=True, exist_ok=True)
        BUS.touch()
        self.offset = 0
        self.pace = pace
        self.engine_pace = engine_pace
        self.manual = manual
        self.store = SignalStore(threshold=threshold, telemetry=TelemetryClient())
        self.dispatched: set[str] = set()
        if manual:
            control = _control()
            control.update({"mode": "manual", "run_requested": False})
            control.setdefault("queued", 0)
            _atomic_json(CONTROL, control)

    def _peek_queued(self) -> int:
        with BUS.open() as handle:
            handle.seek(self.offset)
            return sum(1 for line in handle if line.strip())

    def _report_queued(self) -> None:
        queued = self._peek_queued()
        control = _control()
        control.update({"mode": "manual", "run_requested": False, "queued": queued})
        _atomic_json(CONTROL, control)
        log("ingest.queued", f"{queued} complaints waiting for a manual run", queued=queued)

    def _read_new(self) -> list[dict]:
        complaints = []
        with BUS.open() as handle:
            handle.seek(self.offset)
            for line in handle:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        complaints.append(value)
                    else:
                        log("bus.malformed", "complaint line is not an object")
                except json.JSONDecodeError as exc:
                    log("bus.malformed", f"invalid JSON: {exc}")
            self.offset = handle.tell()
        return complaints

    def write_state(self) -> None:
        signals = []
        for signal in self.store.signals.values():
            if signal.status == "merged":
                continue
            signals.append(
                {
                    "id": signal.id,
                    "feature": signal.feature,
                    "symptom": signal.symptom,
                    "status": signal.status,
                    "complaint_ids": signal.complaint_ids,
                    "complaint_count": len(signal.complaint_ids),
                    "distinct_authors": signal.distinct_authors,
                    "families": signal.families,
                    "artifacts": signal.artifacts,
                    "first_seen": signal.first_seen.isoformat(timespec="seconds"),
                    "last_seen": signal.last_seen.isoformat(timespec="seconds"),
                    "investigations": signal.investigations,
                }
            )
        signals.sort(key=lambda item: item["complaint_count"], reverse=True)
        _atomic_json(
            STATE,
            {
                "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "signals": signals,
                "counts": {
                    "signals": len(signals),
                    "diagnosed": sum(item["status"] == "diagnosed" for item in signals),
                },
            },
        )

    def _engine_event(self, signal_id: str, kind: str, detail: str) -> None:
        log(kind, detail, signal_id=signal_id)
        if self.engine_pace > 0:
            time.sleep(self.engine_pace)

    def dispatch(self, signal: Signal) -> None:
        payload = signal.to_mcp_payload()
        _atomic_json(RUNTIME / f"signal-{signal.id}.json", payload)
        try:
            from engine.pipeline import diagnose

            output = diagnose(
                payload,
                on_event=lambda kind, detail: self._engine_event(signal.id, kind, detail),
            )
        except Exception as exc:
            log("engine.error", f"{type(exc).__name__}: {exc}", signal_id=signal.id)
            signal.status = "open"
            self.dispatched.discard(signal.id)
            self.write_state()
            return
        _atomic_json(RUNTIME / f"diagnosis-{signal.id}.json", output)
        (RUNTIME / f"fix-{signal.id}.md").write_text(output["prompt"])
        signal.status = "diagnosed"
        self.write_state()
        log("fix.ready", f"fix-{signal.id}.md · hand to an actor to apply", signal_id=signal.id)

    def tick(self) -> None:
        control = _control()
        manual = self.manual or control.get("mode") == "manual"
        if manual and not control.get("run_requested", False):
            self._report_queued()
            return
        if manual:
            control.update({"run_requested": False, "queued": 0})
            _atomic_json(CONTROL, control)
        batch = self._read_new()
        if not batch:
            return
        for complaint in batch:
            verdict = classify(str(complaint.get("text", "")))
            log(
                "triage",
                f"{complaint.get('id')} · {verdict.label} · {verdict.feature or 'unrouted'} · {verdict.reason}",
                complaint_id=complaint.get("id"),
            )
            if self.pace > 0:
                time.sleep(self.pace)
        result = self.store.ingest(batch)
        for duplicate in result["dupes"]:
            log("dedup.drop", f"{duplicate['id']} duplicates {duplicate['duplicateOf']}")
        for signal in result["created"]:
            log("signal.created", f"{signal.feature} · {signal.distinct_authors}/{self.store.threshold} voices")
        for complaint_id in result["absorbed"]:
            log("signal.absorbed", f"{complaint_id} absorbed into its only live specific sibling")
        for signal in result["reinforced"]:
            log("signal.reinforced", f"{signal.feature} · {signal.distinct_authors}/{self.store.threshold} voices")
        self.write_state()
        for signal in result["dispatch"]:
            if signal.id in self.dispatched:
                continue
            self.dispatched.add(signal.id)
            log("threshold.cross", f"{signal.feature} crossed at {signal.distinct_authors} independent voices", signal_id=signal.id)
            self.dispatch(signal)


def seed_bus() -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    ordered = sorted(_SEED_COMPLAINTS, key=lambda complaint: -int(complaint["time"].rstrip("m")))
    with BUS.open("w") as handle:
        for complaint in ordered:
            handle.write(json.dumps(complaint) + "\n")
    log("ingest.seed", f"seeded {len(ordered)} complaints oldest first")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true", help="follow the append-only complaint bus")
    parser.add_argument("--once", action="store_true", help="drain the current backlog and exit")
    parser.add_argument("--seed", action="store_true", help="replace the complaint bus with the deterministic demo feed")
    parser.add_argument("--manual", action="store_true", help="queue arrivals until a run is explicitly requested")
    parser.add_argument("--threshold", type=int, default=3)
    parser.add_argument("--pace", type=float, default=0.0, help="display pacing between real complaints; classification is unchanged")
    parser.add_argument("--engine-pace", type=float, default=0.3, help="display pacing between real engine events; diagnosis is unchanged")
    parser.add_argument("--run", action="store_true", help="request a run from an already-watching manual service")
    args = parser.parse_args()
    if args.run:
        request_run()
        return 0
    if args.seed:
        seed_bus()
        if not args.once and not args.watch:
            return 0
    ingestor = Ingestor(args.threshold, args.pace, args.engine_pace, args.manual)
    if args.once:
        ingestor.tick()
        return 0
    if args.watch:
        while True:
            ingestor.tick()
            time.sleep(0.5)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
