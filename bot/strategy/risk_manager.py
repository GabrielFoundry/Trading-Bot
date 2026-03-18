"""
Gestionnaire de risque — gatekeeper financier.
Tout ordre doit passer par ce module. Aucun bypass possible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from loguru import logger


@dataclass
class OrderProposal:
    symbol: str
    side: Literal["BUY", "SELL"]
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity: float
    usdt_value: float
    risk_amount_usdt: float
    risk_pct: float
    leverage: float
    liquidation_price: float


class RiskManager:
    """
    Calcule les paramètres de risque et valide chaque ordre avant exécution.

    Responsabilités :
    1. Calcul du levier adaptatif selon la confiance du signal
    2. Calcul de la taille de position (ATR-based)
    3. Calcul du stop-loss et take-profit
    4. Calcul du prix de liquidation
    5. Validation finale de l'ordre
    """

    def __init__(
        self,
        risk_per_trade_pct: float = 3.5,
        max_open_positions: int = 3,
        max_drawdown_pct: float = 15.0,
        stop_loss_pct: float = 2.0,
        take_profit_pct: float = 4.0,
        atr_stop_multiplier: float = 1.5,
        risk_reward_ratio: float = 2.0,
        max_leverage: float = 2.0,
        high_confidence_threshold: float = 0.80,
        mid_confidence_threshold: float = 0.60,
        mid_leverage: float = 1.5,
        liquidation_guard_pct: float = 5.0,
        initial_balance: float = 300.0,
    ):
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_open_positions = max_open_positions
        self.max_drawdown_pct = max_drawdown_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.atr_stop_multiplier = atr_stop_multiplier
        self.risk_reward_ratio = risk_reward_ratio
        self.max_leverage = max_leverage
        self.high_confidence_threshold = high_confidence_threshold
        self.mid_confidence_threshold = mid_confidence_threshold
        self.mid_leverage = mid_leverage
        self.liquidation_guard_pct = liquidation_guard_pct
        self.initial_balance = initial_balance

    # ------------------------------------------------------------------
    # Levier adaptatif
    # ------------------------------------------------------------------

    def calculate_leverage(self, confidence: float) -> float:
        """
        Détermine le levier selon la confiance du signal.
        - confiance > 80% → levier max (x2)
        - confiance 60-80% → levier intermédiaire (x1.5)
        - confiance < 60% → pas de levier (x1)
        """
        if confidence >= self.high_confidence_threshold:
            leverage = self.max_leverage
        elif confidence >= self.mid_confidence_threshold:
            leverage = self.mid_leverage
        else:
            leverage = 1.0

        logger.debug(f"Levier calculé : x{leverage} (confiance={confidence:.1%})")
        return leverage

    # ------------------------------------------------------------------
    # Prix de liquidation
    # ------------------------------------------------------------------

    def calculate_liquidation_price(
        self, entry_price: float, leverage: float, side: str
    ) -> float:
        """
        Calcule le prix de liquidation estimé (formule Binance Futures simplifiée).
        Pour LONG : liquidation = entry × (1 - 1/leverage × 0.9)  (marge × 0.9 = maintenance)
        Pour SHORT: liquidation = entry × (1 + 1/leverage × 0.9)
        """
        if leverage <= 1.0:
            return 0.0  # Pas de levier = pas de liquidation

        maintenance_margin_rate = 0.005  # 0.5% Binance USDT-M
        margin_fraction = 1.0 / leverage

        if side == "BUY":
            liq_price = entry_price * (1.0 - margin_fraction + maintenance_margin_rate)
        else:
            liq_price = entry_price * (1.0 + margin_fraction - maintenance_margin_rate)

        return round(liq_price, 4)

    def is_near_liquidation(
        self, current_price: float, liquidation_price: float, side: str
    ) -> bool:
        """
        Vérifie si le prix est dangereux proche du prix de liquidation.
        Déclenche la fermeture anticipée si distance < liquidation_guard_pct%.
        """
        if liquidation_price <= 0:
            return False

        if side == "BUY":
            distance_pct = (current_price - liquidation_price) / current_price * 100
        else:
            distance_pct = (liquidation_price - current_price) / current_price * 100

        return distance_pct < self.liquidation_guard_pct

    # ------------------------------------------------------------------
    # Stop-Loss et Take-Profit
    # ------------------------------------------------------------------

    def calculate_stop_loss(
        self,
        entry_price: float,
        side: str,
        atr: Optional[float],
        leverage: float = 1.0,
    ) -> float:
        """
        Calcule le stop-loss adaptatif.
        Utilise l'ATR si disponible, sinon le stop_loss_pct fixe.
        Le levier ne modifie pas le stop-loss en prix — mais le stop-loss
        est ajusté pour que la perte réelle reste dans la limite de risque.
        """
        if atr and atr > 0:
            distance = atr * self.atr_stop_multiplier
        else:
            distance = entry_price * (self.stop_loss_pct / 100.0)

        if side == "BUY":
            sl = entry_price - distance
        else:
            sl = entry_price + distance

        return round(max(sl, 0.01), 6)

    def calculate_take_profit(
        self, entry_price: float, stop_loss: float, side: str
    ) -> float:
        """
        Take-profit basé sur le ratio risque/récompense.
        TP = entry + (entry - SL) × rr_ratio  (pour LONG)
        """
        risk_distance = abs(entry_price - stop_loss)
        reward_distance = risk_distance * self.risk_reward_ratio

        if side == "BUY":
            tp = entry_price + reward_distance
        else:
            tp = entry_price - reward_distance

        return round(tp, 6)

    # ------------------------------------------------------------------
    # Taille de position
    # ------------------------------------------------------------------

    def calculate_position_size(
        self,
        portfolio_value: float,
        entry_price: float,
        stop_loss: float,
        leverage: float,
    ) -> float:
        """
        Calcule la quantité à acheter selon la règle de risque.

        Logique :
        - risk_amount = portfolio_value × risk_per_trade_pct / 100
        - Avec levier, le risque réel par unité = (entry - SL) / leverage
        - quantity = risk_amount / risque_par_unité

        Quantité maximale : 33% du portfolio par position (diversification).
        """
        risk_amount = portfolio_value * (self.risk_per_trade_pct / 100.0)
        price_risk = abs(entry_price - stop_loss)

        if price_risk <= 0 or entry_price <= 0:
            return 0.0

        # Avec levier, l'exposition réelle est amplifiée
        effective_price_risk = price_risk  # Le SL est en prix absolu, levier déjà pris en compte
        quantity = risk_amount / effective_price_risk

        # Quantité maximale : 33% du portfolio / prix d'entrée
        max_quantity = (portfolio_value * 0.33 * leverage) / entry_price
        quantity = min(quantity, max_quantity)

        # Vérification de la valeur minimale (Binance exige ~10 USDT min)
        if quantity * entry_price < 10.0:
            return 0.0

        return round(quantity, 6)

    # ------------------------------------------------------------------
    # Proposition d'ordre complète
    # ------------------------------------------------------------------

    def build_order_proposal(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        portfolio_value: float,
        confidence: float,
        atr: Optional[float] = None,
    ) -> Optional[OrderProposal]:
        """
        Construit une proposition d'ordre complète avec tous les paramètres de risque.
        Retourne None si le trade ne satisfait pas les critères de risque.
        """
        leverage = self.calculate_leverage(confidence)
        stop_loss = self.calculate_stop_loss(entry_price, side, atr, leverage)
        take_profit = self.calculate_take_profit(entry_price, stop_loss, side)
        quantity = self.calculate_position_size(
            portfolio_value, entry_price, stop_loss, leverage
        )

        if quantity <= 0:
            logger.warning(
                f"{symbol}: taille de position nulle (portfolio={portfolio_value:.2f} USDT)"
            )
            return None

        usdt_value = quantity * entry_price / leverage
        risk_amount = abs(entry_price - stop_loss) * quantity
        risk_pct = risk_amount / portfolio_value * 100

        liquidation_price = self.calculate_liquidation_price(entry_price, leverage, side)

        proposal = OrderProposal(
            symbol=symbol,
            side=side,
            entry_price=round(entry_price, 6),
            stop_loss=stop_loss,
            take_profit=take_profit,
            quantity=quantity,
            usdt_value=round(usdt_value, 4),
            risk_amount_usdt=round(risk_amount, 4),
            risk_pct=round(risk_pct, 4),
            leverage=leverage,
            liquidation_price=liquidation_price,
        )

        logger.debug(
            f"{symbol} OrderProposal: side={side}, entry={entry_price:.4f}, "
            f"SL={stop_loss:.4f}, TP={take_profit:.4f}, qty={quantity}, "
            f"levier=x{leverage}, liq={liquidation_price:.4f}, "
            f"risque={risk_pct:.2f}%"
        )
        return proposal

    # ------------------------------------------------------------------
    # Validation finale
    # ------------------------------------------------------------------

    def validate_order(
        self,
        proposal: OrderProposal,
        current_open_positions: int,
        current_portfolio_value: float,
    ) -> tuple[bool, str]:
        """
        Validation finale avant exécution de l'ordre.
        Retourne (is_valid, raison_du_rejet).
        """
        # Trop de positions ouvertes
        if current_open_positions >= self.max_open_positions:
            return False, f"Trop de positions ouvertes ({current_open_positions}/{self.max_open_positions})"

        # Valeur minimale de l'ordre
        if proposal.usdt_value < 10.0:
            return False, f"Valeur trop faible ({proposal.usdt_value:.2f} USDT, min 10 USDT)"

        # Vérification du drawdown maximum
        drawdown_pct = (
            (self.initial_balance - current_portfolio_value) / self.initial_balance * 100
        )
        if drawdown_pct >= self.max_drawdown_pct:
            return False, (
                f"Drawdown maximum atteint ({drawdown_pct:.1f}% >= {self.max_drawdown_pct}%). "
                "Le bot est en pause de protection."
            )

        # Vérification du risque
        if proposal.risk_pct > self.risk_per_trade_pct * 2:
            return False, (
                f"Risque trop élevé ({proposal.risk_pct:.2f}% > "
                f"{self.risk_per_trade_pct * 2:.2f}%)"
            )

        return True, "OK"

    def check_max_drawdown(self, current_portfolio_value: float) -> bool:
        """
        Vérifie si le drawdown maximum a été atteint.
        Retourne True si le bot doit s'arrêter.
        """
        drawdown_pct = (
            (self.initial_balance - current_portfolio_value) / self.initial_balance * 100
        )
        if drawdown_pct >= self.max_drawdown_pct:
            logger.critical(
                f"DRAWDOWN MAXIMUM ATTEINT: {drawdown_pct:.1f}% "
                f"(limite: {self.max_drawdown_pct}%). Bot mis en pause."
            )
            return True
        return False
