"""
esri.py — Esri CoT Bridge module for infra-TAK

Registers /esri and /api/esri/* routes directly on the Flask app.
Call register_routes(app, login_required, load_settings, save_settings) from app.py.

What it does:
  - Checks whether Node-RED is installed/running; if not, prompts to install it
  - Provides a configurator: Survey123 URL, field mapping, icon mapping, TAKServer settings
  - Generates and deploys a Node-RED flow to the local Node-RED Admin API (localhost:1880)
  - Saves config to .config/settings.json under key 'esri_cot_bridge'
"""

import json
import os
import urllib.request
import urllib.parse
import urllib.error

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_ICON_HASH = '412c43f948b1664a3a0b513336b6c32382b13289a6ed2e91dd31e23d9d52a683'

INCIDENT_ICONS = {
    'Area Command':                      f'{_ICON_HASH}/Incident Icons/Area Command Post.png',
    'CAP Unit Position update':          f'{_ICON_HASH}/Incident Icons/CAP Asset Report.png',
    'Clue Location':                     f'{_ICON_HASH}/Incident Icons/CLUE.png',
    'ELT Signal':                        f'{_ICON_HASH}/Incident Icons/ELT Signal.png',
    'Flood/Water Level (HWM)':           f'{_ICON_HASH}/Incident Icons/Flood.png',
    'Hazard, Animal':                    f'{_ICON_HASH}/Incident Icons/Animal.png',
    'Hazard, Electrical':                f'{_ICON_HASH}/Incident Icons/Electrical.png',
    'Hazard, Fire':                      f'{_ICON_HASH}/Incident Icons/Fire.png',
    'Hazard, Haz Materials':             f'{_ICON_HASH}/Incident Icons/Hazard, Haz Materials.png',
    'Hazard, Other':                     f'{_ICON_HASH}/Incident Icons/Hazard, Other.png',
    'Helicopter Landing Zone':           f'{_ICON_HASH}/Incident Icons/Helicopter Landing Zone.png',
    'Incident Command Post':             f'{_ICON_HASH}/Incident Icons/Incident Command Post.png',
    'Initial Planning Point':            f'{_ICON_HASH}/Incident Icons/Initial Planning Point.png',
    'Initial Planning Point (PLS, LKP)': f'{_ICON_HASH}/Incident Icons/Initial Planning Point.png',
    'Medical Station':                   f'{_ICON_HASH}/Incident Icons/EMS.png',
    'Placeholder Other':                 f'{_ICON_HASH}/Incident Icons/Placeholder Other.png',
    'Plane Crash':                       f'{_ICON_HASH}/Incident Icons/Crash Site.png',
    'PLT/PLB Signal':                    f'{_ICON_HASH}/Incident Icons/PLT Signal.png',
    'Staging':                           f'{_ICON_HASH}/Incident Icons/Staging Area.png',
    'Structure, Damaged':                f'{_ICON_HASH}/Incident Icons/Structure, Damaged.png',
    'Structure, Destroyed':              f'{_ICON_HASH}/Incident Icons/Structure, Destroyed.png',
    'Structure, Failed':                 f'{_ICON_HASH}/Incident Icons/Structure, Failed.png',
    'Structure, No Damage':              f'{_ICON_HASH}/Incident Icons/Structure, No-Damage.png',
    'Transportation, Route Block':       f'{_ICON_HASH}/Incident Icons/Transportation, Route Block.png',
}
DEFAULT_ICON = f'{_ICON_HASH}/Incident Icons/Placeholder Other.png'
DEFAULT_COT_TYPE = 'a-h-G'
ESRI_KEY = 'esri_cot_bridge'

CONFIG_DIR = os.environ.get('CONFIG_DIR') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '.config'
)

# ─────────────────────────────────────────────────────────────────────────────
# Settings helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_cfg(load_settings):
    return load_settings().get(ESRI_KEY, {})

def _save_cfg(data, load_settings, save_settings):
    s = load_settings()
    s[ESRI_KEY] = data
    save_settings(s)

# ─────────────────────────────────────────────────────────────────────────────
# Node-RED Admin API helpers
# ─────────────────────────────────────────────────────────────────────────────

def _nr_request(method, path, body=None, host='localhost', port=1880, timeout=8):
    url = f'http://{host}:{port}{path}'
    data = json.dumps(body).encode() if body is not None else None
    headers = {'Content-Type': 'application/json', 'Node-RED-API-Version': 'v2'}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body_text = e.read().decode()
        except Exception:
            body_text = ''
        return False, {'error': f'HTTP {e.code}: {e.reason}', 'detail': body_text}
    except Exception as e:
        return False, {'error': str(e)}


def _nr_running(host='localhost', port=1880):
    ok, _ = _nr_request('GET', '/settings', host=host, port=port, timeout=4)
    return ok


def _deploy_to_nodered(new_nodes, host='localhost', port=1880):
    """Merge new_nodes into Node-RED, replacing any existing Esri CoT Bridge tabs."""
    ok, current = _nr_request('GET', '/flows', host=host, port=port)
    if not ok:
        return False, f'Cannot reach Node-RED at {host}:{port} — {current.get("error", "")}'

    rev = current.get('rev', '')
    existing = current.get('flows', current if isinstance(current, list) else [])

    our_labels = {'Survey123 → TAKServer', 'TAKServer CoT Logger'}
    our_tab_ids = {
        n['id'] for n in existing
        if n.get('type') == 'tab' and n.get('label', '') in our_labels
    }
    # Remove old esri tab nodes and the shared TLS config we own
    kept = [
        n for n in existing
        if n.get('id') not in our_tab_ids
        and n.get('z') not in our_tab_ids
        and not (n.get('type') == 'tls-config' and n.get('name') == 'TAK Server TLS (Esri)')
    ]

    merged = kept + new_nodes
    payload = {'flows': merged}
    if rev:
        payload['rev'] = rev

    ok2, res = _nr_request('POST', '/flows', body=payload, host=host, port=port)
    if not ok2:
        return False, f'Deploy failed — {res.get("error", res)}'
    return True, 'Flow deployed to Node-RED successfully'

