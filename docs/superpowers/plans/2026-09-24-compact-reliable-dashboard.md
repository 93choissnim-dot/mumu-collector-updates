# Compact and reliable dashboard implementation plan

Goal: apply the approved compact layout and all reliability/status improvements, then ship v0.7.59.
Design approved in conversation: compact default and remembered size; accurate task status and counts; priority issue visibility; contextual connection status; clear run controls; subtle artwork; partial completion; bounded end review; reason evidence; safe recovery; resume unfinished work; preflight checks; final summary.
Constraints: preserve v0.7.58 recognition fixes; no paid purchases/donations; no uncertain same-run resource retries; cancellation before input; private diagnostics never committed; Windows full regression and EXE update gates before publish.
Execution: inline, user requested autonomous completion and no intermediate approvals.

- [x] Task 1: pure UI summaries, compact geometry and layout, remembered size, contextual status and safe controls. Test geometry clamping, priority without execution mutation, partial and paid-excluded results, distinguish inspected from successful counts. Use validate_compact_reliability plus Windows real-widget bounds at 680x800 and scaled displays.
- [x] Task 2: durable scope/day-bound unfinished-run journal; no re-running confirmed results on resume; bounded final review using same collector and existing fresh-input guards; detailed completion metadata and private diagnostics. Test stopped/unstarted tasks, stale/account-changed checkpoints, corrupt journal, pending-input exclusion and no duplicate review, review-only guard, results aggregation. Existing transport/stall recovery is retained and tested.
- [x] Task 3: free-only guild donation and explicit paid exclusions in step records. Reproduce paid screen path before change; preserve historical pending requests and require fresh confirmation for free input.
- [ ] Task 4: full regression, fresh code review, Windows UI screenshots, frozen EXE and updater checks. Stage changed files over pinned v0.7.57 source including all v0.7.58 changes, build draft, verify exact tested commit/bytes then publish and check both live feeds.

Review focus: same-run uncertain inputs; stop between review and input; stale/mismatched resume scopes; small/DPI-scaled windows; truthful aggregate vs step completion.

Evidence/decisions:
- Baseline exact pinned source matches all files except generated release.json. Local broad discovery ran 827 tests with one legacy fixture setup error (validate_recovery.FarmRegression missing fixtures/farm_reported.png); official Windows module list excludes that legacy test. Use official full module list, retaining all 827 release checks.
- Existing environment binding already checks package, screenshot dimensions and identity; retained and surfaced preflight status. Existing transition timeout, safe navigation recovery and transport recovery retained.
- Display issues sort first; execution route remains unchanged; rows stay stable during running, with an active/issue banner so a moving click target is avoided.
- Final pass only retries failed/unrecognized tasks with no pending action or blocked step; uncertain requests remain unresolved and are reported, never rearmed.
- Source contained active ruby-donation code despite handover prohibition. Removed automatic paid branch; legacy uncertain donation evidence remains untouched without game completion proof.
- Window setting stores logical dimensions, validates saved input, clamps to work area; compact header gets a separate action row to avoid truncation.
- Resume is explicitly scoped by configured account and KST date; the app cannot detect an in-game character change within an unchanged package automatically. Existing account profile is the boundary.
- Fresh code review found empty-profile tooltip crash, uninitialized daily scope on interrupted fleet, and explicit retry permission leaking into final review. Each reproduced RED then fixed GREEN in validate_compact_reliability. Daily scopes initialize before journaling all planned accounts; final pass removes explicit reinspection permission.

- Local official regression after reviewer fixes: 843 checks passed. One additional free-key progress test passed with all 17 focused tests. Windows GUI suite passed on 94070e58ced14a7c7c2dc55f4a0e5ce897664554; earlier failure was a fixture inheriting compact startup selection, corrected by explicitly resetting the roster view.

- Windows build 36016574206 passed all 844 regression tests, source/folder/single EXE GUI health, update/restart/rollback using v0.7.28, and upload byte verification. Reviewed synthetic compact 680px, paused and empty screenshots; text and actions fit. Publication pins this exact tested source commit.
