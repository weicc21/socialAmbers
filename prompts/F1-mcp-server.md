# F1 — MCP server

Create `socialClues/engine/server.py`. Runs in parallel with F2 and F3.

## The design choice this file exists to defend

`investigate_signal` performs the fusion **inside the server** and returns a
validated Diagnosis. The alternative — proxying `query_logs` and `query_code` up
to the agent and letting it correlate in context — would make the correlation
slow, nondeterministic, and impossible to unit-test. The escape hatches exist so
the agent is never boxed in, **not as the primary path**. Put this in the module
docstring.

## Construction

```python
from mcp.server.mcpserver import MCPServer
def build_server(telemetry: TelemetryClient | None = None,
                 greptile: GreptileClient | None = None) -> MCPServer
```

Instantiate clients **once** at build time and close over them — per-call
construction re-reads fixtures and re-resolves env on every tool call.

## `INSTRUCTIONS` — the server-level prompt

Must state the two-axis rule in the words a consuming agent will act on:

> entries carry both a `source` (which analysis found it) and a `role` (what it
> is in the causal chain). Patch the `root-cause` entry. The `crash-site` entry
> often has HIGHER confidence because both analyses agree on it, but it is where
> the exception surfaced, not where the defect lives.

## Tools

| tool | arguments | returns |
|---|---|---|
| `investigate_signal` | `signal_id, symptom, feature, window_minutes=90, families=None` | full diagnosis dict + `proposed_fix` + `fix_instruction` |
| `list_fix_instructions` | none | `{pending:[{signal_id, instruction_path, feature, mode, patch_target}], count}` |
| `get_fix_instruction` | `signal_id` | `{signal_id, instruction}` |
| `propose_fix` | `diagnosis_id` | `{diagnosisId, target, files, strategy, risks, testPlan}` |
| `query_code` | `question` | `{answer, sources[], servedFrom, degraded}` |
| `query_telemetry` | `query="", window_minutes=90` | clusters + frames + errorRate + changepoint + deploys |

**Descriptions are the API.** A model chooses tools by reading them, so each one
must say when to call it and what to do with the result.
`investigate_signal` says *"Call this first"* and repeats the role rule.
`query_code` says *"not as a substitute for investigate_signal"* — without that
line a model will happily reach for the low-altitude tool and re-derive the
correlation badly.

Docstrings carry the per-argument help (`symptom: ... This becomes the
code-analysis query, so be specific.`) — that is what stops a caller passing
`"checkout broken"` and getting a useless semantic query.

Keep `_diagnoses: dict[str, Any]` at module scope so `propose_fix` can resolve
an id from an earlier call. On an unknown id return
`{"error": ..., "known": sorted(_diagnoses)}` — **return the error, never
raise**: an exception across the MCP boundary reaches the model as a protocol
failure it cannot reason about, while a dict tells it what to do next.

`list_fix_instructions` and `get_fix_instruction` read `runtime/fix-*.md` and
`runtime/diagnosis-*.json` written by F3. They make the actor's queue
discoverable to *any* MCP client — Claude Desktop, Cursor, a customer's own
agent — without a shared filesystem convention having to be documented anywhere
else.

## `main()`

```bash
python -m engine.server            # stdio — MCP Inspector, Claude Desktop
python -m engine.server --http     # streamable-http on 127.0.0.1:8787/mcp
```

`argparse` with `--http`, `--host 127.0.0.1`, `--port 8787`. Print the URL
before serving.

## Acceptance

```bash
set -a; . .env; set +a; export ACME_SHOP_PATH=../acme-shop
./.venv/bin/python -c "
from engine.server import build_server
s = build_server()
print('tools:', sorted(t.name for t in s.list_tools()))" 
npx @modelcontextprotocol/inspector --cli \
  ./.venv/bin/python -m engine.server --method tools/list
```

Six tools. Then call `investigate_signal` through the inspector with
`checkout/promo` and confirm the returned `code_evidence` contains exactly one
`role == "root-cause"` at `packages/pricing/src/promo.ts:12`, and that
`fix_instruction` is present and non-empty.
