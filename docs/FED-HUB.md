# Federation Hub (infra-TAK module)

This module tracks **TAK Federation Hub** on a **dedicated Ubuntu host** reachable by **SSH** from the infra-TAK console. The primary flow matches **split-mode TAK database** deploy: upload the official `.deb` on the console, then infra-TAK **SCP**s it to the target and runs **`apt-get install`** there, followed by **MongoDB**, **certificate generation**, **config patching**, and `systemctl` for `federation-hub`. Manual install + **Confirm** remains a fallback.

## Official steps

Install and configure Federation Hub using the **TAK.gov** guide (Ubuntu .deb path, Java, optional MongoDB, certs, `federation-hub` service):

[Federation Hub documentation](https://tak.gov/documentation/resources/civ-documentation/tak-server-documentation/federation-hub)

## In infra-TAK (automated deploy)

1. Open **Marketplace → Federation Hub** (or `/federation-hub`).
2. Set **remote host**, SSH user/port, generate/install SSH key (same pattern as MediaMTX remote), **Save target**.
3. Upload **`takserver-fed-hub`** `.deb` from TAK.gov (drag/drop or file picker). The console validates the package with `dpkg-deb` — run the console on **Linux** for uploads.
4. Click **Deploy to remote host**. The automated deploy runs:
   1. Apt lock cleanup, SCP `.deb` to `/tmp/`, ensure `policies/` dir exists (vendor preinst workaround), `apt-get install`.
   2. **MongoDB 8.0** — add repo, install `mongodb-org`, enable/start `mongod`, generate random password into `federation-hub-broker.yml`, run vendor `configure.sh`.
   3. **Certificates** — `makeRootCa.sh`, `makeCert.sh ca` (intermediate), `makeCert.sh server` (hostname), `makeCert.sh client webadmin-fed` (admin cert). Uses `cert-metadata.sh` from the package. Skipped on re-deploy when certs already exist.
   4. **Patch config** — `federation-hub-ui.yml` and `federation-hub-broker.yml` get the actual truststore/keystore names (from intermediate CA and hostname).
   5. **Start** — `chown -R tak:tak`, `systemctl enable/restart federation-hub`, wait for `"Started FederationHubUIServer"` in UI log.
   6. **Register admin cert** — `federation-hub-manager.jar` + copy `webadmin-fed.p12` to `/root/`.
   7. **Firewall** — UFW allow 9100–9103.
   8. Console registration updated.
5. Use **Restart / Start / Stop** for remote `systemctl` (requires passwordless `sudo` for that user, like other remote modules).

## HTTPS at `fedhub.<FQDN>` (Caddy on the infra-TAK console)

Federation Hub exposes a **web UI** on the **remote** Ubuntu host (port **9100**, HTTPS with client cert). infra-TAK can add a **Caddy** site on the **same machine that runs Caddy** (usually this console) so you use **`https://fedhub.<your-base-FQDN>`** with a Let's Encrypt cert, while Caddy reverse-proxies to the hub.

1. Set the console **FQDN** and deploy **Caddy SSL** (as for other subdomains).
2. **DNS:** create **`fedhub.<FQDN>`** → **public IP of the Caddy host** (this console), *not* the private Fed Hub IP — same idea as `infratak.*` or `stream.*`.
3. On **Federation Hub → HTTPS access**, set **Hub web UI port** (default **9100**). The hub must accept connections from the console's IP.
4. **Save target** (or complete **Deploy**) so the Caddyfile is regenerated and Caddy reloads.

### Hub login (client certificate)

Two options:

**Option 1 — Client certificate (default, works out of the box):**
infra-TAK auto-generates **`webadmin-fed.p12`** during deploy and registers it via `federation-hub-manager.jar`. Download it from **`/root/webadmin-fed.p12`** on the target, import into your browser, then open **`https://<host>:9100`**. Password = TAK cert password (default **`atakatak`**).

**Option 2 — Authentik SSO (OAuth2/OIDC):**
If **Authentik** is deployed, click **"Enable Authentik login"** on the Federation Hub page. This:
1. Creates an **OAuth2/OIDC application** in Authentik (`Federation Hub` provider + app).
2. Patches **`federation-hub-ui.yml`** on the remote (`allowOauth: true`, Authentik endpoints, client ID/secret).
3. Restarts `federation-hub` and opens port **8446** (OAuth port).

Users in the **`authentik Admins`** group can then log in at `https://<host>:9100` with their Authentik username/password. Client cert login continues to work alongside OAuth.

## Updating (after install)

Same idea as **Update TAK Server**: open **Update Federation Hub** on `/federation-hub`, upload a newer official `takserver-fed-hub` .deb (dedicated drop zone or the main upload area — same file store), then **Update Federation Hub**. The console SCPs to the target, runs `apt-get install`, and restarts `federation-hub`. Deploy and update cannot run at the same time. Existing certs are preserved (the cert step is skipped when the server JKS already exists).

## Manual install (fallback)

1. Complete the **official** install on the Ubuntu host so `/opt/tak/federation-hub` exists.
2. Click **Confirm install on target** — the console verifies that path over SSH and registers the module.

## Register vs uninstall

- **Remove from console** only clears infra-TAK settings; it does **not** remove packages on the target.

## Network ports

| Port | Purpose |
|------|---------|
| 9100 | Federation Hub web UI (HTTPS, client cert) |
| 9101 | Federation V1 |
| 9102 | Federation V2 (default) |
| 9103 | Token Federation (optional) |
| 8446 | OAuth/OIDC login (when Authentik SSO enabled) |

## Future work

- Rocky/RHEL paths, Docker Fed Hub, and deeper health checks can build on this shell.
