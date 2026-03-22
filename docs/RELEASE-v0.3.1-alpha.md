# infra-TAK v0.3.1-alpha

Release Date: March 2026

---

## Highlights

- **Migrate database to new Server One (two-server)** — From **TAK Server**, copy `cot` from the current Server One to a new host, update CoreConfig + saved deployment, restart TAK. Collapsible section matches other cards (standard border).
- **Same SSH / deploy patterns as the split wizard** — **Setup SSH key**, **Copy key to new host** (optional `install_host` on `install-ssh-key`), and **Deploy Server One (DB) on new host** via `deploy_target_host` without changing saved `server_one.host` until migration completes.
- **takserver-database .deb on the migrate card** — Status + drop zone use the shared uploads folder; `GET /api/takserver/two-server/migration-database-deb-status` for ready/missing state.
- **Version safety** — Uploaded database `.deb` `Version` must match `dpkg-query` on the **current** Server One before alternate deploy and inside the migration worker (SSH check runs in the worker so `POST /migrate-database/start` returns quickly and avoids proxy “Failed to fetch” timeouts).

---

## What end users should do after upgrading

1. **Update infra-TAK** — **Console → Update Now** (or `git pull` + `sudo systemctl restart takwerx-console`).
2. **Two-server operators** planning a DB host move: open **TAK Server** → **Migrate database to new Server One** and follow steps 2–5 in the UI. See [TWO-SERVER-MIGRATE-DATABASE.md](TWO-SERVER-MIGRATE-DATABASE.md).

---

## Summary of changes

| Area | Change |
|------|--------|
| **API** | `POST .../install-ssh-key` — optional `install_host`, `install_user`, `install_port`. `POST .../deploy-server-one` — optional `deploy_target_host` (+ user/port); password save only when using alternate host. `POST .../migrate-database/start`, `GET .../migrate-database/log`, `GET .../migration-database-deb-status`. |
| **TAK Server UI** | Migrate section: host/user/port, steps 2–4, Start migration, log polling, database `.deb` upload strip, styling aligned with Update / DB maintenance cards. |
| **JS** | `takserver.js` — migrate helpers, upload, safer fetch error handling for migration start. |

---

## Operator checklist (release maintainer)

- [ ] Run **TESTING-UPDATES.md** protocol on test VPS if desired.
- [ ] Merge to `main`, tag `v0.3.1-alpha`, push tag: `git tag v0.3.1-alpha && git push origin v0.3.1-alpha`
- [ ] Recommend upgrade to deployments that need two-server DB migration.
