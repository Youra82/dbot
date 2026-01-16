# src/dbot/strategy/run.py
"""
DBot - High-Frequency Momentum Scalper
Aggressive Strategie für 500% ROI in 5 Tagen
"""
import sys
import os
import json
import time
from datetime import datetime

# Path setup
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '../../..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.utils.exchange import Exchange
from dbot.utils.telegram_notifier import TelegramNotifier
from dbot.strategy.scalper_engine import ScalperEngine


def load_configs():
    """Lade Konfigurationsdateien"""
    settings_file = os.path.join(PROJECT_ROOT, 'settings.json')
    secret_file = os.path.join(PROJECT_ROOT, 'secret.json')
    
    with open(settings_file, 'r') as f:
        settings = json.load(f)
    
    with open(secret_file, 'r') as f:
        secrets = json.load(f)
    
    return settings, secrets


def run_strategy(symbol: str, timeframe: str, use_momentum_filter: bool):
    """
    Führe die aggressive Scalping-Strategie aus
    
    Args:
        symbol: Trading-Paar (z.B. 'BTC/USDT:USDT')
        timeframe: Zeitrahmen (z.B. '5m')
        use_momentum_filter: Momentum-Filter aktivieren
    """
    print(f"\n{'='*70}")
    print(f"🚀 DBot Scalper gestartet")
    print(f"📊 Symbol: {symbol}")
    print(f"⏱️  Timeframe: {timeframe}")
    print(f"🎯 Momentum Filter: {'Aktiv' if use_momentum_filter else 'Inaktiv'}")
    print(f"{'='*70}\n")
    
    settings, secrets = load_configs()
    
    # Exchange initialisieren
    account_config = secrets['dbot'][0]
    exchange = Exchange(
        exchange_id=account_config['exchange'],
        api_key=account_config['api_key'],
        api_secret=account_config['secret'],
        password=account_config.get('password', '')
    )
    
    # Telegram Notifier
    notifier = TelegramNotifier() if 'telegram' in secrets else None
    
    # Scalper Engine initialisieren
    engine = ScalperEngine(
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        settings=settings,
        notifier=notifier,
        use_momentum_filter=use_momentum_filter
    )
    
    try:
        # Hauptloop
        while True:
            try:
                # Führe Trading-Logik aus
                engine.execute_trading_cycle()
                
                # Kurze Pause (1 Minute bei 5m Timeframe)
                sleep_time = 60
                if timeframe == '1m':
                    sleep_time = 30
                
                time.sleep(sleep_time)
                
            except KeyboardInterrupt:
                print("\n⚠️  Bot durch Benutzer gestoppt")
                break
            except Exception as e:
                print(f"❌ Fehler im Trading-Cycle: {e}")
                if notifier:
                    notifier.send_error(f"DBot Error ({symbol}): {e}")
                time.sleep(60)  # 1 Minute warten bei Fehler
                
    finally:
        print(f"\n{'='*70}")
        print(f"🛑 DBot Scalper gestoppt für {symbol}")
        print(f"{'='*70}\n")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python run.py <symbol> <timeframe> [use_momentum_filter]")
        print("Example: python run.py BTC/USDT:USDT 5m true")
        sys.exit(1)
    
    symbol = sys.argv[1]
    timeframe = sys.argv[2]
    use_momentum_filter = sys.argv[3].lower() == 'true' if len(sys.argv) > 3 else True
    
    run_strategy(symbol, timeframe, use_momentum_filter)
