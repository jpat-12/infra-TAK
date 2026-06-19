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

def _cert_dir():
    return os.path.join(CONFIG_DIR, 'esri_certs')

def _cert_paths():
    d = _cert_dir()
    return {
        'cert': os.path.join(d, 'client.pem'),
        'key':  os.path.join(d, 'client.key'),
        'ca':   os.path.join(d, 'ca.pem'),
    }

def _run_openssl(*args):
    import subprocess as _sp
    r = _sp.run(['openssl'] + list(args), capture_output=True, text=True)
    return r.returncode == 0, r.stderr.strip()

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


def _build_cot_fn(field_map, icon_map, cot_type, remarks_fields, include_attachments, survey_url, token, icon_base_url=''):
    import re as _re
    fm = field_map or {}
    # Separate __other__ from the icon map; it becomes the defaultIcon
    raw_icons = icon_map if icon_map else INCIDENT_ICONS
    icons = {k: v for k, v in raw_icons.items() if k != '__other__'}
    default_icon_path = raw_icons.get('__other__', DEFAULT_ICON) if icon_map else DEFAULT_ICON

    # Derive the FeatureServer/0 base URL for attachment queries
    att_base = _re.sub(r'/\d+/query$', '', (survey_url or '').rstrip('/'), flags=_re.IGNORECASE)
    att_base = _re.sub(r'/query$', '', att_base, flags=_re.IGNORECASE)
    if not _re.search(r'/\d+$', att_base):
        att_base = att_base + '/0'

    remarks_json = json.dumps(remarks_fields or [])

    common = [
        '// Configured via infra-TAK Esri CoT Bridge',
        f"const F_CALLSIGN = '{_js(fm.get('callsign', 'team_callsign'))}';",
        f"const F_WAYPOINT = '{_js(fm.get('waypoint_type', 'select_a_waypoint_of_what_you_a'))}';",
        f"const COT_TYPE   = '{_js(cot_type or DEFAULT_COT_TYPE)}';",
        f'const REMARKS_FIELDS = {remarks_json};',
        f"const INCLUDE_ATTACHMENTS = {json.dumps(bool(include_attachments))};",
        f"const ATT_BASE_URL = '{_js(att_base)}';",
        f"const SURVEY_TOKEN = '{_js(token or '')}';",
        '',
        f'const iconPaths = {json.dumps(icons, indent=2)};',
        f"const defaultIcon = '{_js(default_icon_path)}';",
        f"const ICON_BASE_URL = '{_js(icon_base_url)}';",
        'function getIcon(v) {',
        '    const p = iconPaths[v] || defaultIcon;',
        "    if (p && p.startsWith('CUSTOM:')) {",
        "        return ICON_BASE_URL + '/api/esri/icon/' + encodeURIComponent(p.slice(7));",
        '    }',
        '    return p;',
        '}',
        '',
        'function buildRemarks(a, lat, lon, callsign, creationDateStr, objectid) {',
        '    const parts = REMARKS_FIELDS.map(r => {',
        "        const v = (a[r.field] !== null && a[r.field] !== undefined) ? String(a[r.field]) : '';",
        "        return v ? r.label + ': ' + v : null;",
        '    }).filter(Boolean);',
        "    parts.push('Lat: ' + lat + ', Lon: ' + lon);",
        "    parts.push('ObjectID: ' + objectid);",
        "    if (creationDateStr) parts.push('Submitted: ' + creationDateStr);",
        "    return parts.join(', ');",
        '}',
        '',
        'let data = msg.payload;',
        "if (typeof data === 'string') {",
        '    try { data = JSON.parse(data); } catch(e) {',
        "        node.error('Parse error: ' + e.message); return null;",
        '    }',
        '}',
        'if (!data || !data.features || data.features.length === 0) {',
        "    node.status({fill: 'yellow', shape: 'ring', text: 'no features'}); return null;",
        '}',
        'const now = new Date();',
        'const stale = new Date(now.getTime() + 5 * 60 * 1000);',
        'const timeStr = now.toISOString();',
        'const staleStr = stale.toISOString();',
    ]

    cot_tpl = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<event version="2.0" uid="Survey123_${objectid}" type="${COT_TYPE}" '
        'time="${timeStr}" start="${timeStr}" stale="${staleStr}" how="m-g">'
        '<point lat="${lat}" lon="${lon}" hae="0" ce="10.0" le="2.0"/>'
        '<detail><UID>Survey123_${callsign} ${creationDateStr}</UID>'
        '<usericon iconsetpath="${iconPath}"/>'
        '<remarks>${remarks}</remarks>'
        '<contact callsign="${callsign}"/>'
        '<track speed="0" course="0"/>${fileshareXml}</detail></event>'
    )

    if include_attachments:
        lines = common + [
            "const https = require('https');",
            "const http  = require('http');",
            'function fetchJson(url) {',
            '    return new Promise(resolve => {',
            "        const lib = url.startsWith('https') ? https : http;",
            "        try { lib.get(url, res => { let d = ''; res.on('data', c => d += c);",
            "            res.on('end', () => { try { resolve(JSON.parse(d)); } catch { resolve({}); } });",
            "        }).on('error', () => resolve({})); } catch { resolve({}); }",
            '    });',
            '}',
            '',
            '(async () => {',
            '    const events = [];',
            '    for (const feature of data.features) {',
            '        const a = feature.attributes;',
            '        const geom = feature.geometry;',
            '        if (!geom || geom.x == null || geom.y == null) continue;',
            '        const lat = geom.y, lon = geom.x;',
            '        const objectid = a.objectid || a.OBJECTID || a.ObjectId;',
            "        const callsign = a[F_CALLSIGN] || 'UNKNOWN';",
            "        const waypointType = a[F_WAYPOINT] || '';",
            '        const creationDate = a.CreationDate || a.creationdate;',
            '        const creationDateStr = creationDate',
            "            ? new Date(creationDate).toISOString().replace('T', ' ').replace('Z', '').slice(0, 23)",
            "            : '';",
            '        const iconPath = getIcon(waypointType);',
            '        const remarks = buildRemarks(a, lat, lon, callsign, creationDateStr, objectid);',
            "        let fileshareXml = '';",
            '        if (ATT_BASE_URL && objectid != null) {',
            "            const tq = SURVEY_TOKEN ? '&token=' + SURVEY_TOKEN : '';",
            "            const attData = await fetchJson(ATT_BASE_URL + '/' + objectid + '/attachments?f=json' + tq);",
            "            for (const att of (attData.attachmentInfos || [])) {",
            "                const ts = SURVEY_TOKEN ? '?token=' + SURVEY_TOKEN : '';",
            "                const dlUrl = ATT_BASE_URL + '/' + objectid + '/attachments/' + att.id + ts;",
            '                fileshareXml += `<fileshare filename="${att.name}" senderUrl="${dlUrl}" senderCallsign="${callsign}" sha256="" sizeInBytes="${att.size || 0}"/>`;',
            '            }',
            '        }',
            f'        const event = `{cot_tpl}`;',
            '        events.push(event);',
            '    }',
            '    if (events.length === 0) {',
            "        node.status({fill: 'yellow', shape: 'ring', text: 'no valid features'}); node.send(null); return;",
            '    }',
            "    msg.payload = events.join('\\n');",
            "    node.status({fill: 'green', shape: 'dot', text: events.length + ' events sent'});",
            '    node.send(msg);',
            "})().catch(e => { node.error('Attachment query failed: ' + e.message); node.send(null); });",
            'return;',
        ]
    else:
        lines = common + [
            'const events = [];',
            'for (const feature of data.features) {',
            '    const a = feature.attributes;',
            '    const geom = feature.geometry;',
            '    if (!geom || geom.x == null || geom.y == null) continue;',
            '    const lat = geom.y, lon = geom.x;',
            '    const objectid = a.objectid || a.OBJECTID || a.ObjectId;',
            "    const callsign = a[F_CALLSIGN] || 'UNKNOWN';",
            "    const waypointType = a[F_WAYPOINT] || '';",
            '    const creationDate = a.CreationDate || a.creationdate;',
            '    const creationDateStr = creationDate',
            "        ? new Date(creationDate).toISOString().replace('T', ' ').replace('Z', '').slice(0, 23)",
            "        : '';",
            '    const iconPath = getIcon(waypointType);',
            '    const remarks = buildRemarks(a, lat, lon, callsign, creationDateStr, objectid);',
            "    const fileshareXml = '';",
            f'    const event = `{cot_tpl}`;',
            '    events.push(event);',
            '}',
            'if (events.length === 0) {',
            "    node.status({fill: 'yellow', shape: 'ring', text: 'no valid features'}); return null;",
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
    log_file  = cfg.get('log_file', 'cot-logged.txt')
    # Cert paths come from the upload directory, not free-text config
    _cp = _cert_paths()
    tls_cert = _cp['cert'] if os.path.exists(_cp['cert']) else ''
    tls_key  = _cp['key']  if os.path.exists(_cp['key'])  else ''
    tls_ca   = _cp['ca']   if os.path.exists(_cp['ca'])   else ''
    poll      = str(int(cfg.get('poll_interval', 60)))

    url_fn  = _build_url_fn(cfg.get('survey_url', ''), cfg.get('token', ''))
    cot_fn  = _build_cot_fn(
        cfg.get('field_mapping', {}),
        cfg.get('icon_mapping', {}),
        cfg.get('cot_type', DEFAULT_COT_TYPE),
        cfg.get('remarks_fields', []),
        cfg.get('include_attachments', False),
        cfg.get('survey_url', ''),
        cfg.get('token', ''),
        cfg.get('_icon_base_url', ''),
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
.remarks-row{display:flex;gap:8px;align-items:center;margin-bottom:8px}
.remarks-row input{flex:0 0 180px}
.remarks-row select{flex:1}
.remarks-row .del-btn{flex-shrink:0;background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.25);color:var(--red);border-radius:6px;padding:6px 10px;cursor:pointer;font-size:13px;line-height:1}
.remarks-row .del-btn:hover{background:rgba(239,68,68,.22)}
.upload-row{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.upload-label{display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border-radius:7px;background:rgba(255,255,255,.05);border:1px solid var(--border);color:var(--text-secondary);font-size:12px;font-weight:600;cursor:pointer;transition:all .15s}
.upload-label:hover{border-color:var(--accent);color:var(--accent)}
.upload-label input[type=file]{display:none}
.cert-file-status{font-size:12px;color:var(--text-dim);font-family:monospace}
.cert-file-status.ok{color:var(--green)}
.cert-file-status.missing{color:var(--red)}
.format-tab{padding:7px 16px;border-radius:7px;font-size:12px;font-weight:600;cursor:pointer;border:1px solid var(--border);background:transparent;color:var(--text-secondary);transition:all .15s}
.format-tab.active{background:var(--accent);color:#fff;border-color:var(--accent)}
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

  <!-- Required CoT Fields -->
  <div class="card">
    <div class="card-title">Required CoT Fields</div>
    <p class="hint" style="margin-bottom:14px">Discover Fields above to populate dropdowns. Latitude &amp; longitude come from the feature geometry automatically.</p>
    <div class="grid-2">
      <div class="form-group">
        <label class="form-label">Callsign / Unit ID <span style="color:var(--red)">*</span></label>
        <select id="field-callsign" class="form-input">
          <option value="{{ cfg.get('field_mapping',{}).get('callsign','team_callsign') }}">{{ cfg.get('field_mapping',{}).get('callsign','team_callsign') }}</option>
        </select>
        <div class="hint">Used in the CoT uid, UID detail, and contact callsign elements</div>
      </div>
      <div class="form-group">
        <label class="form-label">Waypoint / Incident Type <span style="color:var(--text-dim);font-weight:400">(drives icon)</span></label>
        <select id="field-waypoint" class="form-input" onchange="onWaypointFieldChange()">
          <option value="{{ cfg.get('field_mapping',{}).get('waypoint_type','select_a_waypoint_of_what_you_a') }}">{{ cfg.get('field_mapping',{}).get('waypoint_type','select_a_waypoint_of_what_you_a') }}</option>
        </select>
      </div>
    </div>
    <div class="form-group" style="max-width:220px">
      <label class="form-label">CoT Type</label>
      <input id="cot-type" class="form-input" type="text" placeholder="a-h-G"
             value="{{ cfg.get('cot_type', 'a-h-G') }}">
      <div class="hint">e.g. a-f-G (friendly ground), a-h-G (hostile), a-n-G (neutral)</div>
    </div>
  </div>

  <!-- Remarks Builder -->
  <div class="card">
    <div class="card-title">Remarks Builder</div>
    <p class="hint" style="margin-bottom:14px">
      These fields are concatenated into the CoT <code style="font-family:monospace;font-size:11px">&lt;remarks&gt;</code> element in order.
      Lat/Lon, ObjectID, and submission time are always appended automatically.
    </p>
    <div id="remarks-list"></div>
    <div class="controls" style="margin-top:8px">
      <button class="btn btn-ghost btn-sm" onclick="addRemarksRow()">+ Add Field</button>
    </div>
  </div>

  <!-- Attachments -->
  <div class="card">
    <div class="card-title">ArcGIS Attachments</div>
    <label style="display:flex;align-items:center;gap:10px;cursor:pointer;font-size:13px">
      <input type="checkbox" id="include-attachments" style="width:16px;height:16px;accent-color:var(--accent)"
             {{ 'checked' if cfg.get('include_attachments') else '' }}>
      <span>Query ArcGIS for photo/file attachments and include as CoT <code style="font-family:monospace;font-size:11px">&lt;fileshare&gt;</code> elements</span>
    </label>
    <div class="hint" style="margin-top:10px;line-height:1.6">
      When enabled, the flow makes an additional HTTP request per feature to
      <code style="font-family:monospace;font-size:11px">/FeatureServer/0/{objectId}/attachments</code>.
      TAK clients must be able to reach the ArcGIS server directly to download the files.
      Leave disabled for faster polling if your survey has no attachments.
    </div>
  </div>

  <!-- Icon Mapping -->
  <div class="card">
    <div class="card-title">Icon Mapping</div>
    <p class="hint" style="margin-bottom:14px">One row per unique survey value. The <strong>Other</strong> row is the catch-all for any value not listed.</p>

    <!-- Custom icon upload -->
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap">
      <label class="upload-label">&#128247; Upload Custom Icon (PNG/JPG)
        <input type="file" id="file-custom-icon" accept=".png,.jpg,.jpeg,.gif,.svg"
               onchange="uploadCustomIcon(this)">
      </label>
      <span id="icon-upload-status" style="font-size:12px;color:var(--text-dim)"></span>
    </div>
    {% if custom_icons %}
    <div class="hint" style="margin-bottom:12px">
      Uploaded icons: {% for ic in custom_icons %}<code style="font-family:monospace;font-size:11px;margin-right:6px">{{ ic }}</code>{% endfor %}
    </div>
    {% endif %}

    <div class="controls" style="margin-bottom:16px">
      <button class="btn btn-ghost btn-sm" onclick="discoverValues()">&#127981; Discover Waypoint Values</button>
      <span id="values-status" style="font-size:12px;color:var(--text-dim)"></span>
    </div>
    <div id="icon-table-wrap">
      <table>
        <thead><tr><th>Survey Value</th><th>TAK Icon</th><th>Preview</th></tr></thead>
        <tbody id="icon-table-body"></tbody>
      </table>
    </div>
    <div id="icon-table-empty" style="color:var(--text-dim);font-size:13px;display:none">
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
    <div class="card-title" style="margin-top:4px">TLS Certificates</div>

    <!-- Format toggle -->
    <div style="display:flex;gap:8px;margin-bottom:16px">
      <button class="format-tab active" id="fmt-pem" onclick="setCertFormat('pem')">PEM files (cert + key)</button>
      <button class="format-tab" id="fmt-p12" onclick="setCertFormat('p12')">PKCS12 / P12</button>
    </div>

    <!-- PEM section -->
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

    <!-- P12 section -->
    <div id="cert-p12-section" style="display:none">
      <div class="upload-row">
        <label class="upload-label">&#128196; P12 / PFX file
          <input type="file" id="file-p12" accept=".p12,.pfx" onchange="setFileLabel(this,'lbl-p12')">
        </label>
        <span class="cert-file-status {{ 'ok' if cert_status.get('has_cert') else 'missing' }}" id="lbl-p12">
          {{ cert_status.get('p12_name','no file') }}
        </span>
      </div>
    </div>

    <!-- CA (shared between PEM and P12 modes) -->
    <div class="upload-row">
      <label class="upload-label">&#128196; CA Certificate <span style="color:var(--text-dim);font-weight:400">(optional — PEM or P12)</span>
        <input type="file" id="file-ca" accept=".pem,.crt,.cer,.p12,.pfx" onchange="setFileLabel(this,'lbl-ca')">
      </label>
      <span class="cert-file-status {{ 'ok' if cert_status.get('has_ca') else '' }}" id="lbl-ca">
        {{ cert_status.get('ca_name','no file') }}
      </span>
    </div>

    <!-- Single shared password -->
    <div class="form-group" style="max-width:320px;margin-top:8px">
      <label class="form-label">Certificate Password</label>
      <input id="cert-password" class="form-input" type="password" placeholder="leave blank if no password">
      <div class="hint">One password for both the private key and any P12 files</div>
    </div>

    <div class="controls" style="margin-top:12px">
      <button class="btn btn-ghost btn-sm" id="upload-btn" onclick="uploadCerts()">&#8679; Upload Certificates</button>
      <span id="cert-upload-status" style="font-size:12px;color:var(--text-dim)">
        {% if cert_status.get('uploaded_at') %}Uploaded {{ cert_status.uploaded_at }}{% endif %}
      </span>
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
const SAVED_REMARKS = {{ saved_remarks_json }};

// ── Remarks Builder ───────────────────────────────────────────────────────────
function remarksFieldOptions(selectedField) {
  const fields = window._discoveredFields || [];
  let opts = '<option value="">-- select field --</option>';
  fields.forEach(f => {
    const label = (f.alias && f.alias !== f.name) ? f.alias + ' (' + f.name + ')' : f.name;
    const sel = f.name === selectedField ? ' selected' : '';
    opts += `<option value="${f.name}"${sel}>${label}</option>`;
  });
  // If selectedField isn't in the discovered list, prepend it so it stays visible
  if (selectedField && !fields.some(f => f.name === selectedField)) {
    opts = `<option value="${selectedField}" selected>${selectedField}</option>` + opts;
  }
  return opts;
}

function addRemarksRow(field, label) {
  const list = document.getElementById('remarks-list');
  const row = document.createElement('div');
  row.className = 'remarks-row';
  row.innerHTML = `
    <input type="text" class="form-input remarks-label" placeholder="Label" value="${label || ''}">
    <select class="form-input remarks-field">${remarksFieldOptions(field || '')}</select>
    <button class="del-btn" onclick="this.closest('.remarks-row').remove()">&#10005;</button>`;
  list.appendChild(row);
}

function collectRemarksFields() {
  return Array.from(document.querySelectorAll('.remarks-row')).map(row => ({
    label: row.querySelector('.remarks-label').value.trim(),
    field: row.querySelector('.remarks-field').value,
  })).filter(r => r.field);
}

function initRemarks() {
  const saved = SAVED_REMARKS.length ? SAVED_REMARKS : [
    {label: 'Mission Number',    field: 'mission_number'},
    {label: 'Sortie Number',     field: 'sortie_number'},
    {label: 'Team Leader',       field: 'team_leader_name'},
    {label: 'Team Leader CAPID', field: 'team_leader_capid'},
    {label: 'Callsign',          field: 'team_callsign'},
  ];
  saved.forEach(r => addRemarksRow(r.field, r.label));
}
document.addEventListener('DOMContentLoaded', initRemarks);

// ── Cert upload ───────────────────────────────────────────────────────────────
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

async function uploadCerts() {
  const btn = document.getElementById('upload-btn');
  const status = document.getElementById('cert-upload-status');
  const password = document.getElementById('cert-password').value;
  const fd = new FormData();
  fd.append('format', _certFormat);
  fd.append('password', password);
  if (_certFormat === 'pem') {
    const cert = document.getElementById('file-cert').files[0];
    const key  = document.getElementById('file-key').files[0];
    if (!cert || !key) { showToast('Select both a certificate and a key file', 'warn'); return; }
    fd.append('cert', cert);
    fd.append('key', key);
  } else {
    const p12 = document.getElementById('file-p12').files[0];
    if (!p12) { showToast('Select a P12 file', 'warn'); return; }
    fd.append('p12', p12);
  }
  const ca = document.getElementById('file-ca').files[0];
  if (ca) fd.append('ca', ca);
  btn.disabled = true;
  status.textContent = 'Uploading…';
  try {
    const res = await fetch('/api/esri/upload-certs', {method: 'POST', body: fd});
    const data = await res.json();
    if (data.ok) {
      showToast(data.message || 'Certificates uploaded', 'success');
      status.textContent = 'Uploaded ' + (data.uploaded_at || '');
    } else {
      showToast(data.error || 'Upload failed', 'error');
      status.textContent = 'Error: ' + (data.error || 'unknown');
    }
  } catch(e) {
    showToast(e.message, 'error');
    status.textContent = 'Error: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

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
  let url = document.getElementById('survey-url').value.trim();
  const token = document.getElementById('survey-token').value.trim();
  const status = document.getElementById('discover-status');
  if (!url) { showToast('Enter a Survey123 URL first', 'error'); return; }
  // Ensure URL ends with /<number>/query
  if (!/\/\d+\/query$/i.test(url)) {
    url = url.endsWith('/') ? url + '0/query' : url + '/0/query';
    document.getElementById('survey-url').value = url;
  }
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
  window._discoveredFields = fields;
  ['field-callsign', 'field-waypoint'].forEach(id => {
    const sel = document.getElementById(id);
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
  // Refresh all remarks field dropdowns, preserving current selections
  document.querySelectorAll('.remarks-field').forEach(sel => {
    const current = sel.value;
    sel.innerHTML = remarksFieldOptions(current);
  });
}

// ── Custom icon upload ─────────────────────────────────────────────────────────
async function uploadCustomIcon(input) {
  if (!input.files || !input.files[0]) return;
  const status = document.getElementById('icon-upload-status');
  const fd = new FormData();
  fd.append('icon', input.files[0]);
  status.textContent = 'Uploading...';
  try {
    const res = await fetch('/api/esri/upload-icon', {method: 'POST', body: fd});
    const data = await res.json();
    if (data.ok) {
      const newOpt = {name: 'Custom: ' + data.filename, path: 'CUSTOM:' + data.filename, custom: true};
      ICON_OPTIONS.push(newOpt);
      // Refresh all existing dropdowns so the new icon appears
      document.querySelectorAll('.icon-sel').forEach(sel => {
        const opt = document.createElement('option');
        opt.value = newOpt.path;
        opt.textContent = newOpt.name;
        sel.insertBefore(opt, sel.lastElementChild); // before Custom path...
      });
      status.textContent = data.filename + ' uploaded';
      showToast('Icon uploaded: ' + data.filename, 'success');
    } else {
      status.textContent = 'Error: ' + (data.error || 'upload failed');
      showToast(data.error || 'Upload failed', 'error');
    }
  } catch(e) {
    status.textContent = 'Error: ' + e.message;
    showToast(e.message, 'error');
  }
  input.value = '';
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

function makeIconRow(val, isOtherRow) {
  const savedPath = SAVED_ICON_MAP[isOtherRow ? '__other__' : val] || (!isOtherRow ? guessIcon(val) : '') || '';
  const isCustomPath = Boolean(savedPath && !ICON_OPTIONS.some(o => o.path === savedPath) && !savedPath.startsWith('CUSTOM:'));
  const opts = ICON_OPTIONS.map(o => {
    const sel = o.path === savedPath ? ' selected' : '';
    return `<option value="${o.path}"${sel}>${o.name}</option>`;
  }).join('');
  const customSel = isCustomPath ? ' selected' : '';
  const customVal = isCustomPath ? savedPath : '';
  const label = isOtherRow
    ? '<em style="color:var(--text-dim)">Other (catch-all for unmatched values)</em>'
    : `<span style="font-family:monospace;font-size:12px">${val}</span>`;
  const deleteBtn = isOtherRow ? '' : `<button class="del-btn" style="flex-shrink:0" onclick="this.closest('tr').remove()">&#10005;</button>`;
  const tr = document.createElement('tr');
  tr.setAttribute('data-value', isOtherRow ? '__other__' : val);
  if (isOtherRow) tr.setAttribute('data-other', '1');
  tr.innerHTML = `
    <td>${label}</td>
    <td style="display:flex;gap:6px;align-items:flex-start;flex-wrap:wrap">
      <select class="form-input icon-sel" style="flex:1;font-size:12px;padding:6px 10px;min-width:160px" onchange="iconSelChange(this)">
        <option value="">-- default icon --</option>
        ${opts}
        <option value="__custom__"${customSel}>Custom path…</option>
      </select>
      ${deleteBtn}
      <input type="text" class="form-input icon-custom"
             style="display:none;width:100%;margin-top:6px;font-size:12px"
             placeholder="hash/Incident Icons/name.png or CUSTOM:filename.png"
             value="${customVal}">
    </td>
    <td><img class="icon-preview" src="" style="height:28px;display:none"
             onerror="this.style.display='none'"></td>`;
  return tr;
}

function renderIconTable(values) {
  const tbody = document.getElementById('icon-table-body');
  const wrap  = document.getElementById('icon-table-wrap');
  const empty = document.getElementById('icon-table-empty');
  // Deduplicate
  const unique = [...new Set(values.map(v => String(v).trim()).filter(Boolean))].sort();
  tbody.innerHTML = '';
  unique.forEach(val => {
    const tr = makeIconRow(val, false);
    tbody.appendChild(tr);
    updateIconPreview(tr.querySelector('.icon-sel'));
    if (tr.querySelector('.icon-custom').value) tr.querySelector('.icon-custom').style.display = 'block';
  });
  // Always append the Other row
  ensureOtherRow();
  wrap.style.display = '';
  empty.style.display = 'none';
}

function ensureOtherRow() {
  const tbody = document.getElementById('icon-table-body');
  if (tbody.querySelector('[data-other]')) return;
  const tr = makeIconRow('__other__', true);
  tbody.appendChild(tr);
  updateIconPreview(tr.querySelector('.icon-sel'));
  if (tr.querySelector('.icon-custom').value) tr.querySelector('.icon-custom').style.display = 'block';
}

document.addEventListener('DOMContentLoaded', () => {
  // Restore icon table from saved config if any mappings exist
  const saved = Object.keys(SAVED_ICON_MAP).filter(k => k !== '__other__');
  if (saved.length) {
    renderIconTable(saved);
  } else {
    ensureOtherRow();
  }
});

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
  if (!path || path === '__custom__') { img.style.display = 'none'; return; }
  if (path.startsWith('CUSTOM:')) {
    img.src = '/api/esri/icon/' + encodeURIComponent(path.slice(7));
  } else {
    img.src = 'https://static.arcgis.com/images/Symbols/Mil2525d/' + path;
  }
  img.style.display = 'inline';
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
    // __other__ with empty selection → omit so defaultIcon is used
  });
  return result;
}

// ── Save config ───────────────────────────────────────────────────────────────
function buildCfg() {
  return {
    survey_url:          document.getElementById('survey-url').value.trim(),
    token:               document.getElementById('survey-token').value.trim(),
    poll_interval:       parseInt(document.getElementById('poll-interval').value) || 60,
    tak_host:            document.getElementById('tak-host').value.trim(),
    tak_port:            parseInt(document.getElementById('tak-port').value) || 8089,
    log_file:            document.getElementById('log-file').value.trim() || 'cot-logged.txt',
    cot_type:            document.getElementById('cot-type').value.trim() || 'a-h-G',
    include_attachments: document.getElementById('include-attachments').checked,
    field_mapping: {
      callsign:     document.getElementById('field-callsign').value,
      waypoint_type:document.getElementById('field-waypoint').value,
    },
    remarks_fields: collectRemarksFields(),
    icon_mapping:   collectIconMap(),
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

        _icon_dir = os.path.join(CONFIG_DIR, 'esri_icons')
        _exts = {'.png', '.jpg', '.jpeg', '.gif', '.svg'}
        custom_icons = []
        if os.path.isdir(_icon_dir):
            custom_icons = sorted(
                f for f in os.listdir(_icon_dir)
                if os.path.splitext(f)[1].lower() in _exts
            )
        icon_options = (
            [{'name': k, 'path': v} for k, v in INCIDENT_ICONS.items()] +
            [{'name': f'Custom: {f}', 'path': f'CUSTOM:{f}', 'custom': True} for f in custom_icons]
        )
        icon_options_json = Markup(json.dumps(icon_options))
        saved_icon_map_json = Markup(json.dumps(cfg.get('icon_mapping', {})))
        saved_remarks_json = Markup(json.dumps(cfg.get('remarks_fields', [])))

        # Cert status for the upload UI
        cp = _cert_paths()
        cs = cfg.get('cert_status', {})
        cert_status = {
            'has_cert':    os.path.exists(cp['cert']),
            'has_key':     os.path.exists(cp['key']),
            'has_ca':      os.path.exists(cp['ca']),
            'cert_name':   cs.get('cert_name', 'no file'),
            'key_name':    cs.get('key_name', 'no file'),
            'p12_name':    cs.get('p12_name', 'no file'),
            'ca_name':     cs.get('ca_name', 'no file'),
            'uploaded_at': cs.get('uploaded_at', ''),
        }

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
            saved_remarks_json=saved_remarks_json,
            cert_status=cert_status,
            custom_icons=custom_icons,
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

    # ── Certificate upload ────────────────────────────────────────────────────

    @app.route('/api/esri/upload-certs', methods=['POST'])
    @login_required
    def esri_upload_certs():
        import tempfile, subprocess as _sp, datetime as _dt
        cert_format = request.form.get('format', 'pem')
        password    = request.form.get('password', '')
        passarg     = f'pass:{password}' if password else 'pass:'

        d = _cert_dir()
        os.makedirs(d, exist_ok=True)

        cert_path = _cert_paths()['cert']
        key_path  = _cert_paths()['key']
        ca_path   = _cert_paths()['ca']

        status = {}

        def run(*args):
            r = _sp.run(list(args), capture_output=True, text=True)
            return r.returncode == 0, r.stderr.strip()

        if cert_format == 'p12':
            p12f = request.files.get('p12')
            if not p12f:
                return jsonify({'ok': False, 'error': 'No P12 file selected'})

            # Save P12 to a temp file so we can run openssl against it
            with tempfile.NamedTemporaryFile(suffix='.p12', delete=False, dir=d) as tmp:
                p12f.save(tmp.name)
                tmp_p12 = tmp.name

            try:
                ok, err = run('openssl', 'pkcs12', '-in', tmp_p12,
                              '-clcerts', '-nokeys', '-out', cert_path, '-passin', passarg)
                if not ok:
                    return jsonify({'ok': False, 'error': 'Could not extract certificate — wrong password? ' + err})

                ok, err = run('openssl', 'pkcs12', '-in', tmp_p12,
                              '-nocerts', '-nodes', '-out', key_path, '-passin', passarg)
                if not ok:
                    return jsonify({'ok': False, 'error': 'Could not extract private key — ' + err})

                # Try to extract CA certs from the P12 (may be empty if not included)
                run('openssl', 'pkcs12', '-in', tmp_p12,
                    '-cacerts', '-nokeys', '-out', ca_path, '-passin', passarg)
            finally:
                try: os.unlink(tmp_p12)
                except Exception: pass

            status['p12_name'] = p12f.filename

        else:  # pem
            certf = request.files.get('cert')
            keyf  = request.files.get('key')
            if not certf or not keyf:
                return jsonify({'ok': False, 'error': 'Select both a certificate and a key file'})

            certf.save(cert_path)
            status['cert_name'] = certf.filename
            status['key_name']  = keyf.filename

            # Save key to temp, decrypt if password given, then save to key_path
            if password:
                with tempfile.NamedTemporaryFile(suffix='.key', delete=False, dir=d) as tmp:
                    keyf.save(tmp.name)
                    tmp_key = tmp.name
                try:
                    ok, err = run('openssl', 'pkey', '-in', tmp_key,
                                  '-out', key_path, '-passin', passarg)
                    if not ok:
                        # Fall back to saving as-is
                        import shutil
                        shutil.copy(tmp_key, key_path)
                finally:
                    try: os.unlink(tmp_key)
                    except Exception: pass
            else:
                keyf.save(key_path)

        # CA cert — may be PEM or P12 (handle both)
        caf = request.files.get('ca')
        if caf:
            fname = caf.filename.lower()
            if fname.endswith('.p12') or fname.endswith('.pfx'):
                with tempfile.NamedTemporaryFile(suffix='.p12', delete=False, dir=d) as tmp:
                    caf.save(tmp.name)
                    tmp_ca = tmp.name
                try:
                    ok, err = run('openssl', 'pkcs12', '-in', tmp_ca,
                                  '-nokeys', '-out', ca_path, '-passin', passarg)
                    if not ok:
                        run('openssl', 'pkcs12', '-in', tmp_ca,
                            '-nokeys', '-out', ca_path, '-passin', 'pass:')
                finally:
                    try: os.unlink(tmp_ca)
                    except Exception: pass
            else:
                caf.save(ca_path)
            status['ca_name'] = caf.filename

        # Restrict permissions so private key isn't world-readable
        for p in (cert_path, key_path, ca_path):
            if os.path.exists(p):
                try: os.chmod(p, 0o600)
                except Exception: pass

        uploaded_at = _dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
        status['uploaded_at'] = uploaded_at

        cfg = _load_cfg(load_settings)
        cfg['cert_status'] = status
        _save_cfg(cfg, load_settings, save_settings)

        return jsonify({'ok': True, 'message': 'Certificates saved', 'uploaded_at': uploaded_at})

    # ── Custom icon upload / serve ────────────────────────────────────────────

    @app.route('/api/esri/upload-icon', methods=['POST'])
    @login_required
    def esri_upload_icon():
        import datetime as _dt
        f = request.files.get('icon')
        if not f or not f.filename:
            return jsonify({'ok': False, 'error': 'No file selected'})
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in {'.png', '.jpg', '.jpeg', '.gif', '.svg'}:
            return jsonify({'ok': False, 'error': 'Only PNG, JPG, GIF, SVG allowed'})
        icon_dir = os.path.join(CONFIG_DIR, 'esri_icons')
        os.makedirs(icon_dir, exist_ok=True)
        safe_name = os.path.basename(f.filename).replace(' ', '_')
        dest = os.path.join(icon_dir, safe_name)
        f.save(dest)
        return jsonify({'ok': True, 'filename': safe_name})

    @app.route('/api/esri/icon/<path:filename>')
    @login_required
    def esri_serve_icon(filename):
        from flask import send_from_directory
        icon_dir = os.path.join(CONFIG_DIR, 'esri_icons')
        return send_from_directory(icon_dir, filename)

    # ── Discover fields ───────────────────────────────────────────────────────

    @app.route('/api/esri/discover-fields')
    @login_required
    def esri_discover_fields():
        raw_url = request.args.get('url', '').strip()
        token   = request.args.get('token', '').strip()
        if not raw_url:
            return jsonify({'ok': False, 'error': 'url parameter is required'})

        # Build the layer metadata URL from whatever the user pasted
        import re as _re
        base = raw_url.rstrip('/')
        # Strip /<number>/query or /query suffix
        base = _re.sub(r'/\d+/query$', '', base, flags=_re.IGNORECASE)
        base = _re.sub(r'/query$', '', base, flags=_re.IGNORECASE)
        # If we're still at the FeatureServer level (no trailing layer number), append /0
        if not _re.search(r'/\d+$', base):
            base = base + '/0'

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
        import re as _re
        base = raw_url.rstrip('/')
        base = _re.sub(r'/\d+/query$', '', base, flags=_re.IGNORECASE)
        base = _re.sub(r'/query$', '', base, flags=_re.IGNORECASE)
        if not _re.search(r'/\d+$', base):
            base = base + '/0'
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

        seen = set()
        values = []
        for feat in data.get('features', []):
            v = feat.get('attributes', {}).get(field)
            if v is not None:
                sv = str(v).strip()
                if sv and sv not in seen:
                    seen.add(sv)
                    values.append(sv)

        return jsonify({'ok': True, 'values': sorted(values)})

    # ── Deploy ────────────────────────────────────────────────────────────────

    @app.route('/api/esri/deploy', methods=['POST'])
    @login_required
    def esri_deploy():
        cfg = request.get_json(silent=True) or {}
        host, port = _nr_host_port()

        if not _nr_running(host, port):
            return jsonify({'ok': False, 'error': f'Node-RED is not reachable at {host}:{port}. Start it from the Node-RED page first.'})

        # Inject icon base URL so custom icons can be resolved in the flow
        _fqdn = load_settings().get('fqdn', '')
        cfg['_icon_base_url'] = ('https://' + _fqdn) if _fqdn else ''

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
