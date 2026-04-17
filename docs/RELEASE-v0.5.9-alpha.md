# infra-TAK v0.5.9-alpha

Release Date: April 2026

---

## Boot sequence hardening — reliable cold reboot to full stack in under 5 minutes

### Guard Dog Boot Sequencer

On reboot, all Docker containers are stopped immediately so TAK Server gets exclusive CPU during its heavy Java initialization (~100s). Nothing else starts until TAK Server is listening on port 8089.

### Authentik staggered start

PostgreSQL starts first and the boot orchestrator waits for `pg_isready` before bringing up the Authentik server, worker, and LDAP outpost. Eliminates the "too many clients already" PostgreSQL connection storms that occurred when all Authentik components started simultaneously.

### PostgreSQL tuning (idempotent)

`max_connections=300`, `idle_session_timeout=300s`, and TCP keepalives are injected into the Authentik `docker-compose.yml` via a new `_ensure_authentik_compose_patches()` helper. This runs on every deploy, reconfigure, and update — so tuning can never silently disappear after upgrades. Previously, the `reconfigure` and `update` code paths skipped compose patching, and `_apply_authentik_pg_tuning` could inadvertently clear `ALTER SYSTEM` settings if the compose tuning wasn't present.

### Priority service ordering with connection-safe stagger

TAK Server → Authentik → TAK Portal start as fast as possible (critical trio operational in under 3 minutes). CloudTAK and Node-RED get 30-second cooldown delays before startup to prevent Docker iptables rule rebuilds from disrupting active TAK client connections. MediaMTX (systemd-native, no Docker iptables impact) starts last with a shorter delay.

### Cold boot timeline (tested on 12-core / 48 GB VPS)

| Milestone | Time |
|---|---|
| TAK Server ready (8089) | ~100s |
| Authentik PostgreSQL ready | +4s |
| Authentik server healthy | +50s |
| LDAP outpost responding | instant |
| TAK Portal up | +12s |
| CloudTAK up | +48s (staggered) |
| Node-RED up | +46s (staggered) |
| **Full stack operational** | **~4m 42s** |

Zero PostgreSQL errors, zero LDAP 502s, LDAP binds under 1ms after initial cache warmup. ATAK clients reconnect within seconds of TAK Server coming online.

---

## Everything else

Includes all fixes from v0.5.8 and prior. See [v0.5.8-alpha](RELEASE-v0.5.8-alpha.md).
