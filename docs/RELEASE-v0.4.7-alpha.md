# infra-TAK v0.4.7-alpha

Release Date: April 2026

---

## Highlights

### Auto-deploy everything on update

When infra-TAK updates to a new version, **all module configs are automatically re-deployed** in the background. No more manually pressing buttons after console updates.

- Detects version change on startup
- Waits 10 seconds for the console to stabilize
- Re-deploys Guard Dog first (updated scripts, timers, and config)
- Then runs Authentik, TAK Portal, and CloudTAK **in parallel** so a slow Authentik reconfigure doesn't block the others
- Re-runs Authentik reconfigure (LDAP/forward-auth sync)
- Re-pushes TAK Portal settings and restarts the container
  - SSH auto-config only runs when TAK Server is on the same box (`/opt/tak` exists)
  - Remote TAK Server deployments: settings are pushed but SSH is left to manual config
- Regenerates CloudTAK `docker-compose.override.yml` and restarts containers (picks up env var fixes)
  - Works for both local and remote CloudTAK deployments
- Console cards show **"Updating config..."** with a cyan spinner while each service is being reconfigured, then revert to Running/Healthy when done
- Manual buttons remain available as fallback

> **Note:** Authentik will be unavailable for approximately 3–5 minutes during the reconfigure. Services behind Authentik (TAK Portal login, console via domain) may be unreachable during this time. Use the IP:5001 backdoor if you need console access while the update is running.

### Online database repack (pg_repack)

New Guard Dog script `tak-db-repack.sh` reclaims actual disk space from the CoT database **without downtime**. Addresses the issue where TAK Server retention deletes rows but PostgreSQL never returns disk space to the OS.

- Uses `pg_repack` — no exclusive table locks, TAK stays online
- Runs weekly (Sunday 4 AM) via systemd timer
- Only triggers if the database exceeds 10 GB (skip for small installs)
- Auto-installs `pg_repack` on first run (detects PostgreSQL version)
- Logs before/after size and space reclaimed
- Emails results and alerts on failure
- Works in both local and two-server mode

**Previous behavior:** `VACUUM ANALYZE` (daily 3 AM) marks dead space as reusable but never shrinks files on disk. Database size grew indefinitely even with retention enabled.

**New behavior:** Weekly repack after the daily vacuum actually returns disk space to the OS. `VACUUM FULL` (which requires downtime) is still available for manual maintenance but should rarely be needed.

### Guard Dog remote database monitor fix

Fixed a bug where the Remote Database TCP+SSH monitor showed **green** even when Server One was unreachable. The socket connection timeout exception was caught by a generic handler and returned `None` (skip) instead of `False` (failure).

Now correctly returns red when the remote database server cannot be reached.

### Guard Dog config drift prevention

`guarddog.conf` (which stores the remote database IP for monitoring scripts) now stays in sync with `settings.json` automatically:

1. **On every console startup** — if the DB host in settings differs from guarddog.conf, it's updated
2. **After DB migration** — already existed, confirmed working
3. **After console update** — the new auto-deploy re-writes guarddog.conf from settings

Previously, if the database was migrated to a new host, `guarddog.conf` could retain the old IP, causing vacuum, CoT DB size monitoring, and the new repack script to fail silently.

### Guard Dog — TAK Portal monitor

New container health monitor for TAK Portal, same pattern as Authentik/Node-RED/CloudTAK:

- Checks `tak-portal` container status every 1 minute
- Alerts and auto-restarts after 3 consecutive failures
- 15-minute boot grace period and restart cooldown to avoid loops
- Shows as a row in the Guard Dog Monitors section with a green/red health dot

Previously TAK Portal had no health monitor — if the container crashed, nobody knew until a user noticed.

### Guard Dog — smart "Update" button

The Guard Dog UI now shows whether the deployed config is current:

- **"✓ up to date (v0.4.7-alpha)"** — green indicator when Guard Dog version and settings match what's deployed
- **"⚠ settings changed — update needed"** — yellow warning when alert email or server nickname changed since last deploy
- **"↻ Update Guard Dog" button** only appears when there's a mismatch — hidden when everything is current

Deployed version, email, and nickname are stamped in `settings.json` on every deploy (full, update, or auto-deploy). Existing installs get stamped automatically on first startup at this version.

### CloudTAK security fix

Removed `NODE_TLS_REJECT_UNAUTHORIZED=0` from CloudTAK's `.env` and `docker-compose.override.yml`. This environment variable disabled **all** TLS certificate verification in Node.js — not just for TAK Server connections, but for every HTTPS request the process made.

Flagged by CloudTAK developer Nick Ingalls as a security flaw. The setting was leftover from an abandoned automatic bootstrap feature and is not needed — users upload the admin P12 manually through CloudTAK's UI.

The fix is applied automatically on upgrade via the new auto-deploy (CloudTAK override is regenerated and containers restarted).

### UI: "Patch CoreConfig" rename

The TAK Server "Update config" button was renamed to **"Patch CoreConfig"** with a tooltip explaining its purpose, to avoid confusion with the module-level "Update config" buttons.

---

## Schedule summary (database maintenance)

| Time | Script | What it does |
|------|--------|-------------|
| Midnight | TAK Server retention | Deletes expired CoT rows |
| 3:00 AM daily | `tak-auto-vacuum.sh` | `VACUUM ANALYZE` — marks dead space reusable, updates stats |
| 4:00 AM Sunday | `tak-db-repack.sh` | `pg_repack` — reclaims actual disk space, no lock |
| Every 6 hours | `tak-cotdb-watch.sh` | Monitors DB size, alerts at 25 GB / 40 GB |

---

## Update instructions

From the infra-TAK console: **Update Now** button. Everything is automatic — Guard Dog, Authentik, TAK Portal, and CloudTAK configs will be updated after the console restarts. No manual steps required. Service cards on the console will show "Updating config..." while each module is being reconfigured.

**Expect ~3–5 minutes of Authentik downtime** while it reconfigures. If you need console access during the update, use `https://<server-ip>:5001` (bypasses Authentik).

For servers where Guard Dog shows stale remote DB config after a prior migration, the startup sync will correct it automatically on this update.

---

## Everything else in this train

Same as **v0.4.6** (boot sequencer, Authentik resilience, cert password fix, TAK Portal SSH auto-config). Prior: [v0.4.6-alpha](RELEASE-v0.4.6-alpha.md), [v0.4.5-alpha](RELEASE-v0.4.5-alpha.md), [v0.4.4-alpha](RELEASE-v0.4.4-alpha.md), [v0.4.3-alpha](RELEASE-v0.4.3-alpha.md), [v0.4.2-alpha](RELEASE-v0.4.2-alpha.md).

---

## Release checklist (maintainer)

- [ ] `app.py` → `VERSION = "0.4.7-alpha"` matches tag **`v0.4.7-alpha`**.
- [ ] Tag **`v0.4.7-alpha`** and push after `main` push.
