# src/dbot/utils/circuit_breaker.py
"""
Circuit Breaker für Drawdown-Management im DBot.
Stoppt Trading automatisch bei zu hohen Verlusten.
Angepasst für hochfrequenten Trading mit schärferen Limits.
"""

import os
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
CIRCUIT_BREAKER_FILE = os.path.join(PROJECT_ROOT, 'artifacts', 'db', 'circuit_breaker.json')


def get_circuit_breaker_status():
    """Liest den Circuit Breaker Status."""
    if not os.path.exists(CIRCUIT_BREAKER_FILE):
        return {
            'tripped': False,
            'peak_equity': 0,
            'current_equity': 0,
            'daily_loss': 0,
            'weekly_loss': 0,
            'last_reset': datetime.now().isoformat()
        }
    
    try:
        with open(CIRCUIT_BREAKER_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {'tripped': False, 'peak_equity': 0}


def update_circuit_breaker(current_equity, peak_equity=None):
    """
    Prüft Drawdown-Limits und aktiviert Circuit Breaker wenn nötig.
    Für DBot: Schärfere Limits wegen hochfrequentem Trading.
    
    Returns:
        str: 'OK', 'REDUCE_SIZE', 'STOP_ALL_TRADING'
    """
    status = get_circuit_breaker_status()
    
    # Update Peak Equity
    if peak_equity is None:
        peak_equity = max(status.get('peak_equity', current_equity), current_equity)
    
    # Berechne Drawdown
    if peak_equity > 0:
        drawdown_pct = (peak_equity - current_equity) / peak_equity
    else:
        drawdown_pct = 0
    
    # Update Status
    status['current_equity'] = current_equity
    status['peak_equity'] = peak_equity
    status['drawdown_pct'] = drawdown_pct
    status['last_update'] = datetime.now().isoformat()
    
    result = 'OK'
    
    # LEVEL 1: 3% Drawdown - Warnung (schärfer als JaegerBot)
    if drawdown_pct > 0.03:
        logger.warning(f"⚠️  WARNUNG: 3% Drawdown erreicht! ({drawdown_pct*100:.2f}%)")
        result = 'REDUCE_SIZE'
        # Persistente Markierung: Positionsgrößenreduktion aktivieren
        status['reduced'] = True
        status['reduction_factor'] = status.get('reduction_factor', 0.5)

    # Wenn Drawdown wieder unter 2.5% fällt, entferne die Reduktion (Auto-Restore)
    if status.get('reduced') and drawdown_pct < 0.025:
        logger.info(f"ℹ️  Drawdown unter 2.5% ({drawdown_pct*100:.2f}%), hebe Positionsgrößenreduktion auf.")
        status['reduced'] = False
        status.pop('reduction_factor', None)
    
    # LEVEL 2: 7% Drawdown - Circuit Breaker (schärfer als JaegerBot)
    if drawdown_pct > 0.07:
        logger.critical(f"🚨 CIRCUIT BREAKER AKTIVIERT: 7% Drawdown erreicht! ({drawdown_pct*100:.2f}%)")
        status['tripped'] = True
        status['tripped_at'] = datetime.now().isoformat()
        status['trip_reason'] = f'Drawdown: {drawdown_pct*100:.2f}%'
        result = 'STOP_ALL_TRADING'
    
    # Speichere Status
    os.makedirs(os.path.dirname(CIRCUIT_BREAKER_FILE), exist_ok=True)
    with open(CIRCUIT_BREAKER_FILE, 'w') as f:
        json.dump(status, f, indent=4)
    
    return result


def reset_circuit_breaker():
    """Setzt den Circuit Breaker zurück (nur manuell)."""
    status = get_circuit_breaker_status()
    status['tripped'] = False
    status['reset_at'] = datetime.now().isoformat()
    
    with open(CIRCUIT_BREAKER_FILE, 'w') as f:
        json.dump(status, f, indent=4)
    
    logger.info("✅ Circuit Breaker wurde zurückgesetzt.")


def check_daily_loss_limit(current_pnl_today, daily_limit_pct=0.02):
    """
    Prüft ob tägliches Verlust-Limit erreicht wurde.
    Für DBot: 2% tägliches Limit (schärfer als JaegerBot's 3%).
    
    Args:
        current_pnl_today: PnL des heutigen Tages
        daily_limit_pct: Max Verlust pro Tag (default 2%)
    
    Returns:
        bool: True wenn Limit überschritten
    """
    status = get_circuit_breaker_status()
    peak = status.get('peak_equity', 1000)
    
    loss_limit = peak * daily_limit_pct
    
    if current_pnl_today < -loss_limit:
        logger.critical(f"🚨 TÄGLICHES VERLUST-LIMIT ERREICHT: {current_pnl_today:.2f} USDT")
        status['tripped'] = True
        status['trip_reason'] = f'Daily Loss: {current_pnl_today:.2f} USDT'
        
        with open(CIRCUIT_BREAKER_FILE, 'w') as f:
            json.dump(status, f, indent=4)
        
        return True
    
    return False


def is_trading_allowed():
    """Prüft ob Trading erlaubt ist (Circuit Breaker nicht ausgelöst)."""
    status = get_circuit_breaker_status()
    return not status.get('tripped', False)
