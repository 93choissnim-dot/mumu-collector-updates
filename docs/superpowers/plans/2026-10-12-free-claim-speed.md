# Free claim speed v0.7.88 implementation plan

> Execute inline with superpowers:executing-plans; final independent review.

Goal: deploy the two optimizations approved by the user, preserving input safety.
Architecture: reuse two recent observations only for farm/ranking free claim prechecks; retain the existing post-reservation fresh guard. Skip the extra one-second wait only for twice-confirmed empty extra-task buttons.
Spec: user-approved items 1 and 2 from the 2026-10-12 simulation research. No automatic retry or learned timing.
Tech stack: Python 3.12, OpenCV, MuMu ADB, Windows packaged EXE.

## Constraints and review focus
- Whitelist farm/claim/ready_farm and ranking/claim/x_rank_active only.
- Observations expire after 0.75 seconds and must match the current run generation and last screen identity.
- Storage/evidence may block: a fresh capture must follow both before dispatch.
- Account change, stop, pause/resume, conflicting markers and changed pages must prevent input.
- Uncertain transport remains pending, with no automatic repeat. Ordinary, paid and point-based input retains both captures.
- Empty reuse requires two consistent observations; unknown, active, conflicting, stale and single observations retain the one-second wait.

## Task 1: protected free precheck reuse
Files: input_safety.py, free_claim.py, validate_v088_speed.py.
- [ ] Write regressions for capture reduction and all safety conditions above.
- [ ] Run python -m unittest -v validate_v088_speed; observe capture-count regression fail on v0.7.87.
- [ ] Add optional free_claim context to verified_tap, supplied only by free_claim_tap. Reuse through confirmation_seed with the whitelist; keep the rest of verified_tap intact.
- [ ] Re-run new and prior input/lifecycle regression suites; expect PASS.

## Task 2: confirmed completion wait
Files: extra_collector.py, validate_v088_speed.py.
- [ ] Test ranking/worldboss/excavation completion, unknown/single/conflicting/stale observations and retained uncertain-input wait.
- [ ] Observe the confirmed case fail with the existing unconditional one-second pause.
- [ ] Use confirmation_seed after post_input; omit pause(1) only with count >= 2 for the same page and empty-only marker.
- [ ] Run the whole non-UI regression suite; expect PASS.

## Task 3: package and publish
Files: frozen_entry.py, version.py, changes, release recipe and CI workflows.
- [ ] Include validate_v088_speed in source/frozen validation and free_claim_speed_v088 health key.
- [ ] Independent review; fix material findings with regression tests.
- [ ] Build Windows source, folder and single EXE; test update/restart/rollback and previous helper update.
- [ ] Publish only a successful exact-commit build with verified bytes and all existing health gates.
- [ ] Verify both public feeds report v0.7.88, preserve handoff history.

Ruling: existing user approval authorizes implementation and publication; no new approval checkpoint is needed.

## Verification ledger

- Baseline input/lifecycle/extra suite: 30 tests PASS.
- New regression RED: 17 tests, 6 expected failing subcases for capture reduction and skipped wait; no setup errors.
- After implementation: 127 focused tests PASS; independent review: 53 tests PASS, no blocking findings.
- Final source simulation: 240 paired cases, all completed with exactly one input, no wrong clicks. Constant transport: 134 faster / 26 same / 0 slower. Variable transport: 68 faster / 10 same / 2 slower; worst +1.266253 s, overall average -0.305598 s.
- Ruling: preserve the existing 0.75 s observation freshness bound. In two variable-delay cases, earlier dispatch shifts captures into a slower phase, expiring consecutive evidence and causing extra confirmation captures. Do not expand safety expiry or claim universal speedup. Cost: rare slower completion checks remain; this is the next measured optimization candidate, not a correctness failure.
- Existing ExecutionTrace already records per-task duration/reasons and aggregate capture/recognition/wait timing. No duplicate telemetry added.
