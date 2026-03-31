# infra-TAK v0.3.7-alpha

Release Date: March 2026

---

## Highlights

- **Create Client Cert group picker is now channel-centric**: groups with TAK Portal directional suffixes (`_READ`, `_WRITE`, `_BOTH`, and dash variants) are normalized to one canonical channel name.
- **Duplicate directional variants are collapsed** so operators don't assign the same channel multiple times under different suffix forms.
- **System/admin groups are hidden from cert picker** to reduce mistakes and noise (`authentik*`, `cn=tak_*`, `ROLE_ADMIN`, `vid_public`, `vid_private`).
- **Pull/restart and updater/release docs were hardened** with safer sync guidance to avoid divergent-branch pull failures.

---

## Why this matters

TAK operators expect certificate assignment to target operational channel names, not LDAP naming artifacts. This release aligns the UI and backend behavior so cert assignments are consistent with how data channels are actually managed.

---

## What end users should do after upgrading

1. **Update infra-TAK** — **Console → Update Now**.
2. Open **TAK Server → Create Client Certificate → Show groups**.
3. Confirm the picker shows clean channel names (no directional/admin/system clutter) and assign READ/WRITE/BOTH as needed.

---

## Summary of changes

| Area | Change |
|------|--------|
| **TAK cert group normalization** | Added canonical group-name normalization in backend group loading and cert assignment (`_READ/_WRITE/_BOTH` collapse to base channel). |
| **TAK cert picker filtering** | Excluded non-operational/system groups from picker (`authentik*`, `cn=tak_*`, `ROLE_ADMIN`, `vid_public`, `vid_private`, anon/empty). |
| **Docs: update reliability** | Updated pull/restart and update-testing docs to use deterministic branch sync guidance and reduce divergent-branch failures during maintenance. |
| **Release docs/tooling** | Updated release command examples for `v0.3.7-alpha` and added this release document. |

---

## Operator checklist (release maintainer)

- [ ] Confirm `app.py` contains `VERSION = "0.3.7-alpha"` before tagging.
- [ ] Tag/publish **`v0.3.7-alpha`**.
- [ ] Run **Update Now** on a test VPS and confirm sidebar shows **v0.3.7-alpha** after restart.
