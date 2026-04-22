from flask import Blueprint, request, jsonify, render_template_string, make_response
import os, json, subprocess, threading, html, shutil
from datetime import datetime
from routes.helpers import login_required, load_settings, save_settings, VERSION

cot_featurelayer_bp = Blueprint('cot_featurelayer', __name__)

_CONDA_BIN = '/root/miniconda/bin/conda'

# ── CoT-FeatureLayer ─────────────────────────────────────────────────────────
COT_FL_DIR     = '/opt/CoT-FeatureLayer'
COT_FL_SERVICE = 'cot-featurelayer'
_cot_fl_install_log    = []
_cot_fl_install_status = {'running': False, 'complete': False, 'error': False}
_cot_fl_conda_log      = []
_cot_fl_conda_status   = {'running': False, 'complete': False, 'error': False}


def _cot_fl_load_config():
    s = load_settings()
    return s.get('cot_featurelayer', {})


def _cot_fl_save_config(cfg):
    s = load_settings()
    s['cot_featurelayer'] = cfg
    save_settings(s)


def _run_cot_fl_conda_install():
    """Background thread: ensure Miniconda + arcgis_env are ready (shared with tak_esri)."""
    import shutil as _shutil
    log    = _cot_fl_conda_log
    status = _cot_fl_conda_status

    def plog(msg):
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        log.append(entry)
        print(entry, flush=True)

    try:
        # ── Step 1: Miniconda ─────────────────────────────────────────────────
        plog("━━━ Step 1/3: Miniconda ━━━")
        if not os.path.exists(_CONDA_BIN):
            plog("  Downloading Miniconda installer…")
            r = subprocess.run(
                ['wget', '-q', 'https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh',
                 '-O', '/tmp/miniconda.sh'],
                capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                plog(f"  ✗ Download failed: {(r.stderr or r.stdout or '')[:200]}")
                status.update({'running': False, 'error': True})
                return
            r = subprocess.run(['bash', '/tmp/miniconda.sh', '-b', '-p', '/root/miniconda'],
                               capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                plog(f"  ✗ Install failed: {(r.stderr or r.stdout or '')[:200]}")
                status.update({'running': False, 'error': True})
                return
            plog("  ✓ Miniconda installed to /root/miniconda/")
        else:
            plog("  ✓ Already installed")

        # ── Step 2: arcgis_env ────────────────────────────────────────────────
        plog("")
        plog("━━━ Step 2/3: arcgis_env (Python 3.9) ━━━")
        r = subprocess.run([_CONDA_BIN, 'env', 'list'], capture_output=True, text=True, timeout=30)
        if 'arcgis_env' in (r.stdout or ''):
            plog("  ✓ arcgis_env already exists (shared with TAK-Esri)")
        else:
            plog("  Creating environment…")
            r = subprocess.run([_CONDA_BIN, 'create', '-n', 'arcgis_env', 'python=3.9', '-y'],
                               capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                plog(f"  ✗ Failed: {(r.stderr or r.stdout or '')[:300]}")
                status.update({'running': False, 'error': True})
                return
            plog("  ✓ arcgis_env created")

        # ── Step 3: ArcGIS SDK ────────────────────────────────────────────────
        plog("")
        plog("━━━ Step 3/3: ArcGIS SDK (may take 10–20 min) ━━━")
        chk = subprocess.run(
            [_CONDA_BIN, 'run', '-n', 'arcgis_env', 'python', '-c',
             'import arcgis; print(arcgis.__version__)'],
            capture_output=True, text=True, timeout=60)
        if chk.returncode == 0 and chk.stdout.strip():
            plog(f"  ✓ ArcGIS SDK already installed (v{chk.stdout.strip()})")
        else:
            plog("  Running: conda install -c esri arcgis -y")
            proc = subprocess.Popen(
                [_CONDA_BIN, 'install', '-n', 'arcgis_env', '-c', 'esri', 'arcgis', '-y'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    plog(f"  {line}")
            proc.wait()
            if proc.returncode != 0:
                plog("  ✗ conda install failed — trying pip fallback…")
                r = subprocess.run(
                    [_CONDA_BIN, 'run', '-n', 'arcgis_env', 'pip', 'install', 'arcgis', '-q'],
                    capture_output=True, text=True, timeout=600)
                if r.returncode != 0:
                    plog(f"  ✗ pip also failed: {(r.stderr or '')[:200]}")
                    status.update({'running': False, 'error': True})
                    return
                plog("  ✓ ArcGIS SDK installed via pip")
            else:
                plog("  ✓ ArcGIS SDK installed via conda")

        plog("")
        plog("✅ Conda environment ready — proceed to Deploy.")
        status.update({'running': False, 'complete': True, 'error': False})
    except Exception as e:
        plog(f"✗ Fatal error: {e}")
        status.update({'running': False, 'error': True})


def _run_cot_fl_install():
    """Background thread: copy script, write config, generate cert, install service."""
    import shutil as _shutil, stat as _stat
    log    = _cot_fl_install_log
    status = _cot_fl_install_status

    def plog(msg):
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        log.append(entry)
        print(entry, flush=True)

    try:
        cfg      = _cot_fl_load_config()
        base_dir = os.path.dirname(os.path.abspath(__file__))
        src_py   = os.path.join(base_dir, 'modules', 'cot_featurelayer', 'python')
        src_svc  = os.path.join(base_dir, 'modules', 'cot_featurelayer', 'service-files')

        # Step 1: Copy script
        plog("━━━ Step 1/4: Copying script ━━━")
        os.makedirs(COT_FL_DIR, exist_ok=True)
        src = os.path.join(src_py, 'cot-to-feature-layer.py')
        dst = os.path.join(COT_FL_DIR, 'cot-to-feature-layer.py')
        if os.path.exists(src):
            _shutil.copy2(src, dst)
            plog("  ✓ cot-to-feature-layer.py")
        else:
            plog(f"  ✗ Source not found: {src}")
            status.update({'running': False, 'error': True})
            return

        # Step 2: Write config.json
        plog("")
        plog("━━━ Step 2/4: Writing config.json ━━━")
        config_path = os.path.join(COT_FL_DIR, 'config.json')
        config_data = {
            "tak_server": {
                "host":          (cfg.get('tak_host') or 'localhost').strip(),
                "port":          int(cfg.get('tak_port') or 8089),
                "tls":           bool(cfg.get('tak_tls', True)),
                "cert_path":     os.path.join(COT_FL_DIR, 'certs', 'cot-fl.p12'),
                "cert_password": (cfg.get('cert_password') or '').strip(),
                "ca_cert":       (cfg.get('ca_cert') or '').strip()
            },
            "feature_layer": {
                "url":        (cfg.get('layer_url') or '').strip(),
                "layer_type": (cfg.get('layer_type') or 'online').strip(),
                "username":   (cfg.get('esri_username') or '').strip(),
                "password":   (cfg.get('esri_password') or '').strip(),
                "portal_url": (cfg.get('portal_url') or '').strip()
            },
            "field_mapping": {
                "uid_field":      (cfg.get('uid_field') or 'tak_uid').strip(),
                "callsign_field": (cfg.get('callsign_field') or 'callsign').strip(),
                "type_field":     (cfg.get('type_field') or 'cot_type').strip(),
                "lat_field":      (cfg.get('lat_field') or 'latitude').strip(),
                "lon_field":      (cfg.get('lon_field') or 'longitude').strip(),
                "altitude_field": (cfg.get('altitude_field') or 'altitude').strip(),
                "time_field":     (cfg.get('time_field') or 'last_seen').strip(),
                "remarks_field":  (cfg.get('remarks_field') or 'remarks').strip()
            },
            "filter": {
                "cot_types":  [t.strip() for t in (cfg.get('cot_types') or '').split(',') if t.strip()],
                "uid_prefix": (cfg.get('uid_prefix') or '').strip()
            }
        }
        with open(config_path, 'w') as f:
            json.dump(config_data, f, indent=2)
        plog("  ✓ config.json written")

        # Step 3: Generate client cert if none exists
        cert_dir = os.path.join(COT_FL_DIR, 'certs')
        p12_path = os.path.join(cert_dir, 'cot-fl.p12')
        key_pem  = os.path.join(cert_dir, 'cot-fl-key.pem')
        cert_pem = os.path.join(cert_dir, 'cot-fl-cert.pem')
        plog("")
        plog("━━━ Step 3/4: Certificate ━━━")
        if not os.path.exists(p12_path):
            os.makedirs(cert_dir, exist_ok=True)
            r = subprocess.run(
                ['openssl', 'req', '-x509', '-newkey', 'rsa:4096',
                 '-keyout', key_pem, '-out', cert_pem,
                 '-days', '365', '-nodes', '-subj', '/CN=cot-fl/O=CoTFeatureLayer'],
                capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                plog(f"  ⚠ openssl failed: {r.stderr[:200]}")
            else:
                r2 = subprocess.run(
                    ['openssl', 'pkcs12', '-export',
                     '-out', p12_path, '-inkey', key_pem, '-in', cert_pem,
                     '-name', 'cot-fl', '-passout', 'pass:'],
                    capture_output=True, text=True, timeout=60)
                if r2.returncode == 0:
                    os.chmod(key_pem,  _stat.S_IRUSR | _stat.S_IWUSR)
                    os.chmod(p12_path, _stat.S_IRUSR | _stat.S_IWUSR)
                    plog("  ✓ Self-signed cert generated")
                    plog(f"    {p12_path}")
                    plog("  ⚠ Add certs/cot-fl-cert.pem to TAK Server trusted clients")
                else:
                    plog(f"  ⚠ .p12 bundle failed: {r2.stderr[:200]}")
        else:
            plog("  ✓ Existing cert found — skipping generation")

        # Step 4: Install systemd service
        plog("")
        plog("━━━ Step 4/4: systemd service ━━━")
        svc_src = os.path.join(src_svc, 'cot-featurelayer.service')
        svc_dst = f'/etc/systemd/system/{COT_FL_SERVICE}.service'
        if os.path.exists(svc_src):
            _shutil.copy2(svc_src, svc_dst)
            subprocess.run(['systemctl', 'daemon-reload'], capture_output=True, timeout=30)
            plog(f"  ✓ {COT_FL_SERVICE}.service installed")
            plog("  Service not auto-started — add TAK cert, configure, then click Start")
        else:
            plog(f"  ⚠ Service file not found: {svc_src}")

        plog("")
        plog("━━━ Deploy complete ━━━")
        plog("  Next: 1) Add certs/cot-fl-cert.pem to TAK Server trusted clients")
        plog("        2) Set Feature Layer URL + credentials on the Config tab, save")
        plog("        3) Click Start on the Service tab")
        status.update({'running': False, 'complete': True, 'error': False})

    except Exception as e:
        plog(f"✗ Fatal error: {e}")
        status.update({'running': False, 'error': True})


@cot_featurelayer_bp.route('/cot-featurelayer')
@login_required
def cot_fl_page():
    from app import detect_modules
    settings   = load_settings()
    modules    = detect_modules()
    mod        = modules.get('cot_featurelayer', {})
    cfg        = _cot_fl_load_config()
    svc_active = False
    if mod.get('installed'):
        r = subprocess.run(['systemctl', 'is-active', f'{COT_FL_SERVICE}.service'],
                           capture_output=True, text=True)
        svc_active = r.stdout.strip() == 'active'
    log_tail = ''
    log_path = '/var/log/cot-featurelayer.log'
    if os.path.exists(log_path):
        try:
            with open(log_path) as f:
                lines = f.readlines()
            log_tail = ''.join(lines[-50:])
        except Exception:
            pass
    cert_pem    = os.path.join(COT_FL_DIR, 'certs', 'cot-fl-cert.pem')
    cert_exists = os.path.exists(cert_pem)
    conda_ready = os.path.exists('/root/miniconda/envs/arcgis_env/bin/python')
    return make_response(render_template_string(COT_FL_TEMPLATE,
        settings=settings, mod=mod, cfg=cfg,
        svc_active=svc_active, log_tail=log_tail,
        cert_exists=cert_exists, cert_pem_path=cert_pem,
        conda_ready=conda_ready,
        install_dir=COT_FL_DIR, version=VERSION,
        deploying=_cot_fl_install_status.get('running', False),
        deploy_done=_cot_fl_install_status.get('complete', False),
        deploy_error=_cot_fl_install_status.get('error', False),
        conda_running=_cot_fl_conda_status.get('running', False),
        conda_done=_cot_fl_conda_status.get('complete', False),
        conda_error=_cot_fl_conda_status.get('error', False)))


@cot_featurelayer_bp.route('/api/cot-fl/conda/install', methods=['POST'])
@login_required
def cot_fl_conda_install():
    if _cot_fl_conda_status.get('running'):
        return jsonify({'error': 'Already running'}), 409
    _cot_fl_conda_log.clear()
    _cot_fl_conda_status.update({'running': True, 'complete': False, 'error': False})
    threading.Thread(target=_run_cot_fl_conda_install, daemon=True).start()
    return jsonify({'success': True})


@cot_featurelayer_bp.route('/api/cot-fl/conda/log')
@login_required
def cot_fl_conda_log_api():
    idx = request.args.get('index', 0, type=int)
    return jsonify({
        'entries': _cot_fl_conda_log[idx:],
        'total':   len(_cot_fl_conda_log),
        'running': _cot_fl_conda_status['running'],
        'complete':_cot_fl_conda_status['complete'],
        'error':   _cot_fl_conda_status['error'],
    })


@cot_featurelayer_bp.route('/api/cot-fl/install', methods=['POST'])
@login_required
def cot_fl_install():
    if _cot_fl_install_status.get('running'):
        return jsonify({'error': 'Installation already in progress'}), 409
    data = request.get_json(silent=True) or {}
    if data.get('config'):
        _cot_fl_save_config(data['config'])
    _cot_fl_install_log.clear()
    _cot_fl_install_status.update({'running': True, 'complete': False, 'error': False})
    threading.Thread(target=_run_cot_fl_install, daemon=True).start()
    return jsonify({'success': True})


@cot_featurelayer_bp.route('/api/cot-fl/install/log')
@login_required
def cot_fl_install_log():
    idx = request.args.get('index', 0, type=int)
    return jsonify({
        'entries': _cot_fl_install_log[idx:],
        'total':   len(_cot_fl_install_log),
        'running': _cot_fl_install_status['running'],
        'complete':_cot_fl_install_status['complete'],
        'error':   _cot_fl_install_status['error'],
    })


@cot_featurelayer_bp.route('/api/cot-fl/save-config', methods=['POST'])
@login_required
def cot_fl_save_config():
    data = request.get_json(silent=True) or {}
    cfg  = _cot_fl_load_config()
    for key in ['tak_host', 'tak_port', 'tak_tls', 'cert_password', 'ca_cert',
                'layer_url', 'layer_type', 'esri_username', 'esri_password', 'portal_url',
                'uid_field', 'callsign_field', 'type_field', 'lat_field', 'lon_field',
                'altitude_field', 'time_field', 'remarks_field',
                'cot_types', 'uid_prefix']:
        if key in data:
            cfg[key] = data[key]
    _cot_fl_save_config(cfg)
    # Patch live config.json if installed
    config_path = os.path.join(COT_FL_DIR, 'config.json')
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                existing = json.load(f)
            ts = existing.setdefault('tak_server', {})
            fl = existing.setdefault('feature_layer', {})
            fm = existing.setdefault('field_mapping', {})
            ft = existing.setdefault('filter', {})
            if cfg.get('tak_host'):      ts['host'] = cfg['tak_host'].strip()
            if cfg.get('tak_port'):      ts['port'] = int(cfg['tak_port'])
            if 'tak_tls' in cfg:         ts['tls']  = bool(cfg['tak_tls'])
            if cfg.get('layer_url'):     fl['url']  = cfg['layer_url'].strip()
            if cfg.get('layer_type'):    fl['layer_type'] = cfg['layer_type'].strip()
            if cfg.get('esri_username'): fl['username'] = cfg['esri_username'].strip()
            if cfg.get('esri_password'): fl['password'] = cfg['esri_password'].strip()
            if cfg.get('uid_field'):     fm['uid_field'] = cfg['uid_field'].strip()
            if cfg.get('cot_types') is not None:
                ft['cot_types'] = [t.strip() for t in cfg['cot_types'].split(',') if t.strip()]
            if cfg.get('uid_prefix') is not None:
                ft['uid_prefix'] = cfg['uid_prefix'].strip()
            with open(config_path, 'w') as f:
                json.dump(existing, f, indent=2)
        except Exception:
            pass
    return jsonify({'success': True})


@cot_featurelayer_bp.route('/api/cot-fl/service-status')
@login_required
def cot_fl_service_status():
    r  = subprocess.run(['systemctl', 'is-active', f'{COT_FL_SERVICE}.service'],
                        capture_output=True, text=True)
    st = r.stdout.strip() or 'unknown'
    return jsonify({'active': st == 'active', 'status': st})


@cot_featurelayer_bp.route('/api/cot-fl/service-control', methods=['POST'])
@login_required
def cot_fl_service_control():
    data   = request.get_json(silent=True) or {}
    action = (data.get('action') or '').strip()
    if action not in ('start', 'stop', 'restart'):
        return jsonify({'error': 'Invalid action'}), 400
    r = subprocess.run(['systemctl', action, f'{COT_FL_SERVICE}.service'],
                       capture_output=True, text=True, timeout=30)
    return jsonify({'success': r.returncode == 0, 'output': (r.stdout + r.stderr).strip()})


@cot_featurelayer_bp.route('/api/cot-fl/uninstall', methods=['POST'])
@login_required
def cot_fl_uninstall():
    import shutil as _shutil
    for cmd in ('stop', 'disable'):
        subprocess.run(['systemctl', cmd, f'{COT_FL_SERVICE}.service'],
                       capture_output=True, timeout=15)
    svc_dst = f'/etc/systemd/system/{COT_FL_SERVICE}.service'
    if os.path.exists(svc_dst):
        os.remove(svc_dst)
    subprocess.run(['systemctl', 'daemon-reload'], capture_output=True, timeout=30)
    if os.path.exists(COT_FL_DIR):
        _shutil.rmtree(COT_FL_DIR)
    return jsonify({'success': True})


COT_FL_TEMPLATE = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>CoT→Feature Layer — infra-TAK</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
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
.btn{display:inline-flex;align-items:center;gap:8px;padding:10px 20px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;border:none;transition:opacity .15s}
.btn:disabled{opacity:.45;cursor:not-allowed}
.btn-primary{background:var(--accent);color:#fff}.btn-success{background:var(--green);color:#fff}
.btn-ghost{background:rgba(255,255,255,.05);color:var(--text-secondary);border:1px solid var(--border)}
.btn-danger{background:var(--red);color:#fff}
.form-label{display:block;font-size:12px;font-weight:600;color:var(--text-secondary);margin-bottom:6px}
.form-input{width:100%;background:#0a0e1a;border:1px solid var(--border);border-radius:8px;padding:10px 14px;color:var(--text-primary);font-size:13px;font-family:inherit}
.form-input:focus{outline:none;border-color:var(--accent)}
.form-group{margin-bottom:14px}
.log-box{background:#070a12;border:1px solid var(--border);border-radius:8px;padding:16px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-dim);max-height:380px;overflow-y:auto;white-space:pre-wrap;line-height:1.6}
.tab-bar{display:flex;gap:0;border-bottom:1px solid var(--border);margin-bottom:20px}
.tab{padding:9px 18px;font-size:13px;font-weight:500;cursor:pointer;color:var(--text-dim);border-bottom:2px solid transparent;background:none;border-top:none;border-left:none;border-right:none;transition:all .15s}
.tab.active{color:var(--cyan);border-bottom-color:var(--cyan)}
.tab-panel{display:none}.tab-panel.active{display:block}
.hint{font-size:12px;color:var(--text-dim);margin-top:6px}
.status-pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;padding:4px 10px;border-radius:20px}
.pill-active{background:rgba(16,185,129,.12);color:var(--green);border:1px solid rgba(16,185,129,.2)}
.pill-inactive{background:rgba(234,179,8,.1);color:var(--yellow);border:1px solid rgba(234,179,8,.2)}
.dot{width:7px;height:7px;border-radius:50%;background:currentColor;flex-shrink:0}
.info-row{display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);font-size:13px}
.info-row:last-child{border-bottom:none}
.warn-card{background:rgba(234,179,8,.05);border:1px solid rgba(234,179,8,.25);border-radius:10px;padding:14px 18px;font-size:13px;color:var(--yellow);margin-bottom:16px}
.ok-card{background:rgba(16,185,129,.05);border:1px solid rgba(16,185,129,.2);border-radius:10px;padding:14px 18px;font-size:13px;color:var(--green);margin-bottom:16px}
.section-title{font-size:12px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.08em;margin:20px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--border)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:700px){.grid2{grid-template-columns:1fr}}
.step-badge{display:inline-block;background:rgba(59,130,246,.15);color:var(--accent);border-radius:20px;padding:2px 10px;font-size:11px;font-weight:600;margin-right:6px}
</style></head>
<body>
{{ sidebar_html }}
<div class="main">
  <div class="page-header">
    <h1>📡 CoT → Feature Layer</h1>
    <p>Connects to TAK Server, listens for incoming CoT events, and upserts each PLI into an Esri Feature Layer keyed by UID.</p>
  </div>

  <div class="tab-bar">
    <button class="tab active" id="tab-btn-deploy" onclick="showTab('deploy')">🚀 Deploy</button>
    <button class="tab" id="tab-btn-config" onclick="showTab('config')">⚙️ Config</button>
    <button class="tab" id="tab-btn-service" onclick="showTab('service');refreshStatus()">🟢 Service</button>
  </div>

  <!-- ════════════════════════════════════════ DEPLOY TAB ══ -->
  <div id="tab-deploy" class="tab-panel active">

    <!-- Step 1: Conda -->
    <div class="card">
      <div class="card-title"><span class="step-badge">Step 1</span>Conda + ArcGIS SDK</div>
      <div style="font-size:13px;color:var(--text-secondary);line-height:1.8;margin-bottom:14px">
        Installs Miniconda and the <code>arcgis</code> Python package into a shared <code>arcgis_env</code> environment.<br>
        <strong>Skip if already done</strong> — this environment is shared with the TAK-Esri module.
        This step can take <strong>10–20 minutes</strong>.
      </div>
      {% if conda_ready %}
      <div class="ok-card" style="margin-bottom:14px">✓ arcgis_env is ready at <code>/root/miniconda/envs/arcgis_env/</code></div>
      {% endif %}
      {% if conda_running %}
      <div id="conda-log-box" class="log-box" style="margin-bottom:14px">Waiting for log…</div>
      <button class="btn btn-ghost" disabled>⏳ Installing Conda…</button>
      {% elif conda_done %}
      <div id="conda-log-box" class="log-box" style="margin-bottom:14px"></div>
      <button id="conda-btn" class="btn btn-success" onclick="startConda()">✓ Done — Re-run</button>
      {% elif conda_error %}
      <div id="conda-log-box" class="log-box" style="margin-bottom:14px"></div>
      <button id="conda-btn" class="btn btn-danger" onclick="startConda()">✗ Failed — Retry</button>
      {% else %}
      <div id="conda-log-box" class="log-box" style="display:none;margin-bottom:14px"></div>
      <button id="conda-btn" class="btn {% if conda_ready %}btn-ghost{% else %}btn-primary{% endif %}" onclick="startConda()">
        🐍 {% if conda_ready %}Re-run Conda Setup{% else %}Install Conda + ArcGIS SDK{% endif %}
      </button>
      {% endif %}
    </div>

    <!-- Step 2: Deploy script + service -->
    <div class="card">
      <div class="card-title"><span class="step-badge">Step 2</span>Deploy Script &amp; Service</div>
      <div style="font-size:13px;color:var(--text-secondary);line-height:1.8;margin-bottom:14px">
        Copies the listener script, writes <code>config.json</code>, generates a self-signed client cert, and installs the systemd service.
        <div style="margin-top:8px">
          <div>📄 <strong>Script:</strong> cot-to-feature-layer.py</div>
          <div>🔒 <strong>Cert:</strong> certs/cot-fl.p12 (self-signed, skipped if exists)</div>
          <div>⚙️ <strong>Service:</strong> cot-featurelayer.service (not auto-started)</div>
        </div>
      </div>
      {% if not conda_ready %}
      <p class="hint" style="margin-bottom:14px;color:var(--yellow)">⚠ Complete Step 1 (Conda) before deploying.</p>
      {% endif %}
      {% if cert_exists %}
      <div class="ok-card" style="margin-bottom:14px">
        ✓ Client cert at <code>{{ cert_pem_path }}</code><br>
        <span style="font-size:12px;opacity:.8">Add this cert to TAK Server trusted clients before starting the service.</span>
      </div>
      {% endif %}
      {% if deploying %}
      <div id="deploy-log-box" class="log-box" style="margin-bottom:14px">Waiting for log…</div>
      <button class="btn btn-ghost" disabled>⏳ Deploying…</button>
      {% elif deploy_done %}
      <div id="deploy-log-box" class="log-box" style="margin-bottom:14px"></div>
      <button id="deploy-btn" class="btn btn-success" onclick="startDeploy()">✓ Deployed — Re-Deploy</button>
      {% elif deploy_error %}
      <div id="deploy-log-box" class="log-box" style="margin-bottom:14px"></div>
      <button id="deploy-btn" class="btn btn-danger" onclick="startDeploy()">✗ Failed — Retry</button>
      {% else %}
      <div id="deploy-log-box" class="log-box" style="display:none;margin-bottom:14px"></div>
      <button id="deploy-btn" class="btn btn-primary" onclick="startDeploy()" {% if not conda_ready %}disabled{% endif %}>🚀 Deploy</button>
      {% endif %}
    </div>

  </div>

  <!-- ════════════════════════════════════════ CONFIG TAB ══ -->
  <div id="tab-config" class="tab-panel">
    {% if not mod.installed %}
    <div class="warn-card">⚠ Deploy first, then configure.</div>
    {% endif %}
    <div class="card">

      <div class="section-title">TAK Server</div>
      <div class="grid2">
        <div class="form-group">
          <label class="form-label">Host</label>
          <input id="tak_host" class="form-input" type="text" placeholder="localhost" value="{{ cfg.tak_host or '' }}">
        </div>
        <div class="form-group">
          <label class="form-label">CoT Port</label>
          <input id="tak_port" class="form-input" type="number" placeholder="8089" value="{{ cfg.tak_port or '8089' }}">
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">TLS</label>
        <select id="tak_tls" class="form-input">
          <option value="1" {% if cfg.get('tak_tls', True) %}selected{% endif %}>Enabled (recommended)</option>
          <option value="0" {% if not cfg.get('tak_tls', True) %}selected{% endif %}>Disabled</option>
        </select>
      </div>
      <div class="grid2">
        <div class="form-group">
          <label class="form-label">P12 Cert Password <span style="font-weight:400;color:var(--text-dim)">(blank if none)</span></label>
          <input id="cert_password" class="form-input" type="password" value="{{ cfg.cert_password or '' }}">
        </div>
        <div class="form-group">
          <label class="form-label">CA Cert Path <span style="font-weight:400;color:var(--text-dim)">(optional)</span></label>
          <input id="ca_cert" class="form-input" type="text" placeholder="/opt/CoT-FeatureLayer/certs/takserver-ca.pem" value="{{ cfg.ca_cert or '' }}">
        </div>
      </div>

      <div class="section-title">ArcGIS Feature Layer</div>
      <div class="form-group">
        <label class="form-label">Feature Layer URL</label>
        <input id="layer_url" class="form-input" type="text" placeholder="https://services.arcgis.com/.../FeatureServer/0" value="{{ cfg.layer_url or '' }}">
        <p class="hint">The layer must have the field names defined below. Point geometry required.</p>
      </div>
      <div class="grid2">
        <div class="form-group">
          <label class="form-label">Layer Type</label>
          <select id="layer_type" class="form-input">
            <option value="online" {% if (cfg.get('layer_type','online'))=='online' %}selected{% endif %}>ArcGIS Online</option>
            <option value="enterprise" {% if cfg.get('layer_type')=='enterprise' %}selected{% endif %}>ArcGIS Enterprise</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Portal URL <span style="font-weight:400;color:var(--text-dim)">(Enterprise only, auto-derived if blank)</span></label>
          <input id="portal_url" class="form-input" type="text" placeholder="https://gis.myorg.com/portal" value="{{ cfg.portal_url or '' }}">
        </div>
      </div>
      <div class="grid2">
        <div class="form-group">
          <label class="form-label">Username</label>
          <input id="esri_username" class="form-input" type="text" value="{{ cfg.esri_username or '' }}">
        </div>
        <div class="form-group">
          <label class="form-label">Password</label>
          <input id="esri_password" class="form-input" type="password" value="{{ cfg.esri_password or '' }}">
        </div>
      </div>

      <div class="section-title">Field Mapping <span style="font-weight:400;font-size:11px;text-transform:none;letter-spacing:0">(names of fields in your Feature Layer)</span></div>
      <div class="grid2">
        <div class="form-group">
          <label class="form-label">UID Field <span style="font-weight:400;color:var(--text-dim)">(primary key)</span></label>
          <input id="uid_field" class="form-input" type="text" placeholder="tak_uid" value="{{ cfg.uid_field or '' }}">
        </div>
        <div class="form-group">
          <label class="form-label">Callsign Field</label>
          <input id="callsign_field" class="form-input" type="text" placeholder="callsign" value="{{ cfg.callsign_field or '' }}">
        </div>
      </div>
      <div class="grid2">
        <div class="form-group">
          <label class="form-label">CoT Type Field</label>
          <input id="type_field" class="form-input" type="text" placeholder="cot_type" value="{{ cfg.type_field or '' }}">
        </div>
        <div class="form-group">
          <label class="form-label">Last Seen Field <span style="font-weight:400;color:var(--text-dim)">(timestamp)</span></label>
          <input id="time_field" class="form-input" type="text" placeholder="last_seen" value="{{ cfg.time_field or '' }}">
        </div>
      </div>
      <div class="grid2">
        <div class="form-group">
          <label class="form-label">Latitude Field</label>
          <input id="lat_field" class="form-input" type="text" placeholder="latitude" value="{{ cfg.lat_field or '' }}">
        </div>
        <div class="form-group">
          <label class="form-label">Longitude Field</label>
          <input id="lon_field" class="form-input" type="text" placeholder="longitude" value="{{ cfg.lon_field or '' }}">
        </div>
      </div>
      <div class="grid2">
        <div class="form-group">
          <label class="form-label">Altitude Field</label>
          <input id="altitude_field" class="form-input" type="text" placeholder="altitude" value="{{ cfg.altitude_field or '' }}">
        </div>
        <div class="form-group">
          <label class="form-label">Remarks Field</label>
          <input id="remarks_field" class="form-input" type="text" placeholder="remarks" value="{{ cfg.remarks_field or '' }}">
        </div>
      </div>

      <div class="section-title">Filters <span style="font-weight:400;font-size:11px;text-transform:none;letter-spacing:0">(optional)</span></div>
      <div class="grid2">
        <div class="form-group">
          <label class="form-label">CoT Types <span style="font-weight:400;color:var(--text-dim)">(comma-separated, empty = all)</span></label>
          <input id="cot_types" class="form-input" type="text" placeholder="a-f-G,a-f-A" value="{{ cfg.cot_types or '' }}">
        </div>
        <div class="form-group">
          <label class="form-label">UID Prefix Filter <span style="font-weight:400;color:var(--text-dim)">(empty = all)</span></label>
          <input id="uid_prefix" class="form-input" type="text" placeholder="ANDROID-" value="{{ cfg.uid_prefix or '' }}">
        </div>
      </div>

      <div style="display:flex;align-items:center;gap:12px;margin-top:8px">
        <button class="btn btn-success" onclick="saveConfig()">💾 Save Config</button>
        <span id="save-msg" style="font-size:12px"></span>
      </div>
      <p class="hint" style="margin-top:10px">Restart the service after saving to apply changes.</p>
    </div>
  </div>

  <!-- ════════════════════════════════════════ SERVICE TAB ══ -->
  <div id="tab-service" class="tab-panel">
    {% if not mod.installed %}
    <div class="warn-card">⚠ Deploy the module first.</div>
    {% else %}
    <div class="card">
      <div class="card-title">Service Status</div>
      <div class="info-row">
        <span>cot-featurelayer.service</span>
        <span id="svc-badge" class="status-pill {% if svc_active %}pill-active{% else %}pill-inactive{% endif %}">
          <span class="dot"></span><span id="svc-status-text">{% if svc_active %}active{% else %}inactive{% endif %}</span>
        </span>
      </div>
      <div class="info-row">
        <span>Log file</span>
        <span style="font-size:11px;font-family:'JetBrains Mono',monospace;color:var(--text-dim)">/var/log/cot-featurelayer.log</span>
      </div>
      <div class="info-row">
        <span>Python</span>
        <span style="font-size:11px;font-family:'JetBrains Mono',monospace;color:var(--text-dim)">/root/miniconda/envs/arcgis_env/bin/python</span>
      </div>
      <div style="display:flex;gap:10px;margin-top:16px;flex-wrap:wrap">
        <button class="btn btn-success" onclick="svcControl('start')">▶ Start</button>
        <button class="btn btn-ghost" onclick="svcControl('stop')">■ Stop</button>
        <button class="btn btn-ghost" onclick="svcControl('restart')">↺ Restart</button>
        <span id="svc-ctrl-msg" style="font-size:12px;align-self:center"></span>
      </div>
    </div>

    {% if log_tail %}
    <div class="card">
      <div class="card-title">Log (last 50 lines)</div>
      <div class="log-box">{{ log_tail }}</div>
    </div>
    {% endif %}

    <div class="card" style="border-color:rgba(239,68,68,.25)">
      <div class="card-title" style="color:var(--red)">Danger Zone</div>
      <p style="font-size:13px;color:var(--text-secondary);margin-bottom:16px">
        Stops the service, removes <code>{{ install_dir }}</code>, and unregisters the systemd unit. Config in infra-TAK settings is preserved. The shared Conda environment is <strong>not</strong> removed.
      </p>
      <button class="btn btn-danger" onclick="uninstall()">🗑 Uninstall</button>
      <span id="uninstall-msg" style="font-size:12px;margin-left:12px"></span>
    </div>
    {% endif %}
  </div>

</div>
<script>
var _logIdx=0,_logPoll=null,_condaLogIdx=0,_condaLogPoll=null;

function showTab(name){
  document.querySelectorAll('.tab-panel').forEach(function(p){p.classList.remove('active');});
  document.querySelectorAll('.tab').forEach(function(b){b.classList.remove('active');});
  var p=document.getElementById('tab-'+name);
  var b=document.getElementById('tab-btn-'+name);
  if(p)p.classList.add('active');
  if(b)b.classList.add('active');
}

function startConda(){
  var btn=document.getElementById('conda-btn');
  var box=document.getElementById('conda-log-box');
  if(btn){btn.disabled=true;btn.textContent='Installing…';}
  if(box){box.style.display='block';box.textContent='';}
  _condaLogIdx=0;
  fetch('/api/cot-fl/conda/install',{method:'POST',credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(d.error){if(btn){btn.disabled=false;btn.textContent='✗ Error';btn.className='btn btn-danger';}}
      else{_condaLogPoll=setInterval(pollCondaLog,1500);}
    }).catch(function(){if(btn){btn.disabled=false;btn.textContent='✗ Failed';}});
}

function pollCondaLog(){
  fetch('/api/cot-fl/conda/log?index='+_condaLogIdx,{credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      var box=document.getElementById('conda-log-box');
      if(box&&d.entries&&d.entries.length>0){box.textContent+=(box.textContent?'\\n':'')+d.entries.join('\\n');box.scrollTop=box.scrollHeight;}
      _condaLogIdx=d.total;
      var btn=document.getElementById('conda-btn');
      if(!d.running){
        clearInterval(_condaLogPoll);_condaLogPoll=null;
        if(d.error){if(btn){btn.disabled=false;btn.textContent='✗ Failed — Retry';btn.className='btn btn-danger';}}
        else if(d.complete){if(btn){btn.disabled=false;btn.textContent='✓ Done — Re-run';btn.className='btn btn-success';}
          var db=document.getElementById('deploy-btn');if(db)db.disabled=false;}
      }
    }).catch(function(){});
}

function startDeploy(){
  var btn=document.getElementById('deploy-btn');
  var box=document.getElementById('deploy-log-box');
  if(btn){btn.disabled=true;btn.textContent='Deploying…';}
  if(box){box.style.display='block';box.textContent='';}
  _logIdx=0;
  fetch('/api/cot-fl/install',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(d.error){if(btn){btn.disabled=false;btn.textContent='✗ Error — Retry';btn.className='btn btn-danger';}}
      else{_logPoll=setInterval(pollDeployLog,1200);}
    }).catch(function(){if(btn){btn.disabled=false;btn.textContent='✗ Failed';btn.className='btn btn-danger';}});
}

function pollDeployLog(){
  fetch('/api/cot-fl/install/log?index='+_logIdx,{credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      var box=document.getElementById('deploy-log-box');
      if(box&&d.entries&&d.entries.length>0){box.textContent+=(box.textContent?'\\n':'')+d.entries.join('\\n');box.scrollTop=box.scrollHeight;}
      _logIdx=d.total;
      var btn=document.getElementById('deploy-btn');
      if(!d.running){
        clearInterval(_logPoll);_logPoll=null;
        if(d.error){if(btn){btn.disabled=false;btn.textContent='✗ Failed — Retry';btn.className='btn btn-danger';}}
        else if(d.complete){if(btn){btn.disabled=false;btn.textContent='✓ Deployed — Re-Deploy';btn.className='btn btn-success';}}
      }
    }).catch(function(){});
}

function saveConfig(){
  var msg=document.getElementById('save-msg');
  if(msg){msg.textContent='Saving…';msg.style.color='var(--text-dim)';}
  var payload={
    tak_host:document.getElementById('tak_host').value,
    tak_port:parseInt(document.getElementById('tak_port').value)||8089,
    tak_tls:document.getElementById('tak_tls').value==='1',
    cert_password:document.getElementById('cert_password').value,
    ca_cert:document.getElementById('ca_cert').value,
    layer_url:document.getElementById('layer_url').value,
    layer_type:document.getElementById('layer_type').value,
    esri_username:document.getElementById('esri_username').value,
    esri_password:document.getElementById('esri_password').value,
    portal_url:document.getElementById('portal_url').value,
    uid_field:document.getElementById('uid_field').value,
    callsign_field:document.getElementById('callsign_field').value,
    type_field:document.getElementById('type_field').value,
    lat_field:document.getElementById('lat_field').value,
    lon_field:document.getElementById('lon_field').value,
    altitude_field:document.getElementById('altitude_field').value,
    time_field:document.getElementById('time_field').value,
    remarks_field:document.getElementById('remarks_field').value,
    cot_types:document.getElementById('cot_types').value,
    uid_prefix:document.getElementById('uid_prefix').value
  };
  fetch('/api/cot-fl/save-config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(!msg)return;
      if(d.success){msg.textContent='✓ Saved';msg.style.color='var(--green)';setTimeout(function(){msg.textContent='';},2500);}
      else{msg.textContent='✗ Error';msg.style.color='var(--red)';}
    }).catch(function(){if(msg){msg.textContent='Request failed';msg.style.color='var(--red)';}});
}

function refreshStatus(){
  fetch('/api/cot-fl/service-status',{credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      var badge=document.getElementById('svc-badge');
      var txt=document.getElementById('svc-status-text');
      if(!badge)return;
      badge.className='status-pill '+(d.active?'pill-active':'pill-inactive');
      if(txt)txt.textContent=d.status||'unknown';
    }).catch(function(){});
}

function svcControl(action){
  var msg=document.getElementById('svc-ctrl-msg');
  if(msg){msg.textContent=action+'ing…';msg.style.color='var(--text-dim)';}
  fetch('/api/cot-fl/service-control',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:action}),credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(msg){msg.textContent=d.success?'✓ Done':'✗ Failed';msg.style.color=d.success?'var(--green)':'var(--red)';setTimeout(function(){msg.textContent='';},2500);}
      setTimeout(refreshStatus,800);
    }).catch(function(){if(msg){msg.textContent='Request failed';msg.style.color='var(--red)';}});
}

function uninstall(){
  if(!confirm('Remove CoT-FeatureLayer? Deletes {{ install_dir }} and unregisters the service. Conda env is kept.'))return;
  var msg=document.getElementById('uninstall-msg');
  if(msg){msg.textContent='Uninstalling…';msg.style.color='var(--text-dim)';}
  fetch('/api/cot-fl/uninstall',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(d.success){if(msg){msg.textContent='✓ Removed';msg.style.color='var(--green)';}setTimeout(function(){location.href='/cot-featurelayer';},1200);}
      else{if(msg){msg.textContent='✗ Failed';msg.style.color='var(--red)';}}
    }).catch(function(){if(msg){msg.textContent='Request failed';msg.style.color='var(--red)';}});
}

{% if deploying %}
_logPoll=setInterval(pollDeployLog,1200);
{% endif %}
{% if conda_running %}
_condaLogPoll=setInterval(pollCondaLog,1500);
{% endif %}
</script>
</body></html>'''


