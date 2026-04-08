# infra-TAK v0.4.8-alpha

Release Date: April 2026

---

## Purpose

**Stepping-stone release.** Servers that upgraded from v0.4.6-alpha (or earlier) to v0.4.7-alpha received the new auto-deploy code but skipped the actual reconfigure because there was no previous version to compare against. Updating to v0.4.8-alpha triggers the auto-deploy for the first time, applying all v0.4.7 config changes automatically:

- Authentik LDAP/forward-auth reconfigure
- TAK Portal settings push and container restart
- CloudTAK `docker-compose.override.yml` regeneration (includes `NODE_TLS_REJECT_UNAUTHORIZED=0` removal)
- Guard Dog scripts and timers update

No code changes beyond the version bump. All features and fixes are from [v0.4.7-alpha](RELEASE-v0.4.7-alpha.md).

---

## What to expect

1. Hit **Update Now** (or use the Universal recovery block)
2. Console restarts with v0.4.8-alpha
3. Service cards show **"Updating config..."** with a cyan spinner as each module reconfigures
4. **Authentik will be unavailable for ~2–5 minutes** (typically ~2 min) while it reconfigures. Use `https://<server-ip>:5001` if you need console access during this time
5. TAK Server and all other services stay running throughout
6. When all cards return to "Running" / "Healthy", the update is complete

---

## Everything else in this train

Same as **v0.4.7-alpha** (auto-deploy, online database repack, boot sequencer fix, TAK Portal Guard Dog monitor, smart Guard Dog UI, CloudTAK security fix, zero-disruption auto-deploy). See [v0.4.7-alpha](RELEASE-v0.4.7-alpha.md) for full details. Prior: [v0.4.6-alpha](RELEASE-v0.4.6-alpha.md), [v0.4.5-alpha](RELEASE-v0.4.5-alpha.md), [v0.4.4-alpha](RELEASE-v0.4.4-alpha.md), [v0.4.3-alpha](RELEASE-v0.4.3-alpha.md), [v0.4.2-alpha](RELEASE-v0.4.2-alpha.md).

---

## Release checklist (maintainer)

- [ ] `app.py` → `VERSION = "0.4.8-alpha"` matches tag **`v0.4.8-alpha`**.
- [ ] Tag **`v0.4.8-alpha`** and push after `main` push.
