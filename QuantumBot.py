import os
import sys
import csv
import time
import json
import uuid
import math
import random
import re
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import ccxt
except ImportError:
    ccxt = None

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

def _looks_like_quantumbot_data_dir(path: Path) -> bool:
    data_files = (
        "registro_trade.csv",
        "config.json",
        "status_bot.json",
        "eventi_bot.log",
        "QuantumBot.app",
    )
    return path.exists() and any((path / name).exists() for name in data_files)


def _bootstrap_app_directory() -> Path:
    env_dir = os.environ.get("QUANTUMBOT_APP_DIR")
    if env_dir:
        candidate = Path(env_dir).expanduser()
        if _looks_like_quantumbot_data_dir(candidate) or candidate.exists():
            return candidate

    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        for parent in exe_path.parents:
            if parent.suffix == ".app":
                return parent.parent
        return exe_path.parent

    try:
        script_dir = Path(__file__).resolve().parent
    except Exception:
        script_dir = Path.cwd()

    dist_dir = script_dir / "dist"
    if _looks_like_quantumbot_data_dir(dist_dir):
        return dist_dir
    return script_dir


def _is_writable_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        test_file = path / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def configure_matplotlib_cache():
    """Imposta una cache Matplotlib scrivibile prima dell'import di matplotlib."""
    candidates = []
    existing = os.environ.get("MPLCONFIGDIR")
    if existing:
        candidates.append(Path(existing).expanduser())

    candidates.append(_bootstrap_app_directory() / ".quantumbot_matplotlib")

    try:
        user_id = os.getuid()
    except Exception:
        user_id = "user"
    candidates.append(Path(tempfile.gettempdir()) / f"quantumbot_matplotlib_{user_id}")

    for candidate in candidates:
        if _is_writable_directory(candidate):
            os.environ["MPLCONFIGDIR"] = str(candidate)
            return


configure_matplotlib_cache()

import matplotlib
try:
    # TkAgg è il backend corretto per la dashboard Tkinter su macOS.
    # In ambienti senza interfaccia grafica, per esempio durante test/compile,
    # usiamo Agg per evitare crash all'import.
    if sys.platform == "darwin" or os.name == "nt" or os.environ.get("DISPLAY"):
        matplotlib.use("TkAgg")
    else:
        matplotlib.use("Agg")
except Exception:
    pass
import matplotlib.patches
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


# ============================================================
# QUANTUM BOT STUDIO v1.0.0 - DASHBOARD COMPATTA + POPUP
# Dashboard + Engine separato, ottimizzato per macOS.
#
# - Se chiudi la Dashboard, l'Engine continua a lavorare.
# - Per fermare davvero il bot usa il pulsante "Ferma Bot".
# - Trading simulato interno: compra, vendi 25/50/75/100, chiudi tutto.
# - Dati reali Binance con fallback BASE/EUR -> BASE/USDT convertito in EUR.
# - Grafico linea, candele e confronto multi-crypto normalizzato in %.
# - Auto Profit/Loss con Take Profit e Stop Loss configurabili.
# - Layout più morbido: pulsanti arrotondati, card soft e pannelli meno squadrati.
# - Percentuale investimento visibile e configurabile dalla dashboard.
# - Auto Trade opzionale: acquisto/vendita automatica simulata su soglie RSI.
# - Modalità trading selezionabile: Conservativa, Normale, Aggressiva, Ultra.
# - Dashboard scrollabile verticalmente/orizzontalmente per finestre ridotte.
# - Tema visuale più moderno: palette deep navy, pannelli soft, bordi sottili.
# ============================================================

APP_VERSION = "v1.0.0"
ENGINE_ENV_FLAG = "QUANTUMBOT_ENGINE_MODE"


# ============================================================
# PERCORSI
# ============================================================

def get_app_directory() -> Path:
    """
    Cartella in cui salvare config/log/status.

    Script .py:
        cartella del file .py

    PyInstaller macOS .app:
        cartella che contiene QuantumBot.app
    """
    return _bootstrap_app_directory()


APP_DIR = get_app_directory()
FILE_CONFIG = APP_DIR / "config.json"
FILE_STATUS = APP_DIR / "status_bot.json"
FILE_COMMANDI = APP_DIR / "comandi_bot.jsonl"
FILE_COMMAND_STATE = APP_DIR / "comandi_state.json"
FILE_PID = APP_DIR / "engine.pid"
FILE_LOG = APP_DIR / "registro_trade.csv"
FILE_ERRORI = APP_DIR / "errori_bot.log"
FILE_EVENTI = APP_DIR / "eventi_bot.log"
FILE_ENGINE_STDOUT = APP_DIR / "engine_stdout.log"
FILE_ENGINE_STDERR = APP_DIR / "engine_stderr.log"
FILE_ENGINE_LAUNCH = APP_DIR / "engine_launch.log"

REGISTRO_FIELDNAMES = [
    "Data_Ora",
    "Crypto",
    "Operazione",
    "Prezzo_EUR",
    "RSI",
    "Saldo_EUR",
    "Quantita",
    "Importo_EUR",
    "Commissione_EUR",
    "Profitto_EUR",
    "Percentuale",
    "Note",
]


# ============================================================
# WIDGET GRAFICI CUSTOM: PULSANTI E CARD ARROTONDATE
# ============================================================

class RoundedButton(tk.Canvas):
    """Pulsante arrotondato disegnato su Canvas.

    Tkinter/ttk non offre veri bordi arrotondati in modo affidabile con il tema
    scuro, soprattutto quando si forza il tema "clam". Questo widget mantiene
    un aspetto coerente su macOS sia da script sia da app PyInstaller.
    """

    def __init__(
        self,
        master,
        text,
        command=None,
        bg_color="#21262d",
        hover_color="#30363d",
        active_color="#1f6feb",
        fg_color="#ffffff",
        canvas_bg=None,
        radius=18,
        height=34,
        min_width=92,
        font=("Helvetica", 9, "bold"),
        padx=18,
        **kwargs,
    ):
        self.text = text
        self.command = command
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.active_color = active_color
        self.fg_color = fg_color
        self.radius = radius
        self.btn_height = height
        self.min_width = min_width
        self.font = font
        self.padx = padx
        self._state = "normal"
        self._pressed = False

        if canvas_bg is None:
            try:
                canvas_bg = master.cget("bg")
            except Exception:
                canvas_bg = "#0d1117"

        width = max(min_width, len(str(text)) * 8 + padx * 2)
        super().__init__(
            master,
            width=width,
            height=height,
            bg=canvas_bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            **kwargs,
        )

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", lambda _event: self._draw())
        self._draw()

    def _rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        return self.create_polygon(points, smooth=True, splinesteps=24, **kwargs)

    def _current_color(self):
        if self._state == "pressed":
            return self.active_color
        if self._state == "hover":
            return self.hover_color
        return self.bg_color

    def _draw(self):
        self.delete("all")
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        self._rounded_rect(1, 1, w - 1, h - 1, self.radius, fill=self._current_color(), outline="")
        self.create_text(w / 2, h / 2, text=self.text, fill=self.fg_color, font=self.font)

    def _on_enter(self, _event=None):
        self._state = "hover"
        self._draw()

    def _on_leave(self, _event=None):
        self._state = "normal"
        self._pressed = False
        self._draw()

    def _on_press(self, _event=None):
        self._state = "pressed"
        self._pressed = True
        self._draw()

    def _on_release(self, event=None):
        inside = True
        if event is not None:
            inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        self._state = "hover" if inside else "normal"
        self._draw()
        if inside and self._pressed and callable(self.command):
            self.command()
        self._pressed = False

    def configure(self, cnf=None, **kwargs):
        cnf = cnf or {}
        if isinstance(cnf, dict):
            kwargs.update(cnf)
        if "text" in kwargs:
            self.text = kwargs.pop("text")
            width = max(self.min_width, len(str(self.text)) * 8 + self.padx * 2)
            super().configure(width=width)
        if "command" in kwargs:
            self.command = kwargs.pop("command")
        if "bg_color" in kwargs:
            self.bg_color = kwargs.pop("bg_color")
        if "hover_color" in kwargs:
            self.hover_color = kwargs.pop("hover_color")
        if "active_color" in kwargs:
            self.active_color = kwargs.pop("active_color")
        if "fg_color" in kwargs:
            self.fg_color = kwargs.pop("fg_color")
        if kwargs:
            super().configure(**kwargs)
        self._draw()

    config = configure


class RoundedMetricCard(tk.Canvas):
    """Card superiore con sfondo arrotondato e testo aggiornato da StringVar."""

    def __init__(
        self,
        master,
        label,
        value_var,
        panel_bg,
        canvas_bg,
        muted_fg,
        value_fg,
        radius=20,
        height=86,
        **kwargs,
    ):
        super().__init__(master, height=height, bg=canvas_bg, highlightthickness=0, bd=0, **kwargs)
        self.label = label
        self.value_var = value_var
        self.panel_bg = panel_bg
        self.muted_fg = muted_fg
        self.value_fg = value_fg
        self.radius = radius
        self.value_var.trace_add("write", lambda *_: self._draw())
        self.bind("<Configure>", lambda _event: self._draw())
        self._draw()

    def _rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        return self.create_polygon(points, smooth=True, splinesteps=24, **kwargs)

    def _draw(self):
        self.delete("all")
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        self._rounded_rect(1, 1, w - 1, h - 1, self.radius, fill=self.panel_bg, outline="#263852", width=1)
        self._rounded_rect(12, 10, 48, 14, 3, fill=self.value_fg, outline="")
        self.create_text(14, 28, text=self.label, anchor="w", fill=self.muted_fg, font=("Helvetica", 9))
        self.create_text(14, 55, text=self.value_var.get(), anchor="w", fill=self.value_fg, font=("Helvetica", 13, "bold"))


# ============================================================
# MODALITÀ TRADING
# ============================================================

TRADING_MODE_PRESETS = {
    "Conservativa": {
        "risk_percent": 3.0,
        "buy_rsi": 30.0,
        "sell_rsi": 70.0,
        "take_profit": 2.5,
        "stop_loss": 3.0,
        "timeframe": "5m",
        "descrizione": "Pochi ingressi, posizione piccola, segnali più selettivi."
    },
    "Normale": {
        "risk_percent": 5.0,
        "buy_rsi": 35.0,
        "sell_rsi": 65.0,
        "take_profit": 2.0,
        "stop_loss": 3.0,
        "timeframe": "1m",
        "descrizione": "Equilibrio tra frequenza operativa e prudenza."
    },
    "Aggressiva": {
        "risk_percent": 10.0,
        "buy_rsi": 45.0,
        "sell_rsi": 60.0,
        "take_profit": 1.5,
        "stop_loss": 2.5,
        "timeframe": "1m",
        "descrizione": "Più ingressi, posizione più grande, uscite più rapide."
    },
    "Ultra aggressiva": {
        "risk_percent": 15.0,
        "buy_rsi": 50.0,
        "sell_rsi": 58.0,
        "take_profit": 1.0,
        "stop_loss": 2.0,
        "timeframe": "1m",
        "descrizione": "Massima frequenza simulata: molti falsi segnali possibili."
    },
}


def normalizza_modalita_trading(value):
    value = str(value or "Normale").strip()
    if value.lower() == "personalizzata":
        return "Personalizzata"
    if value.lower() in {"ultra", "ultra aggressiva", "ultra-aggressiva"}:
        return "Ultra aggressiva"
    for nome in TRADING_MODE_PRESETS:
        if value.lower() == nome.lower():
            return nome
    return "Normale"


def applica_modalita_a_config(cfg, modalita):
    modalita = normalizza_modalita_trading(modalita)
    if modalita == "Personalizzata":
        modalita = "Normale"
    preset = TRADING_MODE_PRESETS[modalita]
    cfg["modalita_trading"] = modalita
    cfg["percentuale_rischio_per_trade"] = float(preset["risk_percent"])
    cfg["soglia_acquisto"] = float(preset["buy_rsi"])
    cfg["soglia_vendita"] = float(preset["sell_rsi"])
    cfg["take_profit_percentuale"] = float(preset["take_profit"])
    cfg["stop_loss_percentuale"] = float(preset["stop_loss"])
    cfg["timeframe"] = preset["timeframe"] if preset["timeframe"] in VALID_TIMEFRAMES else "1m"
    return modalita, preset


def descrizione_modalita_trading(modalita):
    modalita = normalizza_modalita_trading(modalita)
    if modalita == "Personalizzata":
        return "Personalizzata"
    p = TRADING_MODE_PRESETS[modalita]
    return (
        f"{modalita} · Inv. {p['risk_percent']:.0f}% · "
        f"Buy RSI≤{p['buy_rsi']:.0f} · Sell RSI≥{p['sell_rsi']:.0f} · "
        f"TP {p['take_profit']:.1f}% · SL {p['stop_loss']:.1f}% · TF {p['timeframe']}"
    )


# ============================================================
# DEFAULT CONFIG
# ============================================================

DEFAULT_CONFIG = {
    "crypto_base_list": [
        "BTC", "ETH", "SOL", "BNB", "XRP",
        "ADA", "DOGE", "DOT", "LINK", "SHIB",
        "AVAX", "MATIC", "LTC", "UNI", "NEAR",
        "ATOM", "ICP", "XLM", "ETC", "FIL"
    ],
    "timeframe": "1m",
    "periodo_rsi": 14,
    "soglia_acquisto": 35,
    "soglia_vendita": 65,
    "take_profit_percentuale": 2.0,
    "stop_loss_percentuale": 3.0,
    "auto_profit_loss_attivo": True,
    "auto_trading_attivo": False,
    "modalita_trading": "Normale",
    "percentuale_rischio_per_trade": 5.0,
    "commissione_percentuale": 0.1,
    "saldo_eur": 5000.0,
    "totale_acquisti": 0,
    "totale_vendite": 0,
    "profitto_accumulato": 0.0,
    "storico_saldi": [5000.0],
    "crypto_in_pancia": {},
    "prezzo_acquisto_effettivo": {},
    "importo_speso_effettivo": {},
    "posizioni_aperte": {}
}

VALID_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h"]


# ============================================================
# UTILITY FILE / LOG
# ============================================================

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def format_eur(value, decimals=2):
    try:
        return f"{float(value):,.{decimals}f} EUR".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0,00 EUR"


def format_price(value):
    try:
        value = float(value)
        if abs(value) < 1:
            return f"{value:.8f} EUR"
        if abs(value) < 100:
            return f"{value:.4f} EUR"
        return f"{value:.2f} EUR"
    except Exception:
        return "-"


def format_pct(value):
    try:
        return f"{float(value):+.2f}%"
    except Exception:
        return "+0.00%"


def has_value(value) -> bool:
    return value is not None and str(value).strip() != ""


def format_quantita(value):
    if not has_value(value):
        return "-"
    try:
        value = float(str(value).replace(",", "."))
        if abs(value) < 0.000001:
            return f"{value:.10f}".rstrip("0").rstrip(".") or "0"
        if abs(value) < 1:
            return f"{value:.8f}".rstrip("0").rstrip(".")
        return f"{value:.6f}".rstrip("0").rstrip(".")
    except Exception:
        return "-"


def format_eur_detail(value):
    if not has_value(value):
        return "-"
    return format_eur(safe_float(value))


def format_signed_eur(value):
    if not has_value(value):
        return "-"
    value = safe_float(value)
    return f"{value:+.2f} EUR"


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(float(str(value).replace(",", ".")))
    except Exception:
        return default


def safe_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0

    value = str(value).strip().lower()
    if value in {"1", "true", "vero", "yes", "si", "sì", "on"}:
        return True
    if value in {"0", "false", "falso", "no", "off"}:
        return False
    return default


def normalizza_lista_crypto(lista):
    risultato = []
    if not isinstance(lista, list):
        lista = DEFAULT_CONFIG["crypto_base_list"]

    for item in lista:
        base = str(item).split("/")[0].strip().upper()
        if base and base not in risultato:
            risultato.append(base)

    return risultato or list(DEFAULT_CONFIG["crypto_base_list"])


def simbolo_visuale(base: str) -> str:
    return f"{str(base).split('/')[0].strip().upper()}/EUR"


def log_errore(messaggio, eccezione=None):
    try:
        with open(FILE_ERRORI, "a", encoding="utf-8") as f:
            if eccezione is None:
                f.write(f"[{now_str()}] {messaggio}\n")
            else:
                f.write(f"[{now_str()}] {messaggio} | {repr(eccezione)}\n")
    except Exception:
        pass


def log_evento(messaggio):
    try:
        with open(FILE_EVENTI, "a", encoding="utf-8") as f:
            f.write(f"[{now_str()}] {messaggio}\n")
    except Exception:
        pass


def load_json_file(path: Path, default):
    try:
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log_errore(f"Errore lettura JSON: {path}", e)
        return default


def save_json_atomic(path: Path, data):
    try:
        temp = path.with_suffix(path.suffix + ".tmp")
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(temp, path)
    except Exception as e:
        log_errore(f"Errore salvataggio JSON: {path}", e)


def deep_copy_json(obj):
    return json.loads(json.dumps(obj))


def inizializza_dizionari_config(cfg):
    cfg["crypto_base_list"] = normalizza_lista_crypto(cfg.get("crypto_base_list", DEFAULT_CONFIG["crypto_base_list"]))

    for key in ("crypto_in_pancia", "prezzo_acquisto_effettivo", "importo_speso_effettivo", "posizioni_aperte"):
        if not isinstance(cfg.get(key), dict):
            cfg[key] = {}

    for base in cfg["crypto_base_list"]:
        sym = simbolo_visuale(base)
        cfg["crypto_in_pancia"].setdefault(sym, 0.0)
        cfg["prezzo_acquisto_effettivo"].setdefault(sym, 0.0)
        cfg["importo_speso_effettivo"].setdefault(sym, 0.0)
        cfg["posizioni_aperte"].setdefault(sym, False)
        cfg["crypto_in_pancia"][sym] = safe_float(cfg["crypto_in_pancia"].get(sym, 0.0))
        cfg["prezzo_acquisto_effettivo"][sym] = safe_float(cfg["prezzo_acquisto_effettivo"].get(sym, 0.0))
        cfg["importo_speso_effettivo"][sym] = safe_float(cfg["importo_speso_effettivo"].get(sym, 0.0))
        cfg["posizioni_aperte"][sym] = safe_bool(cfg["posizioni_aperte"].get(sym, False))


