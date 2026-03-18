# Trading Bot Crypto

Bot de trading crypto automatique avec :
- **Paper Trading** (simulation avec prix réels, sans argent réel)
- **Analyse technique** : RSI, MACD, Bandes de Bollinger, EMA, ATR
- **Analyse fondamentale** : News sentiment + Fear & Greed index
- **Levier adaptatif** : x1 à x2 selon la confiance du signal
- **Apprentissage quotidien** : optimisation automatique des paramètres
- **Dashboard web** : portfolio, positions, signaux, métriques en temps réel

---

## Démarrage rapide

### 1. Installation

```bash
make setup
```

### 2. Configuration des clés API Binance Testnet

1. Allez sur https://testnet.binancefuture.com/
2. Connectez-vous avec GitHub
3. Dans "API Management", cliquez sur **"Generate Key"**
4. Copiez les clés dans `config/.env` :

```env
BINANCE_TESTNET_API_KEY=votre_cle_ici
BINANCE_TESTNET_API_SECRET=votre_secret_ici
```

### 3. Lancer le bot

```bash
make run
```

### 4. Ouvrir le dashboard

http://127.0.0.1:8000

---

## Structure du projet

```
Trading-Bot/
├── bot/                    # Moteur de trading
│   ├── data/               # Données marché + news
│   ├── analysis/           # Indicateurs + signaux
│   ├── strategy/           # Stratégie + gestion du risque
│   ├── trading/            # Paper trader + portfolio
│   ├── learning/           # Métriques + optimiseur
│   └── main.py             # Orchestrateur
├── api/                    # API FastAPI
├── dashboard/              # Interface web (HTML/JS/CSS)
├── config/
│   ├── config.yaml         # Seul fichier à modifier
│   └── .env                # Clés API (créé lors du setup)
├── data/                   # Base de données SQLite
└── logs/                   # Logs du bot
```

---

## Configuration clé (config/config.yaml)

| Paramètre | Défaut | Description |
|---|---|---|
| `exchange.testnet` | `true` | Ne passez à `false` qu'après validation |
| `trading.paper_balance` | `300.0` | Votre budget en USDT |
| `trading.risk_per_trade_pct` | `3.5` | Risque par trade (%) |
| `leverage.max_leverage` | `2` | Levier maximum autorisé |
| `risk.max_drawdown_pct` | `15.0` | Le bot s'arrête si perte > 15% |

---

## Sécurités intégrées

- Mode testnet par défaut — aucun argent réel sans action explicite
- Arrêt automatique si drawdown > 15%
- Maximum 3 positions simultanées
- Stop-loss sur chaque trade (basé sur l'ATR)
- Levier x1 pour les signaux de faible confiance
- Garde de liquidation : fermeture auto si prix s'approche à 5% de la liquidation

---

## Commandes

```bash
make setup    # Installation initiale
make run      # Lancer le bot + dashboard
make stop     # Arrêter le bot
make logs     # Voir les logs en direct
make status   # Voir l'état actuel
```

---

## Avertissement

Le trading de crypto-monnaies comporte des risques importants.
Testez toujours en paper trading avant d'utiliser de l'argent réel.