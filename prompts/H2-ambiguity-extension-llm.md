# H2 — Optional ambiguity resolver at the ingestion boundary

Run only after H1 passes. This is an optional extension, not a dependency of
the deterministic pipeline. Read `prompts/00-conventions.md` first.

The resolver operates at the input edge before `engine.pipeline.diagnose`. It
may translate ambiguous customer language into a bounded product-surface
hypothesis; deterministic correlation must still corroborate or reject that
hypothesis. Do not modify `engine/correlate.py`, feed model output into it, or
allow inference to contribute to `Diagnosis.confidence`.

This ticket and `H2-agent-fix-cta.md` both extend the post-H1 system. They are
compatible but must be applied sequentially because both update UI guards and
replay documentation.

## Files

Create `engine/ambiguity.py`. Modify only:

```text
ingest.py
ui/triage.py
ui/signals.py
ui/app.py
run.sh
test_pipeline.py
ui/test_triage.py
ui/test_signals.py
demo-samples.md
verify_samples.py
prompts/00-conventions.md
prompts/F3-ingestion-service.md
prompts/G1-streamlit-frontend.md
prompts/G2-process-manager.md
prompts/H1-test-suite.md
```

## Seeded incident

Add three adjacent complaints with unique authors and explicit `source` values
to `ui/seed_data.py::COMPLAINTS` after the 20 base reports:

```text
SAVE20 worked, but it somehow ate my free shipping.
My $55 cart qualified for free delivery until I applied SAVE20.
The discount applied, then checkout added $4.95 shipping to an order over $50.
```

The first sentence must appear verbatim and be included in `demo-samples.md`
with initial route `checkout/*`. This incident returns HTTP 200 and plausibly
belongs to `checkout/promo`, `checkout/totals`, or `shipping`. The expected
resolved surface is `checkout/totals`; the existing deterministic degradation
path must then locate the free-shipping defect in
`packages/checkout/src/server.ts`.

## Conservative deterministic detection

Extend `Verdict`:

```python
candidate_features: list[str] = field(default_factory=list)
resolution_required: bool = False
```

Do not invoke a model per complaint. `classify()` marks a complaint ambiguous
only when it has evidence for at least two compatible checkout surfaces,
contrast/change language such as `but`, `until`, `then`, or `after`, and no
explicit HTTP error, crash, timeout, or unavailable term. Return a signal with
`feature="checkout/*"`, sorted specific candidates, and
`resolution_required=True`. Do not exact-match the seeded sentences. Existing
unambiguous complaints retain their routes.

Extend `Signal` with sorted `candidate_features` and optional
`ambiguity_resolution`. Serialize them as `evidence.candidateFeatures` and
`evidence.ambiguityResolution`. Existing sibling absorption still wins: one
compatible concrete live sibling absorbs the ambiguous complaint without a
model. A standalone threshold cluster or a choice among multiple siblings
requires resolution.

## Typed resolver boundary

Implement in `engine/ambiguity.py`:

```python
@dataclass
class CandidateObservation:
    feature: str
    metric_anomalies: list[dict]
    suspect_deploy: dict | None

@dataclass
class AmbiguityRequest:
    signal_id: str
    summary: str
    exemplars: list[str]
    artifacts: dict[str, list[str]]
    candidate_features: list[str]
    observations: list[CandidateObservation]

@dataclass
class InvariantHypothesis:
    name: str
    feature: str
    inference_score: float

@dataclass
class AmbiguityResult:
    status: Literal["resolved", "unresolved", "failure"]
    selected_feature: str | None
    interpretation: str
    hypotheses: list[InvariantHypothesis]
    verification_checks: list[str]
    provider: str
    model: str | None
    detail: str

class AmbiguityResolver(Protocol):
    def resolve(self, request: AmbiguityRequest) -> AmbiguityResult: ...

def build_request(signal: Signal, telemetry: TelemetryClient) -> AmbiguityRequest: ...

class OpenAIAmbiguityResolver:
    def resolve(self, request: AmbiguityRequest) -> AmbiguityResult: ...
```

Never call `inference_score` confidence. `build_request()` performs read-only
preflight collection for each candidate using feature-scoped anomalies over
720 minutes and a suspect deployment anchored to the earliest anomaly. Send at
most three exemplars. Exclude handles, complaint IDs, raw logs, traces, source
code, credentials, and arbitrary environment data.

## OpenAI contract and safety

Configuration:

```text
AMBIGUITY_RESOLVER_ENABLED=0
OPENAI_AMBIGUITY_MODEL=<optional; falls back to OPENAI_MODEL>
OPENAI_API_KEY=<required only when enabled>
```

