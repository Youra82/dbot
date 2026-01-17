"""
Simplified Backtester for Scalper Strategy
No ANN/ML dependencies - pure scalping logic
"""

import os
import sys
import json
import pandas as pd
import numpy as np
import ta
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

from dbot.utils.exchange import Exchange


def load_account_config():
    secret_path = os.path.join(PROJECT_ROOT, 'secret.json')
    if not os.path.exists(secret_path):
        raise FileNotFoundError("secret.json not found")
    with open(secret_path, 'r') as f:
        secrets = json.load(f)
    api_setup = secrets.get('dbot', [None])[0]
    if not api_setup:
        raise ValueError("No dbot account in secret.json")
    return {
        'apiKey': api_setup.get('apiKey') or api_setup.get('api_key', ''),
        'secret': api_setup.get('secret', ''),
        'password': api_setup.get('password', '')
    }


def fetch_ohlcv(symbol, timeframe, start_date, end_date):
    """Download OHLCV data from exchange"""
    try:
        account_config = load_account_config()
        exchange = Exchange(account_config)
        df = exchange.fetch_historical_ohlcv(symbol, timeframe, start_date, end_date)
        if df is None or df.empty:
            return pd.DataFrame()
        return df
    except Exception as e:
        print(f"ERROR fetching data: {e}")
        return pd.DataFrame()


def get_scalp_signal(df: pd.DataFrame, params: dict) -> tuple:
    """
    Generate scalping signal
    Returns: (side, entry_price, confidence)
    """
    if len(df) < 50:
        return None, None, 0.0
    
    df = df.copy()
    current = df.iloc[-1]
    close = current['close']
    
    # Parameters
    rsi_period = params.get('rsi_period', 14)
    rsi_oversold = params.get('rsi_oversold', 30)
    rsi_overbought = params.get('rsi_overbought', 70)
    ema_fast = params.get('ema_fast', 5)
    ema_slow = params.get('ema_slow', 20)
    min_confidence = params.get('min_confidence', 0.5)
    roc_threshold = params.get('roc_threshold', 0.2)
    
    # Indicators
    rsi = ta.momentum.rsi(df['close'], window=rsi_period)
    current_rsi = rsi.iloc[-1]
    prev_rsi = rsi.iloc[-2] if len(rsi) > 1 else current_rsi
    
    ema_fast_val = ta.trend.ema_indicator(df['close'], window=ema_fast)
    ema_slow_val = ta.trend.ema_indicator(df['close'], window=ema_slow)
    
    current_ema_fast = ema_fast_val.iloc[-1]
    current_ema_slow = ema_slow_val.iloc[-1]
    prev_ema_fast = ema_fast_val.iloc[-2] if len(ema_fast_val) > 1 else current_ema_fast
    prev_ema_slow = ema_slow_val.iloc[-2] if len(ema_slow_val) > 1 else current_ema_slow
    
    roc = ta.momentum.roc(df['close'], window=5)
    current_roc = roc.iloc[-1]
    
    bb_indicator = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
    bb_high = bb_indicator.bollinger_hband().iloc[-1]
    bb_low = bb_indicator.bollinger_lband().iloc[-1]
    
    # BUY SIGNAL
    buy_signal = False
    buy_confidence = 0.0
    
    if (current_rsi <= rsi_oversold) and (prev_rsi > rsi_oversold):
        buy_signal = True
        buy_confidence += 0.4
    
    if (current_ema_fast > current_ema_slow) and (prev_ema_fast <= prev_ema_slow):
        buy_signal = True
        buy_confidence += 0.35
    
    if current_roc > roc_threshold:
        buy_confidence += 0.25
    
    if close <= bb_low * 1.005:
        buy_confidence += 0.15
    
    if current_rsi < 50:
        buy_confidence += 0.1
    
    # SELL SIGNAL
    sell_signal = False
    sell_confidence = 0.0
    
    if (current_rsi >= rsi_overbought) and (prev_rsi < rsi_overbought):
        sell_signal = True
        sell_confidence += 0.4
    
    if (current_ema_fast < current_ema_slow) and (prev_ema_fast >= prev_ema_slow):
        sell_signal = True
        sell_confidence += 0.35
    
    if current_roc < -roc_threshold:
        sell_confidence += 0.25
    
    if close >= bb_high * 0.995:
        sell_confidence += 0.15
    
    if current_rsi > 50:
        sell_confidence += 0.1
    
    # Decide
    if buy_signal and sell_signal:
        if buy_confidence > sell_confidence:
            return 'buy', close, min(buy_confidence, 1.0)
        else:
            return 'sell', close, min(sell_confidence, 1.0)
    
    if buy_signal and buy_confidence >= min_confidence:
        return 'buy', close, min(buy_confidence, 1.0)
    
    if sell_signal and sell_confidence >= min_confidence:
        return 'sell', close, min(sell_confidence, 1.0)
    
    return None, None, 0.0


