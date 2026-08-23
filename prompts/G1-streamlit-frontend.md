# G1 — Streamlit frontend

Create four files in `socialClues/ui/`: `seed_data.py`, `terminal.py`,
`runtime_bridge.py`, `app.py`. Runs in parallel with G2.

Build them in that order — each is imported by the next. All four are pure
presentation: **no correlation logic, no scoring, no lexicons.** On the live
path, every diagnosis and terminal value must be traced to a file under
`runtime/`; `seed_data.py` is permitted only for the explicitly labelled
offline replay path.

---

## 1 · `seed_data.py` — the replay dataset

Anchors, verified against the target repo:

```python
TARGET_FEATURE = "checkout/promo"
CRASH_SITE     = "packages/checkout/src/checkout.ts:24"
ROOT_CAUSE     = "packages/pricing/src/promo.ts:12"
CRASH_PKG, CAUSE_PKG = "@acme/checkout", "@acme/pricing"
THRESHOLD = 3
```

**These line numbers go stale silently.** They are asserted by a guard test in
H1; when the target repo changes, re-run `npx tsx scripts/repro.ts` and re-sync.

`COMPLAINTS` — 20 dicts, `id/name/handle/avatar/time/likes/reposts/relevant/
source/feature/text`. `time` is a numeric relative string (`"2m"`, including
`"0m"` rather than `"now"`) that F3 sorts on. `source` must visibly span these
nine plug-and-play inputs: campaign reply, support ticket, community, social
post, support chat, app review, session feedback, idea portal, and survey.

Composition matters more than volume:

| group | n | what it must contain |
|---|---|---|
| `checkout/promo` crash | 2 | expired SAVE20 → error page; one from marketing ops naming a 40k-subscriber send |
| `checkout/promo` abuse | 3 | **the same code applied repeatedly, compounding** — "free money glitch", "applied it twice and it doubled", "keep hitting apply". Delighted, not harmed. |
| `ai/assistant` drift | 4 | the assistant's **30-day return window contradicting the merchant guideline's final-sale, no-refund rule**. Every one must name both halves of the contradiction. |
| `checkout/payment` emerging friction | 2 | differently worded spinning/loading reports from independent people; remains at `2/3` |
| `account` emerging friction | 2 | login-loop reports from an app review and support chat; remains at `2/3` |
| `shipping` routed bug | 1 | a real 404 tracking-link report that remains at `1/3` |
| vetoed/unrelated noise | 6 | praise, two feature requests, spam, a pricing-display opinion, and a joke |

The promo cluster carrying **both postures at once** is what forces
`synthesize_symptom` to report two problems, and the assistant cluster is what
forces `degradation` mode. `relevant` is ground truth **for tests only** — the
UI must call `classify()` and never read it.

The payment, account, and shipping reports prove that real signals remain
visible without automatically becoming incidents. They must never create a
third diagnosis or fix fixture in the base demo.

`build_trace(complaint_ids) -> list[(delay, channel, text, tone)]` — the
scripted fallback. A function of the ids, so a live compose during the demo
appears in the log with the right id. Tones: `dim info ok warn accent code
crash cause`. It must walk the same four stages the real engine does and end on
`PATCH <root cause>` / `CITE <crash site> (higher confidence, wrong file)`.

`REPLAY_DIAGNOSES` — two dicts in the **exact shape a real Diagnosis crosses
the wire in** (`id, feature, mode, confidence, root_cause, code_evidence[],
contradictions[], social_context`), so the scripted and live paths share one
renderer. `social_context` contains the synthesized cluster summary, complaint
and distinct-author counts, families, artifacts, and three representative
excerpts. One diagnosis is `crash`, one `degradation`. Any other shape means
the fallback silently rots.

---

## 2 · `terminal.py` — the log renderer

```python
TONES: dict[str, str]          # tone → hex
CHANNEL_TONE: dict[str, str]   # channel label → tone
def script_rows(events, cursor) -> list[tuple[str, str, str, str]]
def to_html(rows) -> str
def render(rows) -> None
```

