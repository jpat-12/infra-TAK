# infra-TAK v0.1.8-alpha

Release Date: 2026-03-02

---

## LDAP QR Registration Fix

**LDAP application was restricted to authentik Admins**, blocking QR code enrollment for non-admin users. LDAP is now open to all authenticated users. Connect LDAP / Resync LDAP applies this fix automatically.

## Fresh Deploy Flow

8446 webadmin login and QR registration now work on **initial deployment** without manual Sync webadmin or Resync LDAP. LDAP outpost restart runs at end of TAK Server deploy and during Connect LDAP.

## Authentik Deploy

- Caddy reload timeout (30s) prevents indefinite hang
- Progress message "Updating Caddy config..." before slow steps

## Recommended Deployment Order

```
Caddy → Authentik → Email Relay → TAK Server → Connect LDAP → TAK Portal → Node-RED / CloudTAK / MediaMTX
```

## Changes

- `app.py`: LDAP removed from admin-only apps; app policy removal in Connect LDAP; Caddy reload timeout; Authentik deploy progress messages
- `README.md`: Updated deployment order, v0.1.8 changelog
- MediaMTX LDAP overlay, Help page, Uninstall-all on Help, Caddy full cleanup

## Status

All modules except **Guard Dog** are production-ready.
