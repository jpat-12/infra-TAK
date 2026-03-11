# infra-TAK v0.2.0

Release Date: 2026-03-11

---

## Authentik — Update config & reconnect (v0.2.0)

### Remote reconfigure

- When Authentik is deployed to a **remote** host, **Update config & reconnect** now runs entirely against the remote host:
  - SSHs to remote and runs `cd ~/authentik && docker compose up -d`.
  - Reads the API token from the remote `.env` via SSH (`cat ~/authentik/.env`).
  - All API steps (cookie domain, TAK Portal sync, Node-RED app, infra-TAK Console app, repair outpost, app access policies, show password) run against `http://<remote_host>:9090`.
- No local `~/authentik` or compose file is required on the console host for remote reconfigure.

### Local reconfigure — four apps and outpost

- **Reconfigure creates/repairs all four applications:** infra-TAK, MediaMTX, Node-RED, TAK Portal. Each gets a proxy provider and application in Authentik, and all are added to the embedded outpost (via safe add-only logic).
- **Outpost safety:** A single helper `_outpost_add_providers_safe()` is used everywhere we add a provider to the embedded outpost. It GETs the full outpost, normalizes providers to PKs, appends missing ones, and PATCHes only if the new list is not shorter. This prevents any code path (e.g. TAK Portal sync) from removing infra-TAK, MediaMTX, or Node-RED from the outpost.
- **Install dir fallback (local only):** If `~/authentik` has no `.env` or `docker-compose.yml`, the console tries `/opt/authentik` and then the Docker Compose project dir from the `authentik-server` container label so reconfigure can still run when the install lives elsewhere.

### Install check and deploy log

- **Reconfigure allowed when:** (1) deployment target is remote and deployed, or (2) `~/authentik/docker-compose.yml` exists, or (3) `docker ps` shows an authentik-server container, or (4) Authentik HTTP is reachable at the configured API URL. Avoids “Authentik not installed” when the stack is running but the console has no local compose file (e.g. remote deploy or different user).
- **Deploy log for reconfigure:** Clicking **Update config & reconnect** no longer redirects immediately. The **Update config & reconnect — Log** card is shown and streams output (same polling as full deploy). The log card is present for both “installed and running” and “installed but stopped” views.

---

## Current struggles (documented for v0.2.0)

- **Remote Authentik:** For reconfigure to succeed, the console must be able to SSH to the remote host and reach it on port **9090** (Authentik API). The remote `~/authentik/.env` must contain `AUTHENTIK_TOKEN` or `AUTHENTIK_BOOTSTRAP_TOKEN`. Firewall rules may be needed (console → remote:9090).
- **Applications not loading:** If only TAK Portal (or a subset) appears in the Authentik app launcher, run **Update config & reconnect** and watch the log. Then verify in Authentik Admin → Applications (infratak, stream, node-red, tak-portal) and Outposts → embedded outpost → Providers (all four attached). Re-run reconfigure if API errors (403, timeout) appear in the log.

---

## Console and module version display

- TAK Server version is shown on the Console card and TAK Server page header (from `takserver`, `takserver-core`, or `takserver-database` for two-server).
- CloudTAK page shows CloudTAK version in the header (e.g. “CloudTAK · v12.93.0”).

---

## Docs updated for v0.2.0

- **README.md:** Changelog entry for v0.2.0 (Authentik reconfigure local/remote, outpost safety, install check, deploy log; current struggles).
- **docs/HANDOFF-LDAP-AUTHENTIK.md:** Current session state set to v0.2.0; new section on v0.2.0 code changes and **Current struggles — Remote Authentik deployment and applications**.
- **docs/MAIN-VS-DEV-AUTHENTIK.md:** Summary of main vs dev (reconfigure, install check, deploy log); new sections **Remote deployment (v0.2.0)** and **Current struggles (v0.2.0)**.

---

## Handoff / merge note

- Version is **v0.2.0** (not v0.1.10). Use `v0.2.0-alpha` for the dev tag if desired.
- For selective merge to main, include at least: `app.py`, `README.md`, `docs/HANDOFF-LDAP-AUTHENTIK.md`, `docs/MAIN-VS-DEV-AUTHENTIK.md`, `docs/RELEASE-v0.2.0.md`.
