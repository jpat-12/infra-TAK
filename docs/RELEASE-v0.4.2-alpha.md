# infra-TAK v0.4.2-alpha

Release Date: April 2026

---

## Highlights

### TAK Portal (new in v0.4.2)

- **`TAK_URL` uses your FQDN, not the VPS IP**: Managed portal `settings.json` used **`https://<server_ip>:8443/Marti`** whenever `server_ip` was set. TAK’s cert is for **`takserver.<yourdomain>`**, so Node.js TLS verification failed (**“TAK server’s identity could not be verified”**) and **QR / certificate enrollment** could fail. **v0.4.2** prefers **`takserver.<fqdn>`** (or your configured TAK host) when **`fqdn`** is set; IP remains the fallback for installs without a domain.

### Update Now (v0.4.0 → v0.4.1)

- **v0.4.0** stopped bulk `git fetch --tags` and fetched only the latest tag from the GitHub API.
- **v0.4.1** clears **`remote.origin.fetch`** for that fetch so explicit refspecs do not still pull every remote-tracking ref and trigger **`would clobber existing tag`**.

### Authentik + TAK + 8446 (v0.3.9 / v0.4.0 track — read this if you skipped v0.3.9)

Many installs will jump **v0.3.8 → v0.4.2** (or similar) and never open older release notes. That work is **in this build**:

- **8446 webadmin (LDAP)**: With Authentik, **`webadmin` lives in Authentik only** — flat-file `usermod` is skipped; LDAP bind is verified after sync.
- **Flat-file “auth provider” toggle removed**: Misleading UI is gone; with Authentik, **LDAP is the path**.
- **Authentik PostgreSQL**: **Update config** / deploy clears stale **`postgresql.auto.conf`** (helps **`FATAL: too many clients already`**).
- **Authentik full deploy (local)**: Ends with a **mandatory `adm_ldapservice` bind** after Caddy / SMTP / final LDAP restart — no false success if LDAP is broken.
- **Authentik Update config**: Missing FQDN no longer **falls through into a full deploy**; optional LDAP heal without FQDN.
- **SMTP / recovery + LDAP re-heal**, **LDAP bind verification** improvements, **Let’s Encrypt 8446** stop-then-patch connector, **XML-safe** `webadmin` removal from `UserAuthenticationFile.xml`, stricter LDAP-in-CoreConfig detection, LDAP outpost URL fixes.

Detail tables and file-level summary: [RELEASE-v0.3.9-alpha.md](RELEASE-v0.3.9-alpha.md), [RELEASE-v0.4.0-alpha.md](RELEASE-v0.4.0-alpha.md), [RELEASE-v0.4.1-alpha.md](RELEASE-v0.4.1-alpha.md) (historical; GitHub Releases).

---

## Required after you upgrade — TAK Portal (v0.4.2)

**TAK Portal does not pick up the new `TAK_URL` until you push settings into the container.**

1. Upgrade the console to **v0.4.2-alpha** and restart if needed.
2. In infra-TAK open **TAK Portal** → click **Update config** (🔄). That writes **`settings.json`** into the portal container and restarts it.
3. If you still see trust / cert errors: **Sync TAK Server CA** on the same page, then try enrollment again.

Skipping step 2 leaves the old **`TAK_URL`** (with IP) inside Docker — the sidebar **VERSION** can be new while the portal still behaves like the old build.

---

## What changed vs v0.3.8 (fresh deploys / behavior)

| Scenario | Before (v0.3.8) | After (v0.4.2) |
|----------|-----------------|----------------|
| **Update Now** | Could fail: `would clobber existing tag` | Latest tag via API; **isolated** `git fetch` (no default refspec side effects) |
| **TAK Portal → TAK API** | `TAK_URL` often used **VPS IP** | **`takserver.<fqdn>`** when **fqdn** set — TLS / QR enrollment align with cert |
| TAK + Authentik | Flat-file `webadmin` could shadow LDAP | Authentik-only `webadmin`, verified bind |
| Authentik full deploy | Success could appear before final LDAP checks | SA bind gate (local) before success |
| Authentik Update config, no FQDN | Could start full deploy | Clean reconfigure exit |
| Authentik PG tuning | Stale `auto.conf` could pile up | Reset + compose-driven tuning on Update config / deploy |

---

## What end users should do after upgrading (especially skipping v0.3.9)

1. **Console** — [README Universal recovery (SSH)](https://github.com/takwerx/infra-TAK/blob/main/README.md#universal-recovery-ssh) or [PULL-AND-RESTART.md](PULL-AND-RESTART.md) if **Update Now** failed once.
2. **Authentik — Update config once**: Clears stale PostgreSQL tuning. Check **`SHOW max_connections;`** → **`300`** if applicable:  
   `docker compose exec postgresql psql -U authentik -d authentik -c "SHOW max_connections;"`
3. **TAK Portal — Update config once** (🔄 on the TAK Portal page): Required for **v0.4.2** `TAK_URL` / enrollment fix (see above).
4. **8446 login issues**: On the **TAK Server** page, **Resync LDAP to TAK Server**.
5. **Non-Authentik installs** — skip Authentik steps; flat-file auth unchanged.

---

## Summary of changes (by area)

| Area | Change |
|------|--------|
| **TAK Portal settings** | **`TAK_URL`** host prefers **`takserver.<fqdn>`** when **fqdn** set (`_takportal_build_settings_dict`). |
| **update_apply()** | API latest tag; **`git -c remote.origin.fetch=`** for tag + main fallback. |
| **webadmin / Authentik / TAK** | LDAP-only `webadmin` with Authentik; XML cleanup in `UserAuthenticationFile.xml`. |
| **Authentik PG** | `_apply_authentik_pg_tuning()` — `ALTER SYSTEM` reset + reload + compose args. |
| **Authentik deploy / reconfigure** | Final SA bind gate (local); reconfigure does not fall through when FQDN missing. |
| **LDAP / SMTP** | Bind verification, flow-error handling, post-SMTP re-heal where applicable. |
| **8446 LE** | Stop TAK → patch connector → start. |

---

## Critical: TAK Server CoreConfig.xml

TAK Server rewrites parts of **`CoreConfig.xml`** at runtime (`<File/>`, connector normalization). **Stop TAK Server** before patching **8446** connectors. See [WORKFLOW-8446-WEBADMIN.md](WORKFLOW-8446-WEBADMIN.md).

---

## Known issues

- **LDAP bind verification** can time out during deploy even when 8446 works — use **Resync LDAP** if login fails.
- **Password change widget** saves to **`settings.json` only**; use **Sync webadmin** for Authentik.
- **Remote Authentik deploy** does not run the same final SA bind gate as local (future).

---

## Release checklist (maintainer)

- [ ] `app.py` → `VERSION = "0.4.2-alpha"` matches tag **`v0.4.2-alpha`** ([COMMANDS.md](COMMANDS.md) Python check).
- [ ] [TESTING-UPDATES.md](TESTING-UPDATES.md) on a test VPS before tagging.
- [ ] Selective `dev` → `main` per [COMMANDS.md](COMMANDS.md); release doc **`docs/RELEASE-v0.4.2-alpha.md`**.
- [ ] Tag **`v0.4.2-alpha`** and push after `main` push.
