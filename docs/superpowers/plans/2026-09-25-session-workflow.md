# Session Workflow Implementation Plan

> For agentic workers: use superpowers:executing-plans inline; one fresh final reviewer.

**Goal:** Ship v0.7.60 with a clear current-run workflow and bounded game-exit recovery.
**Architecture:** Pure session classification + existing journal/ledgers; UI mixin; device-scoped game recovery integrated into existing run recovery.
**Tech Stack:** Python 3.12, customtkinter 5.2.2, OpenCV, Windows PyInstaller, GitHub Actions.
**Spec:** docs/superpowers/specs/2026-09-25-session-workflow-design.md

## Global Constraints
No paid purchase; no uncertain resource replay; cancel before every input including app launch; read-only verification performs no launch; profile/day scoped; no private image publication. Native execution and publication are already authorized. Source assembly uses pinned v0.7.57 plus complete cumulative patch.

## Review Focus
- Mixed safe/held continuation must not erase unresolved journal entries.
- Starting regular tasks must retain unfinished daily jobs and vice versa.
- Launch race with pause or user switching to another app must send no launch.
- Crash immediately after irreversible input must not replay it after reconnect.
- New run, changed profile and KST midnight must never display previous success as current.

### Task 1: session data and continuation
Files: session_workflow.py (new), run_journal.py, fleet_collection.py, ui_state.py; validate_session_workflow.py (new).
- [ ] Write behavior tests: journal begin preserves unrelated unfinished tasks; resume preserves completed/held; pending requests classified held; old day/profile excluded; regular-only automatic run; current unstarted row hides prior success.
- [ ] Run `python -m unittest -q validate_session_workflow` RED.
- [ ] Implement `task_scope(player, scope)`, `continuation(data, players, day=None)`, `session_entry(task, record, previous)`, extend journal entries and preservation. Worker rechecks continuation before execution and records snapshot/reason in journal.
- [ ] Run new tests and relevant existing compact/fleet/history tests GREEN; stage cumulative patch and commit.

### Task 2: bounded game recovery
Files: game_recovery.py (new), adb_device.py, run_support.py, fleet_collection.py; validate_game_recovery.py (new).
- [ ] Test real recovery orchestrator using fake external Android responses: exact launcher/no process required; other app and alive process refuse; cancelled no input; unknown page times out with no taps; at most two launch attempts; same package stable ready; same-run pending retained and completed rooms excluded.
- [ ] RED tests, then implement `GameRecovery(device, vision, stop, verify_identity, log, progress)` and `recover()` returning bool for proven supported closure, integrate worker startup and cycle transport recovery via explicit optional argument.
- [ ] Treat am start as an input under RunControl guard. Recheck identity, foreground and process before launch. Never bind unknown after launch.
- [ ] GREEN recovery plus existing operations/run-control/ADB/input-safety suite; stage and commit.

### Task 3: desktop workflow
Files: ui_workflow.py (new), ui_dashboard.py, ui_roster.py, ui_history.py, app.py, ui_player_settings.py; validate_workflow_ui.py (new).
- [ ] Integrate shared continuation model with idle footer button and preview; executing/held rows distinguish account and reason. Safe-only button revalidates at worker boundary.
- [ ] Scope selector Regular / Daily / All drives one-time execute; automatic control labels regular-only and disables on daily-only scope. Expose free daily selection in dedicated settings section.
- [ ] Compact header, readable supporting text, current run labels and last-success time separation, active account indicator. Preserve run summary after cancellation.
- [ ] Windows UI tests exercise footer button visibility, scope routing, current waiting state despite old success, busy stop/pause layouts and screenshot bounds at 100/125/150%.
- [ ] Run applicable headless tests; stage and commit.

### Task 4: review and release
- [ ] Review diff in fresh context using requesting-code-review. Fix important findings with reproductions.
- [ ] All official release tests; compile/static patch integrity; Windows desktop/folder/single EXE and v0.7.28 updater recovery. Inspect synthetic screenshots.
- [ ] Publish only exact successful build/commit; compare direct EXE to update archive; confirm both public feeds v0.7.60.

## Evidence and decisions
- Remote main 9d6d208d0e04026c7fbbd5ceed5b6ffb5de36d3a matches tested v0.7.59; local isolated worktree chanki-v060 and private full-source copy app-v060.
- Ruling: no repeated spec/plan approval gate — user's explicit autonomous all-work authorization and standing preferences override skill handoff prompts.