Rows are `(timestamp, channel, text, tone)` — **the one shape both sources
produce**, live and scripted.

**`flex-direction: column-reverse` pins the view to the newest line with no
JavaScript.** That is the whole trick: it keeps this renderable through
`st.markdown(..., unsafe_allow_html=True)` with no iframe and no `<script>` for
Streamlit to strip. Emit the lines reversed into the container.

Do **not** add a terminal component dependency. An earlier version offered
`streamlit-xterm`; its last release was June 2023 and the bundle failed to paint
in the iframe — exactly the kind of stale dependency that dies on demo day.

Escape `&`, `<`, `>` in every line: this renders complaint text and log output,
both attacker-adjacent, into raw HTML. Empty rows render `&nbsp;` so blank
spacer lines survive. No rows → an italic `idle — press Run pipeline`.

Fixed height 520px, `overflow-y: auto`, monospace, `white-space: pre`.

---

## 3 · `runtime_bridge.py` — the live reader

The frontend and the ingestion service share **plain files, not a socket**: the
UI appends to the bus, the service tails it, the service writes state and events
back. The UI can start, stop, and reload independently of the pipeline, and
everything on screen can be checked with `cat`.

```python
is_live()            # runtime/state.json exists
read_complaints()    # newest first
read_events(limit=400)
read_state() / signal_for(feature)
control() / is_manual() / queued_count() / run_pending() / request_run()
work_in_flight()
all_diagnoses()      # oldest first
latest_diagnosis()
post_complaint(text, persona=None)
events_to_rows(events)
```

Every JSON read catches `JSONDecodeError` and returns empty — files are read
**while being written**, and a traceback on a partial read would crash the page
mid-demo. The next poll catches it.

`post_complaint` uses `secrets.token_hex(3)` for the id: two posts in the same
second must not collide, or `SignalStore` drops the second as already seen. It
takes a fresh persona per post for the author-scoped-dedup reason in F3.

`all_diagnoses()` returns **every** diagnosis, oldest first. The demo runs two
incidents concurrently and showing only the newest hides whichever finished
second — usually the interesting one.

### `work_in_flight()` — read carefully

Returns True while there is something to poll for. Checks, in order:
`run_pending()`, `queued_count() > 0`, any signal `status == "investigating"`,
and finally **`events.jsonl` mtime within `QUIET_AFTER_SECONDS = 3.0`**.

The mtime check is not redundant. **Status bookkeeping has gaps** — the queue
drains before the first signal is written, and the engine can be several seconds
into a run before its status lands. A growing event log is the honest signal
that work is happening, and it goes quiet on its own when the run ends. Without
it the terminal freezes mid-run and a human has to click Refresh.

### `_CHANNEL` — the event vocabulary

Maps every event `type` the engine and ingestion emit to `(channel, tone)`.
Cover **all** of: `ingest.*`, `bus.malformed`, `triage`, `dedup.drop`,
`signal.*`, `threshold.cross`, `engine.*`, `stage.1.temporal`, `stage.1.deploy`,
`stage.2.logs`, `stage.2.join`, `stage.3.callgraph`, `stage.3.review`,
`stage.3.corroborate`, `stage.4.fusion`, `evidence.*`, `mode.degradation`,
`contradiction`, `fix.target`, `fix.ready`, `diagnosis.ready`, `schema.invalid`,
and the three provenance events `greptile.live`, `greptile.failure`,
`greptile.cache`.

Render those provenance events with literal, unmistakable channel labels:
**GREPTILE LIVE** for a successful MCP response, **GREPTILE FAILURE** for the
real endpoint error/rejection, and **GREPTILE CACHE** when offline fixtures are
substituted. A failure followed by fallback must render as two separate lines;
never collapse it into a generic semantic-stage message.

Map `stage.3.semantic` to the visible channel **CODE INTEL**, never `SEMANTIC`.
The detail supplies the capability/provenance pair (`semantic/cache`,
`semantic/review-mcp`, or a future `semantic/live`). Keep Greptile review events
under their explicit GREPTILE labels so viewers cannot mistake a live review
response for repository-wide semantic search. The scripted replay must say
`GREPTILE CACHE` and `semantic/cache`; it cannot present fixture citations as a
live Greptile result.

