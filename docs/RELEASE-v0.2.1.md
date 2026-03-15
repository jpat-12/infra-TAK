# infra-TAK v0.2.1-alpha

Release Date: 2026-03-14

---

## Highlights

- **Security hardening** — Auth trust, upload safety, CSRF baseline, rate limiting, security headers
- **Server metrics** — CPU, RAM, disk shown on dashboard and module pages (local and remote)
- **TAK Server JVM heap** — Set and view heap size via console; recommended value from total RAM
- **Guard Dog server nickname** — Optional label (e.g. Production, Staging) in alerts for multi-server setups
- **CA rotation and TAK Portal** — Rotate replaces server cert; Sync TAK Server CA button; revoke UI cleanup; tak-ca.pem only
- **Caddy cert expiration** — Shown on the dashboard card; planned for Caddy page top row (after the URL)

---

## Security hardening

Based on [SECURITY-AUDIT-v0.2.0-alpha.md](SECURITY-AUDIT-v0.2.0-alpha.md):

- **Auth header trust** — `X-Authentik-Username` is only trusted when the request comes from loopback (127.0.0.1 / ::1), so SSO headers from untrusted origins cannot bypass login.
- **CloudTAK logs endpoint** — Container name validated with an allowlist regex; `lines` clamped to 1–500; local `docker logs` uses argv-style subprocess (no shell interpolation).
- **TAK package uploads** — Filenames sanitized with `werkzeug.utils.secure_filename()` before writing to disk.
- **CSRF baseline** — State-changing APIs under `/api/*` (POST/PUT/PATCH/DELETE) require same-origin (Origin/Referer host must match request host). Localhost-only Guard Dog script endpoint is exempt.
- **Rate limiting** — Login: 12 attempts per 5 minutes per client IP. API writes: 240 requests per minute per client IP. Implemented without new dependencies.
- **Security headers** — X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy, Content-Security-Policy (compatibility mode), Strict-Transport-Security on HTTPS.

---

## Server metrics

- **Console dashboard** and **module detail pages** now show **server metrics** (CPU, RAM, disk) for:
  - The **local host** (where the console runs).
  - **Remote deployment targets** — When a module (Authentik, CloudTAK, MediaMTX, Node-RED) is deployed to another server via SSH, that host’s metrics are fetched via SSH and displayed on the module page.
- Helps operators see resource usage per server at a glance without logging in elsewhere.

---

## TAK Server — JVM heap

- The TAK Server page shows:
  - **Recommended heap** — Derived from total system RAM (for the host running TAK Server core).
  - **Current heap** — If set via the systemd drop-in `/etc/systemd/system/takserver.service.d/heap.conf`.
- **Set JVM heap** — In the Controls area you can set a custom heap (e.g. 4G, 8G). The console writes the drop-in and restarts TAK Server so the new `-Xmx` takes effect.
- API: `GET /api/takserver/heap-info`, plus existing heap set/apply endpoints.

---

## Guard Dog — server nickname

- In **Guard Dog → Notifications** you can set an optional **Server nickname** (e.g. Production, Staging).
- Alerts (email/SMS) then include the nickname plus IP/FQDN (e.g. `Production (63.250.55.132)`) so you can tell which server sent the alert when monitoring multiple infra-TAK hosts.
- **Save email & nickname** applies the nickname without redeploying Guard Dog. Re-deploy or **Update** after changing server IP or FQDN to refresh the identifier.
- Documented in [GUARDDOG.md](GUARDDOG.md).

---

## CA rotation and TAK Portal

- **Rotate CA** — Now **replaces the server cert** with one signed by the new CA (no “keep existing server cert” option). Planned outage; after rotation, users re-enroll by scanning the new QR (no need to delete the server first). See [GUARDDOG.md](GUARDDOG.md) and certificate docs for workflow.
- **Sync TAK Server CA** — On the **TAK Portal** page, **Controls** section: new **Sync TAK Server CA** button (🔄). Pushes `tak-ca.pem` to the portal container so enrollment and API use the current CA. Same logic as deploy (tak-ca.pem only).
- **Revoke** — Revoke section hides when there are no old CAs. CA/revoke state refetches on visibility change and `pageshow` so the Revoke option disappears after use.
- **Single CA artifact** — Deploy, sync, revoke, and rotate use only **tak-ca.pem**. Removed caCert.p12 and transition-bundle behavior.

---

## Caddy — certificate expiration

- **Cert expiration** is available for Caddy (Let's Encrypt) and is shown on the **dashboard card**.
- On the **Caddy module page**, the top row currently shows only status and URL (e.g. "Caddy is active · test8.taktical.net"); **cert expiration is not yet in that top row**. Planned: show cert expiration in the Caddy page top row, after the URL, so you don’t have to rely on the card alone.

---

## Upgrading from v0.2.0

```bash
cd $(grep -oP 'WorkingDirectory=\K.*' /etc/systemd/system/takwerx-console.service)
git pull
sudo systemctl restart takwerx-console
```

No schema or config changes. All existing deployments and settings are preserved.

---

## Status

Alpha. Not production-ready. Suitable for testing and evaluation; see [SECURITY-AUDIT-v0.2.0-alpha.md](SECURITY-AUDIT-v0.2.0-alpha.md) for hardening roadmap.
