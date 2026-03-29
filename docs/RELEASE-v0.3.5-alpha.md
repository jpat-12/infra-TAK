# infra-TAK v0.3.5-alpha

Release Date: March 2026

---

## Highlights

- **Hotfix: updater loop resolved** — `v0.3.4-alpha` was tagged with an older in-app `VERSION` value (`0.3.3-alpha`), which caused the console to continue showing **Update Available** after updating.
- **No feature changes** — this release carries the same functional changes as v0.3.4-alpha and only corrects the release/version metadata so updates settle correctly.

---

## What end users should do after upgrading

1. **Update infra-TAK** — **Console → Update Now**.
2. Confirm sidebar version shows **v0.3.5-alpha** and update prompt clears.

---

## Summary of changes

| Area | Change |
|------|--------|
| **Versioning** | `app.py` `VERSION` updated to `0.3.5-alpha` to match the published tag and stop repeat update prompts. |
| **Docs** | Added `docs/RELEASE-v0.3.5-alpha.md`; updated README and release command examples. |

---

## Operator checklist (release maintainer)

- [ ] Tag/publish **`v0.3.5-alpha`**.
- [ ] If a server is stuck showing update after `v0.3.4-alpha`, run **Update Now** once more to move to `v0.3.5-alpha`.
