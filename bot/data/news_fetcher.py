"""
Récupération des actualités crypto depuis CryptoPanic et NewsAPI.
Cache dans SQLite pour respecter les limites des API gratuites.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests
from loguru import logger

from bot.db.database import Database

# Timeout des requêtes HTTP
HTTP_TIMEOUT = 10


@dataclass
class NewsItem:
    title: str
    published_at: str
    source: str
    url: str
    body: str = ""
    currencies: list[str] = field(default_factory=list)
    sentiment_score: Optional[float] = None
    sentiment_label: Optional[str] = None

    def to_db_dict(self) -> dict:
        return {
            "title": self.title,
            "body": self.body,
            "source": self.source,
            "url": self.url,
            "published_at": self.published_at,
            "currencies": json.dumps(self.currencies),
            "sentiment_score": self.sentiment_score,
            "sentiment_label": self.sentiment_label,
        }


class CryptoPanicFetcher:
    """Récupère les news depuis l'API CryptoPanic (tier gratuit)."""

    BASE_URL = "https://cryptopanic.com/api/v1/posts/"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch(self, currencies: Optional[list[str]] = None, limit: int = 20) -> list[NewsItem]:
        if not self.api_key:
            return []

        params: dict = {
            "auth_token": self.api_key,
            "public": "true",
            "kind": "news",
        }
        if currencies:
            params["currencies"] = ",".join(currencies)

        try:
            response = requests.get(self.BASE_URL, params=params, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            items = []
            for post in data.get("results", [])[:limit]:
                currencies_list = [
                    c.get("code", "") for c in post.get("currencies", [])
                ]
                items.append(
                    NewsItem(
                        title=post.get("title", ""),
                        published_at=post.get("published_at", datetime.now(timezone.utc).isoformat()),
                        source=post.get("source", {}).get("title", "CryptoPanic"),
                        url=post.get("url", ""),
                        currencies=currencies_list,
                    )
                )
            logger.debug(f"CryptoPanic: {len(items)} articles récupérés")
            return items
        except requests.exceptions.RequestException as e:
            logger.warning(f"CryptoPanic fetch échoué: {e}")
            return []


class NewsAPIFetcher:
    """Récupère les news crypto depuis NewsAPI (tier gratuit)."""

    BASE_URL = "https://newsapi.org/v2/everything"

    CRYPTO_KEYWORDS = "bitcoin OR ethereum OR cryptocurrency OR crypto OR BTC OR ETH"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch(self, limit: int = 20) -> list[NewsItem]:
        if not self.api_key:
            return []

        params = {
            "q": self.CRYPTO_KEYWORDS,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": min(limit, 100),
            "apiKey": self.api_key,
        }

        try:
            response = requests.get(self.BASE_URL, params=params, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            items = []
            for article in data.get("articles", []):
                if not article.get("url"):
                    continue
                items.append(
                    NewsItem(
                        title=article.get("title", ""),
                        body=article.get("description", ""),
                        published_at=article.get("publishedAt", datetime.now(timezone.utc).isoformat()),
                        source=article.get("source", {}).get("name", "NewsAPI"),
                        url=article.get("url", ""),
                        currencies=self._extract_currencies(
                            article.get("title", "") + " " + article.get("description", "")
                        ),
                    )
                )
            logger.debug(f"NewsAPI: {len(items)} articles récupérés")
            return items
        except requests.exceptions.RequestException as e:
            logger.warning(f"NewsAPI fetch échoué: {e}")
            return []

    @staticmethod
    def _extract_currencies(text: str) -> list[str]:
        """Détecte les cryptos mentionnées dans un texte."""
        keywords = {
            "BTC": ["bitcoin", "btc"],
            "ETH": ["ethereum", "eth"],
            "BNB": ["binance coin", "bnb"],
            "SOL": ["solana", "sol"],
            "ADA": ["cardano", "ada"],
            "XRP": ["ripple", "xrp"],
            "DOT": ["polkadot", "dot"],
            "MATIC": ["polygon", "matic"],
        }
        text_lower = text.lower()
        found = [symbol for symbol, terms in keywords.items()
                 if any(term in text_lower for term in terms)]
        return found


class FearGreedFetcher:
    """
    Récupère l'indice Fear & Greed depuis alternative.me.
    Complètement gratuit, aucune clé API requise.
    """

    URL = "https://api.alternative.me/fng/?limit=1"

    def fetch(self) -> Optional[dict]:
        """
        Retourne {value: int (0-100), label: str, timestamp: str}.
        0-25 = Peur extrême (signal d'achat), 75-100 = Avidité extrême (signal de vente).
        """
        try:
            response = requests.get(self.URL, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            entry = data.get("data", [{}])[0]
            return {
                "value": int(entry.get("value", 50)),
                "label": entry.get("value_classification", "Neutral"),
                "timestamp": entry.get("timestamp"),
            }
        except Exception as e:
            logger.warning(f"Fear & Greed fetch échoué: {e}")
            return None

    @staticmethod
    def normalize(value: int) -> float:
        """
        Convertit la valeur Fear & Greed (0-100) en score normalisé (-1 à +1).
        Peur extrême (0) → +1.0 (signal haussier, achat potentiel)
        Avidité extrême (100) → -1.0 (signal baissier, vente potentielle)
        """
        return 1.0 - (value / 50.0)


class NewsFetcher:
    """
    Façade unifiée pour la récupération des news.
    Essaie CryptoPanic en premier, bascule sur NewsAPI, cache tout en SQLite.
    """

    def __init__(
        self,
        db: Database,
        cryptopanic_key: str = "",
        newsapi_key: str = "",
        cache_hours: int = 6,
    ):
        self.db = db
        self.cache_hours = cache_hours
        self.cryptopanic = CryptoPanicFetcher(cryptopanic_key)
        self.newsapi = NewsAPIFetcher(newsapi_key)
        self.fear_greed = FearGreedFetcher()

    def fetch_and_cache(self, currencies: Optional[list[str]] = None) -> list[NewsItem]:
        """
        Récupère les news depuis les sources disponibles et les cache en DB.
        Retourne la liste des nouveaux articles.
        """
        items: list[NewsItem] = []

        # Essayer CryptoPanic en premier
        cp_items = self.cryptopanic.fetch(currencies=currencies)
        if cp_items:
            items.extend(cp_items)
        else:
            # Fallback sur NewsAPI
            na_items = self.newsapi.fetch()
            items.extend(na_items)

        if not items:
            logger.warning("Aucune news récupérée depuis les sources disponibles")
            return []

        # Sauvegarder en DB
        db_items = [item.to_db_dict() for item in items]
        saved = self.db.save_news_items(db_items)
        logger.info(f"News: {saved} nouveaux articles sauvegardés (sur {len(items)} récupérés)")

        return items

    def get_recent_news(
        self, hours: Optional[int] = None, currency: Optional[str] = None
    ) -> list[dict]:
        """Retourne les news récentes depuis la DB (déjà analysées avec sentiment)."""
        h = hours or self.cache_hours * 4  # Plage plus large pour la lecture
        return self.db.get_recent_news(hours=h, currency=currency)

    def needs_refresh(self) -> bool:
        """Vérifie si le cache news doit être rafraîchi."""
        last_fetched = self.db.get_news_last_fetched()
        if not last_fetched:
            return True
        from datetime import timedelta
        try:
            last_dt = datetime.fromisoformat(last_fetched)
            age = datetime.utcnow() - last_dt.replace(tzinfo=None)
            return age > timedelta(hours=self.cache_hours)
        except Exception:
            return True

    def get_fear_greed(self) -> Optional[dict]:
        """Récupère l'indice Fear & Greed avec son score normalisé."""
        data = self.fear_greed.fetch()
        if data:
            data["normalized_score"] = FearGreedFetcher.normalize(data["value"])
        return data
