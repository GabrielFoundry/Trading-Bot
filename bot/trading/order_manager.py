"""
Orchestration du tick de trading.
Chaque tick : fetch prix → vérifier SL/TP → générer signaux → ouvrir positions.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger

from bot.analysis.fundamental import FundamentalAnalyzer, FundamentalSignal
from bot.analysis.signals import Signal, SignalGenerator
from bot.data.market_data import MarketData
from bot.data.news_fetcher import NewsFetcher
from bot.data.sentiment_analyzer import SentimentAnalyzer
from bot.db.database import Database
from bot.strategy.combined_strategy import CombinedStrategy
from bot.strategy.risk_manager import RiskManager
from bot.trading.paper_trader import PaperTrader
from bot.trading.portfolio import Portfolio


class OrderManager:
    """
    Moteur principal du bot. Exécuté à chaque tick (toutes les N minutes).

    Flux d'un tick :
    1. Récupérer les prix courants pour toutes les paires
    2. Vérifier SL/TP sur les positions ouvertes
    3. Pour chaque paire configurée :
       a. Charger les données OHLCV
       b. Calculer les indicateurs
       c. Récupérer le signal fondamental
       d. Générer le signal combiné
       e. Évaluer la sortie sur les positions ouvertes (signal SELL)
       f. Évaluer l'entrée si signal BUY
    4. Persister tous les signaux en DB
    """

    def __init__(
        self,
        db: Database,
        market_data: MarketData,
        portfolio: Portfolio,
        paper_trader: PaperTrader,
        strategy: CombinedStrategy,
        news_fetcher: NewsFetcher,
        sentiment_analyzer: SentimentAnalyzer,
        pairs: list[str],
        timeframe: str = "1h",
    ):
        self.db = db
        self.market_data = market_data
        self.portfolio = portfolio
        self.paper_trader = paper_trader
        self.strategy = strategy
        self.news_fetcher = news_fetcher
        self.sentiment_analyzer = sentiment_analyzer
        self.pairs = pairs
        self.timeframe = timeframe

        self.signal_generator = SignalGenerator()
        self.fundamental_analyzer = FundamentalAnalyzer()
        self._last_signals: dict[str, Signal] = {}

    def run_tick(self) -> dict:
        """
        Exécute un tick complet.
        Retourne un résumé des actions effectuées (pour le WebSocket).
        """
        params = self.db.get_active_strategy_params()
        strategy_version = params.version

        # Vérification du drawdown
        portfolio_snapshot = self.portfolio.get_snapshot()
        state = self.db.get_bot_state()
        if state.max_drawdown_triggered:
            logger.warning("Drawdown maximum déclenché — tick ignoré")
            return {"status": "halted", "reason": "max_drawdown"}

        # 1. Prix courants
        current_prices = {}
        for pair in self.pairs:
            ticker = self.market_data.get_ticker(pair)
            if ticker.get("last"):
                current_prices[pair] = float(ticker["last"])

        if not current_prices:
            logger.warning("Aucun prix disponible — tick ignoré")
            return {"status": "error", "reason": "no_prices"}

        # Mettre à jour les prix dans le portfolio
        self.portfolio.update_prices(current_prices)

        # 2. Vérifier SL/TP
        closed_by_sl_tp = self.paper_trader.check_stop_loss_take_profit(current_prices)
        if closed_by_sl_tp:
            logger.info(f"SL/TP déclenché pour {len(closed_by_sl_tp)} position(s)")

        # 3. Obtenir le signal fondamental (partagé pour toutes les paires)
        fundamental_signal = self._get_fundamental_signal()

        # 4. Pour chaque paire : signal + décision
        signals_generated = []
        positions_opened = []
        positions_closed = []

        for pair in self.pairs:
            price = current_prices.get(pair)
            if not price:
                continue

            # Données OHLCV
            df = self.market_data.fetch_ohlcv(pair, self.timeframe, limit=200)
            if df.empty or len(df) < 30:
                logger.warning(f"{pair}: données OHLCV insuffisantes")
                continue

            # Signal combiné
            signal = self.signal_generator.generate(
                symbol=pair,
                df=df,
                params=params,
                fundamental=fundamental_signal,
                strategy_version=strategy_version,
            )

            # Sauvegarder le signal en DB
            signal_id = self.db.save_signal(signal.to_record())
            self._last_signals[pair] = signal
            signals_generated.append({
                "symbol": pair,
                "action": signal.action,
                "confidence": signal.confidence,
                "score": signal.combined_score,
            })

            # Vérifier la sortie sur les positions ouvertes pour cette paire
            for position in list(self.portfolio.positions):
                if position.symbol != pair:
                    continue
                exit_reason = self.strategy.should_exit(
                    position={"id": position.id, "symbol": position.symbol,
                               "side": position.side, "entry_price": position.entry_price,
                               "leverage": position.leverage,
                               "liquidation_price": position.liquidation_price},
                    current_price=price,
                    signal=signal,
                )
                if exit_reason:
                    result = self.paper_trader.execute_close(position.id, price, exit_reason)
                    if result:
                        positions_closed.append(result)

            # Envisager une entrée
            proposal = self.strategy.should_enter(
                signal=signal,
                portfolio_value=self.portfolio.get_snapshot().total_value,
                open_positions_count=self.portfolio.open_positions_count,
            )
            if proposal:
                # Prix d'achat = ask (légèrement au-dessus du last)
                ask_price = price * 1.0001
                result = self.paper_trader.execute_buy(
                    proposal=proposal,
                    current_ask_price=ask_price,
                    signal_id=signal_id,
                    strategy_version=strategy_version,
                )
                if result:
                    positions_opened.append(result)

        # 5. Vérifier le drawdown après le tick
        updated_snapshot = self.portfolio.get_snapshot()
        if self.strategy.risk_manager.check_max_drawdown(updated_snapshot.total_value):
            self.db.update_bot_state(max_drawdown_triggered=1)

        # 6. Mettre à jour le dernier tick
        from datetime import datetime, timezone
        self.db.update_bot_state(last_tick_at=datetime.now(timezone.utc).isoformat())

        return {
            "status": "ok",
            "prices": current_prices,
            "signals": signals_generated,
            "positions_opened": positions_opened,
            "positions_closed": positions_closed + closed_by_sl_tp,
            "portfolio": self.portfolio.to_dict(),
        }

    def _get_fundamental_signal(self) -> Optional[FundamentalSignal]:
        """Calcule le signal fondamental depuis les news et Fear & Greed."""
        try:
            # News récentes depuis la DB (déjà annotées avec sentiment)
            news_items = self.news_fetcher.get_recent_news(hours=24)
            news_scored = self.sentiment_analyzer.analyze_news_items(news_items)

            # Score de sentiment agrégé
            from bot.data.sentiment_analyzer import SentimentAnalyzer
            agg = self.sentiment_analyzer.aggregate_news_sentiment(news_scored)

            # Fear & Greed
            fear_greed = self.news_fetcher.get_fear_greed()

            return self.fundamental_analyzer.analyze(
                news_sentiment_score=agg.score,
                news_count=len(news_scored),
                fear_greed=fear_greed,
            )
        except Exception as e:
            logger.warning(f"Impossible de calculer le signal fondamental: {e}")
            return None

    def get_last_signals(self) -> dict[str, dict]:
        """Retourne les derniers signaux pour chaque paire (pour le dashboard)."""
        return {
            pair: {
                "action": s.action,
                "confidence": s.confidence,
                "combined_score": s.combined_score,
                "technical_score": s.technical_score,
                "fundamental_score": s.fundamental_score,
                "reasons": s.reasons,
                "timestamp": s.timestamp,
            }
            for pair, s in self._last_signals.items()
        }
