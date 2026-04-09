# infra-TAK v0.5.6-alpha

Release Date: April 2026

---

## Boot sequencer — restart-safe

### The problem

The Guard Dog boot sequencer (`tak-boot-sequencer.sh`) runs as an `ExecStartPre` on the `takserver` systemd service. It was designed to stop all Docker containers (Authentik, TAK Portal, Node-RED, CloudTAK, MediaMTX) before TAK Server starts so TAK gets full CPU during its heavy 5-7 minute initialization on boot.

The problem: it ran on **every** `systemctl restart takserver`, not just on boot. A simple TAK Server restart from the console killed every other service. The companion `tak-post-start.service` (which brings everything back up) only triggers on boot — so after a manual restart, nothing came back.

### The fix

The boot sequencer now checks `/proc/uptime`:

- **Uptime < 10 minutes** → real boot → full sequence: stop all containers, wait for PostgreSQL, let TAK Server start with full CPU, then `tak-post-start` brings everything back in order.
- **Uptime >= 10 minutes** → manual restart → skip container shutdown entirely. Just verify PostgreSQL is ready and let TAK Server restart. All other services stay running undisturbed.

### Node-RED restart policy

Added `restart: unless-stopped` to the Node-RED Docker Compose template. It was the only service missing this — Authentik already had it. This ensures Docker auto-restarts Node-RED after a Docker daemon restart or unexpected container exit.

---

## Everything else

Includes all fixes from v0.5.5 and prior. See [v0.5.5-alpha](RELEASE-v0.5.5-alpha.md).