# ─────────────────────────────────────────────────────────────────────────────
# Flow generation
# ─────────────────────────────────────────────────────────────────────────────

def _js(s):
    """Escape a Python string for embedding in a JS single-quoted string literal."""
    return (s or '').replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n')


def _build_url_fn(survey_url, token):
    return '\n'.join([
        '// Configured via infra-TAK Esri CoT Bridge — do not edit here',
        f"const SURVEY123_URL = '{_js(survey_url)}';",
        f"const SURVEY123_TOKEN = '{_js(token)}';",
        "if (!SURVEY123_URL) {",
        "    node.error('SURVEY123_URL not configured — open infra-TAK → Esri CoT Bridge');",
        "    node.status({fill: 'red', shape: 'ring', text: 'not configured'});",
        "    return null;",
        "}",
        "let url = SURVEY123_URL.trim() + '?where=1%3D1&outFields=*&outSR=4326&f=json';",
        "if (SURVEY123_TOKEN) url += '&token=' + encodeURIComponent(SURVEY123_TOKEN.trim());",
        "msg.url = url;",
        "return msg;",
    ])


def _build_cot_fn(field_map, icon_map, cot_type):
    fm = field_map or {}
    icons = icon_map if icon_map else INCIDENT_ICONS
    lines = [
        '// Field + icon mapping configured via infra-TAK Esri CoT Bridge',
        f"const F_CALLSIGN    = '{_js(fm.get('callsign', 'team_callsign'))}';",
        f"const F_MISSION     = '{_js(fm.get('mission_number', 'mission_number'))}';",
        f"const F_SORTIE      = '{_js(fm.get('sortie_number', 'sortie_number'))}';",
        f"const F_LEADER_NAME = '{_js(fm.get('leader_name', 'team_leader_name'))}';",
        f"const F_LEADER_CAPID= '{_js(fm.get('leader_capid', 'team_leader_capid'))}';",
        f"const F_WAYPOINT    = '{_js(fm.get('waypoint_type', 'select_a_waypoint_of_what_you_a'))}';",
        f"const COT_TYPE      = '{_js(cot_type or DEFAULT_COT_TYPE)}';",
        '',
        f'const iconPaths = {json.dumps(icons, indent=2)};',
        f"const defaultIcon = '{_js(DEFAULT_ICON)}';",
        'function getIcon(v) { return iconPaths[v] || defaultIcon; }',
        '',
        'let data = msg.payload;',
        "if (typeof data === 'string') {",
        '    try { data = JSON.parse(data); } catch(e) {',
        "        node.error('Parse error: ' + e.message); return null;",
        '    }',
        '}',
        'if (!data || !data.features || data.features.length === 0) {',
        "    node.warn('No features from Survey123');",
        "    node.status({fill: 'yellow', shape: 'ring', text: 'no features'});",
        '    return null;',
        '}',
        'const now = new Date();',
        'const stale = new Date(now.getTime() + 5 * 60 * 1000);',
        'const timeStr = now.toISOString();',
        'const staleStr = stale.toISOString();',
        'const events = [];',
        'for (const feature of data.features) {',
        '    const a = feature.attributes;',
        '    const geom = feature.geometry;',
        '    if (!geom || geom.x == null || geom.y == null) continue;',
        '    const lat = geom.y, lon = geom.x;',
        '    const objectid = a.objectid;',
        "    const callsign   = a[F_CALLSIGN]     || 'UNKNOWN';",
        "    const missionNum = a[F_MISSION]       || '';",
        "    const sortieNum  = a[F_SORTIE]        || '';",
        "    const leaderName = a[F_LEADER_NAME]   || '';",
        "    const leaderCapid= a[F_LEADER_CAPID]  || '';",
        "    const waypointType = a[F_WAYPOINT]    || '';",
        '    const creationDate = a.CreationDate;',
        '    const iconPath = getIcon(waypointType);',
        '    const creationDateStr = creationDate',
        "        ? new Date(creationDate).toISOString().replace('T', ' ').replace('Z', '').slice(0, 23)",
        "        : '';",
        "    const remarks = 'Mission Number: ' + missionNum",
        "        + ', Sortie Number: ' + sortieNum",
        "        + ', Team Leader Name: ' + leaderName",
        "        + ', Team Leader CAPID: ' + leaderCapid",
        "        + ', Callsign: ' + callsign",
        "        + ', Latitude: ' + lat + ', Longitude: ' + lon",
        "        + ', TimeSubmitted: ' + creationDateStr",
        "        + ', ObjectID: ' + objectid;",
        # Template literal — double quotes inside need \" in JSON but are fine as-is in Python str
        '    const event = `<?xml version="1.0" encoding="UTF-8"?>'
        '<event version="2.0" uid="Survey123_${objectid}" type="${COT_TYPE}" '
        'time="${timeStr}" start="${timeStr}" stale="${staleStr}" how="m-g">'
        '<point lat="${lat}" lon="${lon}" hae="0" ce="10.0" le="2.0" />'
        '<detail><UID>Survey123_${callsign} ${creationDateStr}</UID>'
        '<usericon iconsetpath="${iconPath}" />'
        '<remarks>${remarks}</remarks>'
        '<contact callsign="${callsign}" />'
        '<track speed="0" course="0" /></detail></event>`;',
        '    events.push(event);',
        '}',
        'if (events.length === 0) {',
        "    node.warn('No valid features to convert');",
        "    node.status({fill: 'yellow', shape: 'ring', text: 'no valid features'});",
        '    return null;',
        '}',
        "msg.payload = events.join('\\n');",
        "node.status({fill: 'green', shape: 'dot', text: events.length + ' events sent'});",
        'return msg;',
    ]
    return '\n'.join(lines)


