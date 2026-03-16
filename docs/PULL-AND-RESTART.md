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
git pull origin dev
sudo systemctl restart takwerx-console
```

## Dev branch (explicit flow)

```bash
cd $(grep -oP 'WorkingDirectory=\K.*' /etc/systemd/system/takwerx-console.service)
git fetch origin
git checkout dev
git pull --ff-only origin dev
sudo systemctl restart takwerx-console
```

## Main branch (stable)

```bash
cd $(grep -oP 'WorkingDirectory=\K.*' /etc/systemd/system/takwerx-console.service)
git fetch origin
git checkout main
git pull --ff-only origin main
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
