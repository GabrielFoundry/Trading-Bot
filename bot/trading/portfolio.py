"""
Gestion de l'état du portfolio (balance, positions ouvertes, P&L).
Backed par SQLite — état cohérent même après redémarrage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from bot.db.database import Database


@dataclass
class Position:
    id: str
    symbol: str
    side: str
    mode: str
    entry_price: float
    quantity: float
    leverage: float
    stop_loss: float
    take_profit: float
    opened_at: str
    strategy_version: int
    liquidation_price: float = 0.0
    signal_id: Optional[int] = None
    current_price: float = 0.0  # Mis à jour en temps réel

    @property
    def unrealized_pnl_usdt(self) -> float:
        if self.current_price <= 0:
            return 0.0
        if self.side == "BUY":
            return (self.current_price - self.entry_price) * self.quantity * self.leverage
        else:
            return (self.entry_price - self.current_price) * self.quantity * self.leverage

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        if self.side == "BUY":
            return (self.current_price - self.entry_price) / self.entry_price * 100 * self.leverage
        else:
            return (self.entry_price - self.current_price) / self.entry_price * 100 * self.leverage

    @property
    def time_open_hours(self) -> float:
        try:
            opened = datetime.fromisoformat(self.opened_at)
            now = datetime.now(timezone.utc)
            if opened.tzinfo is None:
                opened = opened.replace(tzinfo=timezone.utc)
            return (now - opened).total_seconds() / 3600
        except Exception:
            return 0.0


@dataclass
class PortfolioSnapshot:
    usdt_balance: float
    positions: list[Position] = field(default_factory=list)

    @property
    def positions_value(self) -> float:
        """Valeur mark-to-market des positions ouvertes."""
        return sum(
            p.quantity * p.current_price / p.leverage
            for p in self.positions
            if p.current_price > 0
        )

    @property
    def total_value(self) -> float:
        return self.usdt_balance + self.positions_value

    @property
    def unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl_usdt for p in self.positions)

    @property
    def open_positions_count(self) -> int:
        return len(self.positions)


class Portfolio:
    """
    Maintient l'état en mémoire du portfolio, synchronisé avec la DB.
    """

    def __init__(self, db: Database, initial_balance: float = 300.0, mode: str = "paper"):
        self.db = db
        self.mode = mode
        self._balance = initial_balance
        self._positions: dict[str, Position] = {}  # trade_id → Position
        self._realized_pnl = 0.0
        self._reload()

    def _reload(self) -> None:
        """Charge l'état depuis la DB (utilisé au démarrage)."""
        state = self.db.get_bot_state()
        self._balance = state.paper_balance

        open_trades = self.db.get_open_trades()
        self._positions = {}
        for trade in open_trades:
            pos = Position(
                id=trade["id"],
                symbol=trade["symbol"],
                side=trade["side"],
                mode=trade["mode"],
                entry_price=trade["entry_price"],
                quantity=trade["quantity"],
                leverage=trade["leverage"],
                stop_loss=trade["stop_loss"],
                take_profit=trade["take_profit"],
                liquidation_price=trade.get("liquidation_price", 0.0),
                opened_at=trade["opened_at"],
                strategy_version=trade["strategy_version"],
                signal_id=trade.get("signal_id"),
            )
            self._positions[trade["id"]] = pos

        logger.info(
            f"Portfolio rechargé : balance={self._balance:.2f} USDT, "
            f"positions={len(self._positions)}"
        )

    @property
    def balance(self) -> float:
        return self._balance

    @property
    def positions(self) -> list[Position]:
        return list(self._positions.values())

    @property
    def open_positions_count(self) -> int:
        return len(self._positions)

    def get_position(self, trade_id: str) -> Optional[Position]:
        return self._positions.get(trade_id)

    def update_prices(self, prices: dict[str, float]) -> None:
        """Met à jour les prix courants de toutes les positions ouvertes."""
        for pos in self._positions.values():
            symbol = pos.symbol
            if symbol in prices:
                pos.current_price = prices[symbol]

    def get_snapshot(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            usdt_balance=self._balance,
            positions=list(self._positions.values()),
        )

    def add_position(self, position: Position, cost_usdt: float) -> None:
        """Ajoute une nouvelle position et déduit le coût de la balance."""
        self._positions[position.id] = position
        self._balance -= cost_usdt
        self.db.update_paper_balance(self._balance)
        logger.info(
            f"Position ouverte : {position.symbol} {position.side} "
            f"x{position.leverage} | coût={cost_usdt:.2f} USDT | "
            f"balance restante={self._balance:.2f} USDT"
        )

    def close_position(self, trade_id: str, proceeds_usdt: float, pnl_usdt: float) -> None:
        """Ferme une position et crédite les fonds sur la balance."""
        if trade_id not in self._positions:
            logger.warning(f"Position {trade_id} introuvable lors de la clôture")
            return

        pos = self._positions.pop(trade_id)
        self._balance += proceeds_usdt
        self._realized_pnl += pnl_usdt
        self.db.update_paper_balance(self._balance)

        logger.info(
            f"Position fermée : {pos.symbol} | P&L={pnl_usdt:+.2f} USDT | "
            f"balance={self._balance:.2f} USDT"
        )

    def get_realized_pnl(self) -> float:
        return self._realized_pnl

    def to_dict(self) -> dict:
        """Sérialise l'état du portfolio pour l'API/dashboard."""
        snapshot = self.get_snapshot()
        return {
            "usdt_balance": round(self._balance, 4),
            "positions_value": round(snapshot.positions_value, 4),
            "total_value": round(snapshot.total_value, 4),
            "unrealized_pnl": round(snapshot.unrealized_pnl, 4),
            "realized_pnl": round(self._realized_pnl, 4),
            "open_positions_count": snapshot.open_positions_count,
            "positions": [
                {
                    "id": p.id,
                    "symbol": p.symbol,
                    "side": p.side,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "quantity": p.quantity,
                    "leverage": p.leverage,
                    "stop_loss": p.stop_loss,
                    "take_profit": p.take_profit,
                    "liquidation_price": p.liquidation_price,
                    "unrealized_pnl_usdt": round(p.unrealized_pnl_usdt, 4),
                    "unrealized_pnl_pct": round(p.unrealized_pnl_pct, 2),
                    "time_open_hours": round(p.time_open_hours, 1),
                }
                for p in self._positions.values()
            ],
        }
