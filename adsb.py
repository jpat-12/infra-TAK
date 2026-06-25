"""
adsb.py — ADS-B CoT Bridge module for infra-TAK

Registers /adsb and /api/adsb/* routes directly on the Flask app.
Call register_routes(app, login_required, load_settings, save_settings) from app.py.

What it does:
  - Manages a Docker container running adsbcot (https://github.com/snstac/adsbcot)
  - Pulls live ADS-B data from the Airplanes.live API (free, no key required)
  - Converts aircraft to CoT XML with 2525c air-track icons via pytak
  - Sends CoT to TAKServer over TCP or TLS (cert upload supported)
  - Generates ~/adsbcot/docker-compose.yml and controls the container lifecycle
"""

import json
import os
import subprocess
import shlex
import time
import threading

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

ADSB_KEY = 'adsb_cot_bridge'
ADSB_CONTAINER  = 'adsbcot'
ADSB_DIR        = os.path.expanduser('~/adsbcot')
ADSB_COMPOSE    = os.path.join(ADSB_DIR, 'docker-compose.yml')
ADSB_DOCKERFILE = os.path.join(ADSB_DIR, 'Dockerfile')

# TAK cert host dir (same mount point used by the Esri bridge).
_TAK_CERT_HOST_DIR = '/opt/tak/certs/files'
_TAK_CERT_CTR_DIR  = '/certs'

CONFIG_DIR = os.environ.get('CONFIG_DIR') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '.config'
)

# adsbcot Docker image — built locally from a minimal Dockerfile so we don't
# depend on a third-party registry image that may lag behind PyPI releases.
_ADSBCOT_IMAGE = 'infra-tak-adsbcot:latest'

# ─────────────────────────────────────────────────────────────────────────────
# Cert helpers
# ─────────────────────────────────────────────────────────────────────────────

def _cert_paths():
    """Host-filesystem paths for adsbcot client certs."""
    d = _TAK_CERT_HOST_DIR
    return {
        'cert': os.path.join(d, 'adsb_client.pem'),
        'key':  os.path.join(d, 'adsb_client.key'),
        'ca':   os.path.join(d, 'adsb_ca.pem'),
    }

def _cert_ctr_paths():
    """Container-side paths passed as PYTAK_TLS_* env vars."""
    return {
        'cert': f'{_TAK_CERT_CTR_DIR}/adsb_client.pem',
        'key':  f'{_TAK_CERT_CTR_DIR}/adsb_client.key',
        'ca':   f'{_TAK_CERT_CTR_DIR}/adsb_ca.pem',
    }

def _cert_status():
    hp = _cert_paths()
    return {
        'has_cert': os.path.exists(hp['cert']),
        'has_key':  os.path.exists(hp['key']),
        'has_ca':   os.path.exists(hp['ca']),
        'cert_name': os.path.basename(hp['cert']) if os.path.exists(hp['cert']) else 'no file',
        'key_name':  os.path.basename(hp['key'])  if os.path.exists(hp['key'])  else 'no file',
        'ca_name':   os.path.basename(hp['ca'])   if os.path.exists(hp['ca'])   else 'no file',
    }

def _run_openssl(*args):
    import subprocess as _sp
    r = _sp.run(['openssl'] + list(args), capture_output=True, text=True)
    return r.returncode == 0, r.stderr.strip()

# ─────────────────────────────────────────────────────────────────────────────
# Settings helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_cfg(load_settings):
    return load_settings().get(ADSB_KEY, {})

def _save_cfg(data, load_settings, save_settings):
    s = load_settings()
    s[ADSB_KEY] = data
    save_settings(s)

# ─────────────────────────────────────────────────────────────────────────────
# Container management helpers
# ─────────────────────────────────────────────────────────────────────────────

def _docker_installed():
    try:
        r = subprocess.run(['docker', '--version'], capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False

def _container_running():
    try:
        r = subprocess.run(
            ['docker', 'ps', '--filter', f'name={ADSB_CONTAINER}', '--format', '{{.Status}}'],
            capture_output=True, text=True, timeout=6,
        )
        return bool(r.stdout.strip() and 'Up' in r.stdout)
    except Exception:
        return False

def _compose_exists():
    return os.path.exists(ADSB_COMPOSE)

def _run_compose(args, timeout=120):
    """Run docker compose -f <compose> <args> in ADSB_DIR."""
    cmd = ['docker', 'compose', '-f', ADSB_COMPOSE] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ADSB_DIR)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, 'Timed out'
    except Exception as e:
        return False, str(e)

# ─────────────────────────────────────────────────────────────────────────────
# Compose / Dockerfile generation
# ─────────────────────────────────────────────────────────────────────────────

def _build_dockerfile():
    return """\
FROM python:3.11-slim
RUN pip install --no-cache-dir adsbcot
ENTRYPOINT ["adsbcot"]
"""

