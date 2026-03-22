# Testing the Update Now button before a release

The Update Now button in the web console runs a completely different code path from `git pull origin dev`. Pulling dev and restarting does **not** test the updater. You must test the button itself.

## How Update Now works

1. Console checks GitHub **tags** (not branches) to find the highest version.
2. If that tag is newer than the running `VERSION`, it shows "Update Available."
3. When you click **Update Now**, it runs: fetch tags → checkout highest tag → restart console.

Tags drive everything. Pushing to `dev` or `main` does **not** trigger customer updates. Only pushing a **tag** makes the banner appear.

## Pre-release test (zero customer exposure)

### Prerequisites

- Your test VPS is running (e.g. `63.250.55.132`).
- You have SSH access.
- Your new code is committed and pushed to `dev`.

### Steps

**1. Pull dev onto your test VPS**

```bash
cd $(grep -oP 'WorkingDirectory=\K.*' /etc/systemd/system/takwerx-console.service)
git pull origin dev
sudo systemctl restart takwerx-console
```

Your VPS now has the new updater code. No one else sees anything yet.

**2. Fake the version down**

```bash
sed -i 's/VERSION = "[^"]*"/VERSION = "0.0.1"/' app.py
sudo systemctl restart takwerx-console
```

Console now thinks it's `0.0.1`. It sees the current highest tag on GitHub (e.g. `v0.2.7-alpha`) as an update.

**3. Open the console in your browser**

You should see "Update Available" with the current highest tag. If the cache hasn't expired, click **Check for new release** or add `?refresh=1`.

**4. Click Update Now**

This runs the actual updater code path — the same thing customers will run. Watch for:

- Does it restart cleanly? (brief 502, then console loads)
- Does the sidebar show the tag version after restart?
- Any error banner?

**5. If it works — restore dev and proceed with release**

```bash
cd $(grep -oP 'WorkingDirectory=\K.*' /etc/systemd/system/takwerx-console.service)
git checkout -- app.py
git pull origin dev
sudo systemctl restart takwerx-console
```

VPS is back on dev with the real VERSION. Now do the normal release flow — **the exact list of paths to copy from `dev` to `main` is in [COMMANDS.md](COMMANDS.md) → “Merge dev → main (selective — release only)”** (not the whole `dev` branch). Each release, update the `docs/RELEASE-v…` line, commit message, and tag in that block.

```
git checkout dev && git pull origin dev
git checkout main && git pull origin main
git checkout dev -- …   # see COMMANDS.md for the full path list
git add -A && git commit -m "vX.Y.Z-alpha"
git push origin main
git tag vX.Y.Z-alpha && git push origin vX.Y.Z-alpha
git checkout dev
```

**6. If it breaks — fix before anyone sees it**

No tag was pushed, so no customer saw anything. Fix the code on dev, repeat from step 1.

### Optional: Guard Dog / updates email (v0.2.7-alpha+)

After **Update Now** succeeds on the test VPS, click **↻ Update Guard Dog** once. To sanity-check the “updates available” email path without waiting for the timer:

```bash
sudo rm -f /var/lib/takguard/updates_notified
sudo /opt/tak-guarddog/tak-updates-watch.sh
tail -5 /var/log/takguard/updates.log
```

You should see `Updates email sent to …` or `No updates available`. Use **Guard Dog → Send test email** first if you have not confirmed Email Relay.

## Why this works

- The fake version (`0.0.1`) makes the console think it needs an update.
- The updater targets the highest **tag on GitHub**, which already exists from a previous release.
- No new tag is pushed during testing, so customers never see an update prompt.
- You are testing the exact code path customers will use (fetch → checkout → restart).

## What this catches

- Rebase/merge/cherry-pick conflicts (the v0.2.4 bug).
- Broken git state handling (detached HEAD, stale operations).
- Tag resolution failures.
- Restart failures after checkout.

## Quick reference

| Action | Who sees it? |
|--------|-------------|
| Push to `dev` | Nobody (no update banner) |
| Push to `main` | Nobody (no update banner) |
| Push a **tag** | Everyone on older versions sees "Update Available" |
| Delete a tag | Banner disappears on next cache refresh (~10 min) |

**Rule: never push a tag until you have tested Update Now on your VPS.**
