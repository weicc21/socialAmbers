# A3 — Eval harness and storefront UI

Build the groundedness eval that **passes while the bug ships**, and a
single-page storefront that demonstrates all four defects. Runs in parallel with
A1 and A2. Depends on their *interfaces* only — write against the signatures in
those tickets and integrate at wave end.

## Part 1 — the eval harness

This is the project's sharpest artifact. It must reproduce two results exactly.

```
acme-shop/evals/run.ts
acme-shop/evals/derive.ts
acme-shop/evals/golden/support.golden.jsonl
acme-shop/evals/patches/support_agent.{baseline,fixed,overcorrected}.md
```

Add to `package.json`:

```json
"eval":              "npx tsx evals/run.ts --set=curated",
"eval:all":          "npx tsx evals/run.ts --set=all",
"eval:derive":       "npx tsx evals/derive.ts",
"eval:fixed":        "npx tsx evals/run.ts --set=all --prompt=evals/patches/support_agent.fixed.md",
"eval:overcorrected":"npx tsx evals/run.ts --set=all --prompt=evals/patches/support_agent.overcorrected.md"
```

### golden/support.golden.jsonl — exactly 16 cases

One JSON object per line: `{id, question, expect:{grounded?, refused?, contains?[], notContains?[]}, knownGap?, note?}`.

**15 must retrieve successfully** (grounded), **1 must not**. `retrieve()`
matches only if the question literally contains the topic word, so questions
must contain `returns`, `shipping`, or `promo` verbatim.

- `g-01`–`g-06` — returns questions, expect `grounded: true`, contains `30 days`
  / `full refund` / `Standard items`
- `g-07`–`g-11` — shipping questions, contains `$4.95` / `$50` / `flat`
- `g-12`–`g-15` — promo questions, contains `cannot be combined` / `One promo code` / `per order`
- `g-16` — *"do you price match a competitor?"*, `expect.grounded: false`,
  `knownGap: true`, note explaining the corpus has no price-match article

**No curated case may mention `sale`, `clearance`, or `final`.** The blindness
is deliberate and a downstream test asserts it: a curated case naming sale items
would disprove the premise.

15 grounded / 16 = **0.94**, which is the number on the slide.

### run.ts

```
npx tsx evals/run.ts [--prompt=<path>] [--set=curated|field|all]
                     [--threshold=0.90] [--json]
```

Two metrics, and the distinction is load-bearing:

- **groundedness** = `1 - fabricated/total`, where a case is *fabricated* only
  when `!grounded && !refused`. **A refusal is not a hallucination.** Scoring it
  as ungrounded penalises the fix and rewards confident invention.
- **correctness** = per-case assertions. A `knownGap` case never fails
  correctness but still drags groundedness down.

Print a per-case table (`✓` / `✗` / `◌` for a known gap), the two metrics, and
`✓ PASS` / `✗ FAIL`. Exit non-zero on any regression **or** groundedness below
threshold. Resolve `--prompt` against `process.cwd()` and pass it to
`loadPolicy`, so a patch file can be evaluated without editing the real prompt.

### derive.ts

Turns a triaged signal into golden cases — this is what makes the loop
self-healing rather than self-patching. Reads a signal payload (`--from=<path>`,
else a bundled demo signal), takes `evidence.artifacts.policyClaims`, and for
the claim `final sale` emits three probes:

- `can i return a sale item?`
- `are final sale items eligible for a refund?`
- `is a clearance jacket returnable?`

Each with `expect: {refused: true, grounded: false, notContains: ["30 day", "30 days", "full refund"]}`,
`origin: "field"`, and the complaint ids that produced it. Write to
`evals/golden/field-derived.jsonl`. **Do not commit that file** — the demo
generates it.

### patches/

- `baseline.md` — a copy of the live prompt
- `fixed.md` — adds a `## Grounding` section: answer only from retrieved
  articles; if nothing retrieved, say you don't know and offer a human handoff;
  never generalise from a general article to a specific case. Must **not** match
  the blanket-refusal regex.
- `overcorrected.md` — adds grounding **and** `- Never answer questions about
  returns or refunds — escalate to a human every time`. Must match the blanket
  regex so `blanketRefusalTopics` picks up `return`.

### Required results — verify all four

| command | groundedness | correctness | verdict |
|---|---|---|---|
| `npm run eval` | **0.94** | 16/16 | ✓ PASS |
| `npm run eval:all` (after derive) | 0.79 | 16/19 | ✗ FAIL |
| `npm run eval:fixed` | 1.00 | 19/19 | ✓ PASS |
| `npm run eval:overcorrected` | **1.00** | **13/19** | ✗ FAIL |

The last row is the point: the over-correction stops hallucinating by refusing
everything, scores a **perfect** groundedness, and is strictly worse. If it does
not reproduce, the harness is wrong — do not adjust the numbers to match.

### .github/workflows/support-eval.yml

Two steps: `eval:all --threshold=0.90`, then an **over-correction guard** that
runs the overcorrected prompt and **fails the build if it passes**.

## Part 2 — storefront UI

`acme-shop/packages/checkout/src/ui.ts` exporting `STOREFRONT_HTML: string` —
one self-contained page, inline CSS/JS, no external requests. Serve it from
`GET /` and `/index.html` in `server.ts`.

Four panels, each driving a real endpoint:

1. **Cart** — line items and subtotal
2. **Promo** — an input plus one-click `SAVE20` (500), `WELCOME10` (works),
   `NOPE99` (400). Render the raw JSON response and the HTTP status.
3. **Exploit** — an "apply again" button; show the total dropping per click.
4. **Support assistant** — a chat box posting to `/support/ask`, rendering the
   answer plus a `grounded` / `citations` badge.

Below the assistant, a `.truth` footnote — visually distinct, labelled
**GROUND TRUTH · NOT SHOWN TO CUSTOMERS**:

> Sale items are FINAL — not returnable. That rule lives in the merchandising
> runbook, which was never indexed into the assistant's corpus. Ask *"can I
> return a sale item?"* and the assistant will answer "you have 30 days from
> delivery for a full refund" — invented, not retrieved. It returns 200, logs
> nothing, and moves no metric. The nightly groundedness eval still reads 0.94.

## Acceptance

```bash
npm run typecheck
npm run eval && npm run eval:derive && npm run eval:all; echo "expect FAIL"
npm run eval:fixed && npm run eval:overcorrected; echo "expect FAIL"
PORT=3000 npm start &
curl -s -o /dev/null -w '%{http_code}\n' localhost:3000/     # 200
```

All four table rows must reproduce exactly. Document the eval flow in
`acme-shop/README.md`, including why the curated set reads 0.94 and why the
curated cases keep running after a fix.
