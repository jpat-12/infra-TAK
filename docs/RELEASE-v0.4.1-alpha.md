# infra-TAK v0.4.1-alpha

Release Date: April 2026

---

## Highlights

- **Update Now — real tag-clobber fix**: v0.4.0 fetched only the latest tag by refspec, but Git still applies **`remote.origin.fetch`** alongside any explicit refspec. That could continue to update remote-tracking branches and other tags and trigger **`would clobber existing tag`**. **v0.4.1** runs tag (and main fallback) fetches with **`git -c remote.origin.fetch=`** so only the requested refspec runs.

---

## What end users should do

1. **Already on v0.4.0-alpha** and **Update Now** still fails: upgrade to **v0.4.1-alpha** via **Update Now** once this tag is on `main`, or one-time [PULL-AND-RESTART.md](PULL-AND-RESTART.md) / `git checkout --force v0.4.1-alpha` + restart console.
2. **Still on pre-v0.4.0**: One-time jump to **v0.4.1-alpha** (or v0.4.0+) per [PULL-AND-RESTART.md](PULL-AND-RESTART.md); then **Update Now** uses the isolated fetch path.
3. **Pre-release (maintainers):** [docs/TESTING-UPDATES.md](TESTING-UPDATES.md) before tagging.

---

## Release checklist

- [ ] `app.py` → `VERSION = "0.4.1-alpha"` matches tag **`v0.4.1-alpha`** (see [COMMANDS.md](COMMANDS.md) Python check).
- [ ] Selective `dev` → `main` copy uses **only** [COMMANDS.md](COMMANDS.md) list; release doc line is **`docs/RELEASE-v0.4.1-alpha.md`**.
- [ ] Tag **`v0.4.1-alpha`** and push after `main` push.