_FILTER_FN = '\n'.join([
    'const data = msg.payload;',
    "if (!data || data.trim() === '') return null;",
    "const messages = data.split('<?xml version=\"1.0\" encoding=\"UTF-8\"?>');",
    'function isSurvey123(m) {',
    '    const match = m.match(/uid="([^"]+)"/);',
    "    return match && match[1].startsWith('Survey123_');",
    '}',
    "const filtered = messages.filter(m => m.trim() !== '' && !isSurvey123(m));",
    "if (filtered.length === 0) { msg.payload = ''; return null; }",
    "msg.payload = filtered.join('<?xml version=\"1.0\" encoding=\"UTF-8\"?>');",
    "node.status({fill: 'blue', shape: 'dot', text: filtered.length + ' CoT logged'});",
    'return msg;',
])


def _generate_flow_nodes(cfg):
    tab1    = 'esri_t1'
    tab2    = 'esri_t2'
    tls_id  = 'esri_tls'
    tak_host  = cfg.get('tak_host', '')
    tak_port  = str(int(cfg.get('tak_port', 8089)))
    tls_cert  = cfg.get('tls_cert', '')
    tls_key   = cfg.get('tls_key', '')
    tls_ca    = cfg.get('tls_ca', '')
    log_file  = cfg.get('log_file', 'cot-logged.txt')
    poll      = str(int(cfg.get('poll_interval', 60)))

    url_fn  = _build_url_fn(cfg.get('survey_url', ''), cfg.get('token', ''))
    cot_fn  = _build_cot_fn(
        cfg.get('field_mapping', {}),
        cfg.get('icon_mapping', {}),
        cfg.get('cot_type', DEFAULT_COT_TYPE),
    )

    return [
        # ── Tab 1: Survey123 → TAKServer ──────────────────────────────────
        {'id': tab1, 'type': 'tab', 'label': 'Survey123 → TAKServer',
         'disabled': False, 'info': 'Managed by infra-TAK Esri CoT Bridge', 'env': []},
        {'id': 'esri_inj', 'type': 'inject', 'z': tab1,
         'name': f'Poll every {poll}s',
         'props': [{'p': 'payload'}], 'repeat': poll, 'crontab': '', 'once': True,
         'onceDelay': 2, 'topic': '', 'payload': '', 'payloadType': 'str',
         'x': 150, 'y': 160, 'wires': [['esri_fn_url']]},
        {'id': 'esri_fn_url', 'type': 'function', 'z': tab1,
         'name': 'Build Survey123 URL', 'func': url_fn,
         'outputs': 1, 'timeout': 0, 'noerr': 0, 'initialize': '', 'finalize': '', 'libs': [],
         'x': 360, 'y': 160, 'wires': [['esri_http']]},
        {'id': 'esri_http', 'type': 'http request', 'z': tab1,
         'name': 'Fetch Survey123 Features', 'method': 'GET', 'ret': 'obj',
         'paytoqs': 'ignore', 'url': '', 'tls': '', 'persist': False,
         'proxy': '', 'insecureHTTPParser': False, 'authType': '', 'senderr': False, 'headers': [],
         'x': 580, 'y': 160, 'wires': [['esri_fn_cot']]},
        {'id': 'esri_fn_cot', 'type': 'function', 'z': tab1,
         'name': 'Convert to CoT XML', 'func': cot_fn,
         'outputs': 1, 'timeout': 0, 'noerr': 0, 'initialize': '', 'finalize': '', 'libs': [],
         'x': 800, 'y': 160, 'wires': [['esri_tcp_out', 'esri_dbg_cot']]},
        {'id': 'esri_tcp_out', 'type': 'tcp out', 'z': tab1,
         'name': 'Send to TAKServer', 'host': tak_host, 'port': tak_port,
         'beserver': 'client', 'base64': False, 'end': False, 'tls': tls_id,
         'x': 1020, 'y': 120, 'wires': []},
        {'id': 'esri_dbg_cot', 'type': 'debug', 'z': tab1, 'name': 'CoT Preview',
         'active': True, 'tosidebar': True, 'console': False, 'tostatus': False,
         'complete': 'payload', 'targetType': 'msg', 'statusVal': '', 'statusType': 'auto',
         'x': 1020, 'y': 200, 'wires': []},
        # ── Tab 2: TAKServer CoT Logger ───────────────────────────────────
        {'id': tab2, 'type': 'tab', 'label': 'TAKServer CoT Logger',
         'disabled': False, 'info': 'Managed by infra-TAK Esri CoT Bridge', 'env': []},
        {'id': 'esri_tcp_in', 'type': 'tcp in', 'z': tab2,
         'name': 'Receive from TAKServer', 'server': 'client',
         'host': tak_host, 'port': tak_port, 'datamode': 'stream',
         'datatype': 'utf8', 'newline': '', 'topic': '', 'trim': False,
         'base64': False, 'tls': tls_id,
         'x': 160, 'y': 200, 'wires': [['esri_dbg_raw', 'esri_fn_filter']]},
        {'id': 'esri_dbg_raw', 'type': 'debug', 'z': tab2, 'name': 'Raw CoT (off)',
         'active': False, 'tosidebar': True, 'console': False, 'tostatus': False,
         'complete': 'payload', 'targetType': 'msg', 'statusVal': '', 'statusType': 'auto',
         'x': 400, 'y': 140, 'wires': []},
        {'id': 'esri_fn_filter', 'type': 'function', 'z': tab2,
         'name': 'Filter Survey123 UIDs', 'func': _FILTER_FN,
         'outputs': 1, 'timeout': 0, 'noerr': 0, 'initialize': '', 'finalize': '', 'libs': [],
         'x': 420, 'y': 200, 'wires': [['esri_file', 'esri_dbg_filtered']]},
        {'id': 'esri_file', 'type': 'file', 'z': tab2, 'name': 'Log CoT',
         'filename': log_file, 'filenameType': 'str',
         'appendNewline': True, 'createDir': True, 'overwriteFile': 'false', 'encoding': 'none',
         'x': 650, 'y': 180, 'wires': [[]]},
        {'id': 'esri_dbg_filtered', 'type': 'debug', 'z': tab2, 'name': 'Filtered CoT',
         'active': True, 'tosidebar': True, 'console': False, 'tostatus': False,
         'complete': 'payload', 'targetType': 'msg', 'statusVal': '', 'statusType': 'auto',
         'x': 650, 'y': 240, 'wires': []},
        # ── Shared TLS config ──────────────────────────────────────────────
        {'id': tls_id, 'type': 'tls-config', 'name': 'TAK Server TLS (Esri)',
         'cert': tls_cert, 'key': tls_key, 'ca': tls_ca,
         'certname': '', 'keyname': '', 'caname': '',
         'servername': '', 'verifyservercert': False, 'alpnprotocol': ''},
    ]

