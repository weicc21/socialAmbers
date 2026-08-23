# B1 — Diagnosis schema and validator

Create `socialClues/engine/schema.py` and `socialClues/engine/__init__.py`
(empty). Runs in parallel with B2 and B3. Every later ticket builds against
this file — write it first and do not change it afterwards without updating
`contract.md`.

## Type aliases

```python
Source = Literal["stackframe", "greptile", "callgraph", "review", "both"]
Role   = Literal["crash-site", "root-cause", "contributing"]
SCHEMA_VERSION = "1.0"
```

Document each `Source` value in a comment above the alias:

- `stackframe` — the frame the runtime recorded. Observed.
- `callgraph` — reached by resolving references out of the crash frame.
  Checkable: every hop names a definition you can open. The only source that
  routinely crosses a package boundary without a model.
- `greptile` — semantic code analysis. Crosses boundaries, cannot be checked.
- `review` — a PR review comment on the suspect deploy. Unusually strong: it was
  recorded **before** the incident by a process that never saw the symptom, so
  it cannot have been derived from the complaints.
- `both` — two of the above agree on the same `file:line`.

## Dataclasses

```python
@dataclass
class Frame:
    file: str; line: int; function: str; in_app: bool = True
    @property
    def location(self) -> str          # "file:line"

@dataclass
class LogCluster:
    error_type: str; message: str; count: int
    exemplar_trace_id: str
    frames: list[Frame] = field(default_factory=list)
    vendor: str | None = None
    vendor_host: str | None = None
    @property
    def top_in_app(self) -> Frame | None   # first frame with in_app=True

@dataclass
class CodeLocation:
    file: str; line_start: int; line_end: int
    source: Source; role: Role; confidence: float
    symbol: str | None = None
    package: str | None = None
    rationale: str | None = None
    @property
    def location(self) -> str

@dataclass
class Temporal:
    window_from: str; window_to: str
    error_rate_before: float | None = None
    error_rate_after: float | None = None
    changepoint_at: str | None = None
    suspect_deploy: dict | None = None
    metric_anomalies: list[dict] = field(default_factory=list)

@dataclass
class ProposedFix:
    files: list[str]; strategy: str
    risks: list[str] = field(default_factory=list)
    test_plan: str | None = None
    patch: str | None = None

@dataclass
class Diagnosis:
    id: str; signal_id: str; created_at: str
    symptom: str; feature: str
    temporal: Temporal
    log_evidence: list[LogCluster]
    code_evidence: list[CodeLocation]
    root_cause: str
    confidence: float
    mode: str = "crash"
    external_dependency: dict | None = None
    prior_review: dict | None = None
    contradictions: list[str] = field(default_factory=list)
    proposed_fix: ProposedFix | None = None
    schema_version: str = SCHEMA_VERSION
    degraded: list[str] = field(default_factory=list)
```

`ProposedFix.files` is **a list**. Current callers populate one entry; the plural
is deliberate and multi-target support depends on it.

## The two-axis docstring

`CodeLocation` carries the design's core claim. Its docstring must state that
`source` and `role` are independent axes — `source` answers *who found it*
(certainty), `role` answers *what it is causally* (where the fix goes) — and
that collapsing them is the mistake the whole design exists to avoid, because
the location with highest agreement is usually the crash site.

## Convenience properties on Diagnosis

```python
@property
def patch_target(self) -> CodeLocation | None:
    return next((c for c in self.code_evidence if c.role == "root-cause"), None)

@property
def crash_site(self) -> CodeLocation | None:
    return next((c for c in self.code_evidence if c.role == "crash-site"), None)
```

**`patch_target` selects on the role field.** Not `max(..., key=confidence)`,
not `code_evidence[0]`. Ordering of `code_evidence` is presentational.

`to_dict()` → `asdict(self)`.

## `validate(d: dict) -> list[str]`

Cheap structural validation returning a list of problems; empty means valid.
Never raises, never mutates.

Check: required top-level keys present; each `code_evidence` entry has
`file`/`line_start`/`line_end`; `role` in the Role set; `source` in the Source
set; `confidence` numeric in `[0, 1]`.

**Relax for `mode == "external"`.** An external outage legitimately has nothing
in our code to patch, so an empty `code_evidence` and an absent root cause are
valid there and only there. Forcing a root cause would fabricate one.

## `timestamp() -> str`

`datetime.now().astimezone().isoformat(timespec="seconds")`.

## Acceptance

```bash
./.venv/bin/python -c "
from engine.schema import Diagnosis, CodeLocation, validate
print(validate({}))                      # non-empty list, no exception
"
./.venv/bin/python -m pyflakes engine/schema.py    # silent
```

Construct a `Diagnosis` with two `CodeLocation`s — a `crash-site` at confidence
`0.95` and a `root-cause` at `0.92` — and assert `patch_target` returns the
root cause despite its lower confidence. That single assertion is the schema's
reason to exist.
