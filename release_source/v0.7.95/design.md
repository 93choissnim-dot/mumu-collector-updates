# Guild donation counts v0.7.95
User asks for 0회 / 무료 기부 / 4회 and no ruby budget management.
Use an explicit mode field; migrate old 0 to free and old maximum to four.
Off sends no donation. Free sends only free. Four allows one free plus three paid inputs per KST day and account. Existing attempted/verified records and unknown-input guards persist across reruns. Count selection itself authorizes the route; training consent stays unchanged.
Keep legacy budget helpers for compatibility with old integrations; the application fleet dispatch always supplies the new mode.
Verification: real-route synthetic tests, profile merges/migration, Windows settings UI, full regression suite and packaged EXE lifecycle.
