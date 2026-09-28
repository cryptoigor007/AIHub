# AIHub v3.7.0 — CHANGES-SUMMARY (post-audit fixes)

## Critical fixes
1. `_notify_owner` — Path flags for throttle (was broken str key)
2. `prompt_once` on OpenCodeClient — real one-shot for autoname
3. BotDialog stop — set `_running=False` without broken event loop
4. `get_agents` — `model_copy(deep=True)` no live mutation
5. UI: change_model / answer_question / fork / revert actions
6. UI: kill switch via POST /api/settings
7. UI: mobile long-press 520ms
8. Foreign Tailscale Serve — do not touch other ports
9. VERSION fallback 3.7.0; mark CSS; settings.network_mode/port

## Tests
122 passed, 17 skipped

## On Mac
./scripts/check_once.sh
