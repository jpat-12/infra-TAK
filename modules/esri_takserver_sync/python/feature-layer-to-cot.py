#!/usr/bin/env python3
"""
Esri-TAKServer-Sync — Feature Layer to CoT
Polls an Esri Feature Layer and broadcasts records as CoT events to TAK Server.
"""

import hashlib
import json
import logging
import os
import signal
import socket
import ssl
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape, quoteattr as _xml_quoteattr

import requests

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_PATH = os.environ.get(
    "ESRI_TAK_CONFIG",
    "/opt/Esri-TAKServer-Sync/config.json"
)

DEFAULT_CONFIG = {
    "tak_server": {
        "host": "localhost",
        # auth_mode controls how the client authenticates to TAK Server:
        #   "cert"  — TLS with a .p12 client certificate (port 8089 default)
        #             The cert must be enrolled/trusted by TAK Server.
        #   "plain" — Plain TCP, no certificate required (port 8087 default)
        #             Use this for quick testing or when TLS is handled upstream.
        #   "rest"  — HTTPS REST API POST to /Marti/api/cot/xml (port 8443 default)
        #             Uses HTTP Basic Auth (username + password). No cert files needed.
        "auth_mode": "cert",
        "port": 8089,
        "username": "",         # REST mode only
        "password": "",         # REST mode only
        "cert_path": "/opt/Esri-TAKServer-Sync/certs/esri-push.p12",
        "cert_password": "",
        "ca_cert": ""           # path to TAK Server CA cert for verification; empty = no verify
    },
    "feature_layer": {
        "url": "",
        "public": True,
        "layer_type": "online",     # "online" = ArcGIS Online | "enterprise" = ArcGIS Enterprise
        "username": "",
        "password": "",
        "portal_url": "",           # leave empty to auto-derive from layer_type
        "poll_interval": 30,        # seconds between polls
        "page_size": 1000           # max records per REST request
    },
    "field_mapping": {
        "lat": "",              # field name for latitude;  empty = use geometry y
        "lon": "",              # field name for longitude; empty = use geometry x
        "uid_field": "OBJECTID",
        "uid_prefix": "EsriSync",
        "callsign_field": "",   # empty = falls back to uid value
        "cot_type": "a-f-G",    # fixed type OR "field:<fieldname>" to map from data
        "altitude_field": "",   # empty = 0
        "remarks_fields": []    # list of field names packed into <remarks>
    },
    "cot": {
        "stale_minutes": 5,
        "how": "m-g"
    },
    "delta": {
        "enabled": True,
        "track_field": "EditDate"   # set to "" to send all records every poll
    },
    "icon_mapping": {
        "enabled": False,
        # Column whose value selects the icon
        "column": "",
        # Full iconsetpath used when a value has no mapping entry
        # Format: "<uuid>/<group>/<filename.png>"
        "default_iconsetpath": "412c43f948b1664a3a0b513336b6c32382b13289a6ed2e91dd31e23d9d52a683/Incident Icons/Placeholder Other.png",
        # value → full iconsetpath  (supports mixing icons from different uploaded sets)
        # e.g. "Hazard, Fire": "412c43f9.../Incident Icons/Fire.png"
        #      "My Custom":    "other_uuid/MyGroup/custom.png"
        "map": {}
    }
}


def load_config() -> dict:
    path = Path(CONFIG_PATH)
    if not path.exists():
        logging.warning("Config not found at %s — using defaults", CONFIG_PATH)
        return DEFAULT_CONFIG
    with open(path) as f:
        cfg = json.load(f)
    # Deep-merge with defaults so missing keys never crash
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for section, values in cfg.items():
        if section in merged and isinstance(values, dict):
            merged[section].update(values)
        else:
            merged[section] = values
    return merged


# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ"
)
log = logging.getLogger("feature-layer-to-cot")


# ── ArcGIS Feature Layer ──────────────────────────────────────────────────────

