# A1 — Target repo scaffold and the promo crash bug

Create the `acme-shop` repository and plant the first two defects. Runs in
parallel with A2 and A3.

## Create

```
acme-shop/
├── package.json
├── tsconfig.json
├── packages/pricing/package.json
├── packages/pricing/src/{index,types,catalog,promo}.ts
├── packages/checkout/package.json
├── packages/checkout/src/{index,checkout,server}.ts
└── scripts/{repro,repro-soft,repro-exploit}.ts
```

Root `package.json`: `"type": "module"`, workspaces `packages/*`, devDeps
`typescript@^5.7`, `tsx@^4.19`, `@types/node@^22`.

Scripts — **prefix every one with `npx`**. The documented flow never runs
`npm install`, so a bare `tsc` or `tsx` resolves only if globally present:

```json
"repro":         "npx tsx scripts/repro.ts",
"repro:soft":    "npx tsx scripts/repro-soft.ts",
"repro:exploit": "npx tsx scripts/repro-exploit.ts",
"start":         "npx tsx packages/checkout/src/index.ts",
"typecheck":     "npx --yes -p typescript@5 tsc --noEmit"
```

Pin `typescript@5` — TypeScript 6 removed `baseUrl` and the config below fails
on it.

Workspace deps use `"*"`, not `"workspace:*"` — npm rejects the pnpm protocol
outright and `npm install` fails before it starts.

`tsconfig.json`: `strict`, `noUncheckedIndexedAccess`, `module: NodeNext`,
`target: ES2022`, `baseUrl: "."`, `paths` mapping `@acme/pricing` →
`packages/pricing/src/index.ts` and `@acme/support` →
`packages/support/src/assistant.ts`. Include `packages/*/src/**/*.ts`,
`scripts/**/*.ts`, `evals/**/*.ts`.

## packages/pricing

`types.ts` — `Promo { code, discount, expiresAt, stackable }`,
`Cart { id, items, subtotal }`, `CartItem { sku, unitPrice, quantity }`.

`catalog.ts` — exports `CATALOG: Promo[]` with exactly three entries:

| code | discount | expiresAt | stackable |
|---|---|---|---|
| `WELCOME10` | 0.10 | far future | true |
| `SAVE20` | 0.20 | **in the past** | false |
| `FREESHIP` | 0.00 | far future | false |

Compute `expiresAt` from `Date.now()` offsets so the fixture never goes stale.

`promo.ts` — **`resolvePromo` must occupy lines 9–14 exactly.** Downstream
fixtures cite `promo.ts:12`, and a test asserts that line still contains the
expiry branch.

```ts
 9: export function resolvePromo(code: string): Promo | null {
10:   const promo = CATALOG.find((p) => p.code === code.trim().toUpperCase());
11:   if (!promo) return null;
12:   if (promo.expiresAt < Date.now()) return null;
13:   return promo;
14: }
```

**Defect 1 (root cause).** Line 12 collapses "unknown code" and "expired code"
into the same `null`, and the docstring documents only the first. Write that
docstring to say *"Returns `null` when the code is not recognised"* — the
omission is the bug.

Also export:
- `isKnownCode(code)` → `CATALOG.some(...)` — catalog membership, **ignores
  expiry**. This is the guard that fails.
- `canStack(promo)` → `promo.stackable`, with a comment noting **no caller
  checks it**. Defect 3 depends on this being dead code.
- `applyDiscount(cart, promo)` → rounded discounted subtotal.

`index.ts` re-exports `resolvePromo`, `isKnownCode`, `applyDiscount`.

## packages/checkout

`checkout.ts` — **`applyPromo` must occupy lines 17–25 exactly**, with the
dereference on line 24:

```ts
17: export function applyPromo(cart: Cart, code: string): number {
18:   if (!isKnownCode(code)) {
19:     throw new PromoError(code);
20:   }
21:
22:   const promo = resolvePromo(code);
23:
24:   return Math.round(cart.subtotal * (1 - promo!.discount) * 100) / 100;
25: }
```

**Defect 2 (crash site).** `isKnownCode` passes for `SAVE20`, `resolvePromo`
returns `null`, the non-null assertion dereferences it. The doc comment above
must claim *"`isKnownCode` rejects anything not in the catalog, so by the time
we get to the lookup the code is valid and `resolvePromo` always resolves"* —
a stated invariant that is false.

Also export `PromoError extends Error`, `recalculateSubtotal(cart)`, and
`finalTotal(subtotal)` which adds `$4.95` when `subtotal < 50`.

`server.ts` — a plain `node:http` server, no framework. Route handlers
`handleCreateCart`, `handleGetCart`, `handleApplyPromo`, `handleAsk`. Each
returns `{status, body}`; the listener serialises.

`handleApplyPromo` wraps `applyPromo` in try/catch: `PromoError` → 400
`unknown_promo_code`; anything else → 500 `internal_error`, logging the stack as
structured JSON so a stack frame is capturable.

**Defect 3+4 (one line, two symptoms).** Inside the `try`, immediately after
`applyPromo`, persist the discounted subtotal:

```ts
const subtotal = applyPromo(cart, body.code);
// Persist the discount so the cart reflects what the customer will pay.
cart.subtotal = subtotal;
```

That single write causes both:
- **compounding** — re-applying the same code discounts the already-discounted
  value, driving the total toward zero (`canStack` is never consulted)
- **silent overcharge** — a $55 cart becomes $49.50, so `finalTotal` evaluates
  the $50 free-shipping threshold against the *discounted* amount and adds $4.95

Both return HTTP 200. Neither logs an error. The comment must read as a
reasonable justification — it is what makes the line survive review.

Guard the URL parse against `noUncheckedIndexedAccess`:
`const url = (req.url ?? "").split("?")[0] ?? "";`

`index.ts` starts the server on `PORT ?? 3000`.

## scripts

Each prints a labelled, human-readable reproduction. No test framework.

- `repro.ts` — applies `WELCOME10` (succeeds), `NOPE99` (PromoError), `SAVE20`
  (**TypeError**). Prints `isKnownCode` and `resolvePromo` for each, and the
  real stack trace for the failure.
- `repro-soft.ts` — a $55 cart with `WELCOME10`; prints a before/after table
  showing the shipping fee appearing. Every response 200.
- `repro-exploit.ts` — applies the same code five times; prints the total
  falling each round.

## Acceptance

```bash
npm install                 # must succeed — proves no workspace: protocol
npm run typecheck           # zero errors
npm run repro               # prints TypeError with a frame at checkout.ts:24
npm run repro:soft          # shows a $4.95 fee on a qualifying cart
npm run repro:exploit       # shows the total decreasing five times
```

Verify by reading the files that `promo.ts:12` and `checkout.ts:24` hold the
lines specified above. Downstream fixtures cite them by number.

`git init`, commit, and push to a GitHub repo named `acme-shop`. Wave C3 needs
real PRs against a real remote.
