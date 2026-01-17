# src/dbot/strategy/run.py
"""
DBot Aggressive Scalping Strategy Runner
Basierend auf StBot, aber mit aggressiven Parametern für 1m/5m Timeframes
"""
import os
import sys
import json
import logging
from logging.handlers import RotatingFileHandler
import time
import argparse
import ccxt

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.utils.exchange import Exchange
from dbot.utils.telegram import send_message
from dbot.utils.trade_manager import full_trade_cycle

def setup_logging(symbol, timeframe):
    """Richte Logging für Symbol/Timeframe ein"""
    safe_filename = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    log_dir = os.path.join(PROJECT_ROOT, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f'dbot_{safe_filename}.log')

    logger = logging.getLogger(f'dbot_{safe_filename}')
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        # File Handler
        fh = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
        fh_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(fh_formatter)
        logger.addHandler(fh)

        # Console Handler
        ch = logging.StreamHandler()
        ch_formatter = logging.Formatter(f'%(asctime)s [%(levelname)s] {symbol}|{timeframe}: %(message)s', datefmt='%H:%M:%S')
        ch.setFormatter(ch_formatter)
        logger.addHandler(ch)

        logger.propagate = False

    return logger


def load_config(symbol, timeframe, use_macd_filter):
    """Lade Konfiguration für Symbol/Timeframe"""
    configs_dir = os.path.join(PROJECT_ROOT, 'src', 'dbot', 'strategy', 'configs')
    safe_filename_base = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"

    # Suffix-Logik für macd-Filter
    suffix = "_macd" if use_macd_filter else ""
    config_filename = f"config_{safe_filename_base}{suffix}.json"
    config_path = os.path.join(configs_dir, config_filename)

    if not os.path.exists(config_path):
        config_filename_fallback = f"config_{safe_filename_base}.json"
        config_path_fallback = os.path.join(configs_dir, config_filename_fallback)
        if os.path.exists(config_path_fallback):
            config_path = config_path_fallback
            config_filename = config_filename_fallback
        else:
            config_filename_macd = f"config_{safe_filename_base}_macd.json"
            config_path_macd = os.path.join(configs_dir, config_filename_macd)
            if os.path.exists(config_path_macd):
                config_path = config_path_macd
                config_filename = config_filename_macd
            else:
                raise FileNotFoundError(f"Konfigurationsdatei '{config_filename}' oder Fallbacks nicht gefunden in {configs_dir}")

    with open(config_path, 'r') as f:
        config = json.load(f)
    
    return config


def run_for_account(account, telegram_config, params, logger):
    """Führt den Handelszyklus für einen Account aus"""
    try:
        account_name = account.get('name', 'Standard-Account')
        symbol = params['market']['symbol']
        timeframe = params['market']['timeframe']
        
        logger.info(f"--- Starte DBot (Aggressive Scalper) für {symbol} ({timeframe}) ---")
        
        exchange = Exchange(account)

        if not exchange.markets:
            logger.critical("Exchange konnte nicht initialisiert werden (Märkte nicht geladen). Breche Zyklus ab.")
            return

        full_trade_cycle(exchange, params, telegram_config, logger)

    except Exception as e:
        # Fange alle unerwarteten Fehler im Hauptzyklus ab
        symbol_f = params.get('market', {}).get('symbol', 'Unbekannt')
        tf_f = params.get('market', {}).get('timeframe', 'N/A')
        logger.critical(f"!!! KRITISCHER FEHLER im Hauptzyklus für {symbol_f} ({tf_f}) !!!")
        logger.critical(f"Fehlerdetails: {e}", exc_info=True)
        # Sende Telegram Nachricht bei kritischem Fehler
        try:
            error_message = f"🚨 *Kritischer Fehler* in DBot für *{symbol_f} ({tf_f})*:\n\n`{e}`\n\nBot-Instanz könnte instabil sein."
            send_message(
                telegram_config.get('bot_token'),
                telegram_config.get('chat_id'),
                error_message
            )
        except Exception as tel_e:
            logger.error(f"Konnte keine Telegram-Fehlermeldung senden: {tel_e}")


def main():
    parser = argparse.ArgumentParser(description="DBot Aggressive Scalping Trading-Skript")
    parser.add_argument('--symbol', required=True, type=str)
    parser.add_argument('--timeframe', required=True, type=str)
    parser.add_argument('--use_macd', required=True, type=str)
    args = parser.parse_args()

    symbol, timeframe = args.symbol, args.timeframe
    use_macd = args.use_macd.lower() == 'true'

    logger = setup_logging(symbol, timeframe)

    try:
        params = load_config(symbol, timeframe, use_macd)

        with open(os.path.join(PROJECT_ROOT, 'secret.json'), "r") as f:
            secrets = json.load(f)

        # Lese Account-Konfigurationen - dbot nutzt 'dbot' Schlüssel
        accounts_to_run = secrets.get('dbot', [])
        if not accounts_to_run:
            logger.critical("Keine Account-Konfigurationen unter 'dbot' in secret.json gefunden!")
            sys.exit(1)

        telegram_config = secrets.get('telegram', {})

    except FileNotFoundError as e:
        logger.critical(f"Kritischer Initialisierungs-Fehler: Datei nicht gefunden - {e}", exc_info=True)
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.critical(f"Kritischer Initialisierungs-Fehler: JSON-Fehler in Konfigurationsdatei - {e}", exc_info=True)
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Kritischer Initialisierungs-Fehler: {e}", exc_info=True)
        sys.exit(1)

    # Stelle sicher, dass accounts_to_run eine Liste ist
    if not isinstance(accounts_to_run, list):
        logger.critical("Fehler: 'dbot'-Eintrag in secret.json ist keine Liste von Accounts.")
        sys.exit(1)

    # Führe für jeden Account den Handelszyklus aus
    for account in accounts_to_run:
        run_for_account(account, telegram_config, params, logger)


    logger.info(f">>> DBot-Lauf für {symbol} ({timeframe}) abgeschlossen <<<\n")

if __name__ == "__main__":
    main()