Use one OpenAI Responses API request with strict JSON Schema output. Complaint
text is untrusted quoted data. The model may interpret the relationship, rank
only supplied candidates, name candidate business invariants, and choose from:

```text
compare_metric_anomalies
inspect_deploy_diff
trace_value_flow
compare_affected_cohort
```

It may not generate query text, shell commands, code, patches, tool calls,
URLs, or new feature names. Validate that every feature was supplied, every
check is allowlisted, and every inference score is numeric in `[0, 1]`.
Resolution requires a top score of at least `0.65` and a margin of `0.15` over
the runner-up. Otherwise return unresolved without guessing.

Expected substance, not exact prose or score:

```json
{
  "selected_feature": "checkout/totals",
  "hypotheses": [{
    "name": "free_shipping_uses_pre_discount_subtotal",
    "feature": "checkout/totals",
    "inference_score": 0.74
  }],
  "verification_checks": ["compare_metric_anomalies", "trace_value_flow"]
}
```

The client never raises. Missing configuration, timeout, authentication,
malformed output, schema violations, out-of-set features, low score, and low
margin return typed failure or unresolved detail. There is no cached model
answer and no keyword fallback that silently chooses a surface.

## Ingestion lifecycle

Add optional resolver and telemetry dependencies to `Ingestor`; tests inject
fakes. Construct the OpenAI implementation only when enabled. Before dispatch:

1. emit `ambiguity.detected` with candidates;
2. when disabled, persist `needs-resolution`, emit `ambiguity.unresolved`, and
   do not diagnose;
3. build the bounded request and emit `ambiguity.request` with counts only;
4. call once;
5. on failure/unresolved, persist the result and stop without a fix;
6. on resolved, store metadata, change the signal feature, regenerate its
   symptom, emit `ambiguity.resolved`, and enter the existing deterministic
   diagnosis path;
7. retry only after a new explicit `--resolve-ambiguity` control request.

Add `./run.sh resolve-ambiguity`. The model may choose which deterministic
surface to test; it cannot add evidence, set causal role, select a patch target,
or affect evidence confidence.

Map `ambiguity.detected`, `.request`, `.resolved`, `.unresolved`, and `.failure`
to the literal `AMBIGUITY` terminal channel. The Diagnose card labels the
metadata **ambiguity inference**, not evidence confidence, and shows only
provider/model, selected feature, hypotheses, symbolic checks, and detail. Do
not expose prompts, hidden reasoning, API responses, handles, or raw metadata.

## Tests

All required tests inject fakes and never call the network.

Add eight pipeline tests covering bounded-data exclusion, candidate validation,
verification allowlisting, threshold/margin refusal, inert prompt injection,
confidence isolation, and deterministic resolution of the existing silent
defect after selection.

Add three triage tests: the seeded sentences initially route to `checkout/*`;
an explicit SAVE20 500 remains direct `checkout/promo`; unrelated multi-surface
prose without contrast does not invoke ambiguity.

Add four signal tests: independent complaints form one cluster; one live sibling
absorbs without a resolver; disabled/failure persists `needs-resolution` and
writes no fix; successful resolution dispatches exactly once and serializes no
handles.

With `H2-agent-fix-cta.md` already applied, expected totals are `✓ all 50`,
`✓ all 18`, `✓ all 28`.

## Acceptance

```bash
set -a; . .env; set +a
export ACME_SHOP_PATH=../acme-shop AMBIGUITY_RESOLVER_ENABLED=0
./run.sh test
./.venv/bin/python ingest.py --seed
./.venv/bin/python ingest.py --once
./.venv/bin/python -c "
import glob,json
s=json.load(open('runtime/state.json'))
w=[x for x in s['signals'] if x['status']=='needs-resolution']
assert len(w)==1 and w[0]['feature']=='checkout/*', w
assert len(glob.glob('runtime/fix-*.md'))==2
print('original two fixes preserved; one ambiguous cluster waiting')"
```

The in-process fake-resolver acceptance must print:

```text
ambiguous cluster resolved to checkout/totals
deterministic patch target packages/checkout/src/server.ts:24
model inference did not contribute to evidence confidence
```

Optional live smoke test:

```bash
export AMBIGUITY_RESOLVER_ENABLED=1
./run.sh restart
./run.sh run
./run.sh resolve-ambiguity
```

Success shows `ambiguity.resolved` with provider `openai`, followed by ordinary
deterministic stages. Failure shows `ambiguity.failure`, leaves
`needs-resolution`, and writes no third fix. Cached or fabricated success fails
this ticket.
