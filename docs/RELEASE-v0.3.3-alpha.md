# infra-TAK v0.3.3-alpha

Release Date: March 2026

---

## Highlights

- **Federation Hub** — Full deploy-and-manage lifecycle for TAK Server Federation Hub on a remote VPS. Upload the `.rpm`, configure connection details, deploy with one click, and manage the running service from the console. Includes remote host health metrics (CPU, RAM, Disk, Uptime), service status, CA rotation, and update-in-place. Federation Hub sits behind **Authentik forward-auth** (same pattern as Node-RED / MediaMTX) so access is SSO-protected.
- **Federation Hub — certificate metadata** — Editable certificate DN fields (State, OU, Organization, City, Country) and custom certificate password, saved in settings and applied during deploy and CA rotation.
- **Federation Hub — Guard Dog monitor** — New `tak-fedhub-watch.sh` script monitors the remote Fed Hub service, connectivity, and disk. Deployed automatically with Guard Dog and included in `_auto_update_guarddog()` on console restart.
- **TAK Portal — `/locate/*` public path** — Caddy `@public` matcher for TAK Portal now includes `/locate/*`, allowing the new Locate feature to bypass forward-auth.
- **Fix: remote unattended-upgrades toggle** — Disabling unattended upgrades on remote hosts (Fed Hub, remote DB) no longer fails. Previous versions used `pkill -f` inside the SSH command, which matched and killed its own SSH session (exit 255). Now uses `systemctl stop/disable` exclusively.
- **Fix: SSH error reporting** — `_ssh_probe` now reports the exit code and command prefix when SSH returns no output, instead of a blank error message.

---

## What end users should do after upgrading

1. **Update infra-TAK** — **Console → Update Now** (or `git pull` + `sudo systemctl restart takwerx-console`).
2. **Update Guard Dog** — If Guard Dog is deployed, click **↻ Update Guard Dog** so scripts on disk include the new `tak-fedhub-watch.sh` and any fixes.
3. **Federation Hub users** — Open the new **Federation Hub** page in the console to deploy or manage your Fed Hub.

---

## Summary of changes

| Area | Change |
|------|--------|
| **Federation Hub** | Full module: deploy `.rpm` to remote VPS, service management (start/stop/restart), status polling, remote host metrics, CA rotation, update-in-place, certificate metadata (DN + password), Authentik forward-auth integration, Caddy reverse proxy block generation. |
| **Guard Dog** | New `scripts/guarddog/tak-fedhub-watch.sh` — remote Fed Hub health monitor. `_auto_update_guarddog()` copies Fed Hub script and installs its systemd timer on console restart. |
| **Caddy** | TAK Portal `@public` matcher adds `/locate/*`. Federation Hub gets its own Caddy block with forward-auth on deploy. Startup migration regenerates Caddyfile when Fed Hub is deployed. |
| **Unattended Upgrades** | Remote disable rewritten — removed `pkill`/`pgrep` (caused SSH self-kill), uses `systemctl stop/disable` only, 90s SSH timeout. |
| **SSH** | `_ssh_probe` returns `exit <code>, no output. cmd: <safe_cmd>` instead of empty string on silent failures. |
| **Docs** | `docs/FED-HUB.md` — Federation Hub overview. `docs/FEDHUB-LOGIN-RUNBOOK.md` — Fed Hub OAuth login troubleshooting. |

---

## Operator checklist (release maintainer)

- [ ] Run **TESTING-UPDATES.md** protocol on test VPS.
- [ ] Selective merge to `main`, tag **`v0.3.3-alpha`**, push tag (see **docs/COMMANDS.md**).
- [ ] Deployments with Guard Dog: **Update Guard Dog** after console update so Fed Hub monitor and fixes are on disk.
