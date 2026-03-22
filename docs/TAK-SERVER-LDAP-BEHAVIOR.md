# TAK Server → LDAP: Observed Behavior

**Context:** TAK Server with LDAP auth (Authentik LDAP outpost). Observed on infra-TAK deployments; this doc is for upstream/dev reference.

**User-facing symptom:** When able to get onto CloudTAK, the channels prompt / channel-status UI appears repeatedly (user sees the “channels thing” over and over). In other cases, login or loading spins and then fails with 504 / “Unexpected token '<'”.

---

## Observed behavior

- **Client:** TAK Server (or a process on the same host as TAK Server) appears in the LDAP outpost logs as `client: "172.18.0.1"` (Docker bridge / host).

- **Pattern:** Repeated **Bind** (as `cn=adm_ldapservice,ou=users,dc=takldap`, "authenticated from session") followed by **Search** requests for the same user entry:
  - `baseDN`: `cn=admin,ou=users,dc=takldap`
  - Attributes: `[]` or `["memberOf","ntUserWorkstations"]`
  - Scope: Base Object  
  - Filter: `(objectClass=*)`

- **Cadence:** This bind+search sequence for `cn=admin` recurs on the order of every **~2 seconds** while CloudTAK (or 8446 / web use) is active; the LDAP outpost logs show many such cycles in a short window (e.g. dozens over ~1 minute).

- **Direction:** Traffic is TAK Server → LDAP outpost (port 389). The LDAP/IdP side does not initiate requests to TAK Server.

- **Downstream observation:** When CloudTAK is open and this pattern is present, the CloudTAK frontend can receive **504 Gateway Timeout** (HTML) when calling its API. The API request is proxied to the CloudTAK backend, which in turn appears to call TAK Server. If TAK Server is slow to respond, the reverse proxy times out and returns 504 with an HTML error page; the frontend then reports `Unexpected token '<'` when parsing the response as JSON.

---

## How this was captured

- **LDAP outpost logs:** `docker compose logs -f ldap --tail=0` (Authentik stack). Log lines show `Bind request`, `Search request`, `baseDN`, `attributes`, `client`, and timestamps.
- **Authentik server logs:** `docker compose logs -f server --tail=0` filtered for request events. No corresponding burst of requests from the map/CloudTAK host to Authentik during the LDAP burst; the traffic is TAK Server → LDAP only.

Reproduce by starting the LDAP log tail, then opening CloudTAK (or 8446) and using it for 1–2 minutes; the bind+search pattern for `cn=admin` appears every ~2 seconds in the LDAP log.
