"""
Calcul des métriques de performance.
Exécuté après chaque trade clôturé et lors du cycle d'apprentissage quotidien.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from bot.db.database import Database


class PerformanceTracker:
    """
    Calcule et persiste les métriques de performance du bot.

    Métriques calculées :
    - Win rate (% de trades gagnants)
    - Average win / average loss / profit factor
    - Sharpe ratio (annualisé)
    - Maximum drawdown
    - P&L total et par symbole
    """

    def __init__(self, db: Database, window: int = 50):
        self.db = db
        self.window = window

    def calculate_and_save(self) -> Optional[dict]:
        """
        Calcule toutes les métriques sur les N derniers trades et les persiste.
        Retourne None si pas assez de données.
        """
        trades = self.db.get_closed_trades_for_analysis(limit=self.window * 2)
        if len(trades) < 5:
            logger.info(f"Pas assez de trades pour calculer les métriques ({len(trades)} < 5)")
            return None

        # Fenêtre glissante
        recent_trades = trades[:self.window]

        metrics = self._compute_metrics(recent_trades, all_trades=trades)
        metrics["calculated_at"] = datetime.now(timezone.utc).isoformat()
        metrics["window_trades"] = len(recent_trades)

        self.db.save_performance_metrics(metrics)

        logger.info(
            f"Métriques calculées : win_rate={metrics['win_rate']:.1%} | "
            f"profit_factor={metrics['profit_factor']:.2f} | "
            f"max_drawdown={metrics['max_drawdown_pct']:.1f}%"
        )
        return metrics

    def _compute_metrics(self, trades: list[dict], all_trades: list[dict]) -> dict:
        pnls = [t["pnl_usdt"] for t in trades if t.get("pnl_usdt") is not None]

        if not pnls:
            return self._empty_metrics(len(trades))

        winning = [p for p in pnls if p > 0]
        losing = [p for p in pnls if p <= 0]

        total = len(pnls)
        win_count = len(winning)
        loss_count = len(losing)
        win_rate = win_count / total if total > 0 else 0.0

        avg_win = sum(winning) / len(winning) if winning else 0.0
        avg_loss = abs(sum(losing) / len(losing)) if losing else 0.0
        gross_profit = sum(winning)
        gross_loss = abs(sum(losing))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit

        total_pnl = sum(pnls)
        initial_balance = self.db.get_bot_state().paper_balance
        total_pnl_pct = total_pnl / initial_balance * 100 if initial_balance > 0 else 0.0

        max_drawdown_pct = self._calculate_max_drawdown()
        sharpe = self._calculate_sharpe_ratio()

        # Performance par symbole
        symbol_pnl: dict[str, float] = {}
        for t in trades:
            sym = t.get("symbol", "?")
            pnl = t.get("pnl_usdt", 0.0) or 0.0
            symbol_pnl[sym] = symbol_pnl.get(sym, 0.0) + pnl

        best_symbol = max(symbol_pnl, key=symbol_pnl.get) if symbol_pnl else None
        worst_symbol = min(symbol_pnl, key=symbol_pnl.get) if symbol_pnl else None

        return {
            "total_trades": total,
            "winning_trades": win_count,
            "losing_trades": loss_count,
            "win_rate": round(win_rate, 4),
            "avg_win_usdt": round(avg_win, 4),
            "avg_loss_usdt": round(avg_loss, 4),
            "profit_factor": round(profit_factor, 4),
            "sharpe_ratio": round(sharpe, 4) if sharpe is not None else None,
            "max_drawdown_pct": round(max_drawdown_pct, 4),
            "total_pnl_usdt": round(total_pnl, 4),
            "total_pnl_pct": round(total_pnl_pct, 4),
            "best_symbol": best_symbol,
            "worst_symbol": worst_symbol,
        }

    def _calculate_max_drawdown(self) -> float:
        """Calcule le max drawdown depuis les snapshots portfolio."""
        snapshots = self.db.get_portfolio_history(days=365)
        if len(snapshots) < 2:
            return 0.0

        values = [s["total_value"] for s in snapshots]
        peak = values[0]
        max_dd = 0.0

        for value in values:
            if value > peak:
                peak = value
            dd = (peak - value) / peak * 100
            if dd > max_dd:
                max_dd = dd

        return max_dd

    def _calculate_sharpe_ratio(self, risk_free_rate: float = 0.02) -> Optional[float]:
        """
        Calcule le ratio de Sharpe annualisé sur les retours quotidiens.
        Utilise les snapshots portfolio.
        """
        snapshots = self.db.get_portfolio_history(days=90)
        if len(snapshots) < 10:
            return None

        values = [s["total_value"] for s in snapshots]
        daily_returns = [
            (values[i] - values[i - 1]) / values[i - 1]
            for i in range(1, len(values))
            if values[i - 1] > 0
        ]

        if len(daily_returns) < 5:
            return None

        avg_return = sum(daily_returns) / len(daily_returns)
        variance = sum((r - avg_return) ** 2 for r in daily_returns) / len(daily_returns)
        std_dev = math.sqrt(variance) if variance > 0 else 0.0

        if std_dev == 0:
            return None

        daily_rf = risk_free_rate / 365
        sharpe = (avg_return - daily_rf) / std_dev * math.sqrt(365)
        return sharpe

    @staticmethod
    def _empty_metrics(trade_count: int) -> dict:
        return {
            "total_trades": trade_count,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "avg_win_usdt": 0.0,
            "avg_loss_usdt": 0.0,
            "profit_factor": 0.0,
            "sharpe_ratio": None,
            "max_drawdown_pct": 0.0,
            "total_pnl_usdt": 0.0,
            "total_pnl_pct": 0.0,
            "best_symbol": None,
            "worst_symbol": None,
        }
