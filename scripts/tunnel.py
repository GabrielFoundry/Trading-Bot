"""
Lance un tunnel Cloudflare gratuit pour exposer le dashboard sur Internet.
Télécharge automatiquement cloudflared si absent (aucune installation requise).
Usage : python scripts/tunnel.py [--port 8000]
"""

from __future__ import annotations

import argparse
import platform
import re
import stat
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

CLOUDFLARED_URLS = {
    "Windows": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    "Linux":   "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    "Darwin":  "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
}

SCRIPTS_DIR = Path(__file__).parent
BINARY_NAME = "cloudflared.exe" if platform.system() == "Windows" else "cloudflared"
BINARY_PATH = SCRIPTS_DIR / BINARY_NAME


def _download_cloudflared() -> None:
    system = platform.system()
    url = CLOUDFLARED_URLS.get(system)
    if not url:
        print(f"[tunnel] Système non supporté : {system}", file=sys.stderr)
        sys.exit(1)

    print(f"[tunnel] Téléchargement de cloudflared depuis {url} …")
    urllib.request.urlretrieve(url, BINARY_PATH)

    if system != "Windows":
        BINARY_PATH.chmod(BINARY_PATH.stat().st_mode | stat.S_IEXEC)
        print("[tunnel] Permissions d'exécution ajoutées.")

    print(f"[tunnel] cloudflared téléchargé → {BINARY_PATH}")


def _ensure_cloudflared() -> Path:
    if BINARY_PATH.exists():
        return BINARY_PATH
    print("[tunnel] cloudflared introuvable — téléchargement automatique…")
    _download_cloudflared()
    return BINARY_PATH


def _display_qr(url: str) -> None:
    """Affiche un QR code dans le terminal si qrcode est disponible."""
    try:
        import qrcode  # type: ignore
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        print("\n" + "═" * 60)
        print("  Scannez ce QR code avec votre téléphone :")
        print("═" * 60)
        qr.print_ascii(invert=True)
        print("═" * 60 + "\n")
    except ImportError:
        pass  # qrcode optionnel


def run_tunnel(port: int = 8000, url_callback=None) -> subprocess.Popen:
    """
    Lance cloudflared en arrière-plan et retourne le process.
    url_callback(url: str) est appelé dès que l'URL publique est connue.
    """
    binary = _ensure_cloudflared()
    cmd = [str(binary), "tunnel", "--url", f"http://localhost:{port}"]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    url_found = threading.Event()

    def _reader():
        url = None
        for line in process.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if line:
                print(f"[cloudflared] {line}")

            # Cherche l'URL publique dans la sortie
            match = re.search(r"https://[a-z0-9\-]+\.trycloudflare\.com", line)
            if match and not url_found.is_set():
                url = match.group(0)
                url_found.set()
                _on_url_found(url, url_callback)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()

    return process


def _on_url_found(url: str, callback=None) -> None:
    print("\n" + "═" * 60)
    print("  TUNNEL ACTIF")
    print(f"  URL publique : {url}")
    print("  (Valable jusqu'à l'arrêt du programme)")
    print("═" * 60 + "\n")
    _display_qr(url)
    if callback:
        callback(url)


def main() -> None:
    parser = argparse.ArgumentParser(description="Lance le tunnel Cloudflare")
    parser.add_argument("--port", type=int, default=8000, help="Port local à exposer")
    args = parser.parse_args()

    print(f"[tunnel] Démarrage du tunnel → http://localhost:{args.port}")
    process = run_tunnel(port=args.port)

    try:
        process.wait()
    except KeyboardInterrupt:
        print("\n[tunnel] Arrêt du tunnel.")
        process.terminate()


if __name__ == "__main__":
    main()
