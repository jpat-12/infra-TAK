# infra-TAK v0.4.0-alpha

Release Date: April 2026

---

## Highlights

- **Update Now — tag clobber fixed**: **Update Now** no longer runs bulk `git fetch --tags` (which failed with `would clobber existing tag` when local release tags like `v0.3.8-alpha` pointed at a different commit than GitHub). It resolves the latest tag from the GitHub API, then fetches **only** that tag: `git fetch origin +refs/tags/<tag>:refs/tags/<tag>`. **No SSH workaround** for normal upgrades to this version.
- **8446 webadmin login fix (LDAP)** (from v0.3.9 track): With Authentik, `webadmin` is created in Authentik only — flat-file `usermod` skipped; LDAP bind verified after sync.
- **Flat-file toggle removed** (v0.3.9): Misleading UI removed; LDAP is the auth path when Authentik is present.
- **Authentik PostgreSQL stability** (v0.3.9): **Update config** / deploy clears stale `postgresql.auto.conf` via `_apply_authentik_pg_tuning()`; helps `FATAL: too many clients already`.
- **Authentik full deploy — final LDAP gate** (v0.3.9): Local deploy ends with mandatory `adm_ldapservice` bind after Caddy / SMTP / final LDAP restart.
- **Authentik Update config** (v0.3.9): No longer falls through into a full deploy when FQDN is missing; optional LDAP flow heal without FQDN.
- **SMTP / recovery + LDAP re-heal**, **LDAP bind verification** improvements, **LE 8446** stop-then-patch connector, **XML-safe** `webadmin` removal from `UserAuthenticationFile.xml`, stricter `_coreconfig_has_ldap()`, LDAP outpost URL fixes — see Summary table below.

---

## What changed for fresh deploys

| Scenario | Before (v0.3.8) | After (v0.4.0) |
|----------|-----------------|----------------|
| **Update Now** from older console | Could fail: `would clobber existing tag` | Fetches only the latest release tag; avoids touching mismatched older tags |
| TAK + Authentik | Flat-file `webadmin` shadow risk | Authentik-only `webadmin`, verified bind |
| Authentik full deploy | Success before final LDAP checks | SA bind gate (local) before success |
| Authentik Update config, no FQDN | Could start full deploy | Clean reconfigure exit |

---

## What end users should do after upgrading

1. **Pull & restart console** — [PULL-AND-RESTART.md](PULL-AND-RESTART.md).
2. **Authentik — Update config** once: clears stale PostgreSQL tuning. Check `SHOW max_connections;` → `300` if applicable.
3. **8446 issues**: **Resync LDAP to TAK Server** on the TAK Server page.
4. **Skipping v0.3.9-alpha**: If **Update Now** never succeeded on v0.3.9, **v0.4.0-alpha** should work from the UI; if not, use PULL-AND-RESTART once, then **Update Now**.

---

## Summary of changes

| Area | Change |
|------|--------|
| **update_apply()** | Latest tag from API; `git fetch origin +refs/tags/TAG:refs/tags/TAG` only; fallback `origin/main`. |
| **webadmin / Authentik / TAK** | Same as v0.3.9 track (LDAP-only webadmin, `_ensure_authentik_webadmin`, XML cleanup). |
| **Authentik PG** | `_apply_authentik_pg_tuning()` ALTER SYSTEM reset + compose args. |
| **Authentik deploy / reconfigure** | Final SA gate; reconfigure `fqdn` fix. |
| **LDAP** | `_test_ldap_bind_dn`, flow-error rejection, SMTP re-heal. |
| **8446 LE** | Stop TAK → patch connector → start. |

---

## Critical: TAK Server CoreConfig.xml behavior

TAK Server rewrites portions of `CoreConfig.xml` at runtime (`<File/>`, connector normalization). **Stop TAK Server** before patching **8446** connectors. See [WORKFLOW-8446-WEBADMIN.md](WORKFLOW-8446-WEBADMIN.md).

---

## Known issues

- **LDAP bind verification can time out during deploy** even when 8446 works — use **Resync LDAP** if login fails.
- **Password change widget** saves to `settings.json` only; use **Sync webadmin** for Authentik.
- **Remote Authentik deploy** has no same final SA bind gate as local (future).

---

## Operator checklist (release maintainer)

- [ ] `app.py` → `VERSION = "0.4.0-alpha"` matches tag **`v0.4.0-alpha`** (see [COMMANDS.md](COMMANDS.md) Python check).
- [ ] **TESTING-UPDATES.md**: test **Update Now** on a VPS before pushing the tag.
- [ ] Selective `dev` → `main` copy uses **only** [COMMANDS.md](COMMANDS.md) list; release doc line is **`docs/RELEASE-v0.4.0-alpha.md`**.
- [ ] Tag **`v0.4.0-alpha`** and push after `main` push.
