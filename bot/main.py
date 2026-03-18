"""
Orchestrateur principal du bot de trading.
Initialise tous les composants et gère le scheduling via APScheduler.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from loguru import logger

# Charger les variables d'environnement
load_dotenv(Path(__file__).parent.parent / "config" / ".env")
load_dotenv(Path(__file__).parent.parent / ".env")

# Ajouter le répertoire racine au path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from bot.data.market_data import MarketData, build_exchange
from bot.data.news_fetcher import NewsFetcher
from bot.data.sentiment_analyzer import SentimentAnalyzer
from bot.db.database import Database, DB_PATH, init_db
from bot.learning.performance_tracker import PerformanceTracker
from bot.learning.strategy_optimizer import StrategyOptimizer
from bot.strategy.combined_strategy import CombinedStrategy
from bot.strategy.risk_manager import RiskManager
from bot.trading.order_manager import OrderManager
from bot.trading.paper_trader import PaperTrader
from bot.trading.portfolio import Portfolio


def load_config() -> dict:
    config_path = ROOT / "config" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(config: dict) -> None:
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    level = config.get("logging", {}).get("level", "INFO")
    rotation = config.get("logging", {}).get("rotation", "10 MB")
    retention = config.get("logging", {}).get("retention", "1 month")
    logger.remove()
    logger.add(sys.stdout, level=level, colorize=True,
               format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}")
    logger.add(log_dir / "trading_bot.log", level=level,
               rotation=rotation, retention=retention, encoding="utf-8")


class TradingBot:
    """Composant central — initialise et connecte tous les modules."""

    def __init__(self):
        self.config = load_config()
        setup_logging(self.config)
        logger.info("=" * 60)
        logger.info("  TRADING BOT - Démarrage")
        logger.info("=" * 60)

        # Initialiser la DB
        init_db(DB_PATH)

        self.db = Database(DB_PATH)
        self._setup_components()
        self.scheduler = AsyncIOScheduler(timezone="UTC")

    def _setup_components(self) -> None:
        cfg = self.config
        trading_cfg = cfg.get("trading", {})
        exchange_cfg = cfg.get("exchange", {})
        risk_cfg = cfg.get("risk", {})
        leverage_cfg = cfg.get("leverage", {})
        news_cfg = cfg.get("news", {})
        scheduler_cfg = cfg.get("scheduler", {})

        testnet = exchange_cfg.get("testnet", True)
        mode = "paper" if testnet else "live"

        logger.info(f"Mode : {'PAPER TRADING (testnet)' if testnet else '⚠️  LIVE TRADING (argent réel)'}")

        # Exchange
        api_key = os.getenv("BINANCE_TESTNET_API_KEY" if testnet else "BINANCE_API_KEY", "")
        api_secret = os.getenv("BINANCE_TESTNET_API_SECRET" if testnet else "BINANCE_API_SECRET", "")

        exchange = build_exchange(api_key, api_secret, testnet=testnet)

        # Composants données
        self.market_data = MarketData(
            exchange=exchange,
            db=self.db,
            timeframe=trading_cfg.get("timeframe", "1h"),
        )
        self.news_fetcher = NewsFetcher(
            db=self.db,
            cryptopanic_key=os.getenv("CRYPTOPANIC_API_KEY", news_cfg.get("cryptopanic_api_key", "")),
            newsapi_key=os.getenv("NEWSAPI_KEY", news_cfg.get("newsapi_key", "")),
            cache_hours=news_cfg.get("news_cache_hours", 6),
        )
        self.sentiment_analyzer = SentimentAnalyzer(
            use_transformer=news_cfg.get("use_transformer_sentiment", False)
        )

        # Portfolio
        initial_balance = trading_cfg.get("paper_balance", 300.0)
        self.portfolio = Portfolio(self.db, initial_balance=initial_balance, mode=mode)

        # Risk Manager
        self.risk_manager = RiskManager(
            risk_per_trade_pct=trading_cfg.get("risk_per_trade_pct", 3.5),
            max_open_positions=trading_cfg.get("max_open_positions", 3),
            max_drawdown_pct=risk_cfg.get("max_drawdown_pct", 15.0),
            stop_loss_pct=risk_cfg.get("stop_loss_pct", 2.0),
            take_profit_pct=risk_cfg.get("take_profit_pct", 4.0),
            atr_stop_multiplier=risk_cfg.get("atr_stop_multiplier", 1.5),
            risk_reward_ratio=risk_cfg.get("risk_reward_ratio", 2.0),
            max_leverage=leverage_cfg.get("max_leverage", 2.0),
            high_confidence_threshold=leverage_cfg.get("high_confidence_threshold", 0.80),
            mid_confidence_threshold=leverage_cfg.get("mid_confidence_threshold", 0.60),
            mid_leverage=leverage_cfg.get("mid_leverage", 1.5),
            liquidation_guard_pct=leverage_cfg.get("liquidation_guard_pct", 5.0),
            initial_balance=initial_balance,
        )

        # Stratégie
        params = self.db.get_active_strategy_params()
        self.strategy = CombinedStrategy(params=params, risk_manager=self.risk_manager)

        # Paper Trader
        self.paper_trader = PaperTrader(
            db=self.db,
            portfolio=self.portfolio,
            fee_rate=trading_cfg.get("fee_rate", 0.001),
        )

        # Order Manager
        self.order_manager = OrderManager(
            db=self.db,
            market_data=self.market_data,
            portfolio=self.portfolio,
            paper_trader=self.paper_trader,
            strategy=self.strategy,
            news_fetcher=self.news_fetcher,
            sentiment_analyzer=self.sentiment_analyzer,
            pairs=trading_cfg.get("pairs", ["BTC/USDT"]),
            timeframe=trading_cfg.get("timeframe", "1h"),
        )

        # Learning
        learning_cfg = cfg.get("learning", {})
        self.performance_tracker = PerformanceTracker(
            db=self.db,
            window=learning_cfg.get("performance_window_trades", 50),
        )
        self.strategy_optimizer = StrategyOptimizer(
            db=self.db,
            min_trades=learning_cfg.get("min_trades_for_optimization", 50),
            min_improvement_pct=learning_cfg.get("min_improvement_pct", 5.0),
        )

        self._scheduler_cfg = scheduler_cfg
        self._learning_cfg = learning_cfg

    # ------------------------------------------------------------------
    # Tâches planifiées
    # ------------------------------------------------------------------

    def _is_in_trading_hours(self) -> bool:
        """Vérifie si l'heure actuelle est dans les plages horaires configurées."""
        schedule_cfg = self.config.get("schedule", {})
        if not schedule_cfg.get("enabled", False):
            return True  # Pas de restriction = toujours actif

        from datetime import time as dtime
        import time as tmod
        now = datetime.now()  # heure locale
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        today = day_names[now.weekday()]
        allowed_days = schedule_cfg.get("days", day_names)
        if today not in allowed_days:
            return False

        for slot in schedule_cfg.get("trading_hours", []):
            try:
                start_h, start_m = map(int, slot["start"].split(":"))
                end_h, end_m = map(int, slot["end"].split(":"))
                start_t = dtime(start_h, start_m)
                end_t = dtime(end_h, end_m)
                current_t = now.time().replace(second=0, microsecond=0)
                if start_t <= current_t <= end_t:
                    return True
            except Exception:
                return True  # En cas d'erreur de parsing, ne pas bloquer

        return False

    async def trading_loop(self) -> None:
        """Tick principal — exécuté toutes les N minutes."""
        try:
            state = self.db.get_bot_state()
            if not state.is_running:
                return

            if not self._is_in_trading_hours():
                logger.debug("Hors plages horaires — tick ignoré")
                return

            result = self.order_manager.run_tick()
            if result.get("positions_opened") or result.get("positions_closed"):
                # Calculer les métriques après chaque fermeture de trade
                if result.get("positions_closed"):
                    self.performance_tracker.calculate_and_save()
        except Exception as e:
            logger.error(f"Erreur dans le tick principal: {e}", exc_info=True)

    async def update_news(self) -> None:
        """Mise à jour des news — exécutée toutes les heures."""
        try:
            if self.news_fetcher.needs_refresh():
                pairs = self.config.get("trading", {}).get("pairs", [])
                currencies = [p.split("/")[0] for p in pairs]
                items = self.news_fetcher.fetch_and_cache(currencies=currencies)
                if items:
                    news_dicts = [i.to_db_dict() for i in items]
                    self.sentiment_analyzer.analyze_news_items(news_dicts)
                    self.db.save_news_items(news_dicts)
                self.db.update_bot_state(last_news_update_at=datetime.now(timezone.utc).isoformat())
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour des news: {e}", exc_info=True)

    async def daily_learning_cycle(self) -> None:
        """Cycle d'apprentissage quotidien."""
        logger.info("Cycle d'apprentissage quotidien démarré")
        try:
            # 1. Calculer les métriques de performance
            metrics = self.performance_tracker.calculate_and_save()

            # 2. Optimiser les paramètres
            result = self.strategy_optimizer.run()
            if result and result.get("optimized"):
                # Recharger les paramètres dans la stratégie
                new_params = self.db.get_active_strategy_params()
                self.strategy.update_params(new_params)
                logger.info(f"Stratégie mise à jour : version {new_params.version}")
        except Exception as e:
            logger.error(f"Erreur dans le cycle d'apprentissage: {e}", exc_info=True)

    async def daily_snapshot(self) -> None:
        """Snapshot quotidien du portfolio."""
        try:
            snapshot = self.portfolio.get_snapshot()
            self.db.save_portfolio_snapshot(
                usdt_balance=snapshot.usdt_balance,
                positions_value=snapshot.positions_value,
                total_value=snapshot.total_value,
                unrealized_pnl=snapshot.unrealized_pnl,
                realized_pnl_today=self.portfolio.get_realized_pnl(),
                open_positions=snapshot.open_positions_count,
            )
            self.db.update_bot_state(last_snapshot_at=datetime.now(timezone.utc).isoformat())
            logger.info(f"Snapshot portfolio : {snapshot.total_value:.2f} USDT")
        except Exception as e:
            logger.error(f"Erreur lors du snapshot: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Démarrage / Arrêt
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Démarre le bot et le scheduler."""
        cfg = self._scheduler_cfg
        learning_cfg = self._learning_cfg

        # Tick principal
        interval_min = cfg.get("trading_interval_minutes", 5)
        self.scheduler.add_job(
            self.trading_loop, IntervalTrigger(minutes=interval_min),
            id="trading_loop", name="Tick principal",
        )

        # News
        news_hours = cfg.get("news_update_hours", 1)
        self.scheduler.add_job(
            self.update_news, IntervalTrigger(hours=news_hours),
            id="news_update", name="Mise à jour news",
        )

        # Snapshot quotidien
        snap_time = cfg.get("daily_snapshot_time", "00:00").split(":")
        self.scheduler.add_job(
            self.daily_snapshot, CronTrigger(hour=int(snap_time[0]), minute=int(snap_time[1])),
            id="daily_snapshot", name="Snapshot portfolio",
        )

        # Cycle d'apprentissage quotidien
        learn_time = cfg.get("daily_learning_time", "00:05").split(":")
        self.scheduler.add_job(
            self.daily_learning_cycle, CronTrigger(hour=int(learn_time[0]), minute=int(learn_time[1])),
            id="daily_learning", name="Cycle d'apprentissage",
        )

        # Marquer le bot comme démarré
        self.db.set_bot_running(True, mode=self.portfolio.mode)
        self.scheduler.start()
        logger.info(f"Bot démarré — tick toutes les {interval_min} minutes")

    def stop(self) -> None:
        """Arrête le bot proprement."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        self.db.set_bot_running(False)
        logger.info("Bot arrêté")


async def main() -> None:
    bot = TradingBot()

    # Exécuter la première mise à jour des news immédiatement
    await bot.update_news()
    await bot.daily_snapshot()

    bot.start()

    logger.info("Bot en cours d'exécution. Appuyez sur Ctrl+C pour arrêter.")
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Interruption reçue — arrêt du bot...")
    finally:
        bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
