"""
adsb.py — ADS-B CoT Bridge module for infra-TAK

Registers /adsb and /api/adsb/* routes directly on the Flask app.
Call register_routes(app, login_required, load_settings, save_settings) from app.py.

What it does:
  - Manages a Docker container running adsbcot (https://github.com/snstac/adsbcot)
  - Pulls live ADS-B data from the Airplanes.live API (free, no key required)
  - Converts aircraft to CoT XML with 2525c air-track icons via pytak
  - Sends CoT to TAKServer over TCP or TLS (cert upload supported)
  - Supports local deploy (~/adsbcot/) or remote deploy via SSH (same pattern
    as Node-RED, CloudTAK, etc.)
"""

import json
import os
import subprocess
import shutil
import tempfile
import time
import threading

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

ADSB_KEY        = 'adsb_cot_bridge'
ADSB_DEPLOY_KEY = 'adsb_deployment'
ADSB_CONTAINER  = 'adsbcot'
ADSB_DIR        = os.path.expanduser('~/adsbcot')
ADSB_COMPOSE    = os.path.join(ADSB_DIR, 'docker-compose.yml')
ADSB_DOCKERFILE = os.path.join(ADSB_DIR, 'Dockerfile')

# TAK cert host dir — same volume mount used by the Esri bridge and Node-RED.
_TAK_CERT_HOST_DIR = '/opt/tak/certs/files'
_TAK_CERT_CTR_DIR  = '/certs'

CONFIG_DIR = os.environ.get('CONFIG_DIR') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '.config'
)

# ─────────────────────────────────────────────────────────────────────────────
# Cert helpers (local host only — certs are always uploaded to the infra-TAK
# host and then referenced by path in the compose env vars)
# ─────────────────────────────────────────────────────────────────────────────

def _cert_paths():
    d = _TAK_CERT_HOST_DIR
    return {
        'cert': os.path.join(d, 'adsb_client.pem'),
        'key':  os.path.join(d, 'adsb_client.key'),
        'ca':   os.path.join(d, 'adsb_ca.pem'),
    }

def _cert_ctr_paths():
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
    r = subprocess.run(['openssl'] + list(args), capture_output=True, text=True)
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

def _get_deploy_cfg(settings):
    """Return normalized deployment config (local vs remote SSH)."""
    try:
        from app import _get_module_deployment_config
        return _get_module_deployment_config(settings, ADSB_DEPLOY_KEY)
    except Exception:
        return {'target_mode': 'local', 'deployed': False,
                'remote': {'host': '', 'ssh_user': 'root', 'ssh_port': 22,
                           'auth_method': 'ssh_key', 'ssh_key_path': '', 'ssh_password': ''}}

# ─────────────────────────────────────────────────────────────────────────────
# Container status helpers
# ─────────────────────────────────────────────────────────────────────────────

def _compose_exists():
    """True if the compose file exists locally."""
    return os.path.exists(ADSB_COMPOSE)

def _container_running():
    """True if the adsbcot container is running locally."""
    try:
        r = subprocess.run(
            ['docker', 'ps', '--filter', f'name={ADSB_CONTAINER}', '--format', '{{.Status}}'],
            capture_output=True, text=True, timeout=6,
        )
        return bool(r.stdout.strip() and 'Up' in r.stdout)
    except Exception:
        return False

def _remote_container_running(remote_cfg):
    """True if the adsbcot container is running on the remote host."""
    try:
        from app import _ssh_probe
        ok, out = _ssh_probe(
            remote_cfg,
            f'docker ps --filter name={ADSB_CONTAINER} --format "{{{{.Status}}}}" 2>/dev/null',
            timeout=10,
        )
        return bool(ok and out and 'Up' in out)
    except Exception:
        return False

