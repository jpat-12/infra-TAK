# Federation Hub (infra-TAK module)

This module tracks **TAK Federation Hub** on a **dedicated Ubuntu host** reachable by **SSH** from the infra-TAK console. It does **not** replace the official installer; it adds console integration (SSH target, registration, basic `systemctl` control).

## Official steps

Install and configure Federation Hub using the **TAK.gov** guide (Ubuntu .deb path, Java, optional MongoDB, certs, `federation-hub` service):

[Federation Hub documentation](https://tak.gov/documentation/resources/civ-documentation/tak-server-documentation/federation-hub)

## In infra-TAK

1. **Marketplace → Federation Hub** (or `/federation-hub`).
2. Set **remote host**, SSH user/port, generate/install SSH key (same pattern as MediaMTX remote).
3. **Save target settings**.
4. On the Ubuntu box, complete the **official** install so `/opt/tak/federation-hub` exists.
5. Click **Confirm install on target** — the console verifies that path over SSH and registers the module (sidebar + “installed” state).
6. Use **Restart / Start / Stop** to run `systemctl` on the target (requires passwordless `sudo` for that user, as with other remote actions).

## Register vs uninstall

- **Remove from console** only clears infra-TAK settings; it does **not** remove packages on the target.

## Future work

- Rocky/RHEL paths, Docker Fed Hub, deeper health checks, and guided deploy automation can build on this shell.
