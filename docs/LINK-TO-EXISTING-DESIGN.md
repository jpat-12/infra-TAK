# Link to existing services — design sketch (v0.3.0 / late v0.2.x)

**Goal:** Let users who already have Authentik, TAK Server, or TAK Portal use infra-TAK for Guard Dog, rotating CA, MediaMTX, Caddy, etc., by **linking** to those existing services instead of deploying new ones.

**No code in this doc — design only.**

---

## 1. User story

- I have an existing stack: Authentik + TAK Server (and maybe TAK Portal) on one or more hosts.
- I want: Guard Dog, rotating CA, MediaMTX, Caddy, email relay — but I don’t want to redeploy or replace my current Authentik/TAK.
- I deploy infra-TAK as usual (one clone, start, set password). Then in the **marketplace** (or on each module page) I choose **Link to existing** for Authentik and TAK Server instead of **Deploy new**.

---

## 2. Where the choice lives (UX)

- **Marketplace:** Today it shows only “not installed” modules. For a v0.3.0-style flow, clicking a module could open its **module page** (e.g. Authentik, TAK Server) where the first choice is:
  - **Deploy new** — current behavior (we deploy it).
  - **Link to existing** — I already have this; I’ll give you URL/token/host and you use it.
- So the “link vs deploy” decision is **per module, on that module’s page**, not a global mode. You can mix: e.g. link to existing Authentik + link to existing TAK Server, but deploy MediaMTX and Guard Dog.
- Once linked, the module page shows a “Linked” state (read-only or limited actions) instead of Deploy/Update/Remove. Optional: “Re-link” or “Switch to Deploy new” (with confirmation).

---

## 3. Per-module sketch

### 3.1 Authentik — Link to existing

- **User provides:** Authentik base URL (e.g. `https://auth.example.com`), admin/bootstrap token (or token with enough scope for LDAP and apps). Optionally: LDAP outpost ID or “we’ll use default/provider name.”
- **Console does:** Stores “external Authentik” in settings. No Docker/compose deploy. All flows that today talk to “our” Authentik (TAK Portal, Connect LDAP, Email Relay → Configure Authentik, Node-RED app, etc.) use this URL + token instead.
- **Guard Dog:** Doesn’t deploy or manage Authentik containers. Optionally: “Monitor external Authentik” = health check (HTTP/HTTPS to that URL) and optional alert if down. No restart; just “it’s down, notify me.”

### 3.2 TAK Server — Link to existing

- **User provides:** Where the existing TAK Server lives:
  - **Option A:** Same host as infra-TAK: path to TAK (e.g. `/opt/tak`). Console assumes standard layout (CoreConfig, certs, etc.).
  - **Option B:** Remote host: SSH host + user + key (same pattern as remote deploy). Path on that host (e.g. `/opt/tak`).
- **Console does:** No .deb upload or TAK install. We “adopt” that install: read CoreConfig, cert paths, version; offer **Connect LDAP** (patch CoreConfig to point at the linked Authentik’s LDAP), **Rotating CA**, **Guard Dog** (monitors that path/host).
- **Guard Dog:** Already has “remote host” concept. “Linked” TAK Server = we run the same health checks (process, DB, disk, cert expiry, CoT size) on that host/path. Alerts and auto-recovery (restart service) apply to that install.
- **Rotating CA:** Same logic as today; target is the linked path (local or over SSH). Generate new CA, patch CoreConfig, restart TAK Server on that host.

### 3.3 TAK Portal — Link to existing (optional)

- **User provides:** TAK Portal URL (and maybe API key or “we use Authentik for login”). Or: “I don’t use TAK Portal” / “I’ll deploy it with infra-TAK.”
- **Console does:** If linked, we don’t deploy TAK Portal. We might still show a card “TAK Portal (external)” with link and optional “Sync CA” or “Re-fetch settings” if we have an API. If “Deploy new,” current behavior.

### 3.4 Modules we still deploy (unchanged)

