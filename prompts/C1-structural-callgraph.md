# C1 — Call-graph walk

Create `socialClues/engine/structural.py`. Runs in parallel with C2, C3, C4.
Depends on B1 only.

## Why this exists

A stack frame says **where** a program died. It does not say **why**, and for
the interesting bugs those are different files in different packages. A
diff-scoped code reviewer cannot close that gap either: the defect usually lives
in a file the breaking commit never touched.

What closes it is not semantics but **reachability**. Given `promo!.discount`
threw at `checkout.ts:24`, the chain is entirely mechanical:

```
checkout.ts:24   promo!.discount                    ← crash frame
checkout.ts:22   const promo = resolvePromo(code)   ← where the value came from
promo.ts:9       export function resolvePromo(): Promo | null
promo.ts:12      if (promo.expiresAt < Date.now()) return null   ← the defect
```

Every hop is *resolve this symbol → find its definition → enumerate its return
paths*. No model, no ranking, no embedding index — and unlike an inferred
answer, each hop names a definition you can open.

## Scope — state this honestly in the module docstring

A **TypeScript-shaped reader, not a type checker**. It resolves single-assignment
locals to a direct callee and follows that callee across files. It does **not**
handle re-assignment, destructuring, method chains, dynamic dispatch, or
aliasing through intermediates. For those, a real LSP or the TS compiler API is
correct. This covers the null-propagation shape that produces most
crash-site/root-cause splits, and it **refuses rather than guesses** when the
shape does not match.

## API

```python
def repo_root() -> Path | None
@dataclass
class Hop:
    file: str; line_start: int; line_end: int
    symbol: str | None; rationale: str
    distance: int          # hops from the crash frame; 0 is the frame itself
    @property
    def location(self) -> str      # "file:line_start"

def expand(file: str, line: int, root: Path | None = None,
           max_hops: int = 2, error_message: str | None = None) -> list[Hop]
```

`repo_root()` resolves `ACME_SHOP_PATH`, then `<repo>/acme-shop`, then
`<repo>/../acme-shop`. Returns `None` if none exist — the target moved out of
this repo once already, so never assume a fixed location.

## Algorithm

**Hop 1 — which symbol was dereferenced, and where did it come from?**

Find every dereference on the crash line with a regex capturing
`(symbol, optional bang, property)`. A crash line usually dereferences several
things (`cart.subtotal` **and** `promo!.discount`), so you must yield **every**
candidate, not the leftmost — matching the first one resolves the wrong symbol
and returns nothing.

Rank candidates by:
1. the property named in `error_message` (`reading 'discount'`) — exact when
   telemetry supplies it
2. presence of a `!` non-null assertion — someone silenced the compiler on
   precisely this value
3. everything else

For each candidate in order, scan backwards within the enclosing function for
`const|let|var <symbol> = <expr>`. The right one is the one with a resolvable
local assignment; a function parameter (`cart`) has none and falls through.

Emit `Hop(distance=1)` at the assignment line.

**Hop 2 — resolve the callee across files.**

Extract the first identifier called in `<expr>`, skipping language keywords
(`if`, `for`, `return`, `typeof`, `await`, `new`, `Math`, `JSON`, `console`, …).
Search `packages/*/src/**/*.ts` for its declaration, **preferring an exported
one** — that is what a cross-package reference resolves to.

In the resolved function, find lines matching `return (null|undefined);`. Take
the **last** one: earlier returns are usually the documented "not found" case
callers already expect. Emit `Hop(distance=2)` there with a rationale naming the
callee and stating its caller dereferences the result without checking.

If the function has no null return, emit a hop spanning the whole function
instead.

## Helpers

- `_enclosing_function(lines, line)` → `(start, end, name)` by scanning upward
  for a declaration then brace-counting. Not parsing. Degrades to a wide range,
  never a wrong one.
- `_definition_of(root, name)` → `(Path, line)` or `None`.
- `_read(path)` → lines, `[]` on `OSError`.

## Refusal is a feature

`expand` returns `[]` when the frame does not match a followable shape. That is
a **refusal, not a claim that no root cause exists**. A wrong root cause is worse
than an absent one: it sends the fix to the wrong file with confidence attached.

## Acceptance

```bash
ACME_SHOP_PATH=../acme-shop ./.venv/bin/python -c "
from engine.structural import expand
h = expand('packages/checkout/src/checkout.ts', 24,
           error_message=\"Cannot read properties of null (reading 'discount')\")
assert len(h) == 2, h
assert h[0].location == 'packages/checkout/src/checkout.ts:22'
assert h[1].file.endswith('pricing/src/promo.ts') and h[1].line_start == 12
assert expand('packages/pricing/src/promo.ts', 1) == []   # refuses
print('callgraph ok:', ' -> '.join(x.location for x in h))"
```

It must reach `packages/pricing/src/promo.ts:12` — a different package from the
crash — with the error message supplied **and** omitted. Both paths must work,
because degradation incidents have no error text.
