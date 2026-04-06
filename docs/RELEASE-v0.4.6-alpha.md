# infra-TAK v0.4.6-alpha

Release Date: April 2026

---

## Highlights

- **Guard Dog — boot-loop prevention.** Three new protections across all TAK-restarting Guard Dog scripts (`tak-8089-watch`, `tak-process-watch`, `tak-oom-watch`):
  1. **Service-age grace (10 min):** Guard Dog now checks when TAK was *actually* started (by anyone — operator, systemd, or Guard Dog itself) using `systemctl show ActiveEnterTimestampMonotonic`. If TAK was started less than 10 minutes ago, Guard Dog backs off. Previously it only tracked its own restarts.
  2. **Daily restart cap (3/day):** All TAK Guard Dog scripts share a single counter (`tak_restart_count_24h`). After 3 restarts in 24 hours, Guard Dog logs `SKIP … manual intervention required` and stops restarting. This prevents infinite restart loops from destroying the system.
  3. **Clean restart procedure:** Instead of `systemctl restart takserver` (which orphans Java processes), Guard Dog now does: `stop → pkill -9 -u tak → rm -rf /opt/tak/work → start`. This kills orphan Java processes and clears the Ignite cache to prevent the `distributed-configuration` corruption loop.

- **Root cause:** On test10, the old Guard Dog restarted TAK every 20 minutes for hours. Each restart orphaned Java processes (TAK's LSB init script doesn't kill children). This consumed all RAM, drove load to 33+, corrupted the Ignite cache, and made TAK unable to start — requiring a full VPS reboot to recover.

---

## Required after you upgrade

1. **Update Now** in the console (or `git pull origin main && sudo systemctl restart takwerx-console`).
2. **Guard Dog → ↻ Update Guard Dog** to deploy the new scripts to `/opt/tak-guarddog/`.

**Verify Guard Dog has the new protections:**

```bash
grep STARTUP_GRACE /opt/tak-guarddog/tak-8089-watch.sh
grep MAX_DAILY_RESTARTS /opt/tak-guarddog/tak-8089-watch.sh
grep 'pkill.*tak' /opt/tak-guarddog/tak-8089-watch.sh
```

All three should return matches.

---

## Protection layers (all TAK Guard Dog scripts)

| Layer | What it does | Value |
|-------|-------------|-------|
| Boot grace | Skip if system uptime < 15 min | 900s |
| Service-age grace (NEW) | Skip if TAK started < 10 min ago by *anyone* | 600s |
| Guard Dog restart grace | Skip if Guard Dog restarted < 15 min ago | 900s |
| Daily restart cap (NEW) | Max 3 restarts/day across all scripts, then stop | 3/day |
| Clean restart (NEW) | stop → kill orphans → clear Ignite → start | — |

---

## Everything else in this train

Same as **v0.4.5** (console crash fix), **v0.4.4** (8089 TCP connect), **v0.4.3** (Authentik health, Auto-VACUUM logging), **v0.4.2** (TAK Portal FQDN, Update Now isolation). Prior: [v0.4.5-alpha](RELEASE-v0.4.5-alpha.md), [v0.4.4-alpha](RELEASE-v0.4.4-alpha.md), [v0.4.3-alpha](RELEASE-v0.4.3-alpha.md), [v0.4.2-alpha](RELEASE-v0.4.2-alpha.md).

---

## Release checklist (maintainer)

- [ ] `app.py` → `VERSION = "0.4.6-alpha"` matches tag **`v0.4.6-alpha`**.
- [ ] Tag **`v0.4.6-alpha`** and push after `main` push.
