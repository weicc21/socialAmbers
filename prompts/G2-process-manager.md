# G2 — Process manager

Create `socialClues/run.sh` (chmod +x). Runs in parallel with G1.

**Written for bash 3.2** — macOS ships that as `/bin/bash`. No associative
arrays, no `${var,,}`, no `mapfile`. Use `case` dispatch functions instead.

`set -uo pipefail` — **not `-e`**. A component failing to start must print
diagnostics and return a code, not abort the script mid-sequence.

## Environment

Source `.env` under `set -a` so every child inherits it. Without this
`GREPTILE_API_KEY` never reaches the MCP server and the semantic path silently
degrades to cached fixtures — a failure whose only symptom is slightly worse
answers. Add the comment: values must be **unquoted in `.env`**; the shell
strips quotes but naive parsers do not.

Resolve `ACME_SHOP_PATH` by probing `$ROOT/acme-shop` then `$ROOT/../acme-shop`.

```bash
KEY_STATE="MISSING"; [ -n "${GREPTILE_API_KEY:-}" ] && KEY_STATE="set"
```

**Presence flag only — never interpolate the secret into output.** `usage`
prints this on every invocation.

Defaults: `MCP_PORT=8787`, `UI_PORT=8501`, `THRESHOLD=3`, `INGEST_MODE=manual`,
`PACE=0.25`, `ENGINE_PACE=0.3`, `COMPONENTS="mcp ingest ui"`. Colors only when
`[ -t 1 ]`. `ENGINE_PACE` controls display pacing at the ingestion boundary,
not correlation behavior.

## Three components

| name | command | port |
|---|---|---|
| `mcp` | `$PY -m engine.server --http --port $MCP_PORT` | 8787 |
| `ingest` | `$PY ingest.py --watch --threshold N [--manual --pace P] --engine-pace E` | — |
| `ui` | `$STREAMLIT run ui/app.py --server.port $UI_PORT --server.headless true` | 8501 |

PIDs in `runtime/pids/<name>.pid`, logs in `runtime/logs/<name>.log`.

## Lifecycle rules that exist because of specific failures

**Start** — refuse if the port is already busy and print the `lsof` command to
find the holder. After `nohup`, sleep, check `kill -0`, and on death **tail the
last 6 log lines inline**: a start failure whose output is buried in a file
gets diagnosed by reading the wrong thing first. Then `wait_for_port` up to 10s;
a live PID that never listened is a distinct failure and must say so.

**Stop** — TERM, poll 3s, then KILL with a warning. Then **reap orphans holding
the port**: streamlit and uvicorn both fork, and the parent exiting does not
free the socket. Without this, `restart` fails on "port in use" with nothing in
the process table.

`sweep_pattern` recovers a component whose pidfile was lost. It **must be
component-specific** (`ingest.py --watch`, `engine.server --http --port
$MCP_PORT`, `streamlit run ui/app.py --server.port $UI_PORT`) — a shared pattern
here will happily kill a sibling that is running perfectly well.

Stop order is `ui ingest mcp`, reverse of start: ingest depends on mcp.

## Commands

```
start [component...]     stop [component...]     status     logs <name> [-f]
seed                     post "<text>"           run        fix [<signal-id>]
reset-shop               actor [--emit]          test       clean
restart                  restart <component>
```

**`restart` with no argument is a full cycle: stop → reset actor-owned ACME
Shop fix branches → `rm -rf runtime/` → start → seed.** If the current branch
matches `fix/socialclues/*`, discard its tracked demo patch, switch to
`main`/`master`, and delete every local `fix/socialclues/*` branch. Never reset
or delete an unrelated branch; abort restart if cleanup fails. Bundled because
the demo gets reset a lot.

**`restart <component>` deliberately does NOT clean or seed.** That form exists
to bounce one process without losing the run you are in the middle of, and
wiping the bus there would be a nasty surprise. Two different behaviours behind
one verb, so the comment explaining the split is required.

`status` prints a process table (`up` / `no-port` / `down`), then the gate state
from `control.json`, then the live clusters from `state.json` with the same
`▓▓▓░` bar the UI draws — via a heredoc'd `$PY -` block, since bash 3.2 has no
JSON parsing. A `no-port` row means the process is alive but not listening; that
is a real state and collapsing it into `up` hides a hung start.

`run` fails loudly if ingest is not running rather than writing a control file
nothing will read.

`post` shells into `ui/runtime_bridge.post_complaint` so the CLI and the
compose box take the identical path — two code paths for one action drift.

`reset-shop` reverts the target repo between dry runs:
`git checkout -- .`, `git clean -fd`, `checkout main`, `branch -D
fix/signalfuse`. **The actor edits in place, so a second run would otherwise
start from the first run's output and quietly "verify" a fix that was already
applied.** Print the resulting `git status --short`.

`test` runs all three suites, accumulating failures rather than short-circuiting:
`test_pipeline.py`, then `ui/test_triage.py` and `ui/test_signals.py` from
inside `ui/`. Return non-zero if any failed. Seeing all three results in one
pass is worth more than failing at the first.

Keep `agent` as an alias for `fix` — muscle memory, one line, harmless.

`usage` is the default for no args, `-h`, `--help`, `help`; unknown commands
print the error, then usage, then `exit 1`.

## Acceptance

```bash
chmod +x run.sh
bash -n run.sh                              # parses under bash 3.2 syntax
shellcheck run.sh || true                   # advisory
./run.sh                                    # usage, GREPTILE_API_KEY=set|MISSING
./run.sh restart                            # stop, clean, start, seed
./run.sh status                             # three up, gate manual, N queued
./run.sh post "promo code 500s at checkout"
./run.sh run && sleep 8 && ./run.sh status  # clusters diagnosed
./run.sh logs ingest | tail -20
./run.sh stop && ./run.sh status            # three down
lsof -nP -iTCP:8501 -sTCP:LISTEN            # empty — no orphan
```

The last line is the check that matters. An orphaned streamlit holding :8501 is
the single most likely reason a restart fails thirty seconds before a demo.
