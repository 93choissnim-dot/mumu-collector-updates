# Preventive Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent predictable interruption and stale-state failures before user reports.
**Architecture:** Strengthen existing transaction/observation/dispatch boundaries; preserve guarded route semantics.
**Tech Stack:** Python, unittest, Windows/PyInstaller, GitHub Actions.
**Spec:** docs/superpowers/specs/2026-10-25-preventive-reliability.md

## Global Constraints
- No blind retries, payment permission, or uncertain-record reset.
- Preserve original data on storage failure; guild donation stays 0/max.
- User has approved implementation and deployment; no additional approval round.

## Review Focus
- Multiple live ledger instances must not erase pending inputs.
- Deletion/corruption after opening records must halt before writes.
- Pause/resume during capture must not publish obsolete observations.
- Stop/update raised at status callback must prevent a new account dispatch.
- Recovery/identity errors must not dispatch work to a changed endpoint.

### Task 1: Daily record transactions
Files: daily_state.py, validate_v094_prevention.py.
Interfaces: DailyLedger reads/mutations share path_lock; ManualQuestLedger inherits reload.
- [ ] Test two writers, externally changed/deleted/corrupt file, checkpoint and begin_run preservation.
- [ ] Run `python -m unittest validate_v094_prevention.LedgerBoundaryTests -v`; expect failing stale data assertions.
- [ ] Add locked reload and existence tracking; bind each checkpoint to a single day; retain atomic save.
- [ ] Run focused storage and new tests; expect OK; commit.

### Task 2: Observation and dispatch interruption
Files: collector.py, fleet_runner.py, run_support.py, validate_v094_prevention.py.
Interfaces: RunControl.generation, checkpoint; verify_identity callback, no signature breaks.
- [ ] Test pause/stop inside capture/recognition; no stale callbacks, result or input.
- [ ] Test stop/update during fleet_status, pause/resume before dispatch, recovery-cycle identity rejection.
- [ ] Run new classes; expect failures proving missing gates.
- [ ] Recheck generation/stop after capture and recognition; dispatch checkpoint after event; identity at cycle boundary.
- [ ] Run relevant prior stop, recovery, fleet suites; expect OK; commit.

### Task 3: Whole failure-family simulations and release
Files: validate_v094_prevention.py, frozen_entry.py, version.py, build docs and release metadata.
- [ ] Exercise actual claim acknowledgement loss, storage fsync/replace failure, midnight donation pending, repeated popup and update collisions using existing fixtures.
- [ ] Include new tests in source and frozen health checks.
- [ ] Run all existing headless validation modules; expect all pass.
- [ ] Fresh reviewer checks whole diff; fix important findings with regression tests.
- [ ] Build Windows v0.7.94, validate real update/restart/rollback, publish pinned bytes, verify both public feeds.
