# v0.7.75 reliability and speed

User approved all four audited improvements plus a whole-flow speed review and standing deployment. Existing flows are retained: fix false recovery status, persist attributed store reward evidence before dismissal, make idle recovery cooperative, avoid redundant store navigation. Measure recognition costs across recorded/synthetic pages; optimize immutable reference computations only where useful.

Constraints: fresh input capture, identity/foreground/stop/pause guards, duplicate input reservations, free-only summons/store, all red-ruby guild donations, dungeon challenge-count claim rule, five-day diagnostics remain. No historical unknown reward is automatically confirmed. No raw account screenshots published.

Recovery poll returns True only for verified normal screen, False for no recovery, None for in-progress; it shares deadlines, confirmation sets and stable-frame evidence across calls. Blocking collection recovery uses the same logic with waits. Timed-out startup remains unresolved until verified normal screen. One poll must not sleep through loading. Command timeouts remain bounded but cannot guarantee zero scheduler latency on an unresponsive emulator.

Store persists task/day/input-request-bound proof immediately before a freshly verified reward dismissal; restart uses only matching proof, and storage failure sends no dismissal. Visible store card in selected tab skips tab reset/scroll; fallback search remains bounded.

Review decisions: preserve fresh captures and animation waits; no blanket speedup percentage. Fixed clock-domain handoff and HOME/alive continuation after independent review. Windows/full-suite/public-feed gates run separately.
