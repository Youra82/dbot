# master_runner.py
# Orchestriert alle aktiven dbot-Strategien (LSTM)
# Wird per Cronjob alle 15 Minuten aufgerufen
import json
import subprocess
import sys
import os
import time
import logging

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = SCRIPT_DIR
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

log_dir = os.path.join(PROJECT_ROOT, 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'master_runner.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(log_file), logging.StreamHandler()]
)


def main():
    settings_file = os.path.join(SCRIPT_DIR, 'settings.json')
    secret_file = os.path.join(SCRIPT_DIR, 'secret.json')
    bot_runner_script = os.path.join(SCRIPT_DIR, 'src', 'dbot', 'strategy', 'run.py')

    # Python-Interpreter in der venv
    python_executable = os.path.join(SCRIPT_DIR, '.venv', 'bin', 'python3')
    if not os.path.exists(python_executable):
        logging.critical(f"Python-Interpreter nicht gefunden: {python_executable}")
        return

    logging.info("=======================================================")
    logging.info("dbot Master Runner (LSTM) – Cronjob-basiert")
    logging.info("=======================================================")

    try:
        with open(settings_file, 'r') as f:
            settings = json.load(f)

        with open(secret_file, 'r') as f:
            secrets = json.load(f)

        if not secrets.get('dbot'):
            logging.critical("Kein 'dbot'-Account in secret.json gefunden.")
            return

        live_settings = settings.get('live_trading_settings', {})
        strategy_list = live_settings.get('active_strategies', [])

        if not strategy_list:
            logging.warning("Keine aktiven Strategien konfiguriert.")
            return

        logging.info("=======================================================")

        for strategy_info in strategy_list:
            if not isinstance(strategy_info, dict):
                continue
            if not strategy_info.get('active', False):
                continue

            symbol = strategy_info.get('symbol')
            timeframe = strategy_info.get('timeframe')

            if not symbol or not timeframe:
                logging.warning(f"Unvollständige Strategie-Info: {strategy_info}")
                continue

            logging.info(f"Starte Bot für: {symbol} ({timeframe})")
            command = [
                python_executable,
                bot_runner_script,
                "--symbol", symbol,
                "--timeframe", timeframe,
            ]

            try:
                process = subprocess.Popen(command)
                logging.info(f"Prozess für {symbol}_{timeframe} gestartet (PID: {process.pid}).")
                time.sleep(2)
            except Exception as e:
                logging.error(f"Fehler beim Starten des Prozesses für {symbol}_{timeframe}: {e}")

        # Auto-Optimizer im Hintergrund
        auto_opt_script = os.path.join(SCRIPT_DIR, 'auto_optimizer_scheduler.py')
        if os.path.exists(auto_opt_script):
            logging.info("[Auto-Optimizer] Prüfe ob Training/Optimierung fällig...")
            subprocess.Popen(
                [python_executable, auto_opt_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    except FileNotFoundError as e:
        logging.critical(f"Datei nicht gefunden: {e}")
    except json.JSONDecodeError as e:
        logging.critical(f"Fehler beim Lesen einer JSON-Datei: {e}")
    except Exception as e:
        logging.critical(f"Unerwarteter Fehler im Master Runner: {e}", exc_info=True)


if __name__ == "__main__":
    main()
