"""
Moteur d'agrégation des signaux.
Combine analyse technique + fondamentale → Signal(action, confidence, reasons).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

import pandas as pd
from loguru import logger

from bot.analysis.fundamental import FundamentalSignal
from bot.analysis.technical import (
    add_all_indicators,
    extract_indicators_dict,
    get_latest_row,
    is_volume_confirming,
)
from bot.db.database import SignalRecord, StrategyParams


ActionType = Literal["BUY", "SELL", "HOLD"]


@dataclass
class Signal:
    symbol: str
    timestamp: str
    action: ActionType
    confidence: float            # 0.0 - 1.0
    technical_score: float       # -1.0 à +1.0
    fundamental_score: float     # -1.0 à +1.0
    combined_score: float        # Score final pondéré
    reasons: list[str] = field(default_factory=list)
    raw_indicators: dict = field(default_factory=dict)
    strategy_version: int = 1

    def to_record(self) -> SignalRecord:
        return SignalRecord(
            id=None,
            symbol=self.symbol,
            timestamp=self.timestamp,
            action=self.action,
            confidence=self.confidence,
            technical_score=self.technical_score,
            fundamental_score=self.fundamental_score,
            combined_score=self.combined_score,
            reasons=self.reasons,
            raw_indicators=self.raw_indicators,
            strategy_version=self.strategy_version,
        )


class SignalGenerator:
    """
    Génère des signaux de trading en combinant indicateurs techniques et fondamentaux.
    Chaque signal inclut les raisons en langage naturel pour le dashboard.
    """

    def generate(
        self,
        symbol: str,
        df: pd.DataFrame,
        params: StrategyParams,
        fundamental: Optional[FundamentalSignal] = None,
        strategy_version: int = 1,
    ) -> Signal:
        """
        Génère un signal pour un symbole donné.

        Args:
            symbol: Ex. "BTC/USDT"
            df: DataFrame OHLCV (sans indicateurs — ajoutés ici)
            params: Paramètres de stratégie actifs
            fundamental: Signal fondamental pré-calculé (optionnel)
            strategy_version: Version de stratégie pour traçabilité
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        if df.empty or len(df) < 30:
            logger.warning(f"{symbol}: pas assez de données pour générer un signal")
            return Signal(
                symbol=symbol,
                timestamp=timestamp,
                action="HOLD",
                confidence=0.0,
                technical_score=0.0,
                fundamental_score=0.0,
                combined_score=0.0,
                reasons=["Données insuffisantes"],
                strategy_version=strategy_version,
            )

        # Ajouter les indicateurs
        df_with_indicators = add_all_indicators(df, params)
        row = get_latest_row(df_with_indicators)
        prev_row = df_with_indicators.iloc[-2] if len(df_with_indicators) >= 2 else row

        if row.empty:
            return Signal(
                symbol=symbol, timestamp=timestamp, action="HOLD",
                confidence=0.0, technical_score=0.0, fundamental_score=0.0,
                combined_score=0.0, reasons=["Erreur de calcul des indicateurs"],
                strategy_version=strategy_version,
            )

        # --- Calcul du score technique ---
        technical_score, reasons = self._calc_technical_score(row, prev_row, params)

        # --- Score fondamental ---
        fundamental_score = 0.0
        if fundamental:
            fundamental_score = fundamental.score
            if fundamental.label != "neutral":
                reasons.append(
                    f"Fondamental {fundamental.label} "
                    f"(F&G: {fundamental.fear_greed_value or 'N/A'}, "
                    f"News: {fundamental.news_count} articles)"
                )

        # --- Score combiné pondéré ---
        sentiment_weight = params.sentiment_weight
        combined_score = (
            technical_score * (1.0 - sentiment_weight)
            + fundamental_score * sentiment_weight
        )
        combined_score = max(-1.0, min(1.0, combined_score))

        # --- Décision d'action ---
        action, confidence = self._decide_action(combined_score, params)

        # --- Indicateurs bruts pour sauvegarde ---
        raw_indicators = extract_indicators_dict(row)
        if fundamental:
            raw_indicators["fundamental"] = fundamental.components

        signal = Signal(
            symbol=symbol,
            timestamp=timestamp,
            action=action,
            confidence=round(confidence, 4),
            technical_score=round(technical_score, 4),
            fundamental_score=round(fundamental_score, 4),
            combined_score=round(combined_score, 4),
            reasons=reasons,
            raw_indicators=raw_indicators,
            strategy_version=strategy_version,
        )

        logger.info(
            f"{symbol} | {action} | confiance={confidence:.1%} | "
            f"score_tech={technical_score:.3f} | score_fund={fundamental_score:.3f} | "
            f"score_final={combined_score:.3f}"
        )
        return signal

    def _calc_technical_score(
        self,
        row: pd.Series,
        prev_row: pd.Series,
        params: StrategyParams,
    ) -> tuple[float, list[str]]:
        """
        Calcule le score technique en évaluant chaque indicateur.
        Retourne (score, liste_de_raisons).
        """
        score = 0.0
        reasons = []

        close = _safe_float(row, "close")
        rsi = _safe_float(row, "rsi")
        prev_rsi = _safe_float(prev_row, "rsi")
        macd = _safe_float(row, "macd")
        macd_sig = _safe_float(row, "macd_signal")
        bb_pct = _safe_float(row, "bb_pct")
        bb_lower = _safe_float(row, "bb_lower")
        bb_upper = _safe_float(row, "bb_upper")
        ema_cross_up = bool(row.get("ema_cross_up", False))
        ema_cross_down = bool(row.get("ema_cross_down", False))
        macd_cross_up = bool(row.get("macd_cross_up", False))
        macd_cross_down = bool(row.get("macd_cross_down", False))

        # --- RSI : +0.3 si oversold en remontée, -0.3 si overbought en baisse ---
        if rsi is not None and prev_rsi is not None:
            if rsi < params.rsi_oversold and rsi > prev_rsi:
                score += 0.30
                reasons.append(f"RSI survendu en remontée ({rsi:.1f})")
            elif rsi > params.rsi_overbought and rsi < prev_rsi:
                score -= 0.30
                reasons.append(f"RSI suracheté en baisse ({rsi:.1f})")
            elif rsi < params.rsi_oversold:
                score += 0.15
                reasons.append(f"RSI survendu ({rsi:.1f})")
            elif rsi > params.rsi_overbought:
                score -= 0.15
                reasons.append(f"RSI suracheté ({rsi:.1f})")

        # --- MACD : croisements ---
        if macd_cross_up:
            score += 0.25
            reasons.append("MACD croisement haussier")
        elif macd_cross_down:
            score -= 0.25
            reasons.append("MACD croisement baissier")
        elif macd is not None and macd_sig is not None:
            if macd > macd_sig:
                score += 0.08
            elif macd < macd_sig:
                score -= 0.08

        # --- Bandes de Bollinger : mean reversion ---
        if bb_pct is not None:
            if bb_pct < 0.05:
                score += 0.20
                reasons.append(f"Prix proche de la BB basse (BB%: {bb_pct:.2%})")
            elif bb_pct > 0.95:
                score -= 0.20
                reasons.append(f"Prix proche de la BB haute (BB%: {bb_pct:.2%})")
            elif bb_pct < 0.2:
                score += 0.08
            elif bb_pct > 0.8:
                score -= 0.08

        # --- EMA : croisements ---
        if ema_cross_up:
            score += 0.15
            reasons.append("EMA croisement haussier (tendance up)")
        elif ema_cross_down:
            score -= 0.15
            reasons.append("EMA croisement baissier (tendance down)")

        # --- Volume : confirmation ---
        if is_volume_confirming(row, params.volume_threshold_mult):
            # Le volume amplifie le signal existant (×1.2)
            score *= 1.20
            if abs(score) > 0.15:
                reasons.append(
                    f"Volume élevé confirme le signal "
                    f"({_safe_float(row, 'volume_ratio'):.1f}× moyenne)"
                )

        # Clamp
        score = max(-1.0, min(1.0, score))
        return score, reasons

    @staticmethod
    def _decide_action(
        combined_score: float, params: StrategyParams
    ) -> tuple[ActionType, float]:
        """Convertit le score en action + confidence."""
        if combined_score >= params.buy_threshold:
            confidence = min(combined_score / max(params.buy_threshold, 1e-9), 1.0)
            return "BUY", confidence
        elif combined_score <= params.sell_threshold:
            confidence = min(abs(combined_score) / max(abs(params.sell_threshold), 1e-9), 1.0)
            return "SELL", confidence
        else:
            # HOLD — confidence = distance aux seuils (faible = proche d'une décision)
            dist_to_buy = params.buy_threshold - combined_score
            dist_to_sell = combined_score - params.sell_threshold
            confidence = 1.0 - min(dist_to_buy, dist_to_sell) / max(
                params.buy_threshold, abs(params.sell_threshold)
            )
            return "HOLD", max(0.0, confidence)


def _safe_float(row: pd.Series, key: str) -> Optional[float]:
    """Extrait un float d'une Series en gérant NaN."""
    val = row.get(key)
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None
