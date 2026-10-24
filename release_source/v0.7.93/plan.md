# v0.7.93 Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove remaining record-related stalls and improve recovery observability.
**Architecture:** Keep transactional input reservation, introduce opt-in scoped ledger validation, fresh-continuation eligibility, observational watch checks and bounded incident evidence. Preserve paid guards and sequential input ownership.
**Tech Stack:** Python 3.12, unittest, existing OpenCV/Tk Windows packaging.
**Spec:** docs/superpowers/specs/2026-10-25-reliability.md

## Global Constraints
No record deletion or blind paid replay. Whole-file unreadability remains a global halt. No forced restart for unknown images. Evidence last 12 incidents / 24 MiB. Keep prior updater verification gates.

## Review Focus
- Resume permission versus reconnect permission: test a new failure cannot rearm.
- Corruption in unrelated versus selected account: preserve raw bytes/values and block selected corruption.
- Stop/update between jobs: no scan after cancellation.
- Unknown versus recognized static sleep: no false normal or force restart.
- Repeated incidents versus original evidence: bounded history without overwriting same incident.

### Task 1: Fresh continuation and bounded recognition hold
Files: session_workflow.py, recognition_backoff.py, validate_v089_recovery.py.
- [x] Add tests for fresh free continuation, mixed paid/free slots, pending protection, invalid cooldown; run red.
- [x] Add held_reason(...,fresh_run=False), use only in continuation. Reuse exact free-request eligibility; invalid recognition timer permits observation, never settles input.
- [ ] Run relevant suites and commit.

### Task 2: Account record isolation
Files: daily_state.py, action_state.py, run_journal.py, session_workflow.py, fleet_collection.py, retry_resolution.py, validate_v089_recovery.py.
- [x] Add real-file tests: unrelated malformed account retained through successful updates; selected corruption blocks, malformed root blocks; run red.
- [x] Add ScopedLedgerError and opt-in isolated/scoped reads. Preflight each fleet account; skip only scope corruption with explicit reason, preserve global storage failures.
- [ ] Run record/session/fleet suites and commit.

### Task 3: Watch status and between-account checks
Files: game_recovery.py, game_watch.py, fleet_runner.py, fleet_collection.py, validate_game_watch.py.
- [x] Test unknown foreground warning, known sleep, between-account hook, stop/update cancellation; run red.
- [x] Observe foreground screen in incremental watch; warnings retain per-account cause. Add optional between hook on the same device lane; no changes to input budget.
- [ ] Run game/watch/fleet suites and commit.

### Task 4: Bounded incident evidence and release
Files: diagnostics.py, validate_v089_recovery.py, version.py, build scripts, usage/changelog.
- [x] Test per-run same-step first failure, next-run retention, bounded export and no private publication; run red.
- [x] Save atomic incident ZIP copies, bounded retention and export prioritization. Update version/docs.
- [ ] Run full suites, independent review, Windows build and publish; verify public feeds.
