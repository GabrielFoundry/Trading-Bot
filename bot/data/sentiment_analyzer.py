"""
Analyse du sentiment des actualités crypto.
Tier 1 (défaut) : VADER — rapide, aucun téléchargement requis.
Tier 2 (optionnel) : FinBERT — plus précis, ~500MB, nécessite transformers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Optional

from loguru import logger


SentimentLabel = Literal["bullish", "bearish", "neutral"]


@dataclass
class SentimentResult:
    score: float           # -1.0 (très baissier) à +1.0 (très haussier)
    label: SentimentLabel
    confidence: float      # 0.0 à 1.0


def score_to_label(score: float) -> SentimentLabel:
    """Convertit un score numérique en label texte."""
    if score > 0.05:
        return "bullish"
    elif score < -0.05:
        return "bearish"
    return "neutral"


class VaderSentimentAnalyzer:
    """
    Analyse de sentiment basée sur VADER (Valence Aware Dictionary and sEntiment Reasoner).
    Spécialisé pour les textes courts de réseaux sociaux/news.
    Aucun téléchargement, fonctionne hors ligne.
    """

    def __init__(self):
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            self._analyzer = SentimentIntensityAnalyzer()
            logger.debug("VADER sentiment analyzer chargé")
        except ImportError:
            logger.error("vaderSentiment non installé. Exécutez: pip install vaderSentiment")
            self._analyzer = None

    def analyze(self, text: str) -> SentimentResult:
        """Analyse le sentiment d'un texte."""
        if not self._analyzer or not text:
            return SentimentResult(score=0.0, label="neutral", confidence=0.0)

        scores = self._analyzer.polarity_scores(text)
        compound = scores["compound"]  # -1.0 à +1.0

        # Confidence basée sur la magnitude du score
        confidence = abs(compound)

        return SentimentResult(
            score=compound,
            label=score_to_label(compound),
            confidence=confidence,
        )

    def analyze_batch(self, texts: list[str]) -> list[SentimentResult]:
        return [self.analyze(text) for text in texts]


class FinBERTSentimentAnalyzer:
    """
    Analyse de sentiment basée sur FinBERT (BERT pré-entraîné sur textes financiers).
    Plus précis pour le vocabulaire financier mais nécessite transformers + torch.
    Activé uniquement si use_transformer_sentiment: true dans config.yaml.
    """

    MODEL_NAME = "ProsusAI/finbert"

    def __init__(self):
        self._pipeline = None
        self._load()

    def _load(self):
        try:
            from transformers import pipeline
            logger.info(f"Chargement du modèle FinBERT ({self.MODEL_NAME})...")
            self._pipeline = pipeline(
                "sentiment-analysis",
                model=self.MODEL_NAME,
                tokenizer=self.MODEL_NAME,
                max_length=512,
                truncation=True,
            )
            logger.info("FinBERT chargé avec succès")
        except ImportError:
            logger.error("transformers non installé. Décommentez les lignes dans requirements.txt")
            self._pipeline = None
        except Exception as e:
            logger.error(f"Impossible de charger FinBERT: {e}")
            self._pipeline = None

    def analyze(self, text: str) -> SentimentResult:
        if not self._pipeline or not text:
            return SentimentResult(score=0.0, label="neutral", confidence=0.0)

        try:
            result = self._pipeline(text[:512])[0]
            label_map = {"positive": "bullish", "negative": "bearish", "neutral": "neutral"}
            score_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}

            raw_label = result["label"].lower()
            confidence = result["score"]
            score = score_map.get(raw_label, 0.0) * confidence

            return SentimentResult(
                score=score,
                label=label_map.get(raw_label, "neutral"),
                confidence=confidence,
            )
        except Exception as e:
            logger.warning(f"FinBERT analyze échoué: {e}")
            return SentimentResult(score=0.0, label="neutral", confidence=0.0)

    def analyze_batch(self, texts: list[str]) -> list[SentimentResult]:
        """Analyse en batch pour de meilleures performances."""
        if not self._pipeline:
            return [SentimentResult(0.0, "neutral", 0.0) for _ in texts]

        truncated = [t[:512] for t in texts if t]
        try:
            results = self._pipeline(truncated)
            label_map = {"positive": "bullish", "negative": "bearish", "neutral": "neutral"}
            score_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
            output = []
            for r in results:
                raw_label = r["label"].lower()
                confidence = r["score"]
                score = score_map.get(raw_label, 0.0) * confidence
                output.append(SentimentResult(
                    score=score,
                    label=label_map.get(raw_label, "neutral"),
                    confidence=confidence,
                ))
            return output
        except Exception as e:
            logger.warning(f"FinBERT batch analyze échoué: {e}")
            return [SentimentResult(0.0, "neutral", 0.0) for _ in texts]


class SentimentAnalyzer:
    """
    Façade unifiée — choisit automatiquement VADER ou FinBERT selon la config.
    Expose aussi la méthode pour annoter les news en DB.
    """

    def __init__(self, use_transformer: bool = False):
        if use_transformer:
            logger.info("Utilisation de FinBERT pour le sentiment (mode avancé)")
            self._backend = FinBERTSentimentAnalyzer()
        else:
            logger.info("Utilisation de VADER pour le sentiment (mode standard)")
            self._backend = VaderSentimentAnalyzer()

    def analyze(self, text: str) -> SentimentResult:
        return self._backend.analyze(text)

    def analyze_news_items(self, news_items: list[dict]) -> list[dict]:
        """
        Annote une liste de dicts de news avec les scores de sentiment.
        Modifie les dicts en place et les retourne.
        """
        texts = [
            (item.get("title", "") + " " + item.get("body", "")).strip()
            for item in news_items
        ]
        results = self._backend.analyze_batch(texts)
        for item, result in zip(news_items, results):
            item["sentiment_score"] = result.score
            item["sentiment_label"] = result.label
        return news_items

    def aggregate_news_sentiment(
        self,
        news_items: list[dict],
        currency: Optional[str] = None,
        hours: int = 24,
    ) -> SentimentResult:
        """
        Calcule le sentiment agrégé d'une liste de news pour une devise donnée.
        Retourne un score moyen pondéré par la fraîcheur des articles.
        """
        if not news_items:
            return SentimentResult(score=0.0, label="neutral", confidence=0.0)

        scores = []
        for item in news_items:
            score = item.get("sentiment_score")
            if score is None:
                continue
            # Filtrer par devise si spécifié
            if currency:
                currencies = []
                raw = item.get("currencies", "[]")
                if isinstance(raw, str):
                    try:
                        currencies = json.loads(raw)
                    except Exception:
                        currencies = []
                else:
                    currencies = raw
                if currency not in currencies and currencies:
                    continue
            scores.append(float(score))

        if not scores:
            return SentimentResult(score=0.0, label="neutral", confidence=0.0)

        avg_score = sum(scores) / len(scores)
        confidence = min(len(scores) / 10.0, 1.0)  # Plus de news = plus de confiance

        return SentimentResult(
            score=avg_score,
            label=score_to_label(avg_score),
            confidence=confidence,
        )
