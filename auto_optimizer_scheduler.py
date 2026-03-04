#!/usr/bin/env python3
# auto_optimizer_scheduler.py
# Prüft ob wöchentliches Re-Training + Re-Optimierung fällig ist
import os
import sys
import json
import logging
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

log_dir = os.path.join(PROJECT_ROOT, 'logs')
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, 'auto_optimizer.log')),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

SCHEDULE_FILE = os.path.join(PROJECT_ROOT, 'artifacts', 'results', 'optimizer_schedule.json')


def get_schedule():
    if not os.path.exists(SCHEDULE_FILE):
        return {}
    with open(SCHEDULE_FILE) as f:
        return json.load(f)


def save_schedule(schedule):
    os.makedirs(os.path.dirname(SCHEDULE_FILE), exist_ok=True)
    with open(SCHEDULE_FILE, 'w') as f:
        json.dump(schedule, f, indent=4)


def should_run(symbol, timeframe, interval_days=7):
    """Prüft ob Training für dieses Symbol/Timeframe fällig ist."""
    schedule = get_schedule()
    key = f"{symbol}_{timeframe}"
    last_run_str = schedule.get(key, {}).get('last_run')

    if not last_run_str:
        return True  # Noch nie gelaufen

    last_run = datetime.fromisoformat(last_run_str)
    return datetime.now() - last_run > timedelta(days=interval_days)


def mark_done(symbol, timeframe):
    """Markiert das Training als abgeschlossen."""
    schedule = get_schedule()
    key = f"{symbol}_{timeframe}"
    schedule[key] = {'last_run': datetime.now().isoformat()}
    save_schedule(schedule)


def main():
    settings_file = os.path.join(PROJECT_ROOT, 'settings.json')
    if not os.path.exists(settings_file):
        logger.error("settings.json nicht gefunden.")
        return

    with open(settings_file) as f:
        settings = json.load(f)

    opt_settings = settings.get('optimization_settings', {})
    if not opt_settings.get('enabled', False):
        logger.info("Automatische Optimierung deaktiviert (optimization_settings.enabled=false).")
        return

    interval_days = opt_settings.get('interval_days', 7)
    start_capital = opt_settings.get('start_capital', 1000)
    n_trials = opt_settings.get('num_trials', 100)

    active_strategies = settings.get('live_trading_settings', {}).get('active_strategies', [])

    python_executable = os.path.join(PROJECT_ROOT, '.venv', 'bin', 'python3')

    for strategy in active_strategies:
        if not strategy.get('active', False):
            continue

        symbol = strategy['symbol']
        timeframe = strategy['timeframe']

        if not should_run(symbol, timeframe, interval_days):
            logger.info(f"[{symbol} {timeframe}] Training noch nicht fällig.")
            continue

        logger.info(f"[{symbol} {timeframe}] Starte wöchentliches Re-Training + Optimierung...")

        import subprocess

        # Schritt 1: Modell trainieren
        train_cmd = [
            python_executable,
            os.path.join(PROJECT_ROOT, 'train_model.py'),
            '--symbol', symbol, '--timeframe', timeframe,
        ]
        logger.info(f"Training: {' '.join(train_cmd)}")
        result = subprocess.run(train_cmd, capture_output=True, text=True, timeout=3600)
        if result.returncode != 0:
            logger.error(f"Training fehlgeschlagen für {symbol}: {result.stderr}")
            continue

        # Schritt 2: Optimizer
        opt_cmd = [
            python_executable,
            '-m', 'dbot.analysis.optimizer',
            '--symbol', symbol, '--timeframe', timeframe,
            '--trials', str(n_trials),
            '--start-capital', str(start_capital),
        ]
        logger.info(f"Optimizer: {' '.join(opt_cmd)}")
        result = subprocess.run(opt_cmd, capture_output=True, text=True, timeout=3600,
                                cwd=PROJECT_ROOT,
                                env={**os.environ, 'PYTHONPATH': os.path.join(PROJECT_ROOT, 'src')})
        if result.returncode != 0:
            logger.error(f"Optimierung fehlgeschlagen für {symbol}: {result.stderr}")
            continue

        mark_done(symbol, timeframe)
        logger.info(f"[{symbol} {timeframe}] Re-Training + Optimierung abgeschlossen.")


if __name__ == "__main__":
    main()
