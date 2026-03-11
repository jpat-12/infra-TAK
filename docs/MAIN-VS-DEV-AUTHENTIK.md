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
