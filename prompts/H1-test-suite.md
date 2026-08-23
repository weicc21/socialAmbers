# H1 — Test suite

Create `socialClues/test_pipeline.py` (42 tests), `socialClues/ui/test_triage.py`
(15), `socialClues/ui/test_signals.py` (23). Runs last, against everything.

## Harness — no pytest

Each file defines `FAILS: list[str]` and `check(cond, msg)`, collects
`globals()` entries starting with `test_`, runs them all, prints
`✓ all N tests passed` or every failure with its message, and exits non-zero.

Collect failures rather than raising: **one run must report every broken
guarantee**, not the first. A message must name the observed value
(`f"expected root cause at promo.ts:12, got {loc}"`) — a bare `assert` tells you
nothing at 2am the night before a demo.

`test_pipeline.py` needs `sys.path.insert(0, "ui")`; the UI suites run from
inside `ui/`.

---

## `test_pipeline.py` — 42 tests, seven groups

### 1 · The central invariant (8)

`test_correlation_finds_the_planted_bug` · `test_crash_site_is_separate_and_
scores_higher` · `test_crosses_a_package_boundary` · `test_contradiction_is_
surfaced` · `test_schema_validates` · `test_exactly_one_root_cause` ·
`test_temporal_finds_the_suspect_deploy` · `test_fix_targets_root_cause_never_
crash_site`

The load-bearing assertion of the entire project:

```python
check(crash.confidence > root.confidence, "...")   # 0.95 > 0.92
check(fix.files == ["packages/pricing/src/promo.ts"], "...")
```

**Confidence ordering is asserted in the "wrong" direction on purpose.** If a
later change makes the root cause outrank the crash site, someone has started
selecting by score, and the whole two-axis design has quietly collapsed.

### 2 · Degradation — the silent incident (7)

`no_error_logs` · `finds_the_defect_from_metrics_alone` · `confidence_is_lower_
than_a_corroborated_crash` · `surfaces_the_metric_evidence` · `does_not_borrow_
an_unrelated_error_spike` · `says_error_monitoring_saw_nothing` ·
`test_two_hits_in_one_file_are_both_kept`

`does_not_borrow_an_unrelated_error_spike` is the sharp one: a promo `TypeError`
is firing in the same window, and a diagnosis that quietly attaches it is
**wrong in a way that reads as thorough**.

`two_hits_in_one_file_are_both_kept` catches keying candidates on `file`
instead of `file:line`.

### 3 · Fixtures still mean what they claim (4)

`test_telemetry_frames_still_mean_what_the_fixture_claims` ·
`test_greptile_cached_sources_point_at_real_lines` ·
`test_greptile_hallucination_anchors_still_mean_what_they_claim` ·
`test_prompt_is_the_control_surface_not_documentation`

**Open the real files in `$ACME_SHOP_PATH` and assert the anchored line still
contains what the fixture claims** — the dereference on `checkout.ts:24`, the
`expiresAt` check on `promo.ts:12`, the confidence clause on
`support_agent.md:6`.

Stale anchors have been the single most recurring defect in this project — five
occurrences, each producing a diagnosis that is confidently, invisibly wrong.
This class of test is the only thing that catches them, and it caught two
before they shipped. Skip loudly (a recorded failure) when the repo is absent,
never silently.

`prompt_is_the_control_surface` asserts `assistant.ts` **parses the markdown at
call time** — if the prompt were documentation rather than control surface,
patching it would fix nothing.

### 4 · The four evidence paths (8)

`test_callgraph_crosses_the_package_boundary` · `test_callgraph_refuses_rather_
than_guesses` · `test_inference_never_outranks_observation` · `test_no_root_
cause_claimed_from_frames_alone` · `test_greptile_degrades_instead_of_raising` ·
`test_prior_review_joins_on_the_suspect_deploy` · `test_deploys_are_feature_
scoped` · `test_golden_set_is_blind_to_the_planted_drift`

`refuses_rather_than_guesses` — an unresolvable identifier yields **nothing**.
Refusal is a feature; a plausible guess is worse than an empty result.

`inference_never_outranks_observation` — every inferred candidate ≤ `0.92`.

`no_root_cause_claimed_from_frames_alone` — with semantic, callgraph and review
all disabled, `patch_target is None` and `degraded[]` explains why. A system
that always answers is not more useful, only less honest.

`golden_set_is_blind_to_the_planted_drift` — run the target's eval and assert
it **passes** while the field question fails. That is the point of the
incident: an offline eval scoring 0.94 is not wrong, it is answering a question
customers are not asking.

### 5 · MCP surface (2)

`test_mcp_roundtrip` (in-process `Client(build_server())` via `asyncio`, tools
listed, `investigate_signal` returns a schema-valid diagnosis) and
`test_signal_payload_feeds_the_server` (a `SignalStore` payload is directly
consumable — the seam between clustering and the engine holds).