# ─────────────────────────────────────────────────────────────────────────────
# Template
# ─────────────────────────────────────────────────────────────────────────────

ESRI_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Esri CoT Bridge — infra-TAK</title>
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
.status-banner.not-installed{background:rgba(59,130,246,.08);border:1px solid rgba(59,130,246,.2);color:var(--accent)}
.status-banner.deployed{background:rgba(6,182,212,.08);border:1px solid rgba(6,182,212,.2);color:var(--cyan)}
.dot{width:8px;height:8px;border-radius:50%;background:currentColor;flex-shrink:0}
.btn{display:inline-flex;align-items:center;gap:8px;padding:10px 20px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;border:none;transition:opacity .15s}
.btn:hover{opacity:.85}.btn:disabled{opacity:.4;cursor:default}
.btn-primary{background:var(--accent);color:#fff}
.btn-success{background:var(--green);color:#fff}
.btn-ghost{background:rgba(255,255,255,.05);color:var(--text-secondary);border:1px solid var(--border)}
.btn-sm{padding:7px 14px;font-size:12px}
.controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.form-label{display:block;font-size:12px;font-weight:600;color:var(--text-secondary);margin-bottom:6px}
.form-input{width:100%;background:#0a0e1a;border:1px solid var(--border);border-radius:8px;padding:10px 14px;color:var(--text-primary);font-size:13px;font-family:'DM Sans',sans-serif}
.form-input:focus{outline:none;border-color:var(--accent)}
.form-group{margin-bottom:16px}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}
.info-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.info-item{background:#0a0e1a;border-radius:8px;padding:12px 14px}
.info-label{font-size:11px;color:var(--text-dim);margin-bottom:3px;text-transform:uppercase}
.info-value{font-size:13px;font-family:'JetBrains Mono',monospace;word-break:break-all}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:8px 12px;color:var(--text-dim);font-size:11px;text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid var(--border)}
td{padding:8px 12px;border-bottom:1px solid rgba(30,39,54,.6);vertical-align:middle}
tr:last-child td{border-bottom:none}
.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:20px;font-size:11px;font-weight:600}
.badge-green{background:rgba(16,185,129,.15);color:var(--green)}
.badge-red{background:rgba(239,68,68,.15);color:var(--red)}
.badge-yellow{background:rgba(234,179,8,.15);color:var(--yellow)}
.toast{position:fixed;bottom:24px;right:24px;padding:12px 20px;border-radius:10px;font-size:13px;font-weight:600;z-index:9999;opacity:0;transition:opacity .3s;pointer-events:none}
.toast.show{opacity:1}
.toast.success{background:var(--green);color:#fff}
.toast.error{background:var(--red);color:#fff}
.toast.warn{background:var(--yellow);color:#000}
.hint{font-size:11px;color:var(--text-dim);margin-top:4px}
hr{border:none;border-top:1px solid var(--border);margin:16px 0}
</style>
</head>
<body>
{{ sidebar_html }}
<div class="main">
  <div class="page-header">
    <h1>&#128506; Esri CoT Bridge</h1>
    <p>Connect Survey123 feature layers to TAKServer via Node-RED — no Python or system services required</p>
  </div>

  {% if nr.running %}
  <div class="status-banner running"><div class="dot"></div>Node-RED is running &mdash; configurator ready</div>
  {% elif nr.installed %}
  <div class="status-banner stopped"><div class="dot"></div>Node-RED is installed but not running &mdash; start it from the <a href="/nodered" style="color:inherit;text-decoration:underline">Node-RED page</a></div>
  {% else %}
  <div class="status-banner not-installed"><div class="dot"></div>Node-RED is not installed</div>
  {% endif %}

  {% if deployed %}
  <div class="status-banner deployed"><div class="dot"></div>Flow deployed &mdash; last deployed {{ last_deployed }}</div>
  {% endif %}

  {% if not nr.installed %}
  <!-- ── Node-RED not installed ──────────────────────────────────────── -->
  <div class="card">
    <div class="card-title">Install Node-RED First</div>
    <p style="color:var(--text-secondary);font-size:13px;margin-bottom:16px">
      The Esri CoT Bridge runs entirely inside Node-RED. You need Node-RED installed on this host before you can deploy the bridge.
    </p>
    <div class="controls">
      <a href="/nodered" class="btn btn-primary">Go to Node-RED &rarr;</a>
    </div>
  </div>
  {% else %}
  <!-- ── Configurator ───────────────────────────────────────────────── -->

  <!-- Survey123 Connection -->
  <div class="card">
    <div class="card-title">Survey123 Connection</div>
    <div class="grid-2">
      <div class="form-group">
        <label class="form-label">Feature Layer URL</label>
        <input id="survey-url" class="form-input" type="url"
               placeholder="https://services.arcgis.com/.../FeatureServer/0/query"
               value="{{ cfg.get('survey_url','') }}">
        <div class="hint">Paste the FeatureServer URL &mdash; /0/query will be appended automatically</div>
      </div>
      <div class="form-group">
        <label class="form-label">ArcGIS Token <span style="color:var(--text-dim);font-weight:400">(leave blank for public layers)</span></label>
        <input id="survey-token" class="form-input" type="password"
               placeholder="optional token"
               value="{{ cfg.get('token','') }}">
      </div>
    </div>
    <div class="form-group">
      <label class="form-label">Poll Interval (seconds)</label>
      <input id="poll-interval" class="form-input" type="number" min="10" max="3600"
             style="max-width:160px"
             value="{{ cfg.get('poll_interval', 60) }}">
    </div>
    <div class="controls">
      <button class="btn btn-ghost btn-sm" onclick="discoverFields()">&#128270; Discover Fields</button>
      <span id="discover-status" style="font-size:12px;color:var(--text-dim)"></span>
    </div>
  </div>

  <!-- Field Mapping -->
  <div class="card">
    <div class="card-title">Field Mapping</div>
    <p class="hint" style="margin-bottom:14px">Click &ldquo;Discover Fields&rdquo; above to populate these dropdowns from your actual survey, or type field names manually.</p>
    <div class="grid-2">
      <div class="form-group">
        <label class="form-label">Callsign / Unit ID</label>
        <select id="field-callsign" class="form-input">
          <option value="{{ cfg.get('field_mapping',{}).get('callsign','team_callsign') }}">{{ cfg.get('field_mapping',{}).get('callsign','team_callsign') }}</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Mission Number</label>
        <select id="field-mission" class="form-input">
          <option value="{{ cfg.get('field_mapping',{}).get('mission_number','mission_number') }}">{{ cfg.get('field_mapping',{}).get('mission_number','mission_number') }}</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Sortie Number</label>
        <select id="field-sortie" class="form-input">
          <option value="{{ cfg.get('field_mapping',{}).get('sortie_number','sortie_number') }}">{{ cfg.get('field_mapping',{}).get('sortie_number','sortie_number') }}</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Team Leader Name</label>
        <select id="field-leader-name" class="form-input">
          <option value="{{ cfg.get('field_mapping',{}).get('leader_name','team_leader_name') }}">{{ cfg.get('field_mapping',{}).get('leader_name','team_leader_name') }}</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Team Leader CAPID</label>
        <select id="field-leader-capid" class="form-input">
          <option value="{{ cfg.get('field_mapping',{}).get('leader_capid','team_leader_capid') }}">{{ cfg.get('field_mapping',{}).get('leader_capid','team_leader_capid') }}</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Waypoint / Incident Type <span style="color:var(--text-dim);font-weight:400">(drives CoT icon)</span></label>
        <select id="field-waypoint" class="form-input" onchange="onWaypointFieldChange()">
          <option value="{{ cfg.get('field_mapping',{}).get('waypoint_type','select_a_waypoint_of_what_you_a') }}">{{ cfg.get('field_mapping',{}).get('waypoint_type','select_a_waypoint_of_what_you_a') }}</option>
        </select>
      </div>
    </div>
    <div class="form-group" style="max-width:280px">
      <label class="form-label">CoT Type <span style="color:var(--text-dim);font-weight:400">(applied to all features)</span></label>
      <input id="cot-type" class="form-input" type="text"
             placeholder="a-h-G"
             value="{{ cfg.get('cot_type', 'a-h-G') }}">
    </div>
  </div>

  <!-- Icon Mapping -->
  <div class="card">
    <div class="card-title">Icon Mapping</div>
    <p class="hint" style="margin-bottom:14px">Maps each waypoint/incident type value from your survey to a TAK icon. Select the waypoint field above then click Discover Values.</p>
    <div class="controls" style="margin-bottom:16px">
      <button class="btn btn-ghost btn-sm" onclick="discoverValues()">&#127981; Discover Waypoint Values</button>
      <span id="values-status" style="font-size:12px;color:var(--text-dim)"></span>
    </div>
    <div id="icon-table-wrap" style="display:none">
      <table>
        <thead><tr><th>Survey Value</th><th>TAK Icon</th><th>Preview</th></tr></thead>
        <tbody id="icon-table-body"></tbody>
      </table>
    </div>
    <div id="icon-table-empty" style="color:var(--text-dim);font-size:13px">
      No values discovered yet &mdash; click &ldquo;Discover Waypoint Values&rdquo; or deploy with the default icon mapping.
    </div>
  </div>

  <!-- TAKServer Settings -->
  <div class="card">
    <div class="card-title">TAKServer Connection</div>
    <div class="grid-2" style="margin-bottom:16px">
      <div class="form-group">
        <label class="form-label">TAKServer Host / IP</label>
        <input id="tak-host" class="form-input" type="text"
               placeholder="10.0.0.1"
               value="{{ cfg.get('tak_host','') }}">
      </div>
      <div class="form-group">
        <label class="form-label">Port</label>
        <input id="tak-port" class="form-input" type="number" min="1" max="65535"
               value="{{ cfg.get('tak_port', 8089) }}">
      </div>
    </div>
    <hr>
    <div class="card-title" style="margin-top:4px">TLS Certificates <span style="color:var(--text-dim);font-weight:400;font-size:11px">(paths on the Node-RED host)</span></div>
    <div class="grid-3">
      <div class="form-group">
        <label class="form-label">Client Certificate (.pem / .crt)</label>
        <input id="tls-cert" class="form-input" type="text"
               placeholder="/etc/tak/certs/user.pem"
               value="{{ cfg.get('tls_cert','') }}">
      </div>
      <div class="form-group">
        <label class="form-label">Private Key (.key / .pem)</label>
        <input id="tls-key" class="form-input" type="text"
               placeholder="/etc/tak/certs/user.key"
               value="{{ cfg.get('tls_key','') }}">
      </div>
      <div class="form-group">
        <label class="form-label">CA Certificate</label>
        <input id="tls-ca" class="form-input" type="text"
               placeholder="/etc/tak/certs/ca.pem"
               value="{{ cfg.get('tls_ca','') }}">
      </div>
    </div>
  </div>

  <!-- Log Settings -->
  <div class="card">
    <div class="card-title">CoT Log File</div>
    <div class="form-group" style="max-width:480px">
      <label class="form-label">Log file path (on the Node-RED host)</label>
      <input id="log-file" class="form-input" type="text"
             placeholder="cot-logged.txt"
             value="{{ cfg.get('log_file','cot-logged.txt') }}">
      <div class="hint">Incoming TAK CoT messages (excluding Survey123 echoes) are appended here. Relative paths resolve to Node-RED\'s working directory.</div>
    </div>
  </div>

  <!-- Actions -->
  <div class="card" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
    <div class="controls">
      <button class="btn btn-ghost" onclick="saveConfig()">&#128190; Save Settings</button>
      <button class="btn btn-success" id="deploy-btn" onclick="deployFlow()">&#9654; Save &amp; Deploy to Node-RED</button>
    </div>
    <div id="action-status" style="font-size:13px;color:var(--text-dim)"></div>
  </div>

  {% endif %}
</div>

<div class="toast" id="toast"></div>

<script>
const ICON_OPTIONS = {{ icon_options_json }};
const SAVED_ICON_MAP = {{ saved_icon_map_json }};

// ── Toast ─────────────────────────────────────────────────────────────────────
function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show ' + (type || 'success');
  clearTimeout(t._tid);
  t._tid = setTimeout(() => t.className = 'toast', 3000);
}

// ── Discover fields ────────────────────────────────────────────────────────────
async function discoverFields() {
  const url = document.getElementById('survey-url').value.trim();
  const token = document.getElementById('survey-token').value.trim();
  const status = document.getElementById('discover-status');
  if (!url) { showToast('Enter a Survey123 URL first', 'error'); return; }
  status.textContent = 'Discovering...';
  try {
    const res = await fetch('/api/esri/discover-fields?' + new URLSearchParams({url, token}));
    const data = await res.json();
    if (!data.ok) { status.textContent = 'Error: ' + (data.error || 'unknown'); showToast(data.error || 'Failed', 'error'); return; }
    populateSelects(data.fields);
    status.textContent = data.fields.length + ' fields found';
    showToast('Found ' + data.fields.length + ' fields', 'success');
  } catch(e) {
    status.textContent = 'Error: ' + e.message;
    showToast(e.message, 'error');
  }
}

function populateSelects(fields) {
  const selectIds = [
    {id: 'field-callsign',    saved: null},
    {id: 'field-mission',     saved: null},
    {id: 'field-sortie',      saved: null},
    {id: 'field-leader-name', saved: null},
    {id: 'field-leader-capid',saved: null},
    {id: 'field-waypoint',    saved: null},
  ];
  selectIds.forEach(item => {
    const sel = document.getElementById(item.id);
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="">-- select field --</option>';
    fields.forEach(f => {
      const opt = document.createElement('option');
      opt.value = f.name;
      opt.textContent = (f.alias && f.alias !== f.name) ? f.alias + ' (' + f.name + ')' : f.name;
      if (f.name === current) opt.selected = true;
      sel.appendChild(opt);
    });
  });
  window._discoveredFields = fields;
}

// ── Discover waypoint values ───────────────────────────────────────────────────
function onWaypointFieldChange() {
  document.getElementById('values-status').textContent = 'Field changed — click Discover Waypoint Values to refresh';
}

async function discoverValues() {
  const url = document.getElementById('survey-url').value.trim();
  const token = document.getElementById('survey-token').value.trim();
  const field = document.getElementById('field-waypoint').value.trim();
  const status = document.getElementById('values-status');
  if (!url || !field) { showToast('Enter URL and select the waypoint field first', 'warn'); return; }
  status.textContent = 'Querying...';
  try {
    const res = await fetch('/api/esri/discover-values?' + new URLSearchParams({url, token, field}));
    const data = await res.json();
    if (!data.ok) { status.textContent = 'Error: ' + (data.error || 'unknown'); showToast(data.error || 'Failed', 'error'); return; }
    status.textContent = data.values.length + ' unique values';
    renderIconTable(data.values);
    showToast('Found ' + data.values.length + ' waypoint values', 'success');
  } catch(e) {
    status.textContent = 'Error: ' + e.message;
    showToast(e.message, 'error');
  }
}

function guessIcon(value) {
  const lower = value.toLowerCase();
  for (const opt of ICON_OPTIONS) {
    const name = opt.name.toLowerCase();
    if (lower === name || lower.includes(name) || name.includes(lower)) return opt.path;
  }
  return '';
}

function renderIconTable(values) {
  const tbody = document.getElementById('icon-table-body');
  const wrap  = document.getElementById('icon-table-wrap');
  const empty = document.getElementById('icon-table-empty');
  tbody.innerHTML = '';
  values.forEach(val => {
    const savedPath = SAVED_ICON_MAP[val] || guessIcon(val) || '';
    const isCustom = Boolean(savedPath && !ICON_OPTIONS.some(o => o.path === savedPath));
    const opts = ICON_OPTIONS.map(o => {
      const sel = o.path === savedPath ? ' selected' : '';
      return `<option value="${o.path}"${sel}>${o.name}</option>`;
    }).join('');
    const customSel = isCustom ? ' selected' : '';
    const customVal = isCustom ? savedPath : '';
    const tr = document.createElement('tr');
    tr.setAttribute('data-value', val);
    tr.innerHTML = `
      <td style="font-family:monospace;font-size:12px">${val}</td>
      <td>
        <select class="form-input icon-sel" style="font-size:12px;padding:6px 10px" onchange="iconSelChange(this)">
          <option value="">-- default icon --</option>
          ${opts}
          <option value="__custom__"${customSel}>Custom path…</option>
        </select>
        <input type="text" class="form-input icon-custom"
               style="display:none;margin-top:6px;font-size:12px"
               placeholder="hash/Incident Icons/name.png"
               value="${customVal}">
      </td>
      <td><img class="icon-preview" src="" style="height:28px;display:none"
               onerror="this.style.display='none'"></td>`;
    tbody.appendChild(tr);
    updateIconPreview(tr.querySelector('.icon-sel'));
    if (isCustom) tr.querySelector('.icon-custom').style.display = 'block';
  });
  wrap.style.display = 'block';
  empty.style.display = 'none';
}

function iconSelChange(sel) {
  const tr = sel.closest('tr');
  const customInput = tr.querySelector('.icon-custom');
  if (sel.value === '__custom__') {
    customInput.style.display = 'block';
  } else {
    customInput.style.display = 'none';
  }
  updateIconPreview(sel);
}

function updateIconPreview(sel) {
  const tr = sel.closest('tr');
  const img = tr.querySelector('.icon-preview');
  const path = sel.value === '__custom__'
    ? tr.querySelector('.icon-custom').value.trim()
    : sel.value;
  if (path && path !== '__custom__') {
    img.src = 'https://static.arcgis.com/images/Symbols/Mil2525d/' + path;
    img.style.display = 'inline';
  } else {
    img.style.display = 'none';
  }
}

function collectIconMap() {
  const result = {};
  document.querySelectorAll('#icon-table-body tr').forEach(tr => {
    const val = tr.getAttribute('data-value');
    const sel = tr.querySelector('.icon-sel');
    if (!sel || !val) return;
    let path = sel.value;
    if (path === '__custom__') path = (tr.querySelector('.icon-custom').value || '').trim();
    if (path && path !== '__custom__') result[val] = path;
  });
  return result;
}

// ── Save config ───────────────────────────────────────────────────────────────
function buildCfg() {
  return {
    survey_url:    document.getElementById('survey-url').value.trim(),
    token:         document.getElementById('survey-token').value.trim(),
    poll_interval: parseInt(document.getElementById('poll-interval').value) || 60,
    tak_host:      document.getElementById('tak-host').value.trim(),
    tak_port:      parseInt(document.getElementById('tak-port').value) || 8089,
    tls_cert:      document.getElementById('tls-cert').value.trim(),
    tls_key:       document.getElementById('tls-key').value.trim(),
    tls_ca:        document.getElementById('tls-ca').value.trim(),
    log_file:      document.getElementById('log-file').value.trim() || 'cot-logged.txt',
    cot_type:      document.getElementById('cot-type').value.trim() || 'a-h-G',
    field_mapping: {
      callsign:      document.getElementById('field-callsign').value,
      mission_number:document.getElementById('field-mission').value,
      sortie_number: document.getElementById('field-sortie').value,
      leader_name:   document.getElementById('field-leader-name').value,
      leader_capid:  document.getElementById('field-leader-capid').value,
      waypoint_type: document.getElementById('field-waypoint').value,
    },
    icon_mapping: collectIconMap(),
  };
}

async function saveConfig() {
  const cfg = buildCfg();
  const res = await fetch('/api/esri/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(cfg),
  });
  const data = await res.json();
  if (data.ok) showToast('Settings saved', 'success');
  else showToast(data.error || 'Save failed', 'error');
}

// ── Deploy ────────────────────────────────────────────────────────────────────
async function deployFlow() {
  const btn = document.getElementById('deploy-btn');
  const status = document.getElementById('action-status');
  btn.disabled = true;
  status.textContent = 'Deploying…';
  try {
    const cfg = buildCfg();
    const res = await fetch('/api/esri/deploy', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(cfg),
    });
    const data = await res.json();
    if (data.ok) {
      showToast(data.message || 'Deployed!', 'success');
      status.textContent = 'Deployed ✔';
    } else {
      showToast(data.error || 'Deploy failed', 'error');
      status.textContent = 'Error: ' + (data.error || 'unknown');
    }
  } catch(e) {
    showToast(e.message, 'error');
    status.textContent = 'Error: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}
</script>
</body>
</html>'''


# ─────────────────────────────────────────────────────────────────────────────
# Route registration
# ─────────────────────────────────────────────────────────────────────────────

def register_routes(app, login_required, load_settings, save_settings):
    from flask import request, jsonify, render_template_string, make_response
    import subprocess, datetime

    def _nr_host_port():
        """Return (host, port) for the local Node-RED Admin API."""
        return 'localhost', 1880

    # ── Page ──────────────────────────────────────────────────────────────────

    @app.route('/esri')
    @login_required
    def esri_page():
        from markupsafe import Markup
        settings = load_settings()
        cfg = settings.get(ESRI_KEY, {})

        # Detect Node-RED
        nr_installed = False
        nr_running = False
        try:
            r = subprocess.run(
                ['systemctl', 'is-active', 'nodered'],
                capture_output=True, text=True, timeout=4
            )
            nr_running = r.stdout.strip() == 'active'
            nr_installed = nr_running or r.returncode == 0
        except Exception:
            pass
        if not nr_installed:
            import os as _os
            nr_installed = (
                _os.path.exists(os.path.expanduser('~/node-red')) or
                _os.path.exists('/opt/nodered') or
                _nr_running()
            )
        if not nr_running:
            nr_running = _nr_running()

        nr = {'installed': nr_installed, 'running': nr_running}

        icon_options = [{'name': k, 'path': v} for k, v in INCIDENT_ICONS.items()]
        icon_options_json = Markup(json.dumps(icon_options))
        saved_icon_map_json = Markup(json.dumps(cfg.get('icon_mapping', {})))

        deployed = cfg.get('deployed', False)
        last_deployed = cfg.get('last_deployed', '')

        resp = make_response(render_template_string(
            ESRI_TEMPLATE,
            nr=nr,
            cfg=cfg,
            deployed=deployed,
            last_deployed=last_deployed,
            icon_options_json=icon_options_json,
            saved_icon_map_json=saved_icon_map_json,
        ))
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        return resp

    # ── Config GET / POST ─────────────────────────────────────────────────────

    @app.route('/api/esri/config', methods=['GET', 'POST'])
    @login_required
    def esri_config_api():
        if request.method == 'GET':
            return jsonify({'ok': True, 'config': _load_cfg(load_settings)})
        data = request.get_json(silent=True) or {}
        _save_cfg(data, load_settings, save_settings)
        return jsonify({'ok': True})

    # ── Discover fields ───────────────────────────────────────────────────────

    @app.route('/api/esri/discover-fields')
    @login_required
    def esri_discover_fields():
        raw_url = request.args.get('url', '').strip()
        token   = request.args.get('token', '').strip()
        if not raw_url:
            return jsonify({'ok': False, 'error': 'url parameter is required'})

        # Build the layer metadata URL
        # Strip /query suffix if present, then query the layer info endpoint
        base = raw_url
        for suffix in ('/query', '/0/query'):
            if base.lower().endswith(suffix):
                base = base[:-len(suffix)]
                break
        # If URL ends with /0 it's already the layer endpoint; otherwise try /0
        if not base.rstrip('/').endswith('/0'):
            base = base.rstrip('/') + '/0'

        params = {'f': 'json'}
        if token:
            params['token'] = token
        meta_url = base + '?' + urllib.parse.urlencode(params)

        try:
            req = urllib.request.Request(meta_url, headers={'User-Agent': 'infra-TAK/esri-bridge'})
            with urllib.request.urlopen(req, timeout=10) as r:
                meta = json.loads(r.read().decode())
        except Exception as e:
            return jsonify({'ok': False, 'error': f'Could not reach FeatureServer: {e}'})

        if 'error' in meta:
            return jsonify({'ok': False, 'error': meta['error'].get('message', str(meta['error']))})

        raw_fields = meta.get('fields', [])
        if not raw_fields:
            return jsonify({'ok': False, 'error': 'No fields returned — check URL and token'})

        fields = [
            {'name': f.get('name', ''), 'alias': f.get('alias', ''), 'type': f.get('type', '')}
            for f in raw_fields
            if f.get('name') and f.get('type', '') not in ('esriFieldTypeGeometry',)
        ]
        return jsonify({'ok': True, 'fields': fields})

    # ── Discover unique waypoint values ───────────────────────────────────────

    @app.route('/api/esri/discover-values')
    @login_required
    def esri_discover_values():
        raw_url = request.args.get('url', '').strip()
        token   = request.args.get('token', '').strip()
        field   = request.args.get('field', '').strip()
        if not raw_url or not field:
            return jsonify({'ok': False, 'error': 'url and field parameters are required'})

        # Build /query endpoint
        base = raw_url
        for suffix in ('/query',):
            if base.lower().endswith(suffix):
                base = base[:-len(suffix)]
                break
        if not base.rstrip('/').endswith('/0'):
            base = base.rstrip('/') + '/0'
        query_url = base + '/query'

        params = {
            'where': '1=1',
            'outFields': field,
            'returnDistinctValues': 'true',
            'orderByFields': field,
            'f': 'json',
        }
        if token:
            params['token'] = token

        full_url = query_url + '?' + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(full_url, headers={'User-Agent': 'infra-TAK/esri-bridge'})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
        except Exception as e:
            return jsonify({'ok': False, 'error': f'Query failed: {e}'})

        if 'error' in data:
            return jsonify({'ok': False, 'error': data['error'].get('message', str(data['error']))})

        values = []
        for feat in data.get('features', []):
            v = feat.get('attributes', {}).get(field)
            if v is not None and str(v).strip():
                values.append(str(v).strip())

        return jsonify({'ok': True, 'values': values})

    # ── Deploy ────────────────────────────────────────────────────────────────

    @app.route('/api/esri/deploy', methods=['POST'])
    @login_required
    def esri_deploy():
        cfg = request.get_json(silent=True) or {}
        host, port = _nr_host_port()

        if not _nr_running(host, port):
            return jsonify({'ok': False, 'error': f'Node-RED is not reachable at {host}:{port}. Start it from the Node-RED page first.'})

        nodes = _generate_flow_nodes(cfg)
        ok, msg = _deploy_to_nodered(nodes, host, port)

        if ok:
            cfg['deployed'] = True
            cfg['last_deployed'] = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
            _save_cfg(cfg, load_settings, save_settings)
        else:
            # Still save the config even if deploy failed
            _save_cfg(cfg, load_settings, save_settings)

        return jsonify({'ok': ok, 'message': msg if ok else None, 'error': None if ok else msg})

    # ── Status ────────────────────────────────────────────────────────────────

    @app.route('/api/esri/status')
    @login_required
    def esri_status():
        host, port = _nr_host_port()
        nr_up = _nr_running(host, port)
        cfg = _load_cfg(load_settings)
        return jsonify({
            'ok': True,
            'nr_running': nr_up,
            'deployed': cfg.get('deployed', False),
            'last_deployed': cfg.get('last_deployed', ''),
        })
