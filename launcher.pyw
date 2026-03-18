"""
Lanceur GUI sans terminal pour le Trading Bot.
Double-cliquez sur ce fichier pour démarrer le bot et le dashboard.
Extension .pyw = pas de fenêtre console sur Windows.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, scrolledtext

ROOT = Path(__file__).parent


# ─────────────────────────────────────────────────────────────────────────────
# Constantes UI
# ─────────────────────────────────────────────────────────────────────────────
CLR_BG       = "#1a1a2e"
CLR_CARD     = "#16213e"
CLR_GREEN    = "#00d4aa"
CLR_RED      = "#ff4757"
CLR_ORANGE   = "#ffa502"
CLR_TEXT     = "#e0e0e0"
CLR_MUTED    = "#8892a4"
CLR_BORDER   = "#2d3561"


class LauncherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Trading Bot Launcher")
        self.geometry("700x560")
        self.minsize(600, 480)
        self.configure(bg=CLR_BG)
        self.resizable(True, True)

        # Processes
        self._uvicorn_proc: subprocess.Popen | None = None
        self._bot_proc:     subprocess.Popen | None = None
        self._tunnel_proc:  subprocess.Popen | None = None
        self._tunnel_url:   str = ""

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Démarrage automatique du serveur web (sans le bot de trading)
        self.after(500, self._start_server)

    # ─────────────────────────────────────────────────────────────────────────
    # Construction de l'interface
    # ─────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Titre
        header = tk.Frame(self, bg=CLR_BG)
        header.pack(fill=tk.X, padx=20, pady=(18, 4))

        tk.Label(
            header, text="🤖  Trading Bot", bg=CLR_BG, fg=CLR_GREEN,
            font=("Segoe UI", 22, "bold"),
        ).pack(side=tk.LEFT)

        self._status_lbl = tk.Label(
            header, text="⬤  Démarrage…", bg=CLR_BG, fg=CLR_ORANGE,
            font=("Segoe UI", 11),
        )
        self._status_lbl.pack(side=tk.RIGHT, padx=6)

        # Carte URLs
        url_card = tk.Frame(self, bg=CLR_CARD, bd=0, highlightthickness=1,
                            highlightbackground=CLR_BORDER)
        url_card.pack(fill=tk.X, padx=20, pady=(10, 4))

        tk.Label(url_card, text="Accès au Dashboard", bg=CLR_CARD, fg=CLR_MUTED,
                 font=("Segoe UI", 9)).pack(anchor=tk.W, padx=12, pady=(8, 0))

        # WiFi local
        local_row = tk.Frame(url_card, bg=CLR_CARD)
        local_row.pack(fill=tk.X, padx=12, pady=2)
        tk.Label(local_row, text="📶 WiFi local :", bg=CLR_CARD, fg=CLR_MUTED,
                 font=("Segoe UI", 9), width=13, anchor=tk.W).pack(side=tk.LEFT)
        self._local_url_lbl = tk.Label(
            local_row, text="http://localhost:8000", bg=CLR_CARD, fg=CLR_TEXT,
            font=("Consolas", 10), cursor="hand2",
        )
        self._local_url_lbl.pack(side=tk.LEFT)
        self._local_url_lbl.bind("<Button-1>", lambda _: self._open_url("http://localhost:8000"))

        # Tunnel
        tunnel_row = tk.Frame(url_card, bg=CLR_CARD)
        tunnel_row.pack(fill=tk.X, padx=12, pady=(2, 10))
        tk.Label(tunnel_row, text="🌐 Internet :", bg=CLR_CARD, fg=CLR_MUTED,
                 font=("Segoe UI", 9), width=13, anchor=tk.W).pack(side=tk.LEFT)
        self._tunnel_lbl = tk.Label(
            tunnel_row, text="(tunnel non démarré)", bg=CLR_CARD, fg=CLR_MUTED,
            font=("Consolas", 10), cursor="hand2",
        )
        self._tunnel_lbl.pack(side=tk.LEFT)
        self._tunnel_lbl.bind("<Button-1>", lambda _: self._open_url(self._tunnel_url))

        # Boutons principaux
        btn_frame = tk.Frame(self, bg=CLR_BG)
        btn_frame.pack(fill=tk.X, padx=20, pady=(10, 6))

        btn_cfg = {"font": ("Segoe UI", 12, "bold"), "relief": tk.FLAT,
                   "cursor": "hand2", "pady": 10, "padx": 18}

        self._btn_start = tk.Button(
            btn_frame, text="▶  Démarrer le Bot",
            bg=CLR_GREEN, fg="#000",
            command=self._start_bot, **btn_cfg,
        )
        self._btn_start.pack(side=tk.LEFT, padx=(0, 8))

        self._btn_stop = tk.Button(
            btn_frame, text="■  Arrêter le Bot",
            bg=CLR_RED, fg="#fff",
            command=self._stop_bot, state=tk.DISABLED, **btn_cfg,
        )
        self._btn_stop.pack(side=tk.LEFT, padx=(0, 8))

        self._btn_tunnel = tk.Button(
            btn_frame, text="🌐  Activer tunnel",
            bg=CLR_CARD, fg=CLR_TEXT,
            command=self._toggle_tunnel, **btn_cfg,
        )
        self._btn_tunnel.pack(side=tk.LEFT)

        # Zone de logs
        tk.Label(self, text="Journal", bg=CLR_BG, fg=CLR_MUTED,
                 font=("Segoe UI", 9)).pack(anchor=tk.W, padx=22, pady=(6, 0))

        log_frame = tk.Frame(self, bg=CLR_CARD, bd=0, highlightthickness=1,
                             highlightbackground=CLR_BORDER)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(2, 16))

        self._log = scrolledtext.ScrolledText(
            log_frame, bg=CLR_CARD, fg=CLR_TEXT,
            font=("Consolas", 9), relief=tk.FLAT,
            state=tk.DISABLED, wrap=tk.WORD,
        )
        self._log.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    # ─────────────────────────────────────────────────────────────────────────
    # Logging thread-safe
    # ─────────────────────────────────────────────────────────────────────────

    def _log_msg(self, msg: str, color: str = CLR_TEXT) -> None:
        def _insert():
            self._log.config(state=tk.NORMAL)
            self._log.insert(tk.END, msg + "\n")
            self._log.see(tk.END)
            self._log.config(state=tk.DISABLED)
        self.after(0, _insert)

    # ─────────────────────────────────────────────────────────────────────────
    # Serveur web (uvicorn) — démarre automatiquement
    # ─────────────────────────────────────────────────────────────────────────

    def _start_server(self):
        self._log_msg("[launcher] Démarrage du serveur web…")
        self._uvicorn_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.main:app",
             "--host", "0.0.0.0", "--port", "8000"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        threading.Thread(
            target=self._pipe_output, args=(self._uvicorn_proc, "[API] "),
            daemon=True,
        ).start()
        self._status_lbl.config(text="⬤  Dashboard actif", fg=CLR_GREEN)
        self._log_msg("[launcher] Dashboard disponible → http://localhost:8000")

    # ─────────────────────────────────────────────────────────────────────────
    # Bot de trading
    # ─────────────────────────────────────────────────────────────────────────

    def _start_bot(self):
        if self._bot_proc and self._bot_proc.poll() is None:
            return
        self._log_msg("[launcher] Démarrage du bot de trading…")
        self._bot_proc = subprocess.Popen(
            [sys.executable, "-m", "bot.main"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        threading.Thread(
            target=self._pipe_output, args=(self._bot_proc, "[BOT] "),
            daemon=True,
        ).start()
        self._btn_start.config(state=tk.DISABLED)
        self._btn_stop.config(state=tk.NORMAL)
        self._status_lbl.config(text="⬤  Bot en cours", fg=CLR_GREEN)

    def _stop_bot(self):
        if self._bot_proc and self._bot_proc.poll() is None:
            self._bot_proc.terminate()
            self._log_msg("[launcher] Bot arrêté.")
        self._btn_start.config(state=tk.NORMAL)
        self._btn_stop.config(state=tk.DISABLED)
        self._status_lbl.config(text="⬤  Bot arrêté", fg=CLR_ORANGE)

    # ─────────────────────────────────────────────────────────────────────────
    # Tunnel Cloudflare
    # ─────────────────────────────────────────────────────────────────────────

    def _toggle_tunnel(self):
        if self._tunnel_proc and self._tunnel_proc.poll() is None:
            self._tunnel_proc.terminate()
            self._tunnel_url = ""
            self._tunnel_lbl.config(text="(tunnel arrêté)", fg=CLR_MUTED)
            self._btn_tunnel.config(text="🌐  Activer tunnel")
            self._log_msg("[launcher] Tunnel Cloudflare arrêté.")
        else:
            self._start_tunnel()

    def _start_tunnel(self):
        self._log_msg("[launcher] Démarrage du tunnel Cloudflare…")
        self._btn_tunnel.config(text="⏳  Tunnel…", state=tk.DISABLED)
        self._tunnel_proc = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "tunnel.py"), "--port", "8000"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        threading.Thread(target=self._watch_tunnel, daemon=True).start()

    def _watch_tunnel(self):
        import re
        for line in self._tunnel_proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if line:
                self._log_msg(line)
            match = re.search(r"https://[a-z0-9\-]+\.trycloudflare\.com", line)
            if match:
                url = match.group(0)
                self._tunnel_url = url
                self.after(0, lambda u=url: self._on_tunnel_url(u))

    def _on_tunnel_url(self, url: str):
        self._tunnel_lbl.config(text=url, fg=CLR_GREEN)
        self._btn_tunnel.config(text="■  Arrêter tunnel", state=tk.NORMAL)
        self._log_msg(f"[launcher] Tunnel actif → {url}")
        # Essayer d'afficher un QR code dans une fenêtre séparée
        self._show_qr_window(url)

    def _show_qr_window(self, url: str):
        try:
            import qrcode
            from PIL import ImageTk
            img = qrcode.make(url)
            win = tk.Toplevel(self)
            win.title("QR Code — Tunnel")
            win.configure(bg=CLR_BG)
            tk_img = ImageTk.PhotoImage(img)
            tk.Label(win, image=tk_img, bg=CLR_BG).pack(padx=16, pady=12)
            tk.Label(win, text=url, bg=CLR_BG, fg=CLR_GREEN,
                     font=("Consolas", 10)).pack(pady=(0, 12))
            win.tk_img = tk_img  # évite le GC
        except ImportError:
            pass  # qrcode / Pillow optionnels

    # ─────────────────────────────────────────────────────────────────────────
    # Utilitaires
    # ─────────────────────────────────────────────────────────────────────────

    def _pipe_output(self, proc: subprocess.Popen, prefix: str):
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if line:
                self._log_msg(prefix + line)

    def _open_url(self, url: str):
        if not url:
            return
        import webbrowser
        webbrowser.open(url)

    def _on_close(self):
        if messagebox.askokcancel("Quitter", "Arrêter le bot et fermer le launcher ?"):
            for proc in (self._bot_proc, self._tunnel_proc, self._uvicorn_proc):
                if proc and proc.poll() is None:
                    proc.terminate()
            self.destroy()


if __name__ == "__main__":
    app = LauncherApp()
    app.mainloop()
