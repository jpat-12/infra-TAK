# infra-TAK v0.4.5-alpha

Release Date: April 2026

---

## Highlights

- **Console crash fix:** The `/console` page called `apt list --upgradable` to check for Caddy updates. When apt was slow or locked (common after TAK restart storms or on fresh VPS), that command timed out and crashed the page with an **Internal Server Error**. Now caught — the page loads normally and version badges are skipped if apt is unresponsive.
- **Guard Dog — port 8089: TCP connect probe** (from v0.4.4). Queue-depth checks caused false restart loops on scanner-heavy public CoT ports. Now uses `nc -z 127.0.0.1 8089` — if TAK accepts a connection, it's healthy regardless of queue depth.
- **Installer (`start.sh`):** Silent failures fixed, apt lock wait improved, all `.sh` files executable in git.

---

## Required after you upgrade

1. **Update Now** in the console (or `git pull origin main && sudo systemctl restart takwerx-console`).
2. **Guard Dog → ↻ Update Guard Dog** to deploy the new 8089 script to `/opt/tak-guarddog/`.

**Verify Guard Dog:**

```bash
grep CONNECT_TIMEOUT /opt/tak-guarddog/tak-8089-watch.sh
```

If that prints `CONNECT_TIMEOUT=5`, you're on the new logic.

---

## Everything else in this train

Same as **v0.4.4** (8089 TCP connect), **v0.4.3** (Authentik health, Auto-VACUUM logging), **v0.4.2** (TAK Portal FQDN, Update Now isolation). Prior: [v0.4.4-alpha](RELEASE-v0.4.4-alpha.md), [v0.4.3-alpha](RELEASE-v0.4.3-alpha.md), [v0.4.2-alpha](RELEASE-v0.4.2-alpha.md).

---

## Release checklist (maintainer)

- [ ] `app.py` → `VERSION = "0.4.5-alpha"` matches tag **`v0.4.5-alpha`**.
- [ ] Tag **`v0.4.5-alpha`** and push after `main` push.
