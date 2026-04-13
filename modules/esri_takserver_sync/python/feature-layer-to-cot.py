#!/usr/bin/env python3
"""
Esri-TAKServer-Sync — Feature Layer to CoT
Polls an Esri Feature Layer and broadcasts records as CoT events to TAK Server.
"""

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
        "auth_mode": "cert",
        "port": 8089,
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


def build_cot(feature: dict, fm: dict, cot_cfg: dict) -> str:
    """
    Build a CoT XML string from a single Feature Layer record.

    fm      = cfg["field_mapping"]
    cot_cfg = cfg["cot"]
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
    uid_val  = attrs.get(fm.get("uid_field", "OBJECTID"), "unknown")
    uid      = f"{fm.get('uid_prefix', 'EsriSync')}_{uid_val}"

    # ── Callsign ──────────────────────────────────────────────────────────────
    cs_field = fm.get("callsign_field", "")
    callsign = str(attrs.get(cs_field, uid_val)) if cs_field else str(uid_val)

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

    return (
        f'<event version="2.0" uid="{uid}" type="{cot_type}" '
        f'time="{_fmt_time(now)}" start="{_fmt_time(now)}" stale="{_fmt_time(stale)}" '
        f'how="{how}">'
        f'<point lat="{lat}" lon="{lon}" hae="{hae}" ce="10.0" le="2.0" />'
        f'<detail>'
        f'<contact callsign="{callsign}" />'
        f'<remarks>{remarks}</remarks>'
        f'<track speed="0" course="0" />'
        f'</detail>'
        f'</event>'
    )


# ── TAK Server TCP Client ─────────────────────────────────────────────────────

# Default ports per auth mode
_AUTH_MODE_DEFAULT_PORTS = {
    "cert":  8089,   # TLS with client certificate
    "plain": 8087,   # Plain TCP, no certificate
}


class TAKClient:
    """
    Persistent TCP connection to TAK Server.

    auth_mode = "cert"  → TLS with .p12 client certificate (port 8089)
    auth_mode = "plain" → Plain TCP, no certificate required (port 8087)
    """

    def __init__(self, cfg: dict):
        tak = cfg["tak_server"]
        self.host       = tak["host"]
        self.auth_mode  = tak.get("auth_mode", "cert").lower()

        # Honour explicit port; fall back to mode default
        default_port    = _AUTH_MODE_DEFAULT_PORTS.get(self.auth_mode, 8089)
        self.port       = int(tak.get("port") or default_port)

        self.cert_path  = tak.get("cert_path", "")
        self.cert_pass  = tak.get("cert_password", "")
        self.ca_cert    = tak.get("ca_cert", "")
        self._sock      = None

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self):
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

            # .p12 must have PEM sidecars extracted by setup-cert.py
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
        else:
            # Plain TCP — no TLS, no cert
            self._sock = raw

        # Switch to blocking after connect (sendall needs it)
        self._sock.settimeout(None)
        log.info(
            "Connected to TAK Server %s:%d (auth_mode=%s)",
            self.host, self.port, self.auth_mode
        )

    # ── Health check ──────────────────────────────────────────────────────────

    def is_alive(self) -> bool:
        """Non-destructive check: returns False if the server has closed the socket."""
        if not self._sock:
            return False
        try:
            self._sock.setblocking(False)
            data = self._sock.recv(1, socket.MSG_PEEK)
            self._sock.setblocking(True)
            # recv returned 0 bytes → clean close by peer
            return len(data) > 0
        except BlockingIOError:
            # No data waiting, but socket is still open — healthy
            self._sock.setblocking(True)
            return True
        except (OSError, ssl.SSLError):
            self._sock.setblocking(True)
            return False

    # ── Send ──────────────────────────────────────────────────────────────────

    def send(self, cot_xml: str):
        """Send one CoT event. Reconnects once on failure."""
        if not self.is_alive():
            log.debug("Socket not alive — reconnecting before send")
            self.close()
            self.connect()
        data = (cot_xml + "\n").encode("utf-8")
        try:
            self._sock.sendall(data)
        except (OSError, ssl.SSLError) as exc:
            log.warning("TAK send failed (%s) — reconnecting", exc)
            self.close()
            self.connect()
            self._sock.sendall(data)

    def send_keepalive(self):
        """
        Send a minimal CoT SA ping to keep the connection alive between polls.
        TAK Server drops idle connections; this prevents that.
        """
        now   = datetime.now(timezone.utc)
        stale = now + timedelta(minutes=1)
        ping  = (
            f'<event version="2.0" uid="EsriSync-keepalive" type="t-x-c-t" '
            f'time="{_fmt_time(now)}" start="{_fmt_time(now)}" stale="{_fmt_time(stale)}" '
            f'how="m-g">'
            f'<point lat="0" lon="0" hae="0" ce="9999999.0" le="9999999.0"/>'
            f'<detail/>'
            f'</event>'
        )
        try:
            self.send(ping)
            log.debug("Keepalive sent")
        except Exception as exc:
            log.debug("Keepalive failed: %s", exc)

    # ── Close ─────────────────────────────────────────────────────────────────

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None


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
    delta         = DeltaTracker(
        cfg["delta"].get("enabled", True),
        cfg["delta"].get("track_field", "EditDate")
    )

    layer = FeatureLayerClient(cfg)
    tak   = TAKClient(cfg)
    tak.connect()

    log.info(
        "Poll loop started (interval=%ds, auth_mode=%s, delta=%s)",
        poll_interval, tak.auth_mode, delta.enabled
    )

    # Send a keepalive every 15 s during idle to prevent TAK Server
    # from dropping the connection between polls.
    KEEPALIVE_INTERVAL = 15

    while _running:
        try:
            features = layer.fetch_all()
            sent = 0
            for feat in features:
                attrs   = feat.get("attributes", {})
                uid_val = attrs.get(fm.get("uid_field", "OBJECTID"), "unknown")
                uid     = f"{fm.get('uid_prefix', 'EsriSync')}_{uid_val}"
                if delta.is_new_or_changed(uid, attrs):
                    cot = build_cot(feat, fm, cot_cfg)
                    tak.send(cot)
                    sent += 1
            delta.commit()
            log.info("Poll complete — sent %d / %d records", sent, len(features))

        except RuntimeError as exc:
            log.error("%s", exc)
        except Exception as exc:
            log.exception("Unexpected error: %s", exc)

        # Interruptible sleep with periodic keepalives
        elapsed = 0
        while elapsed < poll_interval and _running:
            time.sleep(1)
            elapsed += 1
            if elapsed % KEEPALIVE_INTERVAL == 0 and _running:
                tak.send_keepalive()

    tak.close()
    log.info("Stopped.")


if __name__ == "__main__":
    main()
