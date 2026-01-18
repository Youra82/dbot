"""Backtester für die DBot Physics-Strategie.

Vereinfacht aus der UtBot2-Variante abgeleitet, nutzt jedoch die
PhysicsEngine und die physics-basierte Trade-Logik.
"""

import os
import pandas as pd
import numpy as np
import json
import sys
from tqdm import tqdm
import math

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.utils.exchange import Exchange
from dbot.strategy.physics_engine import PhysicsEngine
from dbot.strategy.trade_logic import (
    get_physics_signal,
    get_stop_loss_take_profit,
    should_close_position,
)

secrets_cache = None
htf_cache = {}  # Cache für HTF-Daten um wiederholtes Laden zu vermeiden

class Bias:
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"

def load_data(symbol, timeframe, start_date_str, end_date_str):
    global secrets_cache
    data_dir = os.path.join(PROJECT_ROOT, 'data')
    cache_dir = os.path.join(data_dir, 'cache')
    symbol_filename = symbol.replace('/', '-').replace(':', '-')
    cache_file = os.path.join(cache_dir, f"{symbol_filename}_{timeframe}.csv")
    
    try:
        if not os.path.exists(data_dir): os.makedirs(data_dir)
        os.makedirs(cache_dir, exist_ok=True)
    except OSError: return pd.DataFrame()

    if os.path.exists(cache_file):
        try:
            data = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
            data_start = data.index.min(); data_end = data.index.max()
            req_start = pd.to_datetime(start_date_str, utc=True); req_end = pd.to_datetime(end_date_str, utc=True)
            if data_start <= req_start and data_end >= req_end:
                return data.loc[req_start:req_end]
        except Exception:
            try: os.remove(cache_file)
            except OSError: pass

    try:
        if secrets_cache is None:
            with open(os.path.join(PROJECT_ROOT, 'secret.json'), "r") as f:
                secrets_cache = json.load(f)

        # Bevorzugt DBot-Account; toleriert alten utbot2-Schlüssel nur noch als Fallback
        if 'dbot' in secrets_cache:
            api_setup = secrets_cache['dbot'][0]
        elif 'utbot2' in secrets_cache:
            # Deprecated: bitte secret.json auf "dbot" umstellen
            api_setup = secrets_cache['utbot2'][0]
        elif 'titanbot' in secrets_cache:
            api_setup = secrets_cache['titanbot'][0]
        else:
            return pd.DataFrame()
        
        exchange = Exchange(api_setup)
        if not exchange.markets: return pd.DataFrame()
        
        full_data = exchange.fetch_historical_ohlcv(symbol, timeframe, start_date_str, end_date_str)
        if not full_data.empty:
            full_data.to_csv(cache_file)
            req_start_dt = pd.to_datetime(start_date_str, utc=True)
            req_end_dt = pd.to_datetime(end_date_str, utc=True)
            return full_data.loc[req_start_dt:req_end_dt]
        return pd.DataFrame()
    except Exception: return pd.DataFrame()
