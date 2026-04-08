# infra-TAK v0.4.7-alpha

Release Date: April 2026

---

## Highlights

### Auto-deploy Guard Dog + Authentik + TAK Portal on update

When infra-TAK updates to a new version, Guard Dog scripts, Authentik configuration, and TAK Portal settings are now **automatically re-deployed** in the background. No more manually pressing "Update Guard Dog", "Reconfigure Authentik", and "Update config" after every console update.

- Detects version change on startup
- Waits 10 seconds for the console to stabilize
- Re-deploys Guard Dog (updated scripts, timers, and config)
- Re-runs Authentik reconfigure (LDAP/forward-auth sync)
- Re-pushes TAK Portal settings and restarts the container
  - SSH auto-config only runs when TAK Server is on the same box (`/opt/tak` exists)
  - Remote TAK Server deployments: settings are pushed but SSH is left to manual config
- Manual buttons remain available as fallback

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

From the infra-TAK console: **Update Now** button. Guard Dog and Authentik configuration will be automatically updated after the console restarts — no manual steps required.

For servers where Guard Dog shows stale remote DB config after a prior migration, the startup sync will correct it automatically on this update.
