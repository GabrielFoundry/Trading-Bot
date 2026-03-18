"""
Analyse fondamentale : agrège news sentiment + Fear & Greed index.
Retourne un score normalisé de -1.0 (très baissier) à +1.0 (très haussier).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FundamentalSignal:
    score: float                    # -1.0 à +1.0
    fear_greed_value: Optional[int] = None   # 0-100
    fear_greed_normalized: float = 0.0
    news_sentiment_score: float = 0.0
    news_count: int = 0
    components: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.score > 0.1:
            return "bullish"
        elif self.score < -0.1:
            return "bearish"
        return "neutral"


class FundamentalAnalyzer:
    """
    Combine le sentiment des news et l'indice Fear & Greed
    en un signal fondamental normalisé.
    """

    # Pondération des composantes
    NEWS_WEIGHT = 0.6
    FEAR_GREED_WEIGHT = 0.4

    def analyze(
        self,
        news_sentiment_score: float,
        news_count: int,
        fear_greed: Optional[dict],
    ) -> FundamentalSignal:
        """
        Args:
            news_sentiment_score: Score agrégé des news (-1 à +1)
            news_count: Nombre d'articles analysés
            fear_greed: Résultat de FearGreedFetcher.fetch() avec 'normalized_score'
        """
        components = {}

        # --- Composante Fear & Greed ---
        fg_score = 0.0
        fg_value = None
        if fear_greed and fear_greed.get("value") is not None:
            fg_value = fear_greed["value"]
            fg_score = fear_greed.get("normalized_score", 0.0)
            components["fear_greed"] = {
                "raw": fg_value,
                "label": fear_greed.get("label", ""),
                "normalized": round(fg_score, 3),
            }

        # --- Composante News ---
        # Réduction de la confiance si peu d'articles
        news_confidence = min(news_count / 5.0, 1.0)  # Confiance max à 5+ articles
        adjusted_news_score = news_sentiment_score * news_confidence
        components["news"] = {
            "score": round(news_sentiment_score, 3),
            "count": news_count,
            "confidence": round(news_confidence, 3),
            "adjusted_score": round(adjusted_news_score, 3),
        }

        # --- Score combiné ---
        if fg_value is not None and news_count > 0:
            combined = (
                adjusted_news_score * self.NEWS_WEIGHT
                + fg_score * self.FEAR_GREED_WEIGHT
            )
        elif fg_value is not None:
            combined = fg_score
        elif news_count > 0:
            combined = adjusted_news_score
        else:
            combined = 0.0

        # Clamp entre -1 et +1
        combined = max(-1.0, min(1.0, combined))

        return FundamentalSignal(
            score=round(combined, 4),
            fear_greed_value=fg_value,
            fear_greed_normalized=round(fg_score, 4),
            news_sentiment_score=round(news_sentiment_score, 4),
            news_count=news_count,
            components=components,
        )
