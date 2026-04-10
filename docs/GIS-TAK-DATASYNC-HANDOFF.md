# Handoff: GIS → TAK DataSync (Node-RED) — infra-TAK module

## Background

The goal is a **reusable path from ArcGIS Feature Services into TAK Server**, using **Node-RED** and **DataSync** as the way to **publish and remove** map content (not just stream CoT over TCP). A prior attempt (Nov 2024) used PGE outage polygons: one flow to **GET** data and push CoT into a mission, and a second **cleanup** flow to list mission UIDs and **DELETE** to avoid duplicates. That approach never behaved reliably: **ongoing outages** tended to get **re-added each poll**, producing **stacked duplicate polygons** on the map.

As of **v0.5.8-alpha**, `nodered/flows.json` includes both an **ArcGIS Configurator** tab (`GET /configurator`) and an **ArcGIS → TAK Engine** tab (disabled by default) implementing the single reconciliation loop described below. The older PGE work was never committed. See *Maintainer log* for current status.

## Problem statement

1. **DataSync** is the practical API surface for **persisting** CoT in a mission and **removing** it later.
2. **Polling** without a clear **reconciliation model** (diff "what the feed says now" vs "what's already in the mission") causes **duplicates** or **racey** delete-then-re-add behavior.
3. **ArcGIS Feature Services** vary by layer: field names, geometry types, date fields, etc. Manually finding the **right index in the array** / the right attribute in each feature is what was hardest in Node-RED function nodes.

## Product direction (infra-TAK module — implemented)

A **"feed configurator"** (web UI served from Node-RED) that:

1. Accepts an **ArcGIS Feature Service** (or layer) URL.
2. Calls the **REST API** to expose **layer metadata** (fields, types) and **sample features** so the user isn't guessing array indices.
3. Lets the user define:
   - **Which field** is the stable **ID** (for mission UID / dedup).
   - **Which field** is **time** (for "only show data < 72 hours" and expiry).
   - **Geometry**: polygons vs points.
   - **CoT styling**: stroke/fill color (ARGB), fill opacity, line thickness, line style (solid/dashed/dotted/outlined), closed polygon toggle, label toggle + label field + center-in-shape option.
   - **Source filter**: checkbox selection from distinct ArcGIS values + free-form manual entry, merged into a combined `WHERE` clause.
   - **Remarks template**: clickable field picker to build the remarks string from feature attributes.
   - **TTL (hours)**: dual role — filters ArcGIS query by time window AND sets CoT `stale` time.
   - **Mission name**: target TAK Server DataSync mission for the engine.
4. Emits **runtime config** (JSON stored in Node-RED flow context with `localfilesystem` persistence) that the **engine flow** reads — configs survive Node-RED container restarts.
5. Supports **multiple named configurations** — save, load, and manage from a card-based UI.

## Recommended runtime behavior (avoid duplicate stacking)

**Single reconciliation loop** (conceptually), not "delete everything" vs "add everything" as two unrelated timers unless carefully sequenced:

1. **Fetch current features** from ArcGIS (with `where`/time filter as needed, e.g. last 72h).
2. **Fetch current mission contents** (or DataSync mission API) and build a **set of UIDs** already present.
3. **Diff**:
   - **In ArcGIS, not in mission** → **PUT/add** CoT for that UID.
   - **In mission, not in ArcGIS** (or older than TTL) → **DELETE** that UID.
   - **In both** → **no-op** (or optional **update** only if geometry/attributes changed — compare hash or `edit` timestamp if available).

Stable **UID** must be **deterministic** (e.g. `prefix + feature id` or hash of id + layer id), identical every poll.

**Current implementation** uses `arcgis-{featureID}` as the UID scheme, where `featureID` is the value of the user-selected ID field from the ArcGIS layer.

## References / packages already in mind

