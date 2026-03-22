# infra-TAK v0.3.2-alpha

Release Date: March 2026

---

## Highlights

- **Guard Dog — TAK LE cert email false alerts fixed** — `tak-cert-watch.sh` exported `takserver-le.jks` with a hardcoded `-alias takserver`, but `install_le_cert_on_8446()` creates the keystore with **alias = TAK hostname** (e.g. `takserver.example.com`). The export failed silently, expiry math broke, and **“0 days remaining” emails** could fire while certs were still valid. The script now **discovers the PrivateKeyEntry alias** from `keytool -list` and **validates** the PEM before computing days left.

---

## What end users should do after upgrading

1. **Update infra-TAK** — **Console → Update Now** (or `git pull` + `sudo systemctl restart takwerx-console`).
2. **Re-deploy Guard Dog** — **Guard Dog → Update Guard Dog** (or full deploy) so `/opt/tak-guarddog/tak-cert-watch.sh` is replaced on the server.
3. Optional: **`sudo rm -f /var/lib/takguard/cert_alert_sent`** once if you want to clear a sticky cert alert state after upgrading.

---

## Summary of changes

| Area | Change |
|------|--------|
| **Guard Dog** | `scripts/guarddog/tak-cert-watch.sh` — resolve LE JKS alias dynamically; require non-empty valid PEM before `DAYS_LEFT`; fallback alias `takserver` for older keystores. |
| **Docs** | `README.md` — **↻ Update Guard Dog** after every console upgrade (scripts on disk). `GUARDDOG.md` — Certificate row notes v0.3.2+ alias fix. `COMMANDS.md` — release example v0.3.2-alpha. |

---

## Operator checklist (release maintainer)

- [ ] Run **TESTING-UPDATES.md** on a test VPS if desired.
- [ ] Selective merge to `main`, tag **`v0.3.2-alpha`**, push tag (see **docs/COMMANDS.md**).
- [ ] Tell deployments with Guard Dog: **Update Guard Dog** after console update so cert monitoring uses the fixed script.
