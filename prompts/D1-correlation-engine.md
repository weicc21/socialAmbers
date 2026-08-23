# D1 — The correlation engine

Create `socialClues/engine/correlate.py`. **Runs alone.** Depends on every
wave-B and wave-C ticket. This is the file to get right; everything else is
plumbing.

## Signature

```python
def correlate(*, signal_id: str, symptom: str, feature: str,
              telemetry: TelemetryClient, greptile: GreptileClient,
              window_minutes: int = 90,
              families: list[str] | None = None,
              tokens: list[str] | None = None,
              reviews: ReviewClient | None = None,
              on_event: Callable[[str, str], None] | None = None) -> Diagnosis

def propose_fix(diagnosis: Diagnosis) -> ProposedFix
```

`on_event(stage, detail)` is the stage log — the engine narrating its own work,
which is more honest than a model narrating it afterwards. Emit at every stage.

## Constants

```python
W_BOTH           = 0.95   # structural + semantic agree
W_CALLGRAPH_BOTH = 0.88   # callgraph + semantic agree (inferred, so below W_BOTH)
W_GREPTILE_TOP   = 0.80   # semantic, ranked first
W_REVIEW         = 0.78   # a PR finding on the suspect deploy
W_CALLGRAPH      = 0.75   # reference resolution alone — provable, single-source
W_GREPTILE       = 0.60   # semantic, ranked lower
W_FRAME_ONLY     = 0.55   # a stack frame nobody corroborates
DEPLOY_BOOST     = 1.10
CEILING_INFERRED = 0.92
DEGRADATION_WINDOW_MINUTES = 720
```

`W_REVIEW` is high because the finding predates the incident and never saw the
symptom — genuinely independent. It stays under `CEILING_INFERRED` because it is
still a model's judgement, not an observation.

`DEGRADATION_WINDOW_MINUTES = 720` — metric drift is slow and a 90-minute window
misses the onset entirely. Widen before concluding "no signal".

## Stage 1 — temporal

`changepoint(window_minutes)`, then
`suspect_deploy(cp["at"], feature=feature)` — **pass the feature**. Build
`Temporal` with the window widened 30 minutes backwards.

## Stage 2 — log evidence, artifacts first

```python
filters = telemetry.resolve_tokens(tokens or [])
if filters:
    clusters = telemetry.query_logs("", minutes=window_minutes, filters=filters)
    emit("stage.2.join", "…")
if not clusters:
    clusters = telemetry.query_logs(_symptom_to_log_query(symptom, feature),
                                    minutes=window_minutes)
```

A token the user actually pasted resolves to a dimension by lookup, and an exact
join beats a keyword projection: the text query for `checkout/promo` also pulls
the 214-count vendor outage from the same window. Fall back to the taxonomy when
nothing resolves — plenty of complaints carry no identifier.

`_symptom_to_log_query(symptom, feature)` is a per-feature lookup table.
`checkout/promo` must **exclude the bare word "checkout"** (it matches
`/checkout/apply-promo` and drags an unrelated incident in), and
`checkout/totals` must be narrow enough **not** to match the promo `TypeError` —
that incident genuinely produced no errors.

## Mode detection

```python
in_app_cluster = next((c for c in clusters if c.top_in_app), None)
```

| mode | signature | root cause is | floor |
|---|---|---|---|
| `crash` | an in-app frame exists | our code | from fusion |
| `external` | error clusters, **no** in-app frames | a vendor | `0.90` |
| `degradation` | no errors at all; metric drift only | our code, silently | from fusion |

**In-app frames take precedence over volume.** Selecting the mode from the
highest-count cluster misclassifies our own crash as external whenever a vendor
outage is noisier — which is exactly when it matters.

In `degradation`: null out the error-rate fields, and if a changepoint exists,
record in `degraded[]` that it belongs to a different incident. Query
`anomalies(feature=feature)` over `soft_window`. **If no deploy was found, retry
`suspect_deploy` over the 720-minute window** — a prompt change that started
drifting hours ago falls outside the default lookback, and without it the
incident has no deploy to join review findings against.

## Stage 3 — four paths into a candidate map

**Key candidates on `file:line`, never `file`.** One file is routinely
implicated at two lines and keying on the path silently drops the first.

**A · structural.** In-app frames. In `external` mode, scope frames to the
vendor cluster (which by definition has none of ours).

**B · callgraph.** From the top in-app frame, `structural.expand(...,
error_message=top.message)`. Distance-1 hops are `contributing` (still inside
the crashing function); only the resolved definition at distance ≥2 is a
`root-cause` claim.

**C · semantic.** `greptile.query(question, cache_key=...)` where
`cache_key = "hallucination" if feature.startswith("ai/") else mode`. Role:
`crash-site` when the frames also name it, else `root-cause`. In `external`
mode nothing is a root cause — the defect is in someone else's system, and what
our code contributes is missing resilience, which is `contributing`.

