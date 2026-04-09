# infra-TAK v0.5.2-alpha

Release Date: April 2026

---

## Guard Dog — CoT Retention Safety Net

### The problem

TAK Server's built-in data retention runs a single massive `DELETE FROM cot_router` transaction. With high-volume feeds (e.g. ADSB), the table accumulates millions of rows between retention runs. A single DELETE of millions of rows can:

- Run for **hours** (28+ hours observed)
- Consume all available RAM and **exhaust swap**
- Overlap with the next scheduled retention run, creating **two competing DELETEs**
- Grind the server to a halt (load average 17+ on a 12-core box)

Guard Dog's existing VACUUM and repack scripts handle the **aftermath** of deletes (dead tuples, bloat) but do not prevent the massive DELETE itself.

### The fix

New Guard Dog script: **`tak-retention-guard.sh`** (runs every 15 minutes)

1. **Detects stuck DELETEs** — any `DELETE` on `cot_router` running longer than 30 minutes
2. **Kills them** — overlapping multi-hour DELETEs will never finish; terminating them frees memory and locks
3. **Batched cleanup** — deletes expired rows in chunks of 50,000 with 2-second pauses between batches (up to 10M rows per run), preventing the single-massive-transaction problem
4. **Reads retention hours** from `CoreConfig.xml` so it respects your TAK Server retention settings
5. **Alerts** via email when stuck queries are killed or large cleanups run

Deployed automatically with Guard Dog (new installs get it; existing installs get it on the next Guard Dog deploy or console update).

### Recommended TAK Server settings

Set data retention frequency to **every hour** (not daily). This way TAK Server's own retention only has to delete a small slice of data each run. The Guard Dog script is insurance in case a run still gets stuck.

---

## Federation Hub (target host) — MongoDB install fix

### The problem (v0.5.1)

The v0.5.1 MongoDB AVX detection worked, but on minimal Ubuntu installs `curl` and `gnupg` are not present. The MongoDB repo setup uses both to fetch and import the signing key, causing:

```
bash: line 1: curl: command not found
bash: line 1: gpg: command not found
```

### The fix

The installer now runs `apt-get install -y curl gnupg` before adding the MongoDB repository. This covers minimal/fresh Ubuntu installs where these packages are not pre-installed.

---

## Everything else

Includes all fixes from v0.5.0 and v0.5.1. See [v0.5.1-alpha](RELEASE-v0.5.1-alpha.md) and [v0.5.0-alpha](RELEASE-v0.5.0-alpha.md).
