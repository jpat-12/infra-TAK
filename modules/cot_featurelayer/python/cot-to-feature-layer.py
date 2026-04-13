#!/usr/bin/env python3
"""
CoT-FeatureLayer — TAK Server CoT → Esri Feature Layer
Connects to TAK Server as a TCP client, listens for incoming CoT events,
and upserts each position report into an Esri Feature Layer keyed by UID.

Requires the arcgis Python package (install via the infra-TAK console Conda step).
Run with: /root/miniconda/envs/arcgis_env/bin/python cot-to-feature-layer.py
"""

import json
import logging
import os
import signal
import socket
import ssl
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# ── ArcGIS SDK ────────────────────────────────────────────────────────────────
try:
    from arcgis.gis import GIS
    from arcgis.features import FeatureLayer, Feature
except ImportError:
    print(
        "ERROR: arcgis package not found.\n"
        "Run the Conda setup in the infra-TAK console (CoT-FeatureLayer → Deploy → Install Conda).",
        file=sys.stderr,
    )
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_PATH = os.environ.get("COT_FL_CONFIG", "/opt/CoT-FeatureLayer/config.json")

DEFAULT_CONFIG = {
    "tak_server": {
        "host": "localhost",
        "port": 8089,
        "tls": True,
        "cert_path": "/opt/CoT-FeatureLayer/certs/cot-fl.p12",
        "cert_password": "",
        "ca_cert": "",          # path to TAK Server CA .pem; empty = no verify
    },
    "feature_layer": {
        "url": "",
        "layer_type": "online",     # "online" | "enterprise"
        "username": "",
        "password": "",
        "portal_url": "",           # auto-derived for enterprise when blank
    },
    "field_mapping": {
        "uid_field":      "tak_uid",
        "callsign_field": "callsign",
        "type_field":     "cot_type",
        "lat_field":      "latitude",
        "lon_field":      "longitude",
        "altitude_field": "altitude",
        "time_field":     "last_seen",
        "remarks_field":  "remarks",
    },
    "filter": {
        "cot_types":  [],   # empty list = accept all CoT types
        "uid_prefix": "",   # empty = accept all UIDs
    },
}


def load_config() -> dict:
    path = Path(CONFIG_PATH)
    if not path.exists():
        logging.warning("Config not found at %s — using defaults", CONFIG_PATH)
        return DEFAULT_CONFIG
    with open(path) as f:
        cfg = json.load(f)
    # Deep-merge so missing keys fall back to defaults
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
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("cot-to-feature-layer")


# ── CoT Parser ────────────────────────────────────────────────────────────────

def parse_cot(xml_str: str) -> dict:
    """
    Parse a single CoT XML event string.
    Returns a dict with position/metadata, or None if the event has no point.
    """
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as exc:
        log.debug("XML parse error: %s", exc)
        return None

    if root.tag != "event":
        return None

    uid      = root.get("uid", "")
    cot_type = root.get("type", "")
    time_str = root.get("time", "")

    point = root.find("point")
    if point is None:
        return None     # no position — skip (e.g. chat, GeoChat, ping)

    lat = float(point.get("lat", 0) or 0)
    lon = float(point.get("lon", 0) or 0)
    hae = float(point.get("hae", 0) or 0)

    detail   = root.find("detail") or ET.Element("detail")
    contact  = detail.find("contact")
    callsign = contact.get("callsign", uid) if contact is not None else uid

    remarks_el = detail.find("remarks")
    remarks    = (remarks_el.text or "").strip() if remarks_el is not None else ""

    return {
        "uid":      uid,
        "cot_type": cot_type,
        "lat":      lat,
        "lon":      lon,
        "hae":      hae,
        "callsign": callsign,
        "remarks":  remarks,
        "time":     time_str,
    }


# ── CoT TCP Receiver ──────────────────────────────────────────────────────────

class CotReceiver:
    """
    TCP (optionally TLS) client that connects to TAK Server and streams CoT events.
    TAK Server streams raw XML with no envelope, so we buffer and split on </event>.
    """

    def __init__(self, cfg: dict):
        tak = cfg["tak_server"]
        self.host          = tak["host"]
        self.port          = int(tak.get("port", 8089))
        self.use_tls       = tak.get("tls", True)
        self.cert_path     = tak.get("cert_path", "")
        self.cert_password = tak.get("cert_password", "")
        self.ca_cert       = tak.get("ca_cert", "")
        self._sock         = None

    def connect(self):
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.settimeout(10)
        raw.connect((self.host, self.port))

        if self.use_tls:
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

            self._sock = ctx.wrap_socket(raw, server_hostname=self.host)
        else:
            self._sock = raw

        self._sock.settimeout(5)    # short timeout so SIGTERM is handled promptly
        log.info("Connected to TAK Server %s:%d (TLS=%s)", self.host, self.port, self.use_tls)

    def stream_events(self):
        """
        Generator: yields complete CoT XML strings as they arrive.
        Yields None on read timeout (heartbeat tick for checking _running).
        """
        buf = ""
        while True:
            try:
                chunk = self._sock.recv(8192).decode("utf-8", errors="replace")
                if not chunk:
                    log.warning("TAK Server closed the connection")
                    return
                buf += chunk
                # Extract every complete <event>…</event> block in the buffer
                while True:
                    end = buf.find("</event>")
                    if end == -1:
                        break
                    start = buf.rfind("<event", 0, end)
                    if start == -1:
                        buf = buf[end + 8:]
                        continue
                    yield buf[start : end + 8]
                    buf = buf[end + 8:]
            except socket.timeout:
                yield None          # tick — caller checks _running
            except (OSError, ssl.SSLError) as exc:
                log.warning("Receive error: %s", exc)
                return

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None


