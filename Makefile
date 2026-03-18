# ============================================================
#  Makefile — Bot de Trading Crypto
#  Commandes disponibles :
#    make setup   — Installation initiale (à faire une seule fois)
#    make run     — Lancer le bot + dashboard
#    make stop    — Arrêter le bot
#    make logs    — Afficher les logs en direct
#    make status  — Voir l'état du bot
# ============================================================

.PHONY: setup run stop logs status clean

# Installation initiale
setup:
	pip install -r requirements.txt && python setup.py

# Lancer le bot (dashboard + moteur de trading en parallèle)
run:
	@echo "🚀 Démarrage du bot..."
	@echo "   Dashboard : http://127.0.0.1:8000"
	@echo "   Logs      : logs/trading_bot.log"
	@echo "   Arrêt     : make stop"
	uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload &
	python -m bot.main

# Arrêter le bot
stop:
	@echo "Arrêt du bot..."
	@pkill -f "python -m bot.main" 2>/dev/null || true
	@pkill -f "uvicorn api.main" 2>/dev/null || true
	@echo "Bot arrêté."

# Afficher les logs en direct
logs:
	tail -f logs/trading_bot.log

# Statut du bot
status:
	@python -c "
from bot.db.database import Database, DB_PATH
db = Database(DB_PATH)
state = db.get_bot_state()
print(f'Mode       : {state.mode}')
print(f'Running    : {state.is_running}')
print(f'Balance    : {state.paper_balance:.2f} USDT')
print(f'Trades     : {state.total_trades_count}')
print(f'Last tick  : {state.last_tick_at or \"jamais\"}')
print(f'Last optim : {state.last_optimization_at or \"jamais\"}')
"

# Nettoyer les fichiers générés (logs, DB)
clean:
	@echo "⚠️  Suppression des logs et de la base de données..."
	@read -p "Confirmer ? [y/N] " CONFIRM; \
	if [ "$$CONFIRM" = "y" ]; then \
		rm -f data/trading_bot.db logs/*.log; \
		echo "Nettoyé."; \
	else \
		echo "Annulé."; \
	fi
