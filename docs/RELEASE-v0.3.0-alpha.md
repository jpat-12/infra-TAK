# infra-TAK v0.3.0-alpha

Release Date: March 2026

---

## Highlights

- **Two-server TAK Server upgrade** — Full support for upgrading split (core + database) deployments from the console. Upload both `takserver-core` and `takserver-database` .deb packages; the UI shows both files, validates package type, and runs core upgrade on this host then database upgrade on Server One via SSH.
- **Package-type enforcement** — Upgrade and deploy flows now accept only the correct package for your mode: **split** = only `takserver-core` and `takserver-database` .deb; **one-server** = only the single `takserver` .deb. Wrong packages are rejected at upload with a clear message.
- **Post-upgrade refresh** — After an upgrade completes, the page auto-refreshes. If it doesn’t (e.g. tab in background), a **Refresh page** button appears so you can reload and see the new version. The “Done” state clears after one view so the next load shows a clean Update section.

---

## What end users should do after upgrading

1. **Update infra-TAK** — **Console → Update Now** (or `git pull` + restart).
2. **Two-server TAK operators:** When upgrading TAK Server next, use **Update TAK Server** → drag and drop both `takserver-core` and `takserver-database` .deb (browse is disabled in split mode so only those two packages can be used). Then click **Update TAK Server**.
3. No other steps required.

---

## Summary of changes

| Area | Change |
|------|--------|
| **Update TAK Server (two-server)** | UI shows both core and database files; no longer clears the list when uploading the second file. Existing uploads are loaded on page load. Update button enables only when both packages are present. |
| **Split mode upgrade** | Only `takserver-core` and `takserver-database` .deb are accepted. Monolithic `takserver` .deb is rejected. File picker is disabled; use drag-and-drop only. |
| **One-server upgrade** | Only the single `takserver` .deb is accepted. Core or database .deb packages are rejected. |
| **Deploy (initial install)** | Same rules at upload: one-server accepts only the single .deb; split accepts only core and database .deb. Wrong type shows a red row and message. |
| **Post-upgrade UX** | Auto-refresh 1.2s after upgrade completes. Retry poll when server reports “not running” to catch completion. “Refresh page” button when log shows Done. Upgrade “done” state clears after one view so the next load is clean. |

---

## Operator checklist (release maintainer)

- [ ] Run **TESTING-UPDATES.md** protocol on test VPS.
- [ ] Merge to `main`, tag `v0.3.0-alpha`, push tag: `git tag v0.3.0-alpha && git push origin v0.3.0-alpha`
- [ ] Recommend upgrade to all active deployments.
