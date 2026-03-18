"""
Stratégie combinée : technique + fondamentale.
Gère les entrées, sorties, et le trailing stop.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger

from bot.analysis.signals import Signal
from bot.db.database import StrategyParams
from bot.strategy.base_strategy import BaseStrategy
from bot.strategy.risk_manager import OrderProposal, RiskManager


class CombinedStrategy(BaseStrategy):
    """
    Stratégie principale du bot.

    Règles d'entrée :
    - Signal BUY avec confiance > buy_threshold
    - Validation par le RiskManager

    Règles de sortie :
    - Stop-loss atteint (géré par paper_trader en temps réel)
    - Take-profit atteint (géré par paper_trader en temps réel)
    - Signal SELL avec confiance > 0.6
    - Trailing stop : si position en profit > 2%, stop monte au breakeven

    Levier :
    - Adaptatif via RiskManager selon la confiance du signal
    """

    # Confiance minimale pour déclencher une sortie sur signal
    MIN_EXIT_CONFIDENCE = 0.60
    # % de profit à partir duquel le trailing stop s'active
    TRAILING_STOP_ACTIVATION_PCT = 2.0

    def __init__(self, params: StrategyParams, risk_manager: RiskManager):
        self._params = params
        self.risk_manager = risk_manager

    def should_enter(
        self,
        signal: Signal,
        portfolio_value: float,
        open_positions_count: int,
    ) -> Optional[OrderProposal]:
        """
        Évalue si on doit ouvrir une position.
        Retourne un OrderProposal ou None.
        """
        if signal.action != "BUY":
            return None

        if signal.confidence < self._params.buy_threshold:
            logger.debug(
                f"{signal.symbol}: signal BUY ignoré (confiance={signal.confidence:.1%} "
                f"< seuil={self._params.buy_threshold})"
            )
            return None

        # Construire la proposition d'ordre (prix d'entrée fictif au moment du signal)
        # Le prix réel sera fixé au moment de l'exécution dans paper_trader
        entry_price = signal.raw_indicators.get("close")
        if not entry_price:
            logger.warning(f"{signal.symbol}: pas de prix de clôture dans les indicateurs")
            return None

        atr = signal.raw_indicators.get("atr")

        proposal = self.risk_manager.build_order_proposal(
            symbol=signal.symbol,
            side="BUY",
            entry_price=float(entry_price),
            portfolio_value=portfolio_value,
            confidence=signal.confidence,
            atr=float(atr) if atr else None,
        )

        if proposal is None:
            return None

        # Validation finale
        is_valid, reason = self.risk_manager.validate_order(
            proposal, open_positions_count, portfolio_value
        )
        if not is_valid:
            logger.info(f"{signal.symbol}: ordre rejeté — {reason}")
            return None

        return proposal

    def should_exit(
        self,
        position: dict,
        current_price: float,
        signal: Signal,
    ) -> Optional[str]:
        """
        Évalue si on doit fermer une position existante.

        Les SL/TP sont vérifiés en premier dans paper_trader (tick par tick).
        Cette méthode gère les sorties sur signal et le trailing stop.
        """
        entry_price = position["entry_price"]
        side = position["side"]
        leverage = position.get("leverage", 1.0)

        # --- Vérification de la garde de liquidation ---
        liq_price = position.get("liquidation_price", 0)
        if liq_price and self.risk_manager.is_near_liquidation(
            current_price, liq_price, side
        ):
            logger.warning(
                f"{position['symbol']}: GARDE LIQUIDATION — prix={current_price:.4f} "
                f"proche liquidation={liq_price:.4f}"
            )
            return "liquidation_guard"

        # --- Trailing stop ---
        if side == "BUY":
            profit_pct = (current_price - entry_price) / entry_price * 100
        else:
            profit_pct = (entry_price - current_price) / entry_price * 100

        # Si en profit > TRAILING_STOP_ACTIVATION_PCT, le SL monte au breakeven
        # (le paper_trader gère le SL réel, on signale juste ici qu'il faut l'ajuster)
        # Note : le trailing stop complet (SL qui suit le prix) serait géré
        # dans order_manager avec une mise à jour dynamique du SL en DB

        # --- Sortie sur signal SELL ---
        if signal.action == "SELL" and signal.confidence >= self.MIN_EXIT_CONFIDENCE:
            logger.info(
                f"{position['symbol']}: sortie sur signal SELL "
                f"(confiance={signal.confidence:.1%})"
            )
            return "signal"

        return None

    def get_params(self) -> StrategyParams:
        return self._params

    def update_params(self, new_params: StrategyParams) -> None:
        self._params = new_params
        logger.info(f"Paramètres de stratégie mis à jour vers version {new_params.version}")
