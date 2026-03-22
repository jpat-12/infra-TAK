# Two-server: migrate `cot` to a new Server One

Use the **TAK Server** page → **Migrate database to new Server One** (two-server mode only), or call the API from an authenticated session.

## What it does

**Start migration** does **not** install `takserver-database` or PostgreSQL on the new VM. It assumes the new host is already prepared (use **4. Deploy Server One (DB) on new host** on the migrate card, or an equivalent install). Then it:

1. Stops **TAK Server** on Server Two (Core).
2. **`pg_dump -Fc`** of database `cot` on the **current** Server One (saved settings still point there until migration finishes).
3. Copies the dump to the console, then to the **new** Server One.
4. On the new host: drops and recreates `cot`, **`pg_restore`**, verifies with `psql`.
5. Runs **Server One setup** (listen / `pg_hba` / firewall) on the **new** host so Core can connect.
6. Updates **CoreConfig.xml** (JDBC host + password) and **saved deployment settings** (`server_one.host`, merged SSH fields).
7. Starts **TAK Server** again and attempts to deploy the health agent to the new Server One.

If migration fails after TAK was stopped, the worker tries to **start `takserver` again** in `finally`.

### Prepare the new host (before Start migration)

On **Migrate database to new Server One**: steps **2–3** (SSH key), then **4. Deploy Server One (DB) on new host** — this calls the same deploy API with **`deploy_target_host`** so the database `.deb` is installed on the new IP **without** changing saved `server_one.host` (so migration still knows the old DB source).

## Version match

Keep the **same** `takserver-database` **Debian package version** on the new host as on the current Server One. The console compares `dpkg-deb -f … Version` on your uploaded `.deb` with `dpkg-query -W takserver-database` on the **current** Server One when you run **4. Deploy… on new host** and again when you click **Start migration**. Upload the matching `.deb` from tak.gov if the check fails.

## Prerequisites

- **Two-server** deployment with a valid current **Server One** in settings.
- **New** host already prepared like a normal Server One (PostgreSQL + TAK DB packages / `takserver-database` as after **Deploy Server One**). Existing **`cot` on the new host will be replaced**.
- **SSH to the new host** — use the same flow as the Split Server Wizard: on the migrate card, **2. Setup SSH key** and **3. Copy key to new host** (same APIs as steps 2–3; `sshpass` required on the console). Or install the matching public key manually.
- **Server Two (Core) IP** must be set in Settings so `pg_hba` can allow Core → new DB.

## UI

- **takserver-database .deb panel** — On the migrate card, status + drop zone use the **same `uploads/` folder** as Deploy and Upgrade. If the file was deleted, the panel shows what’s missing and you can upload again without hunting for the main upload area.
- **New Server One host** — IP or DNS (required).
- **SSH user (optional)** — overrides `server_one.ssh_user` for the new host only in saved settings.
- **SSH port** — optional; used for copy-key and migration SSH.
- **2 / 3 buttons** — same behavior as the two-server wizard for this console’s key and `ssh-copy-id` to the **new** host (not the current Server One).

## API (optional)

- `POST /api/takserver/two-server/migrate-database/start`  
  JSON body: `new_host` (required), `new_ssh_user` (optional), `new_ssh_port` (optional, number).
- `POST /api/takserver/two-server/install-ssh-key` — same as wizard; add **`install_host`** (and optional **`install_user`**, **`install_port`**) to copy the saved Server One public key to the **new** host instead of the configured Server One.
- `GET /api/takserver/two-server/migrate-database/log?index=N`  
  Same shape as the update log: `entries`, `total`, `running`, `complete`, `error`.

Returns **409** if a migration is already running.

### “Failed to fetch” when clicking Start migration

Older builds ran an SSH version check **before** the HTTP response returned; reverse proxies (Caddy/nginx) often cut that off as a timeout, which shows in the browser as **Failed to fetch**. Current code starts the worker immediately and runs the version check **inside** the migration log. Pull/restart infra-TAK and retry; if it still fails, check the browser Network tab for the real HTTP status or a proxy error page.

## After success

The page reloads; confirm **8443/8446** and clients. Keep the old Server One until you are satisfied; you can decommission it after DNS/firewall cutover if you use hostnames.
