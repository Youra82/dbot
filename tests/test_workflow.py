# tests/test_workflow.py
"""
DBot Workflow Tests
Testet den vollständigen Trading-Workflow auf Bitget
High-Frequency Scalping
"""
import pytest
import os
import sys
import json
import logging
import time
import pandas as pd
from unittest.mock import patch

# Füge das Projektverzeichnis zum Python-Pfad hinzu
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

# Imports
from dbot.utils.exchange import Exchange
from dbot.utils.trade_manager import check_and_open_new_position, housekeeper_routine
from dbot.utils.supertrend_indicator import SuperTrendLocal
from dbot.utils.ann_model import create_ann_features

LOCK_FILE_PATH = os.path.join(PROJECT_ROOT, 'artifacts', 'db', 'trade_lock.json')

# Mock-Klassen
class FakeModel:
    """Mock-Version des Keras-Modells."""
    def __init__(self):
        self.return_value = [[0.5]]
    def predict(self, data, verbose=0):
        return self.return_value

class FakeScaler:
    """Mock-Version des Scalers."""
    def transform(self, data):
        return data

class FakeSuperTrendLocal:
    """Mock SuperTrend für Tests."""
    def __init__(self, high, low, close, window, multiplier):
        self.size = len(high)
    
    def get_supertrend_direction(self):
        # Gibt immer 1.0 (Long-Trend) zurück
        return pd.Series([1.0] * self.size)

def clear_lock_file():
    """Löscht die trade_lock.json."""
    if os.path.exists(LOCK_FILE_PATH):
        try:
            os.remove(LOCK_FILE_PATH)
            print("-> Lokale 'trade_lock.json' wurde erfolgreich gelöscht.")
        except Exception as e:
            print(f"Warnung: Lock-Datei konnte nicht gelöscht werden: {e}")

@pytest.fixture
def test_setup():
    """Bereitet die Testumgebung vor."""
    print("\n--- Starte DBot LIVE Workflow-Test (High-Frequency) ---")
    print("\n[Setup] Bereite Testumgebung vor...")

    secret_path = os.path.join(PROJECT_ROOT, 'secret.json')
    if not os.path.exists(secret_path):
        pytest.skip("secret.json nicht gefunden.")

    with open(secret_path, 'r') as f:
        secrets = json.load(f)

    if not secrets.get('dbot'):
        pytest.skip("Kein dbot Account in secret.json gefunden.")

    test_account = secrets['dbot'][0]
    telegram_config = secrets.get('telegram', {})

    exchange = Exchange(test_account)
    symbol = 'BTC/USDT:USDT'  # Für Tests

    # DBot-spezifische Parameter (Hochfrequenz)
    params = {
        'market': {'symbol': symbol, 'timeframe': '1m'},
        'strategy': {'prediction_threshold': 0.65, 'use_momentum_filter': True},
        'behavior': {'use_longs': True, 'use_shorts': True},
        'risk': {
            'risk_per_trade_pct': 1.5,       # Konservativer für HF
            'risk_reward_ratio': 2.0,
            'min_sl_pct': 0.3,              # Enger SL für 1m
            'atr_multiplier_sl': 1.5,       # Enger für HF
            'leverage': 8,
            'margin_mode': 'isolated',
            'trailing_stop_activation_rr': 1.5,
            'trailing_stop_callback_rate_pct': 0.5
        }
    }

    model = FakeModel()
    scaler = FakeScaler()

    # Initiales Aufräumen
    print("-> Führe initiales Aufräumen durch...")
    housekeeper_routine(exchange, symbol, logging.getLogger("test-logger"))
    clear_lock_file()
    print("-> Ausgangszustand ist sauber.")

    yield exchange, model, scaler, params, telegram_config, symbol

    print("\n[Teardown] Räume nach dem Test auf...")
    try:
        housekeeper_routine(exchange, symbol, logging.getLogger("test-logger"))
        final_pos_check = exchange.fetch_open_positions(symbol)
        if final_pos_check:
            print("WARNUNG: Position nach Teardown noch offen.")
    except Exception as e:
        print(f"Fehler beim Aufräumen: {e}")

    clear_lock_file()

