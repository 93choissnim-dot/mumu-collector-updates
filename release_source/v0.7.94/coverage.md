# v0.7.94 preventive coverage

| Failure family | Production boundary and evidence |
| --- | --- |
| Click dispatched but acknowledgement lost | `FailureFamilyTests.test_free_claim_lost_acknowledgement_reconciles_after_reload_without_extra_click`: actual free-summon route, durable request, recreated ledger, lower counter confirms with one input. Existing v080 lifecycle and v090 spending cases preserve uncertain paid requests. |
| Save interrupted or disk unavailable | Child process exits at fsync/replace with old pending bytes intact. New live-ledger tests preserve concurrent account records and reject deletion/corruption. Existing v071 storage suite covers disk full, locked replacement and cleanup. |
| Manual screen / emulator change during recovery | New observation generation tests reject pause-crossing captures; new identity gate rejects changed selected emulator before collection. Existing v070 final input tests reject changed page/button after reservation; run-controls rejects a different app on resume. |
| Midnight, long loading, serial popups | New single-checkpoint date test, cross-midnight unresolved payment with another writer, bounded network polling and three-click persistent overlay test. Existing v090 spending tests test midnight during reservation and final capture. |
| Stop/resume/update collisions | New scheduler status-boundary stop/update and update-while-paused tests; new stop-during-capture/recognition tests. Existing v090 update suite tests deferred apply and authorization, v090 stop tests queued work cancellation. |

Actual tests use simulated game screens/transports. The save-termination test kills a real child process. Windows release gate runs actual built EXE health, update, restart and rollback validation. This is not a multi-day live-game soak and does not establish live in-game character identification.

No unrelated behavior changes: no new paid spending allowance, no blind retries, no wiping previous pending records, no unknown-screen force restart.
