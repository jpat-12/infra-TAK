# Handoff: GIS → TAK DataSync (Node-RED) — infra-TAK module

## Background

The goal is a **reusable path from ArcGIS Feature Services into TAK Server**, using **Node-RED** and **DataSync** as the way to **publish and remove** map content (not just stream CoT over TCP). A prior attempt (Nov 2024) used PGE outage polygons: one flow to **GET** data and push CoT into a mission, and a second **cleanup** flow to list mission UIDs and **DELETE** to avoid duplicates. That approach never behaved reliably: **ongoing outages** tended to get **re-added each poll**, producing **stacked duplicate polygons** on the map.

The **older** PGE work was never committed; **`nodered/flows.json` in this repo is no longer empty** — it includes an **ArcGIS Configurator** tab (e.g. `GET /configurator`). The **reconciliation “engine” subflow** (poll → diff → DataSync PUT/DELETE) is still the main build gap; see *Maintainer log* below.

## Problem statement

1. **DataSync** is the practical API surface for **persisting** CoT in a mission and **removing** it later.
2. **Polling** without a clear **reconciliation model** (diff “what the feed says now” vs “what’s already in the mission”) causes **duplicates** or **racey** delete-then-re-add behavior.
3. **ArcGIS Feature Services** vary by layer: field names, geometry types, date fields, etc. Manually finding the **right index in the array** / the right attribute in each feature is what was hardest in Node-RED function nodes.

## Product direction (proposed infra-TAK module)

A small **“feed configurator”** (web UI + optional backend) that:

1. Accepts an **ArcGIS Feature Service** (or layer) URL.
2. Calls the **REST API** to expose **layer metadata** (fields, types) and **sample features** so the user isn’t guessing array indices.
3. Lets the user define:
   - **Which field** is the stable **ID** (for mission UID / dedup).
   - **Which field** is **time** (for “only show data < 72 hours” and expiry).
   - **Geometry**: polygons vs points.
   - **CoT styling**: e.g. polygon **stroke/fill/opacity**; for points, **CoT type / icon** selection (aligned with how TAK expects markers).
4. Emits either:
   - **Generated Node-RED flow JSON** (importable), or
   - **Runtime config** (JSON/env) that a **standard subflow** in infra-TAK reads — preferred for maintainability.

## Recommended runtime behavior (avoid duplicate stacking)

**Single reconciliation loop** (conceptually), not “delete everything” vs “add everything” as two unrelated timers unless carefully sequenced:

1. **Fetch current features** from ArcGIS (with `where`/time filter as needed, e.g. last 72h).
2. **Fetch current mission contents** (or DataSync mission API) and build a **set of UIDs** already present.
3. **Diff**:
   - **In ArcGIS, not in mission** → **PUT/add** CoT for that UID.
   - **In mission, not in ArcGIS** (or older than TTL) → **DELETE** that UID.
   - **In both** → **no-op** (or optional **update** only if geometry/attributes changed — compare hash or `edit` timestamp if available).

Stable **UID** must be **deterministic** (e.g. `prefix + feature id` or hash of id + layer id), identical every poll.

## References / packages already in mind

