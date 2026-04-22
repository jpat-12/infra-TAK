from flask import Blueprint, request, jsonify, render_template_string, make_response
import os, json, subprocess, threading, html, shutil, re
from datetime import datetime
from routes.helpers import login_required, load_settings, save_settings, VERSION

esri_tak_sync_bp = Blueprint('esri_tak_sync', __name__)

# ── Esri-TAKServer-Sync ───────────────────────────────────────────────────────
ESRI_TAK_SYNC_DIR     = '/opt/Esri-TAKServer-Sync'
ESRI_TAK_SYNC_SERVICE = 'feature-layer-to-cot'
_esri_tak_sync_install_log    = []
_esri_tak_sync_install_status = {'running': False, 'complete': False, 'error': False}
_esri_tak_sync_cert_log    = []
_esri_tak_sync_cert_status = {'running': False, 'complete': False, 'error': False}


def _esri_tak_sync_load_config():
    s = load_settings()
    return s.get('esri_takserver_sync', {})


def _esri_tak_sync_save_config(cfg):
    s = load_settings()
    s['esri_takserver_sync'] = cfg
    save_settings(s)


def _run_esri_tak_sync_install():
    import shutil as _shutil, stat as _stat
    log    = _esri_tak_sync_install_log
    status = _esri_tak_sync_install_status

    def plog(msg):
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        log.append(entry)
        print(entry, flush=True)

    try:
        cfg      = _esri_tak_sync_load_config()
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src_py   = os.path.join(base_dir, 'modules', 'esri_takserver_sync', 'python')
        src_svc  = os.path.join(base_dir, 'modules', 'esri_takserver_sync', 'service-files')

        # Step 1: pip install requests
        plog("━━━ Step 1/6: Installing Python dependencies ━━━")
        r = subprocess.run(['pip3', 'install', 'requests'],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            plog(f"  ⚠ pip3 returned {r.returncode}: {(r.stderr or r.stdout or '')[:300]}")
        else:
            plog("  ✓ requests installed")

        # Step 2: Copy scripts
        plog("")
        plog("━━━ Step 2/6: Copying scripts ━━━")
        os.makedirs(ESRI_TAK_SYNC_DIR, exist_ok=True)
        for fname in ('feature-layer-to-cot.py', 'setup-cert.py'):
            src = os.path.join(src_py, fname)
            dst = os.path.join(ESRI_TAK_SYNC_DIR, fname)
            if os.path.exists(src):
                _shutil.copy2(src, dst)
                plog(f"  ✓ {fname}")
            else:
                plog(f"  ⚠ Not found: {src}")

        # Step 3: Write config.json
        plog("")
        plog("━━━ Step 3/6: Writing config.json ━━━")
        config_path = os.path.join(ESRI_TAK_SYNC_DIR, 'config.json')
        auth_mode = (cfg.get('tak_auth_mode') or 'cert').strip()
        default_port = {'cert': 8089, 'plain': 8087, 'rest': 8443}.get(auth_mode, 8089)
        config_data = {
            "tak_server": {
                "host":          (cfg.get('tak_host') or 'localhost').strip(),
                "port":          int(cfg.get('tak_port') or default_port),
                "auth_mode":     auth_mode,
                "username":      (cfg.get('tak_username') or '').strip(),
                "password":      (cfg.get('tak_password') or '').strip(),
                "cert_path":     os.path.join(ESRI_TAK_SYNC_DIR, 'certs', 'esri-push.p12'),
                "cert_password": "atakatak",
                "ca_cert":       "",
                "cert_file":     (cfg.get('cert_file') or '').strip(),
                "key_file":      (cfg.get('key_file') or '').strip()
            },
            "feature_layer": {
                "url":           (cfg.get('layer_url') or '').strip(),
                "public":        bool(cfg.get('layer_public', True)),
                "layer_type":    (cfg.get('layer_type') or 'online').strip(),
                "username":      (cfg.get('esri_username') or '').strip(),
                "password":      (cfg.get('esri_password') or '').strip(),
                "portal_url":    (cfg.get('portal_url') or '').strip(),
                "poll_interval": int(cfg.get('poll_interval') or 30),
                "page_size":     int(cfg.get('page_size') or 1000)
            },
            "field_mapping": {
                "lat":            (cfg.get('lat_field') or '').strip(),
                "lon":            (cfg.get('lon_field') or '').strip(),
                "uid_field":      (cfg.get('uid_field') or 'OBJECTID').strip(),
                "uid_prefix":     (cfg.get('uid_prefix') or 'EsriSync').strip(),
                "callsign_field": (cfg.get('callsign_field') or '').strip(),
                "cot_type":       (cfg.get('cot_type') or 'a-f-G').strip(),
                "altitude_field": (cfg.get('altitude_field') or '').strip(),
                "remarks_fields": [f.strip() for f in (cfg.get('remarks_fields') or '').split(',') if f.strip()]
            },
            "cot": {
                "stale_minutes": int(cfg.get('stale_minutes') or 5),
                "how":           (cfg.get('cot_how') or 'm-g').strip()
            },
            "delta": {
                "enabled":     bool(cfg.get('delta_enabled', False)),
                "track_field": (cfg.get('delta_field') or 'EditDate').strip()
            },
            "icon_mapping": {
                "enabled":             bool(cfg.get('icon_enabled', False)),
                "column":              (cfg.get('icon_column') or '').strip(),
                "default_iconsetpath": (cfg.get('icon_default_path') or '').strip(),
                "map":                 cfg.get('icon_map') or {}
            }
        }
        with open(config_path, 'w') as f:
            json.dump(config_data, f, indent=2)
        plog("  ✓ config.json written")

        # Step 4: Generate self-signed cert if none exists
        cert_dir = os.path.join(ESRI_TAK_SYNC_DIR, 'certs')
        p12_path = os.path.join(cert_dir, 'esri-push.p12')
        key_pem  = os.path.join(cert_dir, 'esri-push-key.pem')
        cert_pem = os.path.join(cert_dir, 'esri-push-cert.pem')
        plog("")
        plog("━━━ Step 4/6: Certificate ━━━")
        if not os.path.exists(p12_path):
            os.makedirs(cert_dir, exist_ok=True)
            r = subprocess.run(
                ['openssl', 'req', '-x509', '-newkey', 'rsa:4096',
                 '-keyout', key_pem, '-out', cert_pem,
                 '-days', '365', '-nodes', '-subj', '/CN=esri-push/O=EsriTAKSync'],
                capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                plog(f"  ⚠ openssl failed: {r.stderr[:200]}")
            else:
                r2 = subprocess.run(
                    ['openssl', 'pkcs12', '-export',
                     '-out', p12_path, '-inkey', key_pem, '-in', cert_pem,
                     '-name', 'esri-push', '-passout', 'pass:'],
                    capture_output=True, text=True, timeout=60)
                if r2.returncode == 0:
                    os.chmod(key_pem,  _stat.S_IRUSR | _stat.S_IWUSR)
                    os.chmod(p12_path, _stat.S_IRUSR | _stat.S_IWUSR)
                    plog("  ✓ Self-signed cert generated")
                    plog(f"    {p12_path}")
                    plog("  ⚠ Add certs/esri-push-cert.pem to TAK Server trusted clients")
                else:
                    plog(f"  ⚠ .p12 bundle failed: {r2.stderr[:200]}")
        else:
            plog(f"  ✓ Existing cert found — skipping generation")

        # Step 5: Install systemd service
        plog("")
        plog("━━━ Step 5/6: systemd service ━━━")
        svc_src = os.path.join(src_svc, 'feature-layer-to-cot.service')
        svc_dst = '/etc/systemd/system/feature-layer-to-cot.service'
        if os.path.exists(svc_src):
            _shutil.copy2(svc_src, svc_dst)
            subprocess.run(['systemctl', 'daemon-reload'], capture_output=True, timeout=30)
            plog("  ✓ feature-layer-to-cot.service installed")
            plog("  Service not auto-started — configure TAK cert, then click Start")
        else:
            plog(f"  ⚠ Service file not found: {svc_src}")

        # Step 6: Copy bundled iconsets
        plog("")
        plog("━━━ Step 6/6: Bundled Iconsets ━━━")
        icons_dst = os.path.join(ESRI_TAK_SYNC_DIR, 'icons')
        os.makedirs(icons_dst, exist_ok=True)
        src_icons = os.path.join(base_dir, 'modules', 'esri_takserver_sync', 'icons')
        if os.path.isdir(src_icons):
            for zf in os.listdir(src_icons):
                if zf.endswith('.zip'):
                    _shutil.copy2(os.path.join(src_icons, zf), os.path.join(icons_dst, zf))
                    plog(f"  ✓ {zf}")
        else:
            plog("  (no bundled iconsets found)")

        plog("")
        plog("━━━ Install complete ━━━")
        plog("  Next: 1) Add certs/esri-push-cert.pem to TAK Server trusted clients")
        plog("        2) Enter Feature Layer URL on the Config tab, save")
        plog("        3) Click Start on the Service tab")
        status.update({'running': False, 'complete': True, 'error': False})

    except Exception as e:
        plog(f"✗ Fatal error: {e}")
        status.update({'running': False, 'error': True})


def _run_esri_tak_sync_cert_setup(mode, password, cert_name, group):
    import shutil as _shutil
    log    = _esri_tak_sync_cert_log
    status = _esri_tak_sync_cert_status
    tak_dir   = '/opt/tak'
    certs_dir = os.path.join(ESRI_TAK_SYNC_DIR, 'certs')

    def plog(msg):
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        log.append(entry)
        print(entry, flush=True)

    def extract_pem(in_path, out_path, pass_arg, pem_type):
        """Extract cert or key PEM from p12. Tries -legacy first (TAK Server uses RC2-40-CBC)."""
        if pem_type == 'cert':
            extra = ['-clcerts', '-nokeys']
        else:
            extra = ['-nocerts', '-nodes']
        for flags in (['-legacy'], []):
            cmd = ['openssl', 'pkcs12'] + flags + ['-in', in_path] + extra + ['-out', out_path, '-passin', pass_arg]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                return True, ''
        return False, (r.stderr or '')[:300]

    try:
        os.makedirs(certs_dir, exist_ok=True)
        p12_path  = os.path.join(certs_dir, f'{cert_name}.p12')
        cert_pem  = os.path.join(certs_dir, f'{cert_name}-cert.pem')
        key_pem   = os.path.join(certs_dir, f'{cert_name}-key.pem')
        pass_arg  = f'pass:{password}' if password else 'pass:'
        utils_jar = os.path.join(tak_dir, 'utils', 'UserManager.jar')

        if mode == 'local':
            # ── Step 1/3: makeCert.sh ─────────────────────────────────────────
            plog('━━━ Step 1/3: Generating cert with makeCert.sh ━━━')
            certs_tak_dir = os.path.join(tak_dir, 'certs')
            cmd = f'echo "y" | ./makeCert.sh client {cert_name}'
            plog(f'  Running: {cmd}')
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                               timeout=120, cwd=certs_tak_dir)
            output = (r.stdout or '') + (r.stderr or '')
            for line in output.strip().splitlines():
                if line.strip():
                    plog(f'  {line}')
            if r.returncode != 0:
                plog(f'  ✗ makeCert.sh failed (exit {r.returncode})')
                status.update({'running': False, 'error': True}); return
            p12_src = os.path.join(certs_tak_dir, 'files', f'{cert_name}.p12')
            pem_src = os.path.join(certs_tak_dir, 'files', f'{cert_name}.pem')
            if not os.path.exists(p12_src):
                plog(f'  ✗ Expected .p12 not found at {p12_src}')
                status.update({'running': False, 'error': True}); return
            plog(f'  ✓ {p12_src}')

            # ── Step 2/3: Group enrollment ────────────────────────────────────
            plog('')
            plog(f'━━━ Step 2/3: Enrolling cert in group "{group}" ━━━')
            if os.path.exists(utils_jar) and os.path.exists(pem_src):
                r = subprocess.run(
                    ['sudo', '-E', '-u', 'tak', 'java', '-jar', utils_jar,
                     'certmod', '-g', group, pem_src],
                    capture_output=True, text=True, timeout=30)
                output = ((r.stdout or '') + (r.stderr or '')).strip()
                for line in output.splitlines():
                    if line.strip(): plog(f'  {line}')
                if r.returncode != 0:
                    plog(f'  ✗ Group enrollment failed (exit {r.returncode})')
                    plog(f'  Make sure TAK Server is running and the group name is correct.')
                    status.update({'running': False, 'error': True}); return
                plog(f'  ✓ Cert enrolled in group "{group}"')
            elif not os.path.exists(utils_jar):
                plog(f'  ⚠ UserManager.jar not found — enroll manually in TAK Admin UI')
            else:
                plog(f'  ⚠ {pem_src} not found — enroll manually in TAK Admin UI')

            # ── Step 3/3: Copy p12 + extract PEMs ────────────────────────────
            _shutil.copy2(p12_src, p12_path)
            os.chmod(p12_path, 0o600)
            plog('')
            plog('━━━ Step 3/3: Extracting PEM files ━━━')

        else:
            # ── Upload mode: p12 already saved by the upload route ────────────
            plog('━━━ Step 1/2: Extracting PEM files from uploaded .p12 ━━━')
            if not os.path.exists(p12_path):
                plog(f'  ✗ .p12 not found at {p12_path} — upload may have failed')
                status.update({'running': False, 'error': True}); return

        # ── Extract cert PEM (both modes) ─────────────────────────────────────
        ok, err = extract_pem(p12_path, cert_pem, pass_arg, 'cert')
        if not ok:
            plog(f'  ✗ Failed to extract cert PEM: {err}')
            plog(f'  Check that the P12 password is correct (default: atakatak).')
            status.update({'running': False, 'error': True}); return
        plog(f'  ✓ {cert_pem}')

        # ── Extract key PEM (both modes) ──────────────────────────────────────
        ok, err = extract_pem(p12_path, key_pem, pass_arg, 'key')
        if not ok:
            plog(f'  ✗ Failed to extract key PEM: {err}')
            status.update({'running': False, 'error': True}); return
        os.chmod(key_pem, 0o600)
        plog(f'  ✓ {key_pem}')

        if mode == 'upload':
            # ── Step 2/2: Group enrollment (upload mode) ──────────────────────
            plog('')
            plog(f'━━━ Step 2/2: Enrolling cert in group "{group}" ━━━')
            if os.path.exists(utils_jar):
                r = subprocess.run(
                    ['sudo', '-E', '-u', 'tak', 'java', '-jar', utils_jar,
                     'certmod', '-g', group, cert_pem],
                    capture_output=True, text=True, timeout=30)
                output = ((r.stdout or '') + (r.stderr or '')).strip()
                for line in output.splitlines():
                    if line.strip(): plog(f'  {line}')
                if r.returncode != 0:
                    plog(f'  ✗ Group enrollment failed (exit {r.returncode})')
                    plog(f'  This cert may not be signed by this TAK Server\'s CA.')
                    plog(f'  Try generating a new cert instead of uploading.')
                    status.update({'running': False, 'error': True}); return
                plog(f'  ✓ Cert enrolled in group "{group}"')
            else:
                plog(f'  ⚠ UserManager.jar not found — enroll manually in TAK Admin UI')

        # ── Save config ───────────────────────────────────────────────────────
        cfg = _esri_tak_sync_load_config()
        cfg['cert_password'] = password
        cfg['tak_group']     = group
        _esri_tak_sync_save_config(cfg)
        deployed = os.path.join(ESRI_TAK_SYNC_DIR, 'config.json')
        if os.path.exists(deployed):
            try:
                with open(deployed) as fh: dcfg = json.load(fh)
                dcfg.setdefault('tak_server', {})
                dcfg['tak_server']['cert_path']     = p12_path
                dcfg['tak_server']['cert_password'] = password
                with open(deployed, 'w') as fh: json.dump(dcfg, fh, indent=2)
            except Exception: pass

        plog('')
        plog('━━━ Cert setup complete ━━━')
        plog(f'  .p12  : {p12_path}')
        plog(f'  cert  : {cert_pem}')
        plog(f'  key   : {key_pem}')
        plog(f'  group : {group}')
        plog('  Restart the service to apply the new cert.')
        status.update({'running': False, 'complete': True, 'error': False})

    except Exception as e:
        plog(f'✗ Fatal: {e}')
        status.update({'running': False, 'error': True})


@esri_tak_sync_bp.route('/api/esri-tak-sync/setup-cert', methods=['POST'])
@login_required
def esri_tak_sync_setup_cert():
    data      = request.get_json(silent=True) or {}
    password  = data.get('password', 'atakatak')
    cert_name = (data.get('cert_name') or 'esri-push').strip()
    group     = (data.get('group') or '__ANON__').strip() or '__ANON__'
    if not os.path.isdir('/opt/tak'):
        return jsonify({'success': False, 'error': 'TAK Server not found at /opt/tak'}), 400
    if _esri_tak_sync_cert_status.get('running'):
        return jsonify({'error': 'Already running'}), 409
    _esri_tak_sync_cert_log.clear()
    _esri_tak_sync_cert_status.update({'running': True, 'complete': False, 'error': False})
    threading.Thread(target=_run_esri_tak_sync_cert_setup,
                     args=('local', password, cert_name, group), daemon=True).start()
    return jsonify({'success': True})


@esri_tak_sync_bp.route('/api/esri-tak-sync/setup-cert/upload', methods=['POST'])
@login_required
def esri_tak_sync_cert_upload():
    f         = request.files.get('file')
    password  = request.form.get('password', 'atakatak')
    cert_name = (request.form.get('cert_name') or 'esri-push').strip()
    group     = (request.form.get('group') or '__ANON__').strip() or '__ANON__'
    if not f or not f.filename.lower().endswith('.p12'):
        return jsonify({'success': False, 'error': 'Upload a .p12 file'}), 400
    if _esri_tak_sync_cert_status.get('running'):
        return jsonify({'error': 'Already running'}), 409
    certs_dir = os.path.join(ESRI_TAK_SYNC_DIR, 'certs')
    os.makedirs(certs_dir, exist_ok=True)
    save_path = os.path.join(certs_dir, f'{cert_name}.p12')
    f.save(save_path)
    os.chmod(save_path, 0o600)
    _esri_tak_sync_cert_log.clear()
    _esri_tak_sync_cert_status.update({'running': True, 'complete': False, 'error': False})
    threading.Thread(target=_run_esri_tak_sync_cert_setup,
                     args=('upload', password, cert_name, group), daemon=True).start()
    return jsonify({'success': True})


@esri_tak_sync_bp.route('/api/esri-tak-sync/setup-cert/log')
@login_required
def esri_tak_sync_cert_log_route():
    idx = request.args.get('index', 0, type=int)
    return jsonify({
        'entries': _esri_tak_sync_cert_log[idx:],
        'total':   len(_esri_tak_sync_cert_log),
        'running': _esri_tak_sync_cert_status['running'],
        'complete':_esri_tak_sync_cert_status['complete'],
        'error':   _esri_tak_sync_cert_status['error'],
    })


@esri_tak_sync_bp.route('/api/esri-tak-sync/enroll-cert-group', methods=['POST'])
@login_required
def esri_tak_sync_enroll_cert_group():
    """Add the esri-push cert to a TAK Server group via UserManager.jar certmod -g."""
    data  = request.get_json(silent=True) or {}
    group = (data.get('group') or '__ANON__').strip()
    if not group:
        return jsonify({'success': False, 'error': 'Group name is required'}), 400
    if not os.path.isdir('/opt/tak'):
        return jsonify({'success': False, 'error': 'TAK Server not found at /opt/tak'}), 400

    # The pem file is in /opt/tak/certs/files/ (not our copy)
    pem_path  = '/opt/tak/certs/files/esri-push.pem'
    utils_jar = '/opt/tak/utils/UserManager.jar'

    if not os.path.exists(pem_path):
        return jsonify({'success': False, 'error': f'PEM not found at {pem_path} — generate the cert first'}), 400
    if not os.path.exists(utils_jar):
        return jsonify({'success': False, 'error': f'UserManager.jar not found at {utils_jar}'}), 400

    try:
        r = subprocess.run(
            ['sudo', '-E', '-u', 'tak', 'java', '-jar', utils_jar,
             'certmod', '-g', group, pem_path],
            capture_output=True, text=True, timeout=30
        )
        output = (r.stdout or '') + (r.stderr or '')
        if r.returncode != 0:
            return jsonify({'success': False, 'error': output[:400] or f'Exit {r.returncode}'}), 500
        # Save group to settings so it persists
        cfg = _esri_tak_sync_load_config()
        cfg['tak_group'] = group
        _esri_tak_sync_save_config(cfg)
        return jsonify({'success': True, 'output': output[:400]})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@esri_tak_sync_bp.route('/esri-tak-sync')
@login_required
def esri_tak_sync_page():
    from app import detect_modules
    settings   = load_settings()
    modules    = detect_modules()
    mod        = modules.get('esri_takserver_sync', {})
    cfg        = _esri_tak_sync_load_config()
    svc_active = False
    if mod.get('installed'):
        r = subprocess.run(['systemctl', 'is-active', 'feature-layer-to-cot.service'],
                           capture_output=True, text=True)
        svc_active = r.stdout.strip() == 'active'
    log_tail = ''
    log_path = '/var/log/esri-takserver-sync-feature-layer-to-cot.log'
    if os.path.exists(log_path):
        try:
            with open(log_path) as f:
                lines = f.readlines()
            log_tail = ''.join(lines[-50:])
        except Exception:
            pass
    cert_pem = os.path.join(ESRI_TAK_SYNC_DIR, 'certs', 'esri-push-cert.pem')
    cert_exists = os.path.exists(cert_pem)
    tak_local   = os.path.isdir('/opt/tak')
    return make_response(render_template_string(ESRI_TAK_SYNC_TEMPLATE,
        settings=settings, mod=mod, cfg=cfg,
        svc_active=svc_active, log_tail=log_tail,
        cert_exists=cert_exists, cert_pem_path=cert_pem,
        install_dir=ESRI_TAK_SYNC_DIR, version=VERSION,
        tak_local=tak_local,
        deploying=_esri_tak_sync_install_status.get('running', False),
        deploy_done=_esri_tak_sync_install_status.get('complete', False),
        deploy_error=_esri_tak_sync_install_status.get('error', False)))


@esri_tak_sync_bp.route('/api/esri-tak-sync/save-config', methods=['POST'])
@login_required
def esri_tak_sync_save_config():
    data = request.get_json(silent=True) or {}
    cfg  = _esri_tak_sync_load_config()
    for key in ['tak_host', 'tak_port', 'tak_auth_mode', 'tak_username', 'tak_password',
                'tak_cert_name', 'tak_group', 'cert_file', 'key_file', 'output_file',
                'layer_url', 'layer_public', 'layer_type', 'esri_username',
                'esri_password', 'portal_url', 'poll_interval', 'page_size',
                'lat_field', 'lon_field', 'uid_field', 'uid_prefix',
                'callsign_field', 'cot_type', 'altitude_field', 'remarks_fields',
                'stale_minutes', 'cot_how', 'delta_enabled', 'delta_field']:
        if key in data:
            cfg[key] = data[key]
    _esri_tak_sync_save_config(cfg)
    # Patch live config.json if already installed
    config_path = os.path.join(ESRI_TAK_SYNC_DIR, 'config.json')
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                existing = json.load(f)
            ts = existing.setdefault('tak_server', {})
            fl = existing.setdefault('feature_layer', {})
            fm = existing.setdefault('field_mapping', {})
            dt = existing.setdefault('delta', {})
            ts['ca_cert'] = ''  # always clear — server cert verification disabled
            if cfg.get('tak_host'):       ts['host']      = cfg['tak_host'].strip()
            if cfg.get('tak_port'):       ts['port']      = int(cfg['tak_port'])
            if cfg.get('tak_auth_mode'):  ts['auth_mode'] = cfg['tak_auth_mode'].strip()
            if 'tak_username' in cfg:     ts['username']  = cfg['tak_username']
            if 'tak_password' in cfg:     ts['password']  = cfg['tak_password']
            if 'cert_file'   in cfg:      ts['cert_file']    = cfg['cert_file']
            if 'key_file'    in cfg:      ts['key_file']     = cfg['key_file']
            if 'output_file' in cfg:      ts['output_file']  = cfg['output_file']
            if cfg.get('layer_url'):     fl['url']  = cfg['layer_url'].strip()
            if cfg.get('layer_type'):    fl['layer_type'] = cfg['layer_type'].strip()
            if 'layer_public' in cfg:    fl['public'] = bool(cfg['layer_public'])
            if cfg.get('esri_username'): fl['username'] = cfg['esri_username'].strip()
            if cfg.get('esri_password'): fl['password'] = cfg['esri_password'].strip()
            if cfg.get('poll_interval'): fl['poll_interval'] = int(cfg['poll_interval'])
            if cfg.get('uid_field'):     fm['uid_field'] = cfg['uid_field'].strip()
            if cfg.get('cot_type'):      fm['cot_type']  = cfg['cot_type'].strip()
            if 'delta_enabled' in cfg:   dt['enabled'] = bool(cfg['delta_enabled'])
            if cfg.get('delta_field'):   dt['track_field'] = cfg['delta_field'].strip()
            with open(config_path, 'w') as f:
                json.dump(existing, f, indent=2)
        except Exception:
            pass
    return jsonify({'success': True})


@esri_tak_sync_bp.route('/api/esri-tak-sync/install', methods=['POST'])
@login_required
def esri_tak_sync_install():
    if _esri_tak_sync_install_status.get('running'):
        return jsonify({'error': 'Installation already in progress'}), 409
    data = request.get_json(silent=True) or {}
    if data.get('config'):
        _esri_tak_sync_save_config(data['config'])
    _esri_tak_sync_install_log.clear()
    _esri_tak_sync_install_status.update({'running': True, 'complete': False, 'error': False})
    threading.Thread(target=_run_esri_tak_sync_install, daemon=True).start()
    return jsonify({'success': True})


@esri_tak_sync_bp.route('/api/esri-tak-sync/install/log')
@login_required
def esri_tak_sync_install_log():
    idx = request.args.get('index', 0, type=int)
    return jsonify({
        'entries': _esri_tak_sync_install_log[idx:],
        'total':   len(_esri_tak_sync_install_log),
        'running': _esri_tak_sync_install_status['running'],
        'complete':_esri_tak_sync_install_status['complete'],
        'error':   _esri_tak_sync_install_status['error'],
    })


@esri_tak_sync_bp.route('/api/esri-tak-sync/service-status')
@login_required
def esri_tak_sync_service_status():
    r  = subprocess.run(['systemctl', 'is-active', 'feature-layer-to-cot.service'],
                        capture_output=True, text=True)
    st = r.stdout.strip() or 'unknown'
    return jsonify({'active': st == 'active', 'status': st})


@esri_tak_sync_bp.route('/api/esri-tak-sync/service-control', methods=['POST'])
@login_required
def esri_tak_sync_service_control():
    data   = request.get_json(silent=True) or {}
    action = (data.get('action') or '').strip()
    if action not in ('start', 'stop', 'restart'):
        return jsonify({'error': 'Invalid action'}), 400
    r = subprocess.run(['systemctl', action, 'feature-layer-to-cot.service'],
                       capture_output=True, text=True, timeout=30)
    return jsonify({'success': r.returncode == 0, 'output': (r.stdout + r.stderr).strip()})


@esri_tak_sync_bp.route('/api/esri-tak-sync/uninstall', methods=['POST'])
@login_required
def esri_tak_sync_uninstall():
    import shutil as _shutil
    for cmd in ('stop', 'disable'):
        subprocess.run(['systemctl', cmd, 'feature-layer-to-cot.service'],
                       capture_output=True, timeout=15)
    svc_dst = '/etc/systemd/system/feature-layer-to-cot.service'
    if os.path.exists(svc_dst):
        os.remove(svc_dst)
    subprocess.run(['systemctl', 'daemon-reload'], capture_output=True, timeout=30)
    if os.path.exists(ESRI_TAK_SYNC_DIR):
        _shutil.rmtree(ESRI_TAK_SYNC_DIR)
    return jsonify({'success': True})


ESRI_TAK_SYNC_ICONS_DIR = os.path.join(ESRI_TAK_SYNC_DIR, 'icons')


def _esri_tak_sync_icon_manifest():
    """Return list of all installed iconsets parsed from their zip files."""
    import zipfile, xml.etree.ElementTree as ET
    sets = []
    if not os.path.isdir(ESRI_TAK_SYNC_ICONS_DIR):
        return sets
    for fname in sorted(os.listdir(ESRI_TAK_SYNC_ICONS_DIR)):
        if not fname.lower().endswith('.zip'):
            continue
        zpath = os.path.join(ESRI_TAK_SYNC_ICONS_DIR, fname)
        try:
            with zipfile.ZipFile(zpath) as z:
                xml_data = z.read('iconset.xml')
                root = ET.fromstring(xml_data)
                uuid  = root.attrib.get('uid', '')
                name  = root.attrib.get('name', fname)
                group = root.attrib.get('defaultGroup', name)
                raw   = [n for n in z.namelist()
                         if n.lower().endswith('.png') and not n.startswith('__')]
            # Normalize Windows backslashes to forward slashes for URLs
            icons = [{'name': p.replace('\\', '/').split('/')[-1],
                      'path': uuid + '/' + p.replace('\\', '/')}
                     for p in sorted(raw)]
            sets.append({'uuid': uuid, 'name': name, 'group': group,
                         'zip': fname, 'icons': icons})
        except Exception:
            pass
    return sets


@esri_tak_sync_bp.route('/api/esri-tak-sync/icons/list')
@login_required
def esri_tak_sync_icons_list():
    return jsonify({'iconsets': _esri_tak_sync_icon_manifest()})


@esri_tak_sync_bp.route('/api/esri-tak-sync/icons/upload', methods=['POST'])
@login_required
def esri_tak_sync_icons_upload():
    import zipfile, xml.etree.ElementTree as ET
    f = request.files.get('file')
    if not f or not f.filename.lower().endswith('.zip'):
        return jsonify({'success': False, 'error': 'Upload a .zip iconset file'}), 400
    os.makedirs(ESRI_TAK_SYNC_ICONS_DIR, exist_ok=True)
    save_path = os.path.join(ESRI_TAK_SYNC_ICONS_DIR, f.filename)
    f.save(save_path)
    # Validate it contains iconset.xml
    try:
        with zipfile.ZipFile(save_path) as z:
            xml_data = z.read('iconset.xml')
            root = ET.fromstring(xml_data)
            uuid  = root.attrib.get('uid', '')
            name  = root.attrib.get('name', f.filename)
            icons = [n for n in z.namelist() if n.lower().endswith('.png')]
    except Exception as e:
        os.remove(save_path)
        return jsonify({'success': False, 'error': f'Invalid iconset zip: {e}'}), 400
    return jsonify({'success': True, 'uuid': uuid, 'name': name, 'icon_count': len(icons)})


@esri_tak_sync_bp.route('/api/esri-tak-sync/icons/delete', methods=['POST'])
@login_required
def esri_tak_sync_icons_delete():
    data = request.get_json(silent=True) or {}
    uuid = data.get('uuid', '').strip()
    if not uuid:
        return jsonify({'success': False, 'error': 'No uuid provided'}), 400
    for iset in _esri_tak_sync_icon_manifest():
        if iset['uuid'] == uuid:
            path = os.path.join(ESRI_TAK_SYNC_ICONS_DIR, iset['zip'])
            if os.path.exists(path):
                os.remove(path)
            return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Iconset not found'}), 404


@esri_tak_sync_bp.route('/api/esri-tak-sync/icons/img/<uuid>/<path:icon_path>')
@login_required
def esri_tak_sync_icon_img(uuid, icon_path):
    """Serve a single icon PNG from the matching iconset zip."""
    import zipfile
    from flask import make_response
    for iset in _esri_tak_sync_icon_manifest():
        if iset['uuid'] == uuid:
            zpath = os.path.join(ESRI_TAK_SYNC_ICONS_DIR, iset['zip'])
            try:
                with zipfile.ZipFile(zpath) as z:
                    names = z.namelist()
                    # 1. exact match, 2. backslash variant, 3. case-insensitive
                    bs_path = icon_path.replace('/', '\\')
                    matched = (icon_path       if icon_path in names else
                               bs_path         if bs_path   in names else
                               next((n for n in names if n.replace('\\','/').lower()
                                     == icon_path.lower()), None))
                    if matched is None:
                        return jsonify({'error': f'Icon not found in zip: {icon_path}'}), 404
                    data = z.read(matched)
                resp = make_response(data)
                resp.headers['Content-Type'] = 'image/png'
                resp.headers['Cache-Control'] = 'public, max-age=86400'
                return resp
            except Exception as e:
                return jsonify({'error': str(e)}), 500
    return '', 404


@esri_tak_sync_bp.route('/api/esri-tak-sync/icons/save-mapping', methods=['POST'])
@login_required
def esri_tak_sync_icons_save_mapping():
    try:
        data = request.get_json(silent=True) or {}
        cfg = _esri_tak_sync_load_config()
        cfg['icon_column']       = data.get('column', '')
        cfg['icon_enabled']      = bool(data.get('enabled', False))
        cfg['icon_default_path'] = data.get('default_iconsetpath', '')
        cfg['icon_map']          = data.get('map', {})
        _esri_tak_sync_save_config(cfg)
        # Also write directly into the deployed config.json so the service picks it up
        deployed = os.path.join(ESRI_TAK_SYNC_DIR, 'config.json')
        if os.path.exists(deployed):
            try:
                import json as _j
                with open(deployed) as fh:
                    dcfg = _j.load(fh)
                dcfg['icon_mapping'] = {
                    'enabled':             cfg['icon_enabled'],
                    'column':              cfg['icon_column'],
                    'default_iconsetpath': cfg['icon_default_path'],
                    'map':                 cfg['icon_map'],
                }
                with open(deployed, 'w') as fh:
                    _j.dump(dcfg, fh, indent=2)
            except Exception as e:
                # Non-fatal — app settings were saved, deployed config update failed
                return jsonify({'success': True, 'warning': f'App settings saved but deployed config.json update failed: {e}'})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@esri_tak_sync_bp.route('/api/esri-tak-sync/layer-columns')
@login_required
def esri_tak_sync_layer_columns():
    """Return field names from the configured Feature Layer (hits the layer metadata endpoint)."""
    import requests
    try:
        cfg = _esri_tak_sync_load_config()
        url = cfg.get('layer_url', '').rstrip('/')
        if not url:
            return jsonify({'error': 'No layer URL configured — save Config first'}), 400
        params = {'f': 'json'}
        if not cfg.get('layer_public', True):
            # Private layer — obtain token
            try:
                layer_type = cfg.get('layer_type', 'online').lower()
                portal_url = cfg.get('portal_url', '')
                username   = cfg.get('esri_username', '')
                password   = cfg.get('esri_password', '')
                if layer_type == 'online':
                    token_url = 'https://www.arcgis.com/sharing/rest/generateToken'
                else:
                    if not portal_url:
                        from urllib.parse import urlparse
                        p = urlparse(url)
                        parts = [s for s in p.path.split('/') if s.lower() not in ('server','arcgis','rest','services')]
                        portal_url = f"{p.scheme}://{p.netloc}{'/'.join(parts)}/portal"
                    token_url = f"{portal_url.rstrip('/')}/sharing/rest/generateToken"
                tr = requests.post(token_url, data={'username': username, 'password': password,
                    'referer': 'http://localhost', 'expiration': 60, 'f': 'json'}, timeout=15)
                tr.raise_for_status()
                td = tr.json()
                if 'token' in td:
                    params['token'] = td['token']
            except Exception as te:
                return jsonify({'error': f'Token error: {te}'}), 400
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if 'error' in data:
            return jsonify({'error': data['error'].get('message', str(data['error']))}), 400
        fields = [f['name'] for f in data.get('fields', []) if f.get('name')]
        return jsonify({'columns': fields})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@esri_tak_sync_bp.route('/api/esri-tak-sync/layer-values')
@login_required
def esri_tak_sync_layer_values():
    """Return distinct values for a column in the configured Feature Layer."""
    import requests
    column = request.args.get('column', '').strip()
    if not column:
        return jsonify({'error': 'column parameter required'}), 400
    try:
        cfg = _esri_tak_sync_load_config()
        url = cfg.get('layer_url', '').rstrip('/')
        if not url:
            return jsonify({'error': 'No layer URL configured — save Config first'}), 400
        params = {
            'where': '1=1',
            'outFields': column,
            'returnDistinctValues': 'true',
            'returnGeometry': 'false',
            'resultRecordCount': 500,
            'f': 'json',
        }
        if not cfg.get('layer_public', True):
            try:
                layer_type = cfg.get('layer_type', 'online').lower()
                portal_url = cfg.get('portal_url', '')
                username   = cfg.get('esri_username', '')
                password   = cfg.get('esri_password', '')
                if layer_type == 'online':
                    token_url = 'https://www.arcgis.com/sharing/rest/generateToken'
                else:
                    if not portal_url:
                        from urllib.parse import urlparse
                        p = urlparse(url)
                        parts = [s for s in p.path.split('/') if s.lower() not in ('server','arcgis','rest','services')]
                        portal_url = f"{p.scheme}://{p.netloc}{'/'.join(parts)}/portal"
                    token_url = f"{portal_url.rstrip('/')}/sharing/rest/generateToken"
                tr = requests.post(token_url, data={'username': username, 'password': password,
                    'referer': 'http://localhost', 'expiration': 60, 'f': 'json'}, timeout=15)
                tr.raise_for_status()
                td = tr.json()
                if 'token' in td:
                    params['token'] = td['token']
            except Exception as te:
                return jsonify({'error': f'Token error: {te}'}), 400
        resp = requests.get(f'{url}/query', params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if 'error' in data:
            return jsonify({'error': data['error'].get('message', str(data['error']))}), 400
        values = []
        for feat in data.get('features', []):
            val = feat.get('attributes', {}).get(column)
            if val is not None:
                s = str(val).strip()
                if s:
                    values.append(s)
        values.sort(key=lambda x: x.lower())
        return jsonify({'values': values, 'column': column})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


ESRI_TAK_SYNC_TEMPLATE = '''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>FeatureLayer → CoT — infra-TAK</title>
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
.pill-unknown{background:rgba(148,163,184,.08);color:var(--text-dim);border:1px solid var(--border)}
.dot{width:7px;height:7px;border-radius:50%;background:currentColor;flex-shrink:0}
.info-row{display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);font-size:13px}
.info-row:last-child{border-bottom:none}
.warn-card{background:rgba(234,179,8,.05);border:1px solid rgba(234,179,8,.25);border-radius:10px;padding:14px 18px;font-size:13px;color:var(--yellow);margin-bottom:16px}
.ok-card{background:rgba(16,185,129,.05);border:1px solid rgba(16,185,129,.2);border-radius:10px;padding:14px 18px;font-size:13px;color:var(--green);margin-bottom:16px}
.section-title{font-size:12px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.08em;margin:20px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--border)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:700px){.grid2{grid-template-columns:1fr}}
</style></head>
<body>
{{ sidebar_html }}
<div class="main">
  <div class="page-header">
    <h1>FeatureLayer → CoT</h1>
    <p>Polls an Esri Feature Layer and broadcasts records as CoT events to TAK Server. Install dir: <code>{{ install_dir }}</code></p>
  </div>

  <div class="tab-bar">
    <button class="tab active" id="tab-btn-deploy" onclick="showTab('deploy')">🚀 {% if mod.installed %}Re-Deploy{% else %}Deploy{% endif %}</button>
    <button class="tab" id="tab-btn-config" onclick="showTab('config')">⚙️ Config</button>
    <button class="tab" id="tab-btn-icons" onclick="showTab('icons');loadIconsets()">🎨 Icons</button>
    <button class="tab" id="tab-btn-service" onclick="showTab('service');refreshStatus()">🟢 Service</button>
    <button class="tab" id="tab-btn-workflow" onclick="showTab('workflow')">🔀 Workflow</button>
  </div>

  <!-- ══════════════════════════════════════════ DEPLOY TAB ══ -->
  <div id="tab-deploy" class="tab-panel active">
    <div class="card">
      <div class="card-title">{% if mod.installed %}Re-Deploy{% else %}Deploy{% endif %}</div>
      <div style="font-size:13px;color:var(--text-secondary);line-height:1.8;margin-bottom:16px">
        Installs dependencies, copies scripts, writes <code>config.json</code>, generates a self-signed client cert, and registers the systemd service.<br>
        <strong style="display:block;margin-top:8px">What gets deployed:</strong>
        <div style="margin-top:6px">
          <div>📦 <strong>Dep:</strong> pip3 install requests</div>
          <div>📁 <strong>Dir:</strong> {{ install_dir }}/</div>
          <div>📄 <strong>Scripts:</strong> feature-layer-to-cot.py, setup-cert.py</div>
          <div>🔒 <strong>Cert:</strong> certs/esri-push.p12 (self-signed, or skip if exists)</div>
          <div>⚙️ <strong>Service:</strong> feature-layer-to-cot.service (not auto-started)</div>
        </div>
      </div>
      <p class="hint" style="margin-bottom:16px">Configure TAK Server + Feature Layer on the <strong>Config</strong> tab first, or deploy now and configure after.</p>
      {% if deploying %}
      <div id="deploy-log-box" class="log-box" style="margin-bottom:16px">Waiting for log…</div>
      <button class="btn btn-ghost" disabled>⏳ Installing…</button>
      {% elif deploy_done %}
      <div id="deploy-log-box" class="log-box" style="margin-bottom:16px"></div>
      <div style="display:flex;align-items:center;gap:12px">
        <button id="deploy-btn" class="btn btn-success" onclick="startDeploy()">✓ Deployed — Re-Deploy</button>
        <span id="deploy-status-msg" style="font-size:13px;color:var(--green)">✓ Done</span>
      </div>
      {% elif deploy_error %}
      <div id="deploy-log-box" class="log-box" style="margin-bottom:16px"></div>
      <div style="display:flex;align-items:center;gap:12px">
        <button id="deploy-btn" class="btn btn-danger" onclick="startDeploy()">✗ Failed — Retry</button>
        <span id="deploy-status-msg" style="font-size:13px;color:var(--red)">Failed</span>
      </div>
      {% else %}
      <div id="deploy-log-box" class="log-box" style="display:none;margin-bottom:16px"></div>
      <div style="display:flex;align-items:center;gap:12px">
        <button id="deploy-btn" class="btn {% if mod.installed %}btn-ghost{% else %}btn-primary{% endif %}" {% if mod.installed %}style="border-color:var(--yellow);color:var(--yellow)"{% endif %} onclick="startDeploy()">{% if mod.installed %}🔄 Re-Deploy{% else %}🚀 Deploy{% endif %}</button>
        <span id="deploy-status-msg" style="font-size:13px;color:var(--text-dim)"></span>
      </div>
      {% endif %}
    </div>

  </div>

  <!-- ══════════════════════════════════════════ CONFIG TAB ══ -->
  <div id="tab-config" class="tab-panel">
    {% if not mod.installed %}
    <div class="warn-card">⚠ Deploy first to create the install directory, then save config.</div>
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
        <label class="form-label">Auth Mode</label>
        <select id="tak_auth_mode" class="form-input" onchange="toggleAuthMode()">
          <option value="cert"        {% if cfg.get('tak_auth_mode','cert')=='cert'        %}selected{% endif %}>TLS/Cert — P12 client cert (port 8089)</option>
          <option value="tls_keypair" {% if cfg.get('tak_auth_mode')=='tls_keypair'        %}selected{% endif %}>TLS Keypair — PEM cert+key (port 8089)</option>
          <option value="plain"       {% if cfg.get('tak_auth_mode')=='plain'              %}selected{% endif %}>Plain TCP (port 8087)</option>
          <option value="rest"        {% if cfg.get('tak_auth_mode')=='rest'               %}selected{% endif %}>REST / User+Pass + cert (port 8443)</option>
          <option value="authentik"   {% if cfg.get('tak_auth_mode')=='authentik'          %}selected{% endif %}>Authentik / LDAP — user+pass (port 8443)</option>
          <option value="file"        {% if cfg.get('tak_auth_mode')=='file'               %}selected{% endif %}>File — write CoT to text file (no TAK Server)</option>
        </select>
      </div>

      <!-- REST auth fields (user/pass + client cert) -->
      <div id="rest-auth-section" style="display:{% if cfg.get('tak_auth_mode')=='rest' %}block{% else %}none{% endif %}">
        <div class="grid2">
          <div class="form-group">
            <label class="form-label">TAK Username</label>
            <input id="tak_username" class="form-input" type="text" placeholder="admin" value="{{ cfg.tak_username or '' }}">
          </div>
          <div class="form-group">
            <label class="form-label">TAK Password</label>
            <input id="tak_password" class="form-input" type="password" value="{{ cfg.tak_password or '' }}">
          </div>
        </div>
        <p class="hint">CoT is POST-ed to <code>https://&lt;host&gt;:8443/Marti/api/cot/xml</code>. TAK Server 8443 uses mutual TLS — a client cert is still required for the TLS handshake. Use the cert setup below.</p>
      </div>

      <!-- Authentik / LDAP auth fields (user/pass only, no client cert) -->
      <div id="authentik-auth-section" style="display:{% if cfg.get('tak_auth_mode')=='authentik' %}block{% else %}none{% endif %}">
        <div class="grid2">
          <div class="form-group">
            <label class="form-label">TAK Username <span style="font-weight:400;color:var(--text-dim)">(Authentik / LDAP user)</span></label>
            <input id="tak_username" class="form-input" type="text" placeholder="takuser" value="{{ cfg.tak_username or '' }}">
          </div>
          <div class="form-group">
            <label class="form-label">TAK Password</label>
            <input id="tak_password" class="form-input" type="password" value="{{ cfg.tak_password or '' }}">
          </div>
        </div>
        <p class="hint">CoT is POST-ed to <code>https://&lt;host&gt;:8443/Marti/api/cot/xml</code> using the LDAP-synced user credentials from Authentik. No client cert required.</p>
      </div>

      <!-- TLS Keypair fields (PEM cert + key paths, Node-RED style) -->
      <div id="tls-keypair-section" style="display:{% if cfg.get('tak_auth_mode')=='tls_keypair' %}block{% else %}none{% endif %}">
        <div class="grid2">
          <div class="form-group">
            <label class="form-label">PEM Cert File</label>
            <input id="cert_file" class="form-input" type="text" placeholder="/opt/Esri-TAKServer-Sync/certs/esri-push-cert.pem" value="{{ cfg.cert_file or '' }}">
          </div>
          <div class="form-group">
            <label class="form-label">PEM Key File</label>
            <input id="key_file" class="form-input" type="text" placeholder="/opt/Esri-TAKServer-Sync/certs/esri-push-key.pem" value="{{ cfg.key_file or '' }}">
          </div>
        </div>
        <p class="hint">TLS connection to port 8089 using PEM cert+key directly — server cert verification is disabled (matches Node-RED flow). The cert files are generated automatically when you use the cert setup below.</p>
      </div>

      <!-- File output mode -->
      <div id="file-output-section" style="display:{% if cfg.get('tak_auth_mode')=='file' %}block{% else %}none{% endif %}">
        <div class="form-group">
          <label class="form-label">Output File Path</label>
          <input type="text" id="output_file" class="form-input" value="{{ cfg.get('output_file','/opt/Esri-TAKServer-Sync/cot_output.txt') }}" placeholder="/opt/Esri-TAKServer-Sync/cot_output.txt">
          <p class="hint">Each poll cycle overwrites this file with one CoT XML message per line. No TAK Server connection is made.</p>
        </div>
      </div>

      <!-- TLS cert generation — shown only when TLS/Cert or TLS Keypair mode is selected -->
      <div id="cert-gen-section" style="display:{% if cfg.get('tak_auth_mode','cert') in ('cert','tls_keypair') %}block{% else %}none{% endif %}">
      {% if cert_exists %}
      <div style="background:rgba(16,185,129,.05);border:1px solid rgba(16,185,129,.2);border-radius:10px;padding:12px 16px;margin-bottom:12px;font-size:13px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">
        <span style="color:var(--green)">✓ Cert configured — <code>{{ cert_pem_path }}</code></span>
        <button class="btn btn-ghost" style="font-size:12px;padding:4px 12px" onclick="document.getElementById('cert-gen-form').style.display=document.getElementById('cert-gen-form').style.display==='none'?'block':'none'">Replace…</button>
      </div>
      <div id="cert-gen-form" style="display:none">
      {% else %}
      <div id="cert-gen-form">
      {% endif %}
        {% if tak_local %}
        <div class="grid2">
          <div class="form-group">
            <label class="form-label">Cert Name</label>
            <input id="cert-name-input" class="form-input" type="text" value="{{ cfg.tak_cert_name or 'esri-push' }}" placeholder="esri-push">
          </div>
          <div class="form-group">
            <label class="form-label">TAK Group</label>
            <input id="tak_group" class="form-input" type="text" placeholder="__ANON__" value="{{ cfg.tak_group or '__ANON__' }}">
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
          <button id="cert-gen-btn" class="btn btn-success" onclick="runCertSetup()">🔑 Generate &amp; Enroll</button>
          <span id="cert-status-msg" style="font-size:13px"></span>
        </div>
        <div id="cert-log-box" class="log-box" style="margin-top:12px;display:none"></div>
        {% else %}
        <p style="font-size:13px;color:var(--text-secondary)">TAK Server not detected on this host — cannot generate cert locally.</p>
        {% endif %}
      </div>
      </div><!-- end cert-gen-section -->

      <div class="section-title">Feature Layer</div>
      <div class="form-group">
        <label class="form-label">Feature Layer URL</label>
        <input id="layer_url" class="form-input" type="text" placeholder="https://services.arcgis.com/.../FeatureServer/0" value="{{ cfg.layer_url or '' }}">
        <p class="hint">Point to the layer root (e.g. <code>.../FeatureServer/0</code>). The <code>/query</code> suffix is added automatically.</p>
      </div>
      <div class="grid2">
        <div class="form-group">
          <label class="form-label">Layer Type</label>
          <select id="layer_type" class="form-input" onchange="toggleAuth()">
            <option value="online" {% if (cfg.get('layer_type','online'))=='online' %}selected{% endif %}>ArcGIS Online</option>
            <option value="enterprise" {% if cfg.get('layer_type')=='enterprise' %}selected{% endif %}>ArcGIS Enterprise</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Access</label>
          <select id="layer_public" class="form-input" onchange="toggleAuth()">
            <option value="1" {% if cfg.get('layer_public', True) %}selected{% endif %}>Public (no auth)</option>
            <option value="0" {% if not cfg.get('layer_public', True) %}selected{% endif %}>Private (username + password)</option>
          </select>
        </div>
      </div>
      <div id="auth-section" style="display:none">
        <div class="grid2">
          <div class="form-group">
            <label class="form-label">Esri Username</label>
            <input id="esri_username" class="form-input" type="text" value="{{ cfg.esri_username or '' }}">
          </div>
          <div class="form-group">
            <label class="form-label">Esri Password</label>
            <input id="esri_password" class="form-input" type="password" value="{{ cfg.esri_password or '' }}">
          </div>
        </div>
        <div class="form-group" id="portal-url-group" style="display:none">
          <label class="form-label">Enterprise Portal URL <span style="font-weight:400;color:var(--text-dim)">(auto-derived if blank)</span></label>
          <input id="portal_url" class="form-input" type="text" placeholder="https://gis.myorg.com/portal" value="{{ cfg.portal_url or '' }}">
        </div>
      </div>
      <div class="grid2">
        <div class="form-group">
          <label class="form-label">Poll Interval (seconds)</label>
          <input id="poll_interval" class="form-input" type="number" placeholder="30" value="{{ cfg.poll_interval or '30' }}">
        </div>
        <div class="form-group">
          <label class="form-label">Page Size</label>
          <input id="page_size" class="form-input" type="number" placeholder="1000" value="{{ cfg.page_size or '1000' }}">
        </div>
      </div>

      <div class="section-title">Field Mapping</div>
      <p style="font-size:12px;color:var(--text-dim);margin:0 0 12px 0">
        Enter the exact field names from your Feature Layer. Each setting maps directly to a CoT XML attribute.
      </p>

      <!-- CoT XML preview banner -->
      <div style="background:var(--bg-3,#1a1a2e);border:1px solid var(--border);border-radius:6px;padding:10px 14px;font-family:monospace;font-size:11px;color:#7ecfff;margin-bottom:16px;overflow-x:auto;white-space:pre;line-height:1.7">&lt;event uid="<span style="color:#ffd580">PREFIX</span>_<span style="color:#a0e080">UIDFIELD</span>" type="<span style="color:#f9a8d4">COT_TYPE</span>" how="<span style="color:#c4b5fd">HOW</span>" stale="<span style="color:#fb923c">STALE</span>"&gt;
  &lt;point lat="<span style="color:#34d399">LAT</span>" lon="<span style="color:#34d399">LON</span>" hae="<span style="color:#34d399">ALT</span>" /&gt;
  &lt;detail&gt;
    &lt;contact callsign="<span style="color:#60a5fa">CALLSIGN</span>" uid="<span style="color:#a0e080">PREFIX_UIDFIELD</span>" /&gt;
    &lt;remarks&gt;<span style="color:#e5e7eb">REMARKS FIELDS</span>&lt;/remarks&gt;
  &lt;/detail&gt;
&lt;/event&gt;</div>

      <div class="grid2">
        <div class="form-group">
          <label class="form-label">
            UID Field
            <span style="font-weight:400;font-size:10px;background:#2d3748;color:#a0e080;border-radius:3px;padding:1px 5px;margin-left:6px;font-family:monospace">&lt;event uid="PREFIX_<b>value</b>"&gt;</span>
          </label>
          <input id="uid_field" class="form-input" type="text" placeholder="OBJECTID" value="{{ cfg.uid_field or '' }}">
          <p class="hint">Unique field name per record (e.g. OBJECTID, FID, GlobalID). Each record needs a different value or only one marker will appear.</p>
        </div>
        <div class="form-group">
          <label class="form-label">
            UID Prefix
            <span style="font-weight:400;font-size:10px;background:#2d3748;color:#ffd580;border-radius:3px;padding:1px 5px;margin-left:6px;font-family:monospace">&lt;event uid="<b>PREFIX</b>_value"&gt;</span>
          </label>
          <input id="uid_prefix" class="form-input" type="text" placeholder="EsriSync" value="{{ cfg.uid_prefix or '' }}">
          <p class="hint">Prepended to every UID to avoid collisions with other CoT sources.</p>
        </div>
      </div>
      <div class="grid2">
        <div class="form-group">
          <label class="form-label">
            Callsign Field
            <span style="font-weight:400;font-size:10px;background:#2d3748;color:#60a5fa;border-radius:3px;padding:1px 5px;margin-left:6px;font-family:monospace">&lt;contact callsign="<b>value</b>"&gt;</span>
          </label>
          <input id="callsign_field" class="form-input" type="text" placeholder="" value="{{ cfg.callsign_field or '' }}">
          <p class="hint">Label shown in TAK. Empty = falls back to UID value.</p>
        </div>
        <div class="form-group">
          <label class="form-label">
            CoT Type
            <span style="font-weight:400;font-size:10px;background:#2d3748;color:#f9a8d4;border-radius:3px;padding:1px 5px;margin-left:6px;font-family:monospace">&lt;event type="<b>value</b>"&gt;</span>
          </label>
          <input id="cot_type" class="form-input" type="text" placeholder="a-f-G" value="{{ cfg.cot_type or '' }}">
          <p class="hint">Fixed type (e.g. <code>a-f-G</code>) or <code>field:FieldName</code> to read from data.</p>
        </div>
      </div>
      <div class="grid2">
        <div class="form-group">
          <label class="form-label">
            Lat Field
            <span style="font-weight:400;font-size:10px;background:#2d3748;color:#34d399;border-radius:3px;padding:1px 5px;margin-left:6px;font-family:monospace">&lt;point lat="<b>value</b>"&gt;</span>
          </label>
          <input id="lat_field" class="form-input" type="text" placeholder="" value="{{ cfg.lat_field or '' }}">
          <p class="hint">Empty = read from geometry (recommended for point layers).</p>
        </div>
        <div class="form-group">
          <label class="form-label">
            Lon Field
            <span style="font-weight:400;font-size:10px;background:#2d3748;color:#34d399;border-radius:3px;padding:1px 5px;margin-left:6px;font-family:monospace">&lt;point lon="<b>value</b>"&gt;</span>
          </label>
          <input id="lon_field" class="form-input" type="text" placeholder="" value="{{ cfg.lon_field or '' }}">
          <p class="hint">Empty = read from geometry (recommended for point layers).</p>
        </div>
      </div>
      <div class="grid2">
        <div class="form-group">
          <label class="form-label">
            Altitude Field
            <span style="font-weight:400;font-size:10px;background:#2d3748;color:#34d399;border-radius:3px;padding:1px 5px;margin-left:6px;font-family:monospace">&lt;point hae="<b>value</b>"&gt;</span>
          </label>
          <input id="altitude_field" class="form-input" type="text" placeholder="" value="{{ cfg.altitude_field or '' }}">
          <p class="hint">Height above ellipsoid in meters. Empty = 0.</p>
        </div>
        <div class="form-group">
          <label class="form-label">
            Stale (minutes)
            <span style="font-weight:400;font-size:10px;background:#2d3748;color:#fb923c;border-radius:3px;padding:1px 5px;margin-left:6px;font-family:monospace">&lt;event stale="now+<b>N</b>min"&gt;</span>
          </label>
          <input id="stale_minutes" class="form-input" type="number" placeholder="5" value="{{ cfg.stale_minutes or '5' }}">
          <p class="hint">How long TAK keeps the marker before graying it out.</p>
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">
          CoT How
          <span style="font-weight:400;font-size:10px;background:#2d3748;color:#c4b5fd;border-radius:3px;padding:1px 5px;margin-left:6px;font-family:monospace">&lt;event how="<b>value</b>"&gt;</span>
        </label>
        <select id="cot_how" class="form-input" style="max-width:340px">
          <option value="m-g" {% if (cfg.cot_how or 'm-g')=='m-g' %}selected{% endif %}>m-g — Machine / GPS fix</option>
          <option value="h-g-i-g-o" {% if cfg.cot_how=='h-g-i-g-o' %}selected{% endif %}>h-g-i-g-o — INS</option>
          <option value="h-e" {% if cfg.cot_how=='h-e' %}selected{% endif %}>h-e — Human estimated</option>
          <option value="m-f" {% if cfg.cot_how=='m-f' %}selected{% endif %}>m-f — Calculated</option>
        </select>
        <p class="hint">Position acquisition method — affects icon styling in some TAK clients.</p>
      </div>
      <div class="form-group">
        <label class="form-label">
          Remarks Fields
          <span style="font-weight:400;font-size:10px;background:#2d3748;color:#e5e7eb;border-radius:3px;padding:1px 5px;margin-left:6px;font-family:monospace">&lt;remarks&gt;<b>field: value, ...</b>&lt;/remarks&gt;</span>
        </label>
        <input id="remarks_fields" class="form-input" type="text" placeholder="Status, Notes, Address" value="{{ cfg.remarks_fields or '' }}">
        <p class="hint">Comma-separated list of field names. Values are shown in the TAK popup when you tap a marker.</p>
      </div>

      <div class="section-title">Delta / Change Detection</div>
      <div class="grid2">
        <div class="form-group">
          <label class="form-label">Delta Mode</label>
          <select id="delta_enabled" class="form-input">
            <option value="1" {% if cfg.get('delta_enabled', False) %}selected{% endif %}>Enabled — only send new/changed records</option>
            <option value="0" {% if not cfg.get('delta_enabled', False) %}selected{% endif %}>Disabled — broadcast all records every poll</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Track Field <span style="font-weight:400;color:var(--text-dim)">(field with edit timestamp)</span></label>
          <input id="delta_field" class="form-input" type="text" placeholder="EditDate" value="{{ cfg.delta_field or '' }}">
        </div>
      </div>

      <div style="display:flex;align-items:center;gap:12px;margin-top:8px">
        <button class="btn btn-success" onclick="saveConfig()">💾 Save Config</button>
        <span id="save-msg" style="font-size:12px"></span>
      </div>
      <p class="hint" style="margin-top:10px">If the service is already running, restart it after saving to apply changes.</p>
    </div>
  </div>

  <!-- ══════════════════════════════════════════ ICONS TAB ══ -->
  <script id="icon-map-data" type="application/json">{{ (cfg.icon_map or {})|tojson }}</script>
  <div id="tab-icons" class="tab-panel">
    <div class="card">
      <div class="card-title">Upload Iconset</div>
      <p style="font-size:13px;color:var(--text-secondary);margin-bottom:14px">
        Upload any ATAK/WinTAK <code>.zip</code> iconset — must contain <code>iconset.xml</code> with a <code>uid</code> attribute.
      </p>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <input type="file" id="icon-zip-input" accept=".zip" style="font-size:13px;color:var(--text-secondary)">
        <button class="btn btn-primary" onclick="uploadIconset()">⬆ Upload</button>
        <span id="upload-msg" style="font-size:12px"></span>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Installed Iconsets</div>
      <div id="iconset-list"><span style="color:var(--text-dim);font-size:13px">Loading…</span></div>
    </div>

    <div class="card">
      <div class="card-title">Column → Icon Mapping</div>
      <p style="font-size:13px;color:var(--text-secondary);margin-bottom:14px">
        Pick a column whose values determine which icon each PLI gets. Assign an icon to each value, then set a fallback for unmapped values.
      </p>
      <datalist id="col-datalist"></datalist>
      <div class="grid2" style="margin-bottom:14px">
        <div class="form-group">
          <label class="form-label">Mapping Column</label>
          <div style="display:flex;gap:8px;align-items:center">
            <input id="icon-column" class="form-input" type="text" list="col-datalist"
                   placeholder="e.g. STATUS" value="{{ cfg.icon_column or '' }}" style="flex:1">
            <button class="btn btn-ghost" style="white-space:nowrap;padding:6px 12px;font-size:12px"
                    id="fetch-cols-btn" onclick="fetchLayerColumns()" title="Load column names from the Feature Layer">↻ Load</button>
          </div>
          <p id="fetch-cols-msg" style="font-size:11px;color:var(--text-dim);margin-top:4px"></p>
        </div>
        <div class="form-group">
          <label class="form-label">Enable Icon Mapping</label>
          <select id="icon-enabled" class="form-input">
            <option value="1" {% if cfg.get('icon_enabled') %}selected{% endif %}>Yes — inject usericon into CoT</option>
            <option value="0" {% if not cfg.get('icon_enabled') %}selected{% endif %}>No — skip usericon element</option>
          </select>
        </div>
      </div>

      <div class="form-group" style="margin-bottom:18px">
        <label class="form-label">Default Icon <span style="font-weight:400;color:var(--text-dim)">(used when value has no mapping)</span></label>
        <div style="display:flex;gap:10px;align-items:center">
          <input id="icon-default-path" class="form-input" type="text"
                 placeholder="uuid/Incident Icons/Placeholder Other.png"
                 value="{{ cfg.icon_default_path or '' }}" style="flex:1">
          <button class="btn btn-ghost" style="white-space:nowrap" onclick="openPicker('__default__')">🖼 Pick</button>
          <img id="preview-__default__" src="" style="width:32px;height:32px;object-fit:contain;display:none;border-radius:4px;background:rgba(255,255,255,.06)">
        </div>
      </div>

      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <span class="form-label" style="margin:0">Value Mappings</span>
        <button class="btn btn-ghost" style="padding:6px 14px;font-size:12px" id="add-row-btn" onclick="addMappingRow()">+ Add Row</button>
      </div>
      <div id="mapping-rows" style="display:flex;flex-direction:column;gap:8px"></div>

      <div style="display:flex;gap:12px;align-items:center;margin-top:18px">
        <button class="btn btn-success" onclick="saveIconMapping()">💾 Save Mapping</button>
        <span id="icon-save-msg" style="font-size:12px"></span>
      </div>
    </div>

    <style>.picker-icon-cell{display:flex;flex-direction:column;align-items:center;gap:4px;cursor:pointer;padding:8px;border-radius:6px;border:1px solid var(--border);background:var(--surface);transition:border-color .15s}.picker-icon-cell:hover{border-color:var(--accent)}</style>
    <!-- Icon picker modal -->
    <div id="icon-picker-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:1000;align-items:center;justify-content:center">
      <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:14px;padding:24px;width:min(760px,95vw);max-height:85vh;display:flex;flex-direction:column;gap:14px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="font-size:15px;font-weight:600">Pick an Icon</span>
          <button class="btn btn-ghost" style="padding:6px 12px" onclick="closePicker()">✕ Close</button>
        </div>
        <div style="display:flex;align-items:center;gap:10px">
          <input id="picker-search" class="form-input" type="text" placeholder="🔍  Search icons…"
                 style="flex:1;font-size:13px" oninput="_pickerFilter(this.value)">
          <span id="picker-count" style="font-size:12px;color:var(--text-dim);white-space:nowrap"></span>
        </div>
        <div id="picker-grid" style="overflow-y:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(80px,1fr));gap:10px;padding:4px"></div>
      </div>
    </div>

    <!-- Value picker modal (distinct column values) -->
    <div id="value-picker-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:1001;align-items:center;justify-content:center">
      <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:14px;padding:24px;width:min(540px,95vw);max-height:80vh;display:flex;flex-direction:column;gap:14px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="font-size:15px;font-weight:600">Pick a value from <em id="value-picker-col-label" style="color:var(--cyan)"></em></span>
          <button class="btn btn-ghost" style="padding:6px 12px" onclick="closeValuePicker()">✕</button>
        </div>
        <p style="font-size:12px;color:var(--text-dim);margin:0">Click a value to add a mapping row for it, or use <strong>Other</strong> to type one manually.</p>
        <div id="value-picker-loading" style="font-size:13px;color:var(--text-dim)">Loading values…</div>
        <div id="value-picker-chips" style="display:flex;flex-wrap:wrap;gap:8px;overflow-y:auto;max-height:300px;padding:4px 0"></div>
        <div style="display:flex;gap:10px;padding-top:4px;border-top:1px solid var(--border)">
          <button class="btn btn-ghost" style="font-size:12px" onclick="addBlankMappingRow()">+ Other (type manually)</button>
          <button class="btn btn-ghost" style="font-size:12px;margin-left:auto" onclick="closeValuePicker()">Cancel</button>
        </div>
      </div>
    </div>
  </div>

  <!-- ══════════════════════════════════════════ SERVICE TAB ══ -->
  <div id="tab-service" class="tab-panel">
    {% if not mod.installed %}
    <div class="warn-card">⚠ Deploy the module first before starting the service.</div>
    {% else %}
    <div class="card">
      <div class="card-title">Service Status</div>
      <div class="info-row">
        <span>feature-layer-to-cot.service</span>
        <span id="svc-badge" class="status-pill {% if svc_active %}pill-active{% else %}pill-inactive{% endif %}">
          <span class="dot"></span><span id="svc-status-text">{% if svc_active %}active{% else %}inactive{% endif %}</span>
        </span>
      </div>
      <div class="info-row">
        <span>Log file</span>
        <span style="font-size:11px;font-family:'JetBrains Mono',monospace;color:var(--text-dim)">/var/log/esri-takserver-sync-feature-layer-to-cot.log</span>
      </div>
      <div class="info-row">
        <span>Install dir</span>
        <span style="font-size:11px;font-family:'JetBrains Mono',monospace;color:var(--text-dim)">{{ install_dir }}</span>
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
        Stops the service, removes <code>{{ install_dir }}</code>, and unregisters the systemd unit. Config saved in infra-TAK settings is preserved.
      </p>
      <button class="btn btn-danger" onclick="uninstall()">🗑 Uninstall</button>
      <span id="uninstall-msg" style="font-size:12px;margin-left:12px"></span>
    </div>
    {% endif %}
  </div>

  <!-- ══════════════════════════════════════════ WORKFLOW TAB ══ -->
  <div id="tab-workflow" class="tab-panel">
    <div class="card" style="padding:28px 24px">
      <div class="card-title" style="margin-bottom:4px">Data Flow — FeatureLayer → CoT</div>
      <p style="font-size:13px;color:var(--text-secondary);margin-bottom:28px">Hover over any node or arrow to learn more about that part of the pipeline.</p>
      <style>
        .wf-wrap{display:flex;flex-direction:column;align-items:center;gap:0;width:100%;position:relative}
        .wf-row{display:flex;align-items:center;justify-content:center;gap:0;width:100%;flex-wrap:nowrap}
        .wf-node{position:relative;background:var(--bg-card);border:1.5px solid var(--border);border-radius:12px;padding:14px 20px;min-width:170px;max-width:220px;text-align:center;cursor:default;transition:border-color .2s,box-shadow .2s;flex-shrink:0}
        .wf-node:hover{border-color:var(--accent);box-shadow:0 0 18px rgba(59,130,246,.25)}
        .wf-node .wf-icon{font-size:28px;line-height:1;margin-bottom:6px}
        .wf-node .wf-label{font-size:13px;font-weight:600;color:var(--text-primary)}
        .wf-node .wf-sub{font-size:11px;color:var(--text-dim);margin-top:3px}
        .wf-arrow{display:flex;align-items:center;justify-content:center;width:56px;flex-shrink:0;position:relative;cursor:default}
        .wf-arrow svg{overflow:visible}
        .wf-arrow:hover .wf-arr-line{stroke:var(--accent)}
        .wf-arrow:hover .wf-arr-tip{fill:var(--accent)}
        .wf-arrow-v{display:flex;flex-direction:column;align-items:center;height:52px;cursor:default}
        .wf-arrow-v:hover .wf-arr-line{stroke:var(--accent)}
        .wf-arrow-v:hover .wf-arr-tip{fill:var(--accent)}
        .wf-arr-line{stroke:#334155;stroke-width:2;transition:stroke .2s}
        .wf-arr-tip{fill:#334155;transition:fill .2s}
        /* tooltip */
        .wf-tooltip{visibility:hidden;opacity:0;position:absolute;z-index:200;background:#1e2736;border:1px solid var(--border);border-radius:10px;padding:12px 16px;width:260px;font-size:12px;color:var(--text-secondary);line-height:1.6;pointer-events:none;transition:opacity .18s;box-shadow:0 8px 32px rgba(0,0,0,.5)}
        .wf-tooltip strong{color:var(--text-primary);display:block;margin-bottom:4px;font-size:13px}
        .wf-node:hover .wf-tooltip,.wf-arrow:hover .wf-tooltip,.wf-arrow-v:hover .wf-tooltip{visibility:visible;opacity:1}
        /* tooltip placement helpers */
        .tt-above{bottom:calc(100% + 10px);left:50%;transform:translateX(-50%)}
        .tt-below{top:calc(100% + 10px);left:50%;transform:translateX(-50%)}
        .tt-left{right:calc(100% + 10px);top:50%;transform:translateY(-50%)}
        .tt-right{left:calc(100% + 10px);top:50%;transform:translateY(-50%)}
        /* side nodes */
        .wf-side{display:flex;flex-direction:column;gap:10px;align-items:flex-start}
        .wf-side-node{position:relative;background:var(--bg-card);border:1.5px dashed var(--border);border-radius:10px;padding:10px 14px;min-width:140px;font-size:12px;cursor:default;transition:border-color .2s}
        .wf-side-node:hover{border-color:var(--cyan)}
        .wf-side-node .wf-label{font-size:12px;font-weight:600;color:var(--text-secondary)}
        .wf-side-node .wf-sub{font-size:11px;color:var(--text-dim);margin-top:2px}
        .wf-side-node:hover .wf-tooltip{visibility:visible;opacity:1}
        .wf-dashed-v{border-left:2px dashed #334155;height:30px;margin:0 auto;width:0}
      </style>

      <div class="wf-wrap">

        <!-- Row 1: Esri Feature Layer -->
        <div class="wf-row">
          <div class="wf-node" style="border-color:#0ea5e9">
            <div class="wf-icon">🗄️</div>
            <div class="wf-label">Esri Feature Layer</div>
            <div class="wf-sub">ArcGIS Online or Enterprise</div>
            <div class="wf-tooltip tt-below" style="width:280px">
              <strong>Esri Feature Layer</strong>
              The source of truth. Can be hosted on ArcGIS Online or your own ArcGIS Enterprise portal.
              Supports public layers (no auth) and private layers (username/password token auth).
              2FA-protected accounts are not compatible — use a service account.
              <br><br>Records are fetched via the Feature Layer REST API with pagination (up to 1000 records per page).
            </div>
          </div>
        </div>

        <!-- Arrow down -->
        <div class="wf-arrow-v">
          <svg width="2" height="52" style="overflow:visible"><line class="wf-arr-line" x1="1" y1="0" x2="1" y2="44"/><polygon class="wf-arr-tip" points="1,52 -5,38 7,38"/></svg>
          <div class="wf-tooltip tt-right" style="top:0;transform:none;margin-top:-10px">
            <strong>REST API Poll</strong>
            The poller sends an HTTP GET to the Feature Layer's <code>/query</code> endpoint every N seconds (configurable).
            It requests all fields, WGS84 coordinates, and up to 1000 records per page.
            When delta tracking is enabled, only records modified since the last run are fetched.
          </div>
        </div>

        <!-- Row 2: Python Poller + side nodes -->
        <div class="wf-row" style="gap:18px">
          <div class="wf-side" style="align-items:flex-end">
            <div class="wf-side-node">
              <div class="wf-icon" style="font-size:18px">📄</div>
              <div class="wf-label">config.json</div>
              <div class="wf-sub">TAK host, auth mode, field mappings</div>
              <div class="wf-tooltip tt-right">
                <strong>config.json</strong>
                Stored at <code>/opt/Esri-TAKServer-Sync/config.json</code>.
                Defines the TAK Server host/port, auth mode (cert or plain TCP),
                Feature Layer URL, field mapping (lat/lon/callsign/cot_type),
                delta tracking settings, and icon mapping rules.
                Written by infra-TAK on each deploy or config save.
              </div>
            </div>
            <div class="wf-side-node">
              <div class="wf-icon" style="font-size:18px">💾</div>
              <div class="wf-label">delta-state.json</div>
              <div class="wf-sub">Tracks last-seen EditDate per UID</div>
              <div class="wf-tooltip tt-right">
                <strong>Delta State</strong>
                Persisted to <code>/opt/Esri-TAKServer-Sync/delta-state.json</code>.
                When delta mode is on, only records with an EditDate newer than the stored value are sent — reducing bandwidth and TAK Server load.
                Delete this file to force a full re-broadcast on next start.
              </div>
            </div>
          </div>

          <div class="wf-node" style="border-color:#8b5cf6;min-width:200px">
            <div class="wf-icon">🐍</div>
            <div class="wf-label">feature-layer-to-cot.py</div>
            <div class="wf-sub">Python poller + CoT builder</div>
            <div class="wf-tooltip tt-below" style="width:300px">
              <strong>Python Worker Script</strong>
              Runs as a systemd service (<code>feature-layer-to-cot.service</code>).
              On each poll cycle it:
              <br>1. Fetches all (or changed) records from the Feature Layer
              <br>2. Maps lat/lon/callsign/type fields to CoT attributes
              <br>3. Optionally resolves an icon path from the icon mapping table
              <br>4. Builds a CoT XML <code>&lt;event&gt;</code> element for each record
              <br>5. Streams them to TAK Server over the open TCP/TLS connection
              <br>6. Sends a keepalive ping every 15 s to keep the connection alive
            </div>
          </div>

          <div class="wf-side" style="align-items:flex-start">
            <div class="wf-side-node">
              <div class="wf-icon" style="font-size:18px">🎨</div>
              <div class="wf-label">icons/*.zip</div>
              <div class="wf-sub">Uploaded ATAK/WinTAK iconsets</div>
              <div class="wf-tooltip tt-left">
                <strong>Icon Mapping</strong>
                Iconset <code>.zip</code> files are stored in <code>/opt/Esri-TAKServer-Sync/icons/</code>.
                Each zip must contain an <code>iconset.xml</code> with a <code>uid</code> attribute.
                The Icons tab lets you assign a column value → iconset path mapping.
                The poller injects <code>&lt;usericon iconsetpath="uuid/group/icon.png"/&gt;</code>
                into each CoT event so ATAK/WinTAK renders the correct icon.
              </div>
            </div>
          </div>
        </div>

        <!-- Arrow down: two paths -->
        <div class="wf-row" style="gap:0;margin-top:0">
          <div style="display:flex;flex-direction:column;align-items:center;margin-right:60px">
            <div class="wf-arrow-v">
              <svg width="2" height="52" style="overflow:visible"><line class="wf-arr-line" x1="1" y1="0" x2="1" y2="44"/><polygon class="wf-arr-tip" points="1,52 -5,38 7,38"/></svg>
              <div class="wf-tooltip tt-left">
                <strong>TLS/Cert Mode (port 8089)</strong>
                Uses mTLS — the client presents a <code>.p12</code> certificate.
                TAK Server validates it against its trusted CA list.
                Use <code>certmanager.sh client esri-push</code> to generate a CA-signed cert,
                then enroll it via <code>UserManager.jar certmod -A</code>.
                Extract PEM sidecars with <code>openssl pkcs12 -legacy ...</code>.
              </div>
            </div>
            <div style="font-size:11px;color:#64748b;margin-top:2px">cert (8089)</div>
          </div>
          <div style="display:flex;flex-direction:column;align-items:center;margin-left:60px">
            <div class="wf-arrow-v">
              <svg width="2" height="52" style="overflow:visible"><line class="wf-arr-line" x1="1" y1="0" x2="1" y2="44"/><polygon class="wf-arr-tip" points="1,52 -5,38 7,38"/></svg>
              <div class="wf-tooltip tt-right">
                <strong>Plain TCP Mode (port 8087)</strong>
                Unencrypted TCP connection — simpler to set up but traffic is not encrypted.
                Only use on a private/trusted network.
                TAK Server must have a plain TCP input configured in <code>CoreConfig.xml</code>
                (many default TAK Server installs have only TLS enabled on 8089).
              </div>
            </div>
            <div style="font-size:11px;color:#64748b;margin-top:2px">plain (8087)</div>
          </div>
        </div>

        <!-- Row 3: TAK Server -->
        <div class="wf-row">
          <div class="wf-node" style="border-color:#10b981">
            <div class="wf-icon">🖥️</div>
            <div class="wf-label">TAK Server</div>
            <div class="wf-sub">Streams CoT to connected clients</div>
            <div class="wf-tooltip tt-above">
              <strong>TAK Server</strong>
              Receives the CoT XML stream and fans it out to all connected clients in the configured group.
              <br><br>The <code>esri-push</code> user/cert is enrolled in a TAK group (e.g. <em>__ANON__</em> or a custom group).
              All clients subscribed to that group will see the PLIs.
              <br><br>Stale time is configurable — records disappear from maps after N minutes if not refreshed.
            </div>
          </div>
        </div>

        <!-- Arrow down -->
        <div class="wf-arrow-v">
          <svg width="2" height="52" style="overflow:visible"><line class="wf-arr-line" x1="1" y1="0" x2="1" y2="44"/><polygon class="wf-arr-tip" points="1,52 -5,38 7,38"/></svg>
          <div class="wf-tooltip tt-right">
            <strong>CoT Distribution</strong>
            TAK Server sends CoT events to all connected ATAK, WinTAK, iTAK, and TAKX clients.
            Each Feature Layer record appears as a PLI (Position Location Information) dot on the map
            with its callsign label and — if icon mapping is configured — a custom icon.
          </div>
        </div>

        <!-- Row 4: Clients -->
        <div class="wf-row" style="gap:18px">
          <div class="wf-node" style="min-width:130px">
            <div class="wf-icon">📱</div>
            <div class="wf-label">ATAK</div>
            <div class="wf-sub">Android TAK</div>
            <div class="wf-tooltip tt-above">
              <strong>ATAK (Android)</strong>
              Feature Layer records appear as PLI markers. Custom icons render if the matching
              iconset UUID is installed on the device. Remarks fields appear in the detail callout.
            </div>
          </div>
          <div class="wf-node" style="min-width:130px">
            <div class="wf-icon">💻</div>
            <div class="wf-label">WinTAK</div>
            <div class="wf-sub">Windows TAK</div>
            <div class="wf-tooltip tt-above">
              <strong>WinTAK (Windows)</strong>
              Same CoT stream. The bundled <em>Incident Icons</em> iconset is already
              installed in WinTAK by default — icons from that set will render immediately.
            </div>
          </div>
          <div class="wf-node" style="min-width:130px">
            <div class="wf-icon">🌐</div>
            <div class="wf-label">TAK Web / iTAK</div>
            <div class="wf-sub">Browser / iOS</div>
            <div class="wf-tooltip tt-above">
              <strong>TAK Web / iTAK</strong>
              Any CoT-compatible client connected to the same TAK Server and group
              will receive the Feature Layer records in real time.
            </div>
          </div>
        </div>

      </div><!-- /wf-wrap -->

      <div style="margin-top:32px;padding-top:20px;border-top:1px solid var(--border)">
        <div style="font-size:12px;color:var(--text-dim);display:flex;gap:24px;flex-wrap:wrap">
          <span>⬛ Solid border = active data path</span>
          <span>⬜ Dashed border = supporting component</span>
          <span>ℹ️ Hover any node or arrow for details</span>
        </div>
      </div>
    </div>
  </div>

</div>
<script>
var _logIdx=0,_logPoll=null;

function showTab(name){
  document.querySelectorAll('.tab-panel').forEach(function(p){p.classList.remove('active');});
  document.querySelectorAll('.tab').forEach(function(b){b.classList.remove('active');});
  var p=document.getElementById('tab-'+name);
  var b=document.getElementById('tab-btn-'+name);
  if(p)p.classList.add('active');
  if(b)b.classList.add('active');
}
// On load: jump to tab queued by a previous step (post-deploy → config, etc.)
(function(){
  var goto=sessionStorage.getItem('esri_sync_next_tab');
  if(goto){
    sessionStorage.removeItem('esri_sync_next_tab');
    showTab(goto);
    if(goto==='icons'){if(typeof loadIconsets==='function')loadIconsets();}
    else if(goto==='service'){if(typeof refreshStatus==='function')refreshStatus();}
  }
})();

function toggleAuth(){
  var pub=document.getElementById('layer_public').value==='1';
  var ent=document.getElementById('layer_type').value==='enterprise';
  var authSec=document.getElementById('auth-section');
  var portalGrp=document.getElementById('portal-url-group');
  if(authSec)authSec.style.display=pub?'none':'block';
  if(portalGrp)portalGrp.style.display=(!pub&&ent)?'block':'none';
}
toggleAuth();

// ── Cert setup ──────────────────────────────────────────────────────────────
var _certLogIdx=0,_certLogPoll=null;

function _certGroup(){
  var el=document.getElementById('tak_group');
  return (el&&el.value.trim())||'__ANON__';
}

function _certPassword(){ return 'atakatak'; }

function _certPollStart(){
  _certLogIdx=0;
  var box=document.getElementById('cert-log-box');
  if(box){box.style.display='block';box.textContent='';}
  _certLogPoll=setInterval(_certPollLog,800);
}

function _certPollLog(){
  fetch('/api/esri-tak-sync/setup-cert/log?index='+_certLogIdx,{credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      var box=document.getElementById('cert-log-box');
      var msg=document.getElementById('cert-status-msg');
      if(box&&d.entries&&d.entries.length){box.textContent+=(box.textContent?'\\n':'')+d.entries.join('\\n');box.scrollTop=box.scrollHeight;}
      _certLogIdx=d.total;
      if(!d.running){
        clearInterval(_certLogPoll);_certLogPoll=null;
        var genBtn=document.getElementById('cert-gen-btn');
        var upBtn=document.getElementById('cert-upload-btn');
        if(genBtn)genBtn.disabled=false;
        if(upBtn)upBtn.disabled=false;
        if(d.error){if(msg){msg.textContent='✗ Failed — check log above';msg.style.color='var(--red)';}}
        else if(d.complete){if(msg){msg.textContent='✓ Cert ready — save config and restart the service';msg.style.color='var(--green)';}}
      }
    }).catch(function(){});
}

function runCertSetup(){
  var genBtn=document.getElementById('cert-gen-btn');
  var upBtn=document.getElementById('cert-upload-btn');
  var msg=document.getElementById('cert-status-msg');
  var certNameEl=document.getElementById('cert-name-input');
  var certName=(certNameEl&&certNameEl.value.trim())||'esri-push';
  if(genBtn)genBtn.disabled=true;
  if(upBtn)upBtn.disabled=true;
  if(msg){msg.textContent='Running…';msg.style.color='var(--text-dim)';}
  fetch('/api/esri-tak-sync/setup-cert',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({password:_certPassword(),cert_name:certName,group:_certGroup()}),
    credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(d.error){if(msg){msg.textContent='✗ '+d.error;msg.style.color='var(--red)';}
        if(genBtn)genBtn.disabled=false;if(upBtn)upBtn.disabled=false;return;}
      _certPollStart();
    }).catch(function(){if(msg){msg.textContent='Request failed';msg.style.color='var(--red)';}
      if(genBtn)genBtn.disabled=false;if(upBtn)upBtn.disabled=false;});
}

function uploadCert(){
  var fi=document.getElementById('cert-p12-input');
  if(!fi||!fi.files||!fi.files[0]){alert('Select a .p12 file first');return;}
  var genBtn=document.getElementById('cert-gen-btn');
  var upBtn=document.getElementById('cert-upload-btn');
  var msg=document.getElementById('cert-status-msg');
  if(genBtn)genBtn.disabled=true;
  if(upBtn)upBtn.disabled=true;
  if(msg){msg.textContent='Uploading…';msg.style.color='var(--text-dim)';}
  var fd=new FormData();
  fd.append('file',fi.files[0]);
  fd.append('password',_certPassword());
  fd.append('cert_name','esri-push');
  fd.append('group',_certGroup());
  fetch('/api/esri-tak-sync/setup-cert/upload',{method:'POST',body:fd,credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(d.error){if(msg){msg.textContent='✗ '+d.error;msg.style.color='var(--red)';}
        if(genBtn)genBtn.disabled=false;if(upBtn)upBtn.disabled=false;return;}
      _certPollStart();
    }).catch(function(){if(msg){msg.textContent='Request failed';msg.style.color='var(--red)';}
      if(genBtn)genBtn.disabled=false;if(upBtn)upBtn.disabled=false;});
}
// ── End cert setup ──────────────────────────────────────────────────────────

function toggleAuthMode(){
  var mode=document.getElementById('tak_auth_mode').value;
  var restSec=document.getElementById('rest-auth-section');
  var authSec=document.getElementById('authentik-auth-section');
  var tlsKpSec=document.getElementById('tls-keypair-section');
  var fileSec=document.getElementById('file-output-section');
  var certGen=document.getElementById('cert-gen-section');
  if(restSec)restSec.style.display=mode==='rest'?'block':'none';
  if(authSec)authSec.style.display=mode==='authentik'?'block':'none';
  if(tlsKpSec)tlsKpSec.style.display=mode==='tls_keypair'?'block':'none';
  if(fileSec)fileSec.style.display=mode==='file'?'block':'none';
  if(certGen)certGen.style.display=(mode==='cert'||mode==='tls_keypair')?'block':'none';
  var portEl=document.getElementById('tak_port');
  if(portEl){
    if((mode==='rest'||mode==='authentik')&&(portEl.value==='8089'||portEl.value==='8087'))portEl.value='8443';
    else if((mode==='cert'||mode==='tls_keypair')&&(portEl.value==='8443'||portEl.value==='8087'))portEl.value='8089';
    else if(mode==='plain'&&(portEl.value==='8443'||portEl.value==='8089'))portEl.value='8087';
  }
}

function saveConfig(){
  var msg=document.getElementById('save-msg');
  if(msg){msg.textContent='Saving…';msg.style.color='var(--text-dim)';}
  var payload={
    tak_host:document.getElementById('tak_host').value,
    tak_port:parseInt(document.getElementById('tak_port').value)||8089,
    tak_auth_mode:document.getElementById('tak_auth_mode').value,
    tak_username:(document.getElementById('tak_username')||{value:''}).value,
    tak_password:(document.getElementById('tak_password')||{value:''}).value,
    tak_cert_name:(document.getElementById('cert-name-input')||{value:'esri-push'}).value.trim()||'esri-push',
    tak_username:(document.getElementById('tak_username')||{value:''}).value,
    tak_password:(document.getElementById('tak_password')||{value:''}).value,
    cert_file:(document.getElementById('cert_file')||{value:''}).value.trim(),
    key_file:(document.getElementById('key_file')||{value:''}).value.trim(),
    output_file:(document.getElementById('output_file')||{value:'/opt/Esri-TAKServer-Sync/cot_output.txt'}).value.trim(),
    layer_url:document.getElementById('layer_url').value,
    layer_public:document.getElementById('layer_public').value==='1',
    layer_type:document.getElementById('layer_type').value,
    esri_username:document.getElementById('esri_username').value,
    esri_password:document.getElementById('esri_password').value,
    portal_url:document.getElementById('portal_url').value,
    poll_interval:parseInt(document.getElementById('poll_interval').value)||30,
    page_size:parseInt(document.getElementById('page_size').value)||1000,
    uid_field:document.getElementById('uid_field').value,
    uid_prefix:document.getElementById('uid_prefix').value,
    callsign_field:document.getElementById('callsign_field').value,
    cot_type:document.getElementById('cot_type').value,
    lat_field:document.getElementById('lat_field').value,
    lon_field:document.getElementById('lon_field').value,
    altitude_field:document.getElementById('altitude_field').value,
    stale_minutes:parseInt(document.getElementById('stale_minutes').value)||5,
    cot_how:document.getElementById('cot_how').value,
    remarks_fields:document.getElementById('remarks_fields').value,
    delta_enabled:document.getElementById('delta_enabled').value==='1',
    delta_field:document.getElementById('delta_field').value,
    tak_group:(document.getElementById('tak_group')||{value:''}).value.trim()
  };
  fetch('/api/esri-tak-sync/save-config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(!msg)return;
      if(d.success){msg.textContent='✓ Saved — opening Icons…';msg.style.color='var(--green)';setTimeout(function(){msg.textContent='';showTab('icons');if(typeof loadIconsets==='function')loadIconsets();},1500);}
      else{msg.textContent='✗ Error';msg.style.color='var(--red)';}
    }).catch(function(){if(msg){msg.textContent='Request failed';msg.style.color='var(--red)';}});
}

function startDeploy(){
  var btn=document.getElementById('deploy-btn');
  var box=document.getElementById('deploy-log-box');
  if(btn){btn.disabled=true;btn.textContent='⏳ Installing…';}
  if(box){box.style.display='block';box.textContent='';}
  _logIdx=0;
  fetch('/api/esri-tak-sync/install',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(d.error){if(btn){btn.disabled=false;btn.textContent='✗ Error — Retry';btn.className='btn btn-danger';}}
      else{_logPoll=setInterval(pollLog,1200);}
    }).catch(function(){if(btn){btn.disabled=false;btn.textContent='✗ Failed';btn.className='btn btn-danger';}});
}

function pollLog(){
  fetch('/api/esri-tak-sync/install/log?index='+_logIdx,{credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      var box=document.getElementById('deploy-log-box');
      if(box&&d.entries&&d.entries.length>0){box.textContent+=(box.textContent?'\\n':'')+d.entries.join('\\n');box.scrollTop=box.scrollHeight;}
      _logIdx=d.total;
      var btn=document.getElementById('deploy-btn');
      var msg=document.getElementById('deploy-status-msg');
      if(!d.running){
        clearInterval(_logPoll);_logPoll=null;
        if(d.error){if(btn){btn.disabled=false;btn.textContent='✗ Failed — Retry';btn.className='btn btn-danger';}if(msg){msg.textContent='Failed';msg.style.color='var(--red)';}}
        else if(d.complete){if(msg){msg.textContent='✓ Done — opening Config…';msg.style.color='var(--green)';}setTimeout(function(){sessionStorage.setItem('esri_sync_next_tab','config');location.reload();},1500);}
      }
    }).catch(function(){});
}

function refreshStatus(){
  fetch('/api/esri-tak-sync/service-status',{credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      var badge=document.getElementById('svc-badge');
      var txt=document.getElementById('svc-status-text');
      if(!badge)return;
      var active=d.active;
      badge.className='status-pill '+(active?'pill-active':'pill-inactive');
      if(txt)txt.textContent=d.status||'unknown';
    }).catch(function(){});
}

function svcControl(action){
  var msg=document.getElementById('svc-ctrl-msg');
  if(msg){msg.textContent=action+'ing…';msg.style.color='var(--text-dim)';}
  fetch('/api/esri-tak-sync/service-control',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:action}),credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(msg){msg.textContent=d.success?'✓ Done':'✗ Failed';msg.style.color=d.success?'var(--green)':'var(--red)';setTimeout(function(){msg.textContent='';},2500);}
      setTimeout(refreshStatus,800);
    }).catch(function(){if(msg){msg.textContent='Request failed';msg.style.color='var(--red)';}});
}

function uninstall(){
  if(!confirm('Remove FeatureLayer → CoT? This deletes {{ install_dir }} and the systemd service. Config in infra-TAK settings is kept.'))return;
  var msg=document.getElementById('uninstall-msg');
  if(msg){msg.textContent='Uninstalling…';msg.style.color='var(--text-dim)';}
  fetch('/api/esri-tak-sync/uninstall',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(d.success){if(msg){msg.textContent='✓ Removed';msg.style.color='var(--green)';}setTimeout(function(){location.href='/esri-tak-sync';},1200);}
      else{if(msg){msg.textContent='✗ Failed';msg.style.color='var(--red)';}}
    }).catch(function(){if(msg){msg.textContent='Request failed';msg.style.color='var(--red)';}});
}

/* ── Icon management ──────────────────────────────────────────────────────── */
var _iconsets=[];        // [{uuid,name,group,icons:[{name,path}]}]
var _mappingRows=[];     // [{col_value, iconsetpath}]
var _pickerTarget=null;  // index into _mappingRows being edited

function loadIconsets(){
  fetch('/api/esri-tak-sync/icons/list',{credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      _iconsets=d.iconsets||[];
      renderIconsetList();
      renderMappingRows();
    }).catch(function(e){
      var el=document.getElementById('iconset-list');
      if(el)el.innerHTML='<span style="color:var(--red);font-size:13px">Failed to load iconsets</span>';
    });
}

function renderIconsetList(){
  var el=document.getElementById('iconset-list');
  if(!el)return;
  if(!_iconsets.length){el.innerHTML='<span style="color:var(--text-dim);font-size:13px">No iconsets installed.</span>';return;}
  var html='';
  _iconsets.forEach(function(s){
    html+='<div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border)">';
    html+='<div style="flex:1"><strong>'+s.name+'</strong> <span style="font-size:11px;color:var(--text-dim)">'+s.uuid+'</span>';
    html+='<br><span style="font-size:12px;color:var(--text-secondary)">'+s.icons.length+' icons · group: '+s.group+'</span></div>';
    html+='<button class="btn btn-ghost" style="padding:4px 12px;font-size:12px;color:var(--red)" onclick="deleteIconset(this.dataset.uuid,this.dataset.name)" data-uuid="'+s.uuid+'" data-name="'+_esc(s.name)+'">🗑 Remove</button>';
    html+='</div>';
    // show first few icons as previews
    var preview='<div style="display:flex;flex-wrap:wrap;gap:6px;padding:8px 0 4px">';
    var shown=s.icons.slice(0,12);
    shown.forEach(function(ic){
      var imgPath='/api/esri-tak-sync/icons/img/'+encodeURI(ic.path);
      preview+='<img src="'+imgPath+'" title="'+_esc(ic.name)+'" style="width:28px;height:28px;object-fit:contain;background:var(--surface);border-radius:4px;padding:2px">';
    });
    if(s.icons.length>12)preview+='<span style="font-size:11px;color:var(--text-dim);align-self:center">+'+((s.icons.length-12))+' more</span>';
    preview+='</div>';
    html+=preview;
  });
  el.innerHTML=html;
}

function uploadIconset(){
  var fi=document.getElementById('icon-zip-input');
  if(!fi||!fi.files||!fi.files[0]){alert('Select a .zip file first');return;}
  var fd=new FormData();
  fd.append('file',fi.files[0]);
  var msg=document.getElementById('upload-msg');
  if(msg){msg.textContent='Uploading…';msg.style.color='var(--text-dim)';}
  fetch('/api/esri-tak-sync/icons/upload',{method:'POST',body:fd,credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(d.success){
        if(msg){msg.textContent='✓ Uploaded: '+d.name;msg.style.color='var(--green)';}
        fi.value='';
        loadIconsets();
      } else {
        if(msg){msg.textContent='✗ '+(d.error||'Upload failed');msg.style.color='var(--red)';}
      }
    }).catch(function(){if(msg){msg.textContent='Request failed';msg.style.color='var(--red)';}});
}

function deleteIconset(uuid,name){
  if(!confirm('Remove iconset "'+name+'"?'))return;
  fetch('/api/esri-tak-sync/icons/delete',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({uuid:uuid}),credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(d.success){loadIconsets();}
      else{alert('Delete failed: '+(d.error||'unknown'));}
    });
}

function renderMappingRows(){
  // seed from server-side rendered hidden input on first load
  if(!_mappingRows.length){
    var stored=document.getElementById('icon-map-data');
    if(stored){try{
      var m=JSON.parse(stored.textContent)||{};
      _mappingRows=Object.keys(m).map(function(k){return {col_value:k,iconsetpath:m[k]};});
    }catch(e){_mappingRows=[];}}
  }
  _rebuildRowsDOM();
}

var _layerValuesCache={};  // column → [values]

function fetchLayerColumns(){
  var btn=document.getElementById('fetch-cols-btn');
  var msg=document.getElementById('fetch-cols-msg');
  if(btn){btn.disabled=true;btn.textContent='↻ Loading…';}
  if(msg){msg.textContent='';msg.style.color='var(--text-dim)';}
  fetch('/api/esri-tak-sync/layer-columns',{credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(btn){btn.disabled=false;btn.textContent='↻ Load';}
      if(d.error){if(msg){msg.textContent='✗ '+d.error;msg.style.color='var(--red)';}return;}
      var dl=document.getElementById('col-datalist');
      if(dl){dl.innerHTML='';d.columns.forEach(function(c){var o=document.createElement('option');o.value=c;dl.appendChild(o);});}
      if(msg){msg.textContent='✓ '+d.columns.length+' columns loaded — start typing to autocomplete';msg.style.color='var(--green)';}
    }).catch(function(e){
      if(btn){btn.disabled=false;btn.textContent='↻ Load';}
      if(msg){msg.textContent='✗ Request failed';msg.style.color='var(--red)';}
    });
}

function addMappingRow(){
  var col=(document.getElementById('icon-column')||{}).value||'';
  col=col.trim();
  if(!col){
    // No column set — fall back to blank row
    addBlankMappingRow();
    return;
  }
  var btn=document.getElementById('add-row-btn');
  if(btn){btn.disabled=true;btn.textContent='Loading…';}
  var cached=_layerValuesCache[col];
  if(cached!==undefined){
    if(btn){btn.disabled=false;btn.textContent='+ Add Row';}
    _showValuePicker(col,cached);
    return;
  }
  fetch('/api/esri-tak-sync/layer-values?column='+encodeURIComponent(col),{credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(btn){btn.disabled=false;btn.textContent='+ Add Row';}
      if(d.error){alert('Could not load values: '+d.error);return;}
      _layerValuesCache[col]=d.values||[];
      _showValuePicker(col,_layerValuesCache[col]);
    }).catch(function(){
      if(btn){btn.disabled=false;btn.textContent='+ Add Row';}
      alert('Failed to load column values. Check layer config.');
    });
}

function _showValuePicker(col,values){
  var modal=document.getElementById('value-picker-modal');
  var label=document.getElementById('value-picker-col-label');
  var loading=document.getElementById('value-picker-loading');
  var chips=document.getElementById('value-picker-chips');
  if(!modal)return;
  if(label)label.textContent=col;
  if(loading)loading.style.display='none';
  if(chips){
    // Filter out values already mapped
    var mapped=_mappingRows.map(function(r){return r.col_value;});
    var remaining=values.filter(function(v){return mapped.indexOf(v)===-1;});
    if(remaining.length===0){
      chips.innerHTML='<span style="font-size:13px;color:var(--text-dim)">All values in this column already have mappings.</span>';
    } else {
      chips.innerHTML='';
      remaining.forEach(function(v){
        var chip=document.createElement('button');
        chip.className='btn btn-ghost';
        chip.style.cssText='font-size:12px;padding:5px 12px;border-radius:20px';
        chip.textContent=v;
        chip.onclick=function(){
          _mappingRows.push({col_value:v,iconsetpath:''});
          _rebuildRowsDOM();
          closeValuePicker();
        };
        chips.appendChild(chip);
      });
    }
  }
  modal.style.display='flex';
}

function closeValuePicker(){
  var modal=document.getElementById('value-picker-modal');
  if(modal)modal.style.display='none';
}

function addBlankMappingRow(){
  _mappingRows.push({col_value:'',iconsetpath:''});
  _rebuildRowsDOM();
  closeValuePicker();
}

function _rebuildRowsDOM(){
  var container=document.getElementById('mapping-rows');
  if(!container)return;
  if(!_mappingRows.length){
    container.innerHTML='<span style="font-size:13px;color:var(--text-dim)">No mappings defined. Click "+ Add Row" to map a column value to an icon.</span>';
    return;
  }
  var html='';
  _mappingRows.forEach(function(row,i){
    // Normalize backslashes → forward slashes (Windows zips may have stored them with \)
    if(row.iconsetpath)row.iconsetpath=row.iconsetpath.replace(/\\\\/g,'/');
    var previewUrl=row.iconsetpath?'/api/esri-tak-sync/icons/img/'+encodeURI(row.iconsetpath):'';
    html+='<div style="display:flex;align-items:center;gap:10px;background:var(--surface);padding:10px;border-radius:6px">';
    html+='<input type="text" placeholder="Column value" value="'+_esc(row.col_value)+'" style="flex:1;min-width:0"'
         +' onchange="_mappingRows['+i+'].col_value=this.value">';
    html+='<div style="display:flex;align-items:center;gap:8px;cursor:pointer;border:1px solid var(--border);border-radius:6px;padding:6px 10px;background:var(--bg)" onclick="openPicker('+i+')">';
    if(previewUrl){
      html+='<img src="'+previewUrl+'" style="width:24px;height:24px;object-fit:contain">';
    }
    var label=row.iconsetpath?row.iconsetpath.split('/').pop():'Select icon…';
    html+='<span style="font-size:12px;color:var(--text-secondary)">'+_esc(label)+'</span>';
    html+='</div>';
    html+='<button class="btn btn-ghost" style="padding:4px 10px;font-size:12px;color:var(--red)" onclick="_mappingRows.splice('+i+',1);_rebuildRowsDOM()">✕</button>';
    html+='</div>';
  });
  container.innerHTML=html;
}

function _esc(s){return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');}

// Flat list of all icons built once when picker opens: [{set,name,path}]
var _pickerAllIcons=[];

function openPicker(rowIdx){
  _pickerTarget=rowIdx;
  var modal=document.getElementById('icon-picker-modal');
  var grid=document.getElementById('picker-grid');
  var search=document.getElementById('picker-search');
  if(!modal||!grid)return;
  // Build flat icon list from all installed iconsets
  _pickerAllIcons=[];
  _iconsets.forEach(function(s){
    s.icons.forEach(function(ic){
      _pickerAllIcons.push({set:s.name, name:ic.name, path:ic.path});
    });
  });
  if(search){search.value='';search.focus();}
  _pickerFilter('');
  modal.style.display='flex';
}

function _pickerFilter(q){
  var grid=document.getElementById('picker-grid');
  var countEl=document.getElementById('picker-count');
  if(!grid)return;
  var term=q.trim().toLowerCase();
  var filtered=term?_pickerAllIcons.filter(function(ic){
    return ic.name.toLowerCase().indexOf(term)!==-1||ic.set.toLowerCase().indexOf(term)!==-1;
  }):_pickerAllIcons;
  if(countEl)countEl.textContent=filtered.length+' icon'+(filtered.length===1?'':'s');
  if(!filtered.length){
    grid.innerHTML='<p style="color:var(--text-dim);font-size:13px;grid-column:1/-1">'
      +(_pickerAllIcons.length?'No icons match "'+_esc(q)+'".':'No iconsets installed. Upload one in the Upload card above.')
      +'</p>';
    return;
  }
  // Group by iconset name
  var groups={};var order=[];
  filtered.forEach(function(ic){
    if(!groups[ic.set]){groups[ic.set]=[];order.push(ic.set);}
    groups[ic.set].push(ic);
  });
  var html='';
  order.forEach(function(setName){
    // Only show group header when not filtering, or when >1 group matches
    if(!term||order.length>1){
      html+='<div style="font-size:12px;font-weight:600;color:var(--text-secondary);padding:8px 0 4px;grid-column:1/-1">'+_esc(setName)+'</div>';
    }
    groups[setName].forEach(function(ic){
      var imgPath='/api/esri-tak-sync/icons/img/'+encodeURI(ic.path);
      html+='<div onclick="pickIcon(this.dataset.path)" data-path="'+_esc(ic.path)+'" title="'+_esc(ic.name)+'" class="picker-icon-cell">'
           +'<img src="'+imgPath+'" style="width:32px;height:32px;object-fit:contain" loading="lazy">'
           +'<span style="font-size:10px;color:var(--text-secondary);text-align:center;word-break:break-word;line-height:1.3">'+_esc(ic.name)+'</span>'
           +'</div>';
    });
  });
  grid.innerHTML=html;
}

function closePicker(){
  var modal=document.getElementById('icon-picker-modal');
  if(modal)modal.style.display='none';
  _pickerTarget=null;
  _pickerAllIcons=[];
}

function pickIcon(iconsetpath){
  if(_pickerTarget==='__default__'){
    var el=document.getElementById('icon-default-path');
    if(el){el.value=iconsetpath;}
    var prev=document.getElementById('preview-__default__');
    if(prev){prev.src='/api/esri-tak-sync/icons/img/'+encodeURI(iconsetpath);prev.style.display='';}
  } else if(_pickerTarget!==null&&_mappingRows[_pickerTarget]!==undefined){
    _mappingRows[_pickerTarget].iconsetpath=iconsetpath;
    _rebuildRowsDOM();
  }
  closePicker();
}

function saveIconMapping(){
  var enabled=document.getElementById('icon-enabled');
  var colField=document.getElementById('icon-column');
  var defPath=document.getElementById('icon-default-path');
  var msg=document.getElementById('icon-save-msg');
  var payload={
    enabled: enabled?(enabled.value==='1'):false,
    column: colField?colField.value.trim():'',
    default_iconsetpath: defPath?defPath.value.trim():'',
    map: {}
  };
  _mappingRows.forEach(function(r){
    if(r.col_value&&r.iconsetpath)payload.map[r.col_value]=r.iconsetpath;
  });
  if(msg){msg.textContent='Saving…';msg.style.color='var(--text-dim)';}
  fetch('/api/esri-tak-sync/icons/save-mapping',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload),credentials:'same-origin'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(d.success){if(msg){msg.textContent='✓ Saved — opening Service…';msg.style.color='var(--green)';setTimeout(function(){msg.textContent='';showTab('service');if(typeof refreshStatus==='function')refreshStatus();},1500);}}
      else{if(msg){msg.textContent='✗ '+(d.error||'Save failed');msg.style.color='var(--red)';}}
    }).catch(function(){if(msg){msg.textContent='Request failed';msg.style.color='var(--red)';}});
}

{% if deploying %}
_logPoll=setInterval(pollLog,1200);
{% endif %}
// Close modals on Escape
document.addEventListener('keydown',function(e){
  if(e.key==='Escape'){
    var ip=document.getElementById('icon-picker-modal');if(ip&&ip.style.display!=='none')closePicker();
    var vp=document.getElementById('value-picker-modal');if(vp&&vp.style.display!=='none')closeValuePicker();
  }
});
// Close modals when clicking backdrop
var _pm=document.getElementById('icon-picker-modal');
if(_pm)_pm.addEventListener('click',function(e){if(e.target===this)closePicker();});
var _vpm=document.getElementById('value-picker-modal');
if(_vpm)_vpm.addEventListener('click',function(e){if(e.target===this)closeValuePicker();});
</script>
</body></html>'''


