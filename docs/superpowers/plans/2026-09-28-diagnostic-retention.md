# Diagnostic Retention and Recovery Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement each bounded task. Parallel independent domains are explicitly authorized by dispatching-parallel-agents.

**Goal:** Retain five KST calendar days of execution summaries, separate resolved evidence from active diagnostic failures, and explain unresolved inputs and failures without weakening replay guards.
**Architecture:** Existing trace, ledger and overview pipelines remain authoritative. Diagnostic evidence lifecycle is advisory and file-scoped; it never clears resource ledgers. Read-only outcome helpers supply consistent reasons to trace, history and UI.
**Tech Stack:** Python, unittest, JSON/ZIP, existing Windows/Tk application and GitHub release workflows.
**Spec:** User-approved in-chat requests on 2026-09-28: apply proposed pending guidance, failure-reason propagation, confirmed-success diagnostic cleanup, bounded ZIP; keep five days rather than thirty; ship verified update.

## Global Constraints
- Five days includes today using Asia/Seoul dates.
- No automatic replay, spending, or clearing unresolved action/daily ledger entries.
- Cleanup requires later verified success for matching account/task; old or ambiguous identity is not evidence of resolution.
- Diagnostic maintenance failures cannot break a completed game operation.
- User data and screenshots must not enter the public source repository.
- Preserve existing Windows EXE/update/restart/rollback gates.

## Review Focus
- Wrong-account or old-run success must not resolve another failure.
- Missing/corrupt metadata and symlinks must fail safely.
- Missing pending timestamps need honest text, not invented dates.
- Failure callbacks arriving after result callbacks must retain reason in persistent summaries.
- ZIP budgets must retain machine-readable current state and explicitly list omitted evidence.

### Task 1: Five-day execution archive
**Files:** run_archive.py, validate_run_archive.py.
- [x] Change boundary regressions from 30 to five KST days; observe failure.
- [x] Set RETENTION_DAYS=5; verify existing archive and export tests (22 passed with update diagnostics).

### Task 2: Diagnostic evidence lifecycle and export limits
**Files:** diagnostics.py, optional diagnostic_retention.py, validate_v069_diagnostics.py.
**Interfaces:** Existing save_collection_failure/export_diagnostics/save_execution_trace; scope supplied on trace.account_scope and serialized as account_scope by task 3.
- [x] Reproduce retained resolved evidence, cross-account protection, expiry, stale legacy metadata, and total ZIP budget in synthetic disk tests.
- [x] Track matched verified-success resolution, omit resolved evidence from normal export, delete resolved evidence after five days, retain unresolved resource records and their state.
- [x] Bound ZIP payload and prioritize current state/newest failures; report omissions and classification in manifest.
- [x] Run focused regression tests and report exact changes for integration.

### Task 3: Failure reasons and pending guidance
**Files:** fleet_collection.py, execution_trace.py, today_overview.py, optional focused helper, validate_v069_outcomes.py.
**Interfaces:** Serialize trace.account_scope; diagnostics lifecycle reads this field. Do not edit diagnostics.py.
- [x] Reproduce blank outcome/failure reasons and pending info lacking date/action guidance.
- [x] Propagate captured issue reasons to run journal/history/trace, including after-result callback order; do not leak reasons across tasks/runs.
- [x] Present request timestamp, task/slot and useful safe next action for pending records; retain all replay protections and screen rechecks.
- [x] Run focused regressions including missing timestamps and independent scopes.

### Task 4: Integration and release
**Files:** release_source/v0.7.69, build/publish workflows, frozen_entry.py, version.py, release notes.
- [x] Review combined changes independently; fix important issues.
- [ ] Include new tests in Windows and packaged full-health gates; run full local regression suite once integrated.
- [ ] Prepare cumulative pinned source patch, verify hashes and remote tree before updating main.
- [ ] Run Windows validation, publish only tested bytes, verify both public update channels.
