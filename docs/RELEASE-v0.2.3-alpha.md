# infra-TAK v0.2.3-alpha

Release Date: March 2026

---

## Highlights

- **Guard Dog — software update monitor** — Guard Dog now checks for available updates every **6 hours** (infra-TAK, Authentik, MediaMTX, CloudTAK, TAK Portal; same sources as the console update icons). When an update is available (or when the set of available updates changes), it sends **one email** to the same alert address used by other monitors. So you get notified without having to open the console.
- **Ku-band simulator** — When the console installs or updates the **web editor**, it now also copies the Ku-band simulator scripts to the server, so the "Simulate link" button in External Sources works without a manual copy. (Sudoers for the ON/OFF scripts may still be needed; see simulator README.)

---

## Guard Dog — update check and email

- **What it does:** The Guard Dog "Updates" monitor runs every **6 hours**. It checks for newer versions of infra-TAK, Authentik, MediaMTX, CloudTAK, and TAK Portal (same logic as the update badges in the console). If any update is available, or if the set of available updates changes, it sends **one email** to the Guard Dog alert address.
- **Why:** So you don’t have to open the console to see that an update is available; you get an email and can update when it suits you.

---

## Summary of code changes

| Area | Change |
|------|--------|
| **app.py** | Guard Dog: "Updates" monitor (6 h check, email when update available). |
| **app.py** | Web editor deploy/update now copies Ku-band simulator scripts so "Simulate link" works. |
