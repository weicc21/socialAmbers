# Conventions — inherited by every ticket

Apply all of this without being reminded. Tickets do not repeat it.

## Repositories and paths

Two repositories, siblings on disk:

```
socialClues/   this repo — the platform (Python)
acme-shop/     the target under test (TypeScript) — SEPARATE git repo
```

`socialClues` locates the target via `ACME_SHOP_PATH`, falling back to
`../acme-shop`. Never hardcode an absolute path.

All paths in tickets are relative to `socialClues/` unless prefixed `acme-shop/`.

Package layout inside `socialClues/`:

```
engine/       the diagnosis platform — schema, telemetry, evidence clients,
              correlate.py, pipeline.py (entrypoint), server.py (MCP)
ui/           triage, clustering, Streamlit frontend — importable standalone
runtime/      generated at run time; never committed
ingest.py     the ingestion service      agent.py   the actor
run.sh        process manager            test_pipeline.py   contract tests
```

The entrypoint module is `engine/pipeline.py`, **not** `engine/engine.py` —
`engine` is the package, and a module repeating its package name makes every
import read `engine.engine`.

## Environment

`socialClues/.env`, gitignored, sourced by `run.sh` with `set -a`:

```
GREPTILE_API_KEY=...
TARGET_REPO=<owner>/acme-shop
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.6-sol
ACME_SHOP_PATH=../acme-shop
```

**Write values unquoted.** A quoted value survives naive parsers as literal `"`
characters and produces `401 Invalid API key` on calls that validate, while
discovery calls still return 200 — an integration that looks healthy and is not.

Python deps, one venv at `socialClues/.venv`:

```
mcp>=2.0   openai   streamlit   pyflakes
```

## Non-negotiable engineering constraints

1. **No placeholders.** No `TODO`, no `pass  # implement later`, no stub that
   returns a constant standing in for real work. Every function ships complete.
2. **Never raise across a client boundary.** Telemetry, Greptile and review
   clients return a typed result carrying a `source`/`detail` field describing
   degradation. A dependency outage degrades the diagnosis; it never crashes the
   service.
3. **No model inside the correlation.** Stages 1–4 are pure functions over their
   evidence. Models are permitted only at the input edge (symptom phrasing) and
   the output edge (fix prose), and both fall back to deterministic templates.
4. **Comments explain why, not what.** Explain a non-obvious decision, a
   constraint, or a trap. Do not narrate the line beneath.
5. **Every failure is visible.** Prefer a loud refusal over a silent default. A
   guard whose tooling is missing must fail with an actionable message, never
   pass quietly.

## Style

- Python 3.11+, `from __future__ import annotations`, dataclasses over dicts for
  anything crossing a boundary, type hints on public functions.
- TypeScript strict, ESM, `.js` extension in relative imports.
- Tests are plain scripts with a `check(cond, message)` helper collecting
  failures into a module-level list, printing `✓ all N <suite> tests passed` and
  exiting non-zero on failure. **Do not add pytest.**
- `pyflakes` must report nothing across `ingest.py`, `agent.py`,
  `engine/*.py`, `ui/*.py`.

## Vocabulary — used precisely throughout

| term | meaning |
|---|---|
| **token** | a candidate substring of a complaint. Meaningless until probed. |
| **dimension** | the *name* of a telemetry field (`promo.code`). Finite set. |
| **value** | content stored in a dimension (`SAVE20`). |
| **artifact** | a token that turns out to be a value of some dimension. **Telemetry decides, not us.** |
| **crash site** | where execution terminated. Observed. Not necessarily defective. |
| **root cause** | where the defect is. The patch target. Exactly one per diagnosis. |
| **signal** | a cluster of complaints about one feature, with lifecycle state. |

## The invariant that governs the whole system

Two axes on every `CodeLocation`, never collapsed:

- **`confidence`** — *epistemic*. How sure are we this location is involved?
  Derived from how many independent paths named it.
- **`role`** — *causal*. What part does it play? Derived from *which* path found
  it and how.

The evidence that makes you most certain is evidence about location-of-death,
not about cause. A stack frame is the strongest thing you have and is precisely
the wrong place to patch when the defect lives a package away.

**Inference never outranks observation**: locations not backed by a stack frame
are capped at `CEILING_INFERRED = 0.92`; frame-backed locations may reach
`W_BOTH = 0.95`. `patch_target` selects on the `role` field. Never
`max(..., key=confidence)`.