def _docker_installed_local():
    try:
        r = subprocess.run(['docker', '--version'], capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False

def _run_compose_local(args, timeout=120):
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

def _build_compose(cfg, is_remote=False):
    """Generate docker-compose.yml content from saved ADS-B config."""
    lat           = str(cfg.get('lat', '0.0'))
    lon           = str(cfg.get('lon', '0.0'))
    radius        = str(int(cfg.get('radius', 100)))
    poll_interval = str(int(cfg.get('poll_interval', 30)))
    tak_host      = (cfg.get('tak_host') or '').strip()
    tak_port      = str(int(cfg.get('tak_port', 8087)))
    tls_enabled   = bool(cfg.get('tls_enabled', False))

    feed_url = f'https://api.airplanes.live/v2/point/{lat}/{lon}/{radius}'
    cot_url  = f'{"tls" if tls_enabled else "tcp"}://{tak_host}:{tak_port}'

    hp = _cert_paths()
    cp = _cert_ctr_paths()

    env_lines = [
        f'      FEED_URL: "{feed_url}"',
        f'      COT_URL: "{cot_url}"',
        f'      POLL_INTERVAL: "{poll_interval}"',
    ]
    if tls_enabled:
        if os.path.exists(hp['cert']):
            env_lines.append(f'      PYTAK_TLS_CLIENT_CERT: "{cp["cert"]}"')
        if os.path.exists(hp['key']):
            env_lines.append(f'      PYTAK_TLS_CLIENT_KEY: "{cp["key"]}"')
        if os.path.exists(hp['ca']):
            env_lines.append(f'      PYTAK_TLS_CA_CERT: "{cp["ca"]}"')
        env_lines.append('      PYTAK_TLS_DONT_VERIFY: "1"')

    env_block = '\n'.join(env_lines)

    volumes_block = ''
    if tls_enabled and os.path.exists(_TAK_CERT_HOST_DIR):
        volumes_block = f'    volumes:\n      - {_TAK_CERT_HOST_DIR}:{_TAK_CERT_CTR_DIR}:ro\n'

    return f"""\
services:
  adsbcot:
    image: infra-tak-adsbcot:latest
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
{volumes_block}\
    extra_hosts:
      - "host.docker.internal:host-gateway"
"""

# ─────────────────────────────────────────────────────────────────────────────
# Deploy thread
# ─────────────────────────────────────────────────────────────────────────────

_deploy_status: dict = {'running': False, 'complete': False, 'error': False, 'log': []}

def _run_deploy(cfg, deploy_cfg, load_settings, save_settings):
    global _deploy_status
    log: list = []
    _deploy_status.update({'running': True, 'complete': False, 'error': False, 'log': log})

    def plog(m):
        log.append(m)

    is_remote = deploy_cfg.get('target_mode') == 'remote'

    try:
        from app import _module_run, _module_copy, _ssh_probe
    except ImportError as e:
        plog(f'✗ Cannot import app helpers: {e}')
        _deploy_status.update({'running': False, 'error': True})
        return

    try:
        plog('━━━ ADS-B CoT Bridge deploy ━━━')
        plog(f'  Target: {"remote (" + (deploy_cfg.get("remote", {}).get("host") or "?") + ")" if is_remote else "local"}')

        # ── Ensure Docker ────────────────────────────────────────────────────
        plog('')
        plog('━━━ Checking Docker ━━━')
        ok, out = _module_run(deploy_cfg, 'docker --version 2>&1', timeout=15)
        if not ok or 'Docker version' not in (out or ''):
            plog('  Docker not found — installing...')
            ok, out = _module_run(deploy_cfg,
                'curl -fsSL https://get.docker.com | sh 2>&1', timeout=300, log_fn=plog)
            if not ok:
                plog('✗ Failed to install Docker')
                _deploy_status.update({'running': False, 'error': True})
                return
        plog(f'  {(out or "").strip().splitlines()[0]}')
        plog('✓ Docker available')

        # ── Write files locally then copy ────────────────────────────────────
        plog('')
        plog('━━━ Writing config files ━━━')

        with tempfile.NamedTemporaryFile('w', suffix='.yml', delete=False) as f:
            f.write(_build_compose(cfg, is_remote=is_remote))
            tmp_compose = f.name
        with tempfile.NamedTemporaryFile('w', suffix='', delete=False) as f:
            f.write(_build_dockerfile())
            tmp_dockerfile = f.name

        remote_dir = '~/adsbcot'
        ok_dir, _ = _module_run(deploy_cfg, f'mkdir -p {remote_dir}', timeout=10)
        if not ok_dir:
            plog(f'✗ Could not create {remote_dir}')
            _deploy_status.update({'running': False, 'error': True})
            return

        ok1, _ = _module_copy(deploy_cfg, tmp_compose,    f'{remote_dir}/docker-compose.yml', log_fn=plog)
        ok2, _ = _module_copy(deploy_cfg, tmp_dockerfile, f'{remote_dir}/Dockerfile',         log_fn=plog)

        try:
            os.remove(tmp_compose)
            os.remove(tmp_dockerfile)
        except Exception:
            pass

        if not ok1 or not ok2:
            plog('✗ Failed to write compose files')
            _deploy_status.update({'running': False, 'error': True})
            return
        plog('✓ docker-compose.yml and Dockerfile written')

        # ── Build image ──────────────────────────────────────────────────────
        plog('')
        plog('━━━ Building adsbcot image (pip install adsbcot) ━━━')
        plog('  This may take 1–2 minutes on first run...')
        ok, out = _module_run(deploy_cfg,
            f'cd {remote_dir} && docker compose build --no-cache 2>&1',
            timeout=300, log_fn=plog)
        if not ok:
            plog('✗ Image build failed')
            _deploy_status.update({'running': False, 'error': True})
            return
        plog('✓ Image built')

        # ── Start container ──────────────────────────────────────────────────
        plog('')
        plog('━━━ Starting container ━━━')
        _module_run(deploy_cfg,
            f'cd {remote_dir} && docker compose down --remove-orphans 2>&1',
            timeout=30)
        ok, out = _module_run(deploy_cfg,
            f'cd {remote_dir} && docker compose up -d 2>&1',
            timeout=60, log_fn=plog)
        if not ok:
            plog('✗ docker compose up failed')
            _deploy_status.update({'running': False, 'error': True})
            return
        plog(f'✓ Container started')

        # ── Save settings ────────────────────────────────────────────────────
        s = load_settings()
        s.setdefault(ADSB_KEY, {}).update({
            **cfg,
            'deployed': True,
            'deployed_at': time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()),
        })
        from app import _normalize_module_deployment_config
        s[ADSB_DEPLOY_KEY] = _normalize_module_deployment_config(
            {**deploy_cfg, 'deployed': True}
        )
        save_settings(s)
        plog('✓ Settings saved')
        plog('')
        plog('━━━ Deploy complete ━━━')
        _deploy_status.update({'running': False, 'complete': True, 'error': False})

    except Exception as e:
        log.append(f'✗ Unexpected error: {e}')
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
.collapsible{background:var(--bg-card);border:1px solid var(--border);border-radius:12px;margin-bottom:20px}
.collapsible-header{display:flex;align-items:center;justify-content:space-between;padding:16px 24px;cursor:pointer}
.collapsible-header:hover{background:rgba(255,255,255,.02);border-radius:12px}
.collapsible-body{display:none;padding:0 24px 24px;border-top:1px solid var(--border)}
.status-banner{display:flex;align-items:center;gap:12px;padding:14px 18px;border-radius:10px;margin-bottom:20px;font-size:13px}
.status-banner.running{background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.2);color:var(--green)}
.status-banner.stopped{background:rgba(234,179,8,.08);border:1px solid rgba(234,179,8,.2);color:var(--yellow)}
.status-banner.deployed{background:rgba(6,182,212,.08);border:1px solid rgba(6,182,212,.2);color:var(--cyan)}
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
.log-box{background:#0a0e1a;border:1px solid var(--border);border-radius:8px;padding:14px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-secondary);max-height:340px;overflow-y:auto;white-space:pre-wrap;word-break:break-all}
.metrics-bar{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:16px}
.metric-card{background:var(--bg-surface);border:1px solid var(--border);border-radius:10px;padding:16px;text-align:center}
.metric-label{font-size:11px;color:var(--text-dim);margin-bottom:4px}
.metric-value{font-size:20px;font-weight:600}
.metric-detail{font-size:11px;color:var(--text-dim);margin-top:4px}
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
  <div class="status-banner running"><div class="dot"></div>Container running &mdash; aircraft CoT streaming to TAKServer{% if remote_host %} &nbsp;|&nbsp; remote: <strong>{{ remote_host }}</strong>{% endif %}</div>
  {% elif installed %}
  <div class="status-banner stopped"><div class="dot"></div>Container deployed but stopped &mdash; click Start to resume{% if remote_host %} &nbsp;|&nbsp; remote: <strong>{{ remote_host }}</strong>{% endif %}</div>
  {% endif %}

  {% if deployed %}
  <div class="status-banner deployed"><div class="dot"></div>Last deployed {{ deployed_at }}</div>
  {% endif %}

  <!-- ── Deployment Target ─────────────────────────────────────────────── -->
  <details class="collapsible" id="section-target" style="padding:0">
    <summary class="collapsible-header" style="list-style:none;display:flex;align-items:center;justify-content:space-between;padding:16px 24px;cursor:pointer">
      <span class="card-title" style="margin:0">Deployment Target</span>
      <span style="font-size:18px;color:var(--text-dim)">&#9662;</span>
    </summary>
    <div class="collapsible-body" style="display:block;padding:0 24px 24px;border-top:1px solid var(--border)" id="target-body">
      <div class="form-group" style="margin-top:16px">
        <label class="form-label">Where should adsbcot run?</label>
        <select id="target-mode" class="form-input" style="max-width:320px" onchange="onTargetModeChange()">
          <option value="local" {{ 'selected' if deploy_cfg.get('target_mode','local') != 'remote' else '' }}>On this infra-TAK host</option>
          <option value="remote" {{ 'selected' if deploy_cfg.get('target_mode') == 'remote' else '' }}>On a remote host (SSH)</option>
        </select>
      </div>
      <div id="remote-fields" style="display:{{ 'block' if deploy_cfg.get('target_mode') == 'remote' else 'none' }}">
        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">Remote Host / IP</label>
            <input id="remote-host" class="form-input" type="text" placeholder="10.0.0.15"
                   value="{{ deploy_cfg.get('remote',{}).get('host','') }}">
          </div>
          <div class="form-group">
            <label class="form-label">SSH Port</label>
            <input id="remote-port" class="form-input" type="number" min="1" max="65535"
                   value="{{ deploy_cfg.get('remote',{}).get('ssh_port', 22) }}">
          </div>
        </div>
        <div class="grid-2">
          <div class="form-group">
            <label class="form-label">SSH Username</label>
            <input id="remote-user" class="form-input" type="text" placeholder="root"
                   value="{{ deploy_cfg.get('remote',{}).get('ssh_user','root') }}">
          </div>
          <div class="form-group">
            <label class="form-label">SSH Key Path</label>
            <input id="remote-key" class="form-input" type="text" placeholder="~/.ssh/infra-tak-adsb"
                   value="{{ deploy_cfg.get('remote',{}).get('ssh_key_path','') }}">
          </div>
        </div>
        <div class="form-group">
          <label class="form-label">One-time password <span style="color:var(--text-dim);font-weight:400">(for Install SSH Key only)</span></label>
          <input id="remote-password" class="form-input" type="password" placeholder="Used only for ssh-copy-id" style="max-width:320px">
        </div>
        <div class="controls" style="margin-top:4px;margin-bottom:12px">
          <button class="btn btn-ghost btn-sm" onclick="ensureSshKey()">Generate SSH key</button>
          <button class="btn btn-ghost btn-sm" onclick="installSshKey()">Install SSH key</button>
          <button class="btn btn-ghost btn-sm" onclick="testSsh()">Test SSH</button>
        </div>
        <div id="ssh-status" style="font-size:12px;color:var(--text-dim);margin-bottom:12px"></div>
        <div class="form-group">
          <label class="form-label">Public key <span style="color:var(--text-dim);font-weight:400">(manual copy fallback)</span></label>
          <textarea id="public-key" class="form-input" rows="3" readonly placeholder="Click 'Generate SSH key' to show public key"></textarea>
        </div>
      </div>
      <div style="margin-top:8px">
        <button class="btn btn-ghost btn-sm" onclick="saveTarget()">Save target settings</button>
        <span id="target-save-msg" style="font-size:12px;color:var(--text-dim);margin-left:8px"></span>
      </div>
    </div>
  </details>

  <!-- ── Remote host metrics (shown when remote + installed) ───────────── -->
  {% if remote_host and installed %}
  <div class="card">
    <div style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-dim);margin-bottom:12px">
      Remote host: <span style="color:var(--cyan)">{{ remote_host }}</span>
    </div>
    <div class="card-title" style="margin-bottom:8px">Remote host health</div>
    <div class="metrics-bar" id="remote-metrics-bar">
      <div class="metric-card"><div class="metric-label">CPU</div><div class="metric-value" id="m-cpu">—</div></div>
      <div class="metric-card"><div class="metric-label">Memory</div><div class="metric-value" id="m-ram">—</div><div class="metric-detail" id="m-ram-d"></div></div>
      <div class="metric-card"><div class="metric-label">Disk</div><div class="metric-value" id="m-disk">—</div><div class="metric-detail" id="m-disk-d"></div></div>
      <div class="metric-card"><div class="metric-label">Uptime</div><div class="metric-value" id="m-uptime" style="font-size:16px">—</div></div>
    </div>
  </div>
  {% endif %}

  <!-- ── Feed settings ─────────────────────────────────────────────────── -->
  <div class="card">
    <div class="card-title">Airplanes.live Feed</div>
    <p class="hint" style="margin-bottom:16px">
      Free API &mdash; no account or key required. Maximum radius 250 nm, at most 1 request/second.
      Aircraft appear on EUD maps with 2525c air-track icons.
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
      <div class="hint">30s is a safe default; API allows 1 req/s max.</div>
    </div>
    <div class="form-group">
      <label class="form-label" style="margin-bottom:6px">Feed URL preview</label>
      <div id="feed-url-preview" style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--cyan);padding:8px 12px;background:#0a0e1a;border-radius:6px;border:1px solid var(--border);word-break:break-all"></div>
    </div>
  </div>

  <!-- ── TAKServer connection ───────────────────────────────────────────── -->
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
      <div class="hint" style="margin-top:6px">Enable for port 8089. Upload a client certificate below.</div>
    </div>

    <hr>
    <div class="card-title" style="margin-top:4px">TLS Certificates</div>
    <div id="tls-section">
      <div style="display:flex;gap:8px;margin-bottom:16px">
        <button class="format-tab active" id="fmt-pem" onclick="setCertFormat('pem')">PEM files (cert + key)</button>
        <button class="format-tab" id="fmt-p12" onclick="setCertFormat('p12')">PKCS12 / P12</button>
      </div>
      <div id="cert-pem-section">
        <div class="upload-row">
          <label class="upload-label">&#128196; Client Certificate (.pem/.crt)
            <input type="file" id="file-cert" accept=".pem,.crt,.cer" onchange="setFileLabel(this,'lbl-cert')">
          </label>
          <span class="cert-file-status {{ 'ok' if cert_status.get('has_cert') else '' }}" id="lbl-cert">
            {{ cert_status.get('cert_name','no file') }}
          </span>
        </div>
        <div class="upload-row">
          <label class="upload-label">&#128196; Private Key (.key/.pem)
            <input type="file" id="file-key" accept=".key,.pem" onchange="setFileLabel(this,'lbl-key')">
          </label>
          <span class="cert-file-status {{ 'ok' if cert_status.get('has_key') else '' }}" id="lbl-key">
            {{ cert_status.get('key_name','no file') }}
          </span>
        </div>
      </div>
      <div id="cert-p12-section" style="display:none">
        <div class="upload-row">
          <label class="upload-label">&#128196; P12 / PFX file
            <input type="file" id="file-p12" accept=".p12,.pfx" onchange="setFileLabel(this,'lbl-p12')">
          </label>
          <span class="cert-file-status {{ 'ok' if cert_status.get('has_cert') else '' }}" id="lbl-p12">
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

  <!-- ── Container control ─────────────────────────────────────────────── -->
  <div class="card">
    <div class="card-title">Container Control</div>
    <div class="controls" style="margin-bottom:16px">
      <button class="btn btn-success" id="deploy-btn" onclick="deployContainer()">&#9654; Save &amp; Deploy</button>
      {% if installed %}
      <button class="btn btn-ghost" onclick="controlContainer('start')">Start</button>
      <button class="btn btn-ghost" onclick="controlContainer('stop')">Stop</button>
      <button class="btn btn-ghost" onclick="controlContainer('restart')">Restart</button>
      <button class="btn btn-ghost btn-sm" onclick="fetchLogs()">&#128196; Logs</button>
      <button class="btn btn-danger btn-sm" onclick="removeContainer()" style="margin-left:auto">Remove</button>
      {% endif %}
    </div>
    <div id="action-status" style="font-size:13px;color:var(--text-dim)"></div>
  </div>

  <!-- Deploy log -->
  <div class="card" id="deploy-log-card" style="{{ '' if (deploying or deploy_done or deploy_error) else 'display:none' }}">
    <div class="card-title">Deploy Log</div>
    <div class="log-box" id="deploy-log">{{ deploy_log }}</div>
  </div>

  <!-- Container logs -->
  <div class="card" id="container-log-card" style="display:none">
    <div class="card-title">Container Logs</div>
    <div class="log-box" id="container-log"></div>
  </div>

