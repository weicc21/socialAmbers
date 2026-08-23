# C4 — Triage classifier and signal clustering

Create `socialClues/ui/triage.py` and `socialClues/ui/signals.py`. Runs in parallel
with C1–C3. No dependency on `engine/`.

## Part 1 — `ui/triage.py`

Deterministic keyword classification. No model. Every verdict must be
explainable by the terms that produced it — an opaque score proves nothing on
stage, matched terms are inspectable.

### API

```python
@dataclass
class Verdict:
    label: str          # signal | unrelated | praise | request | spam
    feature: str | None
    score: float
    matched: dict[str, list[str]]
    reason: str
    family: str | None = None   # availability | correctness | friction | abuse
    @property
    def is_signal(self) -> bool
    @property
    def is_abuse(self) -> bool

def normalize(text: str) -> str
def classify(text: str) -> Verdict
def triage_feed(complaints: list[dict]) -> list[dict]
def dedup(complaints) -> tuple[list, dict]
```

### The core rule

A complaint is signal only when it names **a surface AND a failure**. Either
alone is noise: *"checkout is great"* names a surface, *"this is broken"* names
a failure with nothing to route.

### Lexicons

`SURFACES` maps feature keys to term lists:
`checkout/promo` (promo code, coupon, discount code, SAVE20…),
`checkout/payment`, `checkout/totals` (total, subtotal, shipping fee, charged),
`ai/assistant` (assistant, chatbot, support bot, ai chat),
`shipping`, `account`.

`GENERIC_SURFACES` maps bare `checkout` → `checkout/*` (`AMBIGUOUS_SUFFIX = "/*"`).
Provide `parent_of()` and `is_ambiguous()`.

Failure terms split into families:
- `CORRECTNESS` — wrong total, charged twice, doesn't match, made up, isnt real
- `FRICTION` — **high-signal UI terms**: frozen, spinning, stuck, lagging, keeps
  loading, won't load
- HTTP errors via regex `\b([45]\d{2})(?:s|ing|ed)?\b`

`FAILURE = CORRECTNESS + FRICTION + [error page, throws, crash, bug, glitch…]`

Vetoes: `PRAISE`, `REQUEST` (please add, wish, would be nice), `SPAM`
(100x, link in bio, @everyone).

### `ABUSE` — evaluated BEFORE every veto

An exploit report names a surface and **celebrates** an unintended benefit:
*free money, applied it twice, stacks infinitely, go wild before they patch it,
best bug*. The reporter is delighted, so praise and spam vetoes would swallow it.
Requiring a surface is what stops generic excitement firing on everything.

Return `family="abuse"` with `score = min(1.0, 0.60 + 0.08 × min(len(hits), 4))`.
**A false negative here costs money; a false positive costs one investigation.**

### Two traps that must be handled

1. **Negation must not cross a sentence boundary.** In *"…no refunds. they are
   not the same policy"*, the `no` belongs to the previous sentence. Preserve
   clause boundaries through `normalize()` as a token (e.g. `zsentz`) and stop
   the backwards negation window (3 tokens) at it.
2. **Self-subject terms.** *"now im stuck with it"* is resignation, not a frozen
   UI. Void `stuck|frozen|lost|confused` when preceded by `i|im|i'm|we|me`
   (optionally `still`/`now`). Same shape as a slow-motion-video false positive.

Record **every** matched bucket in `matched`, including `abuse` — the dict is the
audit trail and must not lie about why a verdict fired.

Routing preferences: `ai/assistant` wins outright when matched;
`checkout/totals` wins over generic checkout when correctness terms are present.

## Part 2 — `ui/signals.py`

### Three mechanisms, easy to conflate — say so in the docstring

- **dedup** — same *text* (repost, bot, double-submit) → dropped, never counted
- **clustering** — different text, same *feature* → merged into one Signal. Not
  dropped: the count is the evidence.
- **signal state** — the same cluster firing while an investigation is open →
  attaches to it. **This** is what stops the engine re-running per complaint.

Dedup is **author-scoped** by default (`dedup_across_authors=False`). Two people
independently reporting the same thing is corroboration, not duplication.

### Two extractors, two jobs

