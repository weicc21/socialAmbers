# H2 — Diagnose-to-fix CTA with live Codex actor streaming

Run after H1 passes. This optional extension closes the interactive demo loop
from a successful diagnosis to a verified local code patch. Read
`prompts/00-conventions.md` first.

There is another optional H2 ticket for ambiguity resolution. The two
extensions are compatible but are not parallel tickets because both update UI
guards and replay documentation. Apply them sequentially and rerun the complete
suite after each.

## Files

Modify only:

```text
agent.py
ui/runtime_bridge.py
ui/app.py
ui/test_signals.py
prompts/F2-actor.md
prompts/G1-streamlit-frontend.md
prompts/H1-test-suite.md
prompts/README.md
```

Do not add a second actor implementation. The CTA must invoke the real
`agent.py` that `./run.sh fix <signal-id>` already uses.

Use the OpenAI Responses API through the existing `OPENAI_API_KEY` environment
contract. Default `OPENAI_MODEL` to `gpt-5.6-sol`; never embed a credential,
write it to status/events, or accept it from the browser. The live actor uses
strict local function tools and remains outside diagnosis.

## Product behavior

On the live Diagnose view, place an issue selector and **Fix issue** CTA beside
**Run pipeline**. The CTA is disabled until all of these are true:

- at least one persisted diagnosis has a `signal_id`;
- `runtime/fix-<signal-id>.md` exists;
- the ingestion/correlation pipeline is idle;
- no fix actor is already requested or running;
- the selected fix has not completed.

Clicking the CTA starts `agent.py <signal-id>` asynchronously and immediately
returns control to Streamlit. Never run the model synchronously in the
Streamlit fragment: it would freeze the terminal throughout model and test
execution.

The CTA creates a unique `fix/socialclues/<signal-id>-<timestamp>` branch for
every invocation, then applies and verifies the patch there. It does **not**
commit or push. Preserve `_DENIED = ("git commit", "git push")`; those are the
only Git operations excluded by this ticket. The button help states that exact
boundary.

## Runtime contract

Add one status file per signal:

```text
runtime/fix-status-<signal-id>.json
```

States are `requested`, `running`, `completed`, and `failure`. Completed status
includes the working branch and changed-file list. Failure includes actionable
detail. Write actor status atomically through a temporary file and rename so
Streamlit never parses a partial object.

`runtime_bridge.request_fix(signal_id)` must:

1. accept only `[A-Za-z0-9._-]+` signal IDs;
2. require the matching persisted fix instruction;
3. refuse while any actor is requested or running;
4. write `requested` before launch so rapid double-clicks cannot spawn twice;
5. launch `[sys.executable, agent.py, signal_id]` with `subprocess.Popen`, the
   project root as cwd, inherited environment, and a new process session;
6. send stdout/stderr to `runtime/logs/actor-<signal-id>.log`;
7. turn launch failure into persisted `failure` plus an `actor.failure` event;
8. never raise into Streamlit.

Add `fix_status`, `fix_in_flight`, `has_fix`, `request_fix`, and
`pipeline_in_flight` to `runtime_bridge.py`. `work_in_flight()` includes fix
states so the fast fragment continues repainting until the actor stops.

## Real actor event stream

`agent.py::log()` continues flushing human-readable stderr and, while
processing a named signal, appends the same event to `runtime/events.jsonl`:

```json
{
  "at": "<ISO timestamp>",
  "kind": "actor.tool",
  "detail": "turn 2 · write_file · ...",
  "signal_id": "sig-0001"
}
```

Emit and map all of:

```text
actor.start
actor.branch
actor.tool
actor.result
actor.text
actor.error
actor.failure
actor.ready
actor.queue
actor.verify
```

Every event renders under the literal terminal channel **FIX AGENT** with a
tone appropriate to success, information, tool output, or failure. Do not
synthesize progress in the UI. The same terminal first shows correlation and
then the actor's actual Responses API tool loop and verification output.

After successful model verification, run a deterministic proof step with
`cwd=ACME_SHOP_PATH` and stream it under **FIX PROOF**:

