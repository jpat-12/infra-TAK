# infra-TAK v0.4.3-alpha

Release Date: April 2026

---

## Highlights

- **Guard Dog — port 8089 monitor (false TAK restarts):** On servers with **public** CoT port **8089**, internet scanners partially fill the TCP **accept queue** all day. The old watch script treated **`Recv-Q >= Send-Q - 5`** as “unhealthy” and restarted **TAK Server** every ~15–20 minutes in a loop, even when TAK was fine. **v0.4.3** only flags backlog when the queue is **≥95%** full and requires **5** consecutive failures before restart. See **`scripts/guarddog/tak-8089-watch.sh`** and [GUARDDOG.md](GUARDDOG.md).
- **Guard Dog — Authentik health:** **`tak-authentik-watch.sh`** tries **`/-/health/live/`** first (then **`/`**), accepts **200/204/301/302**, and waits **3s** and retries once **before** counting a failure. That reduces **`docker compose restart`** on transient **500/503** during worker or DB blips.
- **Guard Dog — Auto-VACUUM logging:** When the daily **`tak-auto-vacuum.sh`** job cannot read the dead-tuple count (SSH/psql failure), **`/var/log/takguard/restarts.log`** now records **two-server vs local** and **`user@target`** so ops can see whether **Server One** or local Postgres is the problem.

---

## Required after you upgrade — Guard Dog is not automatic

**Update Now** (or any console upgrade) **does not** refresh Guard Dog’s on-disk scripts. The new **`tak-8089-watch.sh`**, **`tak-authentik-watch.sh`**, and **`tak-auto-vacuum.sh`** in this release **do nothing** until you deploy them.

**If Guard Dog is installed:** after the console is on **v0.4.3-alpha**, open **Guard Dog** in infra-TAK and click **↻ Update Guard Dog** (the Update control on that page) **once**. That copies the scripts from the console checkout into **`/opt/tak-guarddog/`** and is the only way those fixes take effect. Skipping this step leaves the **old** watch scripts running.

Optional on noisy boxes: **`echo 0 | sudo tee /var/lib/takguard/8089.failcount`**

---

## Everything else in this train

Same as **v0.4.2** (TAK Portal **`TAK_URL`** FQDN, **Update Now** isolation, Authentik track). Full skip-upgrade notes: [RELEASE-v0.4.2-alpha.md](RELEASE-v0.4.2-alpha.md).

---

## Release checklist (maintainer)

- [ ] `app.py` → `VERSION = "0.4.3-alpha"` matches tag **`v0.4.3-alpha`** ([COMMANDS.md](COMMANDS.md) Python check).
- [ ] [TESTING-UPDATES.md](TESTING-UPDATES.md) before tagging.
- [ ] Selective `dev` → `main` per [COMMANDS.md](COMMANDS.md); release doc **`docs/RELEASE-v0.4.3-alpha.md`**.
- [ ] Tag **`v0.4.3-alpha`** and push after `main` push.
