# infra-TAK v0.2.9-alpha

Release Date: March 2026

---

## Highlights

- **Deep security hardening** — Comprehensive audit and remediation of shell injection, session management, credential handling, information disclosure, and file permission issues across the entire codebase.

---

## What end users should do after upgrading

1. **Update infra-TAK** — **Console → Update Now** (or pull + restart).
2. No additional steps required. All fixes take effect immediately on restart.

---

## Summary of changes

| Area | Change |
|------|--------|
| **Shell injection (CRITICAL/HIGH)** | User-controlled inputs to `subprocess.run` (log viewers, cert group names, domain/FQDN in sed, package filenames in apt, GitHub version in wget) are now validated, whitelisted, or escaped with `shlex.quote()`. List-form commands replace `shell=True` where possible. |
| **Credential handling** | Hardcoded default passwords removed; random passwords generated via `secrets.token_urlsafe()` and persisted to settings. `sshpass -p` (password visible in `ps`) replaced with `sshpass -e` (env var). Certificate password setter validates input characters. |
| **Session security** | Session cookie flags (`HttpOnly`, `SameSite=Lax`) added. Session cleared on login to prevent fixation. Logout route restricted to POST. X-Forwarded-For trusted only from loopback for rate limiting. |
| **File permissions** | `settings.json` written with `0o600` permissions. Sensitive temp files (`tak-portal-settings.json`, `.p12`, CA bundles) use `tempfile.mkstemp()` instead of world-readable `/tmp/` paths. |
| **Information disclosure** | Exception messages in API responses truncated to 200 characters. Secrets (bootstrap passwords, API tokens, LDAP passwords) masked in deploy logs. |
| **Input validation** | FQDN validated on save. MediaMTX version from GitHub validated before use. `StrictHostKeyChecking=accept-new` replaces `=no` on SSH key install. |

---

## Operator checklist (release maintainer)

- [ ] Run **TESTING-UPDATES.md** protocol on test VPS.
- [ ] Merge to `main`, tag `v0.2.9-alpha`, push tag.
- [ ] Recommend upgrade to all active deployments.
