# Build tickets — SocialClues

Reconstruct SocialClues from zero. Tickets are numbered by wave; **every ticket
in a wave is independent and may run in parallel.** A wave starts only after the
previous wave's tickets have all passed their acceptance checks.

Read [`00-conventions.md`](00-conventions.md) before executing any ticket. It
defines constraints every ticket inherits and does not repeat.
[`codex.md`](codex.md) has the prompt template and invocation for driving these
with Codex CLI.

## Waves

| wave | tickets | parallel | produces |
|---|---|---|---|
| **A** | A1, A2, A3 | 3-way | `acme-shop` target repo — the system under test |
| **B** | B1, B2, B3 | 3-way | `Diagnosis` schema, telemetry fixtures, telemetry client |
| **C** | C1, C2, C3, C4 | 4-way | four evidence sources + triage/clustering |
| **D** | D1 | — | the correlation engine (depends on all of B and C) |
| **E** | E1, E2 | 2-way | fix instruction renderer, engine entrypoint |
| **F** | F1, F2, F3 | 3-way | MCP server, actor, ingestion service |
| **G** | G1, G2 | 2-way | Streamlit frontend, process manager |
| **H** | H1, then optional H2 extensions | — | full suite; fix CTA and bounded ambiguity resolver |
| **I** | I1, I2 | sequential | customer-owned outcome flywheel; captured agent-fix replay fixtures |

```
A ──► B ──► C ──► D ──► E ──► F ──► G ──► H ──► I
```

## Ticket index

**Wave A — target repository** (separate git repo, cloned beside this one)
- [`A1-target-scaffold-and-promo-bug.md`](A1-target-scaffold-and-promo-bug.md)
- [`A2-target-support-assistant.md`](A2-target-support-assistant.md)
- [`A3-target-evals-and-storefront.md`](A3-target-evals-and-storefront.md)

**Wave B — contracts and telemetry**
- [`B1-diagnosis-schema.md`](B1-diagnosis-schema.md)
- [`B2-telemetry-fixtures.md`](B2-telemetry-fixtures.md)
- [`B3-telemetry-client.md`](B3-telemetry-client.md)

**Wave C — evidence sources and triage**
- [`C1-structural-callgraph.md`](C1-structural-callgraph.md)
- [`C2-greptile-semantic-client.md`](C2-greptile-semantic-client.md)
- [`C3-greptile-review-client.md`](C3-greptile-review-client.md)
- [`C4-triage-and-signals.md`](C4-triage-and-signals.md)

**Wave D — fusion**
- [`D1-correlation-engine.md`](D1-correlation-engine.md)

**Wave E — output**
- [`E1-fix-instruction.md`](E1-fix-instruction.md)
- [`E2-engine-entrypoint.md`](E2-engine-entrypoint.md)

**Wave F — services**
- [`F1-mcp-server.md`](F1-mcp-server.md)
- [`F2-actor.md`](F2-actor.md)
- [`F3-ingestion-service.md`](F3-ingestion-service.md)

**Wave G — surface**
- [`G1-streamlit-frontend.md`](G1-streamlit-frontend.md)
- [`G2-process-manager.md`](G2-process-manager.md)

**Wave H — verification and optional extension**
- [`H1-test-suite.md`](H1-test-suite.md)
- [`H2-agent-fix-cta.md`](H2-agent-fix-cta.md) — optional, connects a live
  diagnosis to the existing actor and streams its real execution
- [`H2-ambiguity-extension-llm.md`](H2-ambiguity-extension-llm.md) — optional,
  run only after H1 passes; preserves deterministic correlation

**Wave I — operational learning and deterministic replay**
- [`I1-customer-owned-learning-flywheel.md`](I1-customer-owned-learning-flywheel.md)
- [`I2-agent-fix-fixture-replay.md`](I2-agent-fix-fixture-replay.md) — run after
  I1; captures a live verified Codex diff once and replays it without another model call

## What the finished system does

A cross-channel customer-evidence feed is normalized, triaged, and clustered.
When a cluster crosses an independent-author threshold, a **deterministic
correlation engine** fuses four independent
evidence sources into a schema-validated `Diagnosis` plus a self-contained fix
instruction. A replaceable actor executes that instruction against the target
repo and verifies it. The verified outcome becomes customer-owned evaluation,
retrieval, ranking, or post-training data. No model sits inside correlation,
and SocialClues does not own the customer's trainer.

The finished UI preserves that chain of evidence rather than presenting a
detached technical answer: the Diagnose view streams the engine's real emitted
events at a judging-friendly three-lines-per-second pace, then places the
consolidated social complaint language directly above the machine-evidence
drill-down. Its Signal Feed visibly distinguishes two gates: customer
corroboration qualifies an investigation; operational evidence justifies a fix.
Only the two base incidents pass both, while three emerging clusters remain
visible without generating unsupported remediation.

The single most important behaviour, asserted by tests in H1: the **crash site
scores higher confidence than the root cause and is the wrong file**. The patch
target is selected by causal `role`, never by `confidence`.

## Driving this with Codex CLI

One agent per ticket, fresh context each time; tickets within a wave run in
parallel. The prompt template, the invocation, and the four places to stop and
verify are in [`codex.md`](codex.md).

**Do not start a wave until every ticket in the previous one has printed a
passing acceptance block** — the acceptance output is the gate, not the agent's
own summary.

### Wave gates

| after | gate |
|---|---|
| A | `cd acme-shop && npm run repro` throws at `checkout.ts:24`; `npm run eval:all` prints 19/19 |
| B | `TelemetryClient().resolve_token("SAVE20")` returns `promo.code` |
| C | all four evidence clients return results or degrade with a stated reason — none raise |
| D | `crash_site.confidence > patch_target.confidence` and the patch target is `promo.ts:12` |
| E | the rendered instruction contains `### Do NOT patch packages/checkout/src/checkout.ts:24` |
| F | `ingest.py --seed && ingest.py --once` writes exactly two `fix-*.md` |
| G | `./run.sh restart` brings up three components; the UI badge reads `live pipeline` |
| H | `./run.sh test` → base suite plus selected extension counts, exit 0 |
| I | fixture replay applies one validated diff at the pinned base; only durable customer-verified acceptances become positive learning examples |

## Definition of done

```bash
./run.sh restart          # three components up, feed seeded
./run.sh run              # engine runs; terminal streams its stage log
./run.sh fix <signal-id>  # actor applies the instruction and verifies it
./run.sh capture-fix <signal-id> # live API actor; capture verified JSON diff
./run.sh replay-fix <signal-id>  # no model call; validate/apply/verify fixture
./run.sh test             # pipeline + triage + signal/UI + learning suites
./run.sh reset-shop       # target repo back to the planted bug
```

Two incidents diagnosed from one feed — a crash whose root cause is in a
different package from its stack trace, and a silent degradation with no
exception anywhere — each with a prior Greptile review finding on the same line,
recorded **before** the incident.

## Deliberately not covered

These tickets rebuild the running system. Not included, and not needed to run
it: `contract.md`, `correlation.md`, `roadmap.md`, `competition.md`,
`playbook.md`, and `docs/` (the pitch deck). They are argument and narrative
written *about* the system — reconstruct the system first; the prose describes
whatever it turns out to be.