def test_full_dbot_workflow_on_bitget(test_setup):
    """
    Testet den gesamten High-Frequency Trading Workflow.
    """
    exchange, model, scaler, params, telegram_config, symbol = test_setup
    logger = logging.getLogger("test-logger")
    
    # Mock Daten
    DATE_LEN = 100
    SAFE_LEN = 50
    BTC_PRICE = 30000.0
    
    # OHLCV Mock
    start_dt = '2025-01-01 00:00:00'
    date_range = pd.date_range(start=start_dt, periods=DATE_LEN, freq='1min')
    ohlcv_mock_data = {
        'open': [BTC_PRICE] * DATE_LEN,
        'high': [BTC_PRICE + 200] * DATE_LEN,  # Kleinere Range für 1m
        'low': [BTC_PRICE - 200] * DATE_LEN,
        'close': [BTC_PRICE] * DATE_LEN,
        'volume': [1000] * DATE_LEN
    }
    mock_ohlcv_df = pd.DataFrame(ohlcv_mock_data, index=date_range)

    # Features Mock
    model.return_value = [[0.9]]  # Starkes Long-Signal
    feature_cols = [
        'bb_width', 'obv', 'rsi', 'macd_diff', 'day_of_week',
        'returns_lag1', 'returns_lag2', 'atr_normalized', 'adx',
        'mfi', 'stoch_k', 'williams_r', 'roc', 'cci'
    ]
    fake_data = {col: [0.0] * SAFE_LEN for col in feature_cols}
    fake_data['adx'] = [30.0] * SAFE_LEN  # Über Threshold
    fake_data['rsi'] = [50.0] * SAFE_LEN  # Neutral
    fake_data['high'] = [BTC_PRICE + 200] * SAFE_LEN
    fake_data['low'] = [BTC_PRICE - 200] * SAFE_LEN
    fake_data['close'] = [BTC_PRICE] * SAFE_LEN
    fake_data['volume'] = [1000] * SAFE_LEN
    fake_data['atr'] = [200.0] * SAFE_LEN  # Kleinerer ATR für 1m
    
    index_range = pd.date_range(start='2025-01-01', periods=SAFE_LEN, freq='1min')
    fake_features_df = pd.DataFrame(fake_data, index=index_range)
    
    # User Balance
    USER_BALANCE = 25.0
    
    with patch('dbot.utils.exchange.Exchange.fetch_balance_usdt', return_value=USER_BALANCE):
        with patch('dbot.utils.trade_manager.create_ann_features', return_value=fake_features_df):
            with patch('dbot.utils.exchange.Exchange.fetch_recent_ohlcv', return_value=mock_ohlcv_df):
                with patch('dbot.utils.trade_manager.SuperTrendLocal', new=FakeSuperTrendLocal):
                    
                    print(f"\n[Schritt 1/3] Prüfe Trade-Eröffnung ({symbol}) mit {USER_BALANCE} USDT...")
                    check_and_open_new_position(exchange, model, scaler, params, telegram_config, logger)
                    time.sleep(5)

    print("\n[Schritt 2/3] Überprüfe Position und Orders...")
    position = exchange.fetch_open_positions(symbol)
    trigger_orders = exchange.fetch_open_trigger_orders(symbol)

    assert position, "FEHLER: Position wurde nicht eröffnet!"
    assert position[0]['marginMode'] == 'isolated', f"FEHLER: Falscher Margin-Modus: {position[0]['marginMode']}"
    print(f"-> ✔ Position korrekt eröffnet (Isolated, {position[0]['leverage']}x).")

    assert len(trigger_orders) >= 1, f"FEHLER: Mindestens 1 SL-Order erforderlich. Gefunden: {len(trigger_orders)}"
    print(f"-> ✔ {len(trigger_orders)} SL/TSL-Order(s) platziert.")

    print("\n[Schritt 3/3] Test erfolgreich!")
    print("\n--- ✅ DBOT HIGH-FREQUENCY WORKFLOW-TEST ERFOLGREICH! ---")