| Item | Role |
|------|------|
| [node-red-contrib-tak](https://github.com/snstac/node-red-contrib-tak) | CoT encode/decode, TAK protocol, TCP/mesh patterns |
| [node-red-contrib-tfr2cot](https://flows.nodered.org/node/node-red-contrib-tfr2cot) | Example of **DataSync**: includes **`dataSyncSubscription`** and pattern of pairing **HTTP request** (method from message) with Mission API — useful as a **reference**, even though TFR-specific |
| TAK Mission / DataSync API | Add/remove persisted mission content (exact paths/ports depend on TAK Server version and `CoreConfig.xml`) |

**Note:** `tfr2cot` docs explicitly call out that **saving to DataSync** does not auto-remove stale items — aligns with building **explicit DELETE** or reconciliation in infra-TAK.

## Operational / TLS notes from prior screenshots

- **HTTP request** to Mission API over TLS may need **TLS config** matching the **TCP/TLS** client (same CA/client cert as used elsewhere).
- Errors like **`ERR_SSL_SSLV3_ALERT_CERTIFICATE_UNKNOWN`** usually mean **wrong CA**, **self-signed** cert not trusted in Node-RED, or **hostname mismatch** — fix in Node-RED TLS config, not by disabling verification in production.

## What to build inside infra-TAK (suggested slices)

1. **Configurator UI** (minimal): Feature Service URL → layer picker → field picker → style → TTL hours → export config / flow.
2. **One “engine” subflow** in Node-RED: read config → poll ArcGIS → reconcile → emit CoT + Mission API DELETE/PUT as needed.
3. **Docs**: how to create DataSync mission, ports (`missionApiPort` often **8442** but verify), and how UIDs map to CoT `uid`.

## Open decisions for infra-TAK maintainers

- **Config storage**: file on disk vs Node-RED **context** vs small API DB.
- **Auth**: ArcGIS public vs token; TAK certs for Mission API.
- **Scale**: number of features per poll (batching, split node).
- **Idempotency**: exact UID scheme and whether to send **updates** for changed geometries.

## One-line elevator pitch

**“ArcGIS Feature Service URL + guided field/style mapping → reproducible Node-RED + DataSync lifecycle (add / keep / delete), with TTL like ‘only show last 72 hours’ — shipped as an infra-TAK module.”**

---

## Maintainer log (keep this doc current)

**Why this section exists:** Cursor (and similar) may **not** reload the full chat transcript into the assistant on every turn. **Treat this file as the source of truth** for Node-RED / GIS–DataSync decisions. When you agree on a plan in chat, **append a short bullet here** so the next session does not depend on chat memory.

### 2026-04 — session update

- **Repo state:** `nodered/` includes committed flows (Configurator UI path); the handoff’s **slice (2)** — single **engine** subflow: ArcGIS poll → mission/DataSync reconcile → PUT/DELETE — is still needed for “make it real.”
- **Operational tie-in (high-volume CoT / ADSB):** TAK Server retention should run **hourly** when possible (same 24h window, smaller deletes per run). Overlapping multi-hour `DELETE` on `cot_router` can exhaust RAM/swap; infra-TAK **v0.5.2+** adds Guard Dog **`tak-retention-guard.sh`** as a safety net (kill stuck DELETEs, batched cleanup). Not a substitute for hourly retention — complementary.

### 2026-02-06 — recovered plan (paste from prior chat; canonical example layer)

**Goal:** Lower the bar from “navigate ArcGIS REST and attribute tables” to **paste Feature Service URL → discover fields/values in-tool → build filter → export config** for the engine.

**Example layer (screenshot / attribute table):** *CA Perimeters CAL FIRE NIFC FIRIS public view* (~467 records in sample). Key fields:

| Field | Role |
|--------|------|
| `source` | Filter — user wants only **FIRIS** and **CAL FIRE INTEL FLIGHT DATA** (ignore USFS, NIFC, etc. for this deployment). Full strings must come from API (UI may truncate, e.g. “CAL FIRE INTEL FLIGHT D…”). |
| `poly_DateCurrent` | Time — keep features **newer than 72 hours** (rolling window). |
| `mission` | Stable **UID / dedup** candidate (e.g. `CA-LPF-Gifford-N50X`, `GIFFORD`). |
| `incident_name` | Human-readable label (optional for CoT title). |

**Representative `where` clause** (date literal must be generated in code from “now − 72h” in ArcGIS SQL syntax):

```text
source IN ('FIRIS', 'CAL FIRE INTEL FLIGHT DATA')
AND poly_DateCurrent > DATE '2025-08-10'   -- example; use dynamic cutoff
```

(Use the REST API’s date format your layer expects — confirm against the service.)

**Configurator backlog (agreed next steps):**

1. **Test** the configurator against the **live** CA perimeters Feature Service URL.
2. **Distinct values** — for a selected field (e.g. `source`), call ArcGIS **`returnDistinctValues=true`** (or equivalent query) so the tool lists *actual* values (checkboxes), not guesswork from attribute tables.
3. **Filter builder** — multi-select sources + time window (72h) + chosen ID/time fields.
4. **Validate** exported JSON is what the **engine** subflow will consume.

**Reference flows (user’s Node-RED screenshots, not in repo):** *GET PGE OUTAGES* (ArcGIS → `dataSyncSubscription` / CoT / mission), *PGE CLEANUP V2* (mission list → split → `DELETE` per UID), *PGE NUKE MISSION*. Patterns align with **`node-red-contrib-tfr2cot`** / Mission API; fix **TLS** properly (`ERR_SSL_SSLV3_ALERT_CERTIFICATE_UNKNOWN` in screenshots — same CA/client cert story as in *Operational / TLS notes* above).

**Next build increment (update when done):**

1. **Configurator** — distinct-values query + filter builder + live endpoint test (CA perimeters).
2. **Engine** — reconciliation subflow consuming exported config; Mission/DataSync PUT/DELETE + stable UIDs from `mission`.

*Add dated bullets below as you ship slices or change direction.*
