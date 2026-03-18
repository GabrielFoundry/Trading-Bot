"""
Simulation de trading (paper trading).
Simule les fills sur les prix de marché réels. Aucun ordre envoyé à Binance.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from bot.db.database import Database, TradeRecord
from bot.strategy.risk_manager import OrderProposal
from bot.trading.portfolio import Portfolio, Position


class PaperTrader:
    """
    Exécute des trades simulés en paper trading.
    - Simule le fill au prix de marché actuel + frais
    - Vérifie SL/TP à chaque tick
    - Persiste tout en SQLite via la Database
    """

    def __init__(
        self,
        db: Database,
        portfolio: Portfolio,
        fee_rate: float = 0.001,  # 0.1% Binance taker
    ):
        self.db = db
        self.portfolio = portfolio
        self.fee_rate = fee_rate

    # ------------------------------------------------------------------
    # Ouverture d'une position
    # ------------------------------------------------------------------

    def execute_buy(
        self,
        proposal: OrderProposal,
        current_ask_price: float,
        signal_id: Optional[int] = None,
        strategy_version: int = 1,
    ) -> Optional[dict]:
        """
        Exécute un achat simulé.
        Retourne le trade ouvert ou None si impossible.
        """
        # Vérification de la balance disponible
        required_margin = (proposal.quantity * current_ask_price) / proposal.leverage
        fee = required_margin * self.fee_rate

        if required_margin + fee > self.portfolio.balance:
            logger.warning(
                f"{proposal.symbol}: balance insuffisante "
                f"({required_margin + fee:.2f} > {self.portfolio.balance:.2f} USDT)"
            )
            return None

        trade_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Créer l'enregistrement en DB
        trade = TradeRecord(
            id=trade_id,
            symbol=proposal.symbol,
            side="BUY",
            mode="paper",
            status="open",
            entry_price=current_ask_price,
            quantity=proposal.quantity,
            leverage=proposal.leverage,
            liquidation_price=proposal.liquidation_price,
            stop_loss=proposal.stop_loss,
            take_profit=proposal.take_profit,
            signal_id=signal_id,
            strategy_version=strategy_version,
            opened_at=now,
        )
        self.db.save_trade(trade)

        # Mettre à jour le portfolio en mémoire
        position = Position(
            id=trade_id,
            symbol=proposal.symbol,
            side="BUY",
            mode="paper",
            entry_price=current_ask_price,
            quantity=proposal.quantity,
            leverage=proposal.leverage,
            stop_loss=proposal.stop_loss,
            take_profit=proposal.take_profit,
            liquidation_price=proposal.liquidation_price,
            opened_at=now,
            strategy_version=strategy_version,
            signal_id=signal_id,
            current_price=current_ask_price,
        )
        cost = required_margin + fee
        self.portfolio.add_position(position, cost)

        logger.info(
            f"ACHAT PAPER | {proposal.symbol} | "
            f"prix={current_ask_price:.4f} | qty={proposal.quantity} | "
            f"levier=x{proposal.leverage} | SL={proposal.stop_loss:.4f} | "
            f"TP={proposal.take_profit:.4f} | coût={cost:.2f} USDT"
        )

        return {"id": trade_id, "symbol": proposal.symbol, "entry_price": current_ask_price}

    # ------------------------------------------------------------------
    # Fermeture d'une position
    # ------------------------------------------------------------------

    def execute_close(
        self,
        trade_id: str,
        current_bid_price: float,
        exit_reason: str,
    ) -> Optional[dict]:
        """
        Ferme une position ouverte.
        Retourne les détails du trade clôturé ou None si introuvable.
        """
        position = self.portfolio.get_position(trade_id)
        if not position:
            logger.warning(f"Position {trade_id} introuvable pour clôture")
            return None

        # Calcul du P&L
        if position.side == "BUY":
            gross_pnl = (current_bid_price - position.entry_price) * position.quantity * position.leverage
        else:
            gross_pnl = (position.entry_price - current_bid_price) * position.quantity * position.leverage

        # Frais de sortie (sur la valeur nominale)
        exit_fee = (position.quantity * current_bid_price) / position.leverage * self.fee_rate
        net_pnl = gross_pnl - exit_fee
        pnl_pct = net_pnl / (position.entry_price * position.quantity / position.leverage) * 100

        # Valeur récupérée = marge initiale + P&L net
        initial_margin = (position.entry_price * position.quantity) / position.leverage
        proceeds = initial_margin + net_pnl

        now = datetime.now(timezone.utc).isoformat()

        # Mettre à jour en DB
        self.db.close_trade(
            trade_id=trade_id,
            exit_price=current_bid_price,
            pnl_usdt=round(net_pnl, 6),
            pnl_pct=round(pnl_pct, 4),
            fee_usdt=round(exit_fee, 6),
            exit_reason=exit_reason,
            closed_at=now,
        )

        # Mettre à jour le portfolio
        self.portfolio.close_position(trade_id, max(proceeds, 0.0), net_pnl)

        emoji = "✓" if net_pnl >= 0 else "✗"
        logger.info(
            f"{emoji} CLÔTURE PAPER | {position.symbol} | "
            f"raison={exit_reason} | exit={current_bid_price:.4f} | "
            f"P&L={net_pnl:+.4f} USDT ({pnl_pct:+.2f}%)"
        )

        return {
            "id": trade_id,
            "symbol": position.symbol,
            "exit_price": current_bid_price,
            "pnl_usdt": net_pnl,
            "pnl_pct": pnl_pct,
            "exit_reason": exit_reason,
        }

    # ------------------------------------------------------------------
    # Vérification SL/TP sur toutes les positions ouvertes
    # ------------------------------------------------------------------

    def check_stop_loss_take_profit(
        self, current_prices: dict[str, float]
    ) -> list[dict]:
        """
        Vérifie si des positions ont atteint leur SL ou TP.
        Appeler à chaque tick de prix.
        Retourne la liste des trades fermés.
        """
        closed_trades = []

        for position in list(self.portfolio.positions):
            symbol = position.symbol
            price = current_prices.get(symbol)
            if not price:
                continue

            exit_reason = None

            if position.side == "BUY":
                if price <= position.stop_loss:
                    exit_reason = "stop_loss"
                elif price >= position.take_profit:
                    exit_reason = "take_profit"
            else:
                if price >= position.stop_loss:
                    exit_reason = "stop_loss"
                elif price <= position.take_profit:
                    exit_reason = "take_profit"

            if exit_reason:
                result = self.execute_close(position.id, price, exit_reason)
                if result:
                    closed_trades.append(result)

        return closed_trades

    def update_trailing_stop(
        self,
        trade_id: str,
        new_stop_loss: float,
    ) -> None:
        """Met à jour le stop-loss d'une position (trailing stop)."""
        position = self.portfolio.get_position(trade_id)
        if not position:
            return

        old_sl = position.stop_loss
        position.stop_loss = new_stop_loss

        # Mise à jour en DB (requête directe)
        with self.db._conn() as conn:
            conn.execute(
                "UPDATE trades SET stop_loss=? WHERE id=?",
                (new_stop_loss, trade_id),
            )

        logger.debug(
            f"Trailing stop mis à jour : {position.symbol} "
            f"SL {old_sl:.4f} → {new_stop_loss:.4f}"
        )
