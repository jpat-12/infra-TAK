# infra-TAK v0.2.5-alpha

Release Date: March 2026

---

## Highlights

- **MediaMTX web editor — stale overlay self-heal** — `Patch web editor` now always syncs `mediamtx_ldap_overlay.py` from the current infra-TAK repo into `/opt/mediamtx-webeditor` before restart. This fixes existing installs where an older overlay file was still injecting legacy UI logic (duplicate Private/Share controls and broken External Sources layout).
- **Guard Dog — Updates monitor recovery** — `↻ Update Guard Dog` now reinstalls `takupdatesguard.service` and `takupdatesguard.timer`, runs `systemctl daemon-reload`, and enables/starts the timer. This fixes installs where the Updates monitor stayed red because the timer unit was missing.
- **Guard Dog UX** — Update button label is clearer (`↻ Update Guard Dog`) and the success message now auto-clears after a few seconds.

---

## MediaMTX web editor — stale overlay sync

- **Problem:** Some upgraded infra-TAK deployments had an old `/opt/mediamtx-webeditor/mediamtx_ldap_overlay.py` that still injected legacy JS badges/buttons into External Sources. Core web editor code was correct, but stale overlay logic mutated the rendered table.
- **Fix:** `mediamtx_recovery()` now always copies the overlay file from the running infra-TAK repo to the active web editor path before restart, so patching always converges to the current overlay behavior.
- **Operator action (existing installs):** Open MediaMTX and click **Patch web editor** once.

---

## Guard Dog — Updates monitor timer reinstall

- **Problem:** Some boxes had Guard Dog scripts but were missing `takupdatesguard.timer`, so the "Update check" monitor stayed red (`systemctl is-enabled takupdatesguard.timer` failed).
- **Fix:** `POST /api/guarddog/update` now writes both `takupdatesguard.service` and `takupdatesguard.timer`, reloads systemd, enables/starts the timer, and refreshes the Guard Dog monitor cache.
- **Operator action (existing installs):** On Guard Dog page, click **↻ Update Guard Dog** once.

---

## Summary of code changes

| Area | Change |
|------|--------|
| **app.py** | `mediamtx_recovery()` now syncs `mediamtx_ldap_overlay.py` to `/opt/mediamtx-webeditor/` before restart. |
| **app.py** | `guarddog_update()` now re-creates + enables `takupdatesguard.timer` and refreshes monitor cache. |
| **app.py** | Guard Dog Updates monitor description now explicitly tells operators to click **Update Guard Dog** if red/missing. |
| **app.py** | Guard Dog status banner button text changed to **↻ Update Guard Dog**. |
| **static/guarddog.js** | `gdUpdate()` deduplicated/cleaned; success message auto-clears and health checks refresh immediately. |