def carica_config():
    cfg = deep_copy_json(DEFAULT_CONFIG)

    if FILE_CONFIG.exists():
        loaded = load_json_file(FILE_CONFIG, {})
        if isinstance(loaded, dict):
            cfg.update(loaded)

    # Compatibilità con vecchi config.
    if "crypto_da_monitorare" in cfg and "crypto_base_list" not in cfg:
        cfg["crypto_base_list"] = cfg["crypto_da_monitorare"]

    cfg["crypto_base_list"] = normalizza_lista_crypto(cfg.get("crypto_base_list", DEFAULT_CONFIG["crypto_base_list"]))

    if cfg.get("timeframe") not in VALID_TIMEFRAMES:
        cfg["timeframe"] = "1m"

    # Compatibilità con vecchi config: queste chiavi possono mancare se arrivi da v6.8/v6.9.
    cfg.setdefault("auto_profit_loss_attivo", True)
    cfg.setdefault("auto_trading_attivo", False)
    cfg["modalita_trading"] = normalizza_modalita_trading(cfg.get("modalita_trading", "Normale"))
    cfg.setdefault("percentuale_rischio_per_trade", 5.0)
    cfg.setdefault("soglia_acquisto", 35)
    cfg.setdefault("soglia_vendita", 65)

    cfg["periodo_rsi"] = max(2, safe_int(cfg.get("periodo_rsi", DEFAULT_CONFIG["periodo_rsi"]), DEFAULT_CONFIG["periodo_rsi"]))
    cfg["soglia_acquisto"] = min(99.0, max(1.0, safe_float(cfg.get("soglia_acquisto"), DEFAULT_CONFIG["soglia_acquisto"])))
    cfg["soglia_vendita"] = min(99.0, max(1.0, safe_float(cfg.get("soglia_vendita"), DEFAULT_CONFIG["soglia_vendita"])))
    cfg["take_profit_percentuale"] = min(100.0, max(0.1, safe_float(cfg.get("take_profit_percentuale"), DEFAULT_CONFIG["take_profit_percentuale"])))
    cfg["stop_loss_percentuale"] = min(100.0, max(0.1, safe_float(cfg.get("stop_loss_percentuale"), DEFAULT_CONFIG["stop_loss_percentuale"])))
    cfg["percentuale_rischio_per_trade"] = min(100.0, max(0.1, safe_float(cfg.get("percentuale_rischio_per_trade"), DEFAULT_CONFIG["percentuale_rischio_per_trade"])))
    cfg["commissione_percentuale"] = min(10.0, max(0.0, safe_float(cfg.get("commissione_percentuale"), DEFAULT_CONFIG["commissione_percentuale"])))
    cfg["saldo_eur"] = max(0.0, safe_float(cfg.get("saldo_eur"), DEFAULT_CONFIG["saldo_eur"]))
    cfg["profitto_accumulato"] = safe_float(cfg.get("profitto_accumulato"), DEFAULT_CONFIG["profitto_accumulato"])
    cfg["totale_acquisti"] = max(0, safe_int(cfg.get("totale_acquisti"), DEFAULT_CONFIG["totale_acquisti"]))
    cfg["totale_vendite"] = max(0, safe_int(cfg.get("totale_vendite"), DEFAULT_CONFIG["totale_vendite"]))
    cfg["auto_profit_loss_attivo"] = safe_bool(cfg.get("auto_profit_loss_attivo"), True)
    cfg["auto_trading_attivo"] = safe_bool(cfg.get("auto_trading_attivo"), False)

    if not isinstance(cfg.get("storico_saldi"), list) or len(cfg.get("storico_saldi", [])) == 0:
        cfg["storico_saldi"] = [cfg["saldo_eur"]]
    else:
        cfg["storico_saldi"] = [round(max(0.0, safe_float(v, cfg["saldo_eur"])), 2) for v in cfg["storico_saldi"][-300:]]

    inizializza_dizionari_config(cfg)
    return cfg


def salva_config(cfg):
    inizializza_dizionari_config(cfg)
    save_json_atomic(FILE_CONFIG, cfg)


def _parse_numero_da_testo(pattern, text, default=""):
    match = re.search(pattern, str(text or ""), flags=re.IGNORECASE)
    if not match:
        return default
    return str(match.group(1)).replace(",", ".")


def normalizza_riga_registro(row):
    row = dict(row or {})
    for field in REGISTRO_FIELDNAMES:
        row.setdefault(field, "")

    note = row.get("Note", "")
    operazione = str(row.get("Operazione", "") or "").upper()
    prezzo = safe_float(row.get("Prezzo_EUR", 0.0))

    if not has_value(row.get("Importo_EUR")):
        importo = _parse_numero_da_testo(r"(?:Importo|Ricavo netto)\s+([+-]?\d+(?:[\.,]\d+)?)\s*EUR", note)
        if importo:
            row["Importo_EUR"] = f"{safe_float(importo):.2f}"

    if not has_value(row.get("Profitto_EUR")):
        profitto = _parse_numero_da_testo(r"P/L\s*([+-]?\d+(?:[\.,]\d+)?)\s*EUR", note)
        if profitto:
            row["Profitto_EUR"] = f"{safe_float(profitto):.2f}"

    if not has_value(row.get("Percentuale")):
        percentuale = _parse_numero_da_testo(r"quota\s+([+-]?\d+(?:[\.,]\d+)?)\s*%", note)
        if percentuale:
            row["Percentuale"] = f"{safe_float(percentuale):.2f}"
        elif "COMPRA" in operazione or "BUY" in operazione:
            row["Percentuale"] = "100.00"

    if not has_value(row.get("Commissione_EUR")):
        commissione_eur = _parse_numero_da_testo(r"Commissione\s+([+-]?\d+(?:[\.,]\d+)?)\s*EUR", note)
        if commissione_eur:
            row["Commissione_EUR"] = f"{safe_float(commissione_eur):.2f}"
        else:
            commissione_pct = _parse_numero_da_testo(r"Commissione\s+([+-]?\d+(?:[\.,]\d+)?)\s*%", note)
            importo = safe_float(row.get("Importo_EUR", 0.0))
            if commissione_pct and importo > 0:
                row["Commissione_EUR"] = f"{importo * safe_float(commissione_pct) / 100:.2f}"

    if not has_value(row.get("Quantita")):
        importo = safe_float(row.get("Importo_EUR", 0.0))
        commissione = safe_float(row.get("Commissione_EUR", 0.0))
        if prezzo > 0 and importo > 0 and ("COMPRA" in operazione or "BUY" in operazione):
            row["Quantita"] = f"{max(0.0, importo - commissione) / prezzo:.12f}"

    return row


