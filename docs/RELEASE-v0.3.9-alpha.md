# infra-TAK v0.3.9-alpha

Release Date: April 2026

---

## Highlights

- **8446 webadmin login fix (LDAP)**: Fresh deploys with Authentik now create the `webadmin` user directly in Authentik — never in the flat-file. Eliminates the flat-file/LDAP shadowing bug that caused "invalid username/password" on 8446 after deploy.
- **Flat-file toggle removed**: The "Auth Provider: Flat File" card and API have been removed. TAK Server always re-adds `<File/>` to CoreConfig on restart, so toggling it was misleading and caused config drift. LDAP is now the sole auth path when Authentik is present.
- **Authentik PostgreSQL stability**: Authentik **Update config** (and deploy) runs `_apply_authentik_pg_tuning()`, which clears stale `postgresql.auto.conf` entries (`ALTER SYSTEM RESET ALL`) before relying on `docker-compose.yml` command-line args. Prevents `FATAL: too many clients already` errors after upgrades.
- **Authentik full deploy — final LDAP gate**: Local Authentik deploy finishes with Caddy (if FQDN), Email Relay SMTP push (if configured), final LDAP container restart, then a **mandatory** `adm_ldapservice` bind check (`_authentik_deploy_final_verify_ldap_sa`). Success is only reported when that passes; otherwise deploy ends in **error** (no false "go deploy TAK" after a broken outpost).
- **Authentik Update config — control-flow fix**: Local reconfigure used to end with `return` only inside `if fqdn:`. Without FQDN, execution **fell through into a full Authentik deploy**. Now reconfigure **always** completes with proper status; if FQDN is missing, forward-auth steps are skipped and an optional LDAP flow heal still runs when the API is up.
- **SMTP / recovery + LDAP**: After configuring Authentik from Email Relay, the stack re-heals LDAP authentication flow / outpost behavior so SMTP restarts are less likely to leave LDAP in a bad state.
- **LDAP bind verification improvements**: `_test_ldap_bind_dn()` treats `ldapsearch` success as primary signal, retries, rejects obvious Authentik flow errors in outpost logs (`ak-stage-flow-error`, etc.), and expanded log matching for more reliable detection.
- **Deterministic webadmin password**: The console never silently rotates the webadmin password. It always uses the password from `settings.json` and fails loudly if missing or if LDAP bind cannot be verified.
- **Safer XML editing**: `_remove_webadmin_from_userauth()` uses `xml.etree.ElementTree` and removes the `webadmin` user from its **parent** (not only direct children of the document root), avoiding silent failures and malformed XML.
- **LE cert 8446 connector fix**: TAK Server overwrites `<connector>` elements in CoreConfig.xml on restart. The LE cert install now stops TAK Server before patching the 8446 connector, then starts it — preventing the patch from being silently reverted.
- **LDAP outpost internal URL fix**: LDAP outpost uses the internal Docker network URL where appropriate, fixing connectivity issues on some deployments.

---

## What changed for fresh deploys

| Scenario | Before (v0.3.8) | After (v0.3.9) |
|----------|-----------------|----------------|
| TAK Server deploy **with** Authentik | `webadmin` created in flat-file via `UserManager.jar`, then removed post-deploy | `webadmin` created directly in Authentik only — flat-file `usermod` skipped; verified LDAP bind after sync |
| TAK Server deploy **without** Authentik | `webadmin` created in flat-file | Same — no change |
| Resync LDAP / Connect LDAP | Removed `webadmin` from flat-file (line-based, could break XML) | Removes `webadmin` from flat-file using XML parser (nested-safe) |
| Authentik **full** deploy complete | Success could be printed before Caddy/SMTP/final LDAP restart | Success only after final `adm_ldapservice` bind verification (local deploy) |
| Authentik **Update config** without FQDN | Could fall through into full deploy | Always exits as reconfigure; optional LDAP flow heal |

---

## What end users should do after upgrading

