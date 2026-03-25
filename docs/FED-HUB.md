# Federation Hub (infra-TAK module)

This module tracks **TAK Federation Hub** on a **dedicated Ubuntu host** reachable by **SSH** from the infra-TAK console. The primary flow matches **split-mode TAK database** deploy: upload the official `.deb` on the console, then infra-TAK **SCP**s it to the target and runs **`apt-get install`** there (plus `systemctl` for `federation-hub`). Manual install + **Confirm** remains a fallback.

## Official steps

Install and configure Federation Hub using the **TAK.gov** guide (Ubuntu .deb path, Java, optional MongoDB, certs, `federation-hub` service):

[Federation Hub documentation](https://tak.gov/documentation/resources/civ-documentation/tak-server-documentation/federation-hub)

## In infra-TAK (automated deploy)

1. Open **Marketplace → Federation Hub** (or `/federation-hub`).
2. Set **remote host**, SSH user/port, generate/install SSH key (same pattern as MediaMTX remote), **Save target**.
3. Upload **`takserver-fed-hub`** `.deb` from TAK.gov (drag/drop or file picker). The console validates the package with `dpkg-deb` — run the console on **Linux** for uploads.
4. Click **Deploy to remote host** — apt lock cleanup, SCP to `/tmp/`, ensure `/opt/tak/federation-hub/policies` exists (workaround for some package pre-install scripts that `cp policies/*`), `apt-get install`, `systemctl enable/restart federation-hub`, then registration in settings when the service is **active**.
5. Use **Restart / Start / Stop** for remote `systemctl` (requires passwordless `sudo` for that user, like other remote modules).

## HTTPS at `fedhub.<FQDN>` (Caddy on the infra-TAK console)

Federation Hub exposes a **web UI** on the **remote** Ubuntu host. infra-TAK can add a **Caddy** site on the **same machine that runs Caddy** (usually this console) so you use **`https://fedhub.<your-base-FQDN>`** with a Let’s Encrypt cert, while Caddy reverse-proxies to the hub over HTTP.

1. Set the console **FQDN** and deploy **Caddy SSL** (as for other subdomains).
2. **DNS:** create **`fedhub.<FQDN>`** → **public IP of the Caddy host** (this console), *not* the private Fed Hub IP — same idea as `infratak.*` or `stream.*`.
3. On **Federation Hub → HTTPS access**, set **Hub web UI port** to the HTTP port the hub listens on (see TAK.gov and `/opt/tak/federation-hub` config; often **8080**). The hub must accept connections from the console’s IP (not bound only to `127.0.0.1` unless you tunnel).
4. **Save target** (or complete **Deploy**) so the Caddyfile is regenerated and Caddy reloads.

### Hub login (username / password)

Admin credentials for the **Federation Hub application** are **not** stored in infra-TAK. Configure them per the **official TAK.gov Federation Hub** guide (setup wizard / security / `application.yml` as documented there). infra-TAK only stores this **console’s** login.

## Updating (after install)

Same idea as **Update TAK Server**: open **Update Federation Hub** on `/federation-hub`, upload a newer official `takserver-fed-hub` .deb (dedicated drop zone or the main upload area — same file store), then **Update Federation Hub**. The console SCPs to the target, runs `apt-get install`, and restarts `federation-hub`. Deploy and update cannot run at the same time.

## Manual install (fallback)

1. Complete the **official** install on the Ubuntu host so `/opt/tak/federation-hub` exists.
2. Click **Confirm install on target** — the console verifies that path over SSH and registers the module.

## Register vs uninstall

- **Remove from console** only clears infra-TAK settings; it does **not** remove packages on the target.

## Future work

- Rocky/RHEL paths, Docker Fed Hub, and deeper health checks can build on this shell.
