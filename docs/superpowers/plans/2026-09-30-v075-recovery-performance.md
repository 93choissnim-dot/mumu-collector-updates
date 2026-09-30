# v0.7.75 Implementation Plan

> Execute natively with test-driven-development and one final requesting-code-review. Standing user approval covers implementation and deployment.

**Goal:** Apply four audited reliability/speed fixes and measured shared-recognition optimizations.
**Architecture:** Cooperative recovery uses the existing serialized device lane. Scoped durable reward evidence extends existing daily records. Immutable image references can be cached, observations never reused across input.
**Tech Stack:** Python, OpenCV, unittest, Windows PyInstaller.
**Spec:** docs/superpowers/specs/2026-09-30-v075-recovery-performance.md

## Global Constraints
Preserve all input guards, bounded retries, free-only purchases, guild rules, and five-day diagnostic policy.

## Review Focus
- Interrupted polling across new recovery objects, stop/pause and changed foreground.
- Expired recovery must not clear failure on unknown pixels.
- Reward belongs only to the pending current task/day/request; no inferred legacy completion.
- Storage failure before dismissal must preserve reward screen.
- Cached references must keep all states, buttons, diagnostics and negative recognition equivalent.

### Task 1: Recovery polling and truthful status
Files: game_recovery.py, game_watch.py, ui_game_watch.py, validate_v075_recovery.py.
Interface: GameRecovery.poll() -> bool|None, same recover() blocking API; GameWatch.perform(...,incremental=False). Persist stable observations and startup unresolved state; never sleep in poll.
- [x] RED timeout/unknown status, poll continuation/fresh controls, unchanged network button no-repeat, scheduled execution while other instance loads.
- [x] GREEN shared wait_ready single-step path and status handling. Focused old/new recovery suite.

### Task 2: Store evidence and navigation
Files: free_daily_actions.py, collector.py, validate_v075_store.py.
Interface: optional before-dismiss callback invoked by verified input; store proof bound to current request id and day.
- [x] RED interrupted dismissal then process restart, unrelated/stale proof, failed disk write, already-visible card without scroll.
- [x] GREEN persist proof before closing, resolve matching proof on restart, selected visible target fast path; focused store/safety suite.

### Task 3: Whole-flow speed review
Files: measured vision reference caches plus validate_v075_performance.py.
- [x] Profile representative facility/menu/boss/guild/dungeon/store/summon/event/overlay/unknown frames; inspect action waits and capture/discovery loops.
- [x] RED equivalent outputs with bounded repeated preprocessing; GREEN immutable cache only. Record before/after median recognition timings; retain animation/combat waits.

### Task 4: Release
- [ ] Full local suite; fresh read-only branch review; fix findings with regressions.
- [ ] Assemble cumulative v0.7.75 patch, manifest, health checks, workflow. Build Windows, inspect reports; publish verified build and check both public feeds.

Review decisions: preserve fresh captures and animation waits; no blanket speedup percentage. Fixed clock-domain handoff and HOME/alive continuation after independent review. Windows/full-suite/public-feed gates run separately.
