# infra-TAK v0.1.9

Release Date: 2026-03-04

---

## Guard Dog — UX and Hardening (v0.1.9-alpha)

- **Sidebar:** Guard Dog appears **directly under Console** when installed (high-priority placement).
- **Apply Docker log limits:** Button on the Guard Dog page applies 50 MB × 3 files per container (no redeploy of Authentik, Node-RED, etc.). Reduces risk of a single container log filling the disk.
- **Collapsible sections:** Notifications, Database maintenance (CoT), and Activity log are collapsible (click header to expand/collapse), matching TAK Server and Help page style.
- **4GB swap on deploy:** When Guard Dog is deployed (or auto-deployed with TAK Server), the console ensures a 4GB swap file at `/swapfile` exists and is enabled (from reference TAK Server Hardening script — memory stability under load).

---

## Authentik deploy reliability

- **Swap before stress:** At the start of Authentik deploy (before pulling images and starting containers), the console ensures 4GB swap exists. So the box has swap before postgres + server + worker run — reduces OOM and unhealthy on small VPS where Guard Dog (which also adds swap) may deploy later.
- **PostgreSQL then server:** PostgreSQL is started first; we wait for `pg_isready` (up to ~48s), then start the Authentik server and worker. Avoids the server hitting the DB before it accepts connections (fewer 502s and connection-refused on fresh installs).

---

## Guard Dog — Full Health Monitoring

Guard Dog is now fully operational with **9 monitors** for TAK Server plus service monitors for Authentik, MediaMTX, Node-RED, and CloudTAK.

| Monitor | Interval | Action |
|---------|----------|--------|
| Port 8089 | 1 min | Auto-restart after 3 failures |
| Process (5 Java procs) | 1 min | Auto-restart after 3 failures |
| Network (1.1.1.1 / 8.8.8.8) | 1 min | Alert only |
| PostgreSQL | 5 min | Restart + alert |
| CoT DB size | 6 hr | Alert at 25GB / 40GB |
| OOM | 1 min | Auto-restart + alert |
| Disk | 1 hr | Alert at 80% / 90% |
| Certificate (LE / TAK) | Daily | Alert at 40 days |
| **Root CA / Intermediate CA** | **Escalating** | **Alert at 90, 75, 60, 45, 30 days, then daily** |

Health endpoint on port 8888 for Uptime Robot / external monitoring.

## Certificate Management

### Create Client Certificates

New section on the TAK Server page. Enter a client name, load groups from TAK Server, assign Read (OUT), Write (IN), or Both permissions per group, and download the `.p12` file.

### Rotate Intermediate CA

Phased rotation workflow:
- Generate new Intermediate CA while keeping the old one active for transition
- Regenerates server cert, admin cert, user cert
- Old CA stays in truststore — existing clients continue working
- Users re-enroll via TAK Portal before the old CA is revoked
- **Revoke Old CA** button removes the old CA from the truststore when ready
- TAK Portal certs updated automatically during rotation

### Rotate Root CA

Hard cutover for the rare Root CA rotation (~10 year cycle):
- Generates entirely new PKI: Root CA, Intermediate CA, server cert, admin/user certs
- Updates truststore, CoreConfig, TAK Portal
- Restarts TAK Server
- All clients must re-enroll via QR code
- Double confirmation required

### Certificate Expiry Visibility

- **Console dashboard**: Root CA and Intermediate CA time remaining shown on the TAK Server module card (`Root 10y · Int 1y 12mo 4d`), color-coded green/yellow/red
- **TAK Server page**: Detailed expiry in the status banner and Certificates section
- **Rotate CA cards**: Each shows its relevant CA expiry with time remaining

## TAK Server Update

Upload a `.deb` package with a progress bar, cancel button, and success/failure indicators. The update is blocked if no file has been uploaded.

## UI Overhaul

### TAK Server Page — Collapsible Sections

All major sections are now collapsible cards (uppercase monospace headers, chevron toggle):
- Update TAK Server
- Database Maintenance (CoT)
- Certificates
- Rotate Intermediate CA
- Rotate Root CA
- Create Client Certificate
- Server Log

### Help Page — Collapsible Sections

All help sections converted to the same collapsible card style, left-aligned to match the rest of the console. Reordered: Deployment Order first, then Backdoor, Console Password, Reset Password, SSH Hardening, Uninstall All, Docs.

### Console Dashboard

Removed hidden "Manage" ghost elements from module cards for consistent card heights.

## Changes

- `app.py`: Authentik deploy (4GB swap before pull/start, start PostgreSQL first and wait for pg_isready then server/worker), Guard Dog deploy (9 monitors + service monitors, 4GB swap on deploy), Guard Dog sidebar under Console, Apply Docker log limits API + card, collapsible Guard Dog sections (Notifications, DB maintenance, Activity log), TAK Server update flow, client cert creation, cert expiry API, Intermediate CA rotation, Root CA rotation, revoke old CA, ca-info API, collapsible TAK Server/Help sections, console dashboard cert expiry
- `static/takserver.js`: Extracted TAK Server inline JS to external file
- `static/guarddog.js`: Guard Dog page JavaScript, `gdSectionToggle`, `gdApplyDockerLogLimits`
- `scripts/guarddog/`: All monitor scripts, health endpoint, SMS helper
- `docs/TAK_Server_OpenAPI_v0.json`: In-repo TAK Server OpenAPI 3.1 spec
- `docs/REFERENCES.md`: Added OpenAPI spec reference
- `docs/GUARDDOG.md`: Root CA / Int CA monitor and rotation workflow, 4GB swap, Docker log limits
- `docs/COMMANDS.md`: Pull dev only, restart console, pull+restart, disk full / container logs
- `docs/DISK-AND-LOGS.md`: Disk full recovery, Docker log limits, optional journal/prune
- `docs/HANDOFF-LDAP-AUTHENTIK.md`: Full v0.1.9 session state

## Status

All modules production-ready. Guard Dog fully operational (monitors, 4GB swap, Docker log limits button, collapsible UI). Certificate lifecycle management (create, rotate, revoke) verified.