```text
$ cd acme-shop
$ git branch --show-current
fix/signalfuse
$ git status --short
 M packages/pricing/src/promo.ts
$ git diff --stat
 packages/pricing/src/promo.ts | ...
```

These are real subprocess results, not terminal-shaped prose returned by the
model. Display the stable repository label `acme-shop`, not its absolute host
path. Do not accept arbitrary commands from the browser.

On success, calculate the current branch and changed files from Git, persist
`completed`, emit `actor.ready`, and mark the signal seen. On nonzero actor
return, persist and emit failure. Missing API configuration is a visible
failure, not a fake completion.

## Capture boundary for deterministic replay

The live path may be invoked explicitly with `--capture-fixture`. Capture only
after the model finishes, prescribed verification passes, and deterministic
Git proof agrees with the changed-file allowlist. Serialize the actual
`git diff -- <filepath>`—never reconstruct a patch from model prose—to
`engine/fixtures/agent_fixes/<signal-id>.json`.

The JSON contains `schema_version`, `fixture_id`, `signal_id`, pinned
`base_head`, `generated_by`, `expected_changed_files`, argv-array verification
commands, and one object per changed file with `filepath`, `line_start`,
`line_end`, and `diff`. Capture is opt-in so ordinary live fixes never mutate
golden fixtures. Wave I2 owns fixture validation and replay.

## Streamlit rendering

Keep the fast `@st.fragment(run_every=0.2)`. Use five header columns:

```text
status | diagnosed issue selector | Run pipeline | Fix issue | Refresh
```

The selector shows `<feature> · <signal-id>` for diagnoses with persisted fix
instructions. This avoids silently fixing the newest of multiple diagnoses.
After click, show a toast and let actor events communicate progress in the
terminal. A launch refusal shows an error. Diagnosis cards remain below.

Before I2, replay mode does not enable a fake actor. Never label scripted
terminal prose as live model execution. I2 replaces presentation-only replay
with a validated captured diff and real local verification.

## Tests

Add three tests to `ui/test_signals.py`:

1. A fix instruction launches the exact real actor command once; a second
   request while `requested` is refused.
2. Missing instructions and unsafe signal IDs cannot launch a process or escape
   `runtime/`.
3. A running fix keeps polling active, actor events map to `FIX AGENT`, and
   deterministic Git proof maps to `FIX PROOF`.

Mock only `subprocess.Popen`; never invoke OpenAI in the required suite. Extend
the emitted-event guard to scan `agent.py`. Extend the static UI guard to
assert the source contains `Fix issue`, `request_fix`, and the
publication-boundary help text.

## Acceptance

```bash
export ACME_SHOP_PATH=../acme-shop
./run.sh test
```

Expected after this extension: `✓ all 42`, `✓ all 15`, `✓ all 23`; exit 0.

Then run the real UI path with an OpenAI key:

```bash
./run.sh reset-shop
./run.sh restart
./run.sh run
```

Open Diagnose, wait for the pipeline to become idle, select
`checkout/promo · sig-0001`, and click **Fix issue**. The same terminal must
show `FIX AGENT` start, branch, tool, result, and ready events. Then:

```bash
./.venv/bin/python -c "
import json
s=json.load(open('runtime/fix-status-sig-0001.json'))
assert s['state']=='completed', s
assert s['branch'].startswith('fix/socialclues/sig-0001-'), s
assert s['changed_files']==['packages/pricing/src/promo.ts'], s
print('verified local fix completed from CTA')"
git -C ../acme-shop status --short
git -C ../acme-shop branch --show-current
```

The target repo shows only the allowed pricing file changed on the reported
unique `fix/socialclues/<signal-id>-<timestamp>` branch. A full
`./run.sh restart` returns ACME Shop to `main`/`master` and deletes every local
branch in that actor-owned namespace so the flow can be repeated. No commit or
push exists.

## Definition of done

- Fix is disabled before diagnosis and while diagnosis or another fix runs.
- A rapid second click cannot spawn another actor.
- The UI launches the real `agent.py`, not an alternate or simulated path.
- Actual actor logs stream into the existing terminal.
- Success and failure remain visible after process exit.
- The actor edits and verifies locally but retains the explicit publication
  boundary.
