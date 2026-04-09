# infra-TAK v0.5.3-alpha

Release Date: April 2026

---

## TAK Portal — users not loading (fix)

### The problem

After the v0.5.0 security hardening (Docker ports bound to `127.0.0.1`), TAK Portal could no longer reach the Authentik API. The Portal container was configured to call `http://<server-public-ip>:9090`, but that port was now only listening on the host's loopback — unreachable from inside a Docker container. Result: the Users page in TAK Portal timed out and never loaded.

### Root cause

TAK Portal and Authentik run in **separate Docker Compose stacks** (different bridge networks). Before v0.5.0, Authentik published port 9090 on all interfaces (`0.0.0.0:9090`), so Portal could reach it via the host's public IP. The v0.5.0 hardening changed this to `127.0.0.1:9090`, which is correct for security (Docker's iptables bypass UFW), but broke the cross-stack container communication.

### The fix

**Shared Docker network (`infratak`)** — a new bridge network that connects containers from different compose stacks so they can talk directly using internal hostnames.

- Portal's `AUTHENTIK_URL` is now `http://authentik-server-1:9000` (the same internal hostname Authentik's own LDAP outpost already uses)
- The `infratak` network is **written into TAK Portal's `docker-compose.yml`** as an external network, so the connection survives `docker compose down && up` from the CLI — not just console-driven restarts
- Network creation and container connections are established at:
  - Every console startup (startup migration)
  - Portal deploy, start, restart, update, reconfigure
  - Authentik deploy and reconfigure
  - Auto-deploy on version change

### What happens on upgrade

When you update to v0.5.3-alpha and the console restarts:

1. The startup migration creates the `infratak` Docker network
2. Connects both `authentik-server-1` and `tak-portal` to it
3. Patches Portal's `docker-compose.yml` to include the network permanently
4. The auto-deploy pushes new `settings.json` with the corrected `AUTHENTIK_URL`
5. Portal restarts and users load immediately

No manual steps required.

### Verify

```bash
# Network exists and both containers are on it
docker network inspect infratak --format '{{range .Containers}}{{.Name}} {{end}}'
# Expected: authentik-server-1 tak-portal

# Portal is using the internal hostname
docker exec tak-portal cat /usr/src/app/data/settings.json 2>/dev/null | \
  python3 -c "import sys,json; print(json.load(sys.stdin).get('AUTHENTIK_URL','(not set)'))"
# Expected: http://authentik-server-1:9000
```

---

## Security note

This fix keeps the v0.5.0 port hardening intact. Authentik's HTTP port (9090) remains bound to `127.0.0.1` — it is **not** opened back to the internet. Container-to-container communication goes through the Docker bridge network, not through published host ports.

---

## Everything else

Includes all fixes from v0.5.2 and prior. See [v0.5.2-alpha](RELEASE-v0.5.2-alpha.md).
