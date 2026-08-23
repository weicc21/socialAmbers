# B3 — Telemetry client and dimension catalog

Create `socialClues/engine/telemetry.py`. Runs in parallel with B1 and B2;
write against B1's `Frame`/`LogCluster` and B2's fixture shape.

## What this class is

A **port**, not an OTel interface. Be explicit about that in the module
docstring, because the distinction is load-bearing:

> **OpenTelemetry standardises the write path only.** OTLP defines exactly one
> request type (`Export`). There is no query specification, no query language,
> no read API. OTTL/"TQL" in the collector is a *transform* DSL, not an
> analytical query over storage. Reads were deliberately left to the backend.

| method | standardised? |
|---|---|
| `query_logs` | ❌ vendor language — LogQL, SPL, KQL, Sentry, Datadog |
| `error_rate` | ❌ but PromQL is de-facto (Mimir/Thanos/Cortex/VictoriaMetrics) |
| `list_dimensions` / `dimension_values` | ❌ vendor API, universal concept |
| `list_deploys` | ❌ not telemetry — deploy markers, or the CD system |
| **attribute names** | ✅ **semantic conventions** |

The last row is what the artifact join depends on: it resolves *values against
names*, and the names are standardised. So the join survives a backend swap even
though every method must be rewritten.

## Constructor

`TelemetryClient(fixture: Path | None = None)` — loads the JSON once, sets
`self.source = "fixture-replay"`. Resolve `minutes_ago` offsets against
`datetime.now().astimezone()` at read time so the window always looks recent.

## Logs

```python
query_logs(query: str = "", minutes: int = 90,
           filters: list[dict[str, str]] | None = None) -> list[LogCluster]
```

Two mutually exclusive selection modes:

- **`filters` given** — exact dimension match, the join. A record matches when
  any `{dimension, value}` pair equals a top-level field or an `attributes` key,
  case-insensitively. **Union semantics, not intersection**: a complaint
  routinely names one identifier from the incident and one from somewhere else,
  and requiring all of them narrows to nothing.
- **no filters** — loose term match against `route`/`error_type`/`message`,
  terms OR'd, the fixture stand-in for LogQL.

Return `LogCluster` objects sorted by `count` descending.

## Dimension catalog — the artifact join

```python
list_dimensions() -> list[str]
dimension_values(name: str) -> list[str]
resolve_token(value: str) -> list[str]                       # dimension names
resolve_token_full(value: str) -> list[tuple[str, str]]      # (dimension, stored value)
resolve_tokens(tokens: list[str]) -> list[dict[str, str]]    # → filters
LOW_SELECTIVITY = {"level", "service.name"}
```

**The binding between "a word a user typed" and "a telemetry dimension" is
discovered, not declared.** A declared table would be keyed by artifact type,
and artifact types are unbounded — every new kind of identifier a customer
pastes needs another entry. Dimensions are the finite side: a schema enumerates
them. So the question inverts. Never *"what kind of thing is `SAVE20`?"* —
always *"which dimension contains the value `SAVE20`?"* That is an index lookup
every real backend exposes.

`list_dimensions` returns `route`, `error_type`, `level` plus every
`attributes` key present.

`resolve_token_full` must apply **English morphology, not domain vocabulary**:
try the raw lowercased form, then strip a trailing `s`/`es`/`ing`/`ed` when the
remainder is ≥2 chars. Users write "500s" and "TypeErrors".

**Return the stored value, not the token.** `resolve_token_full("500s")` must
yield `("http.response.status_code", "500")`. Emitting the raw token produces a
filter that resolves fine and then matches **zero rows** — a success
indistinguishable from "the artifact was not in the data". This is the single
easiest bug to introduce here.

`resolve_tokens` dedupes, skips `LOW_SELECTIVITY` dimensions, and emits
`{"dimension": ..., "value": <stored>}`.

`LOW_SELECTIVITY` is declared, keyed on the **finite** side, and must carry a
comment: production derives it from cardinality (`order.id` has millions of
distinct values, `level` has four), and **that threshold cannot be calibrated on
this fixture** — with four records `order.id` and `level` both have cardinality
1, so a tuned threshold would appear to work for the wrong reason.

## Metrics

```python
error_rate(minutes=90) -> list[tuple[str, float]]
changepoint(minutes=90) -> dict | None          # {at, before, after}
list_metrics() -> list[dict]
query_metric(name, minutes=720) -> list[tuple[str, float]]
metric_drift(name, minutes=720, min_change=0.15) -> dict | None
anomalies(minutes=720, feature: str | None = None) -> list[dict]
```

`changepoint` — first bucket at or above `3×` the trailing median. The cheapest
detector that works and is legible on a slide.

`metric_drift` — compare the mean of the first third of the window against the
last third. **A spike detector looks for a step; softness is a sustained shift.**
Return `{metric, unit, description, before, after, change_pct, onset_at,
direction, adverse}` where `adverse` combines the change sign with `direction`.
`onset_at` is the first point crossing the midpoint between the two baselines.

`anomalies` — adverse drifts only, worst first, **scoped by `feature`** against
each metric's `features[]` list. A metric with no `features` matches everything.

## Deploys

```python
list_deploys(minutes=120) -> list[dict]                       # newest first
suspect_deploy(changepoint_at, minutes=120, feature=None) -> dict | None
_feature_paths(feature) -> list[str]     # staticmethod
```

`_feature_paths` maps a surface head to package fragments:
`checkout` → `["packages/checkout", "packages/pricing"]`, `ai` →
`["packages/support"]`, `account` → `["packages/account"]`, `shipping` →
`["packages/checkout"]`. Unmapped → `[]`.

`suspect_deploy` returns the most recent deploy at or before the changepoint,
**scoped strictly** when `_feature_paths` returns anything: keep only deploys
whose `files[]` intersect those fragments, and return **`None`** if none
qualify. Attributing an unrelated deploy is worse than attributing none — it
drags that deploy's PR review findings into the wrong diagnosis. Unmapped
features fall back to the unscoped list.

Document that production reads a **deploy-marker stream** (Datadog `DD_VERSION`,
Grafana annotations, GitHub Deployments) where the SHA arrives tagged. File-path
intersection is a monorepo stand-in, not the real design.

## Also

`get_trace(trace_id)` returning the matching log record or `None`.

## Acceptance

```bash
./.venv/bin/python -c "
from engine.telemetry import TelemetryClient
t = TelemetryClient()
assert t.resolve_token('SAVE20') == ['promo.code']
assert t.resolve_token('500s')   == ['http.response.status_code']   # morphology
assert t.resolve_token('BROKEN') == []                             # self-validating
f = t.resolve_tokens(['500s','SAVE20','checkout'])
assert all(x['dimension'] != 'service.name' for x in f)            # selectivity
assert any(x['value'] == '500' for x in f)                         # stored value
assert len(t.query_logs('', minutes=600, filters=f)) < \
       len(t.query_logs('apply-promo promo checkout discount', minutes=600))
assert t.suspect_deploy(None, minutes=720, feature='ai/assistant')['files'][0].startswith('packages/support')
print('telemetry ok')"
```

The join must return strictly fewer clusters than the keyword query — it should
exclude the 214-count vendor outage, which is the noise mode detection exists to
fight.
