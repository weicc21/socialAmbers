# C2 — Greptile semantic client and question builders

Create `socialClues/engine/greptile.py`. Runs in parallel with C1, C3, C4.
Depends on B2's cached fixtures.

## Read this before writing code

**Greptile's natural-language query API is retired.** Verified against a live
key: `POST /v2/query`, `/v2/search` and `/v2/stream` all return `404` with body
`Cannot POST /v2/query` — byte-identical to an unrouted path, with a valid key,
an invalid key, and no credentials alike. `POST /v2/repositories` still returns
`200`, so the host and auth are fine; those specific routes have no handler.
Their MCP surface has no code-search tool either (`query_repository` and
`search_repository` return `-32601 Method not found`).

Do **not** call those retired routes in configured live mode and do not invent a
replacement semantic endpoint. Live Greptile evidence now comes from the MCP
code-review client in C3, joined to the suspect deploy. C2 retains the semantic
fixtures only for explicit offline operation, where they keep the full
correlation demo deterministic.

The UI must never label this capability simply `SEMANTIC`: that falsely implies
a live repository query. Emit it under `stage.3.semantic`, but render the
channel as **CODE INTEL** and include provenance in every detail:
`semantic/cache`, `semantic/review-mcp`, or `semantic/live` if a future adapter
actually provides cited repository search. Greptile review success remains a
separate **GREPTILE LIVE** witness.

## Constants

```python
CACHE = Path(__file__).parent / "fixtures" / "greptile_cached.json"
DEFAULT_TIMEOUT = 25.0
```

## Types

```python
@dataclass
class Source:
    filepath: str; line_start: int; line_end: int
    repository: str = ""; summary: str = ""
    @property
    def location(self) -> str

@dataclass
class QueryResult:
    answer: str
    sources: list[Source]
    source: str        # "review-mcp" | "cache"
    detail: str = ""   # why we degraded, when we did
```

## Client

```python
class GreptileClient:
    def __init__(self, api_key=None, github_token=None, repo=None,
                 branch="main", timeout=DEFAULT_TIMEOUT)
    @property
    def configured(self) -> bool          # api_key AND repo
    def query(self, question: str, cache_key: str = "") -> QueryResult
    def cached_result(self, detail: str, cache_key: str = "") -> QueryResult
```

Read `GREPTILE_API_KEY`, `GITHUB_TOKEN`, `TARGET_REPO` from the environment.
When key and repo are configured, `query()` returns no invented semantic
sources, `source="review-mcp"`, and a detail explaining that the live MCP review
stage owns Greptile evidence. Correlation must not mark that planned handoff as
degraded; it emits the handoff and then reports C3's live result.

`cached_result` is the explicit fallback seam used only after correlation has
observed a live MCP failure (or in offline mode). Its `detail` must preserve the
actual live failure so the terminal and `degraded[]` explain why cached evidence
was substituted.

**Parse `sources[]` defensively.** Accept `filepath` / `path` / `file` and
`linestart` / `lineStart` / `line_start`. Published docs are thin and shapes
drift; never assume one spelling.

### Never raise

Missing key or missing repo selects the offline cache with `source="cache"` and
a detail naming the missing configuration. No configured live execution should
touch the cache merely because the retired REST route is gone.

### Cache keying

`_cached(detail, cache_key)` loads `fixtures/greptile_cached{_<key>}.json`,
falling back to the base file when that variant is absent.

**The key must combine mode and feature.** Three separate incidents all resolve
to `degradation`, and keying on mode alone serves each of them the first one's
analysis. Callers pass `"hallucination"` for `ai/*` features and the mode
otherwise.

## Question builders

Three module-level functions returning the literal prompt text. **The wording is
load-bearing** — these are the only place the system talks to a model about
code, and a lazy question returns a confirmation of the crash site.

```python
def root_cause_question(symptom, error_type, crash_location) -> str
def degradation_question(symptom, feature, anomalies, deploy) -> str
def external_question(symptom, vendor, call_site) -> str
```

**`root_cause_question`** names the crash site, then **explicitly licenses a
different answer**:

> What is the ROOT CAUSE of this exception? Name the file and line where the fix
> belongs. The fix location may be in a different file or package from where the
> exception is thrown — if so, say which and explain the chain. Be specific about
> why the guarding code fails to prevent this.

Without that second clause the model confirms the location it was given,
producing a confident diagnosis that points at the symptom.

**`degradation_question`** must state **"there is no exception"** outright.
Otherwise the model hunts for a fault path and describes error handling, when
the code in question is returning 200 and computing the wrong number. Anchor it
on the metric drift and the suspect deploy.

**`external_question`** must **forbid looking for a local cause**. We already
know the vendor is failing. The useful answer is whether the call site has any
resilience — timeout, retry, circuit breaker, distinct user-facing state —
because that is the only part we can change.

## Optional probe

`python -m engine.greptile --probe` — call the supported live MCP review route
for PR #1 and print its parsed location, severity, and title. Exit non-zero
unless the result source is `live` and at least one finding is returned.

## Acceptance

```bash
./.venv/bin/python -c "
from engine.greptile import GreptileClient, root_cause_question
r = GreptileClient(api_key='', repo='').query('anything', cache_key='crash')
assert r.source == 'cache' and r.sources and r.answer
assert any(s.filepath.endswith('promo.ts') and s.line_start == 12 for s in r.sources)
q = root_cause_question('promo fails', 'TypeError', 'checkout.ts:24')
assert 'different file or package' in q
print('greptile ok — degraded cleanly:', r.detail)"
```

With a real key in `.env`, `query()` returns `source="review-mcp"`; then
`python -m engine.greptile --probe` must print a live P1 finding. This proves
live mode uses the supported contract instead of manufacturing success from a
known-retired route and cache.