class FeatureLayerClient:
    """Fetches records from an Esri Feature Layer REST endpoint."""

    # Token endpoint paths differ between Online and Enterprise
    _TOKEN_PATHS = {
        "online":     "https://www.arcgis.com/sharing/rest/generateToken",
        "enterprise": "{portal_url}/sharing/rest/generateToken",
    }

    def __init__(self, cfg: dict):
        fl = cfg["feature_layer"]
        self.url        = fl["url"].rstrip("/")
        self.public     = fl["public"]
        self.layer_type = fl.get("layer_type", "online").lower()
        self.page_size  = int(fl.get("page_size", 1000))
        self.session    = requests.Session()
        self._token     = None

        if not self.public:
            portal_url = fl.get("portal_url") or self._derive_portal_url(fl)
            self._token = self._get_token(
                portal_url, fl["username"], fl["password"]
            )

    def _derive_portal_url(self, fl: dict) -> str:
        """
        Auto-derive the portal URL when none is provided.
        - online:     always https://www.arcgis.com
        - enterprise: extract root from the feature layer URL
                      e.g. https://gis.myorg.com/server/... → https://gis.myorg.com/portal
        """
        if self.layer_type == "online":
            return "https://www.arcgis.com"

        # Enterprise: root is everything before /rest/services/...
        from urllib.parse import urlparse
        parsed = urlparse(fl["url"])
        # Strip /server or /arcgis path segments and append /portal
        parts = parsed.path.split("/")
        root_parts = [p for p in parts if p.lower() not in ("server", "arcgis", "rest", "services")]
        root_path = "/".join(root_parts).rstrip("/")
        derived = f"{parsed.scheme}://{parsed.netloc}{root_path}/portal"
        log.info("Enterprise portal URL auto-derived as: %s", derived)
        return derived

    def _get_token(self, portal_url: str, username: str, password: str) -> str:
        """
        Obtain a short-lived ArcGIS token.
        - ArcGIS Online:     POST to https://www.arcgis.com/sharing/rest/generateToken
        - ArcGIS Enterprise: POST to https://<host>/portal/sharing/rest/generateToken
        Raises RuntimeError on 2FA, bad credentials, or unexpected response.
        """
        if self.layer_type == "online":
            token_url = self._TOKEN_PATHS["online"]
        else:
            token_url = self._TOKEN_PATHS["enterprise"].format(portal_url=portal_url.rstrip("/"))

        log.info("Requesting ArcGIS token (%s) from %s", self.layer_type, token_url)
        resp = self.session.post(token_url, data={
            "username": username,
            "password": password,
            "referer": "http://localhost",
            "expiration": 60,
            "f": "json"
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            code = data["error"].get("code", "")
            msg  = data["error"].get("message", "")
            if "multifactor" in msg.lower() or "2fa" in msg.lower() or code in (498, 400):
                raise RuntimeError(
                    "ArcGIS 2FA appears to be enabled on this account. "
                    "Disable 2FA for this user, or switch to a public layer."
                )
            raise RuntimeError(f"ArcGIS token error {code}: {msg}")

        if "token" not in data:
            raise RuntimeError("ArcGIS token response missing 'token' field")

        log.info("ArcGIS token obtained (expires in ~%s min)", data.get("expires", "?"))
        return data["token"]

    def fetch_all(self, where: str = "1=1") -> list:
        """
        Fetch every feature with automatic pagination.
        Handles layers with >1000 records transparently.
        Always requests WGS84 (outSR=4326).
        """
        features = []
        offset = 0

        while True:
            params = {
                "where": where,
                "outFields": "*",
                "resultOffset": offset,
                "resultRecordCount": self.page_size,
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "json"
            }
            if self._token:
                params["token"] = self._token

            resp = self.session.get(
                f"{self.url}/query",
                params=params,
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json()

            if "error" in data:
                raise RuntimeError(f"Feature Layer query error: {data['error']}")

            batch = data.get("features", [])
            features.extend(batch)
            log.debug("Fetched %d records (offset=%d)", len(batch), offset)

            if len(batch) < self.page_size:
                break               # last page — we're done
            offset += len(batch)

        log.info("Total records fetched: %d", len(features))
        return features


# ── CoT Construction ──────────────────────────────────────────────────────────

def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"




def build_cot(feature: dict, fm: dict, cot_cfg: dict, icon_cfg: dict | None = None) -> str:
    """
    Build a CoT XML string from a single Feature Layer record.

    fm       = cfg["field_mapping"]
    cot_cfg  = cfg["cot"]
    icon_cfg = cfg["icon_mapping"]  (optional)
    """
    attrs = feature.get("attributes", {})
    geom  = feature.get("geometry", {})

    # ── Coordinates ───────────────────────────────────────────────────────────
    if fm.get("lat") and fm.get("lon"):
        lat = float(attrs.get(fm["lat"], 0) or 0)
        lon = float(attrs.get(fm["lon"], 0) or 0)
    else:
        # Point geometry returned as {x, y} in WGS84 when outSR=4326
        lat = float(geom.get("y", geom.get("latitude", 0)) or 0)
        lon = float(geom.get("x", geom.get("longitude", 0)) or 0)

    # ── Altitude ──────────────────────────────────────────────────────────────
    hae = 0.0
    if fm.get("altitude_field"):
        hae = float(attrs.get(fm["altitude_field"], 0) or 0)

    # ── UID ───────────────────────────────────────────────────────────────────
    _uid_field = fm.get("uid_field", "OBJECTID") or "OBJECTID"
    uid_val    = attrs.get(_uid_field)
    # Step 1: case-insensitive match if exact fails
    if uid_val is None:
        _lower = _uid_field.lower()
        for _k, _v in attrs.items():
            if _k.lower() == _lower:
                uid_val = _v
                break
    # Step 2: try common Esri OID aliases
    if uid_val is None:
        for _alias in ("OBJECTID", "FID", "OID", "objectid", "fid", "oid", "GlobalID", "GlobalId"):
            if _alias in attrs:
                uid_val = attrs[_alias]
                break
    # Step 3: hash attributes + geometry → guaranteed unique, stable UID
    if uid_val in (None, ""):
        _hash_src = json.dumps(attrs, sort_keys=True, default=str)
        if geom:
            _hash_src += json.dumps(geom, sort_keys=True, default=str)
        uid_val = "h" + hashlib.sha1(_hash_src.encode()).hexdigest()[:10]
        logging.warning(
            "UID field %r not found in attributes — using content hash %r. "
            "Set uid_field in config. Available attribute fields: %s",
            _uid_field, uid_val, list(attrs.keys())
        )
    uid = f"{fm.get('uid_prefix', 'EsriSync')}_{uid_val}"

    # ── Callsign ──────────────────────────────────────────────────────────────
    cs_field = fm.get("callsign_field", "")
    if cs_field:
        raw_cs = attrs.get(cs_field)
        callsign = str(raw_cs) if raw_cs not in (None, "") else str(uid_val)
    else:
        callsign = str(uid_val)

    # ── CoT type ──────────────────────────────────────────────────────────────
    cot_type_cfg = fm.get("cot_type", "a-f-G")
    if cot_type_cfg.startswith("field:"):
        cot_type = str(attrs.get(cot_type_cfg[6:], "a-f-G"))
    else:
        cot_type = cot_type_cfg

    # ── Timestamps ────────────────────────────────────────────────────────────
    now   = datetime.now(timezone.utc)
    stale = now + timedelta(minutes=int(cot_cfg.get("stale_minutes", 5)))
    how   = cot_cfg.get("how", "m-g")

    # ── Remarks ───────────────────────────────────────────────────────────────
    remark_parts = []
    for field in fm.get("remarks_fields", []):
        val = attrs.get(field)
        if val not in (None, ""):
            remark_parts.append(f"{field}: {val}")
    remarks = ", ".join(remark_parts)

    # ── Icon ──────────────────────────────────────────────────────────────────
    usericon_xml = ""
    if icon_cfg and icon_cfg.get("enabled") and icon_cfg.get("column"):
        col_val     = str(attrs.get(icon_cfg["column"], "")).strip()
        # map values are full iconsetpaths — supports mixing different uploaded sets
        iconsetpath = (
            icon_cfg.get("map", {}).get(col_val)
            or icon_cfg.get("default_iconsetpath", "")
        )
        if iconsetpath:
            usericon_xml = f'<usericon iconsetpath={_xml_quoteattr(iconsetpath)} />'

    # No XML declaration — TAK Server's streaming TCP parser reads multiple
    # <event> elements per connection; a repeated <?xml?> mid-stream breaks it.
    return (
        f'<event version="2.0"'
        f' uid={_xml_quoteattr(uid)}'
        f' type={_xml_quoteattr(cot_type)}'
        f' time="{_fmt_time(now)}"'
        f' start="{_fmt_time(now)}"'
        f' stale="{_fmt_time(stale)}"'
        f' how={_xml_quoteattr(how)}>'
        f'<point lat="{lat}" lon="{lon}" hae="{hae}" ce="9999999.0" le="9999999.0" />'
        f'<detail>'
        f'<contact callsign={_xml_quoteattr(callsign)} uid={_xml_quoteattr(uid)} />'
        f'{usericon_xml}'
        f'<remarks>{_xml_escape(remarks)}</remarks>'
        f'<track speed="0.0" course="0.0" />'
        f'</detail>'
        f'</event>'
    )


# ── TAK Server TCP Client ─────────────────────────────────────────────────────

# Default ports per auth mode
_AUTH_MODE_DEFAULT_PORTS = {
    "cert":        8089,   # TLS with client certificate (mutual TLS)
    "tls_keypair": 8089,   # TLS with PEM cert+key, no server verification (Node-RED style)
    "plain":       8087,   # Plain TCP, no certificate
    "rest":        8443,   # HTTPS REST API with Basic Auth + client cert
    "authentik":   8443,   # HTTPS REST API with Basic Auth only (Authentik/LDAP user)
    "file":        0,      # Write CoT to a local text file, one message per line
}


class TAKClient:
    """
    TAK Server client.

    auth_mode = "cert"        → TLS with .p12 client certificate (port 8089)
    auth_mode = "tls_keypair" → TLS with PEM cert+key, no server cert verification (port 8089)
    auth_mode = "plain"       → Plain TCP, no certificate required (port 8087)
    auth_mode = "rest"        → HTTPS REST API POST /Marti/api/cot/xml, Basic Auth + client cert (port 8443)
    auth_mode = "authentik"   → HTTPS REST API POST /Marti/api/cot/xml, Basic Auth only (port 8443)
    """

    def __init__(self, cfg: dict):
        tak = cfg["tak_server"]
        self.host       = tak["host"]
        self.auth_mode  = tak.get("auth_mode", "cert").lower()

        default_port    = _AUTH_MODE_DEFAULT_PORTS.get(self.auth_mode, 8089)
        self.port       = int(tak.get("port") or default_port)

        self.username   = tak.get("username", "")
        self.password   = tak.get("password", "")
        self.cert_path  = tak.get("cert_path", "")
        self.cert_pass  = tak.get("cert_password", "")
        self.ca_cert    = tak.get("ca_cert", "")
        self.cert_file  = tak.get("cert_file", "")   # PEM cert path (tls_keypair mode)
        self.key_file   = tak.get("key_file", "")    # PEM key path  (tls_keypair mode)
        self.output_file = tak.get("output_file", "/opt/Esri-TAKServer-Sync/cot_output.txt")
        self._sock      = None
        self._session   = None
        self._file      = None

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self):
        if self.auth_mode == "file":
            os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
            self._file = open(self.output_file, "w", encoding="utf-8")
            log.info("File mode: writing CoT to %s", self.output_file)
            return

        if self.auth_mode == "authentik":
            # Authentik/LDAP: Basic Auth over HTTPS. TAK Server 8443 enforces
            # mutual TLS so a client cert is still required alongside credentials.
            self._session = requests.Session()
            self._session.auth = (self.username, self.password)
            self._session.verify = False
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            if self.cert_file and self.key_file and os.path.exists(self.cert_file) and os.path.exists(self.key_file):
                self._session.cert = (self.cert_file, self.key_file)
                log.info("Authentik/LDAP mode: using client cert %s", self.cert_file)
            elif os.path.exists(self.cert_path.replace(".p12", "-cert.pem")):
                pem_cert = self.cert_path.replace(".p12", "-cert.pem")
                pem_key  = self.cert_path.replace(".p12", "-key.pem")
                self._session.cert = (pem_cert, pem_key)
                log.info("Authentik/LDAP mode: using client cert %s", pem_cert)
            else:
                log.warning("Authentik/LDAP mode: no client cert found — TAK Server may reject the connection")
            log.info("Authentik/LDAP mode: will POST CoT to https://%s:%d/Marti/api/cot/xml (Basic Auth)",
                     self.host, self.port)
            return

        if self.auth_mode == "rest":
            # REST mode: Basic Auth + client cert (mutual TLS against 8443).
            self._session = requests.Session()
            self._session.auth = (self.username, self.password)

            pem_cert = self.cert_path.replace(".p12", "-cert.pem")
            pem_key  = self.cert_path.replace(".p12", "-key.pem")
            if os.path.exists(pem_cert) and os.path.exists(pem_key):
                self._session.cert = (pem_cert, pem_key)
            else:
                log.warning(
                    "REST mode: PEM sidecars not found (%s / %s). "
                    "TAK Server 8443 requires a client cert — set up the cert on the Config tab.",
                    pem_cert, pem_key
                )

            if not self.ca_cert:
                self._session.verify = False
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            else:
                self._session.verify = self.ca_cert

            log.info("REST mode: will POST CoT to https://%s:%d/Marti/api/cot/xml (Basic Auth + mTLS)",
                     self.host, self.port)
            return

        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.settimeout(10)
        raw.connect((self.host, self.port))

        if self.auth_mode == "cert":
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            if self.ca_cert:
                ctx.load_verify_locations(self.ca_cert)
                ctx.verify_mode    = ssl.CERT_REQUIRED
                ctx.check_hostname = True
            else:
                ctx.check_hostname = False
                ctx.verify_mode    = ssl.CERT_NONE

            pem_cert = self.cert_path.replace(".p12", "-cert.pem")
            pem_key  = self.cert_path.replace(".p12", "-key.pem")
            if os.path.exists(pem_cert) and os.path.exists(pem_key):
                ctx.load_cert_chain(pem_cert, pem_key)
            else:
                log.warning(
                    "PEM sidecars not found (%s / %s). "
                    "Run setup-cert.py or re-deploy to generate them.",
                    pem_cert, pem_key
                )
            self._sock = ctx.wrap_socket(raw, server_hostname=self.host)

        elif self.auth_mode == "tls_keypair":
            # TLS with direct PEM cert+key — no server cert verification (matches Node-RED flow).
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode    = ssl.CERT_NONE
            if self.cert_file and self.key_file:
                if os.path.exists(self.cert_file) and os.path.exists(self.key_file):
                    ctx.load_cert_chain(self.cert_file, self.key_file)
                else:
                    log.warning("tls_keypair: cert/key files not found (%s / %s)", self.cert_file, self.key_file)
            else:
                log.warning("tls_keypair: no cert_file/key_file configured — connecting without client cert")
            self._sock = ctx.wrap_socket(raw, server_hostname=self.host)

        else:
            # Plain TCP — no TLS, no cert
            self._sock = raw

        self._sock.settimeout(None)
        log.info("Connected to TAK Server %s:%d (auth_mode=%s)", self.host, self.port, self.auth_mode)

    # ── Health check ──────────────────────────────────────────────────────────

    def is_alive(self) -> bool:
        """
        Check if the connection is still open.
        Uses select() so it works on both plain and SSL sockets
        (SSL sockets don't support MSG_PEEK).
        """
        if not self._sock:
            return False
        try:
            import select as _select
            readable, _, _ = _select.select([self._sock], [], [], 0)
            if not readable:
                return True          # nothing waiting — socket is healthy
            # Data (or EOF) is pending — do a real recv to distinguish
            old_timeout = self._sock.gettimeout()
            self._sock.settimeout(0.1)
            try:
                data = self._sock.recv(1)
                return len(data) > 0  # 0 bytes == clean close by peer
            except (BlockingIOError, ssl.SSLWantReadError):
                return True           # would block — still open
            except (OSError, ssl.SSLError):
                return False
            finally:
                self._sock.settimeout(old_timeout)
        except (OSError, ssl.SSLError):
            return False

    # ── Send ──────────────────────────────────────────────────────────────────

    def send(self, cot_xml: str):
        """Send one CoT event."""
        if self.auth_mode == "file":
            self._file.write(cot_xml + "\n")
            self._file.flush()
            return

        if self.auth_mode in ("rest", "authentik"):
            url = f"https://{self.host}:{self.port}/Marti/api/cot/xml"
            resp = self._session.post(
                url, data=cot_xml.encode("utf-8"),
                headers={"Content-Type": "application/xml"},
                timeout=10
            )
            if resp.status_code not in (200, 201, 204):
                raise RuntimeError(f"REST CoT POST returned HTTP {resp.status_code}: {resp.text[:200]}")
            return

        # TCP / TLS path
        data = (cot_xml + "\n").encode("utf-8")
        try:
            if not self._sock:
                self.connect()
            self._sock.sendall(data)
        except (OSError, ssl.SSLError) as exc:
            log.warning("TAK send failed (%s) — reconnecting", exc)
            self.close()
            self.connect()
            self._sock.sendall(data)


    # ── Close ─────────────────────────────────────────────────────────────────

    def close(self):
        if self._file:
            try:
                self._file.close()
            except Exception:
                pass
        self._file = None
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
        self._session = None


# ── Delta Tracker ─────────────────────────────────────────────────────────────

class DeltaTracker:
    """
    Tracks the last-seen value of a change-detection field (e.g. EditDate)
    per UID so only new or updated records are forwarded to TAK Server.
    State is persisted to disk so restarts don't re-flood the server.
    """

    STATE_PATH = "/opt/Esri-TAKServer-Sync/delta-state.json"

    def __init__(self, enabled: bool, track_field: str):
        self.enabled     = enabled
        self.track_field = track_field
        self._seen: dict = {}
        if enabled:
            self._load()

    def _load(self):
        try:
            with open(self.STATE_PATH) as f:
                self._seen = json.load(f)
            log.debug("Delta state loaded (%d tracked UIDs)", len(self._seen))
        except FileNotFoundError:
            self._seen = {}

    def _save(self):
        Path(self.STATE_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(self.STATE_PATH, "w") as f:
            json.dump(self._seen, f)

    def is_new_or_changed(self, uid: str, attrs: dict) -> bool:
        if not self.enabled:
            return True
        val = attrs.get(self.track_field)
        if val is None:
            return True                     # no tracking field → always send
        changed = self._seen.get(uid) != val
        if changed:
            self._seen[uid] = val
        return changed

    def commit(self):
        if self.enabled:
            self._save()


# ── Main Loop ─────────────────────────────────────────────────────────────────

_running = True


def _shutdown(sig, frame):
    global _running
    log.info("Received signal %s — shutting down…", sig)
    _running = False


signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)


def main():
    cfg    = load_config()
    fl_cfg = cfg["feature_layer"]

    if not fl_cfg.get("url"):
        log.error("feature_layer.url is not configured. Run setup or edit %s", CONFIG_PATH)
        sys.exit(1)

    poll_interval = int(fl_cfg.get("poll_interval", 30))
    fm            = cfg["field_mapping"]
    cot_cfg       = cfg["cot"]
    icon_cfg      = cfg.get("icon_mapping", {})
    delta         = DeltaTracker(
        cfg["delta"].get("enabled", False),
        cfg["delta"].get("track_field", "EditDate")
    )

    layer = FeatureLayerClient(cfg)
    tak   = TAKClient(cfg)

    log.info(
        "Poll loop started (interval=%ds, auth_mode=%s, delta=%s)",
        poll_interval, tak.auth_mode, delta.enabled
    )

    while _running:
        try:
            features = layer.fetch_all()
            sent = 0
            sent_cots = []   # list of (index, cot_str) for post-poll logging
            tak.connect()
            try:
                for feat in features:
                    attrs    = feat.get("attributes", {})
                    geom_d   = feat.get("geometry", {})
                    _uf      = fm.get("uid_field", "OBJECTID") or "OBJECTID"
                    _uid_raw = attrs.get(_uf)
                    if _uid_raw is None:
                        _lf = _uf.lower()
                        for _k, _v in attrs.items():
                            if _k.lower() == _lf:
                                _uid_raw = _v
                                break
                    if _uid_raw is None:
                        for _al in ("OBJECTID", "FID", "OID", "objectid", "fid", "oid", "GlobalID"):
                            if _al in attrs:
                                _uid_raw = attrs[_al]
                                break
                    if _uid_raw in (None, ""):
                        _hs = json.dumps(attrs, sort_keys=True, default=str)
                        if geom_d:
                            _hs += json.dumps(geom_d, sort_keys=True, default=str)
                        _uid_raw = "h" + hashlib.sha1(_hs.encode()).hexdigest()[:10]
                    uid_val = _uid_raw
                    uid     = f"{fm.get('uid_prefix', 'EsriSync')}_{uid_val}"
                    if delta.is_new_or_changed(uid, attrs):
                        cot = build_cot(feat, fm, cot_cfg, icon_cfg)
                        tak.send(cot)
                        sent += 1
                        sent_cots.append(cot)
            finally:
                tak.close()
            delta.commit()
            log.info("Poll complete — sent %d / %d records", sent, len(features))

            if sent_cots:
                for i, cot in enumerate(sent_cots, 1):
                    log.info("CoT [%d/%d]: %s", i, len(sent_cots), cot)

        except RuntimeError as exc:
            log.error("%s", exc)
        except Exception as exc:
            log.exception("Unexpected error: %s", exc)

        # Interruptible sleep
        elapsed = 0
        while elapsed < poll_interval and _running:
            time.sleep(1)
            elapsed += 1

    log.info("Stopped.")


if __name__ == "__main__":
    main()
