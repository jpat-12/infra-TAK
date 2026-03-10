# Pull and restart on VPS

Use the explicit branch flow below to avoid pulling the wrong branch.

## Dev branch (recommended for testing)

```bash
cd /root/infra-TAK
git fetch origin
git checkout dev
git pull --ff-only origin dev
sudo systemctl restart takwerx-console
```

## Main branch (stable)

```bash
cd /root/infra-TAK
git fetch origin
git checkout main
git pull --ff-only origin main
sudo systemctl restart takwerx-console
```

## Quick current-branch pull (only if you already verified branch)

```bash
cd /root/infra-TAK && git pull --ff-only && sudo systemctl restart takwerx-console
```

*(Repo not in `/root/infra-TAK`? Replace with your actual path.)*

More: `docs/COMMANDS.md`
