# infra-TAK v0.4.6-alpha

Release Date: April 2026

---

## Highlights

### Guard Dog — boot-loop prevention

Three new protections across all TAK-restarting Guard Dog scripts (`tak-8089-watch`, `tak-process-watch`, `tak-oom-watch`):

1. **Service-age grace (10 min):** Guard Dog checks when TAK was *actually* started (by anyone — operator, systemd, or Guard Dog itself) using `systemctl show ActiveEnterTimestampMonotonic`. If TAK was started less than 10 minutes ago, Guard Dog backs off.
2. **Daily restart cap (3/day):** All TAK Guard Dog scripts share a single counter (`tak_restart_count_24h`). After 3 restarts in 24 hours, Guard Dog logs `SKIP … manual intervention required` and stops restarting.
3. **Clean restart procedure:** Instead of `systemctl restart takserver` (which orphans Java processes), Guard Dog now does: `stop → pkill -9 -u tak → rm -rf /opt/tak/work → start`. This kills orphan Java processes and clears the Ignite cache.

### Boot sequencer — staggered startup from cold reboot

Full boot orchestration across the entire stack. On reboot, services start in dependency order instead of all at once.

**Pre-start** (`tak-boot-sequencer.sh`, runs as `ExecStartPre` on `takserver.service`):
- Stops Authentik, TAK Portal, CloudTAK, Node-RED, and MediaMTX
- Waits for PostgreSQL (`SELECT 1` returns success)
- Caddy stays running (lightweight, needed for TLS)

**Post-start** (`tak-post-start.service`, runs after `takserver.service`):
- Waits for TAK Server port 8089 (up to 15 min)
- If TAK config is ready but messaging crashed on cold boot, auto-restarts it
- Then starts services one at a time, waiting for each to be healthy:

```
Power On
  │
  ├─ PostgreSQL (systemd default)
  ├─ Caddy (stays running)
  │
  └─ tak-boot-sequencer.sh (pre-start)
       stops: Authentik, TAK Portal, CloudTAK, Node-RED, MediaMTX
       waits: PostgreSQL ready
       │
       └─ TAK Server starts (Java, ~60-90s)
            │
            └─ tak-post-start.service (oneshot)
                 waits: port 8089 ready
                 │
                 ├─ Authentik (docker compose up -d)
                 │    waits: server healthy
                 │    waits: LDAP port 389 open
                 │    (force-recreates LDAP if not responding after 120s)
                 │
                 ├─ TAK Portal (docker start)
                 │
                 ├─ CloudTAK (docker compose up -d)
                 │
                 ├─ Node-RED (docker compose up -d)
                 │
                 └─ MediaMTX (systemctl start)
                      │
                      └─ "Boot sequence complete — all services started"
```

Only services that are actually installed are touched; everything else is skipped.

**Typical cold-boot timing** (measured on a 12-core / 48 GB VPS, 316 MB/s disk I/O):

| Phase | Duration |
|-------|----------|
| Pre-start (stop Docker, wait PostgreSQL) | ~15s |
| TAK Server start | ~9s |
| Post-start (Authentik, TAK Portal, CloudTAK, Node-RED) | ~90s |
| **Total: boot to full stack healthy** | **~2 min 15s** |

### Authentik deployment resilience

Authentik deploy and LDAP verification are now robust against slow TLS provisioning and LDAP startup timing:

1. **TLS cert readiness gate:** After Caddy reload, the deploy waits up to 300s for Caddy to provision a valid TLS certificate on the Authentik FQDN (`tak.<fqdn>`) before restarting the LDAP outpost. The LDAP outpost needs `AUTHENTIK_HOST: https://tak.<fqdn>` — if there's no valid cert yet, the outpost gets TLS errors and fails to authenticate users.

2. **LDAP port 389 readiness gate:** After the final LDAP container restart, the deploy waits up to 180s for TCP port 389 to actually be listening before starting bind verification. Prevents wasting bind-check attempts while the container is still starting.

3. **Improved LDAP bind verification:** Retry budget increased from 12 attempts / 5s delay (60s total) to 24 attempts / 10s delay (240s total). The log-parsing logic now prioritizes success markers (`authenticated`) over stale error markers from earlier in the log window, preventing false negatives.

4. **Healthcheck `start_period` extended to 600s:** Authentik server and worker Docker healthchecks now allow 10 minutes for first-run database migrations before marking unhealthy. Prevents Docker from restarting containers during slow initial migrations on fresh installs.

### Certificate password fix (two-part)

