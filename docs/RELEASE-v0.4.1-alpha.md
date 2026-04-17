# infra-TAK v0.4.1-alpha

Release Date: April 2026

---

## Highlights

### Update Now (v0.4.0 → v0.4.1)

- **v0.4.0** stopped bulk `git fetch --tags` and fetched only the latest tag from the GitHub API.
- **v0.4.1** fixes what was still broken: explicit `git fetch` refspecs are **additive** with **`remote.origin.fetch`**, so some installs still hit **`would clobber existing tag`**. **v0.4.1** runs tag and main fallback fetches with **`git -c remote.origin.fetch=`** so only the intended refspec runs.

### Authentik + TAK + 8446 (v0.3.9 / v0.4.0 track — read this if you skipped v0.3.9)

Many installs will jump **v0.3.8 → v0.4.1** and never open the v0.3.9 or v0.4.0 release notes. That work is **in this build**:

- **8446 webadmin (LDAP)**: With Authentik, **`webadmin` lives in Authentik only** — flat-file `usermod` is skipped; LDAP bind is verified after sync.
- **Flat-file “auth provider” toggle removed**: Misleading UI is gone; with Authentik, **LDAP is the path**.
- **Authentik PostgreSQL**: **Update config** / deploy clears stale **`postgresql.auto.conf`** (helps **`FATAL: too many clients already`**).
- **Authentik full deploy (local)**: Ends with a **mandatory `adm_ldapservice` bind** after Caddy / SMTP / final LDAP restart — no false success if LDAP is broken.
- **Authentik Update config**: Missing FQDN no longer **falls through into a full deploy**; optional LDAP heal without FQDN.
- **SMTP / recovery + LDAP re-heal**, **LDAP bind verification** improvements, **Let’s Encrypt 8446** stop-then-patch connector, **XML-safe** `webadmin` removal from `UserAuthenticationFile.xml`, stricter LDAP-in-CoreConfig detection, LDAP outpost URL fixes.

Detail tables and file-level summary: [RELEASE-v0.3.9-alpha.md](RELEASE-v0.3.9-alpha.md), [RELEASE-v0.4.0-alpha.md](RELEASE-v0.4.0-alpha.md) (historical; GitHub Releases).

---

## What changed vs v0.3.8 (fresh deploys / behavior)

| Scenario | Before (v0.3.8) | After (v0.4.1) |
|----------|-----------------|----------------|
| **Update Now** | Could fail: `would clobber existing tag` | Latest tag via API; **isolated** `git fetch` (no default refspec side effects) |
| TAK + Authentik | Flat-file `webadmin` could shadow LDAP | Authentik-only `webadmin`, verified bind |
| Authentik full deploy | Success could appear before final LDAP checks | SA bind gate (local) before success |
| Authentik Update config, no FQDN | Could start full deploy | Clean reconfigure exit |
| Authentik PG tuning | Stale `auto.conf` could pile up | Reset + compose-driven tuning on Update config / deploy |

---

## What end users should do after upgrading (especially from v0.3.8)

1. **Console** — [PULL-AND-RESTART.md](PULL-AND-RESTART.md) if **Update Now** failed once; after you are on **v0.4.1-alpha**, future **Update Now** runs should use the isolated fetch path.
2. **Authentik — Update config once**: Clears stale PostgreSQL tuning. Check **`SHOW max_connections;`** → **`300`** if you use that stack:  
   `docker compose exec postgresql psql -U authentik -d authentik -c "SHOW max_connections;"`
3. **8446 login issues**: On the **TAK Server** page, use **Resync LDAP to TAK Server** (re-patches CoreConfig, clears stale flat-file `webadmin`, syncs with Authentik).
4. **Non-Authentik installs** — no extra Authentik steps; flat-file auth unchanged.

---

## Summary of changes (by area)

| Area | Change |
|------|--------|
| **update_apply()** | API latest tag; **`git -c remote.origin.fetch= fetch origin +refs/tags/TAG:refs/tags/TAG`**; fallback isolated fetch of **`main`** → `origin/main`. |
| **webadmin / Authentik / TAK** | LDAP-only `webadmin` with Authentik; `_ensure_authentik_webadmin`; XML cleanup in `UserAuthenticationFile.xml`. |
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

- [ ] `app.py` → `VERSION = "0.4.1-alpha"` matches tag **`v0.4.1-alpha`** (see [COMMANDS.md](COMMANDS.md) Python check).
- [ ] [TESTING-UPDATES.md](TESTING-UPDATES.md): **Update Now** on a test VPS before tagging.
- [ ] Selective `dev` → `main` copy uses **only** [COMMANDS.md](COMMANDS.md) list; release doc line is **`docs/RELEASE-v0.4.1-alpha.md`**.
- [ ] Tag **`v0.4.1-alpha`** and push after `main` push.
