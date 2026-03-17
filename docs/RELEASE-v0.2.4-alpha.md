# infra-TAK v0.2.4-alpha

Release Date: March 2026

---

## Highlights

- **MediaMTX web editor — Patch web editor** — Fixes the crash loop caused by duplicate Flask endpoints after the LDAP overlay is applied. The console patches shared-stream and share-links routes (shared_stream_page, shared_hls_proxy, api_share_links_list, api_share_links_generate, api_share_links_revoke) so the overlay and core don't conflict. Use **Patch web editor** on the MediaMTX page if the editor is already in a loop; the same patch runs on deploy and at service start via the heal script.
- **Update Now — fix "update then still see banner"** — Update Now now fetches and checks out the **latest release tag** (e.g. v0.2.3-alpha) after `git pull`, so the restarted console actually runs that version. The "Update Available" banner and sidebar version then match after you refresh; no more loop where it says it updated but the UI still shows the old version.

---

## MediaMTX web editor — endpoint patch

- **Problem:** With the infra-TAK LDAP overlay injected into the MediaMTX web editor, Flask saw the same route/endpoint registered twice (overlay + core), leading to `AssertionError: View function mapping is overwriting an existing endpoint function` and a service restart loop.
- **Fix:** The console (and the heal script that runs at editor service start) applies an **endpoint patch**: for each of the duplicate view names, it finds the core’s `@app.route` and adds an explicit `endpoint='..._core'` so both overlay and core can coexist.
- **Patched views:** shared_stream_page, shared_hls_proxy, api_share_links_list, api_share_links_generate, api_share_links_revoke.
- **What you do:** If the editor is already crashing, open the MediaMTX page and click **Patch web editor**. For new deploys or after pull+restart, the patch is applied automatically.

---

## Console Update Now — checkout latest tag

- **Problem:** Clicking **Update Now** ran `git pull` (current branch only). The "latest" version in the UI comes from GitHub **tags**. If the release was only tagged (e.g. v0.2.3-alpha) and the branch wasn’t updated to that commit, the tree stayed on the old code. After restart, the app still had the old `VERSION` and the "Update Available" banner never went away.
- **Fix:** After a successful pull, Update Now **fetches the latest release tag** from the GitHub tags API and runs `git fetch origin tag <tagname>` and `git checkout --force <tagname>`. The restarted process then runs the tagged release; the sidebar and update check show the new version and the banner disappears after refresh.
- **Note:** If tag fetch or checkout fails (e.g. network), the handler still clears the cache and restarts; you may remain on the branch tip until the next successful update.

---

## Summary of code changes

| Area | Change |
|------|--------|
| **app.py** | `VERSION` set to `0.2.4-alpha`. |
| **app.py** | `_fetch_latest_tag_name()` added; Update Now fetches and checks out latest release tag after pull. |
| **app.py** | Endpoint patch list extended with api_share_links_list, api_share_links_generate, api_share_links_revoke (ensure-overlay script, remote ep_script, `_mediamtx_editor_endpoint_patch()`). |
| **scripts/fix-mediamtx-webeditor-now.sh** | Same share-links endpoint entries added to the embedded patch loop. |
