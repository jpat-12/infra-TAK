# infra-TAK v0.4.4-alpha

Release Date: April 2026

---

## Highlights

- **Guard Dog — port 8089: TCP connect replaces queue-depth check.** The v0.4.3 backlog threshold (≥95%) still caused restart loops on scanner-heavy public CoT ports: each restart triggered a client reconnect storm that refilled the queue past 95%, restarting again every ~20 minutes. **v0.4.4** replaces the queue-depth rule entirely with a **TCP connect probe** (`nc -z 127.0.0.1 8089`, 5s timeout). If TAK accepts a connection, it's healthy — queue depth is ignored. A restart only fires when TAK **genuinely cannot accept connections** for **5 consecutive** 1-minute checks.
- **Guard Dog — Authentik health:** Tries `/-/health/live/` first (then `/`), accepts 200/204/301/302, and waits 3s + retries once before counting a failure. Reduces `docker compose restart` on transient 500/503 during worker or DB blips.
- **Guard Dog — Auto-VACUUM logging:** When the daily `tak-auto-vacuum.sh` job cannot read the dead-tuple count, `restarts.log` now records two-server vs local and `user@target` so you can see which side failed.
- **Installer (`start.sh`):** Silent exit on dependency failures fixed — errors now print only on failure. `unattended-upgrade-shutdown` no longer falsely blocks the wait loop. All `.sh` files are executable in git (no `chmod +x` needed).

---

## Required after you upgrade — Guard Dog is not automatic

**Update Now** (or any console upgrade) **does not** refresh Guard Dog's on-disk scripts. The fixes in this release **do nothing** until you deploy them.

**After the console shows v0.4.4-alpha:** open **Guard Dog** in infra-TAK and click **↻ Update Guard Dog** (the Update control on that page). That copies the scripts from the console checkout into `/opt/tak-guarddog/` and is **the only way** those fixes take effect. Skipping this step leaves the old watch scripts running.

**Verify on SSH:**

```bash
grep CONNECT_TIMEOUT /opt/tak-guarddog/tak-8089-watch.sh
```

If that prints a line with `CONNECT_TIMEOUT=5`, you're on the new logic. If it prints nothing, Update Guard Dog didn't run.

**Optional:** `echo 0 | sudo tee /var/lib/takguard/8089.failcount` to reset the fail counter immediately.

---

## How to know it's working

After Update Guard Dog, watch `restarts.log`:

```bash
tail -f /var/log/takguard/restarts.log
```

- **No new `8089 unhealthy` lines** = TAK is accepting connections, Guard Dog is happy.
- **New line with `listen=true connect=false`** = TAK is listening but not accepting connections — real problem, restart is correct.
- **New line with `listen=false`** = port 8089 is not listening at all — TAK crashed, restart is correct.

---

## Everything else in this train

Same as **v0.4.3** (port 8089 hardening, Authentik health, Auto-VACUUM logging) and **v0.4.2** (TAK Portal `TAK_URL` FQDN, Update Now isolation, Authentik track). Full skip-upgrade notes: [RELEASE-v0.4.3-alpha.md](RELEASE-v0.4.3-alpha.md), [RELEASE-v0.4.2-alpha.md](RELEASE-v0.4.2-alpha.md).

---

## Release checklist (maintainer)

- [ ] `app.py` → `VERSION = "0.4.4-alpha"` matches tag **`v0.4.4-alpha`** ([COMMANDS.md](COMMANDS.md) Python check).
- [ ] [TESTING-UPDATES.md](TESTING-UPDATES.md) before tagging.
- [ ] Selective `dev` → `main` per [COMMANDS.md](COMMANDS.md); release doc **`docs/RELEASE-v0.4.4-alpha.md`**.
- [ ] Tag **`v0.4.4-alpha`** and push after `main` push.
