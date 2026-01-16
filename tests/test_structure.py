# tests/test_structure.py
"""
DBot Structure Tests
Testet die Projektstruktur und Importfähigkeit
"""
import os
import sys
import pytest

# Füge das Projektverzeichnis zum Python-Pfad hinzu
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

def test_project_structure():
    """Stellt sicher, dass alle erwarteten Hauptverzeichnisse existieren."""
    assert os.path.isdir(os.path.join(PROJECT_ROOT, 'src')), "Das 'src'-Verzeichnis fehlt."
    assert os.path.isdir(os.path.join(PROJECT_ROOT, 'artifacts')), "Das 'artifacts'-Verzeichnis fehlt."
    assert os.path.isdir(os.path.join(PROJECT_ROOT, 'tests')), "Das 'tests'-Verzeichnis fehlt."

def test_core_script_imports():
    """
    Stellt sicher, dass die wichtigsten Funktionen aus den Kernmodulen importiert werden können.
    """
    try:
        # Trade Manager
        from dbot.utils.trade_manager import housekeeper_routine, check_and_open_new_position, full_trade_cycle
        
        # Exchange
        from dbot.utils.exchange import Exchange
        
        # ANN Model
        from dbot.utils.ann_model import load_model_and_scaler, create_ann_features
        
        # Analysis
        from dbot.analysis.backtester import run_ann_backtest
        from dbot.analysis.optimizer import main as optimizer_main
        from dbot.analysis.portfolio_optimizer import run_portfolio_optimizer
        
        # Circuit Breaker & Guardian
        from dbot.utils.circuit_breaker import is_trading_allowed, update_circuit_breaker
        from dbot.utils.guardian import guardian_decorator
        from dbot.utils.decorators import run_with_guardian_checks
        
    except ImportError as e:
        pytest.fail(f"Kritischer Import-Fehler. Die Code-Struktur scheint defekt zu sein. Fehler: {e}")

def test_high_frequency_modules():
    """Testet spezifische DBot High-Frequency Module."""
    try:
        # Scalper Engine
        from dbot.strategy.scalper_engine import ScalperEngine
        
        # SuperTrend Indicator
        from dbot.utils.supertrend_indicator import SuperTrendLocal
        
        # Telegram
        from dbot.utils.telegram import send_message
        
    except ImportError as e:
        pytest.fail(f"High-Frequency Module konnten nicht importiert werden. Fehler: {e}")
