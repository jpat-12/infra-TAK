# infra-TAK v0.3.9-alpha

Release Date: April 2026

---

## Highlights

- **8446 webadmin login fix (LDAP)**: Fresh deploys with Authentik now create the `webadmin` user directly in Authentik — never in the flat-file. Eliminates the flat-file/LDAP shadowing bug that caused "invalid username/password" on 8446 after deploy.
- **Flat-file toggle removed**: The "Auth Provider: Flat File" card and API have been removed. TAK Server always re-adds `<File/>` to CoreConfig on restart, so toggling it was misleading and caused config drift. LDAP is now the sole auth path when Authentik is present.
- **Authentik PostgreSQL stability**: `Update Config` now clears stale `postgresql.auto.conf` entries (`ALTER SYSTEM RESET ALL`) before relying on `docker-compose.yml` command-line args. Prevents `FATAL: too many clients already` errors after upgrades.
- **LDAP bind verification improvements**: `_test_ldap_bind_dn()` now uses `ldapsearch` success as primary signal, retries up to 3 times, and expands log matching for more reliable detection.
- **Deterministic webadmin password**: The console never silently rotates the webadmin password. It always uses the password from `settings.json` and fails loudly if missing or if LDAP bind cannot be verified.
- **Safer XML editing**: `_remove_webadmin_from_userauth()` now uses proper XML parsing instead of line-based string removal, preventing `Invalid authentication file supplied to FileAuthenticator!` crashes.
- **LE cert 8446 connector fix**: TAK Server overwrites `<connector>` elements in CoreConfig.xml on restart. The LE cert install now stops TAK Server before patching the 8446 connector, then starts it — preventing the patch from being silently reverted.
- **LDAP outpost internal URL fix**: LDAP outpost now uses the internal Docker network URL instead of the external HTTPS URL, fixing connectivity issues on some deployments.

---

## What changed for fresh deploys

| Scenario | Before (v0.3.8) | After (v0.3.9) |
|----------|-----------------|-----------------|
| TAK Server deploy **with** Authentik | `webadmin` created in flat-file via `UserManager.jar`, then removed post-deploy | `webadmin` created directly in Authentik only — flat-file is never touched |
| TAK Server deploy **without** Authentik | `webadmin` created in flat-file | Same — no change |
| Resync LDAP / Connect LDAP | Removed `webadmin` from flat-file (line-based, could break XML) | Removes `webadmin` from flat-file using XML parser (safe) |

---

## What end users should do after upgrading

1. **Pull & restart console** — Follow the [PULL-AND-RESTART](PULL-AND-RESTART.md) guide.
2. **Authentik users — run Update Config**: Go to Authentik page → "Update Config". This clears stale PostgreSQL tuning entries that can cause connection exhaustion. Verify: `docker compose exec postgresql psql -U authentik -d authentik -c "SHOW max_connections;"` → should show `300`.
3. **If 8446 login is broken**: Click "Resync LDAP to TAK Server" on the TAK Server page. This re-patches CoreConfig, removes any stale `webadmin` flat-file entry, and syncs to Authentik.
4. **No action needed for non-Authentik users** — flat-file auth continues to work as before.

---

## Summary of changes

| Area | Change |
|------|--------|
| **webadmin deploy flow** | When Authentik is detected, `UserManager.jar usermod webadmin` is skipped entirely. `webadmin` is created directly in Authentik with `tak_ROLE_ADMIN` + `authentik Admins` groups via `_ensure_authentik_webadmin()`. |
| **Flat-file toggle removed** | `_takserver_flatfile_auth_status()`, `GET/POST /api/takserver/flatfile-auth` routes, and all frontend JS (`loadFlatfileAuthStatus`, `toggleFlatfileAuth`) removed. |
| **Authentik PG tuning hardened** | `_apply_authentik_pg_tuning()` now runs `ALTER SYSTEM RESET ALL; SELECT pg_reload_conf();` to clear `postgresql.auto.conf` before relying on `docker-compose.yml` command-line args only. |
| **LDAP bind verification** | `_test_ldap_bind_dn()` retries up to 3 times, uses `ldapsearch` exit code as primary signal, expanded log parsing. |
| **Password management** | Silent password generation/rotation removed from `_ensure_authentik_webadmin()`. Password is always deterministic from `settings.json`. |
| **XML-safe flat-file cleanup** | `_remove_webadmin_from_userauth()` rewritten to use `xml.etree.ElementTree` instead of line filtering. |
| **LE cert 8446 connector** | `install_le_cert_on_8446()` now stops TAK Server before patching the 8446 `<connector>`, then starts. TAK Server overwrites connector elements on restart; patching while running caused the LE keystore config to be silently reverted, resulting in 403 on 8446. |
| **Stricter LDAP detection** | `_coreconfig_has_ldap()` now requires both `default="ldap"` attribute and LDAP provider element, not just `adm_ldapservice` string match. |
| **LDAP outpost URL** | Outpost config uses internal Docker URL (`http://authentik-server:9000`) instead of external HTTPS. |
| **Pull docs** | `PULL-AND-RESTART.md` updated for shallow single-branch clones (`git fetch origin` instead of `git pull`). |

---

## Critical: TAK Server CoreConfig.xml behavior

TAK Server rewrites portions of `CoreConfig.xml` at runtime:
- **`<File/>` tag**: Always re-added to `<auth>` block on startup. Cannot be prevented.
- **`<connector>` elements**: Normalized on startup — `_name`, keystore attributes can be reset to defaults.
- **`<auth>` block contents** (LDAP config, etc.): Generally preserved through restarts.

**Rule**: Any code that patches `<connector>` elements must **stop TAK Server first**, patch, then start. Patching connectors while TAK Server is running will be overwritten on restart. See `docs/WORKFLOW-8446-WEBADMIN.md` for the full safe-patching table.

---

## Known issues

- **LDAP bind verification can time out during deploy** even when 8446 login works. The warning `⚠ webadmin sync: timed out` is cosmetic if `webadmin` was created in Authentik. Use Resync LDAP if 8446 actually fails.
- **Password change widget** currently only saves to `settings.json`. A future update will make it update flat-file (no Authentik) or Authentik (with LDAP) in one click.

---

## Operator checklist (release maintainer)

- [ ] Confirm `app.py` contains `VERSION = "0.3.9-alpha"` before tagging.
- [ ] Tag/publish **`v0.3.9-alpha`**.
- [ ] Fresh deploy on clean VPS with Authentik pre-installed — verify step 9 says "Authentik detected — webadmin will be created directly in Authentik (skipping flat-file)".
- [ ] Verify 8446 login works with `webadmin` / configured password.
- [ ] Verify `webadmin` is NOT in `/opt/tak/UserAuthenticationFile.xml`.
- [ ] Verify Authentik "Update Config" shows "PostgreSQL tuning cleaned up" message.
- [ ] Fresh deploy WITHOUT Authentik — verify `webadmin` flat-file creation works normally.
