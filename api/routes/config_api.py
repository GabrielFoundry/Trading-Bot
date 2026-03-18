"""
Route API pour lire et modifier la configuration du bot.
Permet à l'utilisateur de changer les paramètres directement depuis l'app mobile.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "config.yaml"

router = APIRouter()


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


# ─────────────────────────────────────────
# Schéma des paramètres modifiables
# ─────────────────────────────────────────

class MobileConfigUpdate(BaseModel):
    """Paramètres modifiables depuis l'app mobile."""
    # Trading
    pairs: Optional[list[str]] = None          # ["BTC/USDT", "ETH/USDT"]
    risk_per_trade_pct: Optional[float] = None  # 1.0 – 10.0
    max_open_positions: Optional[int] = None    # 1 – 5
    timeframe: Optional[str] = None             # "1h", "4h", etc.

    # Levier
    max_leverage: Optional[float] = None        # 1.0, 1.5, 2.0
    high_confidence_threshold: Optional[float] = None
    mid_confidence_threshold: Optional[float] = None

    # Risque
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None

    # News
    sentiment_weight: Optional[float] = None    # 0.0 – 0.5

    # Scheduler
    trading_interval_minutes: Optional[int] = None  # 1 – 60

    # Plages horaires
    schedule_enabled: Optional[bool] = None
    schedule_start: Optional[str] = None        # "07:00"
    schedule_end: Optional[str] = None          # "22:00"


# ─────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────

@router.get("")
def get_config():
    """Retourne la configuration actuelle sous forme JSON simplifiée."""
    cfg = load_config()
    trading = cfg.get("trading", {})
    leverage = cfg.get("leverage", {})
    risk = cfg.get("risk", {})
    news = cfg.get("news", {})
    scheduler = cfg.get("scheduler", {})
    schedule = cfg.get("schedule", {})

    return {
        "trading": {
            "pairs": trading.get("pairs", []),
            "risk_per_trade_pct": trading.get("risk_per_trade_pct", 3.5),
            "max_open_positions": trading.get("max_open_positions", 3),
            "timeframe": trading.get("timeframe", "1h"),
            "paper_balance": trading.get("paper_balance", 300.0),
        },
        "leverage": {
            "max_leverage": leverage.get("max_leverage", 2.0),
            "high_confidence_threshold": leverage.get("high_confidence_threshold", 0.80),
            "mid_confidence_threshold": leverage.get("mid_confidence_threshold", 0.60),
            "mid_leverage": leverage.get("mid_leverage", 1.5),
        },
        "risk": {
            "stop_loss_pct": risk.get("stop_loss_pct", 2.0),
            "take_profit_pct": risk.get("take_profit_pct", 4.0),
            "max_drawdown_pct": risk.get("max_drawdown_pct", 15.0),
        },
        "news": {
            "sentiment_weight": news.get("sentiment_weight", 0.25),
        },
        "scheduler": {
            "trading_interval_minutes": scheduler.get("trading_interval_minutes", 5),
        },
        "schedule": {
            "enabled": schedule.get("enabled", False),
            "start": schedule.get("trading_hours", [{}])[0].get("start", "07:00"),
            "end": schedule.get("trading_hours", [{}])[0].get("end", "22:00"),
        },
    }