def _build_compose(cfg):
    """Generate docker-compose.yml content from saved config."""
    lat           = str(cfg.get('lat', '0.0'))
    lon           = str(cfg.get('lon', '0.0'))
    radius        = str(int(cfg.get('radius', 100)))
    poll_interval = str(int(cfg.get('poll_interval', 30)))
    tak_host      = (cfg.get('tak_host') or '').strip()
    tak_port      = str(int(cfg.get('tak_port', 8087)))
    tls_enabled   = bool(cfg.get('tls_enabled', False))

    feed_url = f'https://api.airplanes.live/v2/point/{lat}/{lon}/{radius}'

    if tls_enabled:
        cot_url = f'tls://{tak_host}:{tak_port}'
    else:
        cot_url = f'tcp://{tak_host}:{tak_port}'

    hp = _cert_paths()
    cp = _cert_ctr_paths()
    has_cert = os.path.exists(hp['cert'])
    has_key  = os.path.exists(hp['key'])
    has_ca   = os.path.exists(hp['ca'])

    env_lines = [
        f'      FEED_URL: "{feed_url}"',
        f'      COT_URL: "{cot_url}"',
        f'      POLL_INTERVAL: "{poll_interval}"',
    ]
    if tls_enabled:
        if has_cert:
            env_lines.append(f'      PYTAK_TLS_CLIENT_CERT: "{cp["cert"]}"')
        if has_key:
            env_lines.append(f'      PYTAK_TLS_CLIENT_KEY: "{cp["key"]}"')
        if has_ca:
            env_lines.append(f'      PYTAK_TLS_CA_CERT: "{cp["ca"]}"')
        env_lines.append('      PYTAK_TLS_DONT_VERIFY: "1"')

    env_block = '\n'.join(env_lines)

    # Only mount certs dir when TLS is enabled and the source dir exists.
    volumes_block = ''
    if tls_enabled and os.path.exists(_TAK_CERT_HOST_DIR):
        volumes_block = f'      - {_TAK_CERT_HOST_DIR}:{_TAK_CERT_CTR_DIR}:ro'

    compose = f"""\
services:
  adsbcot:
    image: {_ADSBCOT_IMAGE}
    build: .
    container_name: {ADSB_CONTAINER}
    restart: unless-stopped
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    mem_limit: 256m
    environment:
{env_block}
"""
    if volumes_block:
        compose += f"""\
    volumes:
{volumes_block}
"""
    compose += """\
    extra_hosts:
      - "host.docker.internal:host-gateway"
"""
    return compose

# ─────────────────────────────────────────────────────────────────────────────
# Deploy thread
# ─────────────────────────────────────────────────────────────────────────────

_deploy_status: dict = {'running': False, 'complete': False, 'error': False, 'log': []}
_deploy_lock = threading.Lock()

def _plog(msg, log_list):
    log_list.append(msg)

def _run_deploy(cfg, load_settings, save_settings):
    global _deploy_status
    log: list = []
    _deploy_status.update({'running': True, 'complete': False, 'error': False, 'log': log})

    def plog(m):
        _plog(m, log)

    try:
        plog('━━━ ADS-B CoT Bridge deploy ━━━')

        if not _docker_installed():
            plog('✗ Docker is not installed — install Docker first')
            _deploy_status.update({'running': False, 'error': True})
            return

        os.makedirs(ADSB_DIR, mode=0o755, exist_ok=True)
        plog(f'✓ Working directory: {ADSB_DIR}')

        # Write Dockerfile
        with open(ADSB_DOCKERFILE, 'w') as f:
            f.write(_build_dockerfile())
        plog('✓ Dockerfile written')

        # Write docker-compose.yml
        with open(ADSB_COMPOSE, 'w') as f:
            f.write(_build_compose(cfg))
        plog('✓ docker-compose.yml written')

        # Build image
        plog('')
        plog('━━━ Building adsbcot image (pip install adsbcot) ━━━')
        plog('  This may take 1–2 minutes on first run...')
        ok, out = _run_compose(['build', '--no-cache'], timeout=300)
        for line in (out or '').splitlines():
            plog(f'  {line}')
        if not ok:
            plog('✗ Image build failed')
            _deploy_status.update({'running': False, 'error': True})
            return
        plog('✓ Image built')

        # Stop any existing container
        _run_compose(['down', '--remove-orphans'], timeout=30)

        # Start container
        plog('')
        plog('━━━ Starting container ━━━')
        ok, out = _run_compose(['up', '-d'], timeout=60)
        for line in (out or '').splitlines():
            plog(f'  {line}')
        if not ok:
            plog(f'✗ docker compose up failed')
            _deploy_status.update({'running': False, 'error': True})
            return
        plog(f'✓ Container started')

        # Persist deploy timestamp
        s = load_settings()
        s.setdefault(ADSB_KEY, {}).update({
            **cfg,
            'deployed': True,
            'deployed_at': time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()),
        })
        save_settings(s)
        plog('✓ Settings saved')
        plog('')
        plog('━━━ Deploy complete ━━━')
        _deploy_status.update({'running': False, 'complete': True, 'error': False})

    except Exception as e:
        _plog(f'✗ Unexpected error: {e}', log)
        _deploy_status.update({'running': False, 'error': True})

