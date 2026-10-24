# v0.7.94 preventive reliability

User authorized implementation and deployment of five predicted failure families: connection loss after input; termination during saving; identity/manual-screen changes during recovery; midnight/loading/serial popups; stop/resume/update collisions.

Approach: inject these failures into deterministic tests against the existing guarded input and durable record paths. Preserve proven protections; change code only for concrete uncovered behavior. Do not add blind retries, blanket record resets, payment permission, or arbitrary screen-freeze restarts. Keep guild donation 0/max.

Design: daily ledger operations reload under their existing shared lock, preserving current disk changes and rejecting deletion/corruption. A collector observation interrupted by stop/pause is discarded before callbacks or completion decisions. Fleet scheduler rechecks stop/pause/update immediately before dispatch after status callbacks. Recovery revalidates the selected emulator before entering each resumed collection cycle. Existing free/paid uncertainty, midnight, popup and rollback gates get an explicit combined scenario regression suite.

Limits: emulator identity is verifiable; in-game character identity is not independently readable with the existing recognizer. No claim of automatic character-switch detection or real multi-day game soak. Existing 5-second pixel-age guard bounds ordinary manual-screen races; capture cannot be atomic with a player's simultaneous touch.

Release: v0.7.94, source and frozen suites; Windows actual update/restart/rollback; reviewed source hashes and public feed verification required.
