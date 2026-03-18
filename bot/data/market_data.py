"""
Récupération des données de marché depuis Binance (testnet ou production).
Utilise ccxt avec cache SQLite pour limiter les appels API.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import ccxt
import pandas as pd
from loguru import logger

from bot.db.database import Database


# Colonnes standard d'un DataFrame OHLCV
OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

# URLs du testnet Binance Futures
BINANCE_TESTNET_URLS = {
    "api": {
        "public": "https://testnet.binancefuture.com",
        "private": "https://testnet.binancefuture.com",
    },
    "fapiPublic": "https://testnet.binancefuture.com/fapi/v1",
    "fapiPrivate": "https://testnet.binancefuture.com/fapi/v1",
}


def build_exchange(
    api_key: str,
    api_secret: str,
    testnet: bool = True,
) -> ccxt.binance:
    """Crée et configure une instance ccxt.binance (spot ou testnet futures)."""
    params: dict = {
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "options": {
            "defaultType": "future",
            "adjustForTimeDifference": True,
        },
    }
    if testnet:
        params["urls"] = BINANCE_TESTNET_URLS
        params["options"]["testnet"] = True

    exchange = ccxt.binance(params)
    return exchange


class MarketData:
    """Fournit les données de marché avec cache SQLite."""

    # Fraîcheur maximale du cache avant re-fetch (en secondes par timeframe)
    CACHE_TTL: dict[str, int] = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
    }

    def __init__(self, exchange: ccxt.binance, db: Database, timeframe: str = "1h"):
        self.exchange = exchange
        self.db = db
        self.timeframe = timeframe

    # ------------------------------------------------------------------
    # Données OHLCV
    # ------------------------------------------------------------------

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: Optional[str] = None,
        limit: int = 200,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        Retourne un DataFrame OHLCV pour le symbole donné.
        Utilise le cache SQLite si les données sont encore fraîches.
        """
        tf = timeframe or self.timeframe
        ttl = self.CACHE_TTL.get(tf, 3600)

        if not force_refresh:
            cached_df = self._load_from_cache(symbol, tf, limit)
            if cached_df is not None and self._is_cache_fresh(symbol, tf, ttl):
                logger.debug(f"Cache hit pour {symbol}/{tf} ({len(cached_df)} bougies)")
                return cached_df

        # Fetch depuis Binance
        try:
            raw = self._fetch_from_exchange(symbol, tf, limit)
            if raw:
                self.db.upsert_ohlcv(symbol, tf, raw)
                logger.debug(f"Données fraîches pour {symbol}/{tf} ({len(raw)} bougies)")
        except ccxt.NetworkError as e:
            logger.warning(f"Erreur réseau pour {symbol}: {e}. Utilisation du cache.")
        except ccxt.ExchangeError as e:
            logger.error(f"Erreur exchange pour {symbol}: {e}")

        # Toujours retourner depuis le cache (inclut les nouvelles données)
        cached_df = self._load_from_cache(symbol, tf, limit)
        if cached_df is None or cached_df.empty:
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        return cached_df

    def _fetch_from_exchange(
        self, symbol: str, timeframe: str, limit: int
    ) -> list[list]:
        """Appel direct à l'API Binance via ccxt."""
        candles = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return candles

    def _load_from_cache(
        self, symbol: str, timeframe: str, limit: int
    ) -> Optional[pd.DataFrame]:
        rows = self.db.get_ohlcv(symbol, timeframe, limit)
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=OHLCV_COLUMNS)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        return df

    def _is_cache_fresh(self, symbol: str, timeframe: str, ttl: int) -> bool:
        latest_ts = self.db.get_latest_ohlcv_timestamp(symbol, timeframe)
        if latest_ts is None:
            return False
        age_seconds = (time.time() * 1000 - latest_ts) / 1000
        return age_seconds < ttl

    # ------------------------------------------------------------------
    # Prix en temps réel
    # ------------------------------------------------------------------

    def get_ticker(self, symbol: str) -> dict:
        """Retourne le prix actuel (bid/ask/last) pour un symbole."""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return {
                "symbol": symbol,
                "bid": ticker.get("bid") or ticker.get("last"),
                "ask": ticker.get("ask") or ticker.get("last"),
                "last": ticker.get("last"),
                "timestamp": ticker.get("timestamp"),
            }
        except Exception as e:
            logger.error(f"Impossible de récupérer le ticker pour {symbol}: {e}")
            return {"symbol": symbol, "bid": None, "ask": None, "last": None}

    def get_all_tickers(self, symbols: list[str]) -> dict[str, dict]:
        """Récupère les prix pour tous les symboles configurés."""
        result = {}
        for symbol in symbols:
            result[symbol] = self.get_ticker(symbol)
        return result

    # ------------------------------------------------------------------
    # Balance du compte (testnet ou live)
    # ------------------------------------------------------------------

    def get_account_balance(self) -> dict[str, float]:
        """Retourne la balance USDT du compte exchange."""
        try:
            balance = self.exchange.fetch_balance()
            return {
                "USDT": balance.get("USDT", {}).get("free", 0.0),
                "total": balance.get("USDT", {}).get("total", 0.0),
            }
        except Exception as e:
            logger.error(f"Impossible de récupérer la balance: {e}")
            return {"USDT": 0.0, "total": 0.0}

    # ------------------------------------------------------------------
    # Informations sur les symboles
    # ------------------------------------------------------------------

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """Retourne les informations sur un symbole (min qty, price precision, etc.)."""
        try:
            markets = self.exchange.load_markets()
            return markets.get(symbol)
        except Exception as e:
            logger.error(f"Impossible de charger les marchés: {e}")
            return None

    def round_quantity(self, symbol: str, quantity: float) -> float:
        """Arrondit la quantité selon les règles Binance pour ce symbole."""
        try:
            market = self.exchange.market(symbol)
            precision = market.get("precision", {}).get("amount", 8)
            return float(self.exchange.amount_to_precision(symbol, quantity))
        except Exception:
            return round(quantity, 6)

    def round_price(self, symbol: str, price: float) -> float:
        """Arrondit le prix selon les règles Binance pour ce symbole."""
        try:
            return float(self.exchange.price_to_precision(symbol, price))
        except Exception:
            return round(price, 2)
