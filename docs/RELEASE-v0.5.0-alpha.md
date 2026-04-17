# infra-TAK v0.5.0-alpha

Release Date: April 2026

---

## Security hardening — Docker port binding

### The problem

Docker port mappings like `"1880:1880"` bind to **all network interfaces** (`0.0.0.0`), making services directly reachable from the internet — even when a firewall (UFW) is configured. Docker manipulates iptables directly and **bypasses UFW rules entirely**. This means:

- **Node-RED** (port 1880) was directly accessible without any authentication, despite Caddy + Authentik forward auth being correctly configured for the FQDN. Bots scanning for open Node-RED instances could access the editor and execute arbitrary code (e.g. cryptominers via exec nodes or malicious npm packages).
- **Authentik** admin panel (ports 9000/9443) was directly accessible, bypassing Caddy.
- **Authentik LDAP** (ports 389/636) was exposed to the internet on local deployments where only TAK Server on the same box needs access.

### The fix

All Docker port mappings for services that sit behind Caddy are now bound to `127.0.0.1` (localhost only):

| Service | Before | After |
|---------|--------|-------|
| Node-RED | `"1880:1880"` | `"127.0.0.1:1880:1880"` |
| Authentik HTTP | `"9000:9000"` | `"127.0.0.1:9000:9000"` |
| Authentik HTTPS | `"9443:9443"` | `"127.0.0.1:9443:9443"` |
| Authentik LDAP (local) | `389:3389` / `636:6636` | `127.0.0.1:389:3389` / `127.0.0.1:636:6636` |

Services are only reachable through Caddy (which enforces Authentik login), or from localhost.

**Auto-deploy** applies this fix to existing installations automatically:
1. Port hardening runs **first** (Node-RED + Authentik compose files patched and containers restarted)
2. Then Authentik reconfigure, TAK Portal, and CloudTAK run in parallel

> **Note:** Remote Authentik deployments (where TAK Server is on a separate box) keep LDAP on `0.0.0.0` because TAK Server needs network access to LDAP. These should be firewalled to allow only the TAK Server IP.

### v0.4.9-alpha race condition fix

v0.4.9-alpha had a bug where the Authentik port hardening and the Authentik reconfigure ran in parallel. The reconfigure could restart the containers before the port patch was written, leaving 9000/9443 on `0.0.0.0`. v0.5.0-alpha fixes this by running port hardening sequentially before the parallel reconfigure tasks.

### Immediate action for existing installs

Update via **Update Now**. The auto-deploy will patch and restart all affected containers. Verify afterwards:

```bash
ss -tlnp | grep -E '1880|9000|9443|:389|:636'
```

All listed ports should show `127.0.0.1:PORT` instead of `0.0.0.0:PORT` or `*:PORT`.

---

## Everything else in this train

Same as **v0.4.8-alpha** / **v0.4.7-alpha** (auto-deploy, online database repack, boot sequencer fix, TAK Portal Guard Dog monitor, smart Guard Dog UI, CloudTAK security fix, zero-disruption auto-deploy). See [v0.4.8-alpha](RELEASE-v0.4.8-alpha.md), [v0.4.7-alpha](RELEASE-v0.4.7-alpha.md) for full details.

---

## Release checklist (maintainer)

- [ ] `app.py` → `VERSION = "0.5.0-alpha"` matches tag **`v0.5.0-alpha`**.
- [ ] Tag **`v0.5.0-alpha`** and push after `main` push.
