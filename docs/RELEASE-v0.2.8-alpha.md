# infra-TAK v0.2.8-alpha

Release Date: March 2026

---

## Highlights

- **Security hardening** — Input validation and sanitization across console API endpoints and internal shell commands. All user-supplied and settings-derived values that reach system commands are now validated, whitelisted, or escaped. Recommended upgrade for all deployments.
- **Authentik login branding** — Starter TAK logo shipped with the repo; new guide for Custom CSS, dark theme, and flow text customization ([docs/AUTHENTIK-LOGIN-BRANDING.md](AUTHENTIK-LOGIN-BRANDING.md)).

---

## What end users should do after upgrading

1. **Update infra-TAK** — **Console → Update Now** (or pull + restart).
2. No additional steps required. The security fixes take effect immediately on restart.

---

## Summary of changes

| Area | Change |
|------|--------|
| **API input validation** | Console API endpoints that accept parameters (log viewers, container names) now validate and sanitize all inputs before use. |
| **Shell command safety** | Settings-derived values (certificate passwords, hostnames, domain names) used in internal shell commands are now properly escaped. |
| **Certificate password** | The certificate password setter rejects characters that could interfere with system commands. Alphanumeric and common punctuation are allowed. |
| **Authentik branding** | `static/authentik-branding/tak-gov-brand.svg` bundled; copied to Authentik media on deploy/reconfigure. |
| **Docs** | [docs/AUTHENTIK-LOGIN-BRANDING.md](AUTHENTIK-LOGIN-BRANDING.md) — Custom CSS, Brand Attributes (dark theme), flow text, starter logo. |

---

## Operator checklist (release maintainer)

- [ ] Run **TESTING-UPDATES.md** protocol on test VPS.
- [ ] Merge to `main`, tag `v0.2.8-alpha`, push tag.
- [ ] Recommend upgrade to all active deployments.
