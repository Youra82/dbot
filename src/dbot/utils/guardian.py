# src/dbot/utils/guardian.py
import logging
from functools import wraps
from dbot.utils.telegram import send_message

def guardian_decorator(func):
    """
    Decorator, der eine Funktion umschließt, um alle unerwarteten
    Ausnahmen abzufangen, sie zu protokollieren und eine Telegram-Warnung zu senden.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger = None
        telegram_config = {}
        params = {}

        for arg in args:
            if isinstance(arg, logging.Logger):
                logger = arg
            if isinstance(arg, dict) and 'bot_token' in arg:
                telegram_config = arg
            if isinstance(arg, dict) and 'market' in arg:
                params = arg

        if not logger:
            logger = logging.getLogger("guardian_fallback")
            logger.setLevel(logging.ERROR)
            if not logger.handlers:
                logger.addHandler(logging.StreamHandler())

        try:
            return func(*args, **kwargs)

        except Exception as e:
            symbol = params.get('market', {}).get('symbol', 'Unbekannt')
            timeframe = params.get('market', {}).get('timeframe', 'N/A')

            logger.critical("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            logger.critical("!!! KRITISCHER SYSTEMFEHLER IM GUARDIAN !!!")
            logger.critical(f"!!! Strategie: {symbol} ({timeframe})")
            logger.critical(f"!!! Fehler: {e}", exc_info=True)
            logger.critical("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

            try:
                telegram_message = f"KRITISCHER SYSTEMFEHLER im dbot Guardian für {symbol} ({timeframe}):\n\n{e.__class__.__name__}: {e}\n\nDer Prozess wird neu gestartet."
                send_message(
                    telegram_config.get('bot_token'),
                    telegram_config.get('chat_id'),
                    telegram_message
                )
            except Exception as tel_e:
                logger.error(f"Konnte keine Telegram-Fehlermeldung senden: {tel_e}")

            raise e

    return wrapper