def simulate_smc_backtest(df, params):
    """Simulate scalping backtest"""
    if df is None or df.empty or len(df) < 100:
        return {"error": "Insufficient data"}
    
    df = df.copy()
    
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df.set_index('timestamp', inplace=True)
    elif not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    
    # Add ATR
    atr_indicator = ta.volatility.AverageTrueRange(
        high=df['high'], low=df['low'], close=df['close'], window=14
    )
    df['atr'] = atr_indicator.average_true_range()
    
    start_capital = params.get('start_capital', 1000.0)
    equity = start_capital
    peak_equity = start_capital
    max_dd = 0.0
    fee_pct = 0.0005
    
    position = None
    trades = []
    equity_curve = []
    liquidated = False
    
    lookback = 50
    
    for idx in range(lookback, len(df)):
        window = df.iloc[:idx + 1]
        current = window.iloc[-1]
        
        # Position management
        if position:
            exit_price = None
            if position['side'] == 'long':
                if current['low'] <= position['stop_loss']:
                    exit_price = position['stop_loss']
                elif current['high'] >= position['take_profit']:
                    exit_price = position['take_profit']
            else:
                if current['high'] >= position['stop_loss']:
                    exit_price = position['stop_loss']
                elif current['low'] <= position['take_profit']:
                    exit_price = position['take_profit']
            
            if exit_price:
                pnl_pct = (exit_price / position['entry_price'] - 1) if position['side'] == 'long' else (1 - exit_price / position['entry_price'])
                notional = position['notional']
                pnl_usd = notional * pnl_pct
                total_fees = notional * fee_pct * 2
                net_pnl = pnl_usd - total_fees
                equity = max(0, equity + net_pnl)
                
                trades.append({
                    'side': position['side'],
                    'entry': position['entry_price'],
                    'exit': exit_price,
                    'pnl_usd': net_pnl
                })
                position = None
                peak_equity = max(peak_equity, equity)
                if peak_equity > 0:
                    dd = (peak_equity - equity) / peak_equity
                    max_dd = max(max_dd, dd)
                if equity <= 0:
                    liquidated = True
                    break
        
        # Entry signal
        if position is None:
            signal_side, signal_price, confidence = get_scalp_signal(window, params)
            
            if signal_side:
                entry_price = signal_price or current['close']
                current_atr = current.get('atr')
                if pd.isna(current_atr) or current_atr <= 0:
                    continue
                
                # Simple position sizing
                leverage = 2.0
                max_notional = equity * leverage
                sl_distance = max(current_atr * 0.5, entry_price * 0.002)
                if sl_distance <= 0:
                    continue
                
                notional = min(equity * 0.5, max_notional)
                if notional <= 0:
                    continue
                
                if signal_side == 'buy':
                    sl_price = entry_price - sl_distance
                    tp_price = entry_price + sl_distance * 3.0
                else:
                    sl_price = entry_price + sl_distance
                    tp_price = entry_price - sl_distance * 3.0
                
                position = {
                    'side': 'long' if signal_side == 'buy' else 'short',
                    'entry_price': entry_price,
                    'stop_loss': sl_price,
                    'take_profit': tp_price,
                    'notional': notional
                }
        
        equity_curve.append({
            'timestamp': current.name,
            'equity': equity
        })
    
    trades_count = len(trades)
    wins = sum(1 for t in trades if t['pnl_usd'] > 0)
    win_rate = (wins / trades_count * 100) if trades_count else 0
    pnl_pct = ((equity - start_capital) / start_capital * 100) if start_capital else 0
    
    return {
        'final_equity': equity,
        'start_equity': start_capital,
        'pnl_pct': pnl_pct,
        'trades': trades,
        'trades_count': trades_count,
        'win_rate': win_rate,
        'max_drawdown_pct': max_dd * 100,
        'equity_curve': equity_curve,
        'liquidated': liquidated
    }
