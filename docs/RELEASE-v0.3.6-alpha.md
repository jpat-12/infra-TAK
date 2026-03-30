# infra-TAK v0.3.6-alpha

Release Date: March 2026

---

## Highlights

- **Firewall is now a dedicated always-on section** in the left navigation (not embedded in Guard Dog).
- **Full UFW controls in UI**: open/close ports, restrict source IP/CIDR to port+protocol, and delete by numbered rule.
- **Firewall UX upgrades**: collapsible sections, rule list refresh, service labels for known ports, and `shield_locked` icon.
- **TAK Server cert creation improvements**: READ/WRITE/BOTH selector alignment, correct BOTH (`-g`) handling, and clearer group assignment behavior.
- **TAK group picker is more complete**: cert-group loading now also queries Authentik `tak_*` groups so new groups can appear earlier.

---

## What end users should do after upgrading

1. **Update infra-TAK** — **Console → Update Now**.
2. Open **Firewall** in the left nav and validate expected UFW rules are present.
3. On **TAK Server → Create Client Certificate**, verify group permissions (READ/WRITE/BOTH) and generate one test cert.

---

## Summary of changes

| Area | Change |
|------|--------|
| **Firewall page** | Added new always-available `/firewall` page with dedicated script (`static/firewall.js`) and sidebar entry. |
| **Firewall APIs** | Added status, open port, close port, source restriction (`allow/deny from <CIDR>`), and delete-by-rule-number endpoints. |
| **Guard Dog** | Removed embedded firewall control card from Guard Dog page to avoid split ownership/confusion. |
| **TAK cert assignment** | Added proper support for BOTH group permission (`-g`) in cert generation; deduped and normalized group lists. |
| **TAK groups source** | Group loader now merges groups from TAK APIs and Authentik `tak_*` groups so new groups are visible sooner. |
| **TAK deploy UX** | Added show/hide toggle for keystore/truststore password field in TAK Server deploy config. |
| **Release safety** | Added required pre-tag check guidance to ensure `app.py` `VERSION` matches release tag. |

---

## Operator checklist (release maintainer)

- [ ] Confirm `app.py` contains `VERSION = "0.3.6-alpha"` before tagging.
- [ ] Tag/publish **`v0.3.6-alpha`**.
- [ ] Run **Update Now** on a test VPS and confirm sidebar shows **v0.3.6-alpha** after restart.
