# infra-TAK v0.6.0-alpha

Release Date: April 2026

---

## Guard Dog — Disk I/O Performance Monitor

New automated disk I/O benchmarking that catches noisy-neighbor degradation before it becomes a problem.

- **Benchmark every 15 minutes** — lightweight 10 MB `dd` sync write, logged to CSV with full history retention (30 days).
- **Trend detection** — alerts when the last-hour average drops below 50 MB/s or falls 70%+ from the 24-hour rolling average.
- **Email + SMS alerts** — uses the same Guard Dog alert pipeline (max once per 6 hours to avoid spam).
- **Dashboard card** — real-time stats (current, 1h avg, 24h avg, min/max) with color-coded values (green/yellow/red). Interactive sparkline chart with 50 MB/s warning threshold line.
- **Time range selector** — dropdown to view last 24 hours, 3 days, 5 days, 7 days, or 30 days of history.
- **CSV report download** — one-click export with summary header (server ID, period, averages, min/max) and full raw data.
- **Local timezone** — chart labels automatically display in the user's browser timezone.
- **Auto-deploys** with Guard Dog — `takdiskioguard.timer` and service are created and enabled during Guard Dog deploy, same as all other monitors.

### Why this matters

VPS providers share physical disks across tenants. A "noisy neighbor" can tank your I/O from 400 MB/s to under 50 MB/s without warning, causing Docker build timeouts, slow TAK Server starts, and unreliable boots. This monitor gives you the data to open a migration ticket with your provider before users notice.

---

## VPS memory stability — swappiness tuning

Guard Dog deploy now sets `vm.swappiness=10` (persistent via `/etc/sysctl.conf` and immediate via `sysctl -w`).

**Problem:** Linux defaults to `vm.swappiness=60`, which aggressively swaps out processes even with plenty of free RAM. On VPS hosts with slow disk I/O, this causes severe performance degradation — the system spends all its time swapping instead of running services.

**Fix:** With `swappiness=10`, the kernel only uses swap when RAM is actually exhausted. Combined with Guard Dog's existing 4 GB swap file, the system has emergency swap available without the performance penalty of aggressive swapping.

---

## Postfix installation fix (universal)

Postfix `apt-get install` now preseeds `debconf` values before installation:

```
postfix/mailname → $(hostname -f)
postfix/main_mailer_type → Internet Site
```

**Problem:** On some systems, `DEBIAN_FRONTEND=noninteractive` alone was not enough — Postfix's `postinst` script failed with `meter mydomain: bad parameter value: 0` because the mailname wasn't set, causing the entire Email Relay deploy to fail.

**Fix:** `debconf-set-selections` runs before `apt-get install postfix`, ensuring a consistent install across all environments.

---

## Node-RED — ArcGIS DataSync & FAA TFR Configurator (new)

This release introduces a complete system for streaming GIS vector data and FAA Temporary Flight Restrictions into TAK as live CoT objects. No Node-RED flow editing required — everything is configured through a web-based configurator UI.

### What it does

- **ArcGIS → TAK:** Connect any ArcGIS Feature Service (wildfire perimeters, weather alerts, infrastructure, custom layers) and stream the features into a TAK Server mission as CoT markers/shapes. Features are diffed on each poll — only changes are pushed, not the full dataset.
- **FAA TFR → TAK:** Pull active Temporary Flight Restrictions from the FAA API and display them on ATAK/iTAK/WinTAK with correct boundaries, labels, and direct links to the FAA detail page.
- **Runs inside Node-RED**, which is already deployed and protected behind Authentik SSO as part of the infra-TAK stack.

### How to access the configurator

1. Open Node-RED at `https://nodered.<your-fqdn>` (sign in with your Authentik credentials).
2. The **Configurator** tab is the first tab in the flow editor. Click it to open the built-in configuration UI.
3. In the configurator:
   - **Step 1:** Enter your TAK Server connection details (host, port, mission name, credentials).
   - **Step 2:** Add ArcGIS feeds — paste an ArcGIS Feature Service URL, pick the fields you want for labels/remarks, set a poll interval, and choose a CoT type.
   - **Step 3:** Add TFR feeds — select a geographic bounding box and filter options (labels on/off, capitalize names, label format).
   - **Step 4:** Click **Deploy** — the configurator generates all the Node-RED flow nodes automatically. Each feed gets its own engine tab.
4. Data starts flowing to TAK Server immediately. Open ATAK and you'll see the features appear in your mission.

### Key design decisions

- **No flow editing needed.** The configurator generates and wires all nodes. Users who know Node-RED can still create their own flows alongside the generated ones — they are fully preserved on updates.
- **Non-destructive updates.** Running `deploy.sh` (or updating via infra-TAK) never destroys user-created flows or configurator-created feeds. Dynamic engine tabs, configs, TLS certificates, TCP settings, and credentials all survive. A template sync mechanism (`_templateKey`) automatically updates function code in existing tabs when bug fixes ship — without losing your feed configuration.

### Shipped with fixes and hardening

- **FAA TFR ID fix** — TFR CoT builder uses `notam_id` from the FAA API for display labels and associated links. Links now point directly to the TFR detail page instead of the generic FAA listing.
- **Cold-start guards (ArcGIS + TFR)** — after a Node-RED restart, feeds no longer "churn" (delete and re-add every item in the mission, causing mass notification noise in ATAK). ArcGIS preserves feature hashes across restarts; TFR skips reconcile when no data has been polled yet.
- **Stable ArcGIS feature hashing** — hash only includes CoT-affecting fields (geometry, ID, label, remarks). Metadata changes between polls no longer trigger false updates.
- **TFR configurator options** — per-feed labels on/off toggle, capitalize names checkbox, FAA NOTAM ID format clarification.

---

## Everything else

- **`guarddog.js` cache-control** — JS served with `no-cache, no-store, must-revalidate` headers (matching `firewall.js`). Prevents stale cached JS after updates.
- **Disk I/O API error handling** — fetch errors now surface visible messages on the card instead of silently failing.
- **Refresh button feedback** — shows "Refreshing…" → "Updated" (green) so users can tell it worked.

Includes all fixes from v0.5.9 and prior. See [v0.5.9-alpha](RELEASE-v0.5.9-alpha.md).
