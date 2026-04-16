# infra-TAK v0.6.2-alpha — Node-RED DataSync operator end-state

Release Date: April 2026

---

## What “good” looks like after Update Now

1. **No example feeds in the editor** — Shipped `flows.json` does **not** include static tabs like “CA AIR INTEL” or “POWER-OUTAGES”. Those were repo defaults; they are removed (`FEEDS` is empty in `build-flows.js`).

2. **Configurator is the source of truth** — Operators open **`/configurator`**, choose **ArcGIS** or **FAA TFR**, walk the wizard, and **Save** their feed. Feeds appear as **dynamic engine tabs**; `deploy.sh` merges template code without wiping configs.

3. **TAK TLS uses the host admin cert** — The Node-RED container mounts **`/opt/tak/certs/files` → `/certs`** (compose from console + post-update patch). **`deploy.sh`** sets **`tls_tak`** to **`/certs/admin.pem`** and **`/certs/admin.key`** when those files exist on the host.

4. **Passphrase + Deploy in Node-RED** — The **private key passphrase** is not stored in git. Operators open the **Node-RED editor** → **`TAK Mission API TLS`** → confirm cert paths (or use the mounted files) → enter the **key passphrase** → click **Deploy** in the editor. Mission API and CoT TCP then authenticate.

That sequence is the intended **enterprise** path: update infra-TAK → configure feeds in the UI → one TLS step in the editor → Deploy.

---

## Technical changes (summary)

| Area | Behavior |
|------|----------|
| **Shipped flows** | Configurator + TLS + TCP templates only; no named static ArcGIS feeds. |
| **Console Node-RED deploy** | Compose includes cert mount + `host.docker.internal`; first deploy runs `nodered/deploy.sh --no-pull`. |
| **Post-update** | Patches existing `~/node-red/docker-compose.yml` if mount/`extra_hosts` missing; runs flow sync. |
| **Remote Node-RED** | Same compose template; runs `~/infra-TAK/nodered/deploy.sh --no-pull` when present. |

Details: `nodered/CHANGELOG-nodered-v0.6.0-alpha.md` (sections 7–8), `.cursorrules` (Node-RED / `FEEDS`), and earlier v0.6.1 notes merged here.

---

## Related

- [v0.6.0-alpha](RELEASE-v0.6.0-alpha.md) — Guard Dog, Postfix, broader stack.
- [v0.6.1-alpha](RELEASE-v0.6.1-alpha.md) — Patch notes (may overlap; **v0.6.2 is the Node-RED end-state release**).
