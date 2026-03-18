"""
Calcul des indicateurs techniques sur un DataFrame OHLCV.
Fonction pure : même entrée → même sortie. Pas d'état interne.
"""

from __future__ import annotations

import pandas as pd
import ta
from loguru import logger

from bot.db.database import StrategyParams


def add_all_indicators(df: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    """
    Ajoute tous les indicateurs techniques à un DataFrame OHLCV.

    Colonnes ajoutées :
    - rsi : RSI(period)
    - macd, macd_signal, macd_hist : MACD
    - bb_upper, bb_middle, bb_lower : Bandes de Bollinger
    - bb_pct : Position relative dans les BB (0=lower, 1=upper)
    - ema_fast, ema_slow : EMA rapide et lente
    - sma_20 : Moyenne mobile simple 20 périodes
    - atr : Average True Range
    - volume_sma : SMA du volume (20 périodes)
    - volume_ratio : Volume actuel / volume_sma
    """
    if df.empty or len(df) < max(params.macd_slow + params.macd_signal, params.bb_period, 30):
        logger.warning("Pas assez de données pour calculer les indicateurs")
        return df

    df = df.copy()

    # --- RSI ---
    df["rsi"] = ta.momentum.RSIIndicator(
        close=df["close"], window=params.rsi_period
    ).rsi()

    # --- MACD ---
    macd_indicator = ta.trend.MACD(
        close=df["close"],
        window_fast=params.macd_fast,
        window_slow=params.macd_slow,
        window_sign=params.macd_signal,
    )
    df["macd"] = macd_indicator.macd()
    df["macd_signal"] = macd_indicator.macd_signal()
    df["macd_hist"] = macd_indicator.macd_diff()

    # --- Bandes de Bollinger ---
    bb = ta.volatility.BollingerBands(
        close=df["close"],
        window=params.bb_period,
        window_dev=params.bb_std,
    )
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_pct"] = bb.bollinger_pband()  # 0 = near lower, 1 = near upper

    # --- EMA ---
    df["ema_fast"] = ta.trend.EMAIndicator(
        close=df["close"], window=params.ema_fast
    ).ema_indicator()
    df["ema_slow"] = ta.trend.EMAIndicator(
        close=df["close"], window=params.ema_slow
    ).ema_indicator()
    df["sma_20"] = ta.trend.SMAIndicator(
        close=df["close"], window=20
    ).sma_indicator()

    # --- ATR (Average True Range) ---
    df["atr"] = ta.volatility.AverageTrueRange(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=14,
    ).average_true_range()

    # --- Volume ---
    df["volume_sma"] = df["volume"].rolling(window=20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_sma"].replace(0, float("nan"))

    # --- Croisements (calculés sur 2 dernières bougies) ---
    df["ema_cross_up"] = (df["ema_fast"] > df["ema_slow"]) & (
        df["ema_fast"].shift(1) <= df["ema_slow"].shift(1)
    )
    df["ema_cross_down"] = (df["ema_fast"] < df["ema_slow"]) & (
        df["ema_fast"].shift(1) >= df["ema_slow"].shift(1)
    )
    df["macd_cross_up"] = (df["macd"] > df["macd_signal"]) & (
        df["macd"].shift(1) <= df["macd_signal"].shift(1)
    )
    df["macd_cross_down"] = (df["macd"] < df["macd_signal"]) & (
        df["macd"].shift(1) >= df["macd_signal"].shift(1)
    )

    return df


def get_latest_row(df: pd.DataFrame) -> pd.Series:
    """Retourne la dernière ligne du DataFrame (bougie la plus récente)."""
    if df.empty:
        return pd.Series(dtype=float)
    return df.iloc[-1]


def extract_indicators_dict(row: pd.Series) -> dict:
    """Extrait les indicateurs d'une ligne en dict sérialisable (pour sauvegarde en DB)."""
    fields = [
        "rsi", "macd", "macd_signal", "macd_hist",
        "bb_upper", "bb_middle", "bb_lower", "bb_pct",
        "ema_fast", "ema_slow", "sma_20", "atr",
        "volume_ratio", "close", "volume",
    ]
    result = {}
    for f in fields:
        val = row.get(f)
        if val is not None and not (isinstance(val, float) and (val != val)):  # NaN check
            result[f] = round(float(val), 6)
    return result


def is_volume_confirming(row: pd.Series, threshold_mult: float) -> bool:
    """Vérifie si le volume est au-dessus du seuil de confirmation."""
    ratio = row.get("volume_ratio")
    if ratio is None or (isinstance(ratio, float) and ratio != ratio):
        return False
    return float(ratio) >= threshold_mult