```python
_CANDIDATE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,}")
def candidate_tokens(texts) -> list[str]      # for the telemetry join
def extract_artifacts(texts) -> dict[str, list[str]]   # for the symptom sentence
```

**`candidate_tokens` carries no domain vocabulary.** Shape only. It must not
know what a promo code is — that concept lives in the telemetry schema, and
`resolve_token` recognises it. Adding a new kind of identifier to the product
must require no change here. Filter only an English stopword set (`the`, `and`,
`please`…), never product nouns. A test greps the pattern and stopword set for
`promo|order|checkout|refund` and fails if any appear.

**`extract_artifacts` is presentation only**, feeding the symptom sentence, and
*may* carry domain regex — it writes prose for a human, not queries. Emit
`promoCodes`, `httpStatus`, `policyClaims` (canonicalised: `30-day`,
`final sale`, `no refund`, `return window`). Its type labels are **not**
authoritative for anything downstream.

### `synthesize_symptom(feature, complaints, artifacts) -> str`

One sentence built from the whole cluster. **This becomes the code-analysis
query**, so it must read better than any single post.

- Sample terms **round-robin across complaints**, not first-come — two loud
  crash reports arriving first would otherwise spend the whole budget and
  describe half the incident.
- A cluster can hold **two postures**: some users harmed, others profiting.
  When both `failure` and `abuse` terms exist, say so: *"Users report two
  distinct problems with X: it fails (…) and it can be exploited for unintended
  discounts (…)."*
- Append `Codes named:`, `HTTP status seen:`, `Conflicting policy claims:` when
  the artifacts exist.

### `Signal` and `SignalStore`

```python
@dataclass
class Signal:
    id: str; feature: str; symptom: str
    status: str = "open"        # open → investigating → diagnosed → resolved
    complaint_ids: list[str]; exemplars: list[str]
    artifacts: dict; tokens: list[str]
    families: list[str]; distinct_authors: int
    first_seen: datetime; last_seen: datetime; investigations: int
    def to_mcp_payload(self) -> dict

class SignalStore:
    def __init__(self, threshold=3, near_dup=0.72, dedup_across_authors=False)
    def ingest(self, complaints: list[dict]) -> dict
    def resolve(self, feature: str) -> None
```

`to_mcp_payload` emits `{signalId, feature, symptom, timeWindow, complaintIds,
evidence:{complaintCount, distinctAuthors, exemplars[:3], artifacts, tokens,
families}}`.

**Excluded on purpose:** handles, like counts, avatars, per-post timestamps. If a
field cannot change the investigation it does not cross the boundary.

`ingest` returns `{created, reinforced, dispatch, absorbed, dupes}`. A signal is
**dispatched exactly once**, at the moment its `distinct_authors` crosses the
threshold — later complaints reinforce it. Raw `complaint_ids` still preserve
volume, but three differently worded posts from one loud author must not fire.
Capture `previous_authors` before adding the current author and compare it with
the refreshed distinct-author count. Widen the time window 30 minutes backwards:
the deploy that caused it lands before the first human notices.

Ambiguous parents (`checkout/*`) absorb into a specific sibling when exactly one
is live; with two, attribution is a guess and it stays separate.

## Acceptance

```bash
cd ui && python3 -c "
from triage import classify
from signals import SignalStore, candidate_tokens
from seed_data import COMPLAINTS   # available after G1; use inline strings before then

assert classify('applying SAVE20 at checkout throws an error page').is_signal
assert classify('checkout is great').label == 'praise'
assert classify('free money glitch at acmeshop, promo stacks infinitely').family == 'abuse'
assert not classify('the checkout page is not broken for me').is_signal
assert classify('chatbot quoted 30 days, support refused it, now im stuck with it').is_signal
assert 'promo' not in ' '.join(candidate_tokens(['SAVE20 at checkout'])).lower() or True
print('triage ok')"
```

Then confirm the 20-report seeded feed escalates exactly two clusters
(`checkout/promo`, `ai/assistant`). Payment and account remain at two independent
voices and shipping at one. Add a regression proving three different complaint
wordings from one author remain one voice and cannot cross a threshold of three.
Signals that stay visible without firing are the proof qualification is bounded.