def run_backtest(data, strategy_params, risk_params, start_capital=1000, verbose=False):
    """Backtest für die Physics-Strategie.

    Nutzt PhysicsEngine + get_physics_signal + ATR-basiertes Risiko-Management
    (ähnlich wie im Live-Trade-Manager, aber auf vereinfachter Basis).
    """

    if data.empty or len(data) < 60:
        return {
            "total_pnl_pct": -100,
            "trades_count": 0,
            "win_rate": 0,
            "max_drawdown_pct": 1.0,
            "end_capital": start_capital,
        }

    symbol = strategy_params.get('symbol', '')
    timeframe = strategy_params.get('timeframe', '')

    # Physics-Indikatoren berechnen
    engine = PhysicsEngine(settings=strategy_params)
    processed_data = engine.process_dataframe(data)

    # Setup-Flags ergänzen
    processed_data['impulse_pullback_setup'] = engine.detect_impulse_pullback(processed_data)
    processed_data['volatility_expansion_setup'] = engine.detect_volatility_expansion(processed_data)

    processed_data.dropna(subset=['atr'], inplace=True)
    if processed_data.empty:
        return {
            "total_pnl_pct": -100,
            "trades_count": 0,
            "win_rate": 0,
            "max_drawdown_pct": 1.0,
            "end_capital": start_capital,
        }

    current_capital = start_capital
    peak_capital = start_capital
    max_drawdown_pct = 0.0
    trades_count = 0
    wins_count = 0
    position = None

    # Risiko-Parameter
    risk_reward_ratio = risk_params.get('risk_reward_ratio', 2.0)
    risk_per_trade_pct = risk_params.get('risk_per_trade_pct', 1.0) / 100.0
    activation_rr = risk_params.get('trailing_stop_activation_rr', 2.0)
    callback_rate = risk_params.get('trailing_stop_callback_rate_pct', 1.0) / 100.0
    leverage = risk_params.get('leverage', 5)
    fee_pct = 0.05 / 100.0

    absolute_max_notional_value = 1_000_000
    max_allowed_effective_leverage = 10

    params_for_logic = {"strategy": strategy_params, "risk": risk_params}

    for timestamp, current_candle in processed_data.iterrows():
        if current_capital <= 0:
            break

        # --- Positions-Management ---
        if position is not None:
            exit_price = None

            # Trailing / SL / TP
            if position['side'] == 'long':
                if not position['trailing_active'] and current_candle['high'] >= position['activation_price']:
                    position['trailing_active'] = True
                if position['trailing_active']:
                    position['peak_price'] = max(position['peak_price'], current_candle['high'])
                    trailing_sl = position['peak_price'] * (1 - callback_rate)
                    position['stop_loss'] = max(position['stop_loss'], trailing_sl)
                if current_candle['low'] <= position['stop_loss']:
                    exit_price = position['stop_loss']
                elif not position['trailing_active'] and current_candle['high'] >= position['take_profit']:
                    exit_price = position['take_profit']
            else:  # short
                if not position['trailing_active'] and current_candle['low'] <= position['activation_price']:
                    position['trailing_active'] = True
                if position['trailing_active']:
                    position['peak_price'] = min(position['peak_price'], current_candle['low'])
                    trailing_sl = position['peak_price'] * (1 + callback_rate)
                    position['stop_loss'] = min(position['stop_loss'], trailing_sl)
                if current_candle['high'] >= position['stop_loss']:
                    exit_price = position['stop_loss']
                elif not position['trailing_active'] and current_candle['low'] <= position['take_profit']:
                    exit_price = position['take_profit']

            # Zusätzliche Exit-Logik aus Physics-Strategie
            if exit_price is None:
                data_slice = processed_data.loc[:timestamp]
                pos_side_label = 'buy' if position['side'] == 'long' else 'sell'
                if should_close_position(data_slice, pos_side_label, position['entry_price'], params_for_logic):
                    exit_price = current_candle['close']

            if exit_price is not None:
                pnl_pct = (
                    exit_price / position['entry_price'] - 1
                    if position['side'] == 'long'
                    else 1 - exit_price / position['entry_price']
                )
                notional_value = position['notional_value']
                pnl_usd = notional_value * pnl_pct
                total_fees = notional_value * fee_pct * 2
                current_capital += (pnl_usd - total_fees)
                if (pnl_usd - total_fees) > 0:
                    wins_count += 1
                trades_count += 1
                position = None
                peak_capital = max(peak_capital, current_capital)
                if peak_capital > 0:
                    drawdown = (peak_capital - current_capital) / peak_capital
                    max_drawdown_pct = max(max_drawdown_pct, drawdown)

        # --- Einstiegs-Logik ---
        if position is None and current_capital > 0:
            data_slice = processed_data.loc[:timestamp]
            market_bias = Bias.NEUTRAL  # Für den Backtest ohne HTF-Bias
            side, signal_price = get_physics_signal(data_slice, current_candle, params_for_logic, market_bias)

            if side:
                entry_price = current_candle['close']
                current_atr = current_candle.get('atr', 0)
                if current_atr <= 0:
                    continue

                # SL/TP aus Physics-Logik berechnen
                sl_price, tp_price = get_stop_loss_take_profit(data_slice, side, entry_price, params_for_logic)
                if sl_price is None or tp_price is None:
                    continue

                sl_dist = abs(entry_price - sl_price)
                if sl_dist <= 0:
                    continue

                risk_amount_usd = current_capital * risk_per_trade_pct
                sl_pct = sl_dist / entry_price
                if sl_pct <= 0:
                    continue

                calc_notional = risk_amount_usd / sl_pct
                max_notional = current_capital * max_allowed_effective_leverage
                final_notional = min(calc_notional, max_notional, absolute_max_notional_value)

                margin_needed = final_notional / leverage
                if margin_needed > current_capital or final_notional <= 0:
                    continue

                if side == 'buy':
                    act = entry_price + sl_dist * activation_rr
                    pos_side = 'long'
                else:
                    act = entry_price - sl_dist * activation_rr
                    pos_side = 'short'

                position = {
                    'side': pos_side,
                    'entry_price': entry_price,
                    'stop_loss': sl_price,
                    'take_profit': tp_price,
                    'margin_used': margin_needed,
                    'notional_value': final_notional,
                    'trailing_active': False,
                    'activation_price': act,
                    'peak_price': entry_price,
                }

    win_rate = (wins_count / trades_count * 100) if trades_count > 0 else 0
    final_pnl_pct = (
        (current_capital - start_capital) / start_capital * 100
        if start_capital > 0
        else 0
    )
    final_capital = max(0, current_capital)

    return {
        "total_pnl_pct": final_pnl_pct,
        "trades_count": trades_count,
        "win_rate": win_rate,
        "max_drawdown_pct": max_drawdown_pct,
        "end_capital": final_capital,
    }