def inizializza_file_registro():
    try:
        if not FILE_LOG.exists():
            with open(FILE_LOG, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=REGISTRO_FIELDNAMES)
                writer.writeheader()
            return

        with open(FILE_LOG, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            if all(field in fieldnames for field in REGISTRO_FIELDNAMES):
                return
            rows = list(reader)

        with open(FILE_LOG, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=REGISTRO_FIELDNAMES)
            writer.writeheader()
            for row in rows:
                row = normalizza_riga_registro(row)
                writer.writerow({field: row.get(field, "") for field in REGISTRO_FIELDNAMES})
    except Exception as e:
        log_errore("Errore creazione registro trade", e)


def registra_operazione(
    simbolo,
    operazione,
    prezzo,
    rsi,
    saldo,
    note="",
    quantita=0.0,
    importo=0.0,
    commissione=0.0,
    profitto=0.0,
    percentuale=0.0,
):
    try:
        inizializza_file_registro()
        with open(FILE_LOG, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=REGISTRO_FIELDNAMES)
            writer.writerow({
                "Data_Ora": now_str(),
                "Crypto": simbolo,
                "Operazione": operazione,
                "Prezzo_EUR": f"{safe_float(prezzo):.8f}",
                "RSI": f"{safe_float(rsi):.2f}",
                "Saldo_EUR": f"{safe_float(saldo):.2f}",
                "Quantita": f"{safe_float(quantita):.12f}",
                "Importo_EUR": f"{safe_float(importo):.2f}",
                "Commissione_EUR": f"{safe_float(commissione):.2f}",
                "Profitto_EUR": f"{safe_float(profitto):.2f}",
                "Percentuale": f"{safe_float(percentuale):.2f}",
                "Note": note,
            })
    except Exception as e:
        log_errore("Errore scrittura registro trade", e)


def leggi_registro_operazioni():
    try:
        inizializza_file_registro()
        with open(FILE_LOG, "r", encoding="utf-8", newline="") as f:
            return [normalizza_riga_registro(row) for row in csv.DictReader(f)]
    except Exception as e:
        log_errore("Errore lettura registro trade", e)
        return []


# ============================================================
# GESTIONE PROCESSO ENGINE
# ============================================================

def pid_is_running(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def file_age_seconds(path: Path):
    try:
        return time.time() - path.stat().st_mtime
    except Exception:
        return None


def parse_status_timestamp(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def status_conferma_engine(pid: int, max_age_seconds=300) -> bool:
    status = load_json_file(FILE_STATUS, {})
    engine = status.get("engine", {}) if isinstance(status, dict) else {}
    if not safe_bool(engine.get("running"), False):
        return False
    if safe_int(engine.get("pid"), 0) != pid:
        return False

    last_update = parse_status_timestamp(engine.get("last_update"))
    if last_update is None:
        return False

    age = (datetime.now() - last_update).total_seconds()
    return age <= max_age_seconds


def get_engine_pid():
    try:
        if not FILE_PID.exists():
            return None
        pid = int(FILE_PID.read_text(encoding="utf-8").strip())
        if not pid_is_running(pid):
            try:
                FILE_PID.unlink()
            except Exception:
                pass
            return None

        pid_file_age = file_age_seconds(FILE_PID)
        avvio_recente = pid_file_age is not None and pid_file_age <= 300
        if avvio_recente or status_conferma_engine(pid):
            return pid

        try:
            FILE_PID.unlink()
        except Exception:
            pass
        return None
    except Exception:
        return None


def engine_is_running() -> bool:
    return get_engine_pid() is not None


def start_engine_process():
    """
    Avvia l'engine in background.
    Su macOS/PyInstaller può impiegare qualche secondo a scrivere engine.pid.
    """
    if engine_is_running():
        return True

    try:
        if getattr(sys, "frozen", False):
            args = [sys.executable, "--engine"]
        else:
            args = [sys.executable, str(Path(__file__).resolve()), "--engine"]

        env = os.environ.copy()
        env[ENGINE_ENV_FLAG] = "1"
        env["QUANTUMBOT_APP_DIR"] = str(APP_DIR)

        with open(FILE_ENGINE_LAUNCH, "a", encoding="utf-8") as lf:
            lf.write(f"[{now_str()}] Avvio engine\n")
            lf.write(f"APP_DIR: {APP_DIR}\n")
            lf.write(f"sys.executable: {sys.executable}\n")
            lf.write(f"args: {args}\n")
            lf.write(f"frozen: {getattr(sys, 'frozen', False)}\n\n")

        stdout = open(FILE_ENGINE_STDOUT, "a", encoding="utf-8")
        stderr = open(FILE_ENGINE_STDERR, "a", encoding="utf-8")

        popen_kwargs = {
            "cwd": str(APP_DIR),
            "stdout": stdout,
            "stderr": stderr,
            "stdin": subprocess.DEVNULL,
            "env": env
        }

        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        else:
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

        process = subprocess.Popen(args, **popen_kwargs)
        try:
            stdout.close()
            stderr.close()
        except Exception:
            pass

        for _ in range(60):
            time.sleep(0.25)
            if engine_is_running():
                log_evento(f"Engine avviato dalla dashboard. PID {get_engine_pid()}")
                return True
            if process.poll() is not None:
                log_errore(f"Engine terminato subito con codice {process.returncode}")
                return False

        if process.poll() is None:
            log_evento("Engine avviato ma PID non ancora rilevato: avvio considerato in corso.")
            return True

        return engine_is_running()

    except Exception as e:
        log_errore("Errore avvio engine", e)
        return False


def append_comando(azione, params=None):
    comando = {
        "id": str(uuid.uuid4()),
        "timestamp": now_str(),
        "azione": azione,
        "params": params or {}
    }
    try:
        with open(FILE_COMMANDI, "a", encoding="utf-8") as f:
            f.write(json.dumps(comando, ensure_ascii=False) + "\n")
        return comando["id"]
    except Exception as e:
        log_errore("Errore scrittura comando", e)
        return None


def leggi_comandi():
    if not FILE_COMMANDI.exists():
        return []

    comandi = []
    try:
        with open(FILE_COMMANDI, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    comandi.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        log_errore("Errore lettura comandi", e)

    return comandi


def carica_comandi_processati():
    state = load_json_file(FILE_COMMAND_STATE, {"processed_ids": []})
    ids = state.get("processed_ids", [])
    if not isinstance(ids, list):
        ids = []
    return set(ids)


def salva_comandi_processati(ids):
    ultimi = list(ids)[-1000:]
    save_json_atomic(FILE_COMMAND_STATE, {"processed_ids": ultimi})


# ============================================================
# DATI MERCATO
# ============================================================

def crea_exchange_binance():
    if ccxt is None:
        log_errore("Dipendenza mancante: ccxt. Installa con: python3 -m pip install ccxt")
        return None
    try:
        return ccxt.binance({"enableRateLimit": True, "timeout": 10000})
    except Exception as e:
        log_errore("Errore inizializzazione Binance/ccxt", e)
        return None


exchange = crea_exchange_binance()


def prepara_mercati(cfg):
    market_map = {}
    if exchange is None:
        # Non blocchiamo la dashboard se ccxt non è installato o Binance non è raggiungibile.
        # Il bot resta utilizzabile in simulazione con dati fallback locali.
        for base in cfg.get("crypto_base_list", DEFAULT_CONFIG["crypto_base_list"]):
            market_map[simbolo_visuale(base)] = {"reale": "SIMULATO", "conversione": "SIMULATO"}
        return market_map

    try:
        exchange.load_markets()
        for base in cfg["crypto_base_list"]:
            visual = simbolo_visuale(base)
            eur = f"{base}/EUR"
            usdt = f"{base}/USDT"
            if eur in exchange.markets:
                market_map[visual] = {"reale": eur, "conversione": "EUR"}
            elif usdt in exchange.markets:
                market_map[visual] = {"reale": usdt, "conversione": "USDT_TO_EUR"}
            else:
                market_map[visual] = {"reale": None, "conversione": None}
    except Exception as e:
        log_errore("Errore caricamento mercati Binance", e)
        for base in cfg["crypto_base_list"]:
            market_map[simbolo_visuale(base)] = {"reale": None, "conversione": None}

    return market_map


ULTIMO_CAMBIO_USDT_EUR = {"valore": 0.92, "timestamp": 0.0}


def ottieni_cambio_usdt_eur():
    if exchange is None:
        return ULTIMO_CAMBIO_USDT_EUR.get("valore", 0.92)

    adesso = time.time()
    if adesso - ULTIMO_CAMBIO_USDT_EUR.get("timestamp", 0.0) < 30:
        return ULTIMO_CAMBIO_USDT_EUR.get("valore", 0.92)

    try:
        if "EUR/USDT" in exchange.markets:
            ticker = exchange.fetch_ticker("EUR/USDT")
            prezzo = ticker.get("last")
            if prezzo and prezzo > 0:
                cambio = 1 / prezzo
                ULTIMO_CAMBIO_USDT_EUR.update({"valore": cambio, "timestamp": adesso})
                return cambio

        if "USDT/EUR" in exchange.markets:
            ticker = exchange.fetch_ticker("USDT/EUR")
            prezzo = ticker.get("last")
            if prezzo and prezzo > 0:
                ULTIMO_CAMBIO_USDT_EUR.update({"valore": prezzo, "timestamp": adesso})
                return prezzo
    except Exception as e:
        log_errore("Errore cambio USDT/EUR", e)

    return ULTIMO_CAMBIO_USDT_EUR.get("valore", 0.92)


def genera_ohlcv_fallback(simbolo_visual, timeframe="1m", limit=60):
    """Genera dati OHLC simulati se Binance/ccxt non è disponibile.

    Non sostituisce i dati reali: serve solo a evitare dashboard vuota o crash
    durante test, mancanza rete o dipendenze non installate.
    """
    if pd is None:
        raise RuntimeError("Dipendenza mancante: pandas. Installa con: python3 -m pip install pandas")

    base = str(simbolo_visual).split("/")[0].upper()
    basi_prezzo = {
        "BTC": 62000.0, "ETH": 3200.0, "SOL": 140.0, "BNB": 560.0, "XRP": 0.50,
        "ADA": 0.42, "DOGE": 0.12, "DOT": 6.0, "LINK": 14.0, "SHIB": 0.000022,
        "AVAX": 30.0, "MATIC": 0.65, "LTC": 75.0, "UNI": 9.0, "NEAR": 5.0,
        "ATOM": 8.0, "ICP": 10.0, "XLM": 0.11, "ETC": 25.0, "FIL": 5.5,
    }
    prezzo_base = basi_prezzo.get(base, 10.0)
    seed = sum(ord(c) for c in simbolo_visual) + int(time.time() // max(30, timeframe_seconds(timeframe)))
    rng = random.Random(seed)
    trend = rng.uniform(-0.025, 0.025)
    volatilita = max(prezzo_base * 0.006, 0.0000001)

    rows = []
    ultimo = prezzo_base * (1 + rng.uniform(-0.02, 0.02))
    adesso_ms = int(time.time() * 1000)
    step_ms = timeframe_seconds(timeframe) * 1000

    for i in range(limit):
        progress = (i / max(1, limit - 1)) - 0.5
        drift = prezzo_base * trend * progress
        apertura = max(0.00000001, ultimo)
        chiusura = max(0.00000001, prezzo_base + drift + rng.uniform(-volatilita, volatilita))
        massimo = max(apertura, chiusura) + abs(rng.uniform(0, volatilita * 0.8))
        minimo = max(0.00000001, min(apertura, chiusura) - abs(rng.uniform(0, volatilita * 0.8)))
        rows.append([adesso_ms - (limit - i) * step_ms, apertura, massimo, minimo, chiusura, 0.0])
        ultimo = chiusura

    return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])


def fetch_ohlcv_in_eur(simbolo_visual, market_map, timeframe="1m", limit=60):
    if pd is None:
        raise RuntimeError("Dipendenza mancante: pandas. Installa con: python3 -m pip install pandas")

    info = market_map.get(simbolo_visual)

    if exchange is None:
        return genera_ohlcv_fallback(simbolo_visual, timeframe=timeframe, limit=limit)

    if not info or not info.get("reale") or info.get("conversione") == "SIMULATO":
        return genera_ohlcv_fallback(simbolo_visual, timeframe=timeframe, limit=limit)

    try:
        candele = exchange.fetch_ohlcv(info["reale"], timeframe=timeframe, limit=limit)
        df = pd.DataFrame(candele, columns=["timestamp", "open", "high", "low", "close", "volume"])

        if info["conversione"] == "USDT_TO_EUR":
            cambio = ottieni_cambio_usdt_eur()
            for col in ["open", "high", "low", "close"]:
                df[col] = df[col] * cambio

        return df
    except Exception as e:
        log_errore(f"Errore fetch OHLC {simbolo_visual}: uso fallback simulato", e)
        return genera_ohlcv_fallback(simbolo_visual, timeframe=timeframe, limit=limit)


def calcola_rsi(df, periodo=14):
    """Calcola RSI in modo stabile anche nei trend estremi.

    La formula classica genera divisioni per zero quando non ci sono perdite
    o quando non ci sono guadagni nel periodo. In quei casi il valore corretto
    è rispettivamente 100 oppure 0, non 50. Questo è importante per l'Auto
    Trade: un RSI estremo deve poter attivare compra/vendi.
    """
    delta = df["close"].diff()
    guadagno = delta.where(delta > 0, 0).rolling(window=periodo).mean()
    perdita = (-delta.where(delta < 0, 0)).rolling(window=periodo).mean()

    rs = guadagno / perdita.replace(0, math.nan)
    rsi = 100 - (100 / (1 + rs))

    rsi = rsi.mask((perdita == 0) & (guadagno > 0), 100.0)
    rsi = rsi.mask((guadagno == 0) & (perdita > 0), 0.0)
    rsi = rsi.mask((guadagno == 0) & (perdita == 0), 50.0)
    return rsi.fillna(50.0)


def timeframe_seconds(tf_str):
    mapping = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}
    return mapping.get(tf_str, 60)


def prossimo_controllo_secondi(tf_str):
    intervallo = timeframe_seconds(tf_str)
    trascorso = time.time() % intervallo
    return max(2.0, intervallo - trascorso + 2.0)


# ============================================================
# CALCOLI PORTAFOGLIO
# ============================================================

def reset_posizione_cfg(cfg, simbolo):
    cfg["crypto_in_pancia"][simbolo] = 0.0
    cfg["prezzo_acquisto_effettivo"][simbolo] = 0.0
    cfg["importo_speso_effettivo"][simbolo] = 0.0
    cfg["posizioni_aperte"][simbolo] = False


def valore_posizioni_cfg(cfg, ultimi_prezzi):
    totale = 0.0
    for simbolo, aperta in cfg["posizioni_aperte"].items():
        if aperta:
            quantita = safe_float(cfg["crypto_in_pancia"].get(simbolo, 0.0))
            prezzo = safe_float(ultimi_prezzi.get(simbolo, cfg["prezzo_acquisto_effettivo"].get(simbolo, 0.0)))
            totale += quantita * prezzo
    return totale


def capitale_investito_cfg(cfg):
    totale = 0.0
    for simbolo, aperta in cfg["posizioni_aperte"].items():
        if aperta:
            totale += safe_float(cfg["importo_speso_effettivo"].get(simbolo, 0.0))
    return totale


def costruisci_posizioni_status(cfg, ultimi_prezzi):
    posizioni = []
    for simbolo in [simbolo_visuale(b) for b in cfg["crypto_base_list"]]:
        if not cfg["posizioni_aperte"].get(simbolo, False):
            continue

        entry = safe_float(cfg["prezzo_acquisto_effettivo"].get(simbolo, 0.0))
        quantita = safe_float(cfg["crypto_in_pancia"].get(simbolo, 0.0))
        capitale = safe_float(cfg["importo_speso_effettivo"].get(simbolo, 0.0))
        prezzo_now = safe_float(ultimi_prezzi.get(simbolo, entry))
        valore = quantita * prezzo_now
        pl_eur = valore - capitale
        pl_pct = ((prezzo_now - entry) / entry * 100) if entry > 0 else 0.0

        posizioni.append({
            "simbolo": simbolo,
            "entry": entry,
            "quantita": quantita,
            "capitale": capitale,
            "prezzo_corrente": prezzo_now,
            "valore": valore,
            "pl_eur": pl_eur,
            "pl_pct": pl_pct
        })

    return posizioni


# ============================================================
# ENGINE
# ============================================================

def scrivi_status_engine(cfg, watchlist, ohlc_by_symbol, ultimi_prezzi, running=True, messaggio=""):
    investito = capitale_investito_cfg(cfg)
    valore_posizioni = valore_posizioni_cfg(cfg, ultimi_prezzi)
    patrimonio = safe_float(cfg["saldo_eur"]) + valore_posizioni
    profitto_non_realizzato = valore_posizioni - investito

    status = {
        "engine": {
            "running": running,
            "pid": os.getpid(),
            "last_update": now_str(),
            "messaggio": messaggio,
            "version": APP_VERSION
        },
        "balances": {
            "saldo_eur": safe_float(cfg["saldo_eur"]),
            "investito": investito,
            "valore_posizioni": valore_posizioni,
            "patrimonio": patrimonio,
            "profitto_accumulato": safe_float(cfg["profitto_accumulato"]),
            "profitto_non_realizzato": profitto_non_realizzato,
            "totale_acquisti": int(cfg["totale_acquisti"]),
            "totale_vendite": int(cfg["totale_vendite"]),
            "posizioni_aperte": sum(1 for v in cfg["posizioni_aperte"].values() if v)
        },
        "settings": {
            "risk_percent": safe_float(cfg["percentuale_rischio_per_trade"]),
            "modalita_trading": normalizza_modalita_trading(cfg.get("modalita_trading", "Normale")),
            "take_profit": safe_float(cfg["take_profit_percentuale"]),
            "stop_loss": safe_float(cfg["stop_loss_percentuale"]),
            "auto_profit_loss_attivo": bool(cfg["auto_profit_loss_attivo"]),
            "auto_trading_attivo": bool(cfg.get("auto_trading_attivo", False)),
            "timeframe": cfg["timeframe"],
            "periodo_rsi": int(cfg["periodo_rsi"]),
            "soglia_acquisto": safe_float(cfg["soglia_acquisto"]),
            "soglia_vendita": safe_float(cfg["soglia_vendita"]),
            "commissione_percentuale": safe_float(cfg["commissione_percentuale"])
        },
        "watchlist": watchlist,
        "positions": costruisci_posizioni_status(cfg, ultimi_prezzi),
        "ohlc": ohlc_by_symbol,
        "storico_saldi": cfg["storico_saldi"][-300:]
    }

    save_json_atomic(FILE_STATUS, status)


def ottieni_prezzo_corrente_engine(simbolo, cfg, market_map, ultimi_prezzi):
    prezzo = safe_float(ultimi_prezzi.get(simbolo, 0.0))
    if prezzo > 0:
        return prezzo

    df = fetch_ohlcv_in_eur(simbolo, market_map, timeframe=cfg.get("timeframe", "1m"), limit=2)
    prezzo = safe_float(df["close"].iloc[-1])
    ultimi_prezzi[simbolo] = prezzo
    return prezzo


def esegui_acquisto_manuale(cfg, simbolo, importo_eur, prezzo_corrente, rsi=0.0, operazione="COMPRA_MANUALE"):
    importo_eur = safe_float(importo_eur)
    prezzo_corrente = safe_float(prezzo_corrente)

    if importo_eur < 10.0:
        raise ValueError("Importo minimo manuale: 10 EUR")
    if prezzo_corrente <= 0:
        raise ValueError("Prezzo corrente non valido")
    if safe_float(cfg["saldo_eur"]) < importo_eur:
        raise ValueError("Saldo insufficiente per acquisto manuale")

    commissione = safe_float(cfg["commissione_percentuale"]) / 100
    capitale_netto = importo_eur * (1 - commissione)
    commissione_eur = importo_eur - capitale_netto
    quantita_nuova = capitale_netto / prezzo_corrente
    posizione_gia_aperta = cfg["posizioni_aperte"].get(simbolo, False)

    if posizione_gia_aperta:
        capitale_vecchio = safe_float(cfg["importo_speso_effettivo"].get(simbolo, 0.0))
        quantita_vecchia = safe_float(cfg["crypto_in_pancia"].get(simbolo, 0.0))
        nuovo_capitale_totale = capitale_vecchio + importo_eur
        nuova_quantita_totale = quantita_vecchia + quantita_nuova
        cfg["crypto_in_pancia"][simbolo] = nuova_quantita_totale
        cfg["importo_speso_effettivo"][simbolo] = nuovo_capitale_totale
        cfg["prezzo_acquisto_effettivo"][simbolo] = (nuovo_capitale_totale * (1 - commissione)) / nuova_quantita_totale
    else:
        cfg["crypto_in_pancia"][simbolo] = quantita_nuova
        cfg["importo_speso_effettivo"][simbolo] = importo_eur
        cfg["prezzo_acquisto_effettivo"][simbolo] = prezzo_corrente
        cfg["posizioni_aperte"][simbolo] = True

    cfg["saldo_eur"] = safe_float(cfg["saldo_eur"]) - importo_eur
    cfg["totale_acquisti"] = int(cfg["totale_acquisti"]) + 1
    cfg["storico_saldi"].append(round(safe_float(cfg["saldo_eur"]), 2))

    registra_operazione(
        simbolo, operazione, prezzo_corrente, rsi, safe_float(cfg["saldo_eur"]),
        f"Importo {importo_eur:.2f} EUR | Quantità {quantita_nuova:.8f} | Commissione {commissione_eur:.2f} EUR",
        quantita=quantita_nuova,
        importo=importo_eur,
        commissione=commissione_eur,
        profitto=0.0,
        percentuale=100.0,
    )
    log_evento(f"{operazione} {simbolo}: {importo_eur:.2f} EUR a {prezzo_corrente:.8f}")


def esegui_vendita_manuale(cfg, simbolo, percentuale, prezzo_corrente, rsi=0.0, operazione="VENDI_MANUALE"):

    percentuale = safe_float(percentuale)
    prezzo_corrente = safe_float(prezzo_corrente)

    if percentuale <= 0 or percentuale > 100:
        raise ValueError("Percentuale vendita non valida")
    if prezzo_corrente <= 0:
        raise ValueError("Prezzo corrente non valido")
    if not cfg["posizioni_aperte"].get(simbolo, False):
        raise ValueError(f"Nessuna posizione aperta su {simbolo}")

    quota = percentuale / 100.0
    quantita_totale = safe_float(cfg["crypto_in_pancia"].get(simbolo, 0.0))
    capitale_totale = safe_float(cfg["importo_speso_effettivo"].get(simbolo, 0.0))

    quantita_venduta = quantita_totale * quota
    capitale_venduto = capitale_totale * quota

    commissione = safe_float(cfg["commissione_percentuale"]) / 100
    ricavo_lordo = quantita_venduta * prezzo_corrente
    commissione_eur = ricavo_lordo * commissione
    ricavo_netto = ricavo_lordo - commissione_eur
    profitto_netto = ricavo_netto - capitale_venduto

    cfg["saldo_eur"] = safe_float(cfg["saldo_eur"]) + ricavo_netto
    cfg["profitto_accumulato"] = safe_float(cfg["profitto_accumulato"]) + profitto_netto
    cfg["totale_vendite"] = int(cfg["totale_vendite"]) + 1
    cfg["storico_saldi"].append(round(safe_float(cfg["saldo_eur"]), 2))

    quantita_residua = quantita_totale - quantita_venduta
    capitale_residuo = capitale_totale - capitale_venduto

    if percentuale >= 99.999 or quantita_residua <= 0 or capitale_residuo <= 0:
        reset_posizione_cfg(cfg, simbolo)
    else:
        cfg["crypto_in_pancia"][simbolo] = quantita_residua
        cfg["importo_speso_effettivo"][simbolo] = capitale_residuo
        cfg["posizioni_aperte"][simbolo] = True

    registra_operazione(
        simbolo, operazione, prezzo_corrente, rsi, safe_float(cfg["saldo_eur"]),
        f"Venduta quota {percentuale:.2f}% | Quantità {quantita_venduta:.8f} | Ricavo netto {ricavo_netto:.2f} EUR | P/L {profitto_netto:+.2f} EUR",
        quantita=quantita_venduta,
        importo=ricavo_netto,
        commissione=commissione_eur,
        profitto=profitto_netto,
        percentuale=percentuale,
    )
    log_evento(f"{operazione} {simbolo}: {percentuale:.2f}% | ricavo {ricavo_netto:.2f} EUR | P/L {profitto_netto:+.2f} EUR")


def processa_comandi_engine(cfg, processed_ids, ultimi_prezzi):
    stop_requested = False
    changed = False
    comandi = leggi_comandi()
    market_map_cache = None

    for comando in comandi:
        cid = comando.get("id")
        if not cid or cid in processed_ids:
            continue

        azione = comando.get("azione")
        params = comando.get("params", {})

        try:
            if azione == "ADD_FUNDS":
                amount = safe_float(params.get("amount", 0.0))
                if amount > 0:
                    cfg["saldo_eur"] = safe_float(cfg["saldo_eur"]) + amount
                    cfg["storico_saldi"].append(round(safe_float(cfg["saldo_eur"]), 2))
                    log_evento(f"Aggiunti fondi: +{amount:.2f} EUR")
                    changed = True

            elif azione == "SET_RISK":
                value = safe_float(params.get("risk_percent", cfg["percentuale_rischio_per_trade"]))
                if 0.1 <= value <= 100:
                    cfg["percentuale_rischio_per_trade"] = value
                    cfg["modalita_trading"] = "Personalizzata"
                    log_evento(f"Rischio aggiornato al {value:.2f}%")
                    changed = True

            elif azione == "SET_TIMEFRAME":
                timeframe = str(params.get("timeframe", cfg["timeframe"])).strip()
                if timeframe in VALID_TIMEFRAMES:
                    cfg["timeframe"] = timeframe
                    cfg["modalita_trading"] = "Personalizzata"
                    log_evento(f"Timeframe aggiornato: {timeframe}")
                    changed = True

            elif azione == "SET_AUTO_PL":
                cfg["auto_profit_loss_attivo"] = bool(params.get("active", cfg["auto_profit_loss_attivo"]))
                tp = safe_float(params.get("take_profit", cfg["take_profit_percentuale"]))
                sl = safe_float(params.get("stop_loss", cfg["stop_loss_percentuale"]))
                if 0.1 <= tp <= 100:
                    cfg["take_profit_percentuale"] = tp
                if 0.1 <= sl <= 100:
                    cfg["stop_loss_percentuale"] = sl
                cfg["modalita_trading"] = "Personalizzata"
                log_evento(
                    f"Auto P/L aggiornato: {'ON' if cfg['auto_profit_loss_attivo'] else 'OFF'} "
                    f"TP {cfg['take_profit_percentuale']:.2f}% SL {cfg['stop_loss_percentuale']:.2f}%"
                )
                changed = True

            elif azione == "SET_TRADING_MODE":
                modalita = normalizza_modalita_trading(params.get("mode", cfg.get("modalita_trading", "Normale")))
                if modalita == "Personalizzata":
                    modalita = "Normale"
                modalita, preset = applica_modalita_a_config(cfg, modalita)
                log_evento(
                    f"Modalità trading impostata: {modalita} | "
                    f"Inv. {preset['risk_percent']:.1f}% | BUY RSI <= {preset['buy_rsi']:.1f} | "
                    f"SELL RSI >= {preset['sell_rsi']:.1f} | TP {preset['take_profit']:.1f}% | "
                    f"SL {preset['stop_loss']:.1f}% | TF {preset['timeframe']}"
                )
                changed = True

            elif azione == "SET_AUTO_TRADE":
                cfg["auto_trading_attivo"] = bool(params.get("active", cfg.get("auto_trading_attivo", False)))
                buy_rsi = safe_float(params.get("buy_rsi", cfg.get("soglia_acquisto", 35)))
                sell_rsi = safe_float(params.get("sell_rsi", cfg.get("soglia_vendita", 65)))
                if 1 <= buy_rsi <= 99:
                    cfg["soglia_acquisto"] = buy_rsi
                if 1 <= sell_rsi <= 99:
                    cfg["soglia_vendita"] = sell_rsi
                cfg["modalita_trading"] = "Personalizzata"
                log_evento(
                    f"Auto Trade aggiornato: {'ON' if cfg.get('auto_trading_attivo', False) else 'OFF'} "
                    f"BUY RSI <= {cfg['soglia_acquisto']:.1f} | SELL RSI >= {cfg['soglia_vendita']:.1f}"
                )
                changed = True

            elif azione == "BUY_MANUAL":
                simbolo = str(params.get("symbol", "")).upper()
                importo = safe_float(params.get("amount", 0.0))
                if simbolo not in cfg["posizioni_aperte"]:
                    raise ValueError(f"Simbolo non valido: {simbolo}")
                if market_map_cache is None:
                    market_map_cache = prepara_mercati(cfg)
                prezzo = ottieni_prezzo_corrente_engine(simbolo, cfg, market_map_cache, ultimi_prezzi)
                esegui_acquisto_manuale(cfg, simbolo, importo, prezzo)
                changed = True

            elif azione == "SELL_MANUAL":
                simbolo = str(params.get("symbol", "")).upper()
                percentuale = safe_float(params.get("percent", 100.0))
                if simbolo not in cfg["posizioni_aperte"]:
                    raise ValueError(f"Simbolo non valido: {simbolo}")
                if market_map_cache is None:
                    market_map_cache = prepara_mercati(cfg)
                prezzo = ottieni_prezzo_corrente_engine(simbolo, cfg, market_map_cache, ultimi_prezzi)
                esegui_vendita_manuale(cfg, simbolo, percentuale, prezzo)
                changed = True

            elif azione == "CLOSE_ALL":
                aperte = [s for s, a in cfg["posizioni_aperte"].items() if a]
                if market_map_cache is None:
                    market_map_cache = prepara_mercati(cfg)
                for simbolo in aperte:
                    try:
                        prezzo_corrente = ottieni_prezzo_corrente_engine(simbolo, cfg, market_map_cache, ultimi_prezzi)
                        esegui_vendita_manuale(cfg, simbolo, 100.0, prezzo_corrente)
                    except Exception as e:
                        log_errore(f"Errore chiusura posizione {simbolo}", e)
                changed = True

            elif azione == "RESET":
                crypto_list = cfg.get("crypto_base_list", DEFAULT_CONFIG["crypto_base_list"])
                cfg.clear()
                cfg.update(deep_copy_json(DEFAULT_CONFIG))
                cfg["crypto_base_list"] = crypto_list
                inizializza_dizionari_config(cfg)
                log_evento("Simulazione resettata.")
                changed = True

            elif azione == "STOP":
                log_evento("Richiesta stop engine ricevuta.")
                stop_requested = True
                changed = True

        except Exception as e:
            log_errore(f"Errore processando comando {azione}", e)

        processed_ids.add(cid)

    if changed:
        salva_config(cfg)

    salva_comandi_processati(processed_ids)
    return stop_requested


def ciclo_mercati_engine(cfg, market_map, ultimi_prezzi):
    watchlist = {}
    ohlc_by_symbol = {}

    for base in cfg["crypto_base_list"]:
        simbolo = simbolo_visuale(base)
        try:
            df = fetch_ohlcv_in_eur(simbolo, market_map, timeframe=cfg["timeframe"], limit=60)
            df["RSI"] = calcola_rsi(df, int(cfg["periodo_rsi"]))

            ultimo_rsi = safe_float(df["RSI"].iloc[-1])
            ultimo_prezzo = safe_float(df["close"].iloc[-1])
            primo_prezzo = safe_float(df["close"].iloc[0])
            variazione_pct = ((ultimo_prezzo - primo_prezzo) / primo_prezzo * 100) if primo_prezzo > 0 else 0.0

            if ultimo_prezzo <= 0:
                continue

            ultimi_prezzi[simbolo] = ultimo_prezzo
            info = market_map.get(simbolo, {})
            fonte = info.get("reale", "") or "N/D"

            watchlist[simbolo] = {
                "price": ultimo_prezzo,
                "rsi": ultimo_rsi,
                "source": fonte,
                "change_pct": variazione_pct,
                "has_position": bool(cfg["posizioni_aperte"].get(simbolo, False))
            }
            ohlc_by_symbol[simbolo] = df[["open", "high", "low", "close"]].tail(60).to_dict("records")

            # AUTO TRADE RSI: apre una posizione simulata se RSI è sotto soglia
            # e non c'è già una posizione aperta sulla stessa crypto.
            if cfg.get("auto_trading_attivo", False) and not cfg["posizioni_aperte"].get(simbolo, False):
                soglia_buy = safe_float(cfg.get("soglia_acquisto", 35))
                saldo = safe_float(cfg.get("saldo_eur", 0.0))
                percentuale = safe_float(cfg.get("percentuale_rischio_per_trade", 5.0))
                importo_auto = min(saldo, saldo * percentuale / 100.0)

                if ultimo_rsi <= soglia_buy and importo_auto >= 10.0:
                    esegui_acquisto_manuale(
                        cfg,
                        simbolo,
                        importo_auto,
                        ultimo_prezzo,
                        rsi=ultimo_rsi,
                        operazione="COMPRA_AUTO_RSI",
                    )
                    salva_config(cfg)
                    watchlist[simbolo]["has_position"] = True
                    log_evento(
                        f"COMPRA_AUTO_RSI {simbolo}: RSI {ultimo_rsi:.2f} <= {soglia_buy:.2f} | "
                        f"importo {importo_auto:.2f} EUR"
                    )

            if cfg["auto_profit_loss_attivo"] and cfg["posizioni_aperte"].get(simbolo, False):
                prezzo_ingresso = safe_float(cfg["prezzo_acquisto_effettivo"].get(simbolo, 0.0))
                if prezzo_ingresso > 0:
                    variazione = ((ultimo_prezzo - prezzo_ingresso) / prezzo_ingresso) * 100
                    motivo = None
                    if variazione >= safe_float(cfg["take_profit_percentuale"]):
                        motivo = "TAKE_PROFIT_AUTO"
                    elif variazione <= -safe_float(cfg["stop_loss_percentuale"]):
                        motivo = "STOP_LOSS_AUTO"

                    if motivo is not None:
                        capitale = safe_float(cfg["importo_speso_effettivo"].get(simbolo, 0.0))
                        quantita = safe_float(cfg["crypto_in_pancia"].get(simbolo, 0.0))
                        ricavo_lordo = quantita * ultimo_prezzo
                        commissione_eur = ricavo_lordo * safe_float(cfg["commissione_percentuale"]) / 100
                        ricavo = ricavo_lordo - commissione_eur
                        profitto = ricavo - capitale

                        cfg["saldo_eur"] = safe_float(cfg["saldo_eur"]) + ricavo
                        cfg["profitto_accumulato"] = safe_float(cfg["profitto_accumulato"]) + profitto
                        cfg["totale_vendite"] = int(cfg["totale_vendite"]) + 1
                        cfg["storico_saldi"].append(round(safe_float(cfg["saldo_eur"]), 2))

                        registra_operazione(
                            simbolo, motivo, ultimo_prezzo, ultimo_rsi, safe_float(cfg["saldo_eur"]),
                            f"Variazione {variazione:+.2f}% | Quantità {quantita:.8f} | Ricavo netto {ricavo:.2f} EUR | P/L {profitto:+.2f} EUR",
                            quantita=quantita,
                            importo=ricavo,
                            commissione=commissione_eur,
                            profitto=profitto,
                            percentuale=100.0,
                        )
                        reset_posizione_cfg(cfg, simbolo)
                        salva_config(cfg)
                        watchlist[simbolo]["has_position"] = False
                        log_evento(f"{motivo} {simbolo}: P/L {profitto:+.2f} EUR")

            # AUTO TRADE RSI: chiude la posizione se RSI è sopra soglia vendita.
            # Viene valutato dopo Take Profit/Stop Loss, così TP/SL hanno priorità.
            if cfg.get("auto_trading_attivo", False) and cfg["posizioni_aperte"].get(simbolo, False):
                soglia_sell = safe_float(cfg.get("soglia_vendita", 65))
                if ultimo_rsi >= soglia_sell:
                    esegui_vendita_manuale(
                        cfg,
                        simbolo,
                        100.0,
                        ultimo_prezzo,
                        rsi=ultimo_rsi,
                        operazione="VENDI_AUTO_RSI",
                    )
                    salva_config(cfg)
                    watchlist[simbolo]["has_position"] = False
                    log_evento(f"VENDI_AUTO_RSI {simbolo}: RSI {ultimo_rsi:.2f} >= {soglia_sell:.2f}")

        except Exception as e:
            log_errore(f"Errore ciclo mercato {simbolo}", e)

    return watchlist, ohlc_by_symbol


def run_engine():
    try:
        log_evento(f"Tentativo avvio engine. PID corrente {os.getpid()}")
    except Exception:
        pass

    existing = get_engine_pid()
    if existing and existing != os.getpid():
        print(f"Engine già attivo con PID {existing}.")
        log_evento(f"Engine non avviato: già attivo PID {existing}")
        return

    try:
        FILE_PID.write_text(str(os.getpid()), encoding="utf-8")
    except Exception as e:
        log_errore("Impossibile scrivere engine.pid", e)
        return

    inizializza_file_registro()
    cfg = carica_config()
    market_map = prepara_mercati(cfg)
    processed_ids = carica_comandi_processati()
    ultimi_prezzi = {}
    watchlist = {}
    ohlc_by_symbol = {}
    next_market_run = 0.0

    log_evento(f"Engine avviato. PID {os.getpid()}")

    try:
        while True:
            cfg = carica_config()
            stop = processa_comandi_engine(cfg, processed_ids, ultimi_prezzi)

            if stop:
                scrivi_status_engine(cfg, watchlist, ohlc_by_symbol, ultimi_prezzi, running=False, messaggio="Engine fermato da comando dashboard.")
                break

            adesso = time.time()
            if adesso >= next_market_run:
                market_map = prepara_mercati(cfg)
                watchlist, ohlc_by_symbol = ciclo_mercati_engine(cfg, market_map, ultimi_prezzi)
                cfg = carica_config()
                scrivi_status_engine(cfg, watchlist, ohlc_by_symbol, ultimi_prezzi, running=True, messaggio="Engine attivo.")
                next_market_run = adesso + prossimo_controllo_secondi(cfg["timeframe"])
            else:
                scrivi_status_engine(cfg, watchlist, ohlc_by_symbol, ultimi_prezzi, running=True, messaggio="Engine attivo.")
                time.sleep(1.0)

    except KeyboardInterrupt:
        log_evento("Engine interrotto da KeyboardInterrupt.")
    except Exception as e:
        log_errore("Errore critico engine", e)
    finally:
        try:
            if FILE_PID.exists() and FILE_PID.read_text(encoding="utf-8").strip() == str(os.getpid()):
                FILE_PID.unlink()
        except Exception:
            pass

        cfg = carica_config()
        scrivi_status_engine(cfg, watchlist, ohlc_by_symbol, ultimi_prezzi, running=False, messaggio="Engine non attivo.")
        log_evento("Engine terminato.")


# ============================================================
# DASHBOARD
# ============================================================

class QuantumDashboard:
    # Tema moderno: contrasto alto, colori morbidi e meno effetto "software tecnico".
    BG = "#08111f"
    PANEL = "#101c2f"
    PANEL_2 = "#0d1728"
    PANEL_3 = "#15233a"
    BORDER = "#263852"
    TEXT = "#e6edf7"
    MUTED = "#8fa4bd"
    BLUE = "#7dd3fc"
    GREEN = "#34d399"
    RED = "#fb7185"
    YELLOW = "#fde68a"
    VIOLET = "#a78bfa"

    BTN_DARK = ("#1d2b42", "#283a59", "#162238")
    BTN_BLUE = ("#2563eb", "#3b82f6", "#1d4ed8")
    BTN_GREEN = ("#059669", "#10b981", "#047857")
    BTN_RED = ("#e11d48", "#fb7185", "#be123c")

    def __init__(self):
        self.cfg = carica_config()
        self.status = load_json_file(FILE_STATUS, {})
        self.crypto_selezionata_grafico = "BTC/EUR"
        self.modalita_grafico_crypto = "linea"
        self.confronto_attivo = False
        self.crypto_confronto = []
        self._righe_storico_trade = {}
        self._refresh_after_id = None
        self._closed = False
        self._responsive_mode = None

        self.root = tk.Tk()
        self.root.title(f"Quantum Bot Studio {APP_VERSION} - Modern Dashboard")
        self.root.geometry("1180x820")
        self.root.minsize(760, 520)
        self.root.configure(bg=self.BG)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.var_crypto = tk.StringVar(value=self.crypto_selezionata_grafico)
        self.var_importo = tk.StringVar(value="100")
        risk_cfg = safe_float(self.cfg.get("percentuale_rischio_per_trade", 5.0))
        self.var_investimento_percentuale = tk.StringVar(value=f"{risk_cfg:.2f}%")
        auto_trade_txt = "Auto Trade ON" if self.cfg.get("auto_trading_attivo", False) else "Auto Trade OFF"
        self.var_auto_trade_status = tk.StringVar(value=auto_trade_txt)
        self.var_modalita_trading = tk.StringVar(value=self.cfg.get("modalita_trading", "Normale"))
        self.var_timeframe = tk.StringVar(value=self.cfg.get("timeframe", "1m"))
        self.var_modalita_grafico = tk.StringVar(value=self.modalita_grafico_crypto)

        self.setup_style()
        self.build_scroll_container()
        self.build_ui()
        self.root.after(300, lambda: self.apply_responsive_layout(self._dashboard_width()))

        self.scrivi_log(f"[SISTEMA] QuantumBot {APP_VERSION} avviato.")
        self.scrivi_log(f"[SISTEMA] Cartella dati: {APP_DIR}")
        self.scrivi_log("[SISTEMA] Chiudere la Dashboard non ferma l'Engine.")

        if not engine_is_running():
            ok = start_engine_process()
            if ok:
                self.scrivi_log("[ENGINE] Avvio richiesto. Lo stato può aggiornarsi dopo qualche secondo.")
            else:
                self.scrivi_log("[ERRORE] Engine non avviato. Controlla engine_stderr.log, engine_launch.log e errori_bot.log.")
        else:
            self.scrivi_log(f"[ENGINE] Già attivo. PID {get_engine_pid()}.")

        self.refresh_dashboard()

    def setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=self.BG, foreground=self.TEXT, fieldbackground=self.PANEL, font=("Helvetica", 10))
        style.configure("Treeview", background=self.PANEL_2, fieldbackground=self.PANEL_2, foreground="#f8fafc", rowheight=28, font=("Helvetica", 9), borderwidth=0, relief="flat")
        style.configure("Treeview.Heading", background=self.PANEL_3, foreground=self.BLUE, font=("Helvetica", 9, "bold"), borderwidth=0, relief="flat")
        style.map("Treeview", background=[("selected", "#2563eb")], foreground=[("selected", "#ffffff")])
        style.configure("TCombobox", fieldbackground=self.PANEL_2, background=self.PANEL_2, foreground=self.TEXT, arrowcolor=self.BLUE, borderwidth=0, padding=(10, 5))
        style.map("TCombobox", fieldbackground=[("readonly", self.PANEL_2)], selectbackground=[("readonly", self.PANEL_2)], selectforeground=[("readonly", self.TEXT)])
        style.configure("Vertical.TScrollbar", background=self.PANEL_3, troughcolor=self.PANEL_2, bordercolor=self.PANEL_2, arrowcolor=self.MUTED, relief="flat")
        style.configure("Horizontal.TScrollbar", background=self.PANEL_3, troughcolor=self.PANEL_2, bordercolor=self.PANEL_2, arrowcolor=self.MUTED, relief="flat")

    def build_scroll_container(self):
        """Crea un contenitore scrollabile per tutta la dashboard.

        Serve soprattutto su MacBook o finestre ridotte: la dashboard si riproporziona
        automaticamente e mantiene lo scroll solo quando lo spazio diventa davvero
        troppo piccolo per mostrare tutte le sezioni.
        """
        self.dashboard_min_width = 760

        self.scroll_shell = tk.Frame(self.root, bg=self.BG)
        self.scroll_shell.pack(fill=tk.BOTH, expand=True)

        self.dashboard_canvas = tk.Canvas(
            self.scroll_shell,
            bg=self.BG,
            highlightthickness=0,
            bd=0,
            xscrollincrement=24,
            yscrollincrement=24,
        )
        self.scrollbar_y = ttk.Scrollbar(self.scroll_shell, orient="vertical", command=self.dashboard_canvas.yview)
        self.scrollbar_x = ttk.Scrollbar(self.scroll_shell, orient="horizontal", command=self.dashboard_canvas.xview)
        self.dashboard_canvas.configure(yscrollcommand=self.scrollbar_y.set, xscrollcommand=self.scrollbar_x.set)

        self.dashboard_canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar_y.grid(row=0, column=1, sticky="ns")
        self.scrollbar_x.grid(row=1, column=0, sticky="ew")

        self.scroll_shell.grid_rowconfigure(0, weight=1)
        self.scroll_shell.grid_columnconfigure(0, weight=1)

        self.content = tk.Frame(self.dashboard_canvas, bg=self.BG)
        self.content_id = self.dashboard_canvas.create_window((0, 0), window=self.content, anchor="nw")

        self.content.bind("<Configure>", self._on_content_configure)
        self.dashboard_canvas.bind("<Configure>", self._on_canvas_configure)
        self.dashboard_canvas.bind_all("<MouseWheel>", self._on_dashboard_mousewheel)
        self.dashboard_canvas.bind_all("<Shift-MouseWheel>", self._on_dashboard_shift_mousewheel)
        self.dashboard_canvas.bind_all("<Button-4>", self._on_dashboard_mousewheel_linux)
        self.dashboard_canvas.bind_all("<Button-5>", self._on_dashboard_mousewheel_linux)

    def _on_content_configure(self, event=None):
        try:
            self.dashboard_canvas.configure(scrollregion=self.dashboard_canvas.bbox("all"))
        except Exception:
            pass

    def _on_canvas_configure(self, event):
        try:
            # Il contenuto segue la larghezza reale della finestra.
            # Sotto la larghezza minima resta disponibile lo scroll orizzontale,
            # ma nelle dimensioni normali/macOS non rimane più bloccato a 1180 px.
            width = max(self.dashboard_min_width, event.width)
            self.dashboard_canvas.itemconfigure(self.content_id, width=width)
            self.dashboard_canvas.configure(scrollregion=self.dashboard_canvas.bbox("all"))
            self.apply_responsive_layout(width)
        except Exception:
            pass

    def _mousewheel_units(self, event):
        delta = getattr(event, "delta", 0)
        if delta == 0:
            return 0
        # macOS può mandare delta piccoli; Windows usa spesso multipli di 120.
        if abs(delta) >= 120:
            return int(-delta / 120)
        return -1 if delta > 0 else 1

    def _on_dashboard_mousewheel(self, event):
        units = self._mousewheel_units(event)
        if units:
            self.dashboard_canvas.yview_scroll(units, "units")

    def _on_dashboard_shift_mousewheel(self, event):
        units = self._mousewheel_units(event)
        if units:
            self.dashboard_canvas.xview_scroll(units, "units")

    def _on_dashboard_mousewheel_linux(self, event):
        if getattr(event, "num", None) == 4:
            self.dashboard_canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            self.dashboard_canvas.yview_scroll(1, "units")

    def _dashboard_width(self):
        """Restituisce la larghezza utile della dashboard."""
        try:
            width = self.dashboard_canvas.winfo_width()
            if width <= 1:
                width = self.root.winfo_width()
            return max(self.dashboard_min_width, int(width))
        except Exception:
            return self.dashboard_min_width

    def apply_responsive_layout(self, width=None):
        """Adatta automaticamente layout e griglie alla larghezza della finestra.

        - Wide: card su una riga e colonne laterali affiancate.
        - Medium: card su due righe, colonne ancora affiancate.
        - Compact: card su più righe e contenuto in verticale, senza perdere sezioni.
        """
        try:
            if width is None:
                width = self._dashboard_width()

            if width >= 1120:
                mode = "wide"
            elif width >= 920:
                mode = "medium"
            else:
                mode = "compact"

            if mode == self._responsive_mode:
                return

            self._responsive_mode = mode
            self._layout_topbar(mode)
            self._layout_cards(mode)
            self._layout_main_columns(mode)
        except Exception as e:
            log_errore("Errore layout responsive", e)

    def _layout_topbar(self, mode):
        if not hasattr(self, "topbar"):
            return

        for child in (getattr(self, "title_box", None), getattr(self, "actions", None)):
            if child is not None:
                try:
                    child.grid_forget()
                except Exception:
                    pass

        if mode == "compact":
            self.topbar.grid_columnconfigure(0, weight=1)
            self.topbar.grid_columnconfigure(1, weight=0)
            self.title_box.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))
            self.actions.grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 14))
        else:
            self.topbar.grid_columnconfigure(0, weight=1)
            self.topbar.grid_columnconfigure(1, weight=0)
            self.title_box.grid(row=0, column=0, sticky="nsew", padx=16, pady=14)
            self.actions.grid(row=0, column=1, sticky="e", padx=14, pady=14)

        self._layout_topbar_buttons(mode)

    def _layout_topbar_buttons(self, mode):
        if not hasattr(self, "top_buttons_frame") or not hasattr(self, "top_buttons"):
            return

        for btn in self.top_buttons:
            try:
                btn.grid_forget()
            except Exception:
                pass

        columns = 2 if mode == "compact" else len(self.top_buttons)
        for index, btn in enumerate(self.top_buttons):
            row = index // columns
            col = index % columns
            btn.grid(row=row, column=col, padx=4, pady=3, sticky="ew")

        for col in range(max(columns, 1)):
            self.top_buttons_frame.grid_columnconfigure(col, weight=1 if mode == "compact" else 0)

    def _layout_cards(self, mode):
        if not hasattr(self, "cards_frame") or not hasattr(self, "card_widgets"):
            return

        if mode == "wide":
            columns = 6
        elif mode == "medium":
            columns = 3
        else:
            columns = 2

        for card in self.card_widgets:
            try:
                card.grid_forget()
            except Exception:
                pass

        for index, card in enumerate(self.card_widgets):
            row = index // columns
            col = index % columns
            card.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)

        for col in range(6):
            self.cards_frame.grid_columnconfigure(col, weight=1 if col < columns else 0)

    def _layout_main_columns(self, mode):
        if not hasattr(self, "main_frame"):
            return

        try:
            self.left_col.grid_forget()
            self.right_col.grid_forget()
        except Exception:
            pass

        if mode == "compact":
            self.main_frame.grid_columnconfigure(0, weight=1)
            self.main_frame.grid_columnconfigure(1, weight=0)
            self.left_col.grid(row=0, column=0, sticky="nsew", padx=0, pady=(0, 8))
            self.right_col.grid(row=1, column=0, sticky="nsew", padx=0, pady=(0, 0))
        else:
            self.main_frame.grid_columnconfigure(0, weight=42)
            self.main_frame.grid_columnconfigure(1, weight=58)
            self.left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=0)
            self.right_col.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=0)

        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=1 if mode == "compact" else 0)

    def make_button(self, parent, text, command, variant="dark", min_width=92):
        palette = {
            "dark": self.BTN_DARK,
            "blue": self.BTN_BLUE,
            "green": self.BTN_GREEN,
            "red": self.BTN_RED,
        }.get(variant, self.BTN_DARK)
        try:
            canvas_bg = parent.cget("bg")
        except Exception:
            canvas_bg = self.BG
        return RoundedButton(
            parent,
            text=text,
            command=command,
            bg_color=palette[0],
            hover_color=palette[1],
            active_color=palette[2],
            fg_color="#ffffff",
            canvas_bg=canvas_bg,
            radius=19,
            height=36,
            min_width=min_width,
        )

    def _widget_alive(self, attr_name):
        widget = getattr(self, attr_name, None)
        try:
            return widget is not None and bool(widget.winfo_exists())
        except Exception:
            return False

    def _popup_alive(self, attr_name):
        popup = getattr(self, attr_name, None)
        try:
            return popup is not None and bool(popup.winfo_exists())
        except Exception:
            return False

    def _focus_popup(self, attr_name):
        popup = getattr(self, attr_name, None)
        try:
            popup.lift()
            popup.focus_force()
        except Exception:
            pass

    def _center_popup(self, popup, width=900, height=640):
        try:
            self.root.update_idletasks()
            x = self.root.winfo_x() + max(40, (self.root.winfo_width() - width) // 2)
            y = self.root.winfo_y() + max(40, (self.root.winfo_height() - height) // 2)
            popup.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            popup.geometry(f"{width}x{height}")

    def build_ui(self):
        self.build_topbar()
        self.build_cards()
        self.build_main_area()
        self.build_log_area()

    def build_topbar(self):
        self.topbar = tk.Frame(self.content, bg=self.PANEL, bd=0, highlightthickness=1, highlightbackground=self.BORDER)
        self.topbar.pack(fill=tk.X, padx=14, pady=(14, 8))
        self.topbar.grid_columnconfigure(0, weight=1)

        self.title_box = tk.Frame(self.topbar, bg=self.PANEL)
        tk.Label(
            self.title_box,
            text="Quantum Bot Studio",
            bg=self.PANEL,
            fg="#f8fafc",
            font=("Helvetica", 22, "bold")
        ).pack(anchor="w")
        tk.Label(
            self.title_box,
            text=f"{APP_VERSION} · Simulazione crypto · Dashboard macOS",
            bg=self.PANEL,
            fg=self.MUTED,
            font=("Helvetica", 10)
        ).pack(anchor="w", pady=(2, 0))
        tk.Label(
            self.title_box,
            text="Dashboard compatta · Popup dati · Auto Trade RSI",
            bg=self.PANEL,
            fg=self.BLUE,
            font=("Helvetica", 9, "bold")
        ).pack(anchor="w", pady=(6, 0))

        self.actions = tk.Frame(self.topbar, bg=self.PANEL)

        self.lbl_engine = tk.Label(
            self.actions,
            text="ENGINE: controllo...",
            bg=self.PANEL_2,
            fg=self.YELLOW,
            font=("Helvetica", 10, "bold"),
            padx=12,
            pady=5
        )
        self.lbl_engine.pack(anchor="e", pady=(0, 8))

        self.top_buttons_frame = tk.Frame(self.actions, bg=self.PANEL)
        self.top_buttons_frame.pack(anchor="e", fill=tk.X)

        self.btn_engine = self.make_button(
            self.top_buttons_frame,
            "Avvia/Ferma Bot",
            self.toggle_engine,
            "dark",
            min_width=126
        )
        btn_data = self.make_button(self.top_buttons_frame, "Cartella dati", self.apri_cartella_dati, "dark", min_width=112)
        btn_registry = self.make_button(self.top_buttons_frame, "Registro", lambda: self.apri_file(FILE_LOG), "dark", min_width=86)
        btn_errors = self.make_button(self.top_buttons_frame, "Log errori", lambda: self.apri_file(FILE_ERRORI), "dark", min_width=92)

        self.top_buttons = [self.btn_engine, btn_data, btn_registry, btn_errors]
        self._layout_topbar(self._responsive_mode or "wide")

    def build_cards(self):
        self.card_vars = {}
        self.cards_frame = tk.Frame(self.content, bg=self.BG)
        self.cards_frame.pack(fill=tk.X, padx=14, pady=6)

        cards = [
            ("saldo", "Saldo disponibile", "0,00 EUR"),
            ("investito", "Capitale investito", "0,00 EUR"),
            ("valore", "Valore posizioni", "0,00 EUR"),
            ("patrimonio", "Patrimonio simulato", "0,00 EUR"),
            ("pl", "P/L totale", "+0,00 EUR"),
            ("ops", "Operazioni", "0 acquisti · 0 vendite"),
        ]

        self.card_widgets = []
        for key, label, value in cards:
            var = tk.StringVar(value=value)
            self.card_vars[key] = var
            card = RoundedMetricCard(
                self.cards_frame,
                label=label,
                value_var=var,
                panel_bg=self.PANEL_3,
                canvas_bg=self.BG,
                muted_fg=self.MUTED,
                value_fg="#f8fafc",
            )
            self.card_widgets.append(card)

        self._layout_cards(self._responsive_mode or "wide")

    def build_main_area(self):
        # Dashboard compatta: nella finestra principale restano comandi, riepilogo
        # e grafico. Le tabelle pesanti sono disponibili in popup dedicati.
        self.main_frame = tk.Frame(self.content, bg=self.BG)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=6)

        self.left_col = tk.Frame(self.main_frame, bg=self.BG)
        self.right_col = tk.Frame(self.main_frame, bg=self.BG)

        self.build_compact_summary(self.left_col)
        self.build_trading_panel(self.left_col)
        self.build_popup_launcher(self.left_col)
        self.build_chart_panel(self.right_col)

        self._layout_main_columns(self._responsive_mode or "wide")

    def build_compact_summary(self, parent):
        lf = self.make_labelframe(parent, "Riepilogo crypto selezionata")
        lf.pack(fill=tk.X, pady=(0, 8))

        self.var_selected_title = tk.StringVar(value="BTC/EUR")
        self.var_selected_price = tk.StringVar(value="Prezzo: -")
        self.var_selected_rsi = tk.StringVar(value="RSI: -")
        self.var_selected_var = tk.StringVar(value="Var.: -")
        self.var_selected_source = tk.StringVar(value="Fonte: -")
        self.var_selected_position = tk.StringVar(value="Posizione: no")

        title = tk.Label(
            lf,
            textvariable=self.var_selected_title,
            bg=self.PANEL,
            fg="#f8fafc",
            font=("Helvetica", 18, "bold")
        )
        title.pack(anchor="w", padx=14, pady=(8, 2))

        grid = tk.Frame(lf, bg=self.PANEL)
        grid.pack(fill=tk.X, padx=10, pady=(4, 10))

        items = [
            self.var_selected_price,
            self.var_selected_rsi,
            self.var_selected_var,
            self.var_selected_source,
            self.var_selected_position,
        ]
        for idx, var in enumerate(items):
            pill = tk.Label(
                grid,
                textvariable=var,
                bg=self.PANEL_2,
                fg=self.TEXT,
                font=("Helvetica", 10, "bold"),
                padx=10,
                pady=6
            )
            pill.grid(row=idx // 2, column=idx % 2, sticky="ew", padx=4, pady=4)

        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

    def build_popup_launcher(self, parent):
        lf = self.make_labelframe(parent, "Dati e strumenti")
        lf.pack(fill=tk.X, pady=(0, 8))

        tk.Label(
            lf,
            text="Apri i dettagli in finestre dedicate. La dashboard principale resta compatta.",
            bg=self.PANEL,
            fg=self.MUTED,
            font=("Helvetica", 9),
            wraplength=420,
            justify=tk.LEFT
        ).pack(anchor="w", padx=12, pady=(8, 6))

        grid = tk.Frame(lf, bg=self.PANEL)
        grid.pack(fill=tk.X, padx=8, pady=(0, 10))

        buttons = [
            ("Watchlist", self.apri_popup_watchlist, "blue", 112),
            ("Portafoglio", self.apri_popup_portafoglio, "green", 116),
            ("Storico", self.apri_popup_storico, "dark", 104),
            ("Grafici avanzati", self.apri_popup_grafici, "blue", 142),
            ("Strategia", self.apri_popup_strategia, "green", 108),
            ("Log sistema", self.apri_popup_log, "dark", 112),
        ]

        for idx, (label, command, variant, width) in enumerate(buttons):
            btn = self.make_button(grid, label, command, variant, min_width=width)
            btn.grid(row=idx // 2, column=idx % 2, sticky="ew", padx=4, pady=4)

        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

    def aggiorna_riepilogo_crypto_selezionata(self):
        if not hasattr(self, "var_selected_title"):
            return

        simbolo = self.crypto_corrente()
        watchlist = self.status.get("watchlist", {})
        data = watchlist.get(simbolo, {})

        price = safe_float(data.get("price", 0.0))
        rsi = safe_float(data.get("rsi", 0.0))
        change = safe_float(data.get("change_pct", 0.0))
        source = str(data.get("source", "N/D")).replace("/USDT", "/USDT*")
        positions = {p.get("simbolo"): p for p in self.status.get("positions", [])}
        pos = positions.get(simbolo)

        self.var_selected_title.set(simbolo)
        self.var_selected_price.set(f"Prezzo: {format_price(price)}")
        self.var_selected_rsi.set(f"RSI: {rsi:.1f}")
        self.var_selected_var.set(f"Var.: {format_pct(change)}")
        self.var_selected_source.set(f"Fonte: {source}")

        if pos:
            pl = safe_float(pos.get("pl_eur", 0.0))
            pl_pct = safe_float(pos.get("pl_pct", 0.0))
            self.var_selected_position.set(f"Posizione: sì · P/L {pl:+.2f} EUR ({pl_pct:+.2f}%)")
        else:
            self.var_selected_position.set("Posizione: no")

    def apri_popup_watchlist(self):
        if self._popup_alive("_popup_watchlist"):
            self._focus_popup("_popup_watchlist")
            return

        win = tk.Toplevel(self.root)
        self._popup_watchlist = win
        win.title("Watchlist completa")
        win.configure(bg=self.BG)
        self._center_popup(win, 760, 560)

        def on_close():
            self.tabella_listino = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)

        frame = tk.Frame(win, bg=self.BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        header = tk.Frame(frame, bg=self.BG)
        header.pack(fill=tk.X, pady=(0, 8))
        tk.Label(header, text="Watchlist completa", bg=self.BG, fg=self.TEXT, font=("Helvetica", 16, "bold")).pack(side=tk.LEFT)
        self.make_button(header, "Aggiorna", self.aggiorna_tabelle, "dark", min_width=90).pack(side=tk.RIGHT)

        cols = ("prezzo", "rsi", "var", "fonte", "pos")
        self.tabella_listino = ttk.Treeview(frame, columns=cols, show="tree headings", height=18)
        self.tabella_listino.heading("#0", text="Crypto")
        self.tabella_listino.heading("prezzo", text="Prezzo")
        self.tabella_listino.heading("rsi", text="RSI")
        self.tabella_listino.heading("var", text="Var.")
        self.tabella_listino.heading("fonte", text="Fonte")
        self.tabella_listino.heading("pos", text="Pos.")
        self.tabella_listino.column("#0", width=90, stretch=False)
        self.tabella_listino.column("prezzo", width=130, stretch=False, anchor="e")
        self.tabella_listino.column("rsi", width=70, stretch=False, anchor="e")
        self.tabella_listino.column("var", width=80, stretch=False, anchor="e")
        self.tabella_listino.column("fonte", width=120, stretch=True)
        self.tabella_listino.column("pos", width=60, stretch=False, anchor="center")
        self.tabella_listino.tag_configure("positivo", foreground=self.GREEN)
        self.tabella_listino.tag_configure("negativo", foreground=self.RED)
        self.tabella_listino.tag_configure("neutro", foreground="#f0f6fc")
        self.tabella_listino.bind("<ButtonRelease-1>", self.seleziona_crypto_da_lista)

        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=self.tabella_listino.yview)
        self.tabella_listino.configure(yscrollcommand=scroll_y.set)
        self.tabella_listino.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

        self.aggiorna_tabelle()

    def apri_popup_portafoglio(self):
        if self._popup_alive("_popup_portafoglio"):
            self._focus_popup("_popup_portafoglio")
            return

        win = tk.Toplevel(self.root)
        self._popup_portafoglio = win
        win.title("Portafoglio simulato")
        win.configure(bg=self.BG)
        self._center_popup(win, 860, 560)

        def on_close():
            self.tabella_pancia = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)

        frame = tk.Frame(win, bg=self.BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        header = tk.Frame(frame, bg=self.BG)
        header.pack(fill=tk.X, pady=(0, 8))
        tk.Label(header, text="Portafoglio simulato", bg=self.BG, fg=self.TEXT, font=("Helvetica", 16, "bold")).pack(side=tk.LEFT)
        self.make_button(header, "Vendi 25%", lambda: self.vendi_percentuale(25), "dark", min_width=90).pack(side=tk.RIGHT, padx=3)
        self.make_button(header, "Vendi 50%", lambda: self.vendi_percentuale(50), "dark", min_width=90).pack(side=tk.RIGHT, padx=3)
        self.make_button(header, "Vendi 100%", lambda: self.vendi_percentuale(100), "red", min_width=96).pack(side=tk.RIGHT, padx=3)

        cols = ("entry", "qty", "capitale", "valore", "pl", "plpct")
        self.tabella_pancia = ttk.Treeview(frame, columns=cols, show="tree headings", height=16)
        self.tabella_pancia.heading("#0", text="Crypto")
        self.tabella_pancia.heading("entry", text="Entry")
        self.tabella_pancia.heading("qty", text="Quantità")
        self.tabella_pancia.heading("capitale", text="Capitale")
        self.tabella_pancia.heading("valore", text="Valore")
        self.tabella_pancia.heading("pl", text="P/L")
        self.tabella_pancia.heading("plpct", text="%")
        self.tabella_pancia.column("#0", width=90, stretch=False)
        self.tabella_pancia.column("entry", width=110, anchor="e", stretch=False)
        self.tabella_pancia.column("qty", width=110, anchor="e", stretch=False)
        self.tabella_pancia.column("capitale", width=110, anchor="e", stretch=False)
        self.tabella_pancia.column("valore", width=110, anchor="e", stretch=False)
        self.tabella_pancia.column("pl", width=110, anchor="e", stretch=False)
        self.tabella_pancia.column("plpct", width=80, anchor="e", stretch=False)
        self.tabella_pancia.tag_configure("positivo", foreground=self.GREEN)
        self.tabella_pancia.tag_configure("negativo", foreground=self.RED)
        self.tabella_pancia.bind("<ButtonRelease-1>", self.seleziona_posizione_popup)

        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=self.tabella_pancia.yview)
        self.tabella_pancia.configure(yscrollcommand=scroll_y.set)
        self.tabella_pancia.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

        self.aggiorna_tabelle()

    def seleziona_posizione_popup(self, event=None):
        if not self._widget_alive("tabella_pancia"):
            return
        selected = self.tabella_pancia.selection()
        if selected:
            simbolo = selected[0]
            self.crypto_selezionata_grafico = simbolo
            self.var_crypto.set(simbolo)
            self.aggiorna_riepilogo_crypto_selezionata()
            self.aggiorna_grafici()

    def apri_popup_storico(self):
        if self._popup_alive("_popup_storico"):
            self._focus_popup("_popup_storico")
            return

        win = tk.Toplevel(self.root)
        self._popup_storico = win
        win.title("Storico operazioni")
        win.configure(bg=self.BG)
        self._center_popup(win, 1120, 720)

        def on_close():
            self.tabella_registro = None
            self.tabella_acquisti = None
            self.tabella_vendite = None
            self.tabella_storico_dashboard = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)

        frame = tk.Frame(win, bg=self.BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        self.build_registry_panel(frame)
        self.build_trade_history_panel(frame)
        self.aggiorna_registro()
        self.aggiorna_storico_trade()

    def apri_popup_grafici(self):
        if self._popup_alive("_popup_grafici"):
            self._focus_popup("_popup_grafici")
            return

        win = tk.Toplevel(self.root)
        self._popup_grafici = win
        win.title("Grafici avanzati")
        win.configure(bg=self.BG)
        self._center_popup(win, 420, 260)

        tk.Label(win, text="Grafici avanzati", bg=self.BG, fg=self.TEXT, font=("Helvetica", 16, "bold")).pack(anchor="w", padx=16, pady=(16, 6))
        tk.Label(
            win,
            text="Usa questi comandi per cambiare vista o aprire il confronto multi-crypto sul grafico principale.",
            bg=self.BG,
            fg=self.MUTED,
            wraplength=360,
            justify=tk.LEFT
        ).pack(anchor="w", padx=16, pady=(0, 12))

        grid = tk.Frame(win, bg=self.BG)
        grid.pack(fill=tk.X, padx=12, pady=8)
        self.make_button(grid, "Linea", lambda: self.set_modalita_grafico("linea"), "dark", min_width=90).grid(row=0, column=0, padx=4, pady=4, sticky="ew")
        self.make_button(grid, "Candele", lambda: self.set_modalita_grafico("candele"), "dark", min_width=90).grid(row=0, column=1, padx=4, pady=4, sticky="ew")
        self.make_button(grid, "Confronta crypto", self.seleziona_confronto_crypto, "blue", min_width=150).grid(row=1, column=0, padx=4, pady=4, sticky="ew")
        self.make_button(grid, "Singola crypto", self.disattiva_confronto_crypto, "dark", min_width=130).grid(row=1, column=1, padx=4, pady=4, sticky="ew")
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

    def apri_popup_strategia(self):
        if self._popup_alive("_popup_strategia"):
            self._focus_popup("_popup_strategia")
            return

        win = tk.Toplevel(self.root)
        self._popup_strategia = win
        win.title("Strategia e automazioni")
        win.configure(bg=self.BG)
        self._center_popup(win, 520, 420)

        tk.Label(win, text="Strategia e automazioni", bg=self.BG, fg=self.TEXT, font=("Helvetica", 16, "bold")).pack(anchor="w", padx=16, pady=(16, 6))
        tk.Label(
            win,
            text="Gestisci modalità trading, Auto Trade RSI, Auto P/L, percentuale investimento e timeframe.",
            bg=self.BG,
            fg=self.MUTED,
            wraplength=460,
            justify=tk.LEFT
        ).pack(anchor="w", padx=16, pady=(0, 12))

        grid = tk.Frame(win, bg=self.BG)
        grid.pack(fill=tk.X, padx=12, pady=8)

        actions = [
            ("Modalità trading", self.configura_modalita_trading, "green", 160),
            ("Auto Trade RSI", self.configura_auto_trade, "blue", 150),
            ("Auto Profit/Loss", self.configura_auto_profit_loss, "blue", 160),
            ("Percentuale investimento", self.configura_percentuale_investimento, "dark", 190),
            ("Usa % saldo", self.usa_percentuale_investimento, "dark", 130),
            ("Aggiungi fondi", self.aggiungi_fondi_popup, "green", 140),
        ]

        for idx, (label, command, variant, width) in enumerate(actions):
            self.make_button(grid, label, command, variant, min_width=width).grid(
                row=idx // 2,
                column=idx % 2,
                sticky="ew",
                padx=4,
                pady=5
            )

        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        info = tk.Label(
            win,
            textvariable=self.var_auto_trade_status,
            bg=self.PANEL_2,
            fg=self.YELLOW,
            font=("Helvetica", 10, "bold"),
            padx=12,
            pady=8
        )
        info.pack(fill=tk.X, padx=16, pady=(12, 4))

    def apri_popup_log(self):
        if self._popup_alive("_popup_log"):
            self._focus_popup("_popup_log")
            return

        win = tk.Toplevel(self.root)
        self._popup_log = win
        win.title("Log sistema")
        win.configure(bg=self.BG)
        self._center_popup(win, 940, 640)

        frame = tk.Frame(win, bg=self.BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        header = tk.Frame(frame, bg=self.BG)
        header.pack(fill=tk.X, pady=(0, 8))
        tk.Label(header, text="Log sistema", bg=self.BG, fg=self.TEXT, font=("Helvetica", 16, "bold")).pack(side=tk.LEFT)

        text_widget = tk.Text(
            frame,
            bg=self.PANEL_2,
            fg="#d1fae5",
            insertbackground="#d1fae5",
            font=("Courier New", 10),
            bd=0,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=self.BORDER
        )
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=scroll.set)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        def carica_log(path):
            text_widget.delete("1.0", tk.END)
            try:
                if Path(path).exists():
                    content = Path(path).read_text(encoding="utf-8", errors="replace")
                    text_widget.insert(tk.END, content[-30000:] if content else "File vuoto.")
                else:
                    text_widget.insert(tk.END, f"File non trovato: {path}")
            except Exception as e:
                text_widget.insert(tk.END, f"Errore lettura log: {e}")

        buttons = tk.Frame(header, bg=self.BG)
        buttons.pack(side=tk.RIGHT)
        self.make_button(buttons, "Eventi", lambda: carica_log(FILE_EVENTI), "dark", min_width=80).pack(side=tk.LEFT, padx=3)
        self.make_button(buttons, "Errori", lambda: carica_log(FILE_ERRORI), "red", min_width=80).pack(side=tk.LEFT, padx=3)
        self.make_button(buttons, "Engine err", lambda: carica_log(FILE_ENGINE_STDERR), "dark", min_width=100).pack(side=tk.LEFT, padx=3)
        self.make_button(buttons, "Engine out", lambda: carica_log(FILE_ENGINE_STDOUT), "dark", min_width=100).pack(side=tk.LEFT, padx=3)

        carica_log(FILE_EVENTI)


    def make_labelframe(self, parent, text):
        # Pannello moderno: bordo sottile, titolo a pillola e più respiro interno.
        # Mantiene la compatibilità con i widget Tkinter esistenti senza cambiare la logica.
        panel = tk.Frame(parent, bg=self.PANEL, bd=0, highlightthickness=1, highlightbackground=self.BORDER)
        header = tk.Frame(panel, bg=self.PANEL)
        header.pack(fill=tk.X, padx=12, pady=(10, 4))
        tk.Label(
            header,
            text=text.upper(),
            bg=self.PANEL_3,
            fg=self.BLUE,
            font=("Helvetica", 9, "bold"),
            padx=10,
            pady=4,
        ).pack(anchor="w")
        return panel

    def build_watchlist(self, parent):
        lf = self.make_labelframe(parent, "Watchlist")
        lf.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        cols = ("prezzo", "rsi", "var", "fonte", "pos")
        self.tabella_listino = ttk.Treeview(lf, columns=cols, show="tree headings", height=10)
        self.tabella_listino.heading("#0", text="Crypto")
        self.tabella_listino.heading("prezzo", text="Prezzo")
        self.tabella_listino.heading("rsi", text="RSI")
        self.tabella_listino.heading("var", text="Var.")
        self.tabella_listino.heading("fonte", text="Fonte")
        self.tabella_listino.heading("pos", text="Pos.")
        self.tabella_listino.column("#0", width=86, stretch=False)
        self.tabella_listino.column("prezzo", width=110, stretch=False, anchor="e")
        self.tabella_listino.column("rsi", width=54, stretch=False, anchor="e")
        self.tabella_listino.column("var", width=60, stretch=False, anchor="e")
        self.tabella_listino.column("fonte", width=80, stretch=True)
        self.tabella_listino.column("pos", width=45, stretch=False, anchor="center")
        self.tabella_listino.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0), pady=8)

        scroll = ttk.Scrollbar(lf, orient="vertical", command=self.tabella_listino.yview)
        self.tabella_listino.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 8), pady=8)

        self.tabella_listino.tag_configure("positivo", foreground=self.GREEN)
        self.tabella_listino.tag_configure("negativo", foreground=self.RED)
        self.tabella_listino.tag_configure("neutro", foreground="#f0f6fc")
        self.tabella_listino.bind("<ButtonRelease-1>", self.seleziona_crypto_da_lista)

    def build_trading_panel(self, parent):
        lf = self.make_labelframe(parent, "Trading simulato")
        lf.pack(fill=tk.X, pady=(0, 8))

        row1 = tk.Frame(lf, bg=self.PANEL)
        row1.pack(fill=tk.X, padx=8, pady=(8, 4))
        tk.Label(row1, text="Crypto", bg=self.PANEL, fg=self.MUTED).pack(side=tk.LEFT)
        self.combo_crypto = ttk.Combobox(row1, textvariable=self.var_crypto, values=[simbolo_visuale(b) for b in self.cfg["crypto_base_list"]], state="readonly", width=11)
        self.combo_crypto.pack(side=tk.LEFT, padx=(6, 12))
        self.combo_crypto.bind("<<ComboboxSelected>>", self.seleziona_crypto_combo)

        tk.Label(row1, text="Importo EUR", bg=self.PANEL, fg=self.MUTED).pack(side=tk.LEFT)
        entry = tk.Entry(row1, textvariable=self.var_importo, bg=self.PANEL_2, fg="#f8fafc", insertbackground="#f8fafc", width=10, relief=tk.FLAT, bd=0, highlightthickness=1, highlightbackground=self.BORDER, highlightcolor=self.BLUE)
        entry.pack(side=tk.LEFT, padx=(6, 12))
        self.btn_buy = self.make_button(row1, "Compra", self.compra_da_entry, "green", min_width=82)
        self.btn_buy.pack(side=tk.LEFT, padx=3)

        row2 = tk.Frame(lf, bg=self.PANEL)
        row2.pack(fill=tk.X, padx=8, pady=(4, 8))
        tk.Label(row2, text="Vendi", bg=self.PANEL, fg=self.MUTED).pack(side=tk.LEFT)
        for pct in [25, 50, 75, 100]:
            self.make_button(row2, f"{pct}%", lambda p=pct: self.vendi_percentuale(p), "dark", min_width=54).pack(side=tk.LEFT, padx=3)
        self.make_button(row2, "Chiudi tutte", self.chiudi_tutte_posizioni, "red", min_width=106).pack(side=tk.LEFT, padx=(10, 3))
        self.make_button(row2, "Reset", self.reset_simulazione, "dark", min_width=68).pack(side=tk.LEFT, padx=3)

        row3 = tk.Frame(lf, bg=self.PANEL)
        row3.pack(fill=tk.X, padx=8, pady=(0, 6))
        tk.Label(row3, text="Timeframe", bg=self.PANEL, fg=self.MUTED).pack(side=tk.LEFT)
        combo_tf = ttk.Combobox(row3, textvariable=self.var_timeframe, values=VALID_TIMEFRAMES, state="readonly", width=7)
        combo_tf.pack(side=tk.LEFT, padx=(6, 8))
        combo_tf.bind("<<ComboboxSelected>>", self.cambia_timeframe)
        self.make_button(row3, "Auto P/L", self.configura_auto_profit_loss, "blue", min_width=82).pack(side=tk.LEFT, padx=3)
        self.make_button(row3, "Auto Trade", self.configura_auto_trade, "blue", min_width=98).pack(side=tk.LEFT, padx=3)
        self.make_button(row3, "Modalità", self.configura_modalita_trading, "green", min_width=92).pack(side=tk.LEFT, padx=3)

        row4 = tk.Frame(lf, bg=self.PANEL)
        row4.pack(fill=tk.X, padx=8, pady=(0, 6))
        tk.Label(row4, text="Gestione saldo", bg=self.PANEL, fg=self.MUTED).pack(side=tk.LEFT)
        self.make_button(row4, "+ Aggiungi fondi", self.aggiungi_fondi_popup, "green", min_width=138).pack(side=tk.LEFT, padx=(8, 3))
        tk.Label(row4, text="Aumenta il saldo EUR della simulazione", bg=self.PANEL, fg=self.MUTED, font=("Helvetica", 9)).pack(side=tk.LEFT, padx=(8, 0))

        row5 = tk.Frame(lf, bg=self.PANEL)
        row5.pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Label(row5, text="Investimento", bg=self.PANEL, fg=self.MUTED).pack(side=tk.LEFT)
        tk.Label(row5, textvariable=self.var_investimento_percentuale, bg=self.PANEL, fg=self.GREEN, font=("Helvetica", 10, "bold")).pack(side=tk.LEFT, padx=(6, 8))
        self.make_button(row5, "Usa % saldo", self.usa_percentuale_investimento, "dark", min_width=106).pack(side=tk.LEFT, padx=3)
        self.make_button(row5, "Imposta %", self.configura_percentuale_investimento, "blue", min_width=96).pack(side=tk.LEFT, padx=3)

        row6 = tk.Frame(lf, bg=self.PANEL)
        row6.pack(fill=tk.X, padx=8, pady=(0, 6))
        tk.Label(row6, text="Modalità", bg=self.PANEL, fg=self.MUTED).pack(side=tk.LEFT)
        tk.Label(row6, textvariable=self.var_modalita_trading, bg=self.PANEL, fg=self.GREEN, font=("Helvetica", 9, "bold")).pack(side=tk.LEFT, padx=(6, 0))

        row7 = tk.Frame(lf, bg=self.PANEL)
        row7.pack(fill=tk.X, padx=8, pady=(0, 10))
        tk.Label(row7, textvariable=self.var_auto_trade_status, bg=self.PANEL, fg=self.YELLOW, font=("Helvetica", 9, "bold")).pack(side=tk.LEFT)

    def build_dashboard_trade_summary(self, parent):
        """Riquadro compatto con gli acquisti recenti vicino ai comandi."""
        lf = self.make_labelframe(parent, "Acquisti recenti")
        lf.pack(fill=tk.BOTH, expand=False, pady=(0, 8))

        header = tk.Frame(lf, bg=self.PANEL)
        header.pack(fill=tk.X, padx=8, pady=(6, 2))
        self.lbl_storico_dashboard = tk.Label(
            header,
            text="Dettaglio acquisti",
            bg=self.PANEL,
            fg=self.MUTED,
            font=("Helvetica", 9),
        )
        self.lbl_storico_dashboard.pack(side=tk.LEFT)
        self.make_button(header, "Aggiorna", self.aggiorna_storico_dashboard, "dark", min_width=82).pack(side=tk.RIGHT)

        cols = ("data", "crypto", "qty", "prezzo", "importo", "comm", "saldo")
        table_frame = tk.Frame(lf, bg=self.PANEL)
        table_frame.pack(fill=tk.X, padx=8, pady=(2, 8))

        self.tabella_storico_dashboard = ttk.Treeview(table_frame, columns=cols, show="headings", height=5)
        self.tabella_storico_dashboard.heading("data", text="Data")
        self.tabella_storico_dashboard.heading("crypto", text="Crypto")
        self.tabella_storico_dashboard.heading("qty", text="Quantità")
        self.tabella_storico_dashboard.heading("prezzo", text="Prezzo")
        self.tabella_storico_dashboard.heading("importo", text="Importo")
        self.tabella_storico_dashboard.heading("comm", text="Comm.")
        self.tabella_storico_dashboard.heading("saldo", text="Saldo")
        self.tabella_storico_dashboard.column("data", width=122, stretch=False)
        self.tabella_storico_dashboard.column("crypto", width=72, stretch=False)
        self.tabella_storico_dashboard.column("qty", width=88, anchor="e", stretch=False)
        self.tabella_storico_dashboard.column("prezzo", width=92, anchor="e", stretch=False)
        self.tabella_storico_dashboard.column("importo", width=92, anchor="e", stretch=False)
        self.tabella_storico_dashboard.column("comm", width=74, anchor="e", stretch=False)
        self.tabella_storico_dashboard.column("saldo", width=92, anchor="e", stretch=False)
        self.tabella_storico_dashboard.grid(row=0, column=0, sticky="nsew")

        scroll_y = ttk.Scrollbar(table_frame, orient="vertical", command=self.tabella_storico_dashboard.yview)
        scroll_x = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tabella_storico_dashboard.xview)
        self.tabella_storico_dashboard.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        table_frame.grid_columnconfigure(0, weight=1)

        self.tabella_storico_dashboard.tag_configure("acquisto", foreground=self.GREEN)
        self.tabella_storico_dashboard.bind("<Double-1>", self.mostra_dettaglio_operazione)

    def build_positions(self, parent):
        lf = self.make_labelframe(parent, "Posizioni aperte")
        lf.pack(fill=tk.BOTH, expand=True)

        cols = ("entry", "qty", "capitale", "valore", "pl", "plpct")
        self.tabella_pancia = ttk.Treeview(lf, columns=cols, show="tree headings", height=8)
        self.tabella_pancia.heading("#0", text="Crypto")
        self.tabella_pancia.heading("entry", text="Entry")
        self.tabella_pancia.heading("qty", text="Quantità")
        self.tabella_pancia.heading("capitale", text="Capitale")
        self.tabella_pancia.heading("valore", text="Valore")
        self.tabella_pancia.heading("pl", text="P/L")
        self.tabella_pancia.heading("plpct", text="%")
        self.tabella_pancia.column("#0", width=78, stretch=False)
        self.tabella_pancia.column("entry", width=82, anchor="e", stretch=False)
        self.tabella_pancia.column("qty", width=78, anchor="e", stretch=False)
        self.tabella_pancia.column("capitale", width=80, anchor="e", stretch=False)
        self.tabella_pancia.column("valore", width=80, anchor="e", stretch=False)
        self.tabella_pancia.column("pl", width=78, anchor="e", stretch=False)
        self.tabella_pancia.column("plpct", width=55, anchor="e", stretch=False)
        self.tabella_pancia.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.tabella_pancia.tag_configure("positivo", foreground=self.GREEN)
        self.tabella_pancia.tag_configure("negativo", foreground=self.RED)

    def build_chart_panel(self, parent):
        lf = self.make_labelframe(parent, "Grafici")
        lf.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        tools = tk.Frame(lf, bg=self.PANEL)
        tools.pack(fill=tk.X, padx=8, pady=6)
        self.lbl_chart_title = tk.Label(tools, text="Grafico", bg=self.PANEL, fg="#f8fafc", font=("Helvetica", 10, "bold"))
        self.lbl_chart_title.pack(side=tk.LEFT)
        self.make_button(tools, "Linea", lambda: self.set_modalita_grafico("linea"), "dark", min_width=66).pack(side=tk.RIGHT, padx=3)
        self.make_button(tools, "Candele", lambda: self.set_modalita_grafico("candele"), "dark", min_width=82).pack(side=tk.RIGHT, padx=3)
        self.btn_confronto_crypto = self.make_button(tools, "Confronta crypto", self.seleziona_confronto_crypto, "blue", min_width=132)
        self.btn_confronto_crypto.pack(side=tk.RIGHT, padx=3)
        self.make_button(tools, "Singola crypto", self.disattiva_confronto_crypto, "dark", min_width=112).pack(side=tk.RIGHT, padx=3)

        self.fig = Figure(figsize=(6.6, 5.4), dpi=100, facecolor=self.BG)
        self.ax_crypto = self.fig.add_subplot(211, facecolor=self.PANEL_2)
        self.ax_fondi = self.fig.add_subplot(212, facecolor=self.PANEL_2)
        self.fig.tight_layout(pad=2.0)

        self.canvas = FigureCanvasTkAgg(self.fig, master=lf)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

    def build_registry_panel(self, parent):
        lf = self.make_labelframe(parent, "Ultime operazioni")
        lf.pack(fill=tk.X)

        cols = ("data", "op", "prezzo", "saldo", "note")
        self.tabella_registro = ttk.Treeview(lf, columns=cols, show="tree headings", height=5)
        self.tabella_registro.heading("data", text="Data")
        self.tabella_registro.heading("op", text="Operazione")
        self.tabella_registro.heading("prezzo", text="Prezzo")
        self.tabella_registro.heading("saldo", text="Saldo")
        self.tabella_registro.heading("note", text="Note")
        self.tabella_registro.column("data", width=140, stretch=False)
        self.tabella_registro.column("op", width=120, stretch=False)
        self.tabella_registro.column("prezzo", width=110, anchor="e", stretch=False)
        self.tabella_registro.column("saldo", width=95, anchor="e", stretch=False)
        self.tabella_registro.column("note", width=260, stretch=True)
        self.tabella_registro.pack(fill=tk.X, padx=8, pady=8)


    def build_trade_history_panel(self, parent):
        """Mostra separatamente acquisti e vendite letti da registro_trade.csv.

        La sezione non sostituisce "Ultime operazioni": serve a capire subito
        cosa è stato comprato e cosa è stato venduto, senza dover aprire il CSV.
        """
        lf = self.make_labelframe(parent, "Acquisti e vendite")
        lf.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        header = tk.Frame(lf, bg=self.PANEL)
        header.pack(fill=tk.X, padx=8, pady=(6, 2))
        self.lbl_storico_trade = tk.Label(
            header,
            text="Storico operazioni simulato",
            bg=self.PANEL,
            fg=self.MUTED,
            font=("Helvetica", 9),
        )
        self.lbl_storico_trade.pack(side=tk.LEFT)
        self.make_button(header, "Aggiorna", self.aggiorna_storico_trade, "dark", min_width=82).pack(side=tk.RIGHT)

        self.notebook_trade = ttk.Notebook(lf)
        self.notebook_trade.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))

        tab_acquisti = tk.Frame(self.notebook_trade, bg=self.PANEL)
        tab_vendite = tk.Frame(self.notebook_trade, bg=self.PANEL)
        self.notebook_trade.add(tab_acquisti, text="Acquisti")
        self.notebook_trade.add(tab_vendite, text="Vendite")

        def crea_tabella(parent_tab):
            cols = ("data", "tipo", "qty", "prezzo", "importo", "comm", "pl", "saldo", "note")
            container = tk.Frame(parent_tab, bg=self.PANEL)
            container.pack(fill=tk.BOTH, expand=True)
            tabella = ttk.Treeview(container, columns=cols, show="tree headings", height=6)

            tabella.heading("#0", text="Crypto")
            tabella.heading("data", text="Data")
            tabella.heading("tipo", text="Tipo")
            tabella.heading("qty", text="Quantità")
            tabella.heading("prezzo", text="Prezzo")
            tabella.heading("importo", text="Importo/Ricavo")
            tabella.heading("comm", text="Comm.")
            tabella.heading("pl", text="P/L")
            tabella.heading("saldo", text="Saldo")
            tabella.heading("note", text="Dettaglio")
            tabella.column("#0", width=82, stretch=False)
            tabella.column("data", width=132, stretch=False)
            tabella.column("tipo", width=118, stretch=False)
            tabella.column("qty", width=92, anchor="e", stretch=False)
            tabella.column("prezzo", width=95, anchor="e", stretch=False)
            tabella.column("importo", width=106, anchor="e", stretch=False)
            tabella.column("comm", width=78, anchor="e", stretch=False)
            tabella.column("pl", width=86, anchor="e", stretch=False)
            tabella.column("saldo", width=92, anchor="e", stretch=False)
            tabella.column("note", width=230, stretch=True)
            tabella.grid(row=0, column=0, sticky="nsew")

            scroll_y = ttk.Scrollbar(container, orient="vertical", command=tabella.yview)
            scroll_x = ttk.Scrollbar(container, orient="horizontal", command=tabella.xview)
            tabella.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
            scroll_y.grid(row=0, column=1, sticky="ns")
            scroll_x.grid(row=1, column=0, sticky="ew")
            container.grid_rowconfigure(0, weight=1)
            container.grid_columnconfigure(0, weight=1)

            tabella.tag_configure("acquisto", foreground=self.GREEN)
            tabella.tag_configure("vendita_gain", foreground=self.GREEN)
            tabella.tag_configure("vendita_loss", foreground=self.RED)
            tabella.tag_configure("neutro", foreground=self.MUTED)
            tabella.bind("<Double-1>", self.mostra_dettaglio_operazione)
            return tabella

        self.tabella_acquisti = crea_tabella(tab_acquisti)
        self.tabella_vendite = crea_tabella(tab_vendite)

    @staticmethod
    def _operazione_is_acquisto(nome_operazione):
        nome = str(nome_operazione or "").upper()
        return "COMPRA" in nome or "BUY" in nome

    @staticmethod
    def _operazione_is_vendita(nome_operazione):
        nome = str(nome_operazione or "").upper()
        return "VENDI" in nome or "SELL" in nome or "TAKE_PROFIT" in nome or "STOP_LOSS" in nome

    def _dettaglio_breve_operazione(self, row):
        quantita = format_quantita(row.get("Quantita", ""))
        commissione = format_eur_detail(row.get("Commissione_EUR", ""))
        note = str(row.get("Note", "") or "")
        parti = []
        if quantita != "-":
            parti.append(f"Qtà {quantita}")
        if commissione != "-":
            parti.append(f"Comm. {commissione}")
        if note:
            parti.append(note)
        return " | ".join(parti) if parti else "-"

    def _tag_operazione(self, row):
        op = row.get("Operazione", "")
        if self._operazione_is_acquisto(op):
            return "acquisto"
        if self._operazione_is_vendita(op):
            return "vendita_gain" if safe_float(row.get("Profitto_EUR", 0.0)) >= 0 else "vendita_loss"
        return "neutro"

    def _valori_riga_trade(self, row, includi_crypto=False):
        values = [
            row.get("Data_Ora", ""),
            row.get("Crypto", ""),
            row.get("Operazione", ""),
            format_quantita(row.get("Quantita", "")),
            format_eur_detail(row.get("Importo_EUR", "")),
            format_signed_eur(row.get("Profitto_EUR", "")),
            self._dettaglio_breve_operazione(row)[:160],
        ]
        if includi_crypto:
            return values
        return (
            values[0],
            values[2],
            values[3],
            format_price(safe_float(row.get("Prezzo_EUR", 0.0))),
            values[4],
            format_eur_detail(row.get("Commissione_EUR", "")),
            values[5],
            format_eur_detail(row.get("Saldo_EUR", "")),
            values[6],
        )

    def mostra_dettaglio_operazione(self, event=None):
        widget = event.widget if event is not None else None
        if widget is None or not hasattr(widget, "selection"):
            return
        selected = widget.selection()
        if not selected:
            return

        row = self._righe_storico_trade.get(selected[0])
        if not row:
            return

        dettaglio = [
            f"Data: {row.get('Data_Ora', '-')}",
            f"Crypto: {row.get('Crypto', '-')}",
            f"Operazione: {row.get('Operazione', '-')}",
            f"Prezzo: {format_price(safe_float(row.get('Prezzo_EUR', 0.0)))}",
            f"RSI: {safe_float(row.get('RSI', 0.0)):.2f}",
            f"Quantità: {format_quantita(row.get('Quantita', ''))}",
            f"Importo/Ricavo: {format_eur_detail(row.get('Importo_EUR', ''))}",
            f"Commissione: {format_eur_detail(row.get('Commissione_EUR', ''))}",
            f"P/L: {format_signed_eur(row.get('Profitto_EUR', ''))}",
            f"Quota: {safe_float(row.get('Percentuale', 0.0)):.2f}%",
            f"Saldo dopo operazione: {format_eur_detail(row.get('Saldo_EUR', ''))}",
            "",
            str(row.get("Note", "") or "Nessuna nota"),
        ]
        messagebox.showinfo("Dettaglio operazione", "\n".join(dettaglio), parent=self.root)

    def build_log_area(self):
        self.txt_log = tk.Text(self.content, height=5, bg=self.PANEL_2, fg="#86efac", insertbackground="#86efac", font=("Courier New", 10), bd=0, relief=tk.FLAT, highlightthickness=1, highlightbackground=self.BORDER)
        self.txt_log.pack(fill=tk.X, padx=14, pady=(2, 12))

    def scrivi_log(self, testo):
        try:
            self.txt_log.insert(tk.END, testo + "\n")
            self.txt_log.see(tk.END)
        except Exception:
            print(testo)

    def on_close(self):
        self._closed = True
        if self._refresh_after_id is not None:
            try:
                self.root.after_cancel(self._refresh_after_id)
            except Exception:
                pass
        messagebox.showinfo(
            "Dashboard chiusa",
            "La Dashboard verrà chiusa.\n\n"
            "Il bot continuerà a lavorare in background.\n"
            "Per fermarlo davvero usa il pulsante 'Avvia/Ferma Bot' prima di chiudere."
        )
        self.root.destroy()

    def apri_cartella_dati(self):
        self.apri_file(APP_DIR)

    def apri_file(self, path: Path):
        try:
            if not Path(path).exists():
                if Path(path).suffix:
                    Path(path).touch()
                else:
                    Path(path).mkdir(parents=True, exist_ok=True)
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            elif os.name == "nt":
                os.startfile(str(path))
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            log_errore(f"Errore apertura file/cartella {path}", e)
            messagebox.showerror("Errore", f"Non riesco ad aprire:\n{path}")

    def toggle_engine(self):
        if engine_is_running():
            conferma = messagebox.askyesno(
                "Ferma Bot",
                "Vuoi fermare davvero il motore del bot?\n\n"
                "Dopo lo stop non controllerà più prezzi, RSI, Take Profit o Stop Loss."
            )
            if conferma:
                append_comando("STOP")
                self.scrivi_log("[ENGINE] Richiesto stop engine.")
        else:
            ok = start_engine_process()
            if ok:
                self.scrivi_log("[ENGINE] Avvio richiesto. Attendi qualche secondo per l'aggiornamento dello stato.")
                self.root.after(3000, self.refresh_dashboard)
            else:
                messagebox.showerror(
                    "Errore",
                    "Engine non avviato.\n\nControlla nella cartella dell'app:\n- engine_stderr.log\n- engine_launch.log\n- errori_bot.log"
                )

    def cambia_timeframe(self, event=None):
        tf = self.var_timeframe.get()
        self.cfg = carica_config()
        self.cfg["timeframe"] = tf
        self.cfg["modalita_trading"] = "Personalizzata"
        salva_config(self.cfg)
        self.var_modalita_trading.set("Personalizzata")
        append_comando("SET_TIMEFRAME", {"timeframe": tf})
        self.scrivi_log(f"[COMANDO] Timeframe richiesto: {tf}")

    def aggiungi_fondi_popup(self):
        valore = simpledialog.askfloat("Aggiungi fondi", "Inserisci l'importo da aggiungere al saldo EUR:", minvalue=0.01, parent=self.root)
        if valore is None:
            return

        # Aggiorniamo subito config.json invece di dipendere dal comando engine.
        # Così il saldo aumenta anche se l'engine è momentaneamente fermo.
        self.cfg = carica_config()
        self.cfg["saldo_eur"] = safe_float(self.cfg.get("saldo_eur", 0.0)) + float(valore)
        self.cfg.setdefault("storico_saldi", [])
        self.cfg["storico_saldi"].append(round(safe_float(self.cfg["saldo_eur"]), 2))
        salva_config(self.cfg)

        registra_operazione(
            "SIMULAZIONE",
            "AGGIUNGI_FONDI",
            0.0,
            0.0,
            safe_float(self.cfg["saldo_eur"]),
            f"Aggiunti {float(valore):.2f} EUR al saldo simulato"
        )

        self.scrivi_log(f"[DASHBOARD] Fondi aggiunti subito: +{valore:.2f} EUR")
        self.refresh_dashboard()

    def saldo_disponibile_corrente(self):
        balances = self.status.get("balances", {})
        return safe_float(balances.get("saldo_eur", self.cfg.get("saldo_eur", 0.0)))

    def configura_percentuale_investimento(self):
        self.cfg = carica_config()
        attuale = safe_float(self.cfg.get("percentuale_rischio_per_trade", 5.0))
        nuovo = simpledialog.askfloat(
            "Percentuale investimento",
            "Percentuale del saldo disponibile da usare per ogni acquisto.\n\n"
            "Esempio: 10 = usa il 10% del saldo disponibile.\n"
            "Con Auto Trade ON viene usata anche dagli acquisti automatici RSI.",
            initialvalue=attuale,
            minvalue=0.1,
            maxvalue=100.0,
            parent=self.root,
        )
        if nuovo is None:
            return

        nuovo = float(nuovo)
        self.cfg["percentuale_rischio_per_trade"] = nuovo
        self.cfg["modalita_trading"] = "Personalizzata"
        salva_config(self.cfg)
        append_comando("SET_RISK", {"risk_percent": nuovo})
        self.var_investimento_percentuale.set(f"{nuovo:.2f}%")
        self.var_modalita_trading.set("Personalizzata")
        self.scrivi_log(f"[COMANDO] Percentuale investimento aggiornata: {nuovo:.2f}%")

    def usa_percentuale_investimento(self):
        self.cfg = carica_config()
        percentuale = safe_float(self.cfg.get("percentuale_rischio_per_trade", 5.0))
        saldo = self.saldo_disponibile_corrente()

        if saldo <= 0:
            messagebox.showerror("Saldo non disponibile", "Non c'è saldo EUR disponibile per calcolare l'importo.")
            return

        importo = saldo * percentuale / 100.0
        self.var_importo.set(f"{importo:.2f}")
        self.scrivi_log(f"[DASHBOARD] Importo impostato al {percentuale:.2f}% del saldo: {importo:.2f} EUR")

        if importo < 10:
            messagebox.showinfo(
                "Importo sotto il minimo",
                f"Il {percentuale:.2f}% del saldo corrisponde a {importo:.2f} EUR.\n\n"
                "L'acquisto simulato richiede almeno 10 EUR."
            )

    def crypto_corrente(self):
        simbolo = self.var_crypto.get() or self.crypto_selezionata_grafico
        simbolo = simbolo.upper()
        if "/" not in simbolo:
            simbolo = simbolo_visuale(simbolo)
        return simbolo

    def compra_da_entry(self):
        simbolo = self.crypto_corrente()
        try:
            importo = safe_float(str(self.var_importo.get()).replace(",", "."))
        except Exception:
            importo = 0.0

        if importo < 10:
            messagebox.showerror("Importo non valido", "Inserisci un importo di almeno 10 EUR.")
            return

        saldo = safe_float(self.status.get("balances", {}).get("saldo_eur", self.cfg.get("saldo_eur", 0.0)))
        if importo > saldo:
            messagebox.showerror("Saldo insufficiente", f"Saldo disponibile: {format_eur(saldo)}")
            return

        conferma = messagebox.askyesno("Conferma acquisto", f"Vuoi acquistare {simbolo} per {importo:.2f} EUR?\n\nOperazione simulata.")
        if not conferma:
            return

        append_comando("BUY_MANUAL", {"symbol": simbolo, "amount": float(importo)})
        self.scrivi_log(f"[COMANDO] Compra manuale {simbolo}: {importo:.2f} EUR")

    def vendi_percentuale(self, percentuale):
        simbolo = self.crypto_corrente()
        posizioni = {p.get("simbolo"): p for p in self.status.get("positions", [])}
        if simbolo not in posizioni:
            messagebox.showerror("Nessuna posizione", f"Non hai una posizione aperta su {simbolo}.")
            return

        conferma = messagebox.askyesno("Conferma vendita", f"Vuoi vendere il {percentuale}% della posizione {simbolo}?\n\nOperazione simulata.")
        if not conferma:
            return

        append_comando("SELL_MANUAL", {"symbol": simbolo, "percent": float(percentuale)})
        self.scrivi_log(f"[COMANDO] Vendi manuale {simbolo}: {percentuale}% della posizione")

    def chiudi_tutte_posizioni(self):
        conferma = messagebox.askyesno("Chiudi posizioni", "Vuoi chiudere tutte le posizioni simulate al prezzo corrente?")
        if conferma:
            append_comando("CLOSE_ALL")
            self.scrivi_log("[COMANDO] Chiusura di tutte le posizioni richiesta.")

    def reset_simulazione(self):
        conferma = messagebox.askyesno(
            "Reset simulazione",
            "Vuoi davvero azzerare la simulazione e ripartire da 5000 EUR?\n\n"
            "Questa azione chiude/azzera tutte le posizioni simulate."
        )
        if conferma:
            append_comando("RESET")
            self.scrivi_log("[COMANDO] Reset simulazione richiesto.")

    def configura_modalita_trading(self):
        self.cfg = carica_config()
        finestra = tk.Toplevel(self.root)
        finestra.title("Modalità trading")
        finestra.configure(bg=self.BG)
        finestra.transient(self.root)
        finestra.grab_set()
        finestra.resizable(False, False)

        tk.Label(
            finestra,
            text="Scegli la modalità trading",
            bg=self.BG,
            fg="#f8fafc",
            font=("Helvetica", 15, "bold"),
        ).pack(anchor="w", padx=16, pady=(14, 4))
        tk.Label(
            finestra,
            text="La modalità modifica percentuale investimento, RSI, Take Profit, Stop Loss e timeframe.\n"
                 "Non attiva da sola Auto Trade: quello resta sotto il tuo controllo.",
            bg=self.BG,
            fg=self.MUTED,
            justify=tk.LEFT,
            font=("Helvetica", 10),
        ).pack(anchor="w", padx=16, pady=(0, 10))

        current = self.cfg.get("modalita_trading", "Normale")

        for nome, preset in TRADING_MODE_PRESETS.items():
            row = tk.Frame(finestra, bg=self.PANEL)
            row.pack(fill=tk.X, padx=16, pady=5)

            titolo = f"{nome}"
            if normalizza_modalita_trading(current) == nome:
                titolo += "  ✓"
            tk.Label(row, text=titolo, bg=self.PANEL, fg=self.GREEN if nome in {"Aggressiva", "Ultra aggressiva"} else "#f8fafc", font=("Helvetica", 11, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
            descrizione = (
                f"{preset['descrizione']}\n"
                f"Investimento {preset['risk_percent']:.0f}% · Buy RSI≤{preset['buy_rsi']:.0f} · "
                f"Sell RSI≥{preset['sell_rsi']:.0f} · TP {preset['take_profit']:.1f}% · "
                f"SL {preset['stop_loss']:.1f}% · Timeframe {preset['timeframe']}"
            )
            tk.Label(row, text=descrizione, bg=self.PANEL, fg=self.MUTED, justify=tk.LEFT, font=("Helvetica", 9)).pack(anchor="w", padx=12, pady=(0, 8))
            self.make_button(row, f"Usa {nome}", lambda m=nome, w=finestra: self.applica_modalita_trading(m, w), "blue" if nome != "Ultra aggressiva" else "red", min_width=132).pack(anchor="e", padx=12, pady=(0, 10))

        self.make_button(finestra, "Annulla", finestra.destroy, "dark", min_width=100).pack(anchor="e", padx=16, pady=(4, 14))

    def applica_modalita_trading(self, modalita, finestra=None):
        self.cfg = carica_config()
        modalita, preset = applica_modalita_a_config(self.cfg, modalita)
        salva_config(self.cfg)
        append_comando("SET_TRADING_MODE", {"mode": modalita})

        self.var_modalita_trading.set(descrizione_modalita_trading(modalita))
        self.var_investimento_percentuale.set(f"{preset['risk_percent']:.2f}%")
        self.var_timeframe.set(preset["timeframe"])
        stato = "ON" if self.cfg.get("auto_trading_attivo", False) else "OFF"
        self.var_auto_trade_status.set(
            f"Auto Trade {stato} · Buy RSI≤{preset['buy_rsi']:.1f} · Sell RSI≥{preset['sell_rsi']:.1f}"
        )
        self.scrivi_log(
            f"[COMANDO] Modalità {modalita}: inv. {preset['risk_percent']:.1f}% | "
            f"Buy RSI <= {preset['buy_rsi']:.1f} | Sell RSI >= {preset['sell_rsi']:.1f} | "
            f"TP {preset['take_profit']:.1f}% | SL {preset['stop_loss']:.1f}% | TF {preset['timeframe']}"
        )
        if finestra is not None:
            try:
                finestra.destroy()
            except Exception:
                pass
        messagebox.showinfo(
            "Modalità applicata",
            f"Modalità {modalita} applicata.\n\n"
            f"Investimento: {preset['risk_percent']:.1f}%\n"
            f"Buy RSI: {preset['buy_rsi']:.1f}\n"
            f"Sell RSI: {preset['sell_rsi']:.1f}\n"
            f"Take Profit: {preset['take_profit']:.1f}%\n"
            f"Stop Loss: {preset['stop_loss']:.1f}%\n"
            f"Timeframe: {preset['timeframe']}\n\n"
            f"Auto Trade resta {'attivo' if self.cfg.get('auto_trading_attivo', False) else 'spento'}."
        )

    def configura_auto_trade(self):
        self.cfg = carica_config()
        scelta = messagebox.askyesnocancel(
            "Auto Trade RSI",
            "Vuoi attivare l'acquisto/vendita automatica simulata basata su RSI?\n\n"
            "Sì = attiva\n"
            "No = disattiva\n"
            "Annulla = lascia invariato\n\n"
            "Regola: compra se RSI è sotto la soglia di acquisto e non hai già posizione; "
            "vende se RSI supera la soglia di vendita."
        )
        if scelta is None:
            return

        active = bool(scelta)
        buy_rsi = safe_float(self.cfg.get("soglia_acquisto", 35))
        sell_rsi = safe_float(self.cfg.get("soglia_vendita", 65))

        if active:
            nuovo_buy = simpledialog.askfloat(
                "Soglia acquisto RSI",
                "Compra automaticamente se RSI è minore o uguale a:",
                initialvalue=buy_rsi,
                minvalue=1.0,
                maxvalue=99.0,
                parent=self.root,
            )
            if nuovo_buy is None:
                return
            nuovo_sell = simpledialog.askfloat(
                "Soglia vendita RSI",
                "Vende automaticamente se RSI è maggiore o uguale a:",
                initialvalue=sell_rsi,
                minvalue=1.0,
                maxvalue=99.0,
                parent=self.root,
            )
            if nuovo_sell is None:
                return
            buy_rsi = float(nuovo_buy)
            sell_rsi = float(nuovo_sell)

            if buy_rsi >= sell_rsi:
                messagebox.showerror(
                    "Soglie non valide",
                    "La soglia di acquisto deve essere più bassa della soglia di vendita.\n\n"
                    "Esempio sensato: compra RSI <= 35, vendi RSI >= 65."
                )
                return

        self.cfg["auto_trading_attivo"] = active
        self.cfg["soglia_acquisto"] = buy_rsi
        self.cfg["soglia_vendita"] = sell_rsi
        self.cfg["modalita_trading"] = "Personalizzata"
        salva_config(self.cfg)
        append_comando("SET_AUTO_TRADE", {"active": active, "buy_rsi": buy_rsi, "sell_rsi": sell_rsi})
        stato = "ON" if active else "OFF"
        self.var_auto_trade_status.set(f"Auto Trade {stato} · Buy RSI≤{buy_rsi:.1f} · Sell RSI≥{sell_rsi:.1f}")
        self.var_modalita_trading.set("Personalizzata")
        self.scrivi_log(f"[COMANDO] Auto Trade {stato} | Buy RSI <= {buy_rsi:.1f} | Sell RSI >= {sell_rsi:.1f}")

    def configura_auto_profit_loss(self):
        self.cfg = carica_config()
        scelta = messagebox.askyesnocancel(
            "Auto Profit/Loss",
            "Vuoi attivare l'Auto Profit/Loss?\n\nSì = attiva\nNo = disattiva\nAnnulla = lascia invariato"
        )
        if scelta is None:
            return

        active = bool(scelta)
        tp = safe_float(self.cfg.get("take_profit_percentuale", 2.0))
        sl = safe_float(self.cfg.get("stop_loss_percentuale", 3.0))

        if active:
            nuovo_tp = simpledialog.askfloat("Take Profit automatico", "Percentuale di guadagno da incassare automaticamente:", initialvalue=tp, minvalue=0.1, maxvalue=100.0, parent=self.root)
            if nuovo_tp is None:
                return
            nuovo_sl = simpledialog.askfloat("Stop Loss automatico", "Percentuale massima di perdita prima di chiudere la posizione:", initialvalue=sl, minvalue=0.1, maxvalue=100.0, parent=self.root)
            if nuovo_sl is None:
                return
            tp = float(nuovo_tp)
            sl = float(nuovo_sl)

        self.cfg["auto_profit_loss_attivo"] = active
        self.cfg["take_profit_percentuale"] = tp
        self.cfg["stop_loss_percentuale"] = sl
        self.cfg["modalita_trading"] = "Personalizzata"
        salva_config(self.cfg)
        self.var_modalita_trading.set("Personalizzata")
        append_comando("SET_AUTO_PL", {"active": active, "take_profit": tp, "stop_loss": sl})
        self.scrivi_log(f"[COMANDO] Auto P/L {'ON' if active else 'OFF'} | TP {tp:.2f}% | SL {sl:.2f}%")

    def seleziona_crypto_da_lista(self, event=None):
        if not self._widget_alive("tabella_listino"):
            return
        selected = self.tabella_listino.selection()
        if selected:
            item = selected[0]
            self.crypto_selezionata_grafico = item
            self.var_crypto.set(item)
            self.confronto_attivo = False
            self.crypto_confronto = []
            self.scrivi_log(f"[GRAFICO] Focus su: {item}")
            self.aggiorna_riepilogo_crypto_selezionata()
            self.aggiorna_grafici()

    def seleziona_crypto_combo(self, event=None):
        self.crypto_selezionata_grafico = self.crypto_corrente()
        self.confronto_attivo = False
        self.crypto_confronto = []
        self.scrivi_log(f"[GRAFICO] Focus su: {self.crypto_selezionata_grafico}")
        self.aggiorna_grafici()

    def set_modalita_grafico(self, modalita):
        self.confronto_attivo = False
        self.crypto_confronto = []
        self.modalita_grafico_crypto = modalita
        self.var_modalita_grafico.set(modalita)
        self.btn_confronto_crypto.config(text="Confronta crypto")
        self.scrivi_log(f"[GRAFICO] Modalità {modalita} attiva.")
        self.aggiorna_grafici()

    def seleziona_confronto_crypto(self):
        simboli_disponibili = list(self.status.get("ohlc", {}).keys())
        if len(simboli_disponibili) < 2:
            simboli_disponibili = [simbolo_visuale(b) for b in self.cfg.get("crypto_base_list", [])]

        finestra = tk.Toplevel(self.root)
        finestra.title("Confronta crypto")
        finestra.geometry("360x520")
        finestra.configure(bg=self.BG)
        finestra.transient(self.root)
        finestra.grab_set()

        tk.Label(finestra, text="Seleziona 2 o più crypto da confrontare", bg=self.BG, fg=self.TEXT, font=("Helvetica", 10, "bold")).pack(pady=(12, 4))
        tk.Label(finestra, text="Il confronto mostra la performance % dal primo punto disponibile.", bg=self.BG, fg=self.MUTED, wraplength=310).pack(pady=(0, 8))

        listbox = tk.Listbox(finestra, selectmode=tk.MULTIPLE, height=16, bg=self.PANEL, fg="#f0f6fc", selectbackground="#1f6feb", selectforeground="#ffffff", exportselection=False, font=("Helvetica", 10))
        listbox.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        for simbolo in simboli_disponibili:
            listbox.insert(tk.END, simbolo)

        preselezione = []
        if self.crypto_selezionata_grafico in simboli_disponibili:
            preselezione.append(self.crypto_selezionata_grafico)
        for simbolo in simboli_disponibili:
            if simbolo not in preselezione:
                preselezione.append(simbolo)
            if len(preselezione) >= 4:
                break
        for i, simbolo in enumerate(simboli_disponibili):
            if simbolo in preselezione:
                listbox.selection_set(i)

        def conferma():
            selezioni = [simboli_disponibili[i] for i in listbox.curselection()]
            if len(selezioni) < 2:
                messagebox.showerror("Errore", "Seleziona almeno 2 crypto.")
                return
            self.crypto_confronto = selezioni
            self.confronto_attivo = True
            self.modalita_grafico_crypto = "confronto"
            self.btn_confronto_crypto.config(text=f"Confronto: {len(selezioni)}")
            self.scrivi_log("[GRAFICO] Confronto attivo: " + ", ".join(selezioni))
            self.aggiorna_grafici()
            finestra.destroy()

        frame_btn = tk.Frame(finestra, bg=self.BG)
        frame_btn.pack(pady=10)
        self.make_button(frame_btn, "Mostra confronto", conferma, "blue", min_width=136).pack(side=tk.LEFT, padx=5)
        self.make_button(frame_btn, "Annulla", finestra.destroy, "dark", min_width=82).pack(side=tk.LEFT, padx=5)

    def disattiva_confronto_crypto(self):
        self.confronto_attivo = False
        self.crypto_confronto = []
        self.modalita_grafico_crypto = "linea"
        self.var_modalita_grafico.set("linea")
        self.btn_confronto_crypto.config(text="Confronta crypto")
        self.scrivi_log("[GRAFICO] Vista singola crypto attiva.")
        self.aggiorna_grafici()

    def refresh_dashboard(self):
        if self._closed:
            return

        self.cfg = carica_config()
        self.status = load_json_file(FILE_STATUS, {})

        self.aggiorna_engine_label()
        self.aggiorna_header()
        self.aggiorna_tabelle()
        self.aggiorna_grafici()
        self.aggiorna_registro()
        self.aggiorna_storico_dashboard()
        self.aggiorna_storico_trade()
        self.aggiorna_bottoni()

        self._refresh_after_id = self.root.after(2000, self.refresh_dashboard)

    def aggiorna_engine_label(self):
        pid = get_engine_pid()
        engine_status = self.status.get("engine", {})
        last = engine_status.get("last_update", "mai")
        msg = engine_status.get("messaggio", "")

        if pid:
            self.lbl_engine.config(text=f"ENGINE: ATTIVO · PID {pid} · {last}", fg=self.GREEN)
            self.btn_engine.config(text="Ferma Bot")
        else:
            self.lbl_engine.config(text=f"ENGINE: FERMO · ultimo status: {last}", fg=self.RED)
            self.btn_engine.config(text="Avvia Bot")

        if msg and not hasattr(self, "_last_engine_msg"):
            self._last_engine_msg = msg
        elif msg and getattr(self, "_last_engine_msg", "") != msg:
            self._last_engine_msg = msg
            self.scrivi_log(f"[ENGINE] {msg}")

    def aggiorna_header(self):
        balances = self.status.get("balances", {})
        saldo = safe_float(balances.get("saldo_eur", self.cfg.get("saldo_eur", 0.0)))
        investito = safe_float(balances.get("investito", 0.0))
        valore = safe_float(balances.get("valore_posizioni", 0.0))
        patrimonio = safe_float(balances.get("patrimonio", saldo + valore))
        pl_realizzato = safe_float(balances.get("profitto_accumulato", 0.0))
        pl_non_realizzato = safe_float(balances.get("profitto_non_realizzato", valore - investito))
        totale_pl = pl_realizzato + pl_non_realizzato
        acquisti = int(balances.get("totale_acquisti", self.cfg.get("totale_acquisti", 0)))
        vendite = int(balances.get("totale_vendite", self.cfg.get("totale_vendite", 0)))

        self.card_vars["saldo"].set(format_eur(saldo))
        self.card_vars["investito"].set(format_eur(investito))
        self.card_vars["valore"].set(format_eur(valore))
        self.card_vars["patrimonio"].set(format_eur(patrimonio))
        self.card_vars["pl"].set(f"{totale_pl:+.2f} EUR")
        self.card_vars["ops"].set(f"{acquisti} acquisti · {vendite} vendite")

        settings = self.status.get("settings", {})
        tf = settings.get("timeframe", self.cfg.get("timeframe", "1m"))
        if self.var_timeframe.get() != tf:
            self.var_timeframe.set(tf)

        risk = safe_float(settings.get("risk_percent", self.cfg.get("percentuale_rischio_per_trade", 5.0)))
        nuovo_testo_risk = f"{risk:.2f}%"
        if self.var_investimento_percentuale.get() != nuovo_testo_risk:
            self.var_investimento_percentuale.set(nuovo_testo_risk)

        modalita = settings.get("modalita_trading", self.cfg.get("modalita_trading", "Normale"))
        if modalita != "Personalizzata":
            modalita = normalizza_modalita_trading(modalita)
            modalita_txt = descrizione_modalita_trading(modalita)
        else:
            modalita_txt = "Personalizzata"
        if self.var_modalita_trading.get() != modalita_txt:
            self.var_modalita_trading.set(modalita_txt)

        auto_trade = bool(settings.get("auto_trading_attivo", self.cfg.get("auto_trading_attivo", False)))
        buy_rsi = safe_float(settings.get("soglia_acquisto", self.cfg.get("soglia_acquisto", 35)))
        sell_rsi = safe_float(settings.get("soglia_vendita", self.cfg.get("soglia_vendita", 65)))
        stato = "ON" if auto_trade else "OFF"
        nuovo_auto_txt = f"Auto Trade {stato} · Buy RSI≤{buy_rsi:.1f} · Sell RSI≥{sell_rsi:.1f}"
        if self.var_auto_trade_status.get() != nuovo_auto_txt:
            self.var_auto_trade_status.set(nuovo_auto_txt)

    def aggiorna_tabelle(self):
        watchlist = self.status.get("watchlist", {})
        symbols_all = [simbolo_visuale(b) for b in self.cfg.get("crypto_base_list", [])]
        combo_values = symbols_all

        try:
            self.combo_crypto.configure(values=combo_values)
        except Exception:
            pass

        if self._widget_alive("tabella_listino"):
            for item in self.tabella_listino.get_children():
                self.tabella_listino.delete(item)

            for simbolo in symbols_all:
                data = watchlist.get(simbolo, {})
                price = safe_float(data.get("price", 0.0))
                rsi = safe_float(data.get("rsi", 0.0))
                change = safe_float(data.get("change_pct", 0.0))
                source = str(data.get("source", "N/D")).replace("/USDT", "/USDT*")
                has_pos = bool(data.get("has_position", False))
                tag = "positivo" if change > 0 else "negativo" if change < 0 else "neutro"

                self.tabella_listino.insert(
                    "", tk.END, iid=simbolo, text=simbolo,
                    values=(format_price(price), f"{rsi:.1f}", format_pct(change), source, "Sì" if has_pos else "No"),
                    tags=(tag,)
                )

            if self.crypto_selezionata_grafico in self.tabella_listino.get_children():
                self.tabella_listino.selection_set(self.crypto_selezionata_grafico)

        if self._widget_alive("tabella_pancia"):
            for item in self.tabella_pancia.get_children():
                self.tabella_pancia.delete(item)

            for posizione in self.status.get("positions", []):
                simbolo = posizione.get("simbolo", "")
                entry = safe_float(posizione.get("entry", 0.0))
                quantita = safe_float(posizione.get("quantita", 0.0))
                capitale = safe_float(posizione.get("capitale", 0.0))
                valore = safe_float(posizione.get("valore", 0.0))
                pl_eur = safe_float(posizione.get("pl_eur", 0.0))
                pl_pct = safe_float(posizione.get("pl_pct", 0.0))
                tag = "positivo" if pl_eur >= 0 else "negativo"

                self.tabella_pancia.insert(
                    "", tk.END, iid=simbolo, text=simbolo,
                    values=(format_price(entry), f"{quantita:.6f}", format_eur(capitale), format_eur(valore), f"{pl_eur:+.2f} EUR", f"{pl_pct:+.2f}%"),
                    tags=(tag,)
                )

        self.aggiorna_riepilogo_crypto_selezionata()


    def style_axis(self, ax):
        ax.grid(True, color=self.BORDER, linestyle="--", linewidth=0.6, alpha=0.65)
        ax.tick_params(colors=self.MUTED, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(self.BORDER)
        ax.title.set_color(self.MUTED)
        ax.xaxis.label.set_color(self.MUTED)
        ax.yaxis.label.set_color(self.MUTED)

    def aggiorna_grafici(self):
        storico = self.status.get("storico_saldi", self.cfg.get("storico_saldi", [self.cfg.get("saldo_eur", 0.0)]))
        ohlc_dict = self.status.get("ohlc", {})
        ohlc = ohlc_dict.get(self.crypto_selezionata_grafico, [])

        if not ohlc and ohlc_dict:
            primo_simbolo = next(iter(ohlc_dict.keys()))
            self.crypto_selezionata_grafico = primo_simbolo
            self.var_crypto.set(primo_simbolo)
            ohlc = ohlc_dict.get(primo_simbolo, [])

        self.ax_crypto.clear()
        self.ax_fondi.clear()

        # Grafico capitale
        try:
            valori = [safe_float(v) for v in storico if safe_float(v) > 0]
            if valori:
                self.ax_fondi.plot(valori, color=self.GREEN, linewidth=2, marker="o", markersize=3)
                self.ax_fondi.set_title("Evoluzione patrimonio/saldo simulato", fontsize=9, fontweight="bold")
            else:
                self.ax_fondi.text(0.5, 0.5, "Nessun dato saldo", ha="center", va="center", color=self.MUTED, transform=self.ax_fondi.transAxes)
        except Exception:
            self.ax_fondi.text(0.5, 0.5, "Grafico saldo non disponibile", ha="center", va="center", color=self.MUTED, transform=self.ax_fondi.transAxes)
        self.style_axis(self.ax_fondi)

        # Grafico crypto / confronto
        if self.confronto_attivo and len(self.crypto_confronto) >= 2:
            almeno_una = False
            for simbolo in self.crypto_confronto:
                dati = ohlc_dict.get(simbolo, [])
                chiusure = [safe_float(c.get("close", 0.0)) for c in dati if safe_float(c.get("close", 0.0)) > 0]
                if len(chiusure) < 2:
                    continue
                base = chiusure[0]
                if base <= 0:
                    continue
                performance = [((prezzo / base) - 1) * 100 for prezzo in chiusure]
                self.ax_crypto.plot(performance, linewidth=1.6, label=simbolo)
                almeno_una = True

            if almeno_una:
                self.ax_crypto.axhline(0, color=self.MUTED, linewidth=0.8, linestyle="--")
                self.ax_crypto.set_title("Confronto performance crypto (%)", fontsize=9, fontweight="bold")
                legend = self.ax_crypto.legend(fontsize=7, loc="best", facecolor=self.PANEL, edgecolor=self.BORDER)
                for text in legend.get_texts():
                    text.set_color(self.TEXT)
                self.lbl_chart_title.config(text="Confronto crypto")
            else:
                self.ax_crypto.text(0.5, 0.5, "Dati insufficienti per il confronto", ha="center", va="center", color=self.MUTED, transform=self.ax_crypto.transAxes)
        else:
            if ohlc:
                if self.modalita_grafico_crypto == "candele":
                    larghezza = 0.55
                    for i, candle in enumerate(ohlc):
                        apertura = safe_float(candle.get("open"))
                        massimo = safe_float(candle.get("high"))
                        minimo = safe_float(candle.get("low"))
                        chiusura = safe_float(candle.get("close"))
                        colore = self.GREEN if chiusura >= apertura else self.RED
                        self.ax_crypto.vlines(i, minimo, massimo, color=colore, linewidth=1)
                        bottom = min(apertura, chiusura)
                        altezza = abs(chiusura - apertura)
                        if altezza == 0:
                            altezza = massimo * 0.0001 if massimo > 0 else 0.0001
                        self.ax_crypto.add_patch(matplotlib.patches.Rectangle((i - larghezza / 2, bottom), larghezza, altezza, facecolor=colore, edgecolor=colore, linewidth=0.8))
                    self.ax_crypto.set_xlim(-1, len(ohlc))
                    self.ax_crypto.set_title(f"Candele live: {self.crypto_selezionata_grafico}", fontsize=9, fontweight="bold")
                else:
                    chiusure = [safe_float(c.get("close", 0.0)) for c in ohlc]
                    self.ax_crypto.plot(chiusure, color=self.BLUE, linewidth=2)
                    if len(chiusure) >= 2:
                        var = ((chiusure[-1] - chiusure[0]) / chiusure[0] * 100) if chiusure[0] > 0 else 0.0
                        self.ax_crypto.set_title(f"Linea live: {self.crypto_selezionata_grafico} · {var:+.2f}%", fontsize=9, fontweight="bold")
                    else:
                        self.ax_crypto.set_title(f"Linea live: {self.crypto_selezionata_grafico}", fontsize=9, fontweight="bold")
                self.lbl_chart_title.config(text=f"Grafico {self.crypto_selezionata_grafico}")
            else:
                self.ax_crypto.text(0.5, 0.5, "In attesa dati mercato...", ha="center", va="center", color=self.MUTED, transform=self.ax_crypto.transAxes)
                self.ax_crypto.set_title("Mercato", fontsize=9, fontweight="bold")

        self.style_axis(self.ax_crypto)
        self.fig.tight_layout(pad=2.0)
        try:
            self.canvas.draw_idle()
        except Exception:
            pass

    def aggiorna_registro(self):
        if not self._widget_alive("tabella_registro"):
            return

        for item in self.tabella_registro.get_children():
            self.tabella_registro.delete(item)

        if not FILE_LOG.exists():
            return

        try:
            rows = leggi_registro_operazioni()[-5:]
            for row in reversed(rows):
                self.tabella_registro.insert(
                    "", tk.END,
                    values=(
                        row.get("Data_Ora", ""),
                        f"{row.get('Crypto', '')} {row.get('Operazione', '')}",
                        format_price(safe_float(row.get("Prezzo_EUR", 0.0))),
                        format_eur(safe_float(row.get("Saldo_EUR", 0.0))),
                        row.get("Note", "")[:120]
                    )
                )
        except Exception as e:
            log_errore("Errore lettura registro dashboard", e)


    def aggiorna_storico_dashboard(self):
        """Aggiorna il riquadro compatto visibile nella colonna sinistra."""
        if not self._widget_alive("tabella_storico_dashboard"):
            return

        for item in self.tabella_storico_dashboard.get_children():
            self.tabella_storico_dashboard.delete(item)

        try:
            rows = leggi_registro_operazioni()
            acquisti = [row for row in rows if self._operazione_is_acquisto(row.get("Operazione", ""))]
            if not acquisti:
                if hasattr(self, "lbl_storico_dashboard"):
                    self.lbl_storico_dashboard.config(text="Nessun acquisto registrato")
                return

            for idx, row in enumerate(reversed(acquisti[-8:])):
                iid = f"dashboard-buy-{idx}"
                self._righe_storico_trade[iid] = row
                self.tabella_storico_dashboard.insert(
                    "", tk.END,
                    iid=iid,
                    values=(
                        row.get("Data_Ora", ""),
                        row.get("Crypto", ""),
                        format_quantita(row.get("Quantita", "")),
                        format_price(safe_float(row.get("Prezzo_EUR", 0.0))),
                        format_eur_detail(row.get("Importo_EUR", "")),
                        format_eur_detail(row.get("Commissione_EUR", "")),
                        format_eur_detail(row.get("Saldo_EUR", "")),
                    ),
                    tags=("acquisto",),
                )

            if hasattr(self, "lbl_storico_dashboard"):
                totale = sum(safe_float(row.get("Importo_EUR", 0.0)) for row in acquisti)
                commissioni = sum(safe_float(row.get("Commissione_EUR", 0.0)) for row in acquisti)
                self.lbl_storico_dashboard.config(
                    text=f"{len(acquisti)} acquisti · Investito {format_eur(totale)} · Comm. {format_eur(commissioni)}"
                )
        except Exception as e:
            log_errore("Errore lettura storico visibile dashboard", e)
            if hasattr(self, "lbl_storico_dashboard"):
                self.lbl_storico_dashboard.config(text="Errore lettura storico operazioni")

    def aggiorna_storico_trade(self):
        """Aggiorna le due tabelle dedicate ad acquisti e vendite."""
        if not self._widget_alive("tabella_acquisti") or not self._widget_alive("tabella_vendite"):
            return

        for tabella in (self.tabella_acquisti, self.tabella_vendite):
            for item in tabella.get_children():
                tabella.delete(item)

        acquisti = []
        vendite = []
        try:
            rows = leggi_registro_operazioni()
            if not rows:
                if hasattr(self, "lbl_storico_trade"):
                    self.lbl_storico_trade.config(text="Nessun registro operazioni trovato")
                return

            for row in rows:
                operazione = row.get("Operazione", "")
                if self._operazione_is_acquisto(operazione):
                    acquisti.append(row)
                elif self._operazione_is_vendita(operazione):
                    vendite.append(row)

            for idx, row in enumerate(reversed(acquisti[-80:])):
                iid = f"acquisto-{idx}"
                self._righe_storico_trade[iid] = row
                self.tabella_acquisti.insert(
                    "", tk.END,
                    iid=iid,
                    text=row.get("Crypto", ""),
                    values=self._valori_riga_trade(row),
                    tags=("acquisto",),
                )

            for idx, row in enumerate(reversed(vendite[-80:])):
                iid = f"vendita-{idx}"
                self._righe_storico_trade[iid] = row
                self.tabella_vendite.insert(
                    "", tk.END,
                    iid=iid,
                    text=row.get("Crypto", ""),
                    values=self._valori_riga_trade(row),
                    tags=(self._tag_operazione(row),),
                )

            if hasattr(self, "lbl_storico_trade"):
                totale_acquisti = sum(safe_float(r.get("Importo_EUR", 0.0)) for r in acquisti)
                totale_vendite = sum(safe_float(r.get("Importo_EUR", 0.0)) for r in vendite)
                profitto_vendite = sum(safe_float(r.get("Profitto_EUR", 0.0)) for r in vendite)
                commissioni = sum(safe_float(r.get("Commissione_EUR", 0.0)) for r in acquisti + vendite)
                self.lbl_storico_trade.config(
                    text=(
                        f"{len(acquisti)} acquisti {format_eur(totale_acquisti)} · "
                        f"{len(vendite)} vendite {format_eur(totale_vendite)} · "
                        f"P/L {profitto_vendite:+.2f} EUR · Comm. {format_eur(commissioni)}"
                    )
                )
        except Exception as e:
            log_errore("Errore lettura storico acquisti/vendite", e)
            if hasattr(self, "lbl_storico_trade"):
                self.lbl_storico_trade.config(text="Errore lettura storico acquisti/vendite")

    def aggiorna_bottoni(self):
        # Mantiene l'interfaccia coerente se la crypto selezionata cambia da tabella.
        if self.var_crypto.get() != self.crypto_selezionata_grafico:
            self.var_crypto.set(self.crypto_selezionata_grafico)

    def run(self):
        self.root.mainloop()


# ============================================================
# MAIN
# ============================================================

def main():
    inizializza_file_registro()

    engine_mode = "--engine" in sys.argv or os.environ.get(ENGINE_ENV_FLAG) == "1"
    if engine_mode:
        run_engine()
        return

    app = QuantumDashboard()
    app.run()


if __name__ == "__main__":
    main()
