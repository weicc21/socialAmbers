# I2 — Captured Codex fix fixture and deterministic replay

Run after I1. This makes the final fix demonstration repeatable and inexpensive
while preserving a separate, honest live Codex path.

## Files

Modify `agent.py`, `ui/runtime_bridge.py`, `ui/app.py`, `ui/test_signals.py`,
`run.sh`, `prompts/H2-agent-fix-cta.md`, `prompts/G1-streamlit-frontend.md`,
`prompts/H1-test-suite.md`, and `prompts/README.md`. Store golden artifacts at
`engine/fixtures/agent_fixes/*.json`.

## Execution modes

`FIX_ACTOR_MODE` defaults to `fixture` and accepts only:

- `fixture`: no API call; apply captured verified JSON;
- `live`: call the API-backed actor without changing golden fixtures;
- `capture`: call the live actor, verify, then atomically capture its real Git
  diff.

The UI exposes only diagnoses with a fix instruction and fixture in fixture
mode. Help text names replay versus live execution. Every mode creates a fresh
`fix/socialclues/...` branch and preserves no-commit/no-push.

```bash
./run.sh capture-fix sig-0002
./run.sh replay-fix sig-0002
```

## Fixture validation

Before changing a file, require a safe matching signal ID, exact pinned
`base_head`, clean worktree, non-empty unique file list equal to
`expected_changed_files`, repository-contained paths, exact unified-diff
headers, argv-array verification commands, and a passing `git apply --check`.
After verification, changed files must exactly match the allowlist.

Support consecutive demo fixes without committing the first patch. If replay
starts on a `fix/socialclues/*` branch, compare its complete unstaged diff with
the captured fixtures. Only when one fixture reverses cleanly and exactly may
the actor reverse that known patch, verify a clean tree, switch to `main` or
`master`, and create the next fix branch. Refuse the handoff when there are
untracked files, staged changes, unknown edits, or no protected base branch.
Emit the transition as `actor.handoff`; never use a broad hard reset here.

Emit activity under `FIXTURE`. Never fall back silently from replay to a live
model. Never execute a fixture command through a shell string.

## Golden capture

Start at the pinned clean ACME Shop base. Supply `OPENAI_API_KEY` only through
the environment. Admit a fixture only after the live actor and all prescribed
checks succeed; serialize the actual Git diff, not model prose. Review the JSON
as code. If credentials or network fail, do not claim API provenance.

## Acceptance

In a disposable ACME Shop clone, replay `sig-0002`. Assert that no OpenAI client
is constructed, the base matches, only the expected file changes, field repro
and full eval pass, and Git reports no other modification. Unit tests mock
launch to prove fixture mode refuses missing fixtures and appends
`--fixture-replay` when present. Replay both golden fixtures consecutively and
assert that the second run safely returns from the first actor-owned branch
without requiring a commit.

## Definition of done

The demo can replay a verified fix without API cost or model variance. An
explicit capture path can regenerate the fixture through Codex when credentials
and network access are available.