</div><!-- .main -->
<div class="toast" id="toast"></div>

<script>
// ── Feed URL preview ──────────────────────────────────────────────────────────
function updatePreview() {
  var lat = document.getElementById('lat').value.trim() || '0.0';
  var lon = document.getElementById('lon').value.trim() || '0.0';
  var r   = document.getElementById('radius').value.trim() || '100';
  document.getElementById('feed-url-preview').textContent =
    'https://api.airplanes.live/v2/point/' + lat + '/' + lon + '/' + r;
}
['lat','lon','radius'].forEach(function(id){ var el=document.getElementById(id); if(el) el.addEventListener('input',updatePreview); });
document.addEventListener('DOMContentLoaded', function(){ updatePreview(); onTargetModeChange(); });

// ── Collapsible sections ──────────────────────────────────────────────────────
function toggleSection(id) {
  var body = document.getElementById(id+'-body');
  var icon = document.getElementById(id+'-toggle-icon');
  if (!body) return;
  var open = body.style.display !== 'block';
  body.style.display = open ? 'block' : 'none';
  if (icon) icon.style.transform = open ? 'rotate(180deg)' : 'rotate(0deg)';
}

// ── Deployment target ─────────────────────────────────────────────────────────
function onTargetModeChange() {
  var mode = document.getElementById('target-mode').value;
  document.getElementById('remote-fields').style.display = mode === 'remote' ? 'block' : 'none';
}
function collectTargetConfig() {
  return {
    target_mode: document.getElementById('target-mode').value,
    remote: {
      host:         (document.getElementById('remote-host')||{}).value || '',
      ssh_port:     parseInt((document.getElementById('remote-port')||{}).value) || 22,
      ssh_user:     (document.getElementById('remote-user')||{}).value || 'root',
      ssh_key_path: (document.getElementById('remote-key')||{}).value || '',
    }
  };
}
function saveTarget() {
  var msg = document.getElementById('target-save-msg');
  if (msg) msg.textContent = 'Saving…';
  fetch('/api/adsb/deployment-config', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({config: collectTargetConfig()})
  }).then(function(r){ return r.json(); }).then(function(d){
    if (msg) { msg.textContent = 'Saved.'; msg.style.color = 'var(--green)'; }
  }).catch(function(e){
    if (msg) { msg.textContent = e.message; msg.style.color = 'var(--red)'; }
  });
}
function ensureSshKey() {
  var st = document.getElementById('ssh-status');
  var kEl = document.getElementById('remote-key');
  setSshStatus('Generating SSH key…', 'dim');
  fetch('/api/adsb/remote/ensure-ssh-key', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({config: collectTargetConfig()})
  }).then(function(r){ return r.json(); }).then(function(d){
    if (d.success !== false) {
      if (kEl && d.key_path) kEl.value = d.key_path;
      var ta = document.getElementById('public-key');
      if (ta) ta.value = d.public_key || '';
      setSshStatus('✓ SSH key ready' + (d.fingerprint ? ' | ' + d.fingerprint : ''), 'green');
    } else {
      setSshStatus(d.error || 'Failed', 'red');
    }
  }).catch(function(e){ setSshStatus(e.message, 'red'); });
}
function installSshKey() {
  var pw = (document.getElementById('remote-password')||{}).value;
  if (!pw) { setSshStatus('Enter one-time password for ssh-copy-id', 'red'); return; }
  setSshStatus('Installing SSH key…', 'dim');
  fetch('/api/adsb/remote/install-ssh-key', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({config: collectTargetConfig(), password: pw})
  }).then(function(r){ return r.json(); }).then(function(d){
    setSshStatus(d.success ? '✓ SSH key installed' : (d.error || 'Failed'), d.success ? 'green' : 'red');
  }).catch(function(e){ setSshStatus(e.message, 'red'); });
}
function testSsh() {
  setSshStatus('Testing SSH…', 'dim');
  fetch('/api/adsb/remote/test', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({config: collectTargetConfig()})
  }).then(function(r){ return r.json(); }).then(function(d){
    setSshStatus(d.success ? ('✓ Test passed | ' + ((d.output||'').split('\n')[1]||'').trim()) : (d.error || d.output || 'Test failed'), d.success ? 'green' : 'red');
  }).catch(function(e){ setSshStatus(e.message, 'red'); });
}
function setSshStatus(msg, color) {
  var el = document.getElementById('ssh-status');
  if (!el) return;
  el.textContent = msg;
  el.style.color = color === 'green' ? 'var(--green)' : color === 'red' ? 'var(--red)' : 'var(--text-dim)';
}

