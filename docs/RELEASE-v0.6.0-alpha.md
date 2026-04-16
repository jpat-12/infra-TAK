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

## Node-RED (ArcGIS DataSync) enhancements

### FAA TFR ID fix
TFR CoT builder now uses `notam_id` from the FAA API for display labels and associated links. Links point directly to the TFR detail page instead of the generic listing.

### Cold-start guards (ArcGIS + TFR)
Eliminates post-restart churn where all feeds would delete and re-add every item (causing "119 new items" notifications in ATAK for data that was already there):
- ArcGIS: empty API responses preserve existing hashes; cold-start seeds from mission.
- TFR: empty `_tfrUids` skips reconcile instead of deleting everything; empty filter results preserve previous UIDs.

### Template sync for dynamic engine tabs
Code fixes in `build-flows.js` now automatically propagate to configurator-created tabs via `_templateKey` matching. No manual tab recreation needed after updates.

### TFR configurator enhancements
- Labels on/off toggle (per-feed, default ON)
- Capitalize names checkbox (per-feed, default OFF)
- FAA NOTAM ID format clarification

### Stable ArcGIS feature hashing
Hash now only includes CoT-affecting fields (geometry, ID, label, remarks) instead of the entire feature object. Eliminates false hash mismatches from metadata changes between polls.

### Deploy process — flow preservation
`deploy.sh` never destroys user-created flows. Dynamic tabs, configs, TLS, TCP settings, and credentials all survive updates. Template sync updates function code in preserved tabs without losing configuration.

---

## Everything else

- **`guarddog.js` cache-control** — JS served with `no-cache, no-store, must-revalidate` headers (matching `firewall.js`). Prevents stale cached JS after updates.
- **Disk I/O API error handling** — fetch errors now surface visible messages on the card instead of silently failing.
- **Refresh button feedback** — shows "Refreshing…" → "Updated" (green) so users can tell it worked.

Includes all fixes from v0.5.9 and prior. See [v0.5.9-alpha](RELEASE-v0.5.9-alpha.md).
