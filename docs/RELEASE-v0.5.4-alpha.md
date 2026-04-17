# infra-TAK v0.5.4-alpha

Release Date: April 2026

---

## TAK Server upgrade — robust recovery and self-healing

### The problem

TAK Server upgrades could fail silently or leave the system in a broken state requiring manual SSH intervention:

1. **`apt-get install` hung for 10 minutes** with no output, then timed out — caused by `subprocess.run(capture_output=True)` buffering all output instead of streaming it.
2. **`dpkg was interrupted`** — the timed-out install left `dpkg` in a half-configured (`iF`) state. Every subsequent `apt-get install` refused to run.
3. **Missing files broke `dpkg --configure -a`** — the TAK Server `postinst` script tried to `chmod`/`chown` files that were missing from the incomplete upgrade, failing with cascading errors.
4. **8446 webadmin stopped working** — after a successful upgrade, the webadmin user lost admin access (routed to WebTAK instead of Admin UI) because the LDAP outpost had stale group cache and/or the `adminGroup="ROLE_ADMIN"` attribute was lost from CoreConfig.xml.

### The fix

**Streaming output** — `apt-get install` output is now streamed line-by-line to the upgrade log in real time via `subprocess.Popen` with a reader thread. No more silent 10-minute hangs.

**Unattended-upgrades wait** — before any package operation, the upgrade flow waits for active `unattended-upgrade` workers to finish (same check used during TAK Server deploy).

**Automatic dpkg recovery** — if `dpkg --configure -a` fails (missing files from a partial upgrade), the flow automatically:
1. Runs `dpkg --unpack <package>.deb` to restore all missing files from the uploaded .deb
2. Retries `dpkg --configure -a` (which now succeeds because all files are in place)
3. Skips the redundant `apt-get install` step (package is already fully configured)

**Post-upgrade self-healing** — after a successful upgrade, the flow now:
1. Re-installs the Let's Encrypt cert on 8446 (the TAK `postinst` script can reset the connector to self-signed)
2. Syncs webadmin to Authentik with `--force-recreate ldap` (clears stale LDAP bind cache)
3. Regenerates Caddyfile and reloads Caddy
4. `_resync_ldap_credential_to_coreconfig` now also verifies and restores `adminGroup="ROLE_ADMIN"` if lost (prevents admin users being routed to WebTAK)

Both single-server and two-server upgrade paths are covered.

---

## Authentik Docker network — permanent fix

### The problem

After a Docker-level restart (daemon restart, `docker compose down && up` from CLI, or system reboot that triggers Docker's restart policy), Authentik containers lost their connection to the `infratak` bridge network. TAK Portal would fail with `getaddrinfo EAI_AGAIN authentik-server-1` — users page broken, login broken.

The v0.5.3 fix used runtime `docker network connect` calls, which work when triggered by the console but get lost when Docker itself restarts containers. Docker's `restart: unless-stopped` only reconnects containers to networks defined in their `docker-compose.yml`.

### The fix

**`_patch_authentik_compose_network()`** — mirrors the existing Portal compose patch. Adds the `infratak` external network directly to Authentik's `docker-compose.yml` so it survives any restart path:

- `server` service gets `networks: [default, infratak]`
- Top-level `networks:` block with `infratak: external: true`
- Fresh deploys (local and remote) include the network from the start
- The `infratak` Docker network is created on remote hosts before `docker compose up`

The patch is called from every path: `authentik_control()` start/restart/update, reconfigure, deploy, startup migration, and post-update auto-deploy.

### What happens on upgrade

When you update to v0.5.4-alpha and the console restarts:

1. `_post_update_auto_deploy` triggers Authentik auto-reconfigure
2. `_patch_authentik_compose_network()` writes the network into `~/authentik/docker-compose.yml`
3. `docker compose up -d` recreates the server container with the permanent network config
4. Runtime `docker network connect` calls remain as belt-and-suspenders

No manual steps required.

### Verify

```bash
# Authentik compose has the infratak network
grep infratak ~/authentik/docker-compose.yml

# Container is on the network
docker inspect authentik-server-1 --format '{{json .NetworkSettings.Networks}}' | python3 -m json.tool | grep infratak
```

---

## Everything else

Includes all fixes from v0.5.3 and prior. See [v0.5.3-alpha](RELEASE-v0.5.3-alpha.md).
