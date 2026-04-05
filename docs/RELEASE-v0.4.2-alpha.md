# infra-TAK v0.4.2-alpha

Release Date: April 2026

---

## Highlights

- **TAK Portal — `TAK_URL` uses your FQDN, not the VPS IP**: Managed portal `settings.json` used **`https://<server_ip>:8443/Marti`** whenever `server_ip` was set. TAK’s cert is for **`takserver.<yourdomain>`**, so Node.js TLS verification failed (**“TAK server’s identity could not be verified”**) and **QR / certificate enrollment** could fail. **v0.4.2** prefers **`takserver.<fqdn>`** (or your configured TAK host) when **`fqdn`** is set; IP remains the fallback for installs without a domain.

---

## Required after you upgrade (read this)

**TAK Portal does not pick up the new `TAK_URL` until you push settings into the container.**

1. Upgrade the console (**Update Now** or your usual git path) to **v0.4.2-alpha** and restart if needed.
2. In infra-TAK open **TAK Portal** → click **Update config** (🔄). That writes **`settings.json`** into the portal container and restarts it.
3. If you still see trust / cert errors: **Sync TAK Server CA** on the same page, then try enrollment again.

Skipping step 2 leaves the old **`TAK_URL`** (with IP) inside Docker — the sidebar **VERSION** can be new while the portal still behaves like the old build.

---

## Release checklist (maintainer)

- [ ] `app.py` → `VERSION = "0.4.2-alpha"` matches tag **`v0.4.2-alpha`** ([COMMANDS.md](COMMANDS.md) Python check).
- [ ] [TESTING-UPDATES.md](TESTING-UPDATES.md) on a test VPS before tagging.
- [ ] Selective `dev` → `main` per [COMMANDS.md](COMMANDS.md); release doc **`docs/RELEASE-v0.4.2-alpha.md`**.
- [ ] Tag **`v0.4.2-alpha`** and push after `main` push.
