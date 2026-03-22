# Main vs dev: Authentik reconfigure and app list

Quick reference for how Authentik “Update config & reconnect” and the four apps (infra-TAK, MediaMTX, Node-RED, TAK Portal) diverged between main and dev, and what dev does now.

## Main branch (baseline)

### Reconfigure path (`run_authentik_deploy(reconfigure=True)`)

- Ensures containers are up, sets cookie domain, **does not** create or repair applications.
- Calls: `_ensure_proxy_providers_cookie_domain`, `_ensure_app_access_policies`, then domain sync (AUTHENTIK_HOST, brand, outpost).
- Outpost sync: **PUT** with `list(op.get('providers', []))` → keeps existing providers, does not add or remove.
- **Does not** call:
  - `_ensure_authentik_nodered_app`
  - `_ensure_authentik_console_app`
  - `_sync_authentik_takportal_provider_url`
  - Any “repair outpost” step.

So on main, the four apps are **only** created in the **full deploy** (Step 12). Reconfigure never creates them; it only keeps whatever providers were already on the outpost.

### Install check for reconfigure

- Single check: `os.path.exists(os.path.expanduser('~/authentik/docker-compose.yml'))`.
- No Docker check, no HTTP check, no remote-deploy check.

### UI: “Update config & reconnect”

- `reconfigureAk()`: on success does **immediate redirect** `window.location.href='/authentik'`.
- No deploy log is shown; user only sees the page reload. Log is still written server-side to `authentik_deploy_log`.

---

## Dev branch (current behavior)

### Why only TAK Portal was left

- Some code paths were **PATCHing the embedded outpost** with a **shorter** provider list (e.g. only TAK Portal), which removed infra-TAK, MediaMTX, and Node-RED from the outpost.
- Fix: **never shorten** the provider list. All “add provider to outpost” logic now goes through `_outpost_add_providers_safe()`: load outpost, normalize providers to PKs, **append** missing ones, PATCH only if the new list is not shorter than the original.

### Reconfigure path on dev (aligned with “had it working”)

1. **Same as main**: cookie domain, domain sync, app access policies.
2. **Added** so reconfigure can restore the four apps and outpost:
   - `_sync_authentik_takportal_provider_url(settings)` — TAK Portal provider + app + on outpost.
   - `_ensure_authentik_nodered_app(...)` — Node-RED provider + app + on outpost.
   - `_ensure_authentik_console_app(...)` — infra-TAK + MediaMTX providers + apps + on outpost.
   - `_repair_embedded_outpost_all_apps(...)` — ensure all four app providers are on the embedded outpost (by slug: infratak, stream, node-red, tak-portal).

So on dev, **“Update config & reconnect”** both preserves existing providers (via safe outpost updates) and (re)creates the four applications and adds their providers to the outpost if needed.

### Install check for reconfigure

- Replaced single file check with `_authentik_installed_for_reconfigure()`:
  - Remote and marked deployed → allow.
  - `~/authentik/docker-compose.yml` exists → allow.
  - `docker ps` shows an `authentik-server` container → allow.
  - Authentik HTTP reachable (e.g. 127.0.0.1:9090 or configured URL) → allow.
- Avoids “Authentik not installed” when the stack is running but the compose file path or Docker visibility differs (e.g. different user, containerized console).

### UI: “Update config & reconnect”

- `reconfigureAk()`: on success **does not** redirect immediately.
- Shows the deploy log card (`ak-log-card`), clears/shows “Starting update config & reconnect...”, and starts **polling** `authentik_deploy_log` (same as full deploy).
- User sees the same “Update config & reconnect — Log” (or “Deploy Log”) stream as during a full deploy.
- The log card is present in both “installed and running” and “installed but stopped” views so the reconfigure log is visible whenever they use the button.

---

## Summary

| Aspect | Main | Dev |
|--------|------|-----|
| Reconfigure creates 4 apps | No | Yes (Node-RED, console, TAK Portal sync, repair outpost) |
| Reconfigure can shrink outpost | No (PUT keeps list) | No (safe add-only PATCH) |
| “Authentik not installed” when containers up | Can happen (file-only check) | Avoided (file + docker + HTTP + remote) |
| Deploy log for reconfigure | No (redirect only) | Yes (show card + poll) |

So we didn’t “go back” from main; we kept main’s “don’t remove providers” idea and added:

1. Safe outpost updates so no path can remove existing apps.
2. Reconfigure steps that (re)create the four apps and repair the outpost so one click can restore the previous “working” state.
3. Broader “installed” check and deploy log for reconfigure for better UX and reliability.

---

## Remote deployment (v0.2.0)

When **Authentik deployment target is remote** (`authentik_deployment.target_mode == 'remote'`):

- **Reconfigure** does **not** use local `~/authentik` or `_find_authentik_install_dir()`. It calls `_run_authentik_reconfigure_remote(settings, deploy_cfg, plog)` which:
  1. SSHs to the remote host and runs `cd ~/authentik && docker compose up -d`.
  2. Reads the API token from the remote `.env` via `_get_authentik_env_value(settings, ...)` (which SSHs and cats `~/authentik/.env`).
  3. Uses `_get_authentik_api_url(settings)` → `http://<remote_host>:9090` for all API calls.
  4. Runs the same API steps as local reconfigure: cookie domain, TAK Portal sync, Node-RED app, console app, repair outpost, app access policies, show password.
- **Install check** for reconfigure: if remote and deployed (and remote host set), we allow reconfigure without any local file or Docker check.

**Requirements for remote reconfigure to work:** Console must be able to (1) SSH to the remote host (key or password), and (2) reach the remote host on port **9090** (Authentik API). The remote `~/authentik/.env` must contain `AUTHENTIK_TOKEN` or `AUTHENTIK_BOOTSTRAP_TOKEN`.

---

## Current struggles (v0.2.0)

- **Remote Authentik:** If “Update config & reconnect” still fails for a remote deploy, check: (1) SSH from console to remote works (Authentik page → Deployment Target → Test SSH); (2) from the console host, `curl -s -o /dev/null -w "%{http_code}" http://<remote_ip>:9090/` returns 200/302/301; (3) remote `~/authentik/.env` has a token line. Firewall must allow console → remote:9090.
- **Applications not loading (only TAK Portal or subset):** Ensure “Update config & reconnect” has run successfully at least once (watch the log). Then in Authentik Admin: Applications should list infra-TAK, MediaMTX, Node-RED, TAK Portal; Outposts → embedded outpost → Providers should list all four. If not, run reconfigure again and look for API errors (403, timeouts) in the log.