An unmapped type renders as **the raw type plus its detail**, never as anonymous
grey text. This map went stale once when the engine's stage names changed, and
the symptom on stage was a wall of unlabeled dim lines that read as gibberish.
H1 asserts every emitted type has a channel.

---

## 4 · `app.py` — the two views

`st.set_page_config(page_title="SocialClues", page_icon="📡", layout="wide")`.
The visible page title is also **SocialClues**; do not retain SignalFuse as a
stale browser title or heading.

**Source selection is automatic:** live when `runtime/state.json` exists and the
sidebar has not forced replay; scripted otherwise. Header badge says which.
Replay is the fallback when the wifi dies, and it must work with **zero**
services running.

### View switcher

`st.segmented_control` with `key="view_picker"`, **not `st.tabs`** — tabs reset
on every rerun and playback reruns constantly, which snaps the view back
mid-demo. The control is deselectable (a second click returns `None`), so mirror
the last real selection into `ss.view` and render from the mirror.

Views are **"Signal Feed"** and **"Diagnose"**. Not "Agent Trace" — there is no
agent in this path any more, and a stale tab name invites exactly the question
the architecture is designed to avoid.

### Signal Feed

Compose form (`clear_on_submit=True`) → live: `rb.post_complaint` + toast;
replay: prepend to session state.

Each post renders through `classify()` with **the matched terms visible**:
`SIGNAL · checkout/promo · 0.87 — surface=promo code failure=error page`. An
opaque 0.87 proves nothing on stage; the matched terms are inspectable. Render
`source` as a compact provenance pill in the post header so the UI reads as a
normalized customer-evidence feed, not a social-network clone. A composed post
without provenance falls back visibly to `customer report`.

Right column: one meter per live cluster based on **distinct authors**, not raw
post volume — `4/3 voices ▓▓▓`. Also show raw report count and failure families.
The hint changes with state (`N more independent voices before investigation` /
`Customer-evidence gate passed` /
`investigating — further complaints reinforce it rather than starting a second
run`). A `/*` feature adds the ambiguous-surface note. Show every cluster, not
just the promo one: a complaint naming only "checkout" lands in `checkout/*`,
and showing one feature made that look like it had been dropped.

A queued badge appears in manual mode. Replay renders five clusters: promo 5/3,
assistant 4/3, payment 2/3, account 2/3, shipping 1/3. Below the meters, a fixed
**two gates, two questions** card: independent customer voices qualify a pattern
for investigation; telemetry and code evidence separately determine whether a
fix is justified. State that only the two seeded incidents pass both gates.

### Diagnose

Live path is a fast-polling **`@st.fragment(run_every=0.2)`**, not a whole-page
rerun. The ingestion service deliberately emits real engine events at roughly
one per second; the shorter UI poll ensures each line paints promptly instead
of several arriving together.
Full-script reruns re-render the feed, the meters, and the compose box on every
tick, which reads as the page flickering rather than a log streaming. Fragments
repaint only this block.

Everything the fragment reads must be **inside** it — a variable defined in the
fragment and used in an orphaned block outside it raises `NameError` on first
paint, before any run has happened. H1 runs pyflakes over `ui/` for exactly this.

Header caption: event count, signal count, `◉ streaming` / `idle` from
`work_in_flight()`, plus a manual `↻ Refresh` that reruns **fragment scope**.
Explicitly label the source as the live tail of `runtime/events.jsonl` written
by `engine.pipeline`. Then the terminal, then one `diagnosis_card` per
diagnosis. The Run Pipeline CTA only requests a real ingestion run; it must not
start `build_trace`, invent intermediate reasoning, or dump a completed batch.
`build_trace` is restricted to the visibly labelled scripted replay path.