# ── ArcGIS Feature Layer Writer ───────────────────────────────────────────────

class FeatureLayerWriter:
    """
    Upserts CoT position reports into an Esri Feature Layer.
    Uses UID field as the primary key:
      - existing feature → update geometry + attributes
      - new UID          → insert new feature
    """

    def __init__(self, cfg: dict):
        fl_cfg = cfg["feature_layer"]
        self.url        = fl_cfg["url"].rstrip("/")
        self.layer_type = fl_cfg.get("layer_type", "online").lower()
        self.username   = fl_cfg.get("username", "")
        self.password   = fl_cfg.get("password", "")
        self.portal_url = (fl_cfg.get("portal_url") or "").strip() or self._derive_portal(fl_cfg)
        self.fm         = cfg["field_mapping"]
        self._gis       = None
        self._layer     = None

    def _derive_portal(self, fl_cfg: dict) -> str:
        if self.layer_type == "online":
            return "https://www.arcgis.com"
        from urllib.parse import urlparse
        parsed     = urlparse(fl_cfg["url"])
        parts      = parsed.path.split("/")
        root_parts = [p for p in parts if p.lower() not in ("server", "arcgis", "rest", "services")]
        root_path  = "/".join(root_parts).rstrip("/")
        derived    = f"{parsed.scheme}://{parsed.netloc}{root_path}/portal"
        log.info("Enterprise portal auto-derived as: %s", derived)
        return derived

    def connect(self):
        log.info("Signing in to ArcGIS (%s) at %s", self.layer_type, self.portal_url)
        self._gis   = GIS(self.portal_url, self.username, self.password)
        self._layer = FeatureLayer(self.url, self._gis)
        log.info("Feature Layer ready: %s", self.url)

    def upsert(self, cot: dict):
        """Insert or update a single CoT event."""
        fm  = self.fm
        uid = cot["uid"]

        attrs = {
            fm["uid_field"]:      uid,
            fm["callsign_field"]: cot["callsign"],
            fm["type_field"]:     cot["cot_type"],
            fm["lat_field"]:      cot["lat"],
            fm["lon_field"]:      cot["lon"],
            fm["altitude_field"]: cot["hae"],
            fm["remarks_field"]:  cot["remarks"],
            fm["time_field"]:     cot["time"],
        }

        geom = {
            "x": cot["lon"],
            "y": cot["lat"],
            "spatialReference": {"wkid": 4326},
        }

        # Query for an existing record with this UID
        uid_safe = uid.replace("'", "''")
        result   = self._layer.query(
            where=f"{fm['uid_field']} = '{uid_safe}'",
            out_fields=fm["uid_field"],
            return_geometry=False,
            result_record_count=1,
        )

        if result.features:
            feat = result.features[0]
            feat.attributes.update(attrs)
            feat.geometry = geom
            self._layer.edit_features(updates=[feat])
            log.debug("Updated UID=%s", uid)
        else:
            feat = Feature(geometry=geom, attributes=attrs)
            self._layer.edit_features(adds=[feat])
            log.debug("Inserted UID=%s", uid)


# ── Main Loop ─────────────────────────────────────────────────────────────────

_running = True


def _shutdown(sig, frame):
    global _running
    log.info("Signal %s — shutting down cleanly…", sig)
    _running = False


signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)


def main():
    cfg    = load_config()
    fl_cfg = cfg["feature_layer"]
    filt   = cfg.get("filter", {})

    if not fl_cfg.get("url"):
        log.error("feature_layer.url is not set. Edit %s", CONFIG_PATH)
        sys.exit(1)

    allowed_types = set(filt.get("cot_types", []))
    uid_prefix    = filt.get("uid_prefix", "")

    writer = FeatureLayerWriter(cfg)
    writer.connect()

    log.info(
        "Listener started — TAK=%s:%d  filter_types=%s  uid_prefix=%r",
        cfg["tak_server"]["host"], cfg["tak_server"]["port"],
        list(allowed_types) or "ALL", uid_prefix or "ALL",
    )

    while _running:
        receiver = CotReceiver(cfg)
        try:
            receiver.connect()
            for xml_str in receiver.stream_events():
                if not _running:
                    break
                if xml_str is None:
                    continue    # timeout tick

                cot = parse_cot(xml_str)
                if cot is None:
                    continue

                # Apply filters
                if allowed_types and cot["cot_type"] not in allowed_types:
                    log.debug("Filtered (type): %s", cot["cot_type"])
                    continue
                if uid_prefix and not cot["uid"].startswith(uid_prefix):
                    log.debug("Filtered (uid): %s", cot["uid"])
                    continue

                try:
                    writer.upsert(cot)
                    log.info("Upserted  uid=%-40s  callsign=%s", cot["uid"], cot["callsign"])
                except Exception as exc:
                    log.error("Upsert failed for uid=%s: %s", cot["uid"], exc)

        except Exception as exc:
            log.error("Connection error: %s — reconnecting in 10 s", exc)
        finally:
            receiver.close()

        # Interruptible sleep before reconnect
        if _running:
            for _ in range(10):
                if not _running:
                    break
                time.sleep(1)

    log.info("Stopped.")


if __name__ == "__main__":
    main()