@router.post("")
def update_config(update: MobileConfigUpdate):
    """
    Met à jour la configuration depuis l'app mobile.
    Seuls les champs fournis sont modifiés — les autres restent inchangés.
    """
    cfg = load_config()
    changed = []

    # Trading
    if update.pairs is not None:
        valid_pairs = [p for p in update.pairs if "/" in p]
        if not valid_pairs:
            raise HTTPException(400, "Au moins une paire valide est requise (ex: BTC/USDT)")
        cfg.setdefault("trading", {})["pairs"] = valid_pairs
        changed.append(f"pairs → {valid_pairs}")

    if update.risk_per_trade_pct is not None:
        if not (1.0 <= update.risk_per_trade_pct <= 10.0):
            raise HTTPException(400, "Risque doit être entre 1% et 10%")
        cfg.setdefault("trading", {})["risk_per_trade_pct"] = update.risk_per_trade_pct
        changed.append(f"risque → {update.risk_per_trade_pct}%")

    if update.max_open_positions is not None:
        if not (1 <= update.max_open_positions <= 5):
            raise HTTPException(400, "Max positions entre 1 et 5")
        cfg.setdefault("trading", {})["max_open_positions"] = update.max_open_positions
        changed.append(f"max positions → {update.max_open_positions}")

    if update.timeframe is not None:
        valid_tfs = ["1m", "5m", "15m", "1h", "4h", "1d"]
        if update.timeframe not in valid_tfs:
            raise HTTPException(400, f"Timeframe invalide. Valeurs : {valid_tfs}")
        cfg.setdefault("trading", {})["timeframe"] = update.timeframe
        changed.append(f"timeframe → {update.timeframe}")

    # Levier
    if update.max_leverage is not None:
        if update.max_leverage not in (1.0, 1.5, 2.0):
            raise HTTPException(400, "Levier max : 1.0, 1.5 ou 2.0")
        cfg.setdefault("leverage", {})["max_leverage"] = update.max_leverage
        changed.append(f"levier max → x{update.max_leverage}")

    # Risque
    if update.stop_loss_pct is not None:
        if not (0.5 <= update.stop_loss_pct <= 10.0):
            raise HTTPException(400, "Stop-loss entre 0.5% et 10%")
        cfg.setdefault("risk", {})["stop_loss_pct"] = update.stop_loss_pct
        changed.append(f"stop-loss → {update.stop_loss_pct}%")

    if update.take_profit_pct is not None:
        if not (0.5 <= update.take_profit_pct <= 20.0):
            raise HTTPException(400, "Take-profit entre 0.5% et 20%")
        cfg.setdefault("risk", {})["take_profit_pct"] = update.take_profit_pct
        changed.append(f"take-profit → {update.take_profit_pct}%")

    if update.max_drawdown_pct is not None:
        if not (5.0 <= update.max_drawdown_pct <= 50.0):
            raise HTTPException(400, "Drawdown max entre 5% et 50%")
        cfg.setdefault("risk", {})["max_drawdown_pct"] = update.max_drawdown_pct
        changed.append(f"drawdown max → {update.max_drawdown_pct}%")

    # News
    if update.sentiment_weight is not None:
        if not (0.0 <= update.sentiment_weight <= 0.5):
            raise HTTPException(400, "Poids news entre 0 et 0.5")
        cfg.setdefault("news", {})["sentiment_weight"] = update.sentiment_weight
        changed.append(f"poids news → {update.sentiment_weight}")

    # Scheduler
    if update.trading_interval_minutes is not None:
        if not (1 <= update.trading_interval_minutes <= 60):
            raise HTTPException(400, "Intervalle entre 1 et 60 minutes")
        cfg.setdefault("scheduler", {})["trading_interval_minutes"] = update.trading_interval_minutes
        changed.append(f"intervalle → {update.trading_interval_minutes}min")

    # Plages horaires
    if any(x is not None for x in [update.schedule_enabled, update.schedule_start, update.schedule_end]):
        cfg.setdefault("schedule", {})
        if update.schedule_enabled is not None:
            cfg["schedule"]["enabled"] = update.schedule_enabled
            changed.append(f"planning {'activé' if update.schedule_enabled else 'désactivé'}")

        start = update.schedule_start or cfg.get("schedule", {}).get("trading_hours", [{"start": "07:00"}])[0].get("start", "07:00")
        end = update.schedule_end or cfg.get("schedule", {}).get("trading_hours", [{"end": "22:00"}])[0].get("end", "22:00")

        if not _valid_time(start) or not _valid_time(end):
            raise HTTPException(400, "Format d'heure invalide. Utilisez HH:MM (ex: 07:00)")

        cfg["schedule"]["trading_hours"] = [{"start": start, "end": end}]
        if update.schedule_start or update.schedule_end:
            changed.append(f"horaires → {start}–{end}")

    if not changed:
        return {"success": True, "message": "Aucun changement", "changes": []}

    save_config(cfg)
    return {
        "success": True,
        "message": f"{len(changed)} paramètre(s) mis à jour",
        "changes": changed,
        "note": "Redémarrez le bot pour appliquer les changements de scheduler/timeframe.",
    }


def _valid_time(s: str) -> bool:
    """Valide le format HH:MM."""
    return bool(re.match(r"^\d{2}:\d{2}$", s))
