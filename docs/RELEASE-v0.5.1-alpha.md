# infra-TAK v0.5.1-alpha

Release Date: April 2026

---

## Federation Hub — MongoDB AVX fallback

### The problem

MongoDB 5.0 and later require **AVX CPU instructions**. Many hosting environments lack AVX support:

- **LXC containers** — host CPU flags are not passed through
- **Budget VPS providers** — older CPU generations (pre-Sandy Bridge)
- **Some VM hypervisors** — AVX not exposed to guests

The Federation Hub deploy installed MongoDB 8.0 unconditionally. On non-AVX systems, `mongod` crashes immediately on startup, failing the entire deployment.

### The fix

The installer now detects AVX support before choosing a MongoDB version:

- **AVX present** → MongoDB 8.0 (same as before)
- **No AVX** → MongoDB 4.4 (last version without AVX requirement)

MongoDB 4.4 is not officially supported on Ubuntu 22.04 but works in practice. Federation Hub does not use any MongoDB features that require a newer version.

The AVX check runs on the **target host** (not the console), so it works correctly for remote Federation Hub deployments where the target may have different hardware than the console.

### Action

No action needed for existing Federation Hub installs (MongoDB is already running). For new deployments on LXC or non-AVX VPS: just deploy — the installer handles it automatically.

---

## Everything else in this train

Same as **v0.5.0-alpha** (Docker port hardening, Node-RED malware scan, auto-deploy). See [v0.5.0-alpha](RELEASE-v0.5.0-alpha.md) for details.

---

## Release checklist (maintainer)

- [ ] `app.py` → `VERSION = "0.5.1-alpha"` matches tag **`v0.5.1-alpha`**.
- [ ] Tag **`v0.5.1-alpha`** and push after `main` push.