# ─────────────────────────────────────────────────────────────────────────────
# HTML template
# ─────────────────────────────────────────────────────────────────────────────

ADSB_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>ADS-B CoT Bridge — infra-TAK</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0" rel="stylesheet">
<style>
:root{--bg-deep:#080b14;--bg-surface:#0f1219;--bg-card:#161b26;--border:#1e2736;--text-primary:#f1f5f9;--text-secondary:#cbd5e1;--text-dim:#94a3b8;--accent:#3b82f6;--cyan:#06b6d4;--green:#10b981;--red:#ef4444;--yellow:#eab308}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg-deep);color:var(--text-primary);font-family:'DM Sans',sans-serif;min-height:100vh;display:flex;flex-direction:row}
.sidebar{width:220px;min-width:220px;background:var(--bg-surface);border-right:1px solid var(--border);padding:24px 0;flex-shrink:0}
.material-symbols-outlined{font-family:'Material Symbols Outlined';font-weight:400;font-style:normal;font-size:20px;line-height:1;letter-spacing:normal;white-space:nowrap;direction:ltr;-webkit-font-smoothing:antialiased}
.nav-icon.material-symbols-outlined{font-size:22px;width:22px;text-align:center}
.sidebar-logo{padding:0 20px 24px;border-bottom:1px solid var(--border);margin-bottom:16px}
.sidebar-logo span{font-size:15px;font-weight:700}.sidebar-logo small{display:block;font-size:10px;color:var(--text-dim);font-family:'JetBrains Mono',monospace;margin-top:2px}
.nav-item{display:flex;align-items:center;gap:10px;padding:9px 20px;color:var(--text-secondary);text-decoration:none;font-size:13px;font-weight:500;transition:all .15s;border-left:2px solid transparent}
.nav-item:hover{color:var(--text-primary);background:rgba(255,255,255,.03)}.nav-item.active{color:var(--cyan);background:rgba(6,182,212,.06);border-left-color:var(--cyan)}
.nav-icon{font-size:15px;width:18px;text-align:center}
.main{flex:1;min-width:0;overflow-y:auto;padding:32px}
.page-header{margin-bottom:28px}.page-header h1{font-size:22px;font-weight:700}.page-header p{color:var(--text-secondary);font-size:13px;margin-top:4px}
.card{background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:24px;margin-bottom:20px}
.card-title{font-size:13px;font-weight:600;color:var(--text-dim);text-transform:uppercase;letter-spacing:.08em;margin-bottom:16px}
.status-banner{display:flex;align-items:center;gap:12px;padding:14px 18px;border-radius:10px;margin-bottom:20px;font-size:13px}
.status-banner.running{background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.2);color:var(--green)}
.status-banner.stopped{background:rgba(234,179,8,.08);border:1px solid rgba(234,179,8,.2);color:var(--yellow)}
.status-banner.deployed{background:rgba(6,182,212,.08);border:1px solid rgba(6,182,212,.2);color:var(--cyan)}
.status-banner.error{background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.2);color:var(--red)}
.dot{width:8px;height:8px;border-radius:50%;background:currentColor;flex-shrink:0}
.btn{display:inline-flex;align-items:center;gap:8px;padding:10px 20px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;border:none;transition:opacity .15s}
.btn:hover{opacity:.85}.btn:disabled{opacity:.4;cursor:default}
.btn-primary{background:var(--accent);color:#fff}
.btn-success{background:var(--green);color:#fff}
.btn-danger{background:var(--red);color:#fff}
.btn-ghost{background:rgba(255,255,255,.05);color:var(--text-secondary);border:1px solid var(--border)}
.btn-sm{padding:7px 14px;font-size:12px}
.controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.form-label{display:block;font-size:12px;font-weight:600;color:var(--text-secondary);margin-bottom:6px}
.form-input{width:100%;background:#0a0e1a;border:1px solid var(--border);border-radius:8px;padding:10px 14px;color:var(--text-primary);font-size:13px;font-family:'DM Sans',sans-serif}
.form-input:focus{outline:none;border-color:var(--accent)}
.form-group{margin-bottom:16px}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}
.hint{font-size:11px;color:var(--text-dim);margin-top:4px}
hr{border:none;border-top:1px solid var(--border);margin:16px 0}
.upload-row{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.upload-label{display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border-radius:7px;background:rgba(255,255,255,.05);border:1px solid var(--border);color:var(--text-secondary);font-size:12px;font-weight:600;cursor:pointer;transition:all .15s}
.upload-label:hover{border-color:var(--accent);color:var(--accent)}
.upload-label input[type=file]{display:none}
.cert-file-status{font-size:12px;color:var(--text-dim);font-family:monospace}
.cert-file-status.ok{color:var(--green)}
.cert-file-status.missing{color:var(--red)}
.log-box{background:#0a0e1a;border:1px solid var(--border);border-radius:8px;padding:14px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-secondary);max-height:320px;overflow-y:auto;white-space:pre-wrap;word-break:break-all}
.toast{position:fixed;bottom:24px;right:24px;padding:12px 20px;border-radius:10px;font-size:13px;font-weight:600;z-index:9999;opacity:0;transition:opacity .3s;pointer-events:none}
.toast.show{opacity:1}.toast.success{background:var(--green);color:#fff}.toast.error{background:var(--red);color:#fff}.toast.warn{background:var(--yellow);color:#000}
.format-tab{padding:7px 16px;border-radius:7px;font-size:12px;font-weight:600;cursor:pointer;border:1px solid var(--border);background:transparent;color:var(--text-secondary);transition:all .15s}
.format-tab.active{background:var(--accent);color:#fff;border-color:var(--accent)}
</style>
</head>
<body>
{{ sidebar_html }}
<div class="main">
  <div class="page-header">
    <h1>&#9992; ADS-B CoT Bridge</h1>
    <p>Stream live aircraft positions from Airplanes.live to TAKServer as CoT events &mdash; powered by <a href="https://github.com/snstac/adsbcot" target="_blank" style="color:var(--cyan)">adsbcot</a> in a managed Docker container</p>
  </div>

  {% if running %}
  <div class="status-banner running"><div class="dot"></div>Container running &mdash; aircraft CoT streaming to TAKServer</div>
  {% elif installed %}
  <div class="status-banner stopped"><div class="dot"></div>Container stopped &mdash; click Start to resume streaming</div>
  {% endif %}

  {% if deployed %}
  <div class="status-banner deployed"><div class="dot"></div>Last deployed {{ deployed_at }}</div>
  {% endif %}

  <!-- Feed Settings -->
  <div class="card">
    <div class="card-title">Airplanes.live Feed</div>
    <p class="hint" style="margin-bottom:16px">
      Free API &mdash; no key required. Limited to one request per second and a maximum radius of 250 nm.
      Aircraft appear on your EUD map with 2525c air-track icons.
    </p>
    <div class="grid-3">
      <div class="form-group">
        <label class="form-label">Latitude</label>
        <input id="lat" class="form-input" type="number" step="0.0001" min="-90" max="90"
               placeholder="34.0522" value="{{ cfg.get('lat','') }}">
      </div>
      <div class="form-group">
        <label class="form-label">Longitude</label>
        <input id="lon" class="form-input" type="number" step="0.0001" min="-180" max="180"
               placeholder="-118.2437" value="{{ cfg.get('lon','') }}">
      </div>
      <div class="form-group">
        <label class="form-label">Radius (nm, max 250)</label>
        <input id="radius" class="form-input" type="number" min="1" max="250"
               placeholder="100" value="{{ cfg.get('radius', 100) }}">
      </div>
    </div>
    <div class="form-group" style="max-width:200px">
      <label class="form-label">Poll Interval (seconds)</label>
      <input id="poll-interval" class="form-input" type="number" min="5" max="300"
             value="{{ cfg.get('poll_interval', 30) }}">
      <div class="hint">Airplanes.live allows at most 1 request/second; 30s is a safe default.</div>
    </div>
    <div class="form-group" style="margin-top:8px">
      <label class="form-label" style="margin-bottom:8px">Feed URL preview</label>
      <div id="feed-url-preview" style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--cyan);padding:8px 12px;background:#0a0e1a;border-radius:6px;border:1px solid var(--border);word-break:break-all"></div>
    </div>
  </div>

  <!-- TAKServer Connection -->
  <div class="card">
    <div class="card-title">TAKServer Connection</div>
    <div class="grid-2" style="margin-bottom:16px">
      <div class="form-group">
        <label class="form-label">TAKServer Host / IP</label>
        <input id="tak-host" class="form-input" type="text"
               placeholder="10.0.0.1" value="{{ cfg.get('tak_host','') }}">
      </div>
      <div class="form-group">
        <label class="form-label">Port</label>
        <input id="tak-port" class="form-input" type="number" min="1" max="65535"
               value="{{ cfg.get('tak_port', 8087) }}">
        <div class="hint">8087 = TCP (no TLS) &nbsp;|&nbsp; 8089 = TLS with client cert</div>
      </div>
    </div>
    <div class="form-group">
      <label style="display:flex;align-items:center;gap:10px;cursor:pointer;font-size:13px">
        <input type="checkbox" id="tls-enabled" style="width:16px;height:16px;accent-color:var(--accent)"
               {{ 'checked' if cfg.get('tls_enabled') else '' }} onchange="onTlsToggle()">
        <span>Enable TLS (mTLS with client certificate)</span>
      </label>
      <div class="hint" style="margin-top:6px">Enable when connecting to port 8089. Upload a client certificate below.</div>
    </div>

    <hr>
    <div class="card-title" style="margin-top:4px">TLS Certificates</div>

    <div id="tls-section" style="{{ '' if cfg.get('tls_enabled') else 'opacity:.4;pointer-events:none' }}">
      <!-- Format toggle -->
      <div style="display:flex;gap:8px;margin-bottom:16px">
        <button class="format-tab active" id="fmt-pem" onclick="setCertFormat('pem')">PEM files (cert + key)</button>
        <button class="format-tab" id="fmt-p12" onclick="setCertFormat('p12')">PKCS12 / P12</button>
      </div>

      <div id="cert-pem-section">
        <div class="upload-row">
          <label class="upload-label">&#128196; Client Certificate (.pem/.crt)
            <input type="file" id="file-cert" accept=".pem,.crt,.cer" onchange="setFileLabel(this,'lbl-cert')">
          </label>
          <span class="cert-file-status {{ 'ok' if cert_status.get('has_cert') else 'missing' }}" id="lbl-cert">
            {{ cert_status.get('cert_name','no file') }}
          </span>
        </div>
        <div class="upload-row">
          <label class="upload-label">&#128196; Private Key (.key/.pem)
            <input type="file" id="file-key" accept=".key,.pem" onchange="setFileLabel(this,'lbl-key')">
          </label>
          <span class="cert-file-status {{ 'ok' if cert_status.get('has_key') else 'missing' }}" id="lbl-key">
            {{ cert_status.get('key_name','no file') }}
          </span>
        </div>
      </div>

      <div id="cert-p12-section" style="display:none">
        <div class="upload-row">
          <label class="upload-label">&#128196; P12 / PFX file
            <input type="file" id="file-p12" accept=".p12,.pfx" onchange="setFileLabel(this,'lbl-p12')">
          </label>
          <span class="cert-file-status {{ 'ok' if cert_status.get('has_cert') else 'missing' }}" id="lbl-p12">
            {{ cert_status.get('cert_name','no file') }}
          </span>
        </div>
      </div>

      <div class="upload-row">
        <label class="upload-label">&#128196; CA Certificate <span style="color:var(--text-dim);font-weight:400">(optional)</span>
          <input type="file" id="file-ca" accept=".pem,.crt,.cer,.p12,.pfx" onchange="setFileLabel(this,'lbl-ca')">
        </label>
        <span class="cert-file-status {{ 'ok' if cert_status.get('has_ca') else '' }}" id="lbl-ca">
          {{ cert_status.get('ca_name','no file') }}
        </span>
      </div>

      <div class="form-group" style="max-width:320px;margin-top:8px">
        <label class="form-label">Certificate Password</label>
        <input id="cert-password" class="form-input" type="password" placeholder="leave blank if no password">
      </div>

      <div class="controls" style="margin-top:12px">
        <button class="btn btn-ghost btn-sm" id="upload-btn" onclick="uploadCerts()">&#8679; Upload Certificates</button>
        <span id="cert-upload-status" style="font-size:12px;color:var(--text-dim)">
          {% if cert_status.get('has_cert') %}Certificates on disk{% endif %}
        </span>
      </div>
    </div>
  </div>

  <!-- Actions -->
  <div class="card">
    <div class="card-title">Container Control</div>
    <div class="controls" style="margin-bottom:16px">
      <button class="btn btn-success" id="deploy-btn" onclick="deployContainer()">&#9654; Save &amp; Deploy</button>
      {% if installed %}
      <button class="btn btn-ghost" onclick="controlContainer('start')">Start</button>
      <button class="btn btn-ghost" onclick="controlContainer('stop')">Stop</button>
      <button class="btn btn-ghost" onclick="controlContainer('restart')">Restart</button>
      <button class="btn btn-danger btn-sm" onclick="removeContainer()" style="margin-left:auto">Remove</button>
      {% endif %}
    </div>
    <div id="action-status" style="font-size:13px;color:var(--text-dim)"></div>
  </div>

  <!-- Deploy log -->
  {% if deploying or deploy_done or deploy_error %}
  <div class="card">
    <div class="card-title">Deploy Log</div>
    <div class="log-box" id="deploy-log">{{ deploy_log }}</div>
  </div>
  {% elif installed %}
  <div class="card">
    <div class="card-title">Container Logs</div>
    <div class="controls" style="margin-bottom:12px">
      <button class="btn btn-ghost btn-sm" onclick="fetchLogs()">&#8635; Refresh Logs</button>
    </div>
    <div class="log-box" id="container-log">Click Refresh Logs to view recent output.</div>
  </div>
  {% endif %}

</div><!-- .main -->

<div class="toast" id="toast"></div>

<script>
// ── Feed URL preview ──────────────────────────────────────────────────────────
function updatePreview() {
  const lat = document.getElementById('lat').value.trim() || '0.0';
  const lon = document.getElementById('lon').value.trim() || '0.0';
  const r   = document.getElementById('radius').value.trim() || '100';
  document.getElementById('feed-url-preview').textContent =
    `https://api.airplanes.live/v2/point/${lat}/${lon}/${r}`;
}
['lat','lon','radius'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('input', updatePreview);
});
document.addEventListener('DOMContentLoaded', updatePreview);

// ── TLS toggle ────────────────────────────────────────────────────────────────
function onTlsToggle() {
  const enabled = document.getElementById('tls-enabled').checked;
  document.getElementById('tls-section').style.opacity = enabled ? '' : '0.4';
  document.getElementById('tls-section').style.pointerEvents = enabled ? '' : 'none';
}

// ── Cert format tabs ──────────────────────────────────────────────────────────
let _certFormat = 'pem';
function setCertFormat(fmt) {
  _certFormat = fmt;
  document.getElementById('cert-pem-section').style.display = fmt === 'pem' ? '' : 'none';
  document.getElementById('cert-p12-section').style.display = fmt === 'p12' ? '' : 'none';
  document.getElementById('fmt-pem').classList.toggle('active', fmt === 'pem');
  document.getElementById('fmt-p12').classList.toggle('active', fmt === 'p12');
}
function setFileLabel(input, labelId) {
  const span = document.getElementById(labelId);
  if (input.files && input.files[0]) {
    span.textContent = input.files[0].name;
    span.className = 'cert-file-status ok';
  }
}

// ── Cert upload ───────────────────────────────────────────────────────────────
async function uploadCerts() {
  const btn = document.getElementById('upload-btn');
  const status = document.getElementById('cert-upload-status');
  const fd = new FormData();
  fd.append('format', _certFormat);
  fd.append('password', document.getElementById('cert-password').value);
  if (_certFormat === 'pem') {
    const cert = document.getElementById('file-cert').files[0];
    const key  = document.getElementById('file-key').files[0];
    if (!cert || !key) { showToast('Select both a certificate and key file', 'warn'); return; }
    fd.append('cert', cert); fd.append('key', key);
  } else {
    const p12 = document.getElementById('file-p12').files[0];
    if (!p12) { showToast('Select a P12 file', 'warn'); return; }
    fd.append('p12', p12);
  }
  const ca = document.getElementById('file-ca').files[0];
  if (ca) fd.append('ca', ca);
  btn.disabled = true; status.textContent = 'Uploading…';
  try {
    const res = await fetch('/api/adsb/upload-certs', {method:'POST', body:fd});
    const data = await res.json();
    if (data.ok) { showToast(data.message || 'Certificates uploaded', 'success'); status.textContent = 'Uploaded'; }
    else { showToast(data.error || 'Upload failed', 'error'); status.textContent = 'Error: ' + (data.error||''); }
  } catch(e) { showToast(e.message, 'error'); status.textContent = 'Error: ' + e.message; }
  finally { btn.disabled = false; }
}

// ── Collect config ────────────────────────────────────────────────────────────
function collectConfig() {
  return {
    lat:           parseFloat(document.getElementById('lat').value) || 0,
    lon:           parseFloat(document.getElementById('lon').value) || 0,
    radius:        parseInt(document.getElementById('radius').value) || 100,
    poll_interval: parseInt(document.getElementById('poll-interval').value) || 30,
    tak_host:      document.getElementById('tak-host').value.trim(),
    tak_port:      parseInt(document.getElementById('tak-port').value) || 8087,
    tls_enabled:   document.getElementById('tls-enabled').checked,
  };
}

// ── Deploy ────────────────────────────────────────────────────────────────────
async function deployContainer() {
  const cfg = collectConfig();
  if (!cfg.tak_host) { showToast('Enter a TAKServer host', 'warn'); return; }
  const btn = document.getElementById('deploy-btn');
  btn.disabled = true;
  setStatus('Deploying container… this may take a few minutes on first run.');
  try {
    const res = await fetch('/api/adsb/deploy', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(cfg),
    });
    const data = await res.json();
    if (data.ok) {
      showToast('Deploy started', 'success');
      pollDeploy();
    } else {
      showToast(data.error || 'Deploy failed', 'error');
      setStatus('Error: ' + (data.error || 'unknown'));
      btn.disabled = false;
    }
  } catch(e) { showToast(e.message, 'error'); btn.disabled = false; }
}

function pollDeploy() {
  let t = setInterval(async () => {
    try {
      const res = await fetch('/api/adsb/deploy-status');
      const data = await res.json();
      const logEl = document.getElementById('deploy-log');
      if (logEl && data.log) { logEl.textContent = data.log.join('\n'); logEl.scrollTop = logEl.scrollHeight; }
      if (!data.running) {
        clearInterval(t);
        document.getElementById('deploy-btn').disabled = false;
        if (data.error) { showToast('Deploy failed — check log', 'error'); setStatus('Deploy failed'); }
        else { showToast('Deployed successfully', 'success'); setStatus(''); setTimeout(() => location.reload(), 1200); }
      }
    } catch(e) { clearInterval(t); }
  }, 2000);
}

// ── Container control ─────────────────────────────────────────────────────────
async function controlContainer(action) {
  setStatus(action.charAt(0).toUpperCase() + action.slice(1) + 'ing…');
  try {
    const res = await fetch('/api/adsb/control', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action}),
    });
    const data = await res.json();
    if (data.ok) { showToast(action + 'd successfully', 'success'); setStatus(''); setTimeout(() => location.reload(), 800); }
    else { showToast(data.error || 'Failed', 'error'); setStatus('Error: ' + (data.error||'')); }
  } catch(e) { showToast(e.message, 'error'); setStatus(''); }
}

async function removeContainer() {
  if (!confirm('Remove the adsbcot container and docker-compose file? Config will be preserved.')) return;
  setStatus('Removing…');
  try {
    const res = await fetch('/api/adsb/remove', {method:'POST'});
    const data = await res.json();
    if (data.ok) { showToast('Container removed', 'success'); setTimeout(() => location.reload(), 800); }
    else { showToast(data.error || 'Failed', 'error'); setStatus(''); }
  } catch(e) { showToast(e.message, 'error'); setStatus(''); }
}

// ── Live logs ─────────────────────────────────────────────────────────────────
async function fetchLogs() {
  const el = document.getElementById('container-log');
  if (!el) return;
  el.textContent = 'Fetching…';
  try {
    const res = await fetch('/api/adsb/logs');
    const data = await res.json();
    el.textContent = data.logs || '(no output)';
    el.scrollTop = el.scrollHeight;
  } catch(e) { el.textContent = 'Error: ' + e.message; }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function setStatus(msg) {
  const el = document.getElementById('action-status');
  if (el) el.textContent = msg;
}
function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = 'toast show ' + (type||'success');
  clearTimeout(t._tid); t._tid = setTimeout(() => t.className = 'toast', 3000);
}

// Auto-poll when deploying
{% if deploying %}
document.addEventListener('DOMContentLoaded', pollDeploy);
{% endif %}
</script>
</body>
</html>
'''

# ─────────────────────────────────────────────────────────────────────────────
# Route registration
# ─────────────────────────────────────────────────────────────────────────────

def register_routes(app, login_required, load_settings, save_settings):
    from flask import request, jsonify, render_template_string

    # ── Main page ────────────────────────────────────────────────────────────
    @app.route('/adsb')
    @login_required
    def adsb_page():
        from flask import make_response
        settings = load_settings()
        cfg = settings.get(ADSB_KEY, {})

        # Try to import sidebar renderer (mirrors esri.py pattern)
        sidebar_html = ''
        try:
            from app import render_sidebar, detect_modules
            modules = detect_modules()
            active = 'adsb'
            sidebar_html = render_sidebar(modules, active)
        except Exception:
            pass

        deploying  = _deploy_status.get('running', False)
        deploy_log = '\n'.join(_deploy_status.get('log', []))
        deploy_done  = _deploy_status.get('complete', False)
        deploy_error = _deploy_status.get('error', False)

        resp = make_response(render_template_string(
            ADSB_TEMPLATE,
            cfg=cfg,
            cert_status=_cert_status(),
            installed=_compose_exists(),
            running=_container_running(),
            deployed=bool(cfg.get('deployed')),
            deployed_at=cfg.get('deployed_at', ''),
            sidebar_html=sidebar_html,
            deploying=deploying,
            deploy_done=deploy_done,
            deploy_error=deploy_error,
            deploy_log=deploy_log,
        ))
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        return resp

    # ── Deploy ───────────────────────────────────────────────────────────────
    @app.route('/api/adsb/deploy', methods=['POST'])
    @login_required
    def adsb_deploy():
        global _deploy_status
        if _deploy_status.get('running'):
            return jsonify({'ok': False, 'error': 'Deploy already in progress'}), 409
        data = request.get_json() or {}
        # Validate
        if not (data.get('tak_host') or '').strip():
            return jsonify({'ok': False, 'error': 'TAKServer host is required'}), 400
        radius = int(data.get('radius', 100))
        if radius < 1 or radius > 250:
            return jsonify({'ok': False, 'error': 'Radius must be 1–250 nm'}), 400
        if not _docker_installed():
            return jsonify({'ok': False, 'error': 'Docker is not installed on this host'}), 400

        cfg = {
            'lat':           float(data.get('lat', 0.0)),
            'lon':           float(data.get('lon', 0.0)),
            'radius':        radius,
            'poll_interval': max(5, int(data.get('poll_interval', 30))),
            'tak_host':      data['tak_host'].strip(),
            'tak_port':      int(data.get('tak_port', 8087)),
            'tls_enabled':   bool(data.get('tls_enabled', False)),
        }
        t = threading.Thread(target=_run_deploy, args=(cfg, load_settings, save_settings), daemon=True)
        t.start()
        return jsonify({'ok': True})

    @app.route('/api/adsb/deploy-status')
    @login_required
    def adsb_deploy_status():
        return jsonify({
            'running':  _deploy_status.get('running', False),
            'complete': _deploy_status.get('complete', False),
            'error':    _deploy_status.get('error', False),
            'log':      _deploy_status.get('log', []),
        })

    # ── Container control ─────────────────────────────────────────────────────
    @app.route('/api/adsb/control', methods=['POST'])
    @login_required
    def adsb_control():
        data = request.get_json() or {}
        action = (data.get('action') or '').strip().lower()
        if action not in ('start', 'stop', 'restart'):
            return jsonify({'ok': False, 'error': 'Unknown action'}), 400
        if not _compose_exists():
            return jsonify({'ok': False, 'error': 'Not deployed yet — deploy first'}), 400
        if action == 'start':
            ok, out = _run_compose(['up', '-d'], timeout=60)
        elif action == 'stop':
            ok, out = _run_compose(['stop'], timeout=30)
        else:
            ok, out = _run_compose(['restart'], timeout=60)
        return jsonify({'ok': ok, 'output': out[:800]})

    @app.route('/api/adsb/remove', methods=['POST'])
    @login_required
    def adsb_remove():
        if not _compose_exists():
            return jsonify({'ok': False, 'error': 'Not deployed'}), 400
        _run_compose(['down', '--remove-orphans'], timeout=30)
        try:
            import shutil
            if os.path.exists(ADSB_COMPOSE):
                os.remove(ADSB_COMPOSE)
            if os.path.exists(ADSB_DOCKERFILE):
                os.remove(ADSB_DOCKERFILE)
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 500
        # Mark undeployed in settings
        s = load_settings()
        s.setdefault(ADSB_KEY, {})['deployed'] = False
        save_settings(s)
        return jsonify({'ok': True})

    # ── Container logs ────────────────────────────────────────────────────────
    @app.route('/api/adsb/logs')
    @login_required
    def adsb_logs():
        try:
            r = subprocess.run(
                ['docker', 'logs', '--tail', '200', ADSB_CONTAINER],
                capture_output=True, text=True, timeout=10,
            )
            return jsonify({'logs': (r.stdout + r.stderr).strip()})
        except Exception as e:
            return jsonify({'logs': f'Error: {e}'})

    # ── Status ────────────────────────────────────────────────────────────────
    @app.route('/api/adsb/status')
    @login_required
    def adsb_status():
        return jsonify({
            'installed': _compose_exists(),
            'running':   _container_running(),
            'docker':    _docker_installed(),
        })

    # ── Cert upload ───────────────────────────────────────────────────────────
    @app.route('/api/adsb/upload-certs', methods=['POST'])
    @login_required
    def adsb_upload_certs():
        fmt      = request.form.get('format', 'pem')
        password = request.form.get('password', '')
        hp       = _cert_paths()

        os.makedirs(_TAK_CERT_HOST_DIR, exist_ok=True)

        if fmt == 'pem':
            cert_file = request.files.get('cert')
            key_file  = request.files.get('key')
            ca_file   = request.files.get('ca')
            if not cert_file or not key_file:
                return jsonify({'ok': False, 'error': 'cert and key files are required'}), 400
            cert_file.save(hp['cert'])
            key_file.save(hp['key'])
            if ca_file and ca_file.filename:
                ca_file.save(hp['ca'])
            # Decrypt key if password provided
            if password:
                ok, err = _run_openssl('rsa', '-in', hp['key'], '-out', hp['key'] + '.tmp',
                                       '-passin', f'pass:{password}')
                if ok:
                    os.replace(hp['key'] + '.tmp', hp['key'])
                else:
                    try:
                        os.remove(hp['key'] + '.tmp')
                    except Exception:
                        pass
                    return jsonify({'ok': False, 'error': f'Key decryption failed: {err}'}), 400
        elif fmt == 'p12':
            p12_file = request.files.get('p12')
            ca_file  = request.files.get('ca')
            if not p12_file:
                return jsonify({'ok': False, 'error': 'P12 file is required'}), 400
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.p12', delete=False) as tmp:
                p12_file.save(tmp.name)
                tmp_p12 = tmp.name
            passin = f'pass:{password}' if password else 'pass:'
            ok1, e1 = _run_openssl('pkcs12', '-in', tmp_p12, '-clcerts', '-nokeys',
                                   '-out', hp['cert'], '-passin', passin)
            ok2, e2 = _run_openssl('pkcs12', '-in', tmp_p12, '-nocerts', '-nodes',
                                   '-out', hp['key'], '-passin', passin)
            try:
                os.remove(tmp_p12)
            except Exception:
                pass
            if not ok1 or not ok2:
                return jsonify({'ok': False, 'error': f'P12 extraction failed: {e1 or e2}'}), 400
            if ca_file and ca_file.filename:
                ca_name = ca_file.filename.lower()
                if ca_name.endswith('.p12') or ca_name.endswith('.pfx'):
                    with tempfile.NamedTemporaryFile(suffix='.p12', delete=False) as tmp:
                        ca_file.save(tmp.name)
                        tmp_ca = tmp.name
                    ok_ca, _ = _run_openssl('pkcs12', '-in', tmp_ca, '-cacerts', '-nokeys',
                                            '-out', hp['ca'], '-passin', passin)
                    try:
                        os.remove(tmp_ca)
                    except Exception:
                        pass
                else:
                    ca_file.save(hp['ca'])
        else:
            return jsonify({'ok': False, 'error': 'Unknown format'}), 400

        return jsonify({'ok': True, 'message': 'Certificates saved successfully'})
