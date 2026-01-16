# src/dbot/utils/decorators.py
"""
Decorators für DBot
Pre-Flight Checks und Guardian-Integration
"""
from functools import wraps
from .telegram import send_message

class PreFlightCheckError(Exception):
    """Exception für fehlgeschlagene Pre-Flight Checks"""
    pass

def run_with_guardian_checks(func):
    """
    Ein Decorator, der sicherstellt, dass die Guardian Pre-Flight-Checks
    bestanden werden, bevor die eigentliche Bot-Logik ausgeführt wird.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Der Decorator extrahiert die benötigten Argumente aus dem Aufruf
        # der dekorierten Funktion (run_for_account).
        account = args[0]
        telegram_config = args[1]
        params = args[2]
        logger = args[5]
        model_path = args[6]
        scaler_path = args[7]
        
        account_name = account.get('name', 'Standard-Account')
        symbol = params['market']['symbol']
        
        try:
            # Die Exchange-Instanz wird hier nur für den Guardian erstellt
            from .exchange import Exchange
            exchange = Exchange(account)

            # 1. Grundlegende Pre-Flight Checks
            # Balance Check
            balance = exchange.fetch_balance_usdt()
            if balance <= 0:
                raise PreFlightCheckError(f"Keine Balance verfügbar: {balance} USDT")
            
            # Model/Scaler Check
            import os
            if not os.path.exists(model_path):
                raise PreFlightCheckError(f"Model nicht gefunden: {model_path}")
            if not os.path.exists(scaler_path):
                raise PreFlightCheckError(f"Scaler nicht gefunden: {scaler_path}")
            
            # Circuit Breaker Check
            from .circuit_breaker import is_trading_allowed
            if not is_trading_allowed():
                raise PreFlightCheckError("Circuit Breaker ist aktiv - Trading gestoppt")
            
            logger.info(f"✅ Pre-Flight Checks bestanden für {symbol}")

            # 2. Nur wenn alle Checks bestehen, wird die ursprüngliche Funktion ausgeführt
            return func(*args, **kwargs)

        except PreFlightCheckError as e:
            # 3. Wenn der Guardian Alarm schlägt, wird eine Nachricht gesendet
            #    und die Funktion sicher abgebrochen.
            logger.critical(f"Guardian hat den Start für {account_name} ({symbol}) verhindert.")
            message = f"🚨 *DBot Gestoppt* ({symbol})\n\nGrund: Pre-Flight-Check fehlgeschlagen!\n\n_{e}_"
            send_message(telegram_config.get('bot_token'), telegram_config.get('chat_id'), message)
        
        except Exception as e:
            logger.critical(f"Ein kritischer Fehler ist im Guardian-Decorator aufgetreten: {e}", exc_info=True)
            message = f"🚨 *Kritischer Systemfehler* im DBot Guardian-Decorator für {symbol}."
            send_message(telegram_config.get('bot_token'), telegram_config.get('chat_id'), message)
            
    return wrapper
