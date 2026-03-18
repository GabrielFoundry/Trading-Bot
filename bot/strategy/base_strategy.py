"""
Classe de base abstraite pour toutes les stratégies de trading.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from bot.analysis.signals import Signal
from bot.db.database import StrategyParams
from bot.strategy.risk_manager import OrderProposal


class BaseStrategy(ABC):
    """Interface que toute stratégie concrète doit implémenter."""

    @abstractmethod
    def should_enter(
        self,
        signal: Signal,
        portfolio_value: float,
        open_positions_count: int,
    ) -> Optional[OrderProposal]:
        """
        Évalue si une nouvelle position doit être ouverte.
        Retourne un OrderProposal ou None si on ne doit pas entrer.
        """
        ...

    @abstractmethod
    def should_exit(
        self,
        position: dict,
        current_price: float,
        signal: Signal,
    ) -> Optional[str]:
        """
        Évalue si une position existante doit être fermée.
        Retourne la raison de sortie ('stop_loss', 'take_profit', 'signal', etc.)
        ou None si on garde la position.
        """
        ...

    @abstractmethod
    def get_params(self) -> StrategyParams:
        """Retourne les paramètres actuels de la stratégie."""
        ...

    @abstractmethod
    def update_params(self, new_params: StrategyParams) -> None:
        """Met à jour les paramètres de la stratégie."""
        ...
