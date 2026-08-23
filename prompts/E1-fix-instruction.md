# E1 — Fix instruction renderer

Create `socialClues/engine/fix_prompt.py`. Runs in parallel with E2.

## What this is

**A real interface, not a formatting step.** The actor receiving it has no
access to the evidence chain, the telemetry, or the reasoning — it sees this
text and a filesystem. Everything it needs to do the job, and everything it must
avoid, has to be here.

The failure mode this guards against is specific and likely: handed only
*"fix packages/pricing/src/promo.ts:12"*, a competent agent opens the file, finds
nothing obviously wrong, looks at the stack trace, sees
`packages/checkout/src/checkout.ts:24`, and adds a null guard **there**. That
patch makes the symptom disappear, passes a naive test, and leaves the defect in
place for every other caller.

So the prompt states the patch target **and** names the crash site as a place
explicitly not to fix.

## API

```python
VERIFICATION: dict[str, dict[str, str]]
def fix_prompt(d: Diagnosis, fix: ProposedFix | None = None,
               repo_hint: str = "the acme-shop checkout") -> str
```

## `VERIFICATION` — hand-written per surface

Keys: `repro`, `before`, `after`, `regression`, `why_regression`.

These expectations are **domain knowledge, not derivable from telemetry** —
nothing in a metric says *"a $55 cart gets charged $4.95 it qualified out of."*
Treat the map like a runbook the owning team maintains.

### `checkout/promo`

- repro `npm run repro`
- before — throws `TypeError: Cannot read properties of null (reading 'discount')`, endpoint returns 500
- **after — an expired-but-known code is rejected with an error that says
  EXPIRED, distinguishable from `unknown_promo_code`, because SAVE20 is in the
  catalog and the customer is holding it. HTTP 4xx, no exception, and
  `unknown_promo_code` reserved for codes that do not exist.**
- regression `npm run repro:exploit && npm run typecheck`
- why — the same promo path is reachable by the stacking route; a guard in the
  wrong place changes one and silently alters the other. **Also confirm
  `resolvePromo` is not called twice around the guard** — it reads `Date.now()`,
  so two calls can disagree and any non-null assertion is then justified by
  coincidence, not construction.

**State the specific observable, never just its class.** An earlier version said
*"HTTP 400 unknown_promo_code"* and an actor delivered exactly that — reporting
an expired code as *unknown*, a user-facing regression the reproduction cannot
see. A step asserting only `4xx` cannot tell a correct 400 from a misleading one.

### `checkout/totals`

repro `npm run repro:soft`; before — a $55 cart with WELCOME10 is charged $4.95
it qualified out of, every request 200; after — the threshold is evaluated
against the pre-discount merchandise subtotal; regression `npm run repro && npm
run typecheck`, because the persisted-subtotal line is shared with the promo path.

### `ai/assistant`

repro `npm run repro:hallucination`; before — *"can I return a sale item?"*
answers *"30 days from delivery for a full refund"* with `grounded=false`;
after — the same question is declined with a human handoff;
**regression `npm run eval:all` — THE important one.** A prompt edit that refuses
everything scores a *perfect* groundedness and is strictly worse; the curated
golden set is the only thing that catches it. **19/19 must pass**, not just the
field-derived cases.

### Unmapped surfaces

There is **no honest generic recipe**. `"Expected now: the reported behaviour
reproduces"` is a placeholder wearing the costume of a verification step — it
invites an actor to declare success against a command that never demonstrated the
bug. When a feature is unmapped, say so in those words and instruct the actor to:
derive a reproduction and **run it before editing** (stopping if it cannot make
the bug happen), re-run after, run `npm run typecheck` **as a floor, stated as a
floor**, and report the reproduction it derived so the recipe map can grow.

## Sections, in order

1. `# Fix request — <feature>  (<id>)`
2. **What users are reporting** — the symptom
3. **What the machines saw** — for `degradation`, state plainly that nothing
   threw. **Filter log clusters to `top_in_app or (external and vendor)`** — a
   loose query pulls in whatever else was erroring, and listing a 214-count
   vendor outage invites the actor to investigate someone else's problem.
   Include metric anomalies and the suspect deploy.
4. **This was already flagged** — when `prior_review` exists: PR number,
   severity, location, `still unaddressed`, the quoted title and summary. Then:
   *treat that finding as corroboration, not as the specification — it describes
   the changed line; the patch target below may differ.*
5. **Where to fix it** — the target, its rationale, `source · confidence`. If
   absent: *"No patch target was located. Do not guess — report back rather than
   editing a file on suspicion."*
6. **`### Do NOT patch <crash site>`** — only when it differs from the target.
   State both confidence numbers, that the crash site scores *higher*, that
   agreement measures certainty not causality, and that a guard there fixes this
   call path and leaves every other caller exposed. Instruct: cite it in the PR
   description, do not change it.
7. **Strategy** and **Risks to respect** from `ProposedFix`
8. **Verify — required, in this order** — reproduce first (*"a fix for a bug you
   have not observed is unverifiable"*), apply, re-run, then the regression
   command with `This must pass. <why>`, then the test plan
9. **Report back** — the diff and where it landed, repro output before and
   after, the regression result, and *"anything you found that contradicts this
   diagnosis — that is a useful result, not a failure"*
10. **Known contradictions** and **Evidence gaps** — passed through, not hidden

## Acceptance

```bash
set -a; . .env; set +a; export ACME_SHOP_PATH=../acme-shop
./.venv/bin/python -c "
from engine.correlate import correlate, propose_fix
from engine.fix_prompt import fix_prompt, VERIFICATION
from engine.telemetry import TelemetryClient
from engine.greptile import GreptileClient
d = correlate(signal_id='s', symptom='promo fails', feature='checkout/promo',
              telemetry=TelemetryClient(), greptile=GreptileClient(),
              tokens=['SAVE20','500s'])
t = fix_prompt(d, propose_fix(d))
assert '### Do NOT patch packages/checkout/src/checkout.ts:24' in t
assert 'EXPIRED' in t and 'npm run' in t and 'must pass' in t
assert 'UpstreamError' not in t          # unrelated vendor incident filtered out
u = fix_prompt(correlate(signal_id='s', symptom='login broken', feature='account',
               telemetry=TelemetryClient(), greptile=GreptileClient()))
assert 'No verification recipe is mapped' in u
assert 'the reported behaviour reproduces' not in u
print('fix_prompt ok —', len(t.splitlines()), 'lines')"
```