// ── TLS toggle ────────────────────────────────────────────────────────────────
function onTlsToggle() {
  var enabled = document.getElementById('tls-enabled').checked;
  var sec = document.getElementById('tls-section');
  sec.style.opacity = enabled ? '' : '0.4';
  sec.style.pointerEvents = enabled ? '' : 'none';
}

// ── Cert format tabs ──────────────────────────────────────────────────────────
var _certFormat = 'pem';
function setCertFormat(fmt) {
  _certFormat = fmt;
  document.getElementById('cert-pem-section').style.display = fmt === 'pem' ? '' : 'none';
  document.getElementById('cert-p12-section').style.display = fmt === 'p12' ? '' : 'none';
  document.getElementById('fmt-pem').classList.toggle('active', fmt === 'pem');
  document.getElementById('fmt-p12').classList.toggle('active', fmt === 'p12');
}
function setFileLabel(input, labelId) {
  var span = document.getElementById(labelId);
  if (input.files && input.files[0]) {
    span.textContent = input.files[0].name;
    span.className = 'cert-file-status ok';
  }
}

// ── Cert upload ───────────────────────────────────────────────────────────────
async function uploadCerts() {
  var btn = document.getElementById('upload-btn');
  var status = document.getElementById('cert-upload-status');
  var fd = new FormData();
  fd.append('format', _certFormat);
  fd.append('password', document.getElementById('cert-password').value);
  if (_certFormat === 'pem') {
    var cert = document.getElementById('file-cert').files[0];
    var key  = document.getElementById('file-key').files[0];
    if (!cert || !key) { showToast('Select both a certificate and key file', 'warn'); return; }
    fd.append('cert', cert); fd.append('key', key);
  } else {
    var p12 = document.getElementById('file-p12').files[0];
    if (!p12) { showToast('Select a P12 file', 'warn'); return; }
    fd.append('p12', p12);
  }
  var ca = document.getElementById('file-ca').files[0];
  if (ca) fd.append('ca', ca);
  btn.disabled = true; status.textContent = 'Uploading…';
  try {
    var res = await fetch('/api/adsb/upload-certs', {method:'POST', body:fd});
    var data = await res.json();
    if (data.ok) { showToast(data.message || 'Certificates uploaded', 'success'); status.textContent = 'Uploaded'; }
    else { showToast(data.error || 'Upload failed', 'error'); status.textContent = 'Error: ' + (data.error||''); }
  } catch(e) { showToast(e.message, 'error'); status.textContent = 'Error: ' + e.message; }
  finally { btn.disabled = false; }
}

