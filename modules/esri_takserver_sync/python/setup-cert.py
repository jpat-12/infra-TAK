#!/usr/bin/env python3
"""
Esri-TAKServer-Sync — Certificate Setup
Generates or imports a .p12 client cert for TAK Server authentication,
exports PEM files for runtime use, and optionally enrolls with TAK Server.
"""

import argparse
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

CERT_DIR    = Path("/opt/Esri-TAKServer-Sync/certs")
CONFIG_PATH = Path("/opt/Esri-TAKServer-Sync/config.json")


# ── Certificate generation ────────────────────────────────────────────────────

def generate_self_signed(name: str, password: str, days: int = 365):
    """
    Generate a self-signed RSA key + cert using openssl, then bundle as .p12.
    Also exports PEM files alongside the .p12 for runtime TLS use.
    """
    CERT_DIR.mkdir(parents=True, exist_ok=True)

    p12_path  = CERT_DIR / f"{name}.p12"
    key_path  = CERT_DIR / f"{name}-key.pem"
    cert_path = CERT_DIR / f"{name}-cert.pem"

    print(f"[*] Generating RSA-4096 key and self-signed cert (CN={name}, days={days})…")

    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:4096",
        "-keyout", str(key_path),
        "-out",    str(cert_path),
        "-days",   str(days),
        "-nodes",
        "-subj",   f"/CN={name}/O=EsriTAKSync"
    ], check=True)

    pass_arg = f"pass:{password}" if password else "pass:"

    subprocess.run([
        "openssl", "pkcs12", "-export",
        "-out",    str(p12_path),
        "-inkey",  str(key_path),
        "-in",     str(cert_path),
        "-name",   name,
        "-passout", pass_arg
    ], check=True)

    # Restrict key permissions
    os.chmod(key_path, 0o600)
    os.chmod(p12_path, 0o600)

    print(f"[+] Certificate files written:")
    print(f"    {p12_path}")
    print(f"    {cert_path}")
    print(f"    {key_path}")

    return p12_path, cert_path, key_path


def import_p12(src_path: str, name: str, password: str):
    """
    Import an existing .p12 and extract PEM cert + key for runtime use.
    Copies the .p12 to CERT_DIR and creates the PEM sidecars.
    """
    CERT_DIR.mkdir(parents=True, exist_ok=True)

    src       = Path(src_path)
    p12_path  = CERT_DIR / f"{name}.p12"
    key_path  = CERT_DIR / f"{name}-key.pem"
    cert_path = CERT_DIR / f"{name}-cert.pem"

    import shutil
    shutil.copy2(src, p12_path)
    os.chmod(p12_path, 0o600)

    pass_arg = f"pass:{password}" if password else "pass:"

    print("[*] Extracting PEM cert from .p12…")
    subprocess.run([
        "openssl", "pkcs12",
        "-in",      str(p12_path),
        "-clcerts", "-nokeys",
        "-out",     str(cert_path),
        "-passin",  pass_arg
    ], check=True)

    print("[*] Extracting PEM key from .p12…")
    subprocess.run([
        "openssl", "pkcs12",
        "-in",     str(p12_path),
        "-nocerts", "-nodes",
        "-out",    str(key_path),
        "-passin", pass_arg
    ], check=True)

    os.chmod(key_path, 0o600)

    print(f"[+] Imported and extracted to {CERT_DIR}")
    return p12_path, cert_path, key_path


# ── TAK Server enrollment ─────────────────────────────────────────────────────

def enroll_with_tak(tak_host: str, tak_admin_user: str, tak_admin_pass: str,
                    cert_pem_path: Path, group: str):
    """
    POST the PEM cert to TAK Server's client cert enrollment endpoint and
    optionally assign it to a user group.

    Note: TAK Server must be running and the admin account must have
    cert management permissions. SSL verification is disabled here since
    TAK Server commonly uses a self-signed CA.
    """
    try:
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except ImportError:
        print("[!] 'requests' library not found — skipping TAK enrollment.")
        print("    Manually add the cert via the TAK Server web UI.")
        return

    with open(cert_pem_path) as f:
        pem_data = f.read()

    url = f"https://{tak_host}:8443/Marti/api/tls/config"
    print(f"[*] Enrolling cert with TAK Server at {url} (group={group})…")

    try:
        resp = requests.post(
            url,
            auth=(tak_admin_user, tak_admin_pass),
            json={"clientCert": pem_data, "group": group},
            verify=False,
            timeout=15
        )
        if resp.status_code == 200:
            print(f"[+] Enrolled successfully. Group: {group}")
        else:
            print(f"[!] TAK Server returned {resp.status_code}: {resp.text}")
            print("    You may need to add the cert manually via the TAK Server web UI.")
    except Exception as exc:
        print(f"[!] Could not reach TAK Server: {exc}")
        print("    Add the cert manually via the TAK Server web UI once it is reachable.")


# ── Config update ─────────────────────────────────────────────────────────────

def update_config(p12_path: Path, password: str, tak_host: str, port: int,
                  use_tls: bool, group: str):
    cfg = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)

    cfg.setdefault("tak_server", {})
    cfg["tak_server"]["host"]          = tak_host
    cfg["tak_server"]["port"]          = port
    cfg["tak_server"]["tls"]           = use_tls
    cfg["tak_server"]["cert_path"]     = str(p12_path)
    cfg["tak_server"]["cert_password"] = password

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"[+] Config updated: {CONFIG_PATH}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Set up .p12 certificate for Esri-TAKServer-Sync"
    )
    parser.add_argument(
        "--import-p12", metavar="FILE",
        help="Path to an existing .p12 to import instead of generating one"
    )
    parser.add_argument(
        "--name", default="esri-push",
        help="Certificate CN / filename prefix (default: esri-push)"
    )
    parser.add_argument(
        "--group", default="esri-push",
        help="TAK Server user group to assign (default: esri-push)"
    )
    parser.add_argument(
        "--days", type=int, default=365,
        help="Validity period for auto-generated cert in days (default: 365)"
    )
    parser.add_argument(
        "--tak-host", default="localhost",
        help="TAK Server hostname or IP (default: localhost)"
    )
    parser.add_argument(
        "--port", type=int, default=8089,
        help="TAK Server CoT TCP port (default: 8089)"
    )
    parser.add_argument(
        "--no-tls", action="store_true",
        help="Disable TLS for TAK Server connection (not recommended)"
    )
    parser.add_argument(
        "--skip-enroll", action="store_true",
        help="Skip TAK Server enrollment (add the cert manually later)"
    )
    args = parser.parse_args()

    password = getpass.getpass("P12 password (leave blank for none): ")

    if args.import_p12:
        p12, cert_pem, key_pem = import_p12(args.import_p12, args.name, password)
    else:
        p12, cert_pem, key_pem = generate_self_signed(args.name, password, args.days)

    if not args.skip_enroll:
        tak_user = input("TAK Server admin username: ")
        tak_pass = getpass.getpass("TAK Server admin password: ")
        enroll_with_tak(args.tak_host, tak_user, tak_pass, cert_pem, args.group)

    update_config(
        p12_path = p12,
        password = password,
        tak_host = args.tak_host,
        port     = args.port,
        use_tls  = not args.no_tls,
        group    = args.group
    )


if __name__ == "__main__":
    main()
