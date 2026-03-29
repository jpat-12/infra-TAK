# infra-TAK v0.3.4-alpha

Release Date: March 2026

---

## Highlights

- **TAK Server — new Federation section**: Added a dedicated **Federation** card on the TAK Server page with:
  - V2 federation status + detected port
  - one-click `ca.pem` download
  - inbound firewall open/close control for the federation port
- **Group mapping gotcha documented**: For federation/group mapping, use **bare group names** (example: `CA-COR ADSB2`) instead of LDAP DN format (example: `cn=tak_CA-COR ADSB2`). LDAP search can still help find the group, but remove the `cn=tak_` prefix before adding.
- **Fed Hub firewall behavior clarified**: Remote Federation Hub deploy already opens required ports automatically (`22`, `8080`, `9100-9103`) via UFW on the target host.

---

## What end users should do after upgrading

1. **Update infra-TAK** — **Console → Update Now** (or `git pull` + `sudo systemctl restart takwerx-console`).
2. **TAK Server federation users** — Open **TAK Server → Federation** and use:
   - `Download ca.pem` for CA exchange
   - federation port firewall toggle when acting as receiver
3. **When mapping groups** — Use short group labels (e.g., `CA-COR ADSB2`), not `cn=tak_*` strings.

---

## Summary of changes

| Area | Change |
|------|--------|
| **TAK Server UI** | Added Federation card (status, `ca.pem` download, UFW toggle for V2 port). |
| **TAK Server API** | Added federation helper APIs: federation status, federation firewall toggle, and `ca.pem` download endpoint. |
| **Federation guidance** | Documented group-name normalization for mapping/filtering (`CA-COR ADSB2` vs `cn=tak_CA-COR ADSB2`). |
| **Fed Hub ops** | Clarified remote deploy auto-opens required ports (`22`, `8080`, `9100-9103`). |

---

## Operator checklist (release maintainer)

- [ ] Run **TESTING-UPDATES.md** protocol on a test VPS.
- [ ] Selective merge to `main`, tag **`v0.3.4-alpha`**, push tag (see **docs/COMMANDS.md**).
- [ ] If Guard Dog is deployed, click **↻ Update Guard Dog** after console update.