// ── Collect ADS-B config ──────────────────────────────────────────────────────
function collectConfig() {
  return {
    lat:           parseFloat(document.getElementById('lat').value) || 0,
    lon:           parseFloat(document.getElementById('lon').value) || 0,
    radius:        parseInt(document.getElementById('radius').value) || 100,
    poll_interval: parseInt(document.getElementById('poll-interval').value) || 30,
    tak_host:      document.getElementById('tak-host').value.trim(),
    tak_port:      parseInt(document.getElementById('tak-port').value) || 8087,
    tls_enabled:   document.getElementById('tls-enabled').checked,
    deploy_cfg:    collectTargetConfig(),
  };
}

// ── Deploy ────────────────────────────────────────────────────────────────────
async function deployContainer() {
  var cfg = collectConfig();
  if (!cfg.tak_host) { showToast('Enter a TAKServer host', 'warn'); return; }
  var btn = document.getElementById('deploy-btn');
  btn.disabled = true;
  setStatus('Deploying container… this may take a few minutes on first run.');
  document.getElementById('deploy-log-card').style.display = '';
  document.getElementById('deploy-log').textContent = 'Starting…';
  try {
    var res = await fetch('/api/adsb/deploy', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(cfg),
    });
    var data = await res.json();
    if (data.ok) { showToast('Deploy started', 'success'); pollDeploy(); }
    else { showToast(data.error || 'Deploy failed', 'error'); setStatus('Error: '+(data.error||'')); btn.disabled = false; }
  } catch(e) { showToast(e.message, 'error'); btn.disabled = false; }
}