**Part 1 — JKS files created with wrong password:**
When a custom certificate password was set in the console (instead of the default `atakatak`), `cert-metadata.sh` was never patched before running `makeRootCa.sh` / `makeCert.sh`. All JKS files were created with the default `atakatak`. The helper function also patched wrong variable names (`CERT_PASS`, `PASSWORD`) instead of the actual TAK Server variables (`CAPASS`, `PASS`).

**Fixed:** `cert-metadata.sh` is now patched with the custom password before any cert generation — during initial TAK Server deploy and during CA rotation.

**Part 2 — CoreConfig.xml `<tls>` elements retained default password:**
Even after Part 1, the `<tls>` elements in CoreConfig.xml (main TLS and federation TLS) still had `keystorePass="atakatak"` and `truststorePass="atakatak"`. TAK Server opened the keystore with the wrong password, couldn't extract the RSA public key for JWT signing, and crashed with `NullPointerException: "pub" is null` at `ServerConfiguration.jwkSource`.

**Fixed:** New `_patch_coreconfig_passwords` helper reads CoreConfig.xml and ensures every `keystorePass` and `truststorePass` attribute matches the configured password. Runs during initial deploy, intermediate CA rotation, and root CA rotation.

**Who is affected:** Only deployments that set a custom certificate password. Deployments using the default `atakatak` were never affected.

### TAK Portal — SSH auto-configuration

TAK Portal's new SSH feature (connecting back to the host TAK Server) is now auto-configured on deploy with zero manual steps:

1. Generates an ed25519 keypair at `~/TAK-Portal/data/ssh/tak_ssh_ed25519`
2. Adds the public key to the host's `~/.ssh/authorized_keys`
3. Copies the keypair into the TAK Portal container
4. Populates `TAK_SSH_HOST`, `TAK_SSH_PORT`, `TAK_SSH_USER`, key paths, and marks `TAK_SSH_ONBOARDED: true`

**Same-box only:** Auto-config runs when `/opt/tak` exists (TAK Server on the same host). For remote TAK Server deployments, SSH must be configured manually in TAK Portal's settings UI.

**Existing users:** Click **Update Config** on the TAK Portal page in the console — SSH will be set up automatically.

**On deploy, reconfigure, and update:** The setup is idempotent; it skips if the keypair already exists and is installed.

### VPS disk I/O check in installer

`start.sh` now runs a 256 MB sequential write test on first boot and prints a colored assessment:

| Write speed | Assessment |
|-------------|------------|
| **400+ MB/s** | Excellent |
| **200–400 MB/s** | Acceptable |
| **< 200 MB/s** | Slow — contact your provider |

Helps catch slow/overloaded VPS storage nodes before deploying. The test runs once during initial install and does not block subsequent starts.

### Timer delays increased

Guard Dog timers for 8089, Process, and OOM now wait 20 minutes after boot before first check (was 3-10 min), giving the boot sequencer and TAK Server ample time to initialize.

---

## Required after you upgrade

1. **Update Now** in the console (or `git pull origin main && sudo systemctl restart takwerx-console`).
2. **Guard Dog → ↻ Update Guard Dog** — deploys the new boot sequencer, post-start orchestrator, and updated watch scripts to `/opt/tak-guarddog/`.
3. **Authentik → Update Config & Reconnect** — patches docker-compose healthchecks (`start_period: 600s`) on existing installs. Only needed if Authentik is already deployed.
4. **TAK Portal → Update Config** — generates SSH keypair, installs it on the host, and auto-configures TAK Portal's SSH settings. Only needed if TAK Portal is already deployed.

Steps 2–4 are safe to run at any time. They do not restart TAK Server or cause downtime.

**Verify Guard Dog has the new protections:**

```bash
grep STARTUP_GRACE /opt/tak-guarddog/tak-8089-watch.sh
grep MAX_DAILY_RESTARTS /opt/tak-guarddog/tak-8089-watch.sh
grep 'pkill.*tak' /opt/tak-guarddog/tak-8089-watch.sh
```

All three should return matches.

**Verify boot sequencer is installed:**

```bash
systemctl status tak-post-start
cat /etc/systemd/system/takserver.service.d/soft-start.conf
```

The first should show the oneshot service (active or inactive depending on last boot). The second should show `ExecStartPre=-/opt/tak-guarddog/tak-boot-sequencer.sh`.

**Verify Authentik healthchecks (if Authentik is deployed):**

```bash
grep start_period ~/authentik/docker-compose.yml
```

Should show `start_period: 600s` for server and worker.

**Verify TAK Portal SSH (if TAK Portal is deployed):**

```bash
docker exec tak-portal cat /usr/src/app/data/settings.json 2>/dev/null | grep -i ssh
```