1. **Pull & restart console** — Follow the [PULL-AND-RESTART](PULL-AND-RESTART.md) guide.
2. **Authentik users — run Update Config**: Go to Authentik page → **Update config**. This clears stale PostgreSQL tuning entries that can cause connection exhaustion. Verify: `docker compose exec postgresql psql -U authentik -d authentik -c "SHOW max_connections;"` → should show `300`.
3. **If 8446 login is broken**: Click **Resync LDAP to TAK Server** on the TAK Server page. This re-patches CoreConfig, removes any stale `webadmin` flat-file entry, and syncs to Authentik.
4. **No action needed for non-Authentik users** — flat-file auth continues to work as before.

---

## Summary of changes

| Area | Change |
|------|--------|
| **webadmin deploy flow** | When Authentik is detected, `UserManager.jar usermod webadmin` is skipped entirely. `webadmin` is created/updated in Authentik with `tak_ROLE_ADMIN` + `authentik Admins` via `_ensure_authentik_webadmin()` with LDAP bind verification. |
| **Flat-file toggle removed** | `_takserver_flatfile_auth_status()`, `GET/POST /api/takserver/flatfile-auth` routes, and related UI removed. |
| **Authentik PG tuning hardened** | `_apply_authentik_pg_tuning()` runs `ALTER SYSTEM RESET ALL; SELECT pg_reload_conf();` to clear `postgresql.auto.conf` before relying on `docker-compose.yml` command-line args only. |
| **Authentik deploy final gate** | `_authentik_deploy_final_verify_ldap_sa()` after Caddy, SMTP (if any), final `ldap` restart; sets deploy error if SA bind fails. |
| **Authentik reconfigure** | Completion and `authentik_deploy_status` update moved outside `if fqdn:`; `else` branch for no-FQDN with LDAP flow heal attempt. |
| **LDAP bind verification** | `_test_ldap_bind_dn()` retries, `ldapsearch` + log checks, rejects flow-error lines in outpost logs. |
| **Password management** | No silent rotation in `_ensure_authentik_webadmin()`; password from settings. |
| **XML-safe flat-file cleanup** | `_remove_webadmin_from_userauth()` uses ElementTree and parent-based removal. |
| **LE cert 8446 connector** | `install_le_cert_on_8446()` stops TAK Server before patching 8446 `<connector>`, then starts. |
| **Stricter LDAP detection** | `_coreconfig_has_ldap()` requires `default="ldap"` and LDAP provider element. |
| **LDAP / SMTP** | Post-SMTP `_ensure_ldap_flow_authentication_none()` re-heal where applicable. |
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

- **Update Now — "would clobber existing tag"**: The first `v0.3.9-alpha` publish could fail **Update Now** on boxes whose local `v0.3.8-alpha` (or other release tags) pointed at a different commit than GitHub. **Workaround (SSH on the console host):** `cd <infra-TAK>` then `git fetch origin --tags --force` and click **Update Now** again, or `git checkout --force v0.3.9-alpha && sudo systemctl restart takwerx-console`. **Fix:** `update_apply()` now uses `git fetch origin --tags --force` and `git fetch -f origin tag …` (ship in **v0.3.10-alpha** or cherry-pick that commit).
- **LDAP bind verification can time out during deploy** even when 8446 login works. Use **Resync LDAP** if 8446 actually fails.
- **Password change widget** currently only saves to `settings.json`. A future update will make it update flat-file (no Authentik) or Authentik (with LDAP) in one click.
- **Remote Authentik deploy** does not yet run the same final `adm_ldapservice` gate as local deploy (SSH/console would need an explicit remote bind check).

---

## Operator checklist (release maintainer)

- [ ] Confirm `app.py` contains `VERSION = "0.3.9-alpha"` before tagging.
- [ ] Tag/publish **`v0.3.9-alpha`**.
- [ ] Fresh deploy on clean VPS with Authentik pre-installed — verify Step 9 TAK log says Authentik webadmin LDAP-only path and **✓ webadmin synced to Authentik**.
- [ ] Verify 8446 login works with `webadmin` / configured password.
- [ ] Verify `webadmin` is NOT in `/opt/tak/UserAuthenticationFile.xml` (Authentik path).
- [ ] Verify Authentik full deploy log shows final LDAP SA bind verification (or intentional failure if broken).
- [ ] Verify Authentik **Update config** shows PostgreSQL tuning cleaned up when applicable; with FQDN unset, verify it does **not** start Step 1/10 full deploy.
- [ ] Fresh deploy WITHOUT Authentik — verify `webadmin` flat-file creation works normally.
