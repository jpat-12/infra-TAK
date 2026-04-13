#!/usr/bin/env bash
# Esri-TAKServer-Sync — standalone installer
# Usage:  sudo bash install.sh [--tak-host <host>] [--tak-port <port>] [--no-tls]
#
# Installs the feature-layer-to-cot broadcaster on a fresh Ubuntu/Debian server
# without the infra-TAK console.  Configure /opt/Esri-TAKServer-Sync/config.json
# after running this script, then start the service.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
TAK_HOST="localhost"
TAK_PORT=8089
USE_TLS=true
INSTALL_DIR="/opt/Esri-TAKServer-Sync"
SERVICE_NAME="feature-layer-to-cot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tak-host) TAK_HOST="$2"; shift 2;;
    --tak-port) TAK_PORT="$2"; shift 2;;
    --no-tls)   USE_TLS=false; shift;;
    --help|-h)
      echo "Usage: sudo bash install.sh [--tak-host HOST] [--tak-port PORT] [--no-tls]"
      exit 0;;
    *) echo "Unknown option: $1"; exit 1;;
  esac
done

# ── Root check ────────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: Run as root — sudo bash install.sh"
  exit 1
fi

echo ""
echo "━━━ Esri-TAKServer-Sync Installer ━━━"
echo "  Install dir : $INSTALL_DIR"
echo "  TAK Server  : $TAK_HOST:$TAK_PORT  TLS=$USE_TLS"
echo ""

# ── Step 1: Python dependency ─────────────────────────────────────────────────
echo "[1/5] Installing Python dependency (requests)…"
if ! command -v pip3 &>/dev/null; then
  echo "  pip3 not found — installing python3-pip via apt…"
  apt-get install -y -qq python3-pip
fi
pip3 install --quiet requests
echo "  ✓ requests"

# ── Step 2: Create install directory and copy scripts ─────────────────────────
echo ""
echo "[2/5] Copying scripts to $INSTALL_DIR…"
mkdir -p "$INSTALL_DIR"
cp "$SCRIPT_DIR/python/feature-layer-to-cot.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/python/setup-cert.py"           "$INSTALL_DIR/"
echo "  ✓ feature-layer-to-cot.py"
echo "  ✓ setup-cert.py"

# ── Step 3: Write default config.json ────────────────────────────────────────
echo ""
echo "[3/5] Writing default config.json…"
CONFIG_PATH="$INSTALL_DIR/config.json"

if [[ -f "$CONFIG_PATH" ]]; then
  echo "  ⚠ config.json already exists — skipping (edit manually to update)"
else
  TLS_STR="true"
  if [[ "$USE_TLS" == "false" ]]; then TLS_STR="false"; fi

  cat > "$CONFIG_PATH" <<JSON
{
  "tak_server": {
    "host": "$TAK_HOST",
    "port": $TAK_PORT,
    "tls": $TLS_STR,
    "cert_path": "$INSTALL_DIR/certs/esri-push.p12",
    "cert_password": "",
    "ca_cert": ""
  },
  "feature_layer": {
    "url": "",
    "public": true,
    "layer_type": "online",
    "username": "",
    "password": "",
    "portal_url": "",
    "poll_interval": 30,
    "page_size": 1000
  },
  "field_mapping": {
    "lat": "",
    "lon": "",
    "uid_field": "OBJECTID",
    "uid_prefix": "EsriSync",
    "callsign_field": "",
    "cot_type": "a-f-G",
    "altitude_field": "",
    "remarks_fields": []
  },
  "cot": {
    "stale_minutes": 5,
    "how": "m-g"
  },
  "delta": {
    "enabled": true,
    "track_field": "EditDate"
  }
}
JSON
  echo "  ✓ config.json written"
fi

# ── Step 4: Generate self-signed client cert ──────────────────────────────────
echo ""
echo "[4/5] Certificate…"
CERT_DIR="$INSTALL_DIR/certs"
P12="$CERT_DIR/esri-push.p12"
KEY_PEM="$CERT_DIR/esri-push-key.pem"
CERT_PEM="$CERT_DIR/esri-push-cert.pem"

if [[ -f "$P12" ]]; then
  echo "  ✓ Existing cert found at $P12 — skipping generation"
else
  mkdir -p "$CERT_DIR"
  echo "  Generating RSA-4096 self-signed cert (this may take a few seconds)…"
  openssl req -x509 -newkey rsa:4096 \
    -keyout "$KEY_PEM" -out "$CERT_PEM" \
    -days 365 -nodes \
    -subj "/CN=esri-push/O=EsriTAKSync" 2>/dev/null
  openssl pkcs12 -export \
    -out "$P12" -inkey "$KEY_PEM" -in "$CERT_PEM" \
    -name "esri-push" -passout "pass:" 2>/dev/null
  chmod 600 "$KEY_PEM" "$P12"
  echo "  ✓ Cert generated:"
  echo "    PEM (add to TAK Server): $CERT_PEM"
  echo "    P12 (used by service)  : $P12"
fi

# ── Step 5: Install and register systemd service ──────────────────────────────
echo ""
echo "[5/5] Installing systemd service…"
cp "$SCRIPT_DIR/service-files/feature-layer-to-cot.service" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME" 2>/dev/null || true
echo "  ✓ $SERVICE_NAME.service installed and enabled"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "━━━ Install complete ━━━"
echo ""
echo "  Next steps:"
echo "  1. Add $CERT_PEM to TAK Server's trusted clients"
echo "     (TAK Server Admin → Certificate Enrollment or Manage Users)"
echo ""
echo "  2. Edit $CONFIG_PATH and set feature_layer.url"
echo "     e.g.  \"url\": \"https://services.arcgis.com/.../FeatureServer/0\""
echo ""
echo "  3. Start the service (it was not auto-started to allow cert setup first):"
echo "     systemctl start $SERVICE_NAME"
echo ""
echo "  4. Watch the log:"
echo "     journalctl -fu $SERVICE_NAME"
echo "     # or:"
echo "     tail -f /var/log/esri-takserver-sync-feature-layer-to-cot.log"
echo ""
