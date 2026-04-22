import os, json
from functools import wraps
from flask import request, session, redirect, url_for, jsonify

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.environ.get('CONFIG_DIR') or os.path.join(BASE_DIR, '.config')


def load_settings():
    p = os.path.join(CONFIG_DIR, 'settings.json')
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}


def save_settings(s):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    p = os.path.join(CONFIG_DIR, 'settings.json')
    with open(p, 'w') as f:
        json.dump(s, f, indent=2)
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass


def _apply_authentik_session():
    if request.remote_addr not in ('127.0.0.1', '::1'):
        return False
    uname = request.headers.get('X-Authentik-Username')
    if uname:
        session['authenticated'] = True
        session['authentik_username'] = uname
        return True
    return False


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if _apply_authentik_session():
            return f(*args, **kwargs)
        if not session.get('authenticated'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Unauthorized', 'login_required': True}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated
