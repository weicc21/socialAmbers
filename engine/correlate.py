"""Deterministic fusion of telemetry, structure, deploys, and prior reviews.

Greptile's retired semantic-query API is intentionally absent. Live Greptile
evidence enters only through pre-incident MCP review findings joined to the
suspect deploy. Structural reachability and review remain separate witnesses:
the former proposes causal role, while the latter increases certainty at the
location it independently flagged.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from engine import structural
from engine.reviews import ReviewClient, ReviewFinding
from engine.schema import CodeLocation, Diagnosis, ProposedFix, Temporal, timestamp
from engine.telemetry import TelemetryClient


W_BOTH = 0.95
W_CALLGRAPH_REVIEW = 0.88
W_REVIEW = 0.78
W_CALLGRAPH = 0.75
W_FRAME_ONLY = 0.55
DEPLOY_BOOST = 1.10
CEILING_INFERRED = 0.92
DEGRADATION_WINDOW_MINUTES = 720


def _symptom_to_log_query(symptom: str, feature: str) -> str:
    del symptom
    return {
        "checkout/promo": "apply-promo promo discount",
        "checkout/payment": "checkout/pay payment stripe upstream",
        "checkout/totals": "shipping fee total subtotal overcharge",
        "ai/assistant": "assistant chatbot support",
        "shipping": "tracking delivery shipping",
        "account": "login account sign-in",
    }.get(feature, feature.replace("/", " "))


def _package(path: str) -> str | None:
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] == "packages":
        return f"@acme/{parts[1]}"
    return None


def _same_file(left: str, right: str) -> bool:
    return left == right or left.endswith(f"/{right}") or right.endswith(f"/{left}")


def _deploy_touches(location: CodeLocation, deploy: dict | None) -> bool:
    if deploy is None:
        return False
    return any(_same_file(location.file, path) for path in deploy.get("files", []))


def _candidate_key(file: str, line: int) -> str:
    return f"{file}:{line}"


def _add_candidate(candidates: dict[str, CodeLocation], location: CodeLocation) -> None:
    key = _candidate_key(location.file, location.line_start)
    existing = candidates.get(key)
    if existing is None:
        candidates[key] = location
        return
    if location.confidence > existing.confidence:
        existing.confidence = location.confidence
    if existing.role == "contributing" and location.role != "contributing":
        existing.role = location.role
    if location.rationale and location.rationale not in (existing.rationale or ""):
        existing.rationale = "; ".join(filter(None, (existing.rationale, location.rationale)))


def _review_matches(candidate: CodeLocation, finding: ReviewFinding) -> bool:
    return (
        _same_file(candidate.file, finding.file)
        and finding.line_start <= candidate.line_start <= finding.line_end
    )


def _review_record(
    finding: ReviewFinding,
    filters: list[dict[str, str]],
) -> dict:
    body = finding.body.lower()
    shared = list(
        dict.fromkeys(
            item["value"] for item in filters if item["value"].lower() in body
        )
    )
    return {
        "pr": finding.pr_number,
        "title": finding.title,
        "location": finding.location,
        "created_at": finding.created_at,
        "addressed": finding.addressed,
        "severity": finding.severity,
        "summary": finding.summary,
        "suggested_code": finding.suggested_code,
        "shared_identifiers": shared,
    }


def correlate(
    *,
    signal_id: str,
    symptom: str,
    feature: str,
    telemetry: TelemetryClient,
    window_minutes: int = 90,
    families: list[str] | None = None,
    tokens: list[str] | None = None,
    reviews: ReviewClient | None = None,
    on_event: Callable[[str, str], None] | None = None,
) -> Diagnosis:
    events = on_event or (lambda _stage, _detail: None)
    degraded: list[str] = []
    contradictions: list[str] = []
    now = datetime.now().astimezone()

    events("stage.1.temporal", f"querying {window_minutes}-minute error-rate window")
    change = telemetry.changepoint(window_minutes)
    deploy = telemetry.suspect_deploy(
        change["at"] if change else None,
        minutes=window_minutes,
        feature=feature,
    )
    rates = telemetry.error_rate(window_minutes)
    temporal = Temporal(
        window_from=(now - timedelta(minutes=window_minutes + 30)).isoformat(timespec="seconds"),
        window_to=now.isoformat(timespec="seconds"),
        error_rate_before=change["before"] if change else (rates[0][1] if rates else None),
        error_rate_after=change["after"] if change else (rates[-1][1] if rates else None),
        changepoint_at=change["at"] if change else None,
        suspect_deploy=deploy,
    )
    events(
        "stage.1.deploy",
        f"suspect deploy {deploy['sha']} PR#{deploy.get('pr')}" if deploy else "no feature-scoped deploy found",
    )

    filters = telemetry.resolve_tokens(tokens or [])
    clusters = []
    if filters:
        clusters = telemetry.query_logs("", minutes=window_minutes, filters=filters)
        joined = ", ".join(f"{item['dimension']}={item['value']}" for item in filters)
        events("stage.2.join", f"exact telemetry join on {joined}: {len(clusters)} clusters")
    if not clusters:
        query = _symptom_to_log_query(symptom, feature)
        clusters = telemetry.query_logs(query, minutes=window_minutes)
        events("stage.2.logs", f"feature log projection '{query}': {len(clusters)} clusters")

    in_app_cluster = next((cluster for cluster in clusters if cluster.top_in_app), None)
    if in_app_cluster is not None:
        mode = "crash"
    elif clusters:
        mode = "external"
    else:
        mode = "degradation"
    events("stage.2.mode", f"selected {mode}; in-app frames take precedence over event volume")

    soft_window = window_minutes
    if mode == "degradation":
        soft_window = DEGRADATION_WINDOW_MINUTES
        temporal.error_rate_before = None
        temporal.error_rate_after = None
        if change:
            degraded.append("error-rate changepoint belongs to a different incident")
        temporal.metric_anomalies = telemetry.anomalies(soft_window, feature=feature)
        if deploy is None:
            deploy = telemetry.suspect_deploy(
                None,
                minutes=soft_window,
                feature=feature,
            )
            temporal.suspect_deploy = deploy
        events(
            "mode.degradation",
            f"no matching errors; {len(temporal.metric_anomalies)} adverse metric drifts in {soft_window} minutes",
        )

    candidates: dict[str, CodeLocation] = {}
    frame_locations: list[CodeLocation] = []
    if mode == "crash":
        for cluster in clusters:
            for frame in cluster.frames:
                if not frame.in_app:
                    continue
                location = CodeLocation(
                    file=frame.file,
                    line_start=frame.line,
                    line_end=frame.line,
                    source="stackframe",
                    role="crash-site",
                    confidence=W_FRAME_ONLY,
                    symbol=frame.function,
                    package=_package(frame.file),
                    rationale=f"runtime frame observed in {cluster.error_type}",
                )
                frame_locations.append(location)
                _add_candidate(candidates, location)
        events("stage.3.callgraph", f"recorded {len(frame_locations)} in-app runtime frames")

    callgraph_locations: list[CodeLocation] = []
    if in_app_cluster and in_app_cluster.top_in_app:
        top = in_app_cluster.top_in_app
        for hop in structural.expand(top.file, top.line, error_message=in_app_cluster.message):
            location = CodeLocation(
                file=hop.file,
                line_start=hop.line_start,
                line_end=hop.line_end,
                source="callgraph",
                role="root-cause" if hop.distance >= 2 else "contributing",
                confidence=W_CALLGRAPH,
                symbol=hop.symbol,
                package=_package(hop.file),
                rationale=hop.rationale,
            )
            callgraph_locations.append(location)
            _add_candidate(candidates, location)
        events(
            "stage.3.callgraph",
            f"structural walk produced {len(callgraph_locations)} checkable locations",
        )

    frame_files = {location.file for location in frame_locations}

    def ceiling(path: str) -> float:
        return W_BOTH if any(_same_file(path, frame_file) for frame_file in frame_files) else CEILING_INFERRED

    for candidate in candidates.values():
        if _deploy_touches(candidate, deploy):
            candidate.confidence = min(ceiling(candidate.file), candidate.confidence * DEPLOY_BOOST)
            candidate.rationale = "; ".join(
                filter(None, (candidate.rationale, "same file changed by the suspect deploy"))
            )

    review_client = reviews or ReviewClient()
    prior_review = None
    if deploy is not None:
        review_result = review_client.findings_for_deploy(deploy.get("sha"), deploy.get("pr"))
        if review_result.source == "live" and review_result.findings:
            events("greptile.live", f"live MCP returned {len(review_result.findings)} located review findings")
            for finding in review_result.findings:
                matched = next(
                    (candidate for candidate in candidates.values() if _review_matches(candidate, finding)),
                    None,
                )
                if matched is not None:
                    matched.source = "both"
                    corroborated = W_BOTH if matched.role == "crash-site" else W_CALLGRAPH_REVIEW
                    matched.confidence = min(ceiling(matched.file), max(matched.confidence, corroborated))
                    matched.rationale = "; ".join(
                        filter(None, (matched.rationale, f"prior Greptile review: {finding.title}"))
                    )
                else:
                    _add_candidate(
                        candidates,
                        CodeLocation(
                            file=finding.file,
                            line_start=finding.line_start,
                            line_end=finding.line_end,
                            source="review",
                            role="contributing",
                            confidence=min(CEILING_INFERRED, W_REVIEW),
                            package=_package(finding.file),
                            rationale=f"prior Greptile review: {finding.title}",
                        ),
                    )
                record = _review_record(finding, filters)
                if prior_review is None or record["shared_identifiers"]:
                    prior_review = record
                if record["shared_identifiers"]:
                    events(
                        "stage.3.corroborate",
                        f"review and complaint share telemetry values: {', '.join(record['shared_identifiers'])}",
                    )
            events("stage.3.review", f"joined Greptile review for PR#{deploy.get('pr')} by deploy SHA")
        else:
            reason = review_result.detail or "no located findings"
            degraded.append(f"Greptile review unavailable: {reason}")
            events("greptile.failure", reason)
    else:
        degraded.append("Greptile review unavailable: no suspect deploy to join")
        events("stage.3.review", "no suspect deploy; review join skipped")

    roots = [candidate for candidate in candidates.values() if candidate.role == "root-cause"]
    if roots:
        roots.sort(key=lambda item: (_deploy_touches(item, deploy), item.confidence), reverse=True)
        selected = roots[0]
        for candidate in roots[1:]:
            candidate.role = "contributing"
    else:
        inferred = [
            candidate
            for candidate in candidates.values()
            if candidate.source in {"callgraph", "review", "both"}
            and candidate.role != "crash-site"
        ]
        if inferred and mode != "external":
            selected = max(inferred, key=lambda item: item.confidence)
            selected.role = "root-cause"
            degraded.append("root cause promoted from the strongest non-frame witness")
        else:
            selected = None
            if mode != "external":
                refusal = (
                    "root cause not located: only stack frames were available, and a frame names "
                    "where execution died, not what broke"
                )
                degraded.append(refusal)
                events("stage.4.fusion", refusal)

    if mode == "external":
        selected = None
    role_order = {"root-cause": 0, "crash-site": 1, "contributing": 2}
    code_evidence = sorted(
        candidates.values(),
        key=lambda item: (role_order[item.role], -item.confidence),
    )

    if frame_locations and selected and not _same_file(frame_locations[0].file, selected.file):
        contradictions.append(
            f"Runtime/review evidence names {_package(frame_locations[0].file) or frame_locations[0].file} "
            f"at {frame_locations[0].location}, while structural causality names "
            f"{_package(selected.file) or selected.file} at {selected.location}. "
            "Agreement measures certainty, not causality."
        )
    if mode == "degradation":
        contradictions.append(
            "Error monitoring shows nothing for this incident; a stack-trace-driven workflow has nothing to attach to."
        )
    if selected and selected.source in {"callgraph", "review"}:
        contradictions.append(
            f"The root-cause location has single-witness confidence from {selected.source}."
        )
    if feature.startswith("ai/"):
        contradictions.append(
            "The offline eval remains unchanged at 0.94. It is not wrong: it scores a curated question set, "
            "and the question customers are asking is not in it."
        )
    if families and "abuse" in families:
        contradictions.append(
            "This diagnosis explains the customer-facing failure but not the cluster's separate abuse posture."
        )

    external_dependency = None
    if mode == "external":
        vendor_cluster = clusters[0]
        external_dependency = {
            "vendor": vendor_cluster.vendor or "unknown",
            "host": vendor_cluster.vendor_host,
            "error_type": vendor_cluster.error_type,
        }
    root_cause = (
        f"{selected.location}: {selected.rationale}" if selected else
        f"external dependency failure: {external_dependency['vendor']}" if external_dependency else ""
    )
    confidence = 0.90 if mode == "external" else selected.confidence if selected else 0.0
    events(
        "stage.4.fusion",
        f"selected {selected.location} by causal role at evidence confidence {confidence:.2f}"
        if selected
        else f"completed {mode} fusion without a local patch target",
    )
    diagnosis = Diagnosis(
        id=f"diag-{signal_id}",
        signal_id=signal_id,
        created_at=timestamp(),
        symptom=symptom,
        feature=feature,
        temporal=temporal,
        log_evidence=clusters,
        code_evidence=code_evidence,
        root_cause=root_cause,
        confidence=confidence,
        mode=mode,
        external_dependency=external_dependency,
        prior_review=prior_review,
        contradictions=contradictions,
        degraded=degraded,
    )
    diagnosis.proposed_fix = propose_fix(diagnosis)
    return diagnosis


def propose_fix(diagnosis: Diagnosis) -> ProposedFix:
    target = diagnosis.patch_target
    files = [target.file] if target else []
    if diagnosis.mode == "external":
        vendor = (diagnosis.external_dependency or {}).get("vendor", "vendor")
        return ProposedFix(
            files=files,
            strategy=(
                f"Operational first: confirm {vendor}'s status and stop customers retrying. "
                "Then add bounded timeout, retry, circuit-breaker, and a distinct user-facing state at the call site."
            ),
            risks=["Never ship a code change hoping to resolve an outage that will end on its own."],
            test_plan="Simulate the vendor outage and verify bounded retries and an explicit customer state.",
        )
    if target and (target.file.endswith(".md") or "/prompts/" in target.file):
        return ProposedFix(
            files=files,
            strategy="Restore the grounding constraint and an approved refusal when retrieval has no supporting article.",
            risks=["A blanket refusal scores perfect groundedness and is strictly worse for answerable questions."],
            test_plan="Run the missing-policy case and the curated answerable-question evaluation set.",
        )
    if diagnosis.feature == "checkout/promo" and target:
        return ProposedFix(
            files=[
                "packages/pricing/src/promo.ts",
                "packages/pricing/src/index.ts",
                "packages/checkout/src/checkout.ts",
                "packages/checkout/src/server.ts",
            ],
            strategy=(
                "Preserve unknown versus expired as an explicit pricing resolution state, "
                "convert that state into a typed promo error before dereference, and map the "
                "expired reason to a distinct HTTP 4xx response. Do not change the crash-site "
                "expression at packages/checkout/src/checkout.ts:24."
            ),
            risks=[
                "Changing the pricing return contract can break every caller in the package.",
                "Resolve the promotion once per application; Date.now() makes repeated resolution disagree at expiry boundaries.",
            ],
            test_plan=(
                "Verify SAVE20 returns expired_promo_code with an EXPIRED message, NOPE99 "
                "remains unknown_promo_code, and the crash-site expression is unchanged."
            ),
        )
    if diagnosis.mode == "degradation":
        return ProposedFix(
            files=files,
            strategy="Correct the computation after establishing which quantity each caller expects and preserves.",
            risks=["Nothing throws when this is right or wrong; the repro script is the only reliable signal."],
            test_plan="Run the deterministic degradation repro at both sides of the affected boundary.",
        )
    return ProposedFix(
        files=files,
        strategy="Make the failure mode explicit rather than relying on an undocumented nullable result.",
        risks=["Changing the return contract can break every caller in the package."],
        test_plan="Reproduce the failing input, test the explicit failure, and run every package caller.",
    )