Should show `TAK_SSH_HOST` populated, `TAK_SSH_ONBOARDED: true`, and key paths pointing to `data/ssh/tak_ssh_ed25519`.

**Verify certificate passwords (if using a custom cert password):**

```bash
grep -oP 'keystorePass="\K[^"]+' /opt/tak/CoreConfig.xml | sort -u
```

Should show a single value (your custom password), not `atakatak`.

---

## Checking boot order after a reboot

After rebooting the VPS, check the full boot sequence with timestamps:

```bash
journalctl -u takserver -b --no-pager | grep -E 'boot-sequencer|PostgreSQL|post-start'
```

This shows every service start, every health gate, and the total time from power-on to completion. Docker container status:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

All containers should show "healthy" within ~2–3 minutes of boot.

---

## VPS performance — disk I/O matters

If deploys are slow, services time out on startup, or the boot sequencer takes much longer than the table above, your VPS may have poor disk I/O. Test before deploying:

```bash
# Write speed (sequential)
dd if=/dev/zero of=/tmp/testfile bs=1M count=1024 oflag=dsync 2>&1 | tail -1

# Read speed
dd if=/tmp/testfile of=/dev/null bs=1M 2>&1 | tail -1

# Clean up
rm -f /tmp/testfile
```

| Write speed | Assessment |
|-------------|------------|
| **400+ MB/s** | Good — SSD-backed, full stack will deploy and boot quickly |
| **200–400 MB/s** | Acceptable — deploys work, boot may be slightly slower |
| **< 200 MB/s** | Poor — expect slow Docker builds, service timeouts, and longer boot |
| **< 100 MB/s** | Bad — likely throttled or HDD-backed; migrate to a different VPS or provider node |

Some providers place VPS instances on overloaded storage nodes. If your write speed is under 200 MB/s, contact your provider or migrate to a different node before troubleshooting service issues.

The installer (`start.sh`) now runs this check automatically on first boot and prints a colored assessment.

---

## Protection layers (all TAK Guard Dog scripts)

| Layer | What it does | Value |
|-------|-------------|-------|
| Boot sequencer pre-start (NEW) | Stops Authentik, TAK Portal, CloudTAK, Node-RED, MediaMTX; waits for PG | 2 min PG timeout |
| Boot sequencer post-start (NEW) | Waits for TAK 8089, then starts services in order | 15 min TAK timeout |
| Timer delay (INCREASED) | Guard Dog timers don't fire until 20 min after boot | 20 min |
| Boot grace | Skip if system uptime < 15 min | 900s |
| Service-age grace (NEW) | Skip if TAK started < 10 min ago by *anyone* | 600s |
| Guard Dog restart grace | Skip if Guard Dog restarted < 15 min ago | 900s |
| Daily restart cap (NEW) | Max 3 restarts/day across all scripts, then stop | 3/day |
| Clean restart (NEW) | stop → kill orphans → clear Ignite → start | — |
| TLS cert gate (NEW) | Wait for valid TLS cert before LDAP outpost restart | 300s max |
| LDAP port gate (NEW) | Wait for port 389 before bind verification | 180s max |

---

## Root cause (why this release exists)

On test10, the old Guard Dog restarted TAK every 20 minutes for hours. Each restart orphaned Java processes (TAK's LSB init script doesn't kill children). This consumed all RAM, drove load to 33+, corrupted the Ignite cache, and made TAK unable to start. Separately, Authentik LDAP verification would false-negative when the TLS cert wasn't provisioned yet or port 389 wasn't listening, causing deploys to report failure even when everything was fine.

After migrating to a VPS with decent disk I/O and applying these fixes, the full stack deploys cleanly and boots from cold reboot in under 2.5 minutes.

---

## Everything else in this train

Same as **v0.4.5** (console crash fix), **v0.4.4** (8089 TCP connect), **v0.4.3** (Authentik health, Auto-VACUUM logging), **v0.4.2** (TAK Portal FQDN, Update Now isolation). Prior: [v0.4.5-alpha](RELEASE-v0.4.5-alpha.md), [v0.4.4-alpha](RELEASE-v0.4.4-alpha.md), [v0.4.3-alpha](RELEASE-v0.4.3-alpha.md), [v0.4.2-alpha](RELEASE-v0.4.2-alpha.md).

---

## Release checklist (maintainer)

- [ ] `app.py` → `VERSION = "0.4.6-alpha"` matches tag **`v0.4.6-alpha`**.
- [ ] Tag **`v0.4.6-alpha`** and push after `main` push.
