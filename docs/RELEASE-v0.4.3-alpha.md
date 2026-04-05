# infra-TAK v0.4.3-alpha

Release Date: April 2026

---

## Highlights

- **Guard Dog — port 8089 monitor (false TAK restarts):** On servers with **public** CoT port **8089**, internet scanners partially fill the TCP **accept queue** all day. The old watch script treated **`Recv-Q >= Send-Q - 5`** as “unhealthy” and restarted **TAK Server** every ~15–20 minutes in a loop, even when TAK was fine. **v0.4.3** only flags backlog when the queue is **≥95%** full and requires **5** consecutive failures before restart. See **`scripts/guarddog/tak-8089-watch.sh`** and [GUARDDOG.md](GUARDDOG.md).

---

## Required after you upgrade

**If Guard Dog is installed:** open **Guard Dog** in infra-TAK and click **↻ Update Guard Dog** once. That copies the new scripts under **`/opt/tak-guarddog/`**; the console **VERSION** bump alone does **not** update on-disk watch scripts.

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