Every `stage.3.semantic` event states the provider source and cited-location
count. Configured Greptile currently returns a `review-mcp` handoff with zero
semantic sources because repository-wide query is retired; emit plainly that
semantic query is unavailable and the MCP review is a separate witness. Cache
sources are labelled `semantic/cache` on both the summary and every cited
location. Never describe a cached fixture or review response as live semantic
analysis.

**D · review.** `reviews.findings_for_deploy(deploy["sha"], deploy["pr"])`.
New locations enter as `contributing` with `W_REVIEW`. On a `file:line` match
with an existing candidate: set `source="both"`, raise confidence, and append the
finding to the rationale.

Emit `prior_review` = `{pr, title, location, created_at, addressed, severity,
summary, suggested_code, shared_identifiers}`.

`shared_identifiers` = resolved **filter values** appearing in the review body —
**not raw tokens**. The review and the complaint both containing the word
"checkout" is coincidence; both containing `SAVE20`, which telemetry confirmed
is a real `promo.code`, is evidence. Emit `stage.3.corroborate` when non-empty.

## Stage 4 — fusion

```python
frame_files = {f.file for f in frame_locations}
def _ceiling(path): return W_BOTH if any(_same_file(path, f) for f in frame_files) \
                    else CEILING_INFERRED
```

Apply `_ceiling` to **both** boosts — deploy recency and review corroboration.
Without it, review corroboration pushes the crash site to 1.00 and inverts the
central invariant.

**Root-cause selection, in order:**

1. Collect `role == "root-cause"`; prefer deploy-touched, then confidence;
   demote the rest to `contributing`. **Exactly one survives.**
2. If none exist but a `greptile`/`callgraph`/`review`/`both` candidate does,
   promote the highest and note it in `degraded[]`.
3. **If only stack frames are available, refuse.** Emit *"root cause not
   located: only stack frames were available, and a frame names where execution
   died, not what broke"* and leave everything as `crash-site`. Promoting here
   is the exact conflation the design forbids.

Order `code_evidence` by role (`root-cause`, `crash-site`, `contributing`), then
confidence descending. **Presentational only** — `patch_target` reads the role.

## `contradictions[]` — mandatory

Report disagreement rather than smoothing it into false confidence:

- structural vs semantic naming different files, **including package names**,
  closing with *"Agreement measures certainty, not causality."*
- `degradation`: error monitoring shows nothing, so a stack-trace-driven workflow
  has nothing to attach to
- single-witness confidence, stated as such
- `ai/assistant`: the offline eval is unchanged at 0.94 — **it is not wrong**, it
  scores a curated question set and the question customers are asking is not in it
- `source != "live"` — analysis served from cache
- mixed-posture clusters: when `families` contains `abuse` and the mode is not
  abuse-specific, name the half this diagnosis did **not** explain

## `propose_fix` — dispatch on what is being patched

One template for every incident is wrong in a way that reads as plausible.
Three branches:

| target | strategy | primary risk to state |
|---|---|---|
| `.md` / `/prompts/` | restore the grounding constraint and an approved refusal | a blanket refusal scores a **perfect** groundedness and is strictly worse |
| `mode == "degradation"` | correct the computation; establish which quantity each caller expects | nothing throws when this is right or wrong — the repro script is the only signal |
| `crash` | make the failure mode explicit rather than an undocumented null | changing the return contract breaks every caller in the package |
| `mode == "external"` | **operational first**, code second — confirm the vendor's status, stop customers retrying | never ship a code change hoping to resolve an outage that will end on its own |

Applying crash-shaped language to a markdown prompt tells the actor to re-check
"every caller of the symbol" in a file that has no callers.

## Acceptance

```bash
set -a; . .env; set +a; export ACME_SHOP_PATH=../acme-shop
./.venv/bin/python -c "
from engine.correlate import correlate, propose_fix
from engine.telemetry import TelemetryClient
from engine.greptile import GreptileClient
d = correlate(signal_id='s', symptom='promo code fails at checkout',
              feature='checkout/promo', telemetry=TelemetryClient(),
              greptile=GreptileClient(), tokens=['SAVE20','500s'])
assert d.mode == 'crash'
assert d.patch_target.location == 'packages/pricing/src/promo.ts:12'
assert d.crash_site.location  == 'packages/checkout/src/checkout.ts:24'
assert d.crash_site.confidence > d.patch_target.confidence   # THE invariant
assert propose_fix(d).files == ['packages/pricing/src/promo.ts']
assert any('certainty, not causality' in c for c in d.contradictions)
print('crash ok')"
```

Also verify `ai/assistant` → `degradation`, root cause
`packages/support/prompts/support_agent.md:6`, and that its `propose_fix`
strategy contains **neither** `dereference` nor `null`.

The crash site scoring **higher** than the root cause while the root cause is
what gets patched is not a bug to fix. It is the result.
