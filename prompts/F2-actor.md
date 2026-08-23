# F2 — The actor

Create `socialClues/agent.py`. Runs in parallel with F1 and F3.

## Deliberately dumb, deliberately separate

It makes **no diagnostic decisions**. The engine already decided what is broken,
where the patch belongs, and how to verify it. This reads that instruction,
edits files, and runs the named verification commands.

That boundary is the product claim: everything upstream is deterministic and
testable, everything here is a model editing files, which is neither. Keeping
them apart means a bad edit is visibly a bad edit rather than a mysterious
diagnosis — and it means this process is **replaceable**. An OpenAI model,
Codex, Cursor, or a customer's own agent consumes the same instruction with
nothing upstream changing.

## Model call

Use `openai.OpenAI()` and the Responses API. Default to
`OPENAI_MODEL=gpt-5.6-sol`, while allowing that environment variable to select
another compatible model without changing code. Call
`client.responses.create(model=..., instructions=SYSTEM, input=...,
max_output_tokens=8000, tools=TOOLS, reasoning={"effort":"high"},
parallel_tool_calls=False)`, looping while `function_call` output items come
back, to a `max_turns=24` ceiling.

Do **not** use the SDK tool runner here. The loop is ~20 lines, and the demo
needs a `log()` line per tool call, per text block, and per result — which means
owning the loop.

On the first request, `input` is the fix instruction. On every tool turn, pass
`previous_response_id=response.id` and an input list of
`{"type":"function_call_output", "call_id":..., "output":...}` items. Keep
`instructions=SYSTEM` on every request because instructions are not implicitly
carried forward with `previous_response_id`.

Read assistant text from `message` → `output_text` items and log it as
`actor.text`. For each `function_call`, JSON-decode `arguments`, log the call,
execute the matching local tool, log its result, and return that result with the
same `call_id`. Invalid JSON becomes a model-readable function result rather
than crashing the actor. No function calls means the actor is finished.

Tools use the Responses API function shape: `type="function"`, top-level
`name`, `description`, `parameters`, and `strict=True`. Every object schema has
`additionalProperties=False` so strict validation and the local dispatcher
agree on the accepted arguments.

## Three tools, no more

`read_file(path)`, `write_file(path, content)`, `run(command)` — all resolved
against `repo_root()`, **never** this repo. Anything the actor cannot do with
these it should report back rather than route around.

`repo_root()` resolves `$ACME_SHOP_PATH`, then `./acme-shop`, then
`../acme-shop`; `SystemExit` when none exist.

## Two guards that are not optional

**1 · Fresh fix branches.** `PROTECTED_BRANCHES = {"main", "master"}`.
`ensure_working_branch()` creates a unique local branch for every fix with
`git switch -c fix/socialclues/<signal-id>-<timestamp>` before the first model
turn. Cache that branch only for the active fix so repeated writes remain on the
same branch; resetting the active signal resets the cache. Never reuse an older
fix branch.

**2 · The publish blocklist.**

```python
_DENIED = ("git commit", "git push")
```

Match against `" ".join(command.lower().split())` so whitespace tricks do not
slip through. Local git stays allowed — `git diff` is genuinely useful for the
actor checking its own edit — but nothing may publish. On a hit, return a string
that **tells the model what to do instead**:

> BLOCKED: `git push` is not permitted. This actor verifies changes locally;
> committing and publishing are human decisions. Continue with the verification commands in the
> instruction.

A bare refusal makes a model retry with a variation. Naming the alternative ends
the attempt. This exists because during rehearsal an actor will decide it is
being helpful by opening a PR — against a repo the demo depends on.

`run` uses `shell=True, cwd=repo_root(), timeout=180`, returns
`f"exit={rc}\n{(stdout+stderr)[-4000:]}"`. Tail, not head: the failing assertion
is at the end of the output.

Never let a tool exception kill the loop — catch and return
`f"{type(e).__name__}: {e}"` as the tool result so the model can recover.

## `SYSTEM` — five rules, in priority order

1. Patch the file the instruction names. **If the instruction says NOT to patch
   a location, do not patch it — even when the stack trace points there and it
   looks like the obvious place. That warning exists precisely because the
   obvious place is the symptom.**
2. Run the verification commands. Reproduce **before** editing, re-run after,
   then run the regression command.
3. Smallest change that addresses the root cause. No refactoring, no tidying
   adjacent code, no features.
4. **If the evidence contradicts the instruction, stop and say so.** Reporting a
   contradiction is a useful result; quietly doing something else is not.
5. Do not commit or push. Leave the verified change on its local fix branch.

Plus: *"Read a file before writing it — write_file replaces the entire file."*

## The queue seam

```python
def instructions(poll=1.0, replay=False):   # yields (signal_id, text)
```

A file-poll over `runtime/fix-*.md` stands in for a queue. The seam is
deliberate: `instructions()` knows nothing about where work came from, so
swapping the poll for SQS/NATS/Redis Streams replaces one function and leaves
the actor untouched.

`runtime/.actor-seen` persists processed ids across restarts — an actor that
re-applies every past fix on startup would fight the repo. `--replay` opts back
in, which is what a fresh demo run wants. **Only a clean apply (`rc == 0`)
marks** — a failed run must remain visible as pending work.

## CLI

```
agent.py <signal-id>       apply one instruction
agent.py --list            what is waiting (default with no args)
agent.py --stdio           read the instruction from stdin
agent.py --dry-run         print it; change nothing
agent.py --watch           process instructions as they appear
agent.py --watch --emit    stream NDJSON to stdout instead of applying
agent.py --watch --replay  include already-processed signals
```

Wave I2 later adds `--capture-fixture` and `--fixture-replay` to this same
actor. Do not create a second replay actor; both paths share the branch, status,
proof, changed-file allowlist, and no-commit/no-push boundaries.

`--emit` is the interoperability proof: `./run.sh actor --emit | your-agent`
hands the same instruction to a foreign consumer.

`--dry-run` must work **with no API key** — the only way to inspect an
instruction on a machine that has none.

### UI-triggered status and event contract

When invoked with a signal id, write `runtime/fix-status-<signal-id>.json`
through an atomic temporary-file replacement. States are `running`,
`completed`, and `failure`; completed includes branch and changed files.
`log()` still flushes stderr and also appends its typed event to
`runtime/events.jsonl` while a named signal is active. Use the `actor.*`
vocabulary from `H2-agent-fix-cta.md`. This is the real event source for the
Diagnose terminal; never let the frontend simulate actor progress.

The Streamlit CTA does not change the publication policy. Keep commit, push,
merge, and PR creation outside this actor.

After success, independently run `git branch --show-current`,
`git status --short`, and `git diff --stat` with the target repository as cwd.
Emit the actual command/output sequence as `actor.verify` so the UI renders it
under `FIX PROOF`. Use the label `acme-shop` rather than leaking an absolute
host path. This proof is deterministic post-processing, not model narration.

## Acceptance

```bash
export ACME_SHOP_PATH=../acme-shop
python3 agent.py --list                        # pending, or the run-pipeline hint
python3 agent.py sig-XXXX --dry-run | head -40 # instruction printed, repo untouched
cd ../acme-shop && git status --porcelain      # empty
```

With `OPENAI_API_KEY` set, apply one real instruction and confirm: the actor
branched off `main`, the diff touches **only** the patch-target file, and
`git log --oneline -1` on `main` is unchanged. Then verify the blocklist by
feeding an instruction whose text asks for a push and confirming `BLOCKED`
appears in the log and no remote ref moved.
