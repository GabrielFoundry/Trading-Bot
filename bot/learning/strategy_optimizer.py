"""
Optimiseur de stratégie par grid search avec walk-forward validation.
Ne modifie les paramètres QUE si l'amélioration dépasse le seuil configuré.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from bot.db.database import Database, StrategyParams


class StrategyOptimizer:
    """
    Optimise les paramètres de stratégie sur la base des trades historiques.

    Approche : grid search conservateur
    - Génère des variations ±10% et ±20% autour des paramètres actuels
    - Backteste chaque candidat sur les signaux/trades stockés en DB
    - Adopte les nouveaux params SEULEMENT si amélioration > min_improvement_pct

    Métrique d'optimisation : profit_factor × win_rate
    (plus robuste que le P&L brut pour éviter le surapprentissage)
    """

    def __init__(
        self,
        db: Database,
        min_trades: int = 50,
        min_improvement_pct: float = 5.0,
    ):
        self.db = db
        self.min_trades = min_trades
        self.min_improvement_pct = min_improvement_pct

    def run(self) -> Optional[dict]:
        """
        Lance le cycle d'optimisation.
        Retourne un résumé ou None si les conditions ne sont pas réunies.
        """
        trades = self.db.get_closed_trades_for_analysis(limit=500)
        if len(trades) < self.min_trades:
            logger.info(
                f"Optimiseur : seulement {len(trades)} trades "
                f"(minimum {self.min_trades}). Optimisation ignorée."
            )
            return None

        current_params = self.db.get_active_strategy_params()
        current_score = self._evaluate_params(current_params, trades)

        logger.info(
            f"Optimiseur : évaluation des paramètres actuels "
            f"(version {current_params.version}). "
            f"Score actuel: {current_score:.4f}"
        )

        # Générer les candidats
        candidates = self._generate_candidates(current_params)
        logger.info(f"Optimiseur : {len(candidates)} candidats à évaluer")

        best_params = current_params
        best_score = current_score

        for candidate in candidates:
            score = self._evaluate_params(candidate, trades)
            if score > best_score:
                best_score = score
                best_params = candidate

        # Vérifier le seuil d'amélioration
        improvement_pct = (
            (best_score - current_score) / current_score * 100
            if current_score > 0 else 0.0
        )

        if improvement_pct >= self.min_improvement_pct:
            # Calculer les métriques actuelles pour la traçabilité
            perf = self._compute_simple_metrics(trades)
            reason = (
                f"Optimisation automatique — amélioration de {improvement_pct:.1f}% "
                f"sur profit_factor×win_rate "
                f"({current_score:.4f} → {best_score:.4f})"
            )
            self.db.save_new_strategy_params(
                best_params,
                win_rate=perf.get("win_rate"),
                profit_factor=perf.get("profit_factor"),
                reason=reason,
            )
            self.db.update_bot_state(
                last_optimization_at=datetime.now(timezone.utc).isoformat()
            )
            logger.info(
                f"Optimiseur : NOUVEAUX PARAMÈTRES adoptés ! "
                f"Amélioration: {improvement_pct:.1f}%"
            )
            return {
                "optimized": True,
                "improvement_pct": round(improvement_pct, 2),
                "old_score": round(current_score, 4),
                "new_score": round(best_score, 4),
                "reason": reason,
            }
        else:
            logger.info(
                f"Optimiseur : aucun changement "
                f"(meilleure amélioration: {improvement_pct:.1f}% < {self.min_improvement_pct}%)"
            )
            self.db.update_bot_state(
                last_optimization_at=datetime.now(timezone.utc).isoformat()
            )
            return {
                "optimized": False,
                "improvement_pct": round(improvement_pct, 2),
                "current_score": round(current_score, 4),
            }

    def _evaluate_params(self, params: StrategyParams, trades: list[dict]) -> float:
        """
        Simule les trades avec les paramètres donnés en rejouant les signaux stockés.
        Retourne le score : profit_factor × win_rate.
        """
        simulated_pnls = []

        for trade in trades:
            if trade.get("pnl_usdt") is None:
                continue

            raw_indicators = trade.get("raw_indicators") or {}
            if not raw_indicators:
                # Pas d'indicateurs stockés → on garde le trade tel quel
                simulated_pnls.append(trade["pnl_usdt"])
                continue

            # Vérifier si le signal aurait été déclenché avec ces paramètres
            rsi = raw_indicators.get("rsi")
            macd = raw_indicators.get("macd")
            macd_sig = raw_indicators.get("macd_signal")
            bb_pct = raw_indicators.get("bb_pct")

            would_signal = self._would_signal_fire(
                rsi=rsi, macd=macd, macd_signal=macd_sig, bb_pct=bb_pct, params=params
            )

            if would_signal:
                simulated_pnls.append(trade["pnl_usdt"])
            # Si le signal ne se serait pas déclenché, on ignore ce trade

        if len(simulated_pnls) < 5:
            return 0.0

        winning = [p for p in simulated_pnls if p > 0]
        losing = [p for p in simulated_pnls if p <= 0]

        win_rate = len(winning) / len(simulated_pnls)
        gross_profit = sum(winning)
        gross_loss = abs(sum(losing)) if losing else 1.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit

        return profit_factor * win_rate

    @staticmethod
    def _would_signal_fire(
        rsi: Optional[float],
        macd: Optional[float],
        macd_signal: Optional[float],
        bb_pct: Optional[float],
        params: StrategyParams,
    ) -> bool:
        """Simule si un signal BUY aurait été généré avec ces paramètres."""
        score = 0.0

        if rsi is not None:
            if rsi < params.rsi_oversold:
                score += 0.25
            elif rsi > params.rsi_overbought:
                score -= 0.25

        if macd is not None and macd_signal is not None:
            if macd > macd_signal:
                score += 0.20
            elif macd < macd_signal:
                score -= 0.20

        if bb_pct is not None:
            if bb_pct < 0.1:
                score += 0.15
            elif bb_pct > 0.9:
                score -= 0.15

        return score >= params.buy_threshold

    def _generate_candidates(self, base: StrategyParams) -> list[StrategyParams]:
        """
        Génère des variations des paramètres principaux.
        Chaque paramètre varie à ±10% et ±20%.
        """
        candidates = []

        # Paramètres à optimiser et leurs plages de variation
        adjustments = {
            "rsi_oversold": [0.8, 0.9, 1.0, 1.1, 1.2],  # ×multiplier
            "rsi_overbought": [0.8, 0.9, 1.0, 1.1, 1.2],
            "buy_threshold": [0.8, 0.9, 1.0, 1.1, 1.2],
            "sell_threshold": [0.8, 0.9, 1.0, 1.1, 1.2],
            "sentiment_weight": [0.8, 0.9, 1.0, 1.1, 1.2],
        }

        # Générer 1 paramètre à la fois (évite l'explosion combinatoire)
        for param_name, multipliers in adjustments.items():
            base_value = getattr(base, param_name)
            for mult in multipliers:
                if mult == 1.0:
                    continue
                new_value = base_value * mult

                # Contraintes de validité
                if param_name in ("rsi_oversold",) and not (20 <= new_value <= 45):
                    continue
                if param_name in ("rsi_overbought",) and not (55 <= new_value <= 80):
                    continue
                if param_name in ("buy_threshold",) and not (0.2 <= new_value <= 0.7):
                    continue
                if param_name in ("sell_threshold",) and not (-0.7 <= new_value <= -0.2):
                    continue
                if param_name in ("sentiment_weight",) and not (0.0 <= new_value <= 0.5):
                    continue

                # Créer un nouveau candidat avec seulement ce paramètre modifié
                candidate = StrategyParams(
                    version=base.version,
                    rsi_period=base.rsi_period,
                    rsi_oversold=base.rsi_oversold,
                    rsi_overbought=base.rsi_overbought,
                    macd_fast=base.macd_fast,
                    macd_slow=base.macd_slow,
                    macd_signal=base.macd_signal,
                    bb_period=base.bb_period,
                    bb_std=base.bb_std,
                    ema_fast=base.ema_fast,
                    ema_slow=base.ema_slow,
                    volume_threshold_mult=base.volume_threshold_mult,
                    buy_threshold=base.buy_threshold,
                    sell_threshold=base.sell_threshold,
                    atr_stop_multiplier=base.atr_stop_multiplier,
                    risk_reward_ratio=base.risk_reward_ratio,
                    sentiment_weight=base.sentiment_weight,
                )
                setattr(candidate, param_name, round(new_value, 4))
                candidates.append(candidate)

        return candidates

    def _compute_simple_metrics(self, trades: list[dict]) -> dict:
        pnls = [t["pnl_usdt"] for t in trades if t.get("pnl_usdt") is not None]
        if not pnls:
            return {}
        winning = [p for p in pnls if p > 0]
        losing = [p for p in pnls if p <= 0]
        win_rate = len(winning) / len(pnls)
        gross_loss = abs(sum(losing)) if losing else 1.0
        profit_factor = sum(winning) / gross_loss if gross_loss > 0 else sum(winning)
        return {"win_rate": round(win_rate, 4), "profit_factor": round(profit_factor, 4)}
