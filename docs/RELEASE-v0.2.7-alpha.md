# infra-TAK v0.2.7-alpha

Release Date: March 2026

---

## Highlights

- **Guard Dog alert email** — All Guard Dog email (monitors + “updates available”) now goes through the **same path as “Send test email”** (console → localhost SMTP → Email Relay / Postfix → Brevo). The old system `mail` command is no longer used for alerts.
- **Updates email reliability** — Fixes for HTTPS console on port 5001 (`send-alert-email.sh` tries `https://127.0.0.1:5001` with `-k`, then HTTP), Authentik “current unknown” false positives (read version from `docker-compose.yml` like the dashboard; don’t report an update when current version can’t be read), and the updates script’s email check (global placeholder replace no longer broke the “is email configured?” test).
- **Simpler updates email body** — Lists only components with pending updates (no long generic “how to update” block).
- **Dashboard** — Guard Dog card can show console version and “update” when infra-TAK has a newer tag (same logic as the console).

---

## What end users should do after upgrading

1. **Update infra-TAK** — **Console → Update Now** (or pull + restart as you usually do).
2. **Once:** open **Guard Dog** and click **↻ Update Guard Dog** so scripts under `/opt/tak-guarddog/` match this release (including `send-alert-email.sh` and updated watch scripts).
3. **Notifications** — In **Guard Dog → Notifications**, set your **alert email** and click **Save** (then **Update Guard Dog** again if you change the email later, so scripts on disk get the address).
4. **Email Relay** — Deploy/configure **Email Relay** so outbound mail works; use **Send test email** on the Guard Dog page to confirm. Alerts use the same relay as that test.

See **[docs/GUARDDOG.md](GUARDDOG.md)** for monitors, throttling (“same set” ≈ one email per 24h until the set changes), and `/var/log/takguard/updates.log`.

---

## Pre-release test (before you push the tag)

**Do not push the `v0.2.7-alpha` tag until you have verified Update Now on a test box.**

Follow **[docs/TESTING-UPDATES.md](TESTING-UPDATES.md)**:

1. Pull `dev` onto your test VPS and restart the console.
2. Temporarily set `VERSION = "0.0.1"` in `app.py`, restart, confirm **Update Available** shows the target tag.
3. Click **Update Now** and confirm clean checkout + restart.
4. Restore `app.py` / pull `dev` again, then merge, tag, and push.

That exercises the **same** code path customers use; `git pull` alone does not.

---

## Summary of code changes

| Area | Change |
|------|--------|
| **app.py** | `VERSION` → `0.2.7-alpha`. `POST /api/guarddog/send-alert-email` (localhost only), shared `_guarddog_send_alert_email_via_relay()`, CSRF exemption with `send-sms`. |
| **scripts/guarddog/send-alert-email.sh** | New helper: JSON body → curl to console (HTTPS `-k` then HTTP fallback). |
| **scripts/guarddog/*.sh** | Email alerts pipe through `send-alert-email.sh` instead of `mail`. |
| **scripts/guarddog/tak-updates-watch.sh** | Relay path; email “configured” check; Authentik version from compose; `need_update` skips unknown current; shorter body; 24h throttle text; `HOME` in timer (via app deploy). |
| **app.py** | `run_guarddog_deploy`: ships `send-alert-email.sh`; `takupdatesguard.service` sets `Environment=HOME=…`. |
| **app.py** | `get_all_module_versions()`: Guard Dog card version/update. |
| **docs/GUARDDOG.md**, **README.md** | User-facing notes. |

---

## Operator checklist (release maintainer)

- [ ] Run **TESTING-UPDATES.md** protocol on test VPS.
- [ ] Merge to `main`, tag `v0.2.7-alpha`, push tag.
- [ ] Announce: after update, click **Update Guard Dog** once + confirm Email Relay + test email.
