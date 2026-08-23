# E2 — Engine entrypoint

Create `socialClues/engine/pipeline.py`. Runs in parallel with E1; both are
imported by wave F.

## The whole diagnosis path, with no agent in it

```python
def diagnose(signal: dict, *,
             telemetry: TelemetryClient | None = None,
             greptile: GreptileClient | None = None,
             reviews: ReviewClient | None = None,
             on_event: Callable[[str, str], None] | None = None) -> dict
```

Returns `{"diagnosis": <validated dict>, "fix": <dict>, "prompt": <str>}`.

An agent used to sit here, calling `investigate_signal` then `propose_fix` in
that fixed order every time. **That is not a decision, it is ceremony** — and it
put a nondeterministic hop on the critical path of the one component that is
supposed to be provable. Write that reasoning into the module docstring; it is
the architectural claim the project is judged on.

## Sequence

1. Emit three inspectable inputs: `engine.start` with `<feature> · N reports
   from M people`, then the supplied complaint families, then candidate tokens.
   These are real pipeline facts and make the live terminal explain what the
   engine is about to correlate.
2. `correlate(...)` — unpack `families` and `tokens` from `signal["evidence"]`,
   pass `on_event` straight through so engine and correlation share one log
3. Before validation, attach `payload["social_context"]` from the
   presentation-safe signal fields: `summary=signal["symptom"]`,
   `complaint_count`, `distinct_authors`, `families`, at most three
   `exemplars`, and `artifacts`. Do not add handles, personas, likes, reposts,
   or raw social metadata. This context travels with the persisted diagnosis so
   the UI never has to reconstruct or join the originating cluster.
4. `validate(payload)` — on failure `emit("schema.invalid", ...)` **and** attach
   `payload["_schema_problems"]`. Surface, never swallow: a schema break is a
   contract break, and the demo should say so out loud rather than render a
   broken card. Do **not** raise — a validation failure must still produce a
   diagnosis a human can look at.
5. `propose_fix(d)`, assign to `d.proposed_fix`, mirror into
   `payload["proposed_fix"]`
6. `fix_prompt(d, fix)` → emit the chosen strategy and then
   `emit("fix.target", "<file> · N line instruction")`
7. Replay `d.degraded` as `engine.degraded`, and `d.prior_review` as
   `evidence.prior_review` (`PR #n [P1] title — unaddressed`)
8. `emit("diagnosis.ready", "<id> · mode=<mode> · confidence 0.NN")`

## Why both forms cross the boundary

| form | consumed by |
|---|---|
| `diagnosis` | tests, UI, routing — structured, schema-validated |
| `prompt` | an actor with no other context — prose, self-contained |

Returning only the structure makes every consumer re-write the same
explanation. Returning only the prose makes the result unassertable. Ship both.

## Acceptance

```bash
set -a; . .env; set +a; export ACME_SHOP_PATH=../acme-shop
./.venv/bin/python -c "
from engine.pipeline import diagnose
seen=[]
out = diagnose({'signalId':'sig-1','symptom':'promo code fails at checkout',
                'feature':'checkout/promo',
                'evidence':{'complaintCount':4,'distinctAuthors':4,
                            'tokens':['SAVE20','500s'],'families':['availability'],
                            'exemplars':['SAVE20 returns a 500 at checkout'],
                            'artifacts':{'promoCodes':['SAVE20']}}},
               on_event=lambda s,d: seen.append(s))
assert '_schema_problems' not in out['diagnosis']
assert set(out) == {'diagnosis','fix','prompt'}
ctx=out['diagnosis']['social_context']
assert ctx['complaint_count']==4 and ctx['exemplars']==['SAVE20 returns a 500 at checkout']
assert 'engine.start' in seen and 'diagnosis.ready' in seen
print(len(seen), 'stages ·', len(out['prompt'].splitlines()), 'line prompt')"
```
