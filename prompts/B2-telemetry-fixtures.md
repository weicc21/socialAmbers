# B2 — Telemetry fixtures

Create `socialClues/engine/fixtures/telemetry.json`. Runs in parallel with B1
and B3. **Requires wave A complete** — every stack frame must name a `file:line`
that genuinely exists in `acme-shop`.

## Principle

The data is **replayed, not fabricated**. Capture it by running `acme-shop`'s
repro scripts and transcribing the real frames. A frame naming a line that does
not exist makes the whole demo a lie, and a test in H1 checks that the named
*function* still encloses the cited line.

Times are **relative** (`minutes_ago`), never absolute, so the demo always looks
recent.

## Top-level shape

```json
{ "_comment": "...", "service": "acme-shop",
  "deploys": [...], "error_rate": [...], "logs": [...], "metrics": {...} }
```

## logs — exactly four clusters

Each: `{minutes_ago, level, route, error_type, message, trace_id, count, frames[], attributes{}, vendor?, vendor_host?}`

| route | error_type | count | frames |
|---|---|---|---|
| `/checkout/apply-promo` | `TypeError` | 47 | `checkout.ts:24 applyPromo` (in_app), `server.ts:25 handleApplyPromo` (in_app), `node:internal/http:512 emit` (not in_app) |
| `/checkout/apply-promo` | `PromoError` | 3 | `checkout.ts:19 applyPromo` (in_app) |
| `/cart` | `TimeoutError` | 2 | `server.ts:117 handleGetCart` (in_app) |
| `/checkout/pay` | `UpstreamError` | 214 | **vendor frames only, all `in_app: false`** — set `vendor: "stripe"`, `vendor_host: "api.stripe.com"` |

The `TypeError` message must be exactly
`Cannot read properties of null (reading 'discount')` — the call-graph walk in
C1 parses the property name out of it.

**The UpstreamError cluster is deliberately the loudest.** It exists to prove
mode detection cannot rank by volume: a 214-count vendor outage must not
reclassify our own 47-count crash as someone else's problem.

### attributes — the join keys

Real spans carry the identifiers a user would paste. Without them the artifact
join has nothing to resolve against. Use OTel semantic-convention names where
one exists:

```json
"attributes": {
  "http.response.status_code": "500",
  "promo.code": "SAVE20",
  "order.id": "A1B2C3D4",
  "service.name": "checkout"
}
```

Per cluster: `TypeError` → status 500, `promo.code: SAVE20`, `order.id: A1B2C3D4`;
`PromoError` → status 400, `promo.code: NOPE99`; `TimeoutError` → 504;
`UpstreamError` → 502. All four carry `service.name: checkout`.

## deploys — four entries

`{sha, minutes_ago, author, message, files[], pr}`

| sha | min ago | pr | message | files |
|---|---|---|---|---|
| *(promo PR head)* | 46 | 1 | `checkout: simplify promo application` | `packages/checkout/src/checkout.ts` |
| *(prompt PR head)* | 300 | 3 | `support: tighten assistant tone, drop hedging language` | `packages/support/prompts/support_agent.md` |
| *(persist PR head)* | 372 | 2 | `checkout: apply free-shipping threshold to the payable amount` | `packages/checkout/src/server.ts`, `checkout.ts` |
| `0b7d441` | 380 | 809 | `checkout: add flat-rate shipping under $50` | `packages/checkout/src/checkout.ts` |

**Use the real short SHAs and PR numbers from C3's pushed branches.** The review
join matches on commit SHA; invented identifiers resolve to nothing. Set these
after C3 opens the PRs, and make the `message` match the actual PR title —
a message describing a change the commit did not make is a trap for anyone
reading the trace.

## error_rate

A per-bucket series. Flat around `0.003`, then a step to `~0.031` about 45
minutes ago — the changepoint detector looks for a bucket exceeding 3× the
trailing median, so the step must clear that.

## metrics — six series

`{unit, description, direction, features[], points[{minutes_ago, value}]}`

`direction` is `down_is_bad` or `up_is_suspicious`. **`features[]` scopes each
metric to a product surface** — without it an assistant incident cites
`promo_redemptions_per_order`, which makes a correct diagnosis look like it was
reached for the wrong reason.

| metric | features | direction | shape |
|---|---|---|---|
| `free_shipping_rate` | `checkout/totals` | `down_is_bad` | drops ~370 min ago |
| `shipping_fee_revenue` | `checkout/totals` | `up_is_suspicious` | rises at the same point |
| `promo_orders_with_shipping_fee` | `checkout/totals`, `checkout/promo` | `up_is_suspicious` | rises |
| `promo_redemptions_per_order` | `checkout/promo` | `up_is_suspicious` | rises ~46 min ago |
| `avg_discount_pct` | `checkout/promo` | `up_is_suspicious` | rises |
| `assistant_eval_groundedness` | `ai/assistant` | `down_is_bad` | **flat at 0.94 throughout** |

The last one is the argument, encoded as data: the eval never moves while the
assistant is confidently wrong. Give it at least eight points so the drift
detector has a window and still finds nothing.

Each series needs ≥6 points spanning 12 hours — the degradation window is 720
minutes and drift compares the first third against the last third.

## Cached semantic responses

Four files, same shape as a Greptile `/query` response:
`{answer: str, sources: [{filepath, linestart, lineend, summary}]}`

- `greptile_cached.json` — crash mode. Answer explains `resolvePromo` returns
  null for expired codes while `isKnownCode` reports them valid; checkout guards
  with the wrong predicate. Sources: `promo.ts:12` (root), `checkout.ts:24`
  (crash), `catalog.ts:13`.
- `greptile_cached_degradation.json` — the silent overcharge. Sources:
  `server.ts:24`, `checkout.ts:38`, `checkout.ts:24`.
- `greptile_cached_hallucination.json` — the prompt defect. Sources:
  `support_agent.md:6-7`, `knowledge.ts:13-29`, `assistant.ts:76-81`.
- `greptile_cached_external.json` — the vendor outage. Answer must state the
  fix is **not** in this repository and describe the call site's missing
  resilience. Source: `server.ts:36`.

Every `filepath`/`linestart` must be real. H1 asserts each cited window still
contains an expected token (`confident`, `KNOWLEDGE`, `ungrounded(question)`).

## Acceptance

```bash
./.venv/bin/python -c "
import json,pathlib
d=json.loads(pathlib.Path('engine/fixtures/telemetry.json').read_text())
assert len(d['logs'])==4 and len(d['deploys'])==4 and len(d['metrics'])==6
assert all('attributes' in r for r in d['logs'])
print('fixture shape ok')"
```

Then verify by hand that every `frames[].file` + `line` and every cached
`sources[].filepath` + `linestart` exists in `acme-shop` and names the code the
`summary` claims.
