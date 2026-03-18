#!/usr/bin/env python3
"""
Script d'initialisation du bot de trading.
À exécuter une seule fois avant le premier lancement.
"""

import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def print_step(msg: str, ok: bool = True):
    icon = "✅" if ok else "❌"
    print(f"  {icon}  {msg}")


def print_header(msg: str):
    print(f"\n{'=' * 50}")
    print(f"  {msg}")
    print('=' * 50)


def check_python_version():
    print_header("Vérification Python")
    version = sys.version_info
    if version < (3, 10):
        print_step(f"Python {version.major}.{version.minor} — version trop ancienne (min 3.10)", ok=False)
        sys.exit(1)
    print_step(f"Python {version.major}.{version.minor}.{version.micro} — OK")


def check_dependencies():
    print_header("Vérification des dépendances")
    packages = [
        ("ccxt", "ccxt"),
        ("pandas", "pandas"),
        ("ta", "ta"),
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("yaml", "pyyaml"),
        ("apscheduler", "apscheduler"),
        ("loguru", "loguru"),
        ("vaderSentiment", "vaderSentiment"),
        ("pydantic", "pydantic"),
        ("dotenv", "python-dotenv"),
        ("aiohttp", "aiohttp"),
    ]
    missing = []
    for import_name, pkg_name in packages:
        try:
            __import__(import_name)
            print_step(f"{pkg_name}")
        except ImportError:
            print_step(f"{pkg_name} — MANQUANT (pip install {pkg_name})", ok=False)
            missing.append(pkg_name)

    if missing:
        print(f"\n  ⚠️  Installez les dépendances manquantes :")
        print(f"     pip install -r requirements.txt")
        sys.exit(1)


def create_directories():
    print_header("Création des répertoires")
    dirs = ["data", "logs", "config"]
    for d in dirs:
        path = ROOT / d
        path.mkdir(exist_ok=True)
        print_step(f"Répertoire '{d}/'")


def init_database():
    print_header("Initialisation de la base de données")
    from bot.db.database import init_db, DB_PATH
    try:
        init_db(DB_PATH)
        print_step(f"Base de données créée : {DB_PATH}")
    except Exception as e:
        print_step(f"Erreur lors de la création de la DB : {e}", ok=False)
        sys.exit(1)


def check_env_file():
    print_header("Vérification de la configuration")
    env_file = ROOT / "config" / ".env"
    env_example = ROOT / "config" / ".env.example"

    if not env_file.exists():
        if env_example.exists():
            import shutil
            shutil.copy(env_example, env_file)
            print_step("Fichier .env créé depuis .env.example")
            print("\n  ⚠️  IMPORTANT : Éditez config/.env avec vos clés API Binance testnet")
            print("     Suivez les instructions dans le fichier README.md")
        else:
            print_step("Fichier config/.env absent", ok=False)
    else:
        print_step("Fichier config/.env présent")

    config_file = ROOT / "config" / "config.yaml"
    if config_file.exists():
        print_step("Fichier config/config.yaml présent")
    else:
        print_step("Fichier config/config.yaml absent", ok=False)


def test_binance_connection():
    print_header("Test de connexion Binance Testnet")
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / "config" / ".env")
        load_dotenv(ROOT / ".env")

        import ccxt
        api_key = os.getenv("BINANCE_TESTNET_API_KEY", "")
        api_secret = os.getenv("BINANCE_TESTNET_API_SECRET", "")

        if not api_key or api_key == "your_testnet_api_key_here":
            print_step("Clés API non configurées — connexion ignorée")
            print("     Ajoutez vos clés dans config/.env pour tester la connexion")
            return

        exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
            "urls": {
                "api": {
                    "public": "https://testnet.binancefuture.com",
                    "private": "https://testnet.binancefuture.com",
                }
            },
        })
        markets = exchange.load_markets()
        print_step(f"Connexion Binance Testnet OK — {len(markets)} marchés disponibles")
    except Exception as e:
        print_step(f"Connexion Binance Testnet échouée : {e}", ok=False)
        print("     Vérifiez vos clés API dans config/.env")


def print_final_instructions():
    print_header("Configuration terminée")
    print("""
  📋 PROCHAINES ÉTAPES :

  1. Créez un compte Binance Testnet (futures) :
     https://testnet.binancefuture.com/
     → Connectez-vous avec GitHub
     → Générez vos clés API dans "API Management"

  2. Ajoutez vos clés dans config/.env :
     BINANCE_TESTNET_API_KEY=votre_cle
     BINANCE_TESTNET_API_SECRET=votre_secret

  3. (Optionnel) Ajoutez des clés API de news gratuites :
     CryptoPanic : https://cryptopanic.com/developers/api/
     NewsAPI : https://newsapi.org/

  4. Lancez le bot :
     make run

  5. Ouvrez le dashboard :
     http://127.0.0.1:8000

  ⚠️  Le bot est en mode PAPER TRADING par défaut.
     Aucun argent réel ne sera utilisé.
""")


def main():
    print("\n  🚀  BOT DE TRADING CRYPTO — Configuration initiale")

    check_python_version()
    check_dependencies()
    create_directories()
    init_database()
    check_env_file()
    test_binance_connection()
    print_final_instructions()


if __name__ == "__main__":
    main()