function pollDeploy() {
  var t = setInterval(async function() {
    try {
      var res = await fetch('/api/adsb/deploy-status');
      var data = await res.json();
      var logEl = document.getElementById('deploy-log');
      if (logEl && data.log) { logEl.textContent = data.log.join('\n'); logEl.scrollTop = logEl.scrollHeight; }
      if (!data.running) {
        clearInterval(t);
        document.getElementById('deploy-btn').disabled = false;
        if (data.error) { showToast('Deploy failed — check log', 'error'); setStatus('Deploy failed'); }
        else { showToast('Deployed successfully', 'success'); setStatus(''); setTimeout(function(){ location.reload(); }, 1500); }
      }
    } catch(e) { clearInterval(t); }
  }, 1500);
}

// ── Container control ─────────────────────────────────────────────────────────
async function controlContainer(action) {
  setStatus(action.charAt(0).toUpperCase() + action.slice(1) + 'ing…');
  try {
    var res = await fetch('/api/adsb/control', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({action})
    });
    var data = await res.json();
    if (data.ok) { showToast(action + 'd successfully', 'success'); setStatus(''); setTimeout(function(){ location.reload(); }, 800); }
    else { showToast(data.error || 'Failed', 'error'); setStatus('Error: '+(data.error||'')); }
  } catch(e) { showToast(e.message, 'error'); setStatus(''); }
}

async function removeContainer() {
  if (!confirm('Remove the adsbcot container and compose file? Config will be preserved.')) return;
  setStatus('Removing…');
  try {
    var res = await fetch('/api/adsb/remove', {method:'POST'});
    var data = await res.json();
    if (data.ok) { showToast('Container removed', 'success'); setTimeout(function(){ location.reload(); }, 800); }
    else { showToast(data.error || 'Failed', 'error'); setStatus(''); }
  } catch(e) { showToast(e.message, 'error'); setStatus(''); }
}

async function fetchLogs() {
  var card = document.getElementById('container-log-card');
  var el   = document.getElementById('container-log');
  card.style.display = ''; el.textContent = 'Fetching…';
  try {
    var res = await fetch('/api/adsb/logs');
    var data = await res.json();
    el.textContent = data.logs || '(no output)';
    el.scrollTop = el.scrollHeight;
  } catch(e) { el.textContent = 'Error: ' + e.message; }
}

