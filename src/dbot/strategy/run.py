# src/dbot/strategy/run.py
# Entry Point für eine einzelne dbot-Strategie (LSTM)
import os
import sys
import json
import logging
from logging.handlers import RotatingFileHandler
import argparse
import ccxt

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.utils.exchange import Exchange
from dbot.utils.telegram import send_message
from dbot.utils.trade_manager import full_trade_cycle, get_tracker_file_path
from dbot.utils.guardian import guardian_decorator


def setup_logging(symbol, timeframe):
    """Konfiguriert Logging für eine spezifische Strategie-Instanz."""
    safe_filename = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    log_dir = os.path.join(PROJECT_ROOT, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f'dbot_{safe_filename}.log')

    logger_name = f'dbot_{safe_filename}'
    logger = logging.getLogger(logger_name)

    if not logger.handlers:
        logger.setLevel(logging.INFO)

        fh = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(fh)

        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter(
            f'%(asctime)s [{safe_filename}] %(levelname)s: %(message)s', datefmt='%H:%M:%S'
        ))
        logger.addHandler(ch)
        logger.propagate = False

    return logger


def load_config(symbol, timeframe):
    """Lädt die JSON-Config für symbol+timeframe."""
    configs_dir = os.path.join(PROJECT_ROOT, 'src', 'dbot', 'strategy', 'configs')
    safe_name = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    config_path = os.path.join(configs_dir, f"config_{safe_name}_lstm.json")

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config nicht gefunden: {config_path}")

    with open(config_path, 'r') as f:
        config = json.load(f)

    required = ['market', 'model', 'risk']
    for key in required:
        if key not in config:
            raise ValueError(f"Config unvollständig: '{key}' fehlt in {config_path}")

    return config


@guardian_decorator
def run_for_account(account, telegram_config, params, logger):
    """Führt den Handelszyklus für einen Account und eine Strategie aus."""
    symbol = params['market']['symbol']
    timeframe = params['market']['timeframe']
    account_name = account.get('name', 'Standard-Account')

    logger.info(f"--- Starte dbot (LSTM) für {symbol} ({timeframe}) auf Account '{account_name}' ---")

    try:
        exchange = Exchange(account)
        full_trade_cycle(exchange, params, telegram_config, logger)
    except ccxt.AuthenticationError:
        logger.critical("Authentifizierungsfehler! API-Schlüssel prüfen!")
        raise
    except Exception as e:
        logger.error(f"Unerwarteter Fehler in run_for_account für {symbol}: {e}", exc_info=True)
        raise


def main():
    parser = argparse.ArgumentParser(description="dbot LSTM Trading-Skript")
    parser.add_argument('--symbol', required=True, type=str, help="Handelspaar (z.B. BTC/USDT:USDT)")
    parser.add_argument('--timeframe', required=True, type=str, help="Zeitrahmen (z.B. 4h)")
    args = parser.parse_args()

    symbol = args.symbol
    timeframe = args.timeframe

    logger = setup_logging(symbol, timeframe)

    try:
        params = load_config(symbol, timeframe)
        logger.info(f"Config geladen für {symbol} ({timeframe}).")

        with open(os.path.join(PROJECT_ROOT, 'secret.json'), "r") as f:
            secrets = json.load(f)

        accounts_to_run = secrets.get('dbot', [])
        telegram_config = secrets.get('telegram', {})

        if not accounts_to_run:
            logger.critical("Keine Account-Konfigurationen unter 'dbot' in secret.json gefunden.")
            sys.exit(1)

    except FileNotFoundError as e:
        logger.critical(f"Kritische Datei nicht gefunden: {e}")
        sys.exit(1)
    except ValueError as e:
        logger.critical(f"Fehler in Konfiguration: {e}")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Kritischer Initialisierungs-Fehler: {e}", exc_info=True)
        sys.exit(1)

    for account in accounts_to_run:
        try:
            run_for_account(account, telegram_config, params, logger)
        except Exception as e:
            logger.error(f"Schwerwiegender Fehler für Account {account.get('name', 'Unbenannt')}: {e}", exc_info=True)
            sys.exit(1)

    logger.info(f">>> dbot-Lauf für {symbol} ({timeframe}) abgeschlossen <<<")


if __name__ == "__main__":
    main()
