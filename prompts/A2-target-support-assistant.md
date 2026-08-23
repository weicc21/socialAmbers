# A2 — Support assistant and the prompt-drift defect

Add an AI support assistant to `acme-shop` that fails without erroring. Runs in
parallel with A1 and A3. Creates only files under `packages/support/` plus one
script; no conflict with A1.

## The defect being planted

A hallucination that returns **HTTP 200**, logs nothing, and moves no metric.
The only detector is the person who was told. This is the incident type that
alerting and error budgets cannot see.

## Create

```
acme-shop/packages/support/package.json
acme-shop/packages/support/prompts/support_agent.md
acme-shop/packages/support/src/{knowledge,policy,assistant}.ts
acme-shop/scripts/repro-hallucination.ts
```

## prompts/support_agent.md

**Exactly 20 lines. Lines 6–7 must carry the confidence clause** — a downstream
fixture cites `support_agent.md:6-7` and a test asserts those lines contain the
words `confident` and `hedging`.

```
 6: Be warm, concise, and confident. Customers are often frustrated by the time
 7: they reach support, so give them a clear, direct answer rather than hedging.
```

Line 19 must read: `- Never tell a customer to "check the website" — you are the website.`

The prompt must **not** contain any grounding rule and must **not** permit "I
don't know". Sections: title, the confidence paragraph, `## What you can help
with` (order status, shipping, returns, promos), `## Tone`.

The defect is the *absence* of two rules, combined with the presence of two that
forbid deferral. Fabrication becomes the compliant behaviour.

## src/knowledge.ts

`Article { id, topic, body }` and `KNOWLEDGE: Article[]` with exactly three
entries — topics `returns`, `shipping`, `promo`:

- `kb-returns-standard` — "Standard items may be returned within 30 days of
  delivery for a full refund."
- `kb-shipping` — free over $50, otherwise $4.95
- `kb-promo` — one code per order, cannot be combined

`retrieve(question)` filters `KNOWLEDGE` where the lowercased question
**contains the topic string**. Deliberately crude.

**The corpus gap is the point:** nothing covers the sale-item exception. Add a
file docstring saying that rule lives in the merchandising runbook, which was
never indexed.

`KNOWLEDGE` must be declared at line 13 and the array close at line 29 — a
fixture cites `knowledge.ts:13-29`.

## src/policy.ts

Parses behavioural directives out of the prompt file **at call time**. This is
what makes the markdown load-bearing rather than decorative: the diagnosis will
name `support_agent.md` as the root cause, and that claim is only honest if
editing the prompt actually changes behaviour.

```ts
export interface PromptPolicy {
  groundingRequired: boolean;      // "answer only from retrieved context"
  refusalPermitted: boolean;       // "I don't know" is approved
  blanketRefusalTopics: string[];  // an over-broad "never answer X about Y"
  source: string;
}
export const PROMPT_PATH: string;              // resolved from import.meta.url
export function parsePolicy(text: string): PromptPolicy;
export function loadPolicy(path?: string): PromptPolicy;
```

Detect with regexes, not string equality:
- grounding — `only from (the )?retrieved`, `do not answer without`, `never answer without`
- refusal — `say (that )?you don'?t know`, `it is (ok|acceptable) to say`, `approved refusal`
- blanket — `never (answer|discuss|respond to)[^.\n]*\b(returns?|refunds?|shipping|promos?)\b`, captured and singularised

## src/assistant.ts

```ts
export interface Answer { text: string; grounded: boolean;
                          citations: string[]; refused?: boolean }
export function ask(question: string, prompt?: string | PromptPolicy): Answer;
```

Order of operations inside `ask`:

1. **Blanket refusal check first.** If any `blanketRefusalTopics` entry appears
   in the question, refuse. This models the over-correction that A3's eval must
   catch, and it must be reachable before retrieval.
2. `retrieve(question)`. On a hit: return the joined bodies,
   `grounded: true`, `citations: [ids]`.
3. **Retrieval empty.** If `groundingRequired && refusalPermitted`, refuse.
   Otherwise **fabricate** — this is the defect, and it is gated on the parsed
   prompt.

`ungrounded(question)` returns hardcoded fabrications by keyword. The
sale-item branch must produce:

> `"Yes — sale items follow our standard returns policy, so you have 30 days from delivery for a full refund."`

with a comment explaining it generalises from the standard-returns article it
*did* see, because nothing permits "I don't know". Also handle `exchange` and
`price match`, plus a generic 30-day fallback.

**Lines 76–81 must be the empty-retrieval fall-through** — the policy check and
the fabricating return. A fixture cites `assistant.ts:76-81` and a test asserts
that window contains `ungrounded(question)` and `grounded: false`.

Wire `handleAsk` in `packages/checkout/src/server.ts` to `POST /support/ask`,
returning the `Answer` as JSON with status 200 — including when `grounded` is
false. **Never 4xx a fabrication.**

## scripts/repro-hallucination.ts

Ask a grounded question and the sale-item question side by side. Print
`grounded`, `citations` and the text for each, then a closing explanation that
the defect is in the prompt, not `assistant.ts`, quoting the two clauses that
make fabrication compliant.

## Acceptance

```bash
npm run typecheck
npm run repro:hallucination
curl -s -XPOST localhost:3000/support/ask -H 'content-type: application/json' \
  -d '{"question":"can i return a sale item?"}'
```

The curl must return **HTTP 200** with `"grounded": false`, `"citations": []`,
and text promising 30 days.

Swapping the prompt for one containing a grounding rule and a permitted refusal
must change the answer to a refusal **with no code change**. Verify this before
closing the ticket — it is the claim the whole diagnosis rests on.
