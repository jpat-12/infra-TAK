# Pull and restart on VPS

Run each command separately (one line at a time). Do not combine commands.

## Find the correct directory first

The service might not run from `/root/infra-TAK`. **Always check first:**

```bash
grep WorkingDirectory /etc/systemd/system/takwerx-console.service
```

Use whatever path that returns. Example output:
```
WorkingDirectory=/root/infra-TAK/infra-TAK
```

## Simple dev pull (separate commands)

```bash
cd $(grep -oP 'WorkingDirectory=\K.*' /etc/systemd/system/takwerx-console.service)
git fetch origin dev --tags
git checkout -B dev origin/dev
sudo systemctl restart takwerx-console
```

## Dev branch (explicit flow)

```bash
cd $(grep -oP 'WorkingDirectory=\K.*' /etc/systemd/system/takwerx-console.service)
git fetch origin dev --tags
git checkout -B dev origin/dev
sudo systemctl restart takwerx-console
```

## Main branch (stable)

```bash
cd $(grep -oP 'WorkingDirectory=\K.*' /etc/systemd/system/takwerx-console.service)
git fetch origin main --tags
git checkout -B main origin/main
sudo systemctl restart takwerx-console
```

## Upgrading to v0.2.0+

v0.2.0 switches from Flask dev server to gunicorn (production server). After pulling, run `start.sh` once to upgrade the service:

```bash
cd $(grep -oP 'WorkingDirectory=\K.*' /etc/systemd/system/takwerx-console.service)
sudo ./start.sh
```

This installs gunicorn and updates the systemd service. After that, normal `git pull` + `systemctl restart` works as usual.

More: `docs/COMMANDS.md`

---

## MediaMTX web editor: FQDN won’t load after update

If you updated the MediaMTX web editor and **https://stream.&lt;your-fqdn&gt;** (or your stream subdomain) no longer loads (502, connection refused, or blank):

### Fix from infra-TAK

In infra-TAK, open **MediaMTX**, then click **🔧 Patch web editor**. This patches and restarts the web editor on the same host (or remote) that MediaMTX uses. No CLI needed.

If the Web Console still doesn't load, use **Web editor logs** on the MediaMTX page to see why the service is failing.


---

**1. Check whether the editor service is running**

```bash
systemctl status mediamtx-webeditor
```

If it’s **failed** or **inactive**:

**2. See why it failed**

```bash
journalctl -u mediamtx-webeditor -n 60 --no-pager
```

Common causes after an editor update:

- **Python error** in the new `mediamtx_config_editor.py` (e.g. missing import or syntax change). The last lines of the log usually show the traceback.
- **Port already in use** — something else bound to 5080.

**3. Try starting it by hand (to see errors)**

```bash
cd /opt/mediamtx-webeditor
PORT=5080 python3 mediamtx_config_editor.py
```

If it exits immediately, the traceback in the terminal is the cause. Fix the script or dependencies, then:

```bash
sudo systemctl start mediamtx-webeditor
```

**4. If the service is running but FQDN still doesn’t load**

- **Regenerate Caddy and reload:** In infra-TAK, open **Caddy**, re-save your domain (or click Save so the Caddyfile is rewritten and Caddy reloads). Then try https://stream.&lt;fqdn&gt; again.
- **Check Caddy:** `systemctl status caddy` and `journalctl -u caddy -n 30 --no-pager` for proxy errors.
- **Check direct access:** On the server, `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5080/` should return 200 if the editor is up. If that works but the FQDN doesn’t, the issue is Caddy/proxy or DNS, not the editor.
