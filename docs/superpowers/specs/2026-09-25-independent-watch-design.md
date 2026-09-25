# Independent game recovery v0.7.61

User approved background recovery independently of collection, with a footer switch, preserved schedules, paused-input exclusion, bounded restarts and no emulator restart. Follow-up supplied exact download prompt, offline reward confirmation and footer flicker diagnosis. Existing standing authorization covers implementation, testing and publication without repeated stage approvals.

Architecture: one device lane for collection/read-only inspection and idle watcher. The fleet scheduler calls the same watcher while waiting, without altering next-due times. Watch scans have independent cancellation plus parent pause/generation guard. Only enabled profiles, exact live instance identity, Android HOME and absence of either supported game process permit launch. Preserve observed Play/OneStore edition; ambiguous installations require manual identification. Check every 15 seconds, at most two launches per profile in ten minutes; failures back off 60 seconds. Closing/update/readonly must not race launches.

Startup: authorize only exact download notice plus active confirmation, fresh recapture and package checks. Single confirmation, then bounded five-minute download wait. Existing recognized offline reward confirmation must clear before ready; uncertain confirmation does not repeat. No login/auth/other prompts.

Footer: stable state must not unmap/remap controls on every poll. New watch status/switch remain visible at compact size. Private diagnostic ZIP/full frames stay local; recognition atlas contains only anonymous generic prompt and button controls.

Verification: real Android command-boundary fakes for identity, cancellation, wrong edition, budget, download/offline confirmation; scheduler due-time invariance; repeated native Tk polls without layout remap; full release suite and Windows source/folder/single EXE/update gates. Actual user game recovery remains unverified until new release feedback.
