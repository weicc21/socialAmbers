# Executing these tickets with Codex CLI

Alphabetical order **is** the execution order — the files are named for it.
`ls prompts/` gives `00 → A1 → A2 → A3 → B1 → … → H1`, a valid serial sequence.
The only thing the filename order does not encode is where you are allowed to
stop and check, and that is the part that matters.

## One session per ticket, not one session for all twenty

Do not hand Codex the folder and ask it to walk it.

- **Context rot.** By ticket twelve the session is carrying eleven tickets of
  irrelevant detail and will start "improving" wave-B files while working on
  wave F. The tickets are self-contained precisely so each one can start cold.
- **No gate.** A single session continues past a failed acceptance block, and
  you discover at wave G that B3 never worked.

One invocation per ticket, fresh context each time, and you read the acceptance
output between them.

## The per-ticket prompt

Reuse this for all twenty. Only the filename changes.

```
Read prompts/00-conventions.md, then prompts/D1-correlation-engine.md.

Execute that ticket completely. Create every file it names at the exact path
it names. Implement every behaviour it specifies — no TODO comments, no stub
functions, no "left as an exercise", no placeholder values.

When the code is written, run the ticket's Acceptance block verbatim and paste
its real output. If it fails, fix the code and run it again. Do not report
success without passing output.

Do not modify files outside the ones this ticket names. Do not touch other
tickets. If the ticket contradicts something you find in the codebase, say so
and stop rather than guessing.
```

The last two paragraphs are load-bearing. Without the scope line, an agent that
decides `correlate.py` is importing something wrong will go and edit
`telemetry.py` — and now wave B's acceptance is stale and nothing says so.

## Running it

```bash
cd ~/socialClues

codex exec --full-auto "$(cat <<'EOF'
Read prompts/00-conventions.md, then prompts/B1-diagnosis-schema.md.
Execute that ticket completely. Create every file it names at the exact path it
names. No TODO comments, no stubs, no placeholders. Then run the Acceptance
block verbatim and paste its real output. If it fails, fix and re-run.
Do not modify files outside the ones this ticket names.
EOF
)"
```

Wave A writes to the **other** repository, so point it there:

```bash
codex exec --full-auto --cd ../acme-shop "...A1 prompt..."
```

Check `codex --help` for the exact sandbox and approval flags on your version.
Every ticket creates files and runs `npm` or `python`, so the session needs
workspace write access — `--full-auto` is the usual way to grant it.

## Where to actually stop

Alphabetical order gives you the sequence. These are the four places not to
blow through:

| after | before starting | check |
|---|---|---|
| A3 | B1 | `cd ../acme-shop && npm run repro` throws at `checkout.ts:24` |
| C4 | **D1** | all four evidence clients return or degrade — none raise |
| D1 | E1 | `crash_site.confidence > patch_target.confidence`, target is `promo.ts:12` |
| F3 | G1 | `ingest.py --seed && ingest.py --once` writes exactly two `fix-*.md` |

**D1 is the hard boundary.** It consumes all six wave-B and wave-C modules, and
if any one of them is subtly wrong it will produce a *plausible* diagnosis
pointing at the wrong file — the exact failure mode this project exists to
argue against, and it does not announce itself.

The full per-wave gate table is in [`README.md`](README.md#wave-gates).

## Parallel, by wave

Within a wave the tickets are independent and touch disjoint files:

```bash
for t in C1-structural-callgraph C2-greptile-semantic-client \
         C3-greptile-review-client C4-triage-and-signals; do
  codex exec --full-auto "Read prompts/00-conventions.md and prompts/$t.md. \
Execute it completely, then run its Acceptance block and paste the output." \
    > "runtime/build-$t.log" 2>&1 &
done; wait
grep -l "Traceback\|FAIL\|✗" runtime/build-*.log
```

Four agents, four fresh contexts, no shared files. On the widest waves (A and
C) that is roughly 4× wall-clock, which on a hackathon timer is the difference
that matters.

Serial waves — **D** and **H** — take a single agent by construction.

## Reading the result

The acceptance block's pasted output is the gate, **not the agent's own
summary.** An agent that says "all tests pass" without output has, in practice,
often run nothing. Grep the logs for real failures before starting the next
wave:

```bash
grep -l "Traceback\|FAIL\|✗\|No such file" runtime/build-*.log
```

If a ticket half-lands, re-run the same prompt in a fresh session rather than
asking the existing one to continue. The ticket is idempotent by design —
it names exact paths and exact contents, so a second pass converges rather
than compounding.
