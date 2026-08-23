# I1 — Customer-owned operational learning flywheel

Run after all selected H extensions pass. Read `prompts/00-conventions.md`
first. This wave changes the product boundary from incident resolution to
verified operational learning without turning SocialClues into a trainer.

## Files

Create or modify only `ui/learning.py`, `ui/app.py`, `ui/runtime_bridge.py`,
`ui/seed_data.py`, `ui/test_learning.py`, and `prompts/README.md`.

## Outcome contract

Add a third UI view, **Learn**. Join a persisted Diagnosis to an append-only
outcome with independent fields for `resolution` (`accepted | partial |
rejected`), `patch_accepted`, post-deployment `customer_verified`, durability,
unresolved failure families, executor, external reference, and notes. Persist
live records to `runtime/outcomes.jsonl`.

A passing test or merged patch is not customer verification. Partial outcomes
must retain every unexplained family from a mixed-posture cluster.

Prefill every outcome field when a diagnosis is selected so the replay does not
require improvised text. Use the completed fix branch or fixture in the
PR/incident reference and concrete verification results in outcome evidence.
The promo diagnosis defaults to `partial`, retains unresolved `abuse`, and does
not claim customer verification or durability. The assistant diagnosis defaults
to accepted, customer-verified, and durable with the field reproduction and
19/19 groundedness evaluation summarized. Give each diagnosis distinct widget
state so switching selections loads and preserves the correct draft.

## Portable export

Export `outcome-ledger.jsonl`, `training-examples.jsonl`, and `manifest.json`.
They may feed customer evaluation, retrieval, ranking, or post-training
adapters. SocialClues selects no trainer, launches no training job, hosts no
customer model, and makes no deployment decision.

Only an accepted, durable, customer-verified outcome may set
`use_as_positive=true`. A rejected outcome removes the proposed root cause and
patch target from the expected answer. Partial outcomes are boundary/negative
data, never silent positives.

## Two-point customer-cloud simulation

In the replay UI, add an explicitly labeled **simulated Modal learning job**
using the two seeded outcomes. Treat Modal as one example of infrastructure the
customer supplies, never as a platform dependency or exclusive integration.
The simulated job validates the records, counts accepted/partial/rejected
labels, and emits a downloadable `calibration-report.json` candidate.

The candidate may compare mean diagnosis confidence with the durable accepted
outcome rate and show a proposed calibration offset for explanatory purposes.
It must set `applied_to_production=false` and block promotion below a minimum of
50 verified outcomes. Do not claim that two records fine-tuned a model, learned
reliable weights, or changed the production confidence formula. The UI must say
that customer infrastructure ran the simulation and that no model or policy
was deployed.

## Future Modal orchestration boundary

Generate at least 50 deterministic ACME Shop-shaped historical outcomes marked
`synthetic_historical_demo`, then append the two `recorded_fixture_outcome`
rows. Use these to demonstrate the input, held-out evaluation, scoring, and
versioned artifact contract that a future customer Modal adapter will consume.
Do not authenticate, submit a cloud job, or expose a live-cloud UI control in
this wave.

Synthetic history demonstrates orchestration and artifact contracts, not model
quality. The returned policy must remain `demo_candidate_only` and
`applied_to_production=false`; synthetic volume can never satisfy a production
promotion gate. Modal is an optional customer adapter, while JSONL exports and
the learning schema remain vendor-neutral. A real Modal adapter is deliberately
deferred until it is separately configured and authorized.

## Replay and tests

Seed one partial promo result whose availability fix leaves abuse unresolved,
and one durable customer-verified assistant fix. Plain-script tests assert
unresolved-family preservation, positive-example gating, rejection safety, and
parseable vendor-neutral exports with `training_runtime=customer-supplied`.
Also assert that the two-point Modal artifact contains one durable positive and
one partial outcome, is marked as a simulation, and is blocked from promotion.

## Definition of done

The demo ends with a customer-owned learning artifact, not “PR opened”:
report → incident → diagnosis → resolution → verified outcome → customer
training/evaluation infrastructure.
