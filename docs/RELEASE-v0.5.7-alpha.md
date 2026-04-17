# infra-TAK v0.5.7-alpha

Release Date: April 2026

---

## JVM heap settings preserved across TAK Server upgrades

### The problem

When TAK Server is upgraded via `apt-get install ./takserver_*.deb`, the package's `postinst` script can overwrite `/etc/default/takserver`. This file holds the custom JVM heap allocation set from the infra-TAK console (e.g. `CONFIG_MAX_HEAP`, `API_MAX_HEAP`, `MESSAGING_MAX_HEAP`, etc.). After an upgrade, heap settings silently reverted to package defaults, potentially causing `OutOfMemoryError` on busy servers.

### The fix

Both the single-server and two-server upgrade flows now:

1. **Backup** `/etc/default/takserver` before the upgrade begins
2. Run the upgrade (`dpkg --configure -a` / `apt-get install`)
3. **Restore** the backup after the upgrade completes, before TAK Server restarts

If no custom heap file exists (package defaults), the backup/restore is skipped. The upgrade log shows "JVM heap settings backed up" and "JVM heap settings restored" so you can confirm it worked.

---

## Everything else

Includes all fixes from v0.5.6 and prior. See [v0.5.6-alpha](RELEASE-v0.5.6-alpha.md).
