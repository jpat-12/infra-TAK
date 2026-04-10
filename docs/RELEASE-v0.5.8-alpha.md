# infra-TAK v0.5.8-alpha

Release Date: April 2026

---

## cert-metadata.sh ownership fix — TAK Portal integrations work after upgrades

### The problem

Creating a Node-RED (or any) integration from TAK Portal failed with:

```
Cert automation failed: ./makeCert.sh: line 6: cert-metadata.sh: Permission denied
mkdir: cannot create directory '': No such file or directory
```

This only affected servers that were **upgraded** to TAK Server 5.7 (e.g. from 5.6). Fresh 5.7 installs were unaffected.

### Root cause

Several code paths in infra-TAK modified `/opt/tak/certs/cert-metadata.sh` as root (Python `open()` / `sed -i` / `chmod +r`) without restoring `tak:tak` ownership afterward. The TAK Server installer creates this file as `tak:tak`, but after an upgrade or cert rotation it silently became `root:root`. When TAK Portal later ran `makeCert.sh` as the `tak` user, it could not source the file, so all cert-directory variables were empty and the entire cert chain failed.

### The fix

All five code paths that touch `cert-metadata.sh` now restore `tak:tak` ownership and `500` permissions after writing:

- `_patch_cert_metadata_password()` — Python file write now followed by `shutil.chown()`
- Intermediate CA rotation (Step 2/7, Step 4/7)
- Root CA rotation (Step 2/8)
- TAK Portal integration cert creation

**Existing affected servers:** run this once to fix immediately:

```bash
chown tak:tak /opt/tak/certs/cert-metadata.sh
chmod 500 /opt/tak/certs/cert-metadata.sh
```

Then retry the integration creation in TAK Portal.

---

## Node-RED: ArcGIS → TAK reconciliation engine (new)

New "ArcGIS → TAK Engine" flow tab (disabled by default). This is the first release of the sync engine — no prior version existed. It provides a single reconciliation loop for pushing ArcGIS Feature Service data into TAK missions via DataSync:

- **Poll timer** → load saved configs → query ArcGIS Feature Service (with WHERE + time filter)
- **Build CoT JSON** compatible with `node-red-contrib-tak` (polygons with links, points, styling, remarks)
- **Reconcile** against TAK mission contents → PUT new UIDs / DELETE stale UIDs via Mission API
- **TAK Server Settings** panel added to the configurator (server URL, API port, streaming port, creator UID)
- **Mission name** field added per config in Step 5
- **TLS config** placeholder — upload certs in the Node-RED editor before enabling

The engine tab ships disabled. To activate: configure TAK Server Settings in the configurator, add a mission name to your config, upload TLS certs in the Node-RED editor, wire the CoT output to a TAK node + tcp out, then enable the tab and deploy.

---

## Everything else

Includes all fixes from v0.5.7 and prior. See [v0.5.7-alpha](RELEASE-v0.5.7-alpha.md).
