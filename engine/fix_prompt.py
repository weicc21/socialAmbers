"""Render the complete, evidence-bounded interface consumed by a fix actor."""

from __future__ import annotations

from engine.schema import Diagnosis, ProposedFix


VERIFICATION: dict[str, dict[str, str]] = {
    "checkout/promo": {
        "repro": "npm run repro",
        "before": (
            "Throws TypeError: Cannot read properties of null (reading 'discount'); "
            "the endpoint returns HTTP 500."
        ),
        "after": (
            "An expired-but-known code is rejected with an error that says EXPIRED, "
            "distinguishable from unknown_promo_code. SAVE20 is in the catalog and the "
            "customer is holding it. Return HTTP 4xx with no exception; reserve "
            "unknown_promo_code for codes that do not exist."
        ),
        "regression": "npm run repro:exploit && npm run typecheck",
        "why_regression": (
            "The stacking route shares this promo path. Confirm resolvePromo is not called "
            "twice around the guard: it reads Date.now(), so two calls can disagree and a "
            "non-null assertion would be justified by coincidence rather than construction."
        ),
    },
    "checkout/totals": {
        "repro": "npm run repro:soft",
        "before": (
            "A $55 cart with WELCOME10 is charged $4.95 it qualified out of, while every "
            "request returns HTTP 200."
        ),
        "after": "The free-shipping threshold is evaluated against the pre-discount merchandise subtotal.",
        "regression": "npm run repro && npm run typecheck",
        "why_regression": "The persisted-subtotal line is shared with the promo path.",
    },
    "ai/assistant": {
        "repro": "npm run repro:hallucination",
        "before": (
            "The question 'can I return a sale item?' answers '30 days from delivery for a "
            "full refund' with grounded=false."
        ),
        "after": "The same question is declined with a human handoff.",
        "regression": "npm run eval:all",
        "why_regression": (
            "19/19 must pass. A prompt that refuses everything scores perfect groundedness "
            "and is strictly worse; the curated golden set catches that regression."
        ),
    },
}


def _machine_evidence(diagnosis: Diagnosis) -> list[str]:
    lines = []
    if diagnosis.mode == "degradation":
        lines.append("Nothing threw: matching requests returned successfully and error monitoring is empty.")
    for cluster in diagnosis.log_evidence:
        if cluster.top_in_app or (diagnosis.mode == "external" and cluster.vendor):
            location = cluster.top_in_app.location if cluster.top_in_app else "vendor frames only"
            lines.append(
                f"- {cluster.error_type} × {cluster.count}: {cluster.message} "
                f"(trace {cluster.exemplar_trace_id}; {location})"
            )
    for anomaly in diagnosis.temporal.metric_anomalies:
        lines.append(
            f"- Metric {anomaly.get('metric')}: {anomaly.get('before')} → {anomaly.get('after')} "
            f"({anomaly.get('change_pct', 0):.1f}% change; onset {anomaly.get('onset_at')})"
        )
    deploy = diagnosis.temporal.suspect_deploy
    if deploy:
        lines.append(
            f"- Suspect deploy {deploy.get('sha')} · PR #{deploy.get('pr')} · "
            f"{deploy.get('message')} · files: {', '.join(deploy.get('files', []))}"
        )
    return lines or ["No matching machine evidence was available."]


def _verification_section(feature: str) -> list[str]:
    recipe = VERIFICATION.get(feature)
    if recipe is None:
        return [
            "No verification recipe is mapped for this surface.",
            "1. Derive a deterministic reproduction and run it before editing. A fix for a bug you have not observed is unverifiable.",
            "2. Stop and report back if the derived reproduction cannot make the bug happen.",
            "3. Apply the smallest evidence-consistent change, then re-run the derived reproduction.",
            "4. Run `npm run typecheck` as a floor, not as proof that behavior is correct.",
            "5. Report the reproduction you derived so the owning team's recipe map can grow.",
        ]
    return [
        f"1. Before editing, run `{recipe['repro']}`. A fix for a bug you have not observed is unverifiable.",
        f"   Expected before: {recipe['before']}",
        "2. Apply the strategy below only in the explicitly permitted changed files.",
        f"3. Re-run `{recipe['repro']}`.",
        f"   Expected after: {recipe['after']}",
        f"4. Run `{recipe['regression']}`. This must pass. {recipe['why_regression']}",
    ]


def fix_prompt(
    d: Diagnosis,
    fix: ProposedFix | None = None,
    repo_hint: str = "the acme-shop checkout",
) -> str:
    chosen = fix or d.proposed_fix
    if chosen is None:
        chosen = ProposedFix(files=[], strategy="No safe strategy was produced.")
    target = d.patch_target
    crash = d.crash_site
    lines = [
        f"# Fix request — {d.feature}  ({d.id})",
        "",
        f"Work in {repo_hint}.",
        "",
        "## What users are reporting",
        "",
        d.symptom,
        "",
        "## What the machines saw",
        "",
        *_machine_evidence(d),
    ]

    if d.prior_review:
        review = d.prior_review
        lines.extend(
            [
                "",
                "## This was already flagged",
                "",
                f"PR #{review.get('pr')} · [{review.get('severity')}] · {review.get('location')} · still unaddressed",
                f"“{review.get('title')}”",
                str(review.get("summary", "")),
                "Treat that finding as corroboration, not as the specification—it describes the changed line; the patch target below may differ.",
            ]
        )

    lines.extend(["", "## Where to fix it", ""])
    if target:
        lines.extend(
            [
                f"**Patch target:** `{target.location}`",
                f"{target.rationale or 'Selected by causal role.'}",
                f"{target.source} · evidence confidence {target.confidence:.2f}",
            ]
        )
        if chosen.files:
            lines.append(f"**Permitted changed files:** {', '.join(f'`{path}`' for path in chosen.files)}")
    else:
        lines.append("No patch target was located. Do not guess — report back rather than editing a file on suspicion.")

    if target and crash and crash.location != target.location:
        lines.extend(
            [
                "",
                f"### Do NOT patch {crash.location}",
                "",
                f"The crash site has evidence confidence {crash.confidence:.2f}, higher than the patch target's {target.confidence:.2f}.",
                "Agreement measures certainty, not causality. A guard at the crash site fixes this call path while leaving every other caller exposed.",
                "Cite the crash site in the PR description; do not change it.",
            ]
        )

    lines.extend(["", "## Strategy", "", chosen.strategy, "", "## Risks to respect", ""])
    if chosen.risks:
        lines.extend(f"- {risk}" for risk in chosen.risks)
    else:
        lines.append("- No additional risks were recorded; do not expand the patch beyond the evidence.")
    lines.extend(["", "## Verify — required, in this order", "", *_verification_section(d.feature)])
    if chosen.test_plan:
        lines.append(f"5. Additional test plan: {chosen.test_plan}")

    lines.extend(
        [
            "",
            "## Report back",
            "",
            "- The diff and the exact file and line where it landed.",
            "- Reproduction output before and after the change.",
            "- The required regression result.",
            "- Anything you found that contradicts this diagnosis — that is a useful result, not a failure.",
            "",
            "## Known contradictions",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in d.contradictions)
    if not d.contradictions:
        lines.append("- None recorded.")
    lines.extend(["", "## Evidence gaps", ""])
    lines.extend(f"- {item}" for item in d.degraded)
    if not d.degraded:
        lines.append("- None recorded.")
    return "\n".join(lines).rstrip() + "\n"
