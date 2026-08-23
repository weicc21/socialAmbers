# F3 — Ingestion service

Create `socialClues/ingest.py`. Runs in parallel with F1 and F2.

## What it is

The component that turns posts into investigations: tails an append-only
complaint bus, runs triage and clustering, and dispatches an investigation the
moment a cluster crosses its threshold.

The bus is a **JSONL file, not a broker** — inspectable with `tail -f`, survives
a restart, needs no infrastructure, and the seam it creates (append here, react
there) is the same seam a real queue would occupy.

## Files — the entire inter-process contract

```
runtime/complaints.jsonl   in    frontend appends, service tails
runtime/state.json         out   live signals + counts, frontend reads
runtime/events.jsonl       out   run events, terminal renders
runtime/control.json       both  gate mode and run requests
runtime/signal-<id>.json   out   the payload handed to the engine
runtime/diagnosis-<id>.json out  full engine output
runtime/fix-<id>.md        out   the instruction an actor picks up
```

Track the bus by **byte offset** (`fh.seek(self.offset)` … `self.offset =
fh.tell()`), never by line count — the file is appended to while being read.

`sys.path.insert(0, str(ROOT / "ui"))` before importing `signals` and `triage`;
the UI package is deliberately importable standalone.

## `log(kind, detail, **extra)` — writes twice

Once to stdout (captured to the service log) and once as JSON to
`events.jsonl`. Every stage name the engine emits flows through here unchanged,
so the frontend terminal shows the engine's own vocabulary rather than a
re-labelled summary. **G1's channel map must cover every `kind` emitted here.**

## Manual gate

`control.json` = `{mode, run_requested, queued}`.

In `--manual` mode nothing is processed until a run is requested — from the
frontend's Run button or `./run.sh run`. **This exists for demos:** complaints
pile up visibly while you talk, then the whole pipeline runs while the audience
is watching the log, instead of having already finished before anyone switched
tabs.

`_peek_queued()` counts unprocessed lines **without consuming them** (seek to
offset, count, do not advance) so the queued badge can update while the gate is
still closed.

## Personas

`_HANDLES` — 20 `(name, handle, avatar)` triples. `random_persona()` excludes
handles already on the bus.

Not decoration. Near-duplicate dedup is **author-scoped**, and the escalation
threshold counts **distinct authors**, not posts. Without a fresh persona per
submission, similarly worded reports may collapse and differently worded ones
may accumulate without adding corroborating voices, so the threshold meter
stalls **for no visible reason on stage**. On pool exhaustion append digits
rather than reusing.

## `Ingestor.tick()`

1. Gate check → `_report_queued()` and return if closed
2. `_read_new()`; empty → return
3. Per complaint: `classify(text)` → `log("triage", ...)`, sleep `pace`
4. `store.ingest(batch)`
5. Log `duplicates` / `created` / `absorbed` / `reinforced`
6. `write_state()`
7. For each dispatch not already in `self.dispatched`:
   `log("threshold.cross", ...)` then `dispatch(sig)`

`--pace` inserts a delay between complaints so the log is readable on screen.
**Pacing only — nothing else changes.** Say so in the help text; a reviewer must
be able to tell it is not staging the result.

`--engine-pace` (default `0.3`) separately paces events produced during a real
diagnosis. Wrap the callback passed to `diagnose` so it first calls
`log(kind, detail, signal_id=...)` and then sleeps for `engine_pace`. The
correlation engine itself stays fast for direct API/MCP consumers; only this
demo ingestion boundary makes its genuine events arrive at approximately three
lines per second. Do not synthesize, batch, or replay hardcoded engine messages
on the live path.

## `dispatch(sig)`

Write `signal-<id>.json`, call `diagnose(payload, on_event=log)` — `from
engine.pipeline import diagnose`, **imported late inside the function**, so the MCP stack is not pulled in on a `--seed`-only
invocation.

On exception: `log("engine.error", ...)`, set `sig.status = "open"`,
`self.dispatched.discard(sig.id)`, rewrite state, **return without raising**. A
failed run must not kill the service, and the signal returns to `open` so the
next tick retries with whatever changed. The engine is deterministic, so a
failure here is a bug worth seeing rather than a flaky call worth retrying —
which is exactly why it is logged loudly instead of swallowed.

On success: write `diagnosis-<id>.json` and `fix-<id>.md`, set status
`diagnosed`, `log("fix.ready", "fix-<id>.md · hand to an actor to apply")`.
Rewrite state with status `diagnosed` before emitting `fix.ready`; otherwise the
frontend can stop polling before the final card and event become visible.

`state.json` skips `status == "merged"` signals and sorts by complaint count
descending.

## `seed_bus()`

Truncate the bus, then publish `COMPLAINTS` **oldest first** — sort by
`-int(c["time"].rstrip("m"))` — so the threshold crosses in the same order a
live demo would produce.

## CLI

```
--watch    follow the bus            --once      drain the backlog and exit
--seed     load the seeded feed      --manual    queue arrivals, gate the run
--threshold N (default 3)            --pace SECONDS
--engine-pace SECONDS (default 0.3; display pacing for real engine events only)
--run      request a run against a service already watching
```

`--run` alone must exit after writing control.json — that is how `./run.sh run`
talks to an already-running service.

## Acceptance

```bash
export ACME_SHOP_PATH=../acme-shop
./.venv/bin/python ingest.py --seed
./.venv/bin/python ingest.py --once
ls runtime/                       # state.json events.jsonl fix-*.md diagnosis-*.json
./.venv/bin/python -c "
import json,glob
s=json.load(open('runtime/state.json'))
f=[x['feature'] for x in s['signals'] if x['status']=='diagnosed']
assert set(f)=={'checkout/promo','ai/assistant'}, f
assert len(glob.glob('runtime/fix-*.md'))==2
print('two signals diagnosed, two instructions written')"
```

Exactly two. The 20 seeded inputs produce five real clusters: promo and
assistant diagnose; payment and account remain at two independent voices;
shipping remains at one. No additional `diagnosis-*` or `fix-*` is permitted.
**Visible signals that do not fire are the proof qualification discriminates.**
