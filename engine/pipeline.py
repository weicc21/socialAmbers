"""Deterministic diagnosis entrypoint with no agent in the evidence path.

An agent once called investigation and fix proposal in a fixed order here. That
was ceremony rather than a decision, and it inserted a nondeterministic hop into
the component whose evidence fusion must be provable. This module returns both
validated structure for machines and a self-contained instruction for a later,
replaceable actor; the actor never participates in diagnosis.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from engine.correlate import correlate, propose_fix
from engine.fix_prompt import fix_prompt
from engine.reviews import ReviewClient
from engine.schema import validate
from engine.telemetry import TelemetryClient


def diagnose(
    signal: dict,
    *,
    telemetry: TelemetryClient | None = None,
    reviews: ReviewClient | None = None,
    on_event: Callable[[str, str], None] | None = None,
) -> dict:
    emit = on_event or (lambda _stage, _detail: None)
    evidence = signal.get("evidence", {})
    feature = str(signal.get("feature", ""))
    complaint_count = int(evidence.get("complaintCount", 0))
    distinct_authors = int(evidence.get("distinctAuthors", 0))
    families = [str(item) for item in evidence.get("families", [])]
    tokens = [str(item) for item in evidence.get("tokens", [])]
    emit("engine.start", f"{feature} · {complaint_count} reports from {distinct_authors} people")
    emit("engine.families", ", ".join(families) if families else "no complaint families supplied")
    emit("engine.tokens", ", ".join(tokens) if tokens else "no candidate tokens supplied")

    diagnosis = correlate(
        signal_id=str(signal.get("signalId", "")),
        symptom=str(signal.get("symptom", "")),
        feature=feature,
        telemetry=telemetry or TelemetryClient(),
        families=families,
        tokens=tokens,
        reviews=reviews or ReviewClient(),
        on_event=emit,
    )
    payload = diagnosis.to_dict()
    payload["social_context"] = {
        "summary": str(signal.get("symptom", "")),
        "complaint_count": complaint_count,
        "distinct_authors": distinct_authors,
        "families": families,
        "exemplars": [str(item) for item in evidence.get("exemplars", [])][:3],
        "artifacts": evidence.get("artifacts", {}),
    }
    problems = validate(payload)
    if problems:
        emit("schema.invalid", "; ".join(problems))
        payload["_schema_problems"] = problems

    fix = propose_fix(diagnosis)
    diagnosis.proposed_fix = fix
    payload["proposed_fix"] = asdict(fix)
    prompt = fix_prompt(diagnosis, fix)
    emit("fix.ready", fix.strategy)
    target = diagnosis.patch_target
    target_name = target.file if target else "no patch target"
    emit("fix.target", f"{target_name} · {len(prompt.splitlines())} line instruction")
    for detail in diagnosis.degraded:
        emit("engine.degraded", detail)
    if diagnosis.prior_review:
        review = diagnosis.prior_review
        state = "addressed" if review.get("addressed") else "unaddressed"
        emit(
            "evidence.prior_review",
            f"PR #{review.get('pr')} [{review.get('severity')}] {review.get('title')} — {state}",
        )
    emit(
        "diagnosis.ready",
        f"{diagnosis.id} · mode={diagnosis.mode} · confidence {diagnosis.confidence:.2f}",
    )
    return {"diagnosis": payload, "fix": asdict(fix), "prompt": prompt}
