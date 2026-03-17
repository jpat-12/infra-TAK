# infra-TAK v0.2.6-alpha

Release Date: March 2026

---

## Highlights

- **Update Now hotfix** — Fixed an updater failure where some installs hit git rebase/cherry-pick conflict errors during web-console updates.
- **Safer update strategy** — Update Now now avoids `git pull --rebase --autostash` and uses deterministic fetch + checkout behavior designed for field installs.

---

## Update Now — conflict-proof behavior

- **Problem:** Some customer boxes entered update failures like:
  - `warning: skipped previously applied commit ...`
  - `Rebasing (...) error: could not apply ...`
  - `fatal: Exiting because of an unresolved conflict`
- **Root cause:** Update Now previously used `git pull --rebase --autostash`. On repos with detached/tag state, interrupted git metadata, or non-trivial local history, rebase could fail and leave the install in a bad state.
- **Fix in v0.2.6-alpha:**
  - abort stale in-progress operations (`rebase`, `merge`, `cherry-pick`) if present,
  - `git fetch --tags origin`,
  - resolve latest tag and `git checkout --force <tag>` (fallback: `refs/remotes/origin/main`),
  - restart console.
- **Result:** Update Now no longer tries to replay commit history during normal customer updates.

---

## Summary of code changes

| Area | Change |
|------|--------|
| **app.py** | `VERSION` updated to `0.2.6-alpha`. |
| **app.py** | `update_apply()` rewritten from `pull --rebase --autostash` to safe fetch + force-checkout flow with stale-operation cleanup. |
| **README.md** | Added `v0.2.6-alpha` changelog entry describing Update Now hotfix. |
