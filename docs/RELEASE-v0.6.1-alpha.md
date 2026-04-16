# infra-TAK v0.6.1-alpha

Release Date: April 2026

**Node-RED operator end-state:** See **[v0.6.2-alpha](RELEASE-v0.6.2-alpha.md)** (no static feeds, configurator → admin TLS passphrase → Deploy).

---

## Node-RED — no static example feeds in shipped `flows.json`

**Problem:** `build-flows.js` listed named feeds (`CA AIR INTEL`, `POWER-OUTAGES`) in `FEEDS`, which generated **static** ArcGIS engine tabs in the committed `flows.json`. Every `git pull` + deploy could surface those tabs in the editor on all boxes.

**Fix:** `FEEDS` is now **empty**. ArcGIS and FAA TFR feeds are added only via the **ArcGIS Configurator** (dynamic tabs preserved on deploy). See `nodered/CHANGELOG-nodered-v0.6.0-alpha.md` section 7 and `.cursorrules`.

**Fresh install:** The configurator opens **empty** until you save TAK settings and feed configs — that is correct. Nothing in the repo pre-fills your TAK Server or ArcGIS URLs; settings live in Node-RED global context on the server volume after you configure them.

### TLS (`TAK Mission API TLS`)

Shipped flows no longer point at `/certs/admin.pem` in git (that caused `ENOENT` when the cert volume was not mounted). Defaults are empty; **`deploy.sh` fills `/certs/admin.pem`** when `admin.pem` / `admin.key` exist under `/opt/tak/certs/files` on the host.

### Node-RED deploy (console) — enterprise wiring

**Problem:** The Node-RED `docker-compose` from the console did **not** mount TAK certs into the container and did **not** run `nodered/deploy.sh` on first deploy, so DataSync never “just worked” after Install.

**Fix (app.py):**

- Compose now includes **`/opt/tak/certs/files:/certs:ro`** and **`extra_hosts: host.docker.internal:host-gateway`** (CoT to TAK on the host).
- **First deploy** runs **`nodered/deploy.sh --no-pull`** after the container starts (same merge + TLS auto-fill as post-update).
- **Post-update** patches existing `~/node-red/docker-compose.yml` to add the mount and `extra_hosts` if missing, then `docker compose up -d`.

Remote Node-RED: same compose template; if **`~/infra-TAK/nodered/deploy.sh`** exists on the remote host, it is run after `compose up`.

---

## Other changes in this patch

Patch release — version bump so boxes running **Update Now** receive the complete v0.6.0-alpha stack (Guard Dog, Node-RED enhancements, etc.).

See [v0.6.0-alpha](RELEASE-v0.6.0-alpha.md) for Guard Dog, Postfix, and broader release notes.