// ── Remote metrics ────────────────────────────────────────────────────────────
async function loadRemoteMetrics() {
  try {
    var r = await fetch('/api/adsb/remote-metrics');
    if (!r.ok) return;
    var d = await r.json();
    var set = function(id, v) { var el=document.getElementById(id); if(el) el.textContent=v||'—'; };
    set('m-cpu',    (d.cpu_percent != null ? d.cpu_percent : '—') + '%');
    set('m-ram',    (d.ram_percent != null ? d.ram_percent : '—') + '%');
    set('m-ram-d',  (d.ram_used_gb != null ? d.ram_used_gb+'GB / '+d.ram_total_gb+'GB' : ''));
    set('m-disk',   (d.disk_percent != null ? d.disk_percent : '—') + '%');
    set('m-disk-d', (d.disk_used_gb != null ? d.disk_used_gb+'GB / '+d.disk_total_gb+'GB' : ''));
    set('m-uptime', d.uptime || '—');
  } catch(e) {}
}
if (document.getElementById('remote-metrics-bar')) {
  loadRemoteMetrics(); setInterval(loadRemoteMetrics, 5000);
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function setStatus(msg) { var el=document.getElementById('action-status'); if(el) el.textContent=msg; }
function showToast(msg, type) {
  var t=document.getElementById('toast');
  t.textContent=msg; t.className='toast show '+(type||'success');
  clearTimeout(t._tid); t._tid=setTimeout(function(){ t.className='toast'; }, 3000);
}

{% if deploying %}document.addEventListener('DOMContentLoaded', pollDeploy);{% endif %}
</script>
</body>
</html>
'''

# ─────────────────────────────────────────────────────────────────────────────
# Route registration
# ─────────────────────────────────────────────────────────────────────────────

def register_routes(app, login_required, load_settings, save_settings):
    from flask import request, jsonify, render_template_string, make_response
    from markupsafe import Markup

    # Register the generic SSH key management routes (same as nodered, cloudtak etc.)
    try:
        from app import _register_module_remote_routes
        _register_module_remote_routes('adsb', ADSB_DEPLOY_KEY)
    except Exception as e:
        print(f'[adsb] Could not register remote routes: {e}', flush=True)

    # ── Main page ────────────────────────────────────────────────────────────
    @app.route('/adsb')
    @login_required
    def adsb_page():
        settings = load_settings()
        cfg = settings.get(ADSB_KEY, {})
        deploy_cfg = _get_deploy_cfg(settings)
        is_remote  = deploy_cfg.get('target_mode') == 'remote'
        remote_host = (deploy_cfg.get('remote', {}).get('host') or '').strip() if is_remote else ''

        if is_remote and deploy_cfg.get('deployed') and remote_host:
            installed = True
            running   = _remote_container_running(deploy_cfg.get('remote', {}))
        else:
            installed = _compose_exists()
            running   = _container_running() if installed else False

        sidebar_html = Markup('')
        try:
            from app import render_sidebar, detect_modules
            sidebar_html = Markup(render_sidebar(detect_modules(), 'adsb'))
        except Exception:
            pass

        resp = make_response(render_template_string(
            ADSB_TEMPLATE,
            cfg=cfg,
            deploy_cfg=deploy_cfg,
            cert_status=_cert_status(),
            installed=installed,
            running=running,
            remote_host=remote_host,
            deployed=bool(cfg.get('deployed')),
            deployed_at=cfg.get('deployed_at', ''),
            sidebar_html=sidebar_html,
            deploying=_deploy_status.get('running', False),
            deploy_done=_deploy_status.get('complete', False),
            deploy_error=_deploy_status.get('error', False),
            deploy_log='\n'.join(_deploy_status.get('log', [])),
        ))
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        return resp

    # ── Deploy ───────────────────────────────────────────────────────────────
    @app.route('/api/adsb/deploy', methods=['POST'])
    @login_required
    def adsb_deploy():
        if _deploy_status.get('running'):
            return jsonify({'ok': False, 'error': 'Deploy already in progress'}), 409
        data = request.get_json() or {}
        if not (data.get('tak_host') or '').strip():
            return jsonify({'ok': False, 'error': 'TAKServer host is required'}), 400
        radius = int(data.get('radius', 100))
        if radius < 1 or radius > 250:
            return jsonify({'ok': False, 'error': 'Radius must be 1–250 nm'}), 400

        # Merge incoming deploy_cfg over saved config
        settings = load_settings()
        saved_deploy = _get_deploy_cfg(settings)
        incoming_deploy = data.get('deploy_cfg') or {}
        try:
            from app import _normalize_module_deployment_config, _deep_merge_dict
            deploy_cfg = _normalize_module_deployment_config(
                _deep_merge_dict(saved_deploy, incoming_deploy)
            )
        except Exception:
            deploy_cfg = saved_deploy

        is_remote = deploy_cfg.get('target_mode') == 'remote'
        if not is_remote and not _docker_installed_local():
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
        t = threading.Thread(
            target=_run_deploy,
            args=(cfg, deploy_cfg, load_settings, save_settings),
            daemon=True,
        )
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

        settings = load_settings()
        deploy_cfg = _get_deploy_cfg(settings)
        is_remote  = deploy_cfg.get('target_mode') == 'remote'

        try:
            from app import _module_run
        except ImportError:
            return jsonify({'ok': False, 'error': 'Cannot import app helpers'}), 500

        remote_dir = '~/adsbcot'
        if action == 'start':
            cmd = f'cd {remote_dir} && docker compose up -d 2>&1'
            timeout = 60
        elif action == 'stop':
            cmd = f'cd {remote_dir} && docker compose stop 2>&1'
            timeout = 30
        else:
            cmd = f'cd {remote_dir} && docker compose restart 2>&1'
            timeout = 60

        if not is_remote and not _compose_exists():
            return jsonify({'ok': False, 'error': 'Not deployed yet'}), 400

        ok, out = _module_run(deploy_cfg, cmd, timeout=timeout)
        return jsonify({'ok': ok, 'output': (out or '')[:800]})

    @app.route('/api/adsb/remove', methods=['POST'])
    @login_required
    def adsb_remove():
        settings = load_settings()
        deploy_cfg = _get_deploy_cfg(settings)
        is_remote  = deploy_cfg.get('target_mode') == 'remote'

        try:
            from app import _module_run
        except ImportError:
            return jsonify({'ok': False, 'error': 'Cannot import app helpers'}), 500

        _module_run(deploy_cfg,
            'cd ~/adsbcot && docker compose down --remove-orphans 2>&1',
            timeout=30)
        _module_run(deploy_cfg, 'rm -f ~/adsbcot/docker-compose.yml ~/adsbcot/Dockerfile', timeout=10)

        s = load_settings()
        s.setdefault(ADSB_KEY, {})['deployed'] = False
        try:
            from app import _normalize_module_deployment_config
            s[ADSB_DEPLOY_KEY] = _normalize_module_deployment_config(
                {**deploy_cfg, 'deployed': False}
            )
        except Exception:
            pass
        save_settings(s)
        return jsonify({'ok': True})

    # ── Container logs ────────────────────────────────────────────────────────
    @app.route('/api/adsb/logs')
    @login_required
    def adsb_logs():
        settings = load_settings()
        deploy_cfg = _get_deploy_cfg(settings)
        try:
            from app import _module_run
            ok, out = _module_run(deploy_cfg,
                f'docker logs --tail 200 {ADSB_CONTAINER} 2>&1',
                timeout=12)
            return jsonify({'logs': (out or '').strip()})
        except Exception as e:
            return jsonify({'logs': f'Error: {e}'})

    # ── Remote host metrics ───────────────────────────────────────────────────
    @app.route('/api/adsb/remote-metrics')
    @login_required
    def adsb_remote_metrics():
        settings = load_settings()
        deploy_cfg = _get_deploy_cfg(settings)
        if deploy_cfg.get('target_mode') != 'remote':
            return jsonify({'error': 'Not a remote deployment'}), 404
        remote = deploy_cfg.get('remote', {})
        if not (remote.get('host') or '').strip():
            return jsonify({'error': 'Remote host not configured'}), 404
        try:
            from app import _get_remote_host_metrics
            metrics = _get_remote_host_metrics(remote)
            if metrics is None:
                return jsonify({'error': 'Could not fetch remote metrics'}), 503
            return jsonify(metrics)
        except Exception as e:
            return jsonify({'error': str(e)}), 503

    # ── Status ────────────────────────────────────────────────────────────────
    @app.route('/api/adsb/status')
    @login_required
    def adsb_status():
        settings = load_settings()
        deploy_cfg = _get_deploy_cfg(settings)
        is_remote  = deploy_cfg.get('target_mode') == 'remote'
        if is_remote:
            running = _remote_container_running(deploy_cfg.get('remote', {}))
            installed = deploy_cfg.get('deployed', False)
        else:
            installed = _compose_exists()
            running   = _container_running() if installed else False
        return jsonify({'installed': installed, 'running': running,
                        'target_mode': deploy_cfg.get('target_mode', 'local')})

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
            if password:
                ok, err = _run_openssl('rsa', '-in', hp['key'], '-out', hp['key'] + '.tmp',
                                       '-passin', f'pass:{password}')
                if ok:
                    os.replace(hp['key'] + '.tmp', hp['key'])
                else:
                    try: os.remove(hp['key'] + '.tmp')
                    except Exception: pass
                    return jsonify({'ok': False, 'error': f'Key decryption failed: {err}'}), 400

        elif fmt == 'p12':
            p12_file = request.files.get('p12')
            ca_file  = request.files.get('ca')
            if not p12_file:
                return jsonify({'ok': False, 'error': 'P12 file is required'}), 400
            with tempfile.NamedTemporaryFile(suffix='.p12', delete=False) as tmp:
                p12_file.save(tmp.name)
                tmp_p12 = tmp.name
            passin = f'pass:{password}' if password else 'pass:'
            ok1, e1 = _run_openssl('pkcs12', '-in', tmp_p12, '-clcerts', '-nokeys',
                                   '-out', hp['cert'], '-passin', passin)
            ok2, e2 = _run_openssl('pkcs12', '-in', tmp_p12, '-nocerts', '-nodes',
                                   '-out', hp['key'], '-passin', passin)
            try: os.remove(tmp_p12)
            except Exception: pass
            if not ok1 or not ok2:
                return jsonify({'ok': False, 'error': f'P12 extraction failed: {e1 or e2}'}), 400
            if ca_file and ca_file.filename:
                ca_name = ca_file.filename.lower()
                if ca_name.endswith('.p12') or ca_name.endswith('.pfx'):
                    with tempfile.NamedTemporaryFile(suffix='.p12', delete=False) as tmp:
                        ca_file.save(tmp.name)
                        tmp_ca = tmp.name
                    _run_openssl('pkcs12', '-in', tmp_ca, '-cacerts', '-nokeys',
                                 '-out', hp['ca'], '-passin', passin)
                    try: os.remove(tmp_ca)
                    except Exception: pass
                else:
                    ca_file.save(hp['ca'])
        else:
            return jsonify({'ok': False, 'error': 'Unknown format'}), 400

        return jsonify({'ok': True, 'message': 'Certificates saved successfully'})