- **MediaMTX** — Deploy as today; no “link to existing” needed (they’re adding streaming).
- **Guard Dog** — We deploy it; it then monitors whatever TAK Server / Authentik we have (deployed or linked).
- **Caddy, Email Relay, Node-RED, CloudTAK** — Deploy as today. They consume “Authentik” and “TAK Server” from settings (which may now point at linked instances).

---

## 4. Flow order with “link” in the mix

- **Today:** Caddy → Authentik (deploy) → Email Relay → TAK Server (deploy) → Connect LDAP → TAK Portal (deploy).
- **With link:** Caddy (optional) → **Authentik:** “Link to existing” or “Deploy new” → Email Relay (optional) → **TAK Server:** “Link to existing” or “Deploy new” → **Connect LDAP** (same step; works if Authentik is linked or deployed) → **TAK Portal:** “Link to existing” or “Deploy new.”
- Connect LDAP, rotating CA, and Guard Dog don’t care whether Authentik/TAK were deployed by us or linked; they just need the right URLs, tokens, and paths in settings.

---

## 5. Settings / data model (conceptual)

- For each linkable module we’d have something like:
  - `authentik_mode`: `deployed` | `external`
  - `authentik_external_url`, `authentik_external_token`
  - `takserver_mode`: `deployed` | `external`
  - `takserver_external_host` (optional), `takserver_external_path` (e.g. `/opt/tak`), SSH credentials if remote
- Existing “deployed” flags and paths stay; when mode is `external`, we use the external_* fields and never run deploy for that module.

---

## 6. What “installed” means for cards/marketplace

- **Today:** “Installed” = we detect the service (e.g. Authentik containers, TAK at `/opt/tak`). Marketplace hides installed modules.
- **With link:** “Installed” could mean either “we deployed it” or “we linked to it.” So Authentik card shows as “installed” and links to the Authentik page, where the UI shows “Linked to https://auth.example.com” and read-only (or Re-link), not Deploy/Update/Remove.
- Marketplace could show Authentik/TAK Server/TAK Portal with a subtitle: “Deploy new or link to existing” and clicking goes to the module page where the choice is made.

---

## 7. Scope for v0.3.0 or late v0.2.x

- **Phase 1 (minimal):** “Link to existing” for **Authentik** and **TAK Server** only; TAK Portal stays “deploy only” for now. Connect LDAP and rotating CA work with linked TAK + linked Authentik. Guard Dog can monitor linked TAK Server (path + optional SSH).
- **Phase 2:** “Link to existing” for **TAK Portal**; optional “monitor external Authentik” in Guard Dog (HTTP health check).
- **Phase 3:** Polish — Re-link, “Switch to Deploy new” (with warnings), and clearer onboarding (e.g. “Do you already have Authentik? Link or Deploy”).

---

## 8. Risks / considerations

- **Tokens and URLs:** Storing external Authentik token is sensitive; same security as current bootstrap token storage.
- **Version drift:** We don’t control linked Authentik/TAK versions; some features (e.g. LDAP schema) might assume a minimum version. Doc or UI can say “Tested with Authentik 2024.x / TAK Server 4.x.”
- **Guard Dog on remote TAK:** We already have SSH + remote host; main work is “TAK Server is at this path on this (possibly remote) host” and running the same checks there.

---

## 9. Summary

| Item | Notes |
|------|--------|
| **UX** | On each module page (Authentik, TAK Server, later TAK Portal): choose **Link to existing** or **Deploy new**. No code in this doc. |
| **Authentik link** | URL + token; all console flows use it instead of “our” Authentik. |
| **TAK Server link** | Path (local or remote host + path); Connect LDAP, rotating CA, Guard Dog target that install. |
| **Guard Dog / CA** | No change to feature set; they consume settings that can point at linked or deployed services. |
| **MediaMTX / Caddy / etc.** | Deploy as today; they work with linked Authentik/TAK via settings. |
| **Target release** | v0.3.0 or late v0.2.x; Phase 1 = Authentik + TAK Server link only. |