### 6 · Artifact binding (7)

`binding_is_discovered_not_declared` · `unresolvable_tokens_cost_nothing` ·
`artifact_join_beats_the_keyword_query` · `candidate_tokens_carry_no_domain_
vocabulary` · `shape_extraction_beats_the_old_regex` · `low_selectivity_
dimensions_are_not_join_keys` · `review_corroboration_uses_resolved_artifacts_
only`

`candidate_tokens_carry_no_domain_vocabulary` **greps the source of
`signals.py`** for `promo|order|checkout|refund` inside the extraction pattern
and stopword set. Adding a new identifier type to the product must require no
change there; the moment domain nouns leak in, the extractor stops being
shape-based and starts being a lexicon that silently rots.

`review_corroboration_uses_resolved_artifacts_only` — a shared *word* is
coincidence; a shared value that telemetry confirmed is a dimension value is
evidence.

### 7 · Instruction quality (6)

`test_fix_prompt_names_the_trap` (`### Do NOT patch <crash site>` present, both
confidences stated) · `test_fix_strategy_matches_the_target_kind` (a `.md`
target's strategy contains **neither** `dereference` nor `null`) ·
`test_unmapped_surface_admits_it_has_no_recipe` · `test_loud_incident_still_
works` · `test_mixed_posture_cluster_reports_its_unexplained_half` ·
`test_single_posture_cluster_claims_no_unexplained_half`

The last pair together prove the unexplained-half report is **conditional**, not
boilerplate a reader will learn to ignore.

---

## `ui/test_triage.py` — 15

`seeded_feed_matches_ground_truth` (the `relevant` flag, used **only** here) ·
`praise_with_surface_term_is_not_signal` · `negation_is_not_signal` ·
`real_bug_reports_are_signal` · `ui_friction_is_signal` · `friction_words_do_
not_hijack_feature_requests` · `abuse_survives_every_veto` · `abuse_does_not_
swallow_spam_or_praise` · `family_is_tagged` · `feature_routing` · `spam_and_
requests_are_vetoed` · `dedup_collapses_reposts_only` · `escalation_threshold` ·
`semantic_hook_is_optional_and_narrow` · `scorer_outage_does_not_block_triage`

`negation_is_not_signal` must include the sentence-boundary case: *"…no
refunds. they are not the same policy"* is signal — the `no` belongs to the
previous sentence.

`abuse_survives_every_veto` and `abuse_does_not_swallow_spam_or_praise` are a
matched pair. Each alone is passable by a broken classifier; together they pin
the boundary.

`scorer_outage_does_not_block_triage` — the optional semantic hook raising must
degrade to keyword triage, not take the pipeline down.

---

## `ui/test_signals.py` — 26

Lifecycle: `dispatch_fires_exactly_once_at_threshold` · `later_complaints_
reinforce_not_reinvestigate` · `resolve_allows_a_fresh_signal` · `features_get_
separate_signals` · `payload_shape`

Extend `payload_shape` through the engine boundary: the returned diagnosis must
contain `social_context` with the synthesized symptom, complaint count,
distinct-author count, families, artifacts, and no more than three exemplars.
Serialize it and assert that no handle/presentation field leaked. This is the
contract that lets a persisted diagnosis explain which consolidated human
complaint caused the investigation.

Dedup: `same_author_repost_dedups_across_ticks` · `identical_text_from_
different_authors_both_count` · `cross_author_dedup_is_available_for_
production` · `distinct_voices_are_kept` ·
`one_loud_author_cannot_cross_corroboration_threshold`

**Two people independently reporting the same thing is corroboration, not
duplication.** The pair above encodes that and its production-mode escape.

Ambiguity: `ambiguous_complaint_joins_the_live_sibling` · `ambiguous_arriving_
first_is_absorbed_later` · `ambiguous_stays_separate_when_two_siblings_are_
live` · `ambiguous_cluster_can_reach_threshold_alone`

Symptom: `symptom_carries_the_searchable_artifact` · `symptom_never_contains_a_
raw_taxonomy_key` · `artifact_extraction_ignores_shouting`

### Three UI guards that exist because each failure shipped

**`test_live_view_keeps_refreshing_through_the_status_gap`** — drive
`work_in_flight()` through the window where the queue has drained but no status
has landed, and assert it stays True. The symptom was a frozen terminal and a
human clicking Refresh mid-demo.

That guard also checks the live source path: `app.py` must render
`events_to_rows(read_events())`, while `build_trace` appears only in the replay
branch. Inspect `Ingestor.dispatch` and assert its callback logs each engine
event before applying `engine_pace`, whose CLI/default process-manager value is
`0.3`. This prevents a later rebuild from replacing the live stream with a
fast batch or a convincing hardcoded simulation.

**`test_every_emitted_event_has_a_terminal_channel`** — grep every `emit(...)`
and `log(...)` string literal out of `engine/pipeline.py`, `engine/correlate.py`, and
`ingest.py`, and assert each has a `_CHANNEL` entry. The symptom was a wall of
unlabeled grey lines that read as gibberish on screen. Pair it with
`test_unmapped_events_are_visibly_unmapped`, which asserts an unknown type
renders its raw name rather than vanishing into anonymous text.

The same guard asserts `stage.3.semantic` maps to `CODE INTEL`, that neither the
live map nor replay trace contains a `SEMANTIC` channel, and that replay includes
both `GREPTILE CACHE` and `semantic/cache`. This prevents UI wording from
turning an honest offline code-intelligence fixture into an apparent live
semantic provider.

**`test_ui_modules_have_no_undefined_names`** — run pyflakes over `ui/*.py` and
fail on `undefined name`. Streamlit raises only on the path a user walks, and
**still serves HTTP 200 with the traceback rendered inside the page** — so
`curl` reports healthy while the view is broken. A `NameError` shipped exactly
that way: a block left outside a fragment still referencing the fragment's local.

Prefer `.venv/bin/python` over `sys.executable` and **record a failure when
pyflakes is missing from both**. The first version of this guard skipped quietly
under the system python3 and was inert for days. *A guard that silently passes
when its tooling is missing is worse than no guard, because it reports green.*

Fold static UI contract checks into this guard as well: the source must contain
the `SocialClues` page title, `What people reported`, `social_context`, and
`Inspect exact machine evidence`, plus styled forensic section markers. Replay
diagnoses must carry the same social-context shape as live diagnoses. These are
deliberately source-level checks because the no-browser harness cannot inspect
Streamlit's rendered DOM.

Assert the diagnosis renderer contains `evidence confidence` for the card,
crash/root rows, and code-evidence detail, while preserving the wire field name
`confidence`. Replay prose must use the same label. This prevents a heuristic
evidence score from being presented as a calibrated probability.

Fix CTA: `fix_request_launches_real_actor_once` · `fix_request_refuses_missing_
or_unsafe_instruction` · `fix_status_keeps_terminal_live_and_maps_actor_events`.
Mock `Popen` and assert the command names the real `agent.py`; no required test
may call OpenAI. The emitted-event guard also scans `agent.py`, every
`actor.*` event maps to `FIX AGENT`, and the static UI source contains
`Fix issue`, `request_fix`, plus the explicit no-push/no-PR help text.
`actor.verify` is the exception: it maps to `FIX PROOF`, and `agent.py` must
contain real `git status --short` and `git diff --stat` subprocess arguments.
Also statically guard that full `run.sh restart` calls a cleanup function scoped
to `refs/heads/fix/socialclues/*`; unrelated branches must never be reset or
deleted.

Wave I2 adds a fixture-mode launch test: refuse a missing fixture, append
`--fixture-replay` when it exists, and map `actor.fixture` to `FIXTURE`.
Required tests never call OpenAI or mutate canonical ACME Shop.

---

## Acceptance

```bash
set -a; . .env; set +a; export ACME_SHOP_PATH=../acme-shop
./run.sh test
```

`✓ all 42`, `✓ all 15`, `✓ all 23` — 80 tests, exit 0, no skips.

Then break it deliberately and confirm the suite catches it: change
`patch_target` in `correlate.py` to select `max(confidence)` and re-run.
`test_fix_targets_root_cause_never_crash_site` and
`test_crash_site_is_separate_and_scores_higher` must both fail. Revert.

**A suite that cannot fail proves nothing.** Verify it fails before trusting
that it passes.

---

## Also create: `socialClues/verify_samples.py` + `socialClues/demo-samples.md`

`demo-samples.md` is the list of complaints a presenter types live, each with
the feature it is documented to route to. `verify_samples.py` parses that
markdown, runs `classify()` on every sample, and fails when any one stops
routing where the doc says it does.

Parse the doc rather than duplicating the strings in Python. Two copies drift,
and the copy the presenter reads from is the one that matters.

```python
KNOWN = {"checkout/promo", "checkout/totals", "checkout/payment",
         "checkout/*", "account", "shipping"}
```

Assert each documented feature is in `KNOWN` too — a typo'd feature key in the
doc would otherwise "pass" by never matching anything.

Run it after any change to `ui/triage.py`. **A sample that silently stops
routing where the doc says it does is a demo that fails on stage** — with the
presenter reading the line aloud as it fails.

```bash
python3 verify_samples.py     # every sample routes as documented
```