| Item | Role |
|------|------|
| [node-red-contrib-tak](https://github.com/snstac/node-red-contrib-tak) | CoT encode/decode, TAK protocol, TCP/mesh patterns. Engine outputs CoT JSON in the `_attributes` format this node expects. |
| [node-red-contrib-tfr2cot](https://flows.nodered.org/node/node-red-contrib-tfr2cot) | Reference for **DataSync** patterns: `dataSyncSubscription`, pairing **HTTP request** (method from msg) with Mission API. Greg Albrecht's blog post on RIIS covers the wiring in detail. |
| Paul's DataSync flow (user's prior work) | Pattern for DataSync PUT/DELETE with Mission API — used as the basis for the engine's reconciliation approach. Key insight: `PUT /Marti/api/missions/{name}/contents?creatorUid={uid}` with `{uids: [uid]}` payload to add, `DELETE /Marti/api/missions/{name}/contents?uid={uid}&creatorUid={uid}` to remove. |
| TAK Mission / DataSync API | Add/remove persisted mission content. Ports: **8443** for Mission API (HTTPS with client cert), **8089** for streaming TCP CoT. Exact paths depend on TAK Server version and `CoreConfig.xml`. |

**Note:** `tfr2cot` docs explicitly call out that **saving to DataSync** does not auto-remove stale items — aligns with building **explicit DELETE** or reconciliation in infra-TAK.

## Operational / TLS notes

- **HTTP request** to Mission API over TLS needs a **TLS config** node in Node-RED with the **client cert + key + CA** matching what TAK Server trusts. The engine includes a placeholder `tls-config` node (`tls_tak`) that the user must configure in the Node-RED editor with their certs.
- TAK Portal's "Create Integration" flow auto-generates client certs tied to a group — use those for Node-RED's TLS config.
- Errors like **`ERR_SSL_SSLV3_ALERT_CERTIFICATE_UNKNOWN`** usually mean **wrong CA**, **self-signed** cert not trusted in Node-RED, or **hostname mismatch** — fix in Node-RED TLS config, not by disabling verification in production.
- **v0.5.8-alpha fix**: `cert-metadata.sh` ownership was broken after TAK Server upgrades (owned by `root:root` instead of `tak:tak`), preventing TAK Portal from generating certs for Node-RED integrations. Now auto-healed on console startup.

## What's built inside infra-TAK (current state)

### Slice 1: Configurator UI ✅

**File:** `nodered/configurator.html` — served at `GET /configurator`

Full-featured 5-step wizard:
1. **Paste URL** → auto-detect Feature Service, list layers
2. **Pick layer** → fetch fields, sample data (scrollable table), geometry type detection
3. **Configure fields** — ID field, time field, source filter field with distinct value checkboxes + manual entry, `WHERE` clause auto-generation
4. **Shape styling** — stroke color, fill color, fill opacity, line thickness, line style, closed polygon, label toggle + field + centering, remarks field picker
5. **Export** — TTL hours, CoT type prefix, UID prefix, mission name, named save with card management

**Backend API endpoints** (all in `nodered/build-flows.js`):
- `POST /api/arcgis/service` — proxy to ArcGIS service metadata
- `POST /api/arcgis/layer` — proxy to ArcGIS layer metadata
- `POST /api/arcgis/sample` — proxy to ArcGIS sample features
- `POST /api/arcgis/distinct` — proxy to ArcGIS distinct values query
- `POST /api/config/save` — save single config to flow context
- `POST /api/config/save-all` — save all configs at once
- `GET /api/config/load` — load all saved configs
- `POST /api/tak-settings/save` — save TAK server connection settings
- `GET /api/tak-settings/load` — load TAK server connection settings

### Slice 2: Engine flow ✅ (first pass — needs wiring + testing)

**Flow tab:** "ArcGIS → TAK Engine" (disabled by default in `flows.json`)

Node chain:
1. **`eng_inject`** — timer, every 5 minutes
2. **`eng_load`** — loads all saved ArcGIS configs + global TAK settings from flow context; filters for configs that have a `missionName` and valid TAK settings
3. **`eng_split`** — splits array into one msg per config
4. **`eng_build_q`** — builds ArcGIS query URL with `WHERE` clause + dynamic time filter (now − TTL hours)
5. **`eng_http_ag`** — HTTP GET to ArcGIS Feature Service
6. **`eng_parse`** — transforms ArcGIS features → CoT JSON array:
   - Deterministic UID: `arcgis-{featureID}`
   - CoT type from config (`a-o-G` for points, `u-d-f` for polygons, etc.)
   - Hex → ARGB integer color conversion (with alpha from fill opacity)
   - Polygon rings → `link` array with `point` sub-elements
   - Remarks built from user-selected fields
   - Styling: `strokeColor`, `fillColor`, `strokeWeight`, `strokeStyle`, `labels_on`, `labelField`
7. **`eng_build_m`** — builds TAK Mission API URL for GET mission contents
8. **`eng_http_m`** — HTTP GET mission contents (uses `tls_tak` TLS config)
9. **`eng_reconcile`** — diff ArcGIS UIDs vs mission UIDs:
   - **Port 1**: CoT JSON for new features → wire to `node-red-contrib-tak` TCP output
   - **Port 2**: HTTP action messages (PUT for adds, DELETE for stales) → wire to Mission API HTTP request node
10. **`eng_http_action`** — executes PUT/DELETE against Mission API (uses `tls_tak`)
11. **Debug nodes** at key points for visibility

### Slice 3: Docs (this file + release notes)

- This handoff doc
- `docs/RELEASE-v0.5.8-alpha.md`

## Resolved decisions

| Decision | Resolution |
|----------|------------|
| **Config storage** | Node-RED **flow context** with `localfilesystem` persistence (survives container restarts). Configured via `settings.js` `contextStorage`. |
| **UID scheme** | `arcgis-{value_of_id_field}` — deterministic, stable across polls. |
| **Auth: ArcGIS** | Public services for now (no token). Token auth is a future enhancement. |
| **Auth: TAK certs** | Placeholder `tls-config` node in engine; user uploads client cert/key/CA in Node-RED editor. TAK Portal "Create Integration" generates these. |
| **Scale / batching** | Split node processes configs one at a time. No explicit batching of features yet — adequate for hundreds of features per poll. |
| **Color format** | Hex → ARGB integer conversion in `eng_parse`. Alpha channel derived from fill opacity percentage. |

## Open items / future work

- **End-to-end testing**: Enable the engine tab, configure TLS, point at a live ArcGIS + TAK Server, and verify the full loop.
- **Update detection**: Currently no-op for features already in mission. Could compare a hash of geometry/attributes to detect changes and re-push updated CoT.
- **ArcGIS token auth**: Add optional token field to configurator for secured services.
- **Multiple geometry support per config**: Currently one geometry type per config. Could detect mixed layers.
- **Error handling / retry**: Engine has basic `node.warn` logging but no retry logic for failed HTTP requests.
- **TAK streaming CoT**: Port 1 of reconcile outputs CoT JSON but needs `node-red-contrib-tak` wired to actually stream to TAK Server on port 8089.

## One-line elevator pitch

**"ArcGIS Feature Service URL + guided field/style mapping → reproducible Node-RED + DataSync lifecycle (add / keep / delete), with TTL like 'only show last 72 hours' — shipped as an infra-TAK module."**

---

## Maintainer log (keep this doc current)

**Why this section exists:** Cursor (and similar) may **not** reload the full chat transcript into the assistant on every turn. **Treat this file as the source of truth** for Node-RED / GIS–DataSync decisions. When you agree on a plan in chat, **append a short bullet here** so the next session does not depend on chat memory.

### 2026-04-10 — v0.5.9-alpha shipped (Boot sequence hardening)

- **Guard Dog Boot Sequencer** (`tak-boot-sequencer.sh`): On reboot, all Docker containers are stopped so TAK Server gets exclusive CPU during Java initialization. Nothing else starts until port 8089 is listening.
- **Authentik staggered start** (`tak-post-start.sh`): PostgreSQL starts first → waits for `pg_isready` → then `docker compose up -d` brings server/worker/LDAP. Eliminates "FATAL: sorry, too many clients already" PostgreSQL connection storms.
- **PostgreSQL tuning — idempotent compose patching** (`app.py`): New `_ensure_authentik_compose_patches()` helper injects `max_connections=300`, `idle_session_timeout=300s`, and TCP keepalives into `docker-compose.yml`. Called from `run_authentik_deploy(reconfigure)`, `authentik_control(update)`, and `_apply_authentik_pg_tuning`. Previously, reconfigure and update code paths skipped compose patching, and `_apply_authentik_pg_tuning` could inadvertently clear `ALTER SYSTEM` settings.
- **Priority service ordering with connection-safe stagger**: TAK Server → Authentik → TAK Portal start as fast as possible (critical trio). CloudTAK and Node-RED get 30-second cooldown delays before their `docker compose up -d` to prevent Docker iptables rule rebuilds from disrupting active TAK client connections on port 8089. MediaMTX (systemd-native, no Docker iptables impact) starts last with a shorter delay.
- **`docker-stagger.service` disabled**: This older systemd service conflicted with `tak-boot-sequencer.sh`, causing repeated PostgreSQL stops/restarts during boot. Must be disabled on existing VPS installs (`systemctl disable --now docker-stagger.service`).
- **Validated on three topologies**:
  - **Single server (Responder)**: Critical trio 2m 53s, full stack 4m 42s
  - **Single server (tak-10, beefy)**: Critical trio 1m 03s, full stack 2m 50s
  - **Two-server split**: Critical trio 2m 22s, full stack 4m 15s
- **Results**: Zero PostgreSQL errors, zero LDAP 502s (except expected cold-cache first binds ~80s), LDAP binds under 1ms once warm, TAK client connections stable through CloudTAK/Node-RED startup. ATAK clients may see one data reception timeout on first connect during cold boot (normal TAK Server behavior — clients reconnect immediately).

### 2026-04-08 — v0.5.8-alpha shipped (Configurator + Engine + cert fix)

- **Configurator UI complete**: Full 5-step wizard with ArcGIS proxy APIs, distinct-value checkboxes + manual source filter, shape styling (stroke/fill/opacity/thickness/style/labels/remarks picker), named config save/load with card management, TAK Server settings panel, mission name field. Served at `GET /configurator`.
- **Engine flow built** (first pass, `build-flows.js`): 11-node chain implementing the single reconciliation loop. Disabled by default — user enables in Node-RED editor after configuring TLS certs. Polls every 5 min, iterates all saved configs with a `missionName`, queries ArcGIS, transforms to CoT JSON, diffs against TAK mission contents, emits PUT/DELETE via DataSync API.
- **Config persistence**: `settings.js` configured for `localfilesystem` context storage; configs and TAK settings survive Node-RED container restarts.
- **cert-metadata.sh fix**: Ownership was broken after TAK Server upgrades (`root:root` instead of `tak:tak`), preventing TAK Portal cert generation. Fixed in `app.py` (all code paths that touch the file) + self-healing on console startup for existing servers.
- **Key reference material consumed**: Paul's DataSync flow patterns (PUT/DELETE to Mission API), Greg Albrecht's RIIS blog post on `node-red-contrib-tak` (CoT JSON `_attributes` format), `node-red-contrib-tfr2cot` subflow JSON (DataSync subscription wiring).
- **What's next**: End-to-end test with live ArcGIS service + TAK Server. Wire `node-red-contrib-tak` to Port 1 of reconcile node for TCP CoT streaming. Test polygon and point rendering in TAK clients.

### 2026-04 — earlier session notes

- **Repo state:** `nodered/` includes committed flows (Configurator UI + Engine).
- **Operational tie-in (high-volume CoT / ADSB):** TAK Server retention should run **hourly** when possible (same 24h window, smaller deletes per run). Overlapping multi-hour `DELETE` on `cot_router` can exhaust RAM/swap; infra-TAK **v0.5.2+** adds Guard Dog **`tak-retention-guard.sh`** as a safety net (kill stuck DELETEs, batched cleanup). Not a substitute for hourly retention — complementary.

### 2026-02-06 — recovered plan (paste from prior chat; canonical example layer)

**Product intent (Node-RED tab):** Help the user **identify the slice of data they want from an ArcGIS URL** without manually opening raw GET responses, walking nested JSON, or guessing array indices. The tab is **discovery + filter definition + export** so building downstream flows (CoT, DataSync, mission) starts from a **known-good query**, not trial-and-error. *First concrete feed to ship against:* **airborne intel** — i.e. the CA perimeters layer filtered to **FIRIS** + **CAL FIRE INTEL FLIGHT DATA**, **72h** on `poly_DateCurrent`, **`mission`** as UID (see table below).

**Goal:** Lower the bar from "navigate ArcGIS REST and attribute tables" to **paste Feature Service URL → discover fields/values in-tool → build filter → export config** for the engine.

**Example layer (screenshot / attribute table):** *CA Perimeters CAL FIRE NIFC FIRIS public view* (~467 records in sample). Key fields:

| Field | Role |
|--------|------|
| `source` | Filter — user wants only **FIRIS** and **CAL FIRE INTEL FLIGHT DATA** (ignore USFS, NIFC, etc. for this deployment). Full strings must come from API (UI may truncate, e.g. "CAL FIRE INTEL FLIGHT D…"). |
| `poly_DateCurrent` | Time — keep features **newer than 72 hours** (rolling window). |
| `mission` | Stable **UID / dedup** candidate (e.g. `CA-LPF-Gifford-N50X`, `GIFFORD`). |
| `incident_name` | Human-readable label (optional for CoT title). |

**Representative `where` clause** (date literal must be generated in code from "now − 72h" in ArcGIS SQL syntax):

```text
source IN ('FIRIS', 'CAL FIRE INTEL FLIGHT DATA')
AND poly_DateCurrent > DATE '2025-08-10'   -- example; use dynamic cutoff
```

(Use the REST API's date format your layer expects — confirm against the service.)

**Reference flows (user's Node-RED screenshots, not in repo):** *GET PGE OUTAGES* (ArcGIS → `dataSyncSubscription` / CoT / mission), *PGE CLEANUP V2* (mission list → split → `DELETE` per UID), *PGE NUKE MISSION*. Patterns align with **`node-red-contrib-tfr2cot`** / Mission API; fix **TLS** properly (`ERR_SSL_SSLV3_ALERT_CERTIFICATE_UNKNOWN` in screenshots — same CA/client cert story as in *Operational / TLS notes* above).

*Add dated bullets above as you ship slices or change direction.*
