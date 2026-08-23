# C3 — Greptile MCP review client, and the PRs it reads

Create `socialClues/engine/reviews.py` and open the three PRs it joins
against. Runs in parallel with C1, C2, C4. Requires wave A pushed to GitHub.

## Why review findings are unusually strong evidence

A review comment is recorded **before** the incident, by a process that never saw
the production symptom. It cannot have been derived from the complaints. So when
it lands on the same line the stack frames and the call-graph walk point at,
that is a third independent witness — not an echo.

## Part 1 — open the PRs

Greptile's bot reviews PRs automatically. Reviews need commits it can fetch, so
the branches must be **pushed**; a local-only branch fails with an opaque
`review failed unexpectedly`.

For each defect, construct a branch pair where the second introduces the bug on
top of the first:

```bash
cd acme-shop
# 1 — promo crash
git checkout -qB safe-base main
#   edit checkout.ts: add `if (promo === null) throw new PromoError(code);`
#   and drop the `!` from promo.discount
git commit -aqm "checkout: reject codes that resolve to null"
git checkout -qB bug-demo && git checkout main -- packages/checkout/src/checkout.ts
git commit -qm "checkout: simplify promo application"

# 2 — persist line   safe-persist → bug-persist   (remove / restore `cart.subtotal = subtotal`)
# 3 — prompt drift   safe-prompt  → bug-prompt    (fixed.md → the live prompt)

git push -u origin safe-base bug-demo safe-persist bug-persist safe-prompt bug-prompt
gh pr create --base safe-base    --head bug-demo    --title "checkout: simplify promo application"
gh pr create --base safe-persist --head bug-persist --title "checkout: persist discount so cart reflects what customer pays"
gh pr create --base safe-prompt  --head bug-prompt  --title "assistant: tighten tone, drop hedging language"
```

Titles must read as **plausible, innocuous changes**. That is the point: they
merged because nothing about them looked alarming.

Wait ~30s, then confirm the bot produced P1 findings on all three. Record each
PR's head SHA and number — **B2's `deploys[]` must carry these real values**, or
the SHA join resolves nothing.

## Part 2 — the client

Transport: `POST https://api.greptile.com/mcp`, JSON-RPC 2.0,
`method: "tools/call"`, `params: {name, arguments}`.
Headers: `Authorization: Bearer <GREPTILE_API_KEY>`, `Content-Type: application/json`.

**Two transport facts that will cost you an hour if undocumented — put them in
the module docstring:**

1. `tools/call` **validates** the API key; `tools/list` does **not** and returns
   `200` with a *truncated* tool list on a bad key. If discovery works and every
   call 401s, the key is wrong — most likely still carrying quotes from `.env`.
2. Tool results arrive as a JSON **string** inside `result.content[0].text`
   (MCP content blocks), not as a typed body. Parse twice.

### Types

```python
@dataclass
class ReviewFinding:
    file: str; line_start: int; line_end: int; body: str
    review_id: str = ""; commit_sha: str = ""; created_at: str = ""
    pr_number: int | None = None
    addressed: bool = False; suggested_code: str = ""
    @property
    def location(self) -> str
    @property
    def severity(self) -> str    # from an <img alt="P1"> badge, not a field
    @property
    def title(self) -> str       # first **bold** run, after the badge HTML
    @property
    def summary(self) -> str     # HTML, badge, title and ```suggestion stripped

@dataclass
class ReviewResult:
    findings: list[ReviewFinding] = field(default_factory=list)
    source: str = "live"          # "live" | "unavailable"
    detail: str = ""
```

Greptile encodes severity as an HTML badge and the headline as the first bold
run. Naive `body.splitlines()[0]` yields the `<a href…><img alt="P1"…>` markup —
parse, do not slice.

### Methods

```python
class ReviewClient:
    def __init__(self, api_key=None, repo=None, remote="github",
                 default_branch="main", timeout=25.0)
    @property
    def configured(self) -> bool
    def reviews_for_sha(self, sha, limit=30) -> tuple[list[dict], str]
    def comments(self, pr_number: int) -> tuple[list[ReviewFinding], str]
    def findings_for_deploy(self, sha, pr_number=None) -> ReviewResult
```

Every repository-scoped call sends the exact live identity fields:
`name=<owner/repo>`, `remote`, and `defaultBranch`. `list_code_reviews` also
sends `prNumber` when known plus `status="COMPLETED"`, `limit`, and `offset`.
`list_merge_request_comments` sends `prNumber` and
`greptileGenerated=true`. Do not use the obsolete/non-schema names
`repository` or `mergeRequestNumber`; the MCP server rejects them.

`reviews_for_sha` calls `list_code_reviews` and matches `commitSha` or
`metadata.headSha` by **prefix in either direction** — telemetry reports 7
characters, Greptile stores 40.

`comments` calls `list_merge_request_comments`. The comment fields are
**`filePath`, `lineStart`, `lineEnd`, `isGreptileComment`, `addressed`,
`suggestedCode`, `createdAt`** — not `path`/`line`. Keep only Greptile comments
that carry a `filePath`; summary-level comments have no location to join on.

`findings_for_deploy` is the entry point: filter reviews by `pr_number` when the
deploy record names one **and still verify the returned `commitSha` against the
suspect SHA**. Then fetch comments for the matched PR. A PR number narrows the
join; it does not replace the SHA join. Copy the matched review id, commit SHA,
and creation time onto every parsed finding. Return `ReviewResult` with
`source="unavailable"` and a reason whenever anything is missing — no key, no
SHA, no review, headless review with `mergeRequest: null`.

### Never raise

Any HTTP error, JSON-RPC `error`, or unreadable body returns
`(None, "<reason>")`. On `401`, append the hint `(key rejected — check for stray
quotes from .env)`.

## Acceptance

```bash
set -a; . .env; set +a
./.venv/bin/python -c "
from engine.reviews import ReviewClient
c = ReviewClient()
for pr in (1,2,3):
    r = c.findings_for_deploy(None, pr)
    assert r.source == 'live' and r.findings, (pr, r.detail)
    for f in r.findings:
        assert f.severity == 'P1' and f.file and f.line_start
        assert '<' not in f.title
        print(f'PR#{pr} [{f.severity}] {f.location} — {f.title}')"
```

Expect: PR#1 *Expired promos dereference null* at `checkout.ts:24`; PR#2 two
findings at `server.ts:27`; PR#3 *Grounding fallback is disabled* at
`support_agent.md:6`.

Those three findings, produced **cold with no production symptom**, are the
evidence for the project's central claim: review was right, it shipped anyway,
and nothing at review time said which correct warning mattered.