After a diagnosis persists `runtime/fix-<signal-id>.md`, show a diagnosed-issue
selector and **Fix issue** beside **Run pipeline**. It launches the real
`agent.py <signal-id>` asynchronously through `runtime_bridge.request_fix` and
keeps rendering the same terminal while `fix-status-<signal-id>.json` is
`requested` or `running`. Map every `actor.*` event to **FIX AGENT**. Disable
the CTA before diagnosis, during pipeline/actor work, and after completion.
State in button help that it produces a verified local patch and does not push
or open a PR. Replay mode never simulates actor execution.

Wave I2 replaces presentation-only fix replay with a captured verified diff.
With `FIX_ACTOR_MODE=fixture`, include only diagnoses that have both an
instruction and fixture, label the help as replay, and launch the same actor
with `--fixture-replay`. `live` and `capture` remain explicit API-backed modes;
never silently fall back between them.

### `diagnosis_card(d)` — shaped by mode

| mode | rows |
|---|---|
| `crash` | CRASH SITE (`cite, do not patch`) then ROOT CAUSE (`patch this`), each with source and evidence confidence |
| `degradation` | **NO CRASH SITE · nothing threw · every request returned 200** then ROOT CAUSE |
| `external` | EXTERNAL (vendor, `operational, not a patch`) then CALL SITE (`no timeout, retry or circuit breaker — the durable fix`) |

Rendering a degradation with the crash-mode template produced an **empty card**
and the incident vanished from the demo entirely. Branch on mode.

When `prior_review` exists, prepend a `FLAGGED P1` row above the locations —
PR number, title, location, `still unaddressed`, *"review saw this before users
did"*. It is the sharpest thing on the card.

Always show the first contradiction. Never hide it.

The schema field remains `confidence`, but every user-facing label must read
**evidence confidence**. It is a deterministic evidence-strength score, not a
calibrated probability. Apply the label to the card header, crash/root rows,
and exact code-evidence list. Replay terminal prose also says evidence
confidence; never show an unexplained bare decimal or imply “95% likely.”

Before the technical diagnosis card, render a visually distinct **What people
reported** panel from `d["social_context"]`. Show the synthesized cluster
summary, `N reports · M people`, family/artifact pills, and at most three quoted
complaint exemplars. Escape every value before placing it in HTML. Never render
handles or other social metadata here. For old persisted diagnoses without
`social_context`, fall back to `d["symptom"]` and label it a consolidated
complaint cluster rather than leaving the context blank.

After the card, provide a collapsed **Inspect exact machine evidence** expander.
Its header includes a forensic-trail summary with log-cluster and code-location
counts. Inside, use separate, clearly labelled sections for telemetry and stack
traces, code-analysis evidence, and the prior Greptile review response. Show
full returned stack frames, exact file/line spans, source, role, confidence,
rationale, review summary/status, and suggested code when present. A
degradation with no logs gets an explicit no-exception-telemetry message rather
than an empty section.

### Styling

One `st.markdown` `<style>` block. Dark surface `#0b0f14`/`#0f141a`, borders
`#222a33`, body `#c9d1d9`. Two semantic hues carry meaning and must stay
consistent with `terminal.py`: **`#e0952f` crash/structural**, **`#37c9b9`
cause/fused**. `tabular-nums` on every counter.

The complaint-context panel uses a restrained blue/violet gradient and Twitter-
style blue pills. Style Streamlit's evidence expander as a dark forensic panel:
blue/teal border and hover states, section dividers, high-contrast inline code,
and stack blocks with a blue left rule. Styling must improve hierarchy without
changing semantic crash/cause colors.

## Acceptance

```bash
cd ui && python3 -m pyflakes app.py terminal.py runtime_bridge.py seed_data.py
cd .. && ./run.sh clean && ./.venv/bin/streamlit run ui/app.py --server.headless true
```

With nothing else running: the badge reads `scripted replay`, Run pipeline
plays the trace, and two diagnosis cards render — one crash, one degradation.

Then `./run.sh restart`: the badge flips to `live pipeline`, posting a complaint
appears in the feed within a second, and pressing Run streams the engine's own
stage log into the terminal at approximately **one real event per second**, with
no unlabeled grey lines and no scripted trace warning. Each completed card shows
What people reported above the diagnosis and the styled machine-evidence
expander below it.
