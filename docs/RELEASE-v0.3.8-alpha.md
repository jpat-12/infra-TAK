# infra-TAK v0.3.8-alpha

Release Date: April 2026

---

## Highlights

- **Smart Auto-VACUUM**: Guard Dog now runs a daily check (3am) on the CoT database. If dead tuples exceed 1M, it automatically runs VACUUM ANALYZE to prevent bloat. Works for both local and remote (two-server) databases.
- **Enhanced Database Maintenance UI**: New stat cards show database size, estimated rows, and dead tuples at a glance. Buttons renamed to plain language: "Optimize Tables", "Compact Database", "Rebuild Indexes".
- **VACUUM runs in background with live status**: VACUUM FULL can take hours — now runs in a background thread with a live elapsed timer. Navigate away and come back; the status persists. Detects running VACUUMs even after console restart.
- **REINDEX button**: New "Rebuild Indexes" operation improves query performance. Safe while TAK Server is running.
- **Remote CoT DB size monitoring**: Two-server setups now get CoT database size alerts (was silently skipped before). Alert at 25GB warning / 40GB critical with email.
- **Authentik PostgreSQL hardening**: New deployments get `max_connections=300`. "Update config" now applies `ALTER SYSTEM SET` tuning (idle_session_timeout, tcp_keepalives) to prevent connection exhaustion.
- **Flat-file auth toggle**: New card on the TAK Server page lets you enable/disable the `UserAuthenticationFile.xml` auth provider in CoreConfig with one click. Restarts TAK Server automatically. Useful for LDAP-only setups that don't need local password fallback.
- **TAK Portal Authentik link fix**: The Authentik button on the TAK Portal page now goes to the correct URL.

---

## What end users should do after upgrading

1. **Update infra-TAK** — Console → Update Now, then restart.
2. **Re-deploy Guard Dog** (Guard Dog page → Update) to install the new auto-vacuum and CoT DB size timers.
3. **Authentik users**: Go to Authentik page → "Update config" to apply PostgreSQL tuning. Verify with: `docker compose exec postgresql psql -U authentik -d authentik -c "SHOW max_connections;"` → should show `300`.
4. **Large CoT databases**: Open TAK Server → Database Maintenance. Check dead tuples. If database is bloated, stop TAK Server and run "Compact Database" (VACUUM FULL) to reclaim disk space.

---

## Summary of changes

| Area | Change |
|------|--------|
| **Smart Auto-VACUUM** | New `tak-auto-vacuum.sh` Guard Dog script + `takautovacuum.timer` (daily 3am). Checks dead tuples, runs VACUUM ANALYZE when > 1M. Local + remote SSH. |
| **Remote CoT DB monitor** | `tak-cotdb-watch.sh` now supports two-server mode via SSH. Deployed for both single and two-server setups. |
| **REINDEX endpoint** | New `POST /api/takserver/reindex` — runs `REINDEX DATABASE cot`. Two-server aware. |
| **Enhanced DB stats** | `GET /api/takserver/cot-db-size` now returns `message_count` and `dead_tuples` alongside size. |
| **Background VACUUM** | VACUUM runs in a background thread. New `GET /api/takserver/vacuum/status` polls progress via `pg_stat_activity`. |
| **Database UI** | Both TAK Server and Guard Dog pages show stat grid (size, rows, dead tuples) + three maintenance buttons with accurate descriptions. |
| **Authentik PG tuning** | `POSTGRES_MAX_CONNECTIONS` bumped to 300. "Update config" applies ALTER SYSTEM SET for idle_session_timeout, tcp_keepalives. |
| **Guard Dog Update** | Update button now installs new systemd timers (auto-vacuum, cotdb) — previously only copied scripts. |
| **Flat-file auth toggle** | New UI card + API (`GET/POST /api/takserver/flatfile-auth`) to enable/disable `UserAuthenticationFile.xml` in CoreConfig `<auth>` block. Auto-restarts TAK Server. |
| **TAK Portal link fix** | `authentik_base_url` and `takserver_base_url` now passed to TAK Portal template. |

---

## Operator checklist (release maintainer)

- [ ] Confirm `app.py` contains `VERSION = "0.3.8-alpha"` before tagging.
- [ ] Tag/publish **`v0.3.8-alpha`**.
- [ ] Run **Update Now** on a test VPS and confirm sidebar shows **v0.3.8-alpha** after restart.
- [ ] Verify Guard Dog Update installs `takautovacuum.timer`.
- [ ] Verify Authentik "Update config" shows PG tuning log message.
