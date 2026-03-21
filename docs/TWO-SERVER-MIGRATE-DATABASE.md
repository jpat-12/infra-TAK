# Two-server: migrate `cot` to a new Server One

Use the **TAK Server** page → **Migrate database to new Server One** (two-server mode only), or call the API from an authenticated session.

## What it does

1. Stops **TAK Server** on Server Two (Core).
2. **`pg_dump -Fc`** of database `cot` on the **current** Server One.
3. Copies the dump to the console, then to the **new** Server One.
4. On the new host: drops and recreates `cot`, **`pg_restore`**, verifies with `psql`.
5. Runs **Server One setup** (listen / `pg_hba` / firewall) on the **new** host so Core can connect.
6. Updates **CoreConfig.xml** (JDBC host + password) and **saved deployment settings** (`server_one.host`, merged SSH fields).
7. Starts **TAK Server** again and attempts to deploy the health agent to the new Server One.

If migration fails after TAK was stopped, the worker tries to **start `takserver` again** in `finally`.

## Prerequisites

- **Two-server** deployment with a valid current **Server One** in settings.
- **New** host already prepared like a normal Server One (PostgreSQL + TAK DB packages / `takserver-database` as after **Deploy Server One**). Existing **`cot` on the new host will be replaced**.
- **SSH to the new host** — use the same flow as the Split Server Wizard: on the migrate card, **2. Setup SSH key** and **3. Copy key to new host** (same APIs as steps 2–3; `sshpass` required on the console). Or install the matching public key manually.
- **Server Two (Core) IP** must be set in Settings so `pg_hba` can allow Core → new DB.

## UI

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

## After success

The page reloads; confirm **8443/8446** and clients. Keep the old Server One until you are satisfied; you can decommission it after DNS/firewall cutover if you use hostnames.
