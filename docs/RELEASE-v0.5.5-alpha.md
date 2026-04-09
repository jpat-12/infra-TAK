# infra-TAK v0.5.5-alpha

Release Date: April 2026

---

## Post-update auto-reconfigure — sequenced, not parallel

### The problem

After a console update (Update Now or pull-and-restart), the auto-reconfigure fired Authentik, TAK Portal, and CloudTAK all in parallel. When Authentik's compose gets patched (e.g. infratak network added), `docker compose up -d` recreates the container — which takes 2-5 minutes to become healthy. TAK Portal was simultaneously trying to call the Authentik API for user/group sync and hitting 503s the entire time.

### The fix

The post-update auto-reconfigure now runs in dependency order:

1. **Guard Dog** redeploys (updated scripts + timers)
2. **Authentik port hardening** — checks compose, only writes + recreates if ports aren't already `127.0.0.1` (no-op on servers that are already hardened)
3. **Node-RED port hardening** — same pattern, no-op if already secure
4. **CloudTAK** starts reconfiguring in background (independent — talks to TAK Server, not Authentik)
5. **Authentik** reconfigures (compose patched, containers recreated if needed)
6. **Health gate** — waits up to 5 minutes for Authentik to report healthy
7. **TAK Portal** reconfigures (needs Authentik API for user/group sync)

On a server that's already been updated, the port hardening and network patching are all no-ops (idempotent checks, no writes, no container restarts). The heavy lifting only happens the first time a fix is applied.

### What happens on upgrade

When you update to v0.5.5-alpha: the auto-reconfigure runs in order. If Authentik was already patched by v0.5.4, the compose patch is a no-op, `docker compose up -d` sees no changes, and TAK Portal reconfigures immediately without waiting. Clean and fast.

---

## Everything else

Includes all fixes from v0.5.4 and prior. See [v0.5.4-alpha](RELEASE-v0.5.4-alpha.md).
